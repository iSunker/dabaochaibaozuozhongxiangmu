#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""reseed-state —— 单片状态机 CLI（登记 / 同步 / 汇报 / 待办 / 驱动重搜）。

它**只读** cross-seed 的库与日志、以及 qB 的 API；唯一被写的是我们自己的
sidecar 状态库（默认 `hlink/state.db`，可用 --db 或 RESEED_STATE_DB 覆盖）。

重搜周期
--------
「每站一周搜一次」是默认行为：cross-seed 的 `timestamp` 表里记着
**每个 searchee 在每个索引器上最后一次搜索的时间**，`todo` 就按它逐站比周期。
想改：`--cadence-days 14`，或 `--cadence "SiteA=7,SiteB=30"` 给单个站单独设。

常用流程
--------
    # 1) 登记大包（可反复跑，不会重置已有状态）
    python scripts/reseed-state.py init --pack frds-top250-2024 \\
        --root /volume1/video/download/movies/DouBan_IMDB.TOP250.Movies.Mixed.Collection.20240501.FRDS \\
        --local-root //YOUR-NAS/video/download/movies/DouBan_IMDB.TOP250.Movies.Mixed.Collection.20240501.FRDS

    # 2) 同步：把 cross-seed.db + 日志 + qB 的事实翻译成"每部到哪一步了"
    python scripts/reseed-state.py sync --pack frds-top250-2024 \\
        --db-path  //YOUR-NAS/docker_ssd/prowlarr_cross-seed_autohardlink/cross-seed/cross-seed.db \\
        --log //YOUR-NAS/docker_ssd/prowlarr_cross-seed_autohardlink/cross-seed/logs/info.current.log \\
        --qbit-url http://NAS_IP:3060

    # 3) 看还剩多少没搜 / 每站下次什么时候能重搜
    python scripts/reseed-state.py report --pack frds-top250-2024

    # 4) 导出"该搜但没搜"的清单
    python scripts/reseed-state.py todo --pack frds-top250-2024 \\
        --indexers SiteA,SiteB --out scripts/todo.txt

    # 5) 驱动重搜：控速 + 退避感知 + 打完自动回灌（默认 dry-run，加 --apply 才发）
    python scripts/reseed-state.py drive --pack frds-top250-2024 --apply \\
        --url http://NAS_IP:2468 --api-key <CROSSSEED_API_KEY> \\
        --db-path <cross-seed.db> --log <info.current.log> --qbit-url http://NAS_IP:3060

设计要点见 orchestrator/state.py 顶部的注释。
"""
from __future__ import annotations

import argparse
import os
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from orchestrator import state as S  # noqa: E402

DEFAULT_DB = os.environ.get("RESEED_STATE_DB", str(REPO / "hlink" / "state.db"))


def _say(*a) -> None:
    print(*a, flush=True)


def _note(*a) -> None:
    """走 stderr：用于分批说明等提示，避免污染 todo 的路径清单输出。"""
    print(*a, file=sys.stderr, flush=True)


def _safe_stdout() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    except Exception:  # noqa: BLE001
        pass


def _list_dirs(root: str, pattern: str = "*", exclude: list[str] | None = None) -> list[str]:
    """列出包内子目录（跳过隐藏目录与 @eaDir）。exclude 支持 glob。"""
    excl = [p for p in (exclude or []) if p]
    out = []
    with os.scandir(root) as it:
        for e in it:
            if not e.is_dir(follow_symlinks=False):
                continue
            n = e.name
            if n.startswith(".") or n == "@eaDir":
                continue
            if any(Path(n).match(p) for p in excl):
                continue
            if pattern not in ("*", "") and not Path(n).match(pattern):
                continue
            out.append(n)
    return sorted(out)


def _qbit_torrents(url: str, category: str, timeout: float = 30.0) -> list[dict]:
    import json
    q = urllib.parse.urlencode({"category": category})
    full = url.rstrip("/") + "/api/v2/torrents/info?" + q
    req = urllib.request.Request(full, headers={"Referer": url.rstrip("/")})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8")) or []


def _parse_alias(items: list[str] | None) -> dict[str, str]:
    """`--indexer-alias 'http://prowlarr:9696/1/api=SiteB'` → {url: name}"""
    out: dict[str, str] = {}
    for it in items or []:
        if "=" in it:
            k, v = it.split("=", 1)
            out[k.strip().rstrip("/")] = v.strip()
    return out


def _parse_cadence(spec: str | None) -> dict[str, int]:
    """`--cadence "SiteA=7,SiteB=30"` → {"SiteA": 7, "SiteB": 30}"""
    out: dict[str, int] = {}
    for it in (spec or "").split(","):
        it = it.strip()
        if "=" in it:
            k, v = it.split("=", 1)
            try:
                out[k.strip()] = int(float(v.strip()))
            except ValueError:
                pass
    return out


def _idx_list(s: str | None) -> list[str]:
    return [x.strip() for x in (s or "").split(",") if x.strip()]


def _sync_now(args, st, *, quiet: bool = False):
    """跑一次完整 sync（三来源）。drive 的回灌也用它。"""
    qb = []
    if getattr(args, "qbit_url", None):
        try:
            qb = _qbit_torrents(args.qbit_url, args.category)
            if not quiet:
                _say(f"qB {args.qbit_url} 分类 {args.category!r}：{len(qb)} 个种")
        except Exception as e:  # noqa: BLE001
            _say(f"[!!] 取 qB 列表失败（忽略，不影响其他来源）: {e}")
    return S.sync_pack(
        st, args.pack,
        crossseed_db=getattr(args, "db_path", None),
        log_paths=getattr(args, "log", None) or [],
        qbit_torrents=qb,
        indexers_override=_idx_list(getattr(args, "indexers", None)) or None,
        indexer_alias=_parse_alias(getattr(args, "indexer_alias", None)),
        cadence_days=args.cadence_days,
        cadence_by_indexer=_parse_cadence(getattr(args, "cadence", None)),
        log_attempts=not getattr(args, "quiet_attempts", False),
    )


# --------------------------------------------------------------------------- #
# 子命令
# --------------------------------------------------------------------------- #
def cmd_init(args) -> int:
    with S.StateStore(args.db) as st:
        st.upsert_pack(args.pack, args.root, local_root=args.local_root,
                       link_dir=args.link_dir, category=args.category)
        listing_root = args.local_root or args.root
        if not os.path.isdir(listing_root):
            _say(f"[!!] 列目录用的路径不可达: {listing_root}")
            _say("     Windows 上列目录要传 --local-root //YOUR-NAS/video/...（UNC），")
            _say("     --root 保持 NAS 视角的 /volume1/video/...（webhook 要用它）。")
            return 2
        dirs = _list_dirs(listing_root, args.pattern, args.exclude)
        _say(f"NAS 根目录（写库/webhook 用）: {args.root}")
        _say(f"列目录用的路径            : {listing_root}")
        _say(f"识别到 {len(dirs)} 个子目录")
        if args.dry_run:
            for d in dirs[:10]:
                _say("   ", d)
            if len(dirs) > 10:
                _say(f"    ... 其余 {len(dirs) - 10} 个")
            _say("(--dry-run，未写库)")
            return 0
        added = st.register_dirs(args.pack, args.root, dirs)
        total = len(st.movies(args.pack))
        _say(f"新登记 {added} 部，库内共 {total} 部（已存在的不重置）")
    return 0


def cmd_sync(args) -> int:
    with S.StateStore(args.db) as st:
        rep = _sync_now(args, st)
        _say(rep.render())
        sm = st.summary(args.pack)
        _say("  库内阶段: " + "  ".join(f"{k}={sm[k]}" for k in S.ALL_STAGES if sm[k]))
        _print_cadence(st, args)
    return 0


def _print_cadence(st, args) -> None:
    idx = _idx_list(getattr(args, "indexers", None))
    tab = st.cadence_table(args.pack, indexers_now=idx,
                           cadence_days=args.cadence_days,
                           cadence_by_indexer=_parse_cadence(getattr(args, "cadence", None)))
    if not tab:
        return
    _say("")
    _say("  按站重搜周期：")
    for ix, d in sorted(tab.items()):
        nxt = d["next"].strftime("%m-%d %H:%M") if d["next"] else "现在"
        _say(f"    {ix:<16} 搜过 {d['searched']:>4} 部 · 到周期 {d['due']:>4} 部 · "
             f"下次最早可重搜 {nxt}")


def cmd_report(args) -> int:
    with S.StateStore(args.db) as st:
        p = st.pack(args.pack)
        if p is None:
            _say(f"[!!] 未登记: {args.pack}（先 init）")
            return 2
        sm = st.summary(args.pack)
        _say(f"=== 包 {args.pack} ===")
        _say(f"    源目录: {p['root']}")
        _say(f"    登记 {sm['TOTAL']} 部")
        _say("")
        _say("    阶段          数量   含义")
        meanings = {
            S.STAGE_SEEDING: "已在 qB 里（终点）",
            S.STAGE_MATCHED: "匹配到单种，等 qB 确认",
            S.STAGE_UNMATCHED: "真搜过，但没匹配到",
            S.STAGE_SKIPPED: "★被退避跳过 —— 必须重搜",
            S.STAGE_PENDING: "还没搜过",
            S.STAGE_ERROR: "异常",
        }
        for k in S.ALL_STAGES:
            _say(f"    {k:<13} {sm[k]:>5}   {meanings[k]}")

        idx = _idx_list(args.indexers)
        pairs = st.todo_detail(args.pack, indexers_now=idx,
                               include_cooldown=args.include_cooldown,
                               cadence_days=args.cadence_days,
                               cadence_by_indexer=_parse_cadence(args.cadence))
        _say("")
        _say(f"    → 待搜索: {len(pairs)} 部")
        _say(f"       周期: 每站 {args.cadence_days} 天"
             + (f"（{args.cadence} 单独覆盖）" if args.cadence else ""))
        _print_cadence(st, args)

        if args.verbose:
            _say("")
            for r, due in pairs:
                _say(f"       [{r['stage']:<10}] 该搜: {','.join(due) or '-':<18} {r['dir_name']}")
        else:
            _say("")
            _say("    (加 -v 看逐部清单)")
    return 0


def _apply_batch(pairs, *, limit, batch):
    """按 --limit / --batch 切出一批。

    返回 (这批, 说明文字)；说明为 None 表示参数有误（调用方应报错退出）。

    顺序由 StateStore.todo() 保证（SKIPPED → ERROR → PENDING → UNMATCHED），
    所以"取前 N 条"永远先吃掉最该搜的；一批做完后状态会变（被搜过的离开待办），
    下一批自然接着往下走 —— 因此 **不加 --batch 反复跑同一条命令就能逐批推进**。
    """
    total = len(pairs)
    if not limit:
        return pairs, f"共 {total} 部待搜（未分批，一次全发）"
    nbatch = max(1, -(-total // limit))          # 向上取整
    k = batch or 1
    if k < 1 or k > nbatch:
        return None, f"--batch {k} 超出范围：共 {nbatch} 批（每批 {limit}）"
    lo, hi = (k - 1) * limit, k * limit
    return pairs[lo:hi], (
        f"共 {total} 部待搜 → 每批 {limit}，共 {nbatch} 批；"
        f"本批 = 第 {k} 批（第 {lo + 1}~{min(hi, total)} 部）"
    )


def cmd_todo(args) -> int:
    with S.StateStore(args.db) as st:
        idx = _idx_list(args.indexers)
        pairs = st.todo_detail(args.pack, indexers_now=idx,
                               include_cooldown=args.include_cooldown,
                               cadence_days=args.cadence_days,
                               cadence_by_indexer=_parse_cadence(args.cadence))
        if args.stage:
            want = {s.strip().upper() for s in args.stage.split(",")}
            pairs = [(r, d) for r, d in pairs if r["stage"] in want]
        pairs, plan = _apply_batch(pairs, limit=args.limit, batch=args.batch)
        if pairs is None:
            _note(f"[!!] {plan}")
            return 2
        if args.limit or args.batch or args.plan:
            _note(f"    {plan}")
        if args.plan:
            return 0
        lines = [r["path"] for r, _ in pairs]
        if args.out:
            Path(args.out).write_text("\n".join(lines) + "\n", encoding="utf-8")
            _say(f"已写出 {len(lines)} 条 → {args.out}")
        else:
            for ln in lines:
                _say(ln)
        return 0


def cmd_drive(args) -> int:
    with S.StateStore(args.db) as st:
        idx = _idx_list(args.indexers)
        cad_by = _parse_cadence(args.cadence)
        pairs = st.todo_detail(args.pack, indexers_now=idx,
                               include_cooldown=args.include_cooldown,
                               cadence_days=args.cadence_days,
                               cadence_by_indexer=cad_by)
        if args.stage:
            want = {s.strip().upper() for s in args.stage.split(",")}
            pairs = [(r, d) for r, d in pairs if r["stage"] in want]
        total_all = len(pairs)
        pairs, plan = _apply_batch(pairs, limit=args.limit, batch=args.batch)
        if pairs is None:
            _say(f"[!!] {plan}")
            return 2
        paths = [r["path"] for r, _ in pairs]

        if not paths:
            _say("没有待搜索项。")
            return 0

        by_stage: dict[str, int] = {}
        for r, _ in pairs:
            by_stage[r["stage"]] = by_stage.get(r["stage"], 0) + 1
        eta = max(0, len(paths) - 1) * args.interval
        _say(plan)
        _say(f"本批 {len(paths)} 部  " + "  ".join(f"{k}={v}" for k, v in sorted(by_stage.items())))
        _say(f"节流：每条间隔 {args.interval:.0f}s → 本批约 {eta / 60:.0f} 分钟"
             + (f"；全部 {total_all} 部约 {max(0, total_all - 1) * args.interval / 60:.0f} 分钟"
                if args.limit else ""))

        if args.plan:
            _say("（--plan：只打印计划，未发任何请求）")
            return 0

        if not args.apply:
            for p in paths[:20]:
                _say("   ", p)
            if len(paths) > 20:
                _say(f"    ... 其余 {len(paths) - 20} 部")
            _say("加 --apply 才真正发 webhook。")
            return 0
        if not (args.url and args.api_key):
            _say("[!!] --apply 需要 --url 和 --api-key")
            return 2

        seeding_before = sum(1 for r in st.movies(args.pack) if r["stage"] == S.STAGE_SEEDING)

        last = [0.0]

        def on_event(kind, *rest):
            now = time.time()
            if kind == "sent":
                pth, code, i, total = rest
                tag = "OK " if code in (200, 202, 204) else "!! "
                gap = f" (+{now - last[0]:.0f}s)" if last[0] else ""
                last[0] = now
                _say(f"  [{i}/{total}] {tag}{code}{gap}  {Path(pth).name[:56]}")
            elif kind == "wait":
                _say(f"  ⏸  {rest[0]}")
            elif kind == "warn":
                _say(f"  !  {rest[0]}")
            elif kind == "abort":
                _say(f"  ✗  {rest[0]}")
            elif kind == "drained":
                _say(f"  ·  {rest[0]}")

        sess = S.DriveSession(
            url=args.url, api_key=args.api_key,
            crossseed_db=args.db_path,
            interval=args.interval,
            check_every=args.check_every,
            max_wait=args.max_wait,
            timeout=args.timeout,
            pause_on_backoff=not args.no_pause_on_backoff,
            on_event=on_event,
        )
        stats = sess.run(paths)
        _say("")
        _say(f"发送完毕：成功 {stats.ok} / 失败 {stats.failed}"
             + (f"，因退避等待 {stats.waited_sec / 60:.1f} 分钟（{stats.backoff_hits} 次）"
                if stats.waited_sec else ""))
        if stats.aborted:
            _say(f"⚠ 提前中止：{stats.aborted}")

        if args.no_auto_sync:
            _say("(--no-auto-sync：跳过回灌。之后请自己跑一次 sync)")
            return 0 if not stats.aborted else 3
        if not args.db_path:
            _say("[!!] 回灌需要 --db-path（cross-seed.db 路径），已跳过")
            return 3

        _say("")
        _say("等 cross-seed 忙完（日志静默即视为队列空）...")
        S.wait_for_log_quiet(args.log[0] if args.log else "", quiet_sec=args.settle,
                             max_wait=args.drain_max_wait, on_event=on_event)
        _say("回灌状态...")
        rep = _sync_now(args, st, quiet=True)
        stats.resync = rep
        stats.still_skipped = sum(1 for r in st.movies(args.pack) if r["stage"] == S.STAGE_SKIPPED)
        stats.newly_seeding = (sum(1 for r in st.movies(args.pack)
                                   if r["stage"] == S.STAGE_SEEDING) - seeding_before)
        _say("")
        _say("=== 回灌结果 ===")
        _say(rep.render())
        _say(f"  本次新增做种     : {stats.newly_seeding}")
        _say(f"  仍为 SKIPPED     : {stats.still_skipped}  ← 这些是「又被退避」的")
        _say("")
        _print_cadence(st, args)
        if stats.still_skipped:
            _say("")
            _say("仍被跳过 → 多半是站点侧 502/限流（见 SUMMARY §6.5）。")
            _say("去 Prowlarr 日志看该站真实状态码，别急着调 delay。")
        return 0 if not stats.aborted else 3


def cmd_show(args) -> int:
    with S.StateStore(args.db) as st:
        r = st.movie_by_dir(args.pack, args.movie) or st.movie_by_path(args.pack, args.movie)
        if r is None:
            _say(f"[!!] 找不到: {args.movie}")
            return 2
        _say(f"{r['dir_name']}")
        for k in ("stage", "attempts", "last_attempt_at", "next_retry_at", "seeding_count"):
            _say(f"  {k:<16} {r[k]}")
        for k in ("searched_indexers", "indexer_seen", "skipped_indexers",
                  "matched_indexers", "matched_hashes"):
            _say(f"  {k:<16} {r[k]}")
        _say("  --- 流水 ---")
        for a in st.attempts(r["id"]):
            _say(f"  {a['at']}  {a['kind']:<7} {a['result']:<10} "
                 f"idx={a['indexers']} skip={a['skipped_indexers']} {a['note'] or ''}")
    return 0


# --------------------------------------------------------------------------- #
def _add_cadence_opts(p) -> None:
    p.add_argument("--cadence-days", type=int, default=S.DEFAULT_CADENCE_DAYS,
                   help=f"每个站多久重搜一次（天），默认 {S.DEFAULT_CADENCE_DAYS}")
    p.add_argument("--cadence", help="按站覆盖周期，如 'SiteA=7,SiteB=30'")


def _add_source_opts(p) -> None:
    p.add_argument("--db-path", dest="db_path", help="cross-seed.db 路径（只读）")
    p.add_argument("--log", action="append", help="cross-seed 日志路径，可多次")
    p.add_argument("--qbit-url", help="如 http://NAS_IP:3060")
    p.add_argument("--category", default="reseed-singles")
    p.add_argument("--indexers", help="当前生效的索引器名，逗号分隔（覆盖 db 推断）")
    p.add_argument("--indexer-alias", action="append",
                   help="索引器 url=名字，可多次。如 'http://prowlarr:9696/1/api=SiteB'")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="reseed-state", description="单片状态机 CLI")
    p.add_argument("--db", default=DEFAULT_DB, help=f"sidecar 状态库（默认 {DEFAULT_DB}）")
    sub = p.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("init", help="登记大包与包内子目录")
    a.add_argument("--pack", required=True)
    a.add_argument("--root", required=True,
                   help="★cross-seed 视角的路径（NAS 上），如 /volume1/video/download/movies/<PACK>")
    a.add_argument("--local-root",
                   help="本机可访问的等价路径（Windows 上填 //YOUR-NAS/video/...），只用于列目录")
    a.add_argument("--link-dir")
    a.add_argument("--category")
    a.add_argument("--pattern", default="*")
    a.add_argument("--exclude", nargs="*", default=[])
    a.add_argument("--dry-run", action="store_true")
    a.set_defaults(func=cmd_init)

    a = sub.add_parser("sync", help="从 cross-seed.db + 日志 + qB 同步状态")
    a.add_argument("--pack", required=True)
    _add_source_opts(a)
    _add_cadence_opts(a)
    a.add_argument("--quiet-attempts", action="store_true")
    a.set_defaults(func=cmd_sync)

    a = sub.add_parser("report", help="阶段汇总 + 按站重搜周期")
    a.add_argument("--pack", required=True)
    a.add_argument("--indexers")
    _add_cadence_opts(a)
    a.add_argument("--include-cooldown", action="store_true",
                   help="把还没到周期的也计入待搜（用于强制全量重扫）")
    a.add_argument("-v", "--verbose", action="store_true")
    a.set_defaults(func=cmd_report)

    a = sub.add_parser("todo", help="导出待搜索清单")
    a.add_argument("--pack", required=True)
    a.add_argument("--indexers")
    a.add_argument("--stage", help="只保留这些阶段，逗号分隔")
    a.add_argument("--limit", type=int, help="每批多少条（分批用）")
    a.add_argument("--batch", type=int, default=None,
                   help="取第几批（配合 --limit）。默认第 1 批；"
                        "一批做完重跑同一条命令即可推进到下一批")
    a.add_argument("--plan", action="store_true",
                   help="只打印分批计划，不导出清单")
    a.add_argument("--out")
    _add_cadence_opts(a)
    a.add_argument("--include-cooldown", action="store_true",
                   help="把还没到周期的也带上（强制全量重扫）")
    a.set_defaults(func=cmd_todo)

    a = sub.add_parser("drive", help="按待办清单控速驱动 cross-seed 重搜，并自动回灌")
    a.add_argument("--pack", required=True)
    _add_source_opts(a)
    _add_cadence_opts(a)
    a.add_argument("--stage", help="只驱动这些阶段，逗号分隔")
    a.add_argument("--limit", type=int, help="每批多少条（分批用）")
    a.add_argument("--batch", type=int, default=None,
                   help="取第几批（配合 --limit）。默认第 1 批；"
                        "一批做完重跑同一条命令即可推进到下一批")
    a.add_argument("--plan", action="store_true",
                   help="只打印分批计划，不发请求")
    a.add_argument("--include-cooldown", action="store_true")
    a.add_argument("--url", help="cross-seed 地址，如 http://NAS_IP:2468")
    a.add_argument("--api-key")
    a.add_argument("--interval", type=float, default=30.0,
                   help="两条 webhook 之间的间隔秒数，默认 30（对齐 cross-seed 的 delay）")
    a.add_argument("--check-every", type=int, default=10,
                   help="每发多少条检查一次索引器退避，默认 10")
    a.add_argument("--max-wait", type=float, default=1800.0,
                   help="单次退避最多等多少秒，超过就中止，默认 1800")
    a.add_argument("--no-pause-on-backoff", action="store_true",
                   help="不理会退避，闷头发（不建议）")
    a.add_argument("--settle", type=float, default=90.0,
                   help="回灌前等日志静默多少秒，默认 90")
    a.add_argument("--drain-max-wait", type=float, default=3600.0,
                   help="等 cross-seed 忙完的上限，默认 3600")
    a.add_argument("--no-auto-sync", action="store_true", help="打完不回灌")
    a.add_argument("--timeout", type=float, default=30.0)
    a.add_argument("--apply", action="store_true", help="真的发请求（默认 dry-run）")
    a.set_defaults(func=cmd_drive)

    a = sub.add_parser("show", help="看单片的详情与流水")
    a.add_argument("--pack", required=True)
    a.add_argument("--movie", required=True, help="目录名或完整路径")
    a.set_defaults(func=cmd_show)
    return p


def main(argv: list[str] | None = None) -> int:
    _safe_stdout()
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())

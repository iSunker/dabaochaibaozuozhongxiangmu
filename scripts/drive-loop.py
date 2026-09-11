#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
反馈驱动循环 —— 自动续跑 cross-seed 搜索，无需人盯。

原理
----
每次跑一批 `drive --limit N --apply`，跑完读 `DriveStats` 的三个信号：
  * `still_skipped > 0` 或 `backoff_hits > 0`  → 站点在退避/限流 → 下次间隔拉长
  * `newly_seeding` 稳定产出、无退避           → 站点健康 → 下次间隔收紧
  * `aborted`（> --max-wait 提前中止）         → 休整 + 间隔拉满
然后在 DC / FRDS / (MBF) 三个包之间轮流推进。
一批做完重跑同一条命令即可推进 —— 本脚本把「重跑」自动化了。

用法
----
  python scripts/drive-loop.py --once              # 只跑一轮（当前包下一批）
  python scripts/drive-loop.py                      # 循环跑（默认）
  python scripts/drive-loop.py --max-rounds 3       # 最多 3 轮后退出
  python scripts/drive-loop.py --pack dc-collection # 只跑指定包

参数（除包与循环控制外，其余透传给 drive）
  --url / --api-key / --db-path 必需（与 drive 一致；--api-key 可省略→读 .env）
  --indexers HDFans,NanyangPT   参与搜索的站（逗号分隔）
  --limit 50                    每批条数
  --interval / --check-every / --max-wait / --settle 透传

调度
----
建议挂 Windows 计划任务，每 15 分钟唤醒一次：
  schtasks /Create /TN "reseed-drive-loop" /TR "python D:\\...\\drive-loop.py --once" \
          /SC MINUTE /MO 15
`--once` 模式下每次唤醒只跑一批；`--min-sleep` 保证不会连续猛打。
"""
import argparse
import logging
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))

from orchestrator import state as S  # noqa: E402

LOG = logging.getLogger("drive-loop")

# sidecar 状态库默认位置（与 reseed-state.py 的 DEFAULT_DB 保持一致）
DEFAULT_DB = os.environ.get("RESEED_STATE_DB", str(ROOT / "hlink" / "state.db"))


def parse_cadence(spec: str | None) -> dict[str, int]:
    """`--cadence "SiteA=7,SiteB=30"` → {"SiteA": 7, "SiteB": 30}（内联自 reseed-state.py）"""
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


def apply_batch(pairs, *, limit, batch):
    """按 --limit / --batch 切出一批（内联自 reseed-state.py：顺序由 todo() 保证）。"""
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


# --------------------------------------------------------------------------- #
# 反馈 → 下次间隔
# --------------------------------------------------------------------------- #
BASE_SLEEP = 60 * 45        # 站点健康时，批间最小间隔 45 分钟
BACKOFF_SLEEP = 60 * 120     # 撞退避后，拉长到 2 小时
ABORT_SLEEP = 60 * 180       # 提前中止（退避等太久），休整 3 小时

MIN_SLEEP = 60 * 30          # 硬下限：任何情况批间隔不少于 30 分钟
MAX_SLEEP = 60 * 240         # 硬上限：4 小时


def clamp(s: float) -> float:
    return max(MIN_SLEEP, min(MAX_SLEEP, s))


def next_sleep(stats: S.DriveStats) -> tuple[float, str]:
    """根据上一批的结果决定下次批间隔。返回 (秒, 原因)。"""
    if stats.aborted:
        return ABORT_SLEEP, f"提前中止：{stats.aborted}"
    if stats.still_skipped > 0:
        return BACKOFF_SLEEP, f"仍有 {stats.still_skipped} 部被退避跳过"
    if stats.backoff_hits > 0:
        return BACKOFF_SLEEP, f"本轮 {stats.backoff_hits} 次命中退避"
    if stats.newly_seeding > 0:
        return BASE_SLEEP, f"新增做种 {stats.newly_seeding} 部，站点健康"
    # 一批发出去、既没退避也没新增 —— 站点正常但命中一般，按基准即可
    return BASE_SLEEP, "无退避、无新增（正常）"


# --------------------------------------------------------------------------- #
# 读 .env 里的 CROSSSEED_API_KEY（避免 key 出现在命令行/聊天）
# --------------------------------------------------------------------------- #
def read_key_from_env(env_path: Path) -> str | None:
    for ln in env_path.read_text(encoding="utf-8").splitlines():
        if ln.startswith("CROSSSEED_API_KEY="):
            return ln.split("=", 1)[1].strip()
    return None


def qbit_torrents(url: str, category: str, timeout: float = 30.0) -> list[dict]:
    """取 qB 某分类的全部种子（内联自 reseed-state.py）。失败返回 []，不中断循环。"""
    import json
    import urllib.parse
    import urllib.request
    try:
        q = urllib.parse.urlencode({"category": category})
        full = url.rstrip("/") + "/api/v2/torrents/info?" + q
        req = urllib.request.Request(full, headers={"Referer": url.rstrip("/")})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8")) or []
    except Exception as e:  # noqa: BLE001 —— qB 挂了不该让循环死
        LOG.warning("取 qB 列表失败（忽略）: %s", e)
        return []


def parse_alias(items: list[str] | None) -> dict[str, str]:
    """`--indexer-alias 'http://prowlarr:9696/1/api=SiteB'` → {url: name}（内联）。"""
    out: dict[str, str] = {}
    for it in items or []:
        if "=" in it:
            k, v = it.split("=", 1)
            out[k.strip().rstrip("/")] = v.strip()
    return out


# --------------------------------------------------------------------------- #
# 跑一轮（一个包的一批）
# --------------------------------------------------------------------------- #
def run_round(pack: str, args, api_key: str) -> S.DriveStats | None:
    """对指定包跑一批 drive + 回灌。返回 DriveStats；无待搜 / 出错返回 None。

    ★ 回灌必须带 qB（qbit_torrents）—— 否则 stage 推导拿不到"是否在做种"，
      原本 SEEDING 的片子会被误降级成 MATCHED（2026-09-11 踩过）。
    """
    st = S.StateStore(args.db)
    try:
        idx = [i.strip() for i in (args.indexers or "").split(",") if i.strip()] or None
        pairs = st.todo_detail(pack, indexers_now=idx,
                               include_cooldown=args.include_cooldown,
                               cadence_days=args.cadence_days,
                               cadence_by_indexer=parse_cadence(args.cadence))
        seeding_before = sum(1 for r in st.movies(pack) if r["stage"] == S.STAGE_SEEDING)
    finally:
        st.con.close()

    pairs, plan = apply_batch(pairs, limit=args.limit, batch=args.batch)
    if pairs is None:
        LOG.warning("[%s] %s", pack, plan)
        return None
    paths = [r["path"] for r, _ in pairs]
    if not paths:
        LOG.info("[%s] 没有待搜索项。", pack)
        return None

    sess = S.DriveSession(
        url=args.url,
        api_key=api_key,
        crossseed_db=args.db_path,
        interval=args.interval,
        check_every=args.check_every,
        max_wait=args.max_wait,
        timeout=args.timeout,
        pause_on_backoff=not args.no_pause_on_backoff,
    )
    stats = sess.run(paths)
    LOG.info("[%s] 发送完毕：成功 %s / 失败 %s，退避等待 %.1f 分钟（%s 次）",
             pack, stats.ok, stats.failed, stats.waited_sec / 60, stats.backoff_hits)

    # ---- 回灌（带 qB，否则 SEEDING 会被误降级）----
    if args.log:
        S.wait_for_log_quiet(args.log[0], quiet_sec=args.settle,
                             max_wait=args.drain_max_wait)
    qb = qbit_torrents(args.qbit_url, args.category) if args.qbit_url else []
    st = S.StateStore(args.db)
    try:
        rep = S.sync_pack(
            st, pack,
            crossseed_db=args.db_path,
            log_paths=args.log or [],
            qbit_torrents=qb,
            indexers_override=[i.strip() for i in (args.indexers or "").split(",")
                               if i.strip()] or None,
            indexer_alias=parse_alias(args.indexer_alias),
            cadence_days=args.cadence_days,
            cadence_by_indexer=parse_cadence(args.cadence),
        )
        stats.resync = rep
        stats.still_skipped = sum(1 for r in st.movies(pack)
                                  if r["stage"] == S.STAGE_SKIPPED)
        stats.newly_seeding = (sum(1 for r in st.movies(pack)
                                   if r["stage"] == S.STAGE_SEEDING) - seeding_before)
    finally:
        st.con.close()
    LOG.info("[%s] 回灌：搜过 %s / 匹配 %s / 新增做种 %d / 仍 SKIPPED %d",
             pack, rep.from_db + rep.from_log, rep.matched,
             stats.newly_seeding, stats.still_skipped)
    return stats


# --------------------------------------------------------------------------- #
# 主循环
# --------------------------------------------------------------------------- #
def main() -> int:
    ap = argparse.ArgumentParser(description="反馈驱动循环：自动续跑 cross-seed 搜索")
    ap.add_argument("--packs", default="dc-collection,frds-top250-2024",
                    help="包顺序，逗号分隔（轮流推进），默认 dc-collection,frds-top250-2024")
    ap.add_argument("--once", action="store_true", help="只跑一轮（配合计划任务）")
    ap.add_argument("--max-rounds", type=int, default=0, help="最多跑几轮（0=不限）")
    ap.add_argument("--min-sleep", type=float, default=0, help="批间最小等待秒数（覆盖默认）")
    # --- 透传 drive 参数 ---
    ap.add_argument("--db", default=DEFAULT_DB)
    ap.add_argument("--db-path", dest="db_path")
    ap.add_argument("--url", default="http://192.168.0.7:2468")
    ap.add_argument("--qbit-url", dest="qbit_url", default="http://192.168.0.7:3060",
                    help="qB :3060 地址（回灌必需，否则 SEEDING 会被误降级）")
    ap.add_argument("--category", default="reseed-singles")
    ap.add_argument("--log", action="append", default=None,
                    help="cross-seed 日志路径（回灌用，可多次；默认用 NAS 上的 info.current.log）")
    ap.add_argument("--indexer-alias", action="append", default=None)
    ap.add_argument("--api-key", default=None)
    ap.add_argument("--env", default=str(ROOT / ".env"))
    ap.add_argument("--indexers", default="HDFans,NanyangPT")
    ap.add_argument("--limit", type=int, default=50)
    ap.add_argument("--interval", type=float, default=30.0)
    ap.add_argument("--check-every", type=int, default=10)
    ap.add_argument("--max-wait", type=float, default=1800.0)
    ap.add_argument("--no-pause-on-backoff", action="store_true")
    ap.add_argument("--settle", type=float, default=90.0)
    ap.add_argument("--drain-max-wait", type=float, default=3600.0)
    ap.add_argument("--timeout", type=float, default=30.0)
    ap.add_argument("--batch", type=int, default=None)
    ap.add_argument("--include-cooldown", action="store_true")
    ap.add_argument("--cadence-days", type=int, default=S.DEFAULT_CADENCE_DAYS)
    ap.add_argument("--cadence", default=None)
    ap.add_argument("--dry-run", action="store_true", help="只打印计划，不发请求")
    args = ap.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(str(HERE / "drive-loop.log"), encoding="utf-8"),
        ],
    )

    packs = [p.strip() for p in args.packs.split(",") if p.strip()]

    # 默认日志路径（NAS 上 cross-seed 的 info 日志），回灌要用
    if not args.log:
        default_log = ("//iSunker-DS423/docker_ssd/prowlarr_cross-seed_autohardlink"
                       "/cross-seed/logs/info.current.log")
        if Path(default_log).is_file():
            args.log = [default_log]

    # 默认 cross-seed.db 路径
    if not args.db_path:
        default_db = ("//iSunker-DS423/docker_ssd/prowlarr_cross-seed_autohardlink"
                      "/cross-seed/cross-seed.db")
        if Path(default_db).is_file():
            args.db_path = default_db

    LOG.info("=== drive-loop 启动：packs=%s indexers=%s limit=%d ===",
             packs, args.indexers, args.limit)

    # key：--api-key 显式给优先，否则从 --env 读
    api_key = args.api_key
    if not api_key:
        env_path = Path(args.env)
        if env_path.is_file():
            api_key = read_key_from_env(env_path)
        if not api_key:
            LOG.error("找不到 CROSSSEED_API_KEY（--api-key 或 --env 的 .env）")
            return 2

    # 计划任务每 15 分钟唤醒 --once：连续唤醒时保证最短间隔
    min_sleep = args.min_sleep or MIN_SLEEP

    round_no = 0
    # 包轮流：记录上次跑到哪个包，下次从下一个开始
    cur_pack_idx = 0
    while args.max_rounds == 0 or round_no < args.max_rounds:
        pack = packs[cur_pack_idx % len(packs)]
        round_no += 1

        if args.dry_run:
            LOG.info("[%s] dry-run：列出待搜计划（不发请求）", pack)
            st = S.StateStore(args.db)
            idx = [i.strip() for i in (args.indexers or "").split(",") if i.strip()] or None
            pairs = st.todo_detail(pack, indexers_now=idx,
                                   include_cooldown=args.include_cooldown,
                                   cadence_days=args.cadence_days,
                                   cadence_by_indexer=parse_cadence(args.cadence))
            pairs, plan = apply_batch(pairs, limit=args.limit, batch=args.batch)
            LOG.info("[%s] %s", pack, plan)
            st.con.close()
            if args.once:
                return 0
            cur_pack_idx += 1
            if not args.once:
                time.sleep(min_sleep)
            continue

        t0 = time.time()
        LOG.info("[第 %d 轮] 跑包 %s ...", round_no, pack)
        try:
            stats = run_round(pack, args, api_key)
        except Exception as e:  # noqa: BLE001 —— 循环不能因单批异常而死
            LOG.exception("[%s] 本批异常（继续循环）", pack)
            if args.once:
                return 1
            time.sleep(BACKOFF_SLEEP)
            cur_pack_idx += 1
            continue

        if stats is None:
            LOG.info("[%s] 本批无动作（没待搜或计划为空），跳过该包", pack)
            # 全部包都没待搜 → 全部完成，退出
            cur_pack_idx += 1
            if cur_pack_idx % len(packs) == 0:
                remaining = 0
                st = S.StateStore(args.db)
                for p in packs:
                    remaining += sum(1 for r in st.movies(p) if r["stage"] not in S.DONE_STAGES)
                st.con.close()
                if remaining == 0:
                    LOG.info("=== 所有包均无待搜项，任务完成，退出 ===")
                    return 0
            if args.once:
                return 0
            time.sleep(min_sleep)
            continue

        sleep_sec, reason = next_sleep(stats)
        LOG.info("[第 %d 轮] %s | 原因：%s | 下次间隔 %.0f 分钟",
                 round_no, stats.render().splitlines()[0] if stats else "?",
                 reason, sleep_sec / 60)
        LOG.info("  → %s", reason)
        if stats.newly_seeding:
            LOG.info("  → 本轮新增做种 %d 部 🎉", stats.newly_seeding)
        if stats.still_skipped:
            LOG.warning("  → 仍有 %d 部被退避（站点侧 502/限流？见 SUMMARY §6.5）",
                        stats.still_skipped)

        cur_pack_idx += 1
        if args.once:
            LOG.info("--once 模式：本轮完成，退出")
            return 0
        sleep_sec = max(sleep_sec, min_sleep)
        LOG.info("等待 %.1f 分钟后跑下一批（%s）", sleep_sec / 60, packs[cur_pack_idx % len(packs)])
        time.sleep(sleep_sec)

    return 0


if __name__ == "__main__":
    sys.exit(main())

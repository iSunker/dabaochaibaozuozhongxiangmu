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
import json
import logging
import os
import re
import subprocess
import sys
import threading
import time
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))

from orchestrator import state as S  # noqa: E402

LOG = logging.getLogger("drive-loop")

# sidecar 状态库默认位置（与 reseed-state.py 的 DEFAULT_DB 保持一致）
DEFAULT_DB = os.environ.get("RESEED_STATE_DB", str(ROOT / "hlink" / "state.db"))


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
# 「出声」机制 —— 无人值守最怕的是**无声停摆**
# --------------------------------------------------------------------------- #
# 站点持续 502 时 next_sleep 只会给它 3 小时休息，然后接着试、接着失败。
# 跑一晚上没人知道。所以连续失败要跨过阈值就大声喊；全部干完也要喊一声。
ABORT_ALERT_AFTER = 3


def update_abort_streak(prev: int, stats: S.DriveStats | None, *,
                        failed: bool = False) -> int:
    """维护"连续失败批数"。

    算失败：提前中止（`stats.aborted`）、整批异常（`failed=True`）。
    正常跑完（含"本包无待搜"）清零。
    """
    aborted = failed or bool(stats is not None and stats.aborted)
    if not aborted:
        return 0
    n = prev + 1
    reason = stats.aborted if (stats is not None and stats.aborted) else "整批异常"
    if n < ABORT_ALERT_AFTER:
        LOG.warning("连续第 %d 批失败（%s）", n, reason)
        return n
    LOG.warning("!" * 62)
    LOG.warning("⚠ 已连续 %d 批失败（最近：%s）", n, reason)
    LOG.warning("  无人值守下这通常意味着两种可能：")
    LOG.warning("   ① 站点持续 502 / 限流（看 Prowlarr 里各站状态）")
    LOG.warning("   ② .env 改了但没 force-recreate（容器里还是旧配置，见 SUMMARY §13.6）")
    LOG.warning("  请人工看一眼 cross-seed 日志与 Prowlarr。")
    LOG.warning("!" * 62)
    return n


def alert_if_all_done(packs: list[str], db: str) -> bool:
    """所有包都没有待搜项 → 大声报告"干完了"（否则循环静默退出，没人知道）。"""
    st = S.StateStore(db)
    try:
        remaining = sum(1 for p in packs
                        for r in st.movies(p) if r["stage"] not in S.DONE_STAGES)
    finally:
        st.con.close()
    if remaining:
        return False
    LOG.warning("=" * 62)
    LOG.warning("🎉 所有包均无待搜项 —— 自动循环已无事可做。")
    LOG.warning("   计划任务可保留（新片/新站接入后会自动变回待搜），")
    LOG.warning("   或手动停掉：schtasks /Delete /TN \"reseed-drive-loop\" /F")
    LOG.warning("=" * 62)
    return True


# --------------------------------------------------------------------------- #
# 索引器自检 —— cross-seed 实际会搜的站 vs --indexers
# --------------------------------------------------------------------------- #
def _norm_indexer_name(n: str) -> str:
    """取站名主干：'NanyangPT (南洋)' → 'nanyangpt'。

    cross-seed 里的名字来自站点 caps，常带括号后缀；`--indexers` 是人手写的短名。
    直接比集合会每次都误报，所以去掉括号后缀与大小写再比。
    """
    # ★ maxsplit 必须写成关键字：Python 3.13 起按位置传会发 DeprecationWarning
    #   （re.split(pattern, string, maxsplit) 里 maxsplit 是 keyword-only 的语义）。
    return re.split(r"[(（]", n.strip(), maxsplit=1)[0].strip().lower()


def check_indexers(args) -> None:
    """★ 这两份信息是**分开维护**的，对不上会**静默错记**。

    cross-seed 按它自己的 `TORZNAB_URLS` **全站搜索**；
    `--indexers` 只决定状态机把"搜过"**记到哪个站名下**（`indexer_seen` / 重搜周期）。
    加了站却忘了改 `--indexers` → 新站搜到的结果被记成"没搜过那个站"
    → 要么反复重搜（浪费额度），要么永远不重搜。而且**不报错**，只是数算错。
    """
    if not args.db_path:
        return
    try:
        snap = S.read_crossseed_db(args.db_path)
    except Exception as e:  # noqa: BLE001 —— 自检失败不该挡住正事
        LOG.debug("索引器自检跳过（读不到 cross-seed.db）: %s", e)
        return

    live = list(snap.indexers)
    mine = {_norm_indexer_name(x) for x in (args.indexers or "").split(",") if x.strip()}

    # cross-seed 侧用 "prowlarr#<N>" 表示"active 但拉不到名字"的索引器（见 read_crossseed_db）
    # ★ N 是 **URL 里的 N**（Prowlarr 的索引器号，与 TORZNAB_URLS 的写法一致），
    #   不是 cross-seed 数据库的行号 —— 别拿它去对 indexer 表的 id。
    unnamed = [lbl for lbl in live if lbl.startswith("prowlarr#")]
    named = [lbl for lbl in live if not lbl.startswith("prowlarr#")]
    missing = [lbl for lbl in named if _norm_indexer_name(lbl) not in mine]
    extra = sorted(mine - {_norm_indexer_name(lbl) for lbl in named})

    if unnamed:
        LOG.warning("⚠ cross-seed 有 %d 个 active 索引器**拉不到名字**（%s）——"
                    " 多半是该站返回错误（410/403/CF），caps 取不回来。",
                    len(unnamed), ", ".join(unnamed))
        LOG.warning("  编号是 `TORZNAB_URLS` 里的那个（`#N` = `/N/api`），不是 Prowlarr 界面序号。")
        LOG.warning("  常见原因：`.env` 里删了站但容器没重建，或该站被 Prowlarr 禁用。")
    if missing:
        LOG.warning("⚠ cross-seed 实际会搜 %s，但 --indexers 没列 ——"
                    " 这些站的搜索结果会被状态机**漏记**（→ 重复搜 / 永不重搜）。",
                    ", ".join(missing))
        LOG.warning("  建议把 --indexers 改成：--indexers %s", ",".join(named))
    if extra:
        LOG.warning("⚠ --indexers 列了 %s，但 cross-seed 根本不会搜 ——"
                    " 状态机会把它们记成'搜过'，实际是假的（→ 永远不会去搜）。",
                    ", ".join(extra))
    if not (unnamed or missing or extra):
        LOG.info("索引器自检通过：cross-seed 实际会搜 %s，与 --indexers 一致。",
                 ", ".join(named))


# --------------------------------------------------------------------------- #
# .env 生效自检 —— cross-seed 日志里**最近**的 410/401/403
# --------------------------------------------------------------------------- #
#: 只看最近这么久内的日志。
#: ★ 必须卡时间窗：容器重建成功后，历史 410 还在日志里躺着，不卡窗口就会
#:   **永远报警**（狼来了），反而把真问题淹掉。
STALE_ENV_WINDOW_SEC = 2 * 3600
#: 只读日志**尾部**这么多字节（info.current.log 会长到几百 MB，全读不可接受）
STALE_ENV_TAIL_BYTES = 512 * 1024

#: cross-seed 够不着索引器的两种固定句式（v6.13.7 实测）：
#:   ① 搜索中途：warn: [webhook] Failed to reach <url>: request failed with code 410, snoozing until …
#:   ② 启动取 caps：error: <url> returned 401 Unauthorized when fetching caps, check your apikey
_RE_UNREACHABLE = (
    re.compile(
        r"^(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\.\d+\s+warn:\s+.*?"
        r"Failed to reach (?P<url>\S+?):\s+request failed with code (?P<code>\d+)"
    ),
    re.compile(
        r"^(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\.\d+\s+error:\s+"
        r"(?P<url>\S+?) returned (?P<code>\d+) \w+ when fetching caps"
    ),
)


def _tail_lines(path: Path, nbytes: int) -> list[str]:
    """读文件**尾部** nbytes 字节（SMB 上是范围读，不会把 2.6 MB 全拉过来）。"""
    with open(path, "rb") as f:
        f.seek(0, os.SEEK_END)
        size = f.tell()
        f.seek(max(0, size - nbytes))
        data = f.read()
    lines = data.decode("utf-8", errors="replace").splitlines()
    if size > nbytes and lines:
        lines = lines[1:]      # 第一行多半被切断在半路，丢掉
    return lines


def check_env_applied(args) -> None:
    """★ 本项目的**头号复发坑**：改了 `.env`，但容器没重建。

    `docker compose restart` **不会**重新注入环境变量，必须
    `up -d --no-deps --force-recreate cross-seed`（见 SUMMARY §13.3 / §13.6）。

    它的症状是 cross-seed 日志里不停出现：

        warn: [webhook] Failed to reach http://prowlarr:9696/3/api:
              request failed with code 410, snoozing until …

    410 = 这个索引器在 Prowlarr 里**已经没了**，但容器的 `TORZNAB_URLS` 还留着它
    （删站忘了重建）；401 = apikey 对不上；403 = 该站被禁用。三者多半是同一件事。

    这里**只报警、不自动修** —— 重建容器必须由人执行（会打断正在跑的批次）。
    """
    if not args.log:
        return
    cutoff = time.time() - STALE_ENV_WINDOW_SEC
    hits: dict[tuple[str, str], int] = {}
    newest = 0.0
    for p in args.log:
        try:
            lines = _tail_lines(Path(p), STALE_ENV_TAIL_BYTES)
        except Exception as e:  # noqa: BLE001 —— 自检失败不该挡住正事
            LOG.debug("读不到 cross-seed 日志 %s: %s", p, e)
            continue
        for ln in lines:
            m = None
            for rx in _RE_UNREACHABLE:
                m = rx.match(ln)
                if m:
                    break
            if not m:
                continue
            try:
                ts = datetime.strptime(m["ts"], "%Y-%m-%d %H:%M:%S").timestamp()
            except ValueError:
                continue
            if ts < cutoff:
                continue
            key = (m["url"], m["code"])
            hits[key] = hits.get(key, 0) + 1
            newest = max(newest, ts)

    if not hits:
        LOG.debug("`.env` 生效自检通过：最近 %.0f 小时内没有够不着索引器的记录。",
                  STALE_ENV_WINDOW_SEC / 3600)
        return

    LOG.warning("!" * 62)
    LOG.warning("⚠ cross-seed 最近 %.0f 小时内**一直够不着**这些索引器：",
                STALE_ENV_WINDOW_SEC / 3600)
    for (url, code), n in sorted(hits.items(), key=lambda kv: -kv[1]):
        LOG.warning("    %-46s ← HTTP %s × %d", url, code, n)
    LOG.warning("  最近一次：%s（%.0f 分钟前）",
                time.strftime("%H:%M:%S", time.localtime(newest)),
                (time.time() - newest) / 60)
    LOG.warning("")
    LOG.warning("  ★ 本项目的头号复发坑：**改了 .env，但容器没重建**。")
    LOG.warning("    410 = 该索引器在 Prowlarr 里已经没了，容器里的 TORZNAB_URLS 还留着它；")
    LOG.warning("    401 = apikey 对不上；403 = 该站被禁用。三者多半是同一件事。")
    LOG.warning("    ⚠ `docker compose restart` **不重新注入环境变量**，必须：")
    LOG.warning("      cd /volume2/docker_ssd/prowlarr_cross-seed_autohardlink \\")
    LOG.warning("        && sudo docker compose up -d --no-deps --force-recreate cross-seed")
    LOG.warning("    验证：本条警告消失（上面的「索引器自检」也会跟着变绿）。")
    LOG.warning("!" * 62)


# --------------------------------------------------------------------------- #
# 读 .env 里的 CROSSSEED_API_KEY（避免 key 出现在命令行/聊天）
# --------------------------------------------------------------------------- #
def read_key_from_env(env_path: Path) -> str | None:
    for ln in env_path.read_text(encoding="utf-8").splitlines():
        if ln.startswith("CROSSSEED_API_KEY="):
            return ln.split("=", 1)[1].strip()
    return None


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
                               cadence_by_indexer=S.parse_cadence(args.cadence))
        seeding_before = sum(1 for r in st.movies(pack) if r["stage"] == S.STAGE_SEEDING)
    finally:
        st.con.close()

    pairs, plan = S.apply_batch(pairs, limit=args.limit, batch=args.batch)
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
    # qB 挂了不该让整批死 —— 少一个数据源而已（代价：推不出 SEEDING，会被降级）
    qb: list[dict] = []
    if args.qbit_url:
        try:
            qb = S.qbit_torrents(args.qbit_url, args.category)
        except Exception as e:  # noqa: BLE001
            LOG.warning("取 qB 列表失败（忽略）: %s", e)
    st = S.StateStore(args.db)
    try:
        rep = S.sync_pack(
            st, pack,
            crossseed_db=args.db_path,
            log_paths=args.log or [],
            qbit_torrents=qb,
            indexers_override=[i.strip() for i in (args.indexers or "").split(",")
                               if i.strip()] or None,
            indexer_alias=S.parse_alias(args.indexer_alias),
            cadence_days=args.cadence_days,
            cadence_by_indexer=S.parse_cadence(args.cadence),
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
# --------------------------------------------------------------------------- #
# --once 的跨进程节流 + 包轮换（计划任务每 15 分钟唤醒时靠这个防重叠）
# --------------------------------------------------------------------------- #
STATE_FILE = HERE / ".drive-loop.state"


def read_state() -> dict:
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 —— 没有 / 损坏都当空状态
        return {}


def write_state(d: dict) -> None:
    try:
        STATE_FILE.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    except OSError as e:
        LOG.warning("写状态文件失败（忽略）: %s", e)


# 心跳多久没刷新就认为上一批已经死了。批次里每 60s 刷一次，10 分钟足够宽裕
# （等于容忍 10 次丢拍），又能让被 kill 的残留批次在 10 分钟内被识别、不再挡住后续唤醒。
HEARTBEAT_STALE_SEC = 600


def write_heartbeat() -> None:
    """刷新心跳（合并进现有状态，不动 running_pid / last_pack_idx）。"""
    st = read_state()
    st["heartbeat_ts"] = time.time()
    write_state(st)


class Heartbeat:
    """后台心跳线程：批次运行期间每 `period` 秒刷一次状态文件。

    ★ 为什么不能只靠 PID 判断"上一批还在不在"
      Windows 会**复用 PID**。批次被强杀后状态文件里留着 running_pid，
      若那个号恰好被别的进程占用，pid_alive() 会永远返回 True
      —— 于是每次唤醒都判"上一批还在跑"，**静默永久停工**。
      这正是无人值守最怕的失败模式：不报错，只是不动。

      加了心跳就变成「PID 活着 **且** 心跳新鲜」才算在跑：进程真死了心跳必停，
      PID 被复用也救不回来。

    ★ 为什么用独立线程，而不是"每发一条 webhook 就刷一次"
      批次里有长时间不发请求的阶段 —— 等 cross-seed 日志静默（最多
      --drain-max-wait，默认 1 小时）和回灌。那些阶段没有可挂钩的事件，
      心跳会假死、被误判成残留。独立线程与批次同生共死，最省心。

    用法：`with Heartbeat(): stats = run_round(...)`
    """

    def __init__(self, period: float = 60.0):
        self.period = period
        self._stop = threading.Event()
        self._th: threading.Thread | None = None

    def __enter__(self) -> "Heartbeat":
        self._th = threading.Thread(target=self._loop, daemon=True, name="drive-loop-hb")
        self._th.start()
        return self

    def _loop(self) -> None:
        while not self._stop.wait(self.period):
            try:
                write_heartbeat()
            except Exception:  # noqa: BLE001 —— 心跳失败绝不能拖垮批次
                pass

    def __exit__(self, *exc) -> bool:
        self._stop.set()
        if self._th:
            self._th.join(timeout=5)   # 确保不再与 finally 里写状态竞争
        return False


def pid_alive(pid) -> bool:
    """判断 pid 是否还在跑。Windows 上用 tasklist（os.kill(pid,0) 在 Windows 会杀进程！）。"""
    if not pid:
        return False
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return False
    if os.name == "nt":
        try:
            out = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
                capture_output=True, text=True, errors="replace", timeout=15,
            ).stdout
            return str(pid) in (out or "")
        except Exception:  # noqa: BLE001
            return False
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def batch_alive(st: dict) -> bool:
    """上一批是否**真的**还在跑：PID 存活 **且** 心跳新鲜。

    只看 PID 会被 Windows 的 PID 复用骗到（详见 Heartbeat 的说明）——
    那会导致"永远判在跑 → 静默停工"。
    """
    pid = st.get("running_pid")
    if not pid_alive(pid):
        return False

    # ★ 区分「字段不存在」和「字段过期」—— 这两者处理方式**相反**。
    hb = st.get("heartbeat_ts")
    if hb is None:
        # 旧版（≤ 4f53425）写的状态文件没有心跳字段，**只在升级窗口出现一次**。
        # 那时 pid 确实还活着、批次真的在跑。
        # ★ 这里必须**保守当"在跑"**：抢先接管会让两批并发发 webhook，
        #   一次 429 能废掉几百条（README 坑 4）。少跑一轮的代价小得多。
        #   下一批用新代码写状态后就带上心跳了，此分支自然消失。
        LOG.warning("状态文件是旧版格式（无 heartbeat_ts），但 pid %s 仍在 ——"
                    " 保守当作「上一批还在跑」，本轮跳过。下批起恢复正常。", pid)
        return True

    stale = time.time() - float(hb or 0)
    if stale <= HEARTBEAT_STALE_SEC:
        return True
    LOG.warning("状态文件里的 pid %s 仍存在，但心跳已停 %.0f 分钟"
                "（PID 复用？进程卡死？）—— 判定为残留，接管本轮",
                pid, stale / 60)
    return False


def log_result(pack: str, stats: S.DriveStats | None) -> None:
    if stats is None:
        LOG.info("[%s] 本批无动作（没待搜或计划为空）", pack)
        return
    sleep_sec, reason = next_sleep(stats)
    LOG.info("[%s] %s | 原因：%s | 下次间隔 %.0f 分钟", pack,
             stats.render().splitlines()[0], reason, sleep_sec / 60)
    if stats.newly_seeding:
        LOG.info("  → 本轮新增做种 %d 部 🎉", stats.newly_seeding)
    if stats.still_skipped:
        LOG.warning("  → 仍有 %d 部被退避（站点侧 502/限流？见 SUMMARY §6.5）",
                    stats.still_skipped)


def once_round(packs: list[str], args, api_key: str, min_sleep: float) -> int:
    """`--once` 单批模式：跨进程节流（防计划任务唤醒重叠）+ 包轮换持久化。

    - 上一批还在跑（pid 活着）→ 直接退出
    - 距上次批次结束不足 min_sleep → 直接退出（防猛打）
    - 否则跑「轮到的那个包」一批，并把 {结束时间, 包序号} 写回状态文件
    """
    st = read_state()
    if batch_alive(st):
        LOG.info("上一批（pid %s）仍在运行，跳过本轮", st.get("running_pid"))
        return 0
    last_end = float(st.get("last_end_ts") or 0)
    gap = time.time() - last_end
    if last_end and gap < min_sleep:
        LOG.info("距上次批次结束仅 %.1f 分钟（< %.0f 分钟），跳过本轮",
                 gap / 60, min_sleep / 60)
        return 0

    idx = (int(st.get("last_pack_idx", -1)) + 1) % len(packs)
    pack = packs[idx]
    write_state({**st, "running_pid": os.getpid(), "heartbeat_ts": time.time()})
    LOG.info("[--once] 跑包 %s（第 %d/%d 个）", pack, idx + 1, len(packs))

    stats = None
    rc = 0
    failed = False
    try:
        # 心跳线程只包住跑批阶段：跑完就停，免得和下面 finally 写状态打架
        with Heartbeat():
            stats = run_round(pack, args, api_key)
        log_result(pack, stats)
        if stats is None:
            # 这个包没待搜 —— 看看是不是所有包都干完了（无人值守时必须出声）
            alert_if_all_done(packs, args.db)
    except Exception:  # noqa: BLE001 —— 单批异常也要正确收尾状态
        LOG.exception("[%s] 本批异常", pack)
        failed, rc = True, 1
    finally:
        # 连续失败计数跨进程持久化（无人值守下没人盯着，只能靠日志喊）
        streak = update_abort_streak(int(st.get("consec_abort") or 0), stats, failed=failed)
        write_state({"running_pid": None, "last_end_ts": time.time(),
                     "last_pack_idx": idx, "consec_abort": streak})
    LOG.info("--once 完成。")
    return rc


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
            # ★必须轮转：无人值守会跑几个月，FileHandler 只追加会涨到几百 MB
            RotatingFileHandler(
                str(HERE / "drive-loop.log"),
                maxBytes=5_000_000, backupCount=5, encoding="utf-8",
            ),
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

    # 自检：cross-seed 真实搜索范围 vs --indexers（不一致会静默错记，务必先喊出来）
    check_indexers(args)

    # 自检：cross-seed 是否正够不着某些索引器（头号复发坑 = .env 没生效到容器）
    check_env_applied(args)

    # key：--api-key 显式给优先，否则从 --env 读
    api_key = args.api_key
    if not api_key:
        env_path = Path(args.env)
        if env_path.is_file():
            api_key = read_key_from_env(env_path)
        if not api_key:
            LOG.error("找不到 CROSSSEED_API_KEY（--api-key 或 --env 的 .env）")
            return 2

    # 批次之间的最小间隔（常驻模式用它 sleep；--once 模式用它拦掉过密的唤醒）
    min_sleep = args.min_sleep or MIN_SLEEP

    # --once：单批模式（配合 Windows 计划任务）。跨进程节流 + 包轮换见 once_round()。
    if args.once and not args.dry_run:
        return once_round(packs, args, api_key, min_sleep)

    round_no = 0
    # 包轮流：记录上次跑到哪个包，下次从下一个开始
    cur_pack_idx = 0
    consec_abort = 0     # 连续失败批数（跨过阈值就大声报警）
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
                                   cadence_by_indexer=S.parse_cadence(args.cadence))
            pairs, plan = S.apply_batch(pairs, limit=args.limit, batch=args.batch)
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
            consec_abort = update_abort_streak(consec_abort, None, failed=True)
            if args.once:
                return 1
            time.sleep(BACKOFF_SLEEP)
            cur_pack_idx += 1
            continue

        if stats is None:
            LOG.info("[%s] 本批无动作（没待搜或计划为空），跳过该包", pack)
            consec_abort = update_abort_streak(consec_abort, None)   # 正常，清零
            # 全部包都没待搜 → 全部完成，退出
            cur_pack_idx += 1
            if cur_pack_idx % len(packs) == 0:
                if alert_if_all_done(packs, args.db):
                    return 0
            if args.once:
                return 0
            time.sleep(min_sleep)
            continue

        sleep_sec, reason = next_sleep(stats)
        consec_abort = update_abort_streak(consec_abort, stats)
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

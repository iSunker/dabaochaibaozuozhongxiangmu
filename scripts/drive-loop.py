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

调度（2026-09-11 起跑在 NAS 上，Windows 计划任务已停用）
--------------------------------------------------------
NAS 侧用 DSM 任务计划，每 15 分钟唤醒一次：
  控制面板 → 任务计划 → 用户定义的脚本，用户选 root，频率「每 15 分钟」
  脚本 = sh /volume2/docker_ssd/prowlarr_cross-seed_autohardlink/drive-loop/run.sh

`--once` 模式下每次唤醒只跑一批；`--min-sleep` 保证不会连续猛打。
★ 为什么在 NAS 上跑（原本是 Windows 计划任务）—— 两个独立的坑，见 SUMMARY §14：
  ① Windows 任务计划的 <StopOnIdleEnd>true（默认配置，不是代码问题）：
     你一动鼠标/键盘就**直接 TerminateProcess 整个任务实例**，
     表现是批次「凭空消失」：没有 traceback、没有 finally 收尾、状态文件里
     running_pid 永远挂着，之后每轮都空转。
  ② 包装器 drive-loop-once.cmd 曾是 LF 行尾：cmd.exe 按字节块读批处理文件，
     LF-only 会让它从某行中间开始执行（REM 注释的单词被当命令跑），
     set 的变量全丢 → 留下 exit=9009 且**有 exit= 没有 start=**。已修成 CRLF。
  根因与完整证据见 README「把调度挂到 NAS 上」+ SUMMARY §14。
"""
# ★ 必须放在所有其它 import 之前 —— 这行是 Python 3.10 以下能跑起来的前提。
#   本文件通篇用 `str | None` / `list[str]` 这种写法，它们在 <3.10 上会在
#   **函数定义时**当场求值并抛 TypeError（不是等到调用）。PEP 563 让所有注解
#   退化成字符串、不求值，于是 3.8 也能正常导入。
#   ★ NAS 上系统 python3 就是 3.8.15（DSM 自带，没有更新的）——
#     所以这不是「顺手加的好习惯」，是运行前提：去掉它 drive-loop 在 NAS 上
#     会在 import 阶段就崩，且**连一行日志都写不出来**（崩在 logging 配置之前）。
#   本项目的 state.py / notify.py / reseed-state.py 早就带了这行，这里补齐。
from __future__ import annotations

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

# 通知（可选）。Windows 侧只往 NAS 的 spool 写纯文本事件文件，零凭据；
# 发信由 NAS 上的 notify-spool.sh 读 DSM 自己的 SMTP 配置完成（见 notify.py）。
# ★ 用 try 包住：notify.py 缺失/损坏也不该让跑批起不来 —— 通知是附属功能。
try:
    import notify as _notify  # noqa: E402
except Exception:  # noqa: BLE001
    _notify = None

LOG = logging.getLogger("drive-loop")

# sidecar 状态库默认位置（与 reseed-state.py 的 DEFAULT_DB 保持一致）
DEFAULT_DB = os.environ.get("RESEED_STATE_DB", str(ROOT / "hlink" / "state.db"))


# --------------------------------------------------------------------------- #
# cross-seed 的 compose 目录 —— 同一批文件，两种视角
# --------------------------------------------------------------------------- #
# 这个目录在哪台机器上看，写法不一样：
#
#   在 NAS 本机（DSM 计划任务跑）： /volume2/docker_ssd/prowlarr_cross-seed_autohardlink
#   在 Windows（经 SMB 跑）：       //iSunker-DS423/docker_ssd/prowlarr_cross-seed_autohardlink
#
# ★ 顺序必须「NAS 原生优先」：
#   在 NAS 上 UNC 写法虽然也能通（等于从本机绕一圈 SMB 连回自己），但慢、且
#   依赖 SMB 服务；原生路径一定在。反过来在 Windows 上原生路径不存在，
#   自动落到第二项 —— 于是同一份代码、同一条命令行两边都能跑，
#   不需要维护两套参数（这正是 2026-09-11 把驱动搬到 NAS 时想要的：
#   搬迁只是换个地方执行，不是分叉出第二个版本）。
CROSSSEED_DIRS = (
    "/volume2/docker_ssd/prowlarr_cross-seed_autohardlink",
    "//iSunker-DS423/docker_ssd/prowlarr_cross-seed_autohardlink",
)


def first_existing(rel: str) -> str | None:
    """在 CROSSSEED_DIRS 里找第一个存在的 `rel`，返回完整路径；都没有返回 None。

    ★ 找不到时**必须让调用方出声**（见 main() 里两处 LOG.warning）：
      这两个文件缺失会让「回灌」静默退化 —— cross-seed.db 没了就推不出
      MATCH/SEEDING，info 日志没了就推不出「是否在做种」，结果是 SEEDING
      被误降级成 MATCHED。数算错但**不报错**，正是无人值守最怕的那种坏法。
    """
    for d in CROSSSEED_DIRS:
        p = Path(d) / rel
        if p.is_file():
            return str(p)
    return None


# --------------------------------------------------------------------------- #
# 通知出口（可选）
# --------------------------------------------------------------------------- #
# 事件分两档，由 notify.Event.level 决定 NAS 侧怎么处理：
#
#   alert       → **立刻发信**（自检报警 / 连续失败 / 整批异常）
#   batch, info → 只归档，进**每日摘要**（本批新增做种数、全部干完等）
#
# ★ 这正是「坏消息 + 每日摘要」的分工：好消息不该半夜吵醒人，
#   但也不能只躺在几万行日志里 —— 摘要就是它的去向。
#
# ★ 为什么用模块级单例，而不是给每个函数加参数：
#   这些自检散落在 check_indexers / update_abort_streak / once_round 里，
#   签名各不相同，层层传参会污染每一个调用点。通知是**旁路**，
#   和 LOG 同性质 —— 用同样的方式持有最省事（测试里可直接赋值 _NOTIFIER）。
_NOTIFIER = None


def init_notifier(args):
    """按命令行参数建 Notifier。可重复调用（重建）。"""
    global _NOTIFIER
    if _notify is None:
        return None
    _NOTIFIER = _notify.notifier_from_args(args)
    return _NOTIFIER


def emit(kind: str, title: str, body: str = "", *,
         key: str | None = None, metrics: dict | None = None) -> bool:
    """投递一个通知事件。未启用/写失败 → False。**绝不抛异常**（见 notify.Notifier）。"""
    if _NOTIFIER is None:
        return False
    return _NOTIFIER.emit(kind, title, body=body, key=key, metrics=metrics)


def describe_notifier() -> str:
    """给启动日志用的一句话，让人一眼看出通知到底通没通。"""
    if _notify is None:
        return "✗ 未启用（找不到 notify.py）"
    if _NOTIFIER is None:
        return "✗ 未启用"
    if not _NOTIFIER.enabled:
        return "✗ 已禁用（--no-notify 或 NOTIFY_DISABLE）"
    if _NOTIFIER.dry_run:
        return "试运行（只打印，不写文件）"
    return f"✓ 启用 → {_NOTIFIER.spool}"


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
    # 推给对方。★ 固定 key + 12 小时冷却 = 问题不修每天最多提醒 2 次：
    #   连续失败第 4、5、6… 批都命中同一个 key，不会变成每 30 分钟一封。
    emit("alert",
         f"连续 {n} 批失败（{reason}）",
         body=(f"最近一次失败：{reason}\n连续失败批数：{n}\n\n"
               "无人值守下通常意味着：\n"
               "  ① 站点持续 502 / 限流（看 Prowlarr 里各站状态）\n"
               "  ② .env 改了但容器没 force-recreate（见 SUMMARY §13.6）\n\n"
               "请人工看一眼 cross-seed 日志与 Prowlarr。\n"
               "（本条同 key 12 小时内不重复发；修好后自然消失。）"),
         key="consec-abort", metrics={"streak": n})
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
    # ★ 归到 batch（进每日摘要），不归 alert：这是**里程碑**，不是故障。
    #   按「坏消息立刻发 + 每日摘要」的分工，它应该出现在日报里而不是半夜的告警里。
    #   固定 key + 冷却：全干完之后每次唤醒都会走到这里，不冷却会刷屏。
    emit("batch", f"全部包已无待搜项（{len(packs)} 个包）",
         body=("所有包的片子都已经搜过/做种，自动循环已无事可做。\n\n"
               "  计划任务可以保留 —— 接入新站或新增片子后会自动变回待搜；\n"
               "  也可以停掉：schtasks /Delete /TN \"reseed-drive-loop\" /F\n"),
         key="all-done", metrics={"packs": len(packs)})
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
        for lbl in unnamed:
            emit("alert", f"索引器拉不到名字：{lbl}",
                 body=(f"cross-seed 里有个 active 索引器取不回 caps：{lbl}\n\n"
                       "  ★ 编号 N 是 TORZNAB_URLS 里的那个（#N = /N/api），\n"
                       "    **不是** Prowlarr 界面里的索引器序号 —— 别找错站。\n\n"
                       "  常见原因：\n"
                       "   ① .env 里删了这个站，但容器没重建（容器里还留着它）\n"
                       "   ② 该站被 Prowlarr 禁用了\n"
                       "   ③ 站点返回 410/403 或卡 Cloudflare\n\n"
                       "  查证：docker inspect reseed-cross-seed | grep TORZNAB_URLS\n"),
                 key=f"indexer-unnamed:{lbl}", metrics={"indexer": lbl})
    if missing:
        LOG.warning("⚠ cross-seed 实际会搜 %s，但 --indexers 没列 ——"
                    " 这些站的搜索结果会被状态机**漏记**（→ 重复搜 / 永不重搜）。",
                    ", ".join(missing))
        LOG.warning("  建议把 --indexers 改成：--indexers %s", ",".join(named))
        emit("alert", f"--indexers 漏了 {len(missing)} 个站：{', '.join(missing)}",
             body=(f"cross-seed 实际会搜：{', '.join(named)}\n"
                   f"但 --indexers 只列了：{', '.join(sorted(mine))}\n\n"
                   f"漏掉的：{', '.join(missing)}\n\n"
                   "后果：这些站搜到的结果会被状态机**漏记** ——\n"
                   "  要么反复重搜（浪费站点额度），要么永远不重搜。而且**不报错**，只是数算错。\n\n"
                   f"修法：把 --indexers 改成  {','.join(named)}\n"
                   "     （Windows 计划任务的 /TR 参数里也有一份，两处都要改）\n"),
             key=f"indexer-missing:{','.join(missing)}", metrics={"missing": len(missing)})
    if extra:
        LOG.warning("⚠ --indexers 列了 %s，但 cross-seed 根本不会搜 ——"
                    " 状态机会把它们记成'搜过'，实际是假的（→ 永远不会去搜）。",
                    ", ".join(extra))
        emit("alert", f"--indexers 多了 {len(extra)} 个站：{', '.join(extra)}",
             body=(f"--indexers 列了：{', '.join(extra)}\n"
                   f"但 cross-seed 根本不会搜它们（不在它的 TORZNAB_URLS 里）。\n\n"
                   "后果：状态机会把这些站记成「搜过」，实际是假的 —— 片子永远不会被搜。\n\n"
                   "修法：从 --indexers 里删掉（计划任务的 /TR 参数里也有一份，两处都要改）。\n"),
             key=f"indexer-extra:{','.join(extra)}", metrics={"extra": len(extra)})
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

#: **只有这几种码**算「配置没生效」。
#:   410 = 索引器在 Prowlarr 里已经没了；401 = apikey 对不上；403 = 该站被禁用。
#:   三者都是「改了 .env 但容器没重建」的表现 —— 正是本自检要抓的东西。
#:
#: ★ 429 **必须排除**。它是限流，实测长这样（注意是**站名**不是 URL，还带原因说明）：
#:
#:     warn: [webhook] Failed to reach HDFans: request failed with code 429
#:           due to rate limiting, snoozing until 2026-09-11 21:00:53
#:
#:   限流是**周期性的正常现象**，退避逻辑自己会处理，跟 .env 毫无关系。
#:   上面那个宽泛的正则会把 429 一起捞进来（`\S+?` 连站名也匹配），
#:   于是推出一封「.env 未生效：HDFans 返回 429」——**把人骗去白重建一次容器**。
#:   日志里它只是条误导性警告，一旦接上邮件就成了真骚扰。
STALE_ENV_CODES = frozenset({"410", "401", "403"})


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

    ★ 429 **不算** —— 那是限流，正常现象，退避逻辑自己会处理（见 `STALE_ENV_CODES`）。

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
            if m["code"] not in STALE_ENV_CODES:
                # 429 之类的限流 —— 退避逻辑自己会处理，不是配置问题（见 STALE_ENV_CODES）
                LOG.debug("忽略非配置类错误：%s → HTTP %s", m["url"], m["code"])
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

    # 推给对方。**逐 (url, code) 一条** —— 每个都是独立可修的问题，
    # 分开去重才能在「修好一个、还剩一个」时继续提醒。
    for (url, code), n in sorted(hits.items(), key=lambda kv: -kv[1]):
        emit("alert", f".env 未生效：{url} 返回 {code} ×{n}",
             body=(f"cross-seed 最近 {STALE_ENV_WINDOW_SEC / 3600:.0f} 小时内"
                   f"**一直够不着**这个索引器。\n\n"
                   f"  地址: {url}\n"
                   f"  HTTP: {code}\n"
                   f"  次数: {n}\n"
                   f"  最近一次: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(newest))}\n\n"
                   "★ 本项目的头号复发坑：**改了 .env，但容器没重建**。\n"
                   "  410 = 该索引器在 Prowlarr 里已经没了，容器里的 TORZNAB_URLS 还留着它；\n"
                   "  401 = apikey 对不上；403 = 该站被禁用。三者多半是同一件事。\n\n"
                   "  ⚠ `docker compose restart` **不重新注入环境变量**，必须：\n\n"
                   "  cd /volume2/docker_ssd/prowlarr_cross-seed_autohardlink \\\n"
                   "    && sudo docker compose up -d --no-deps --force-recreate cross-seed\n\n"
                   "  修好后本条自动消失（同 key 12 小时内不重复发）。\n"),
             key=f"env-stale:{url}/{code}",
             metrics={"url": url, "code": code, "n": n})


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

    # ★ 必须把 on_event 接到 LOG 上，否则整批**全程零输出**（2026-09-12 凌晨踩过，
    #   当时对着空日志怀疑批次被杀了，白查一轮）。
    #   DriveSession 自己**不写任何日志**，进度全靠这个回调；不传时它默认是
    #   `lambda *a, **k: None`（见 orchestrator/state.py:1517）。于是最长的那一段
    #   （50 部 × --interval 30s ≈ 25 分钟起，撞上站点退避还可能再等 max_wait）
    #   在 drive-loop.log 里一个字都没有 —— 从日志上**无法区分**
    #   「在正常推进」和「卡死在第 3 部」。无人值守的系统在最长的阶段没有可观测性，
    #   这是实打实的缺陷，不是"日志打得少"而已。
    #   对照：reseed-state.py 的 drive 子命令一直有接（reseed-state.py:452），
    #   所以手工跑的时候看得到进度 —— 差别只在于这里漏传了参数。
    last = [0.0]

    def on_event(kind, *rest):
        now = time.time()
        if kind == "sent":
            pth, code, i, total = rest
            tag = "OK" if code in (200, 202, 204) else "!!"
            gap = f" (+{now - last[0]:.0f}s)" if last[0] else ""
            last[0] = now
            LOG.info("  [%d/%d] %s %s%s  %s", i, total, tag, code, gap,
                     Path(pth).name[:56])
        elif kind == "wait":
            LOG.info("  ⏸  %s", rest[0])
        elif kind == "warn":
            LOG.warning("  !  %s", rest[0])
        elif kind == "abort":
            LOG.error("  ✗  %s", rest[0])
        elif kind == "drained":
            LOG.info("  ·  %s", rest[0])

    sess = S.DriveSession(
        url=args.url,
        api_key=api_key,
        crossseed_db=args.db_path,
        interval=args.interval,
        check_every=args.check_every,
        max_wait=args.max_wait,
        timeout=args.timeout,
        pause_on_backoff=not args.no_pause_on_backoff,
        on_event=on_event,
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
    # 批次事件 → 只进每日摘要（不立刻发信）。好消息不该半夜吵醒人，
    # 但也不能只躺在几万行日志里 —— 摘要就是它的去向。
    # ★ key 不含时间戳，且 batch 不冷却（见 notify._cooled），所以每批都会进摘要；
    #   摘要正是靠这些行统计「最近两次运行窗口的批次数」。
    emit("batch", f"{pack} 本批完成",
         body=(f"包: {pack}\n"
               f"发送: 成功 {stats.ok} / 失败 {stats.failed}\n"
               f"新增做种: {stats.newly_seeding} 部\n"
               f"仍 SKIPPED: {stats.still_skipped}\n"
               f"退避: {stats.backoff_hits} 次（等待 {stats.waited_sec / 60:.1f} 分钟）\n"
               f"回灌: 搜过 {rep.from_db + rep.from_log} / 匹配 {rep.matched}\n"),
         key=f"batch:{pack}",
         metrics={"pack": pack, "ok": stats.ok, "failed": stats.failed,
                  "newly_seeding": stats.newly_seeding,
                  "still_skipped": stats.still_skipped,
                  "backoff_hits": stats.backoff_hits})
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
        emit("alert", f"{pack} 本批异常",
             body=(f"跑包 {pack} 时抛出异常（详见 drive-loop.log 的 traceback）。\n\n"
                   "常见原因：\n"
                   "  · cross-seed 没起来 / API 连不上\n"
                   "  · state.db 被占用（另一批还在跑？）\n"
                   "  · NAS 掉线（SMB 路径读不到）\n\n"
                   "★ 连续异常会自动累计：到 3 批会再发一条「连续批失败」告警。\n"),
             key=f"batch-exception:{pack}", metrics={"pack": pack})
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
    # --- 通知 ---
    ap.add_argument("--notify-spool", dest="notify_spool", default=None,
                    help="通知事件文件写到哪（默认 NAS 上的 notify/spool，见 notify.py；"
                         "也可用环境变量 NOTIFY_SPOOL）")
    ap.add_argument("--no-notify", action="store_true",
                    help="本次不写任何通知事件（也可用环境变量 NOTIFY_DISABLE=1）")
    ap.add_argument("--notify-cooldown-hours", dest="notify_cooldown_hours",
                    type=float, default=12.0,
                    help="同一个告警 key 多久内不重复发（默认 12 小时；0=不冷却，慎用）")
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

    # 默认日志路径（cross-seed 的 info 日志），回灌要用
    if not args.log:
        p = first_existing("cross-seed/logs/info.current.log")
        if p:
            args.log = [p]
            LOG.debug("info 日志：%s", p)
        else:
            LOG.warning("⚠ 找不到 cross-seed 的 info 日志（试过 %s）——"
                        " 回灌将**推不出「是否在做种」**，原本 SEEDING 的片子会被"
                        " 误降级成 MATCHED。", " 和 ".join(CROSSSEED_DIRS))

    # 默认 cross-seed.db 路径
    if not args.db_path:
        p = first_existing("cross-seed/cross-seed.db")
        if p:
            args.db_path = p
            LOG.debug("cross-seed.db：%s", p)
        else:
            LOG.warning("⚠ 找不到 cross-seed.db（试过 %s）——"
                        " 回灌与索引器自检都会跳过，状态机会停止更新。",
                        " 和 ".join(CROSSSEED_DIRS))

    # 默认 .env（取 CROSSSEED_API_KEY）。★ 默认值 ROOT/.env 在 Windows 上对，
    # 但搬到 NAS 后脚本住在 <compose>/drive-loop/，.env 在**上一级**。
    # 所以这里补一个回退：ROOT/.env 不在就去 compose 目录找。这样即使 run.sh
    # 忘了传 --env，也不会退化成"找不到 key"直接退出码 2。
    if not Path(args.env).is_file():
        for d in CROSSSEED_DIRS:
            cand = Path(d) / ".env"
            if cand.is_file():
                LOG.debug("--env 默认值 %s 不存在，改用 %s", args.env, cand)
                args.env = str(cand)
                break

    LOG.info("=== drive-loop 启动：packs=%s indexers=%s limit=%d ===",
             packs, args.indexers, args.limit)

    # 通知：必须在 check_indexers / check_env_applied **之前**建好 ——
    # 那两个自检本身就会发告警（这恰恰是最需要有人看到的两个）。
    init_notifier(args)
    LOG.info("通知: %s", describe_notifier())
    if _NOTIFIER is not None and _NOTIFIER.enabled and not _NOTIFIER.dry_run:
        if not _NOTIFIER.spool.parent.is_dir():
            LOG.warning("  ⚠ 通知目录的上级不存在：%s", _NOTIFIER.spool.parent)
            LOG.warning("    NAS 没挂上？事件会写失败（不影响跑批），先跑一次 "
                        "notify-spool.sh 或在 NAS 上建好该目录。")

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
            emit("alert", f"{pack} 本批异常",
                 body=(f"跑包 {pack} 时抛出异常（详见 drive-loop.log 的 traceback）。\n\n"
                       f"{type(e).__name__}: {e}\n\n"
                       "常见原因：cross-seed 没起来 / state.db 被占用 / NAS 掉线。\n"
                       "★ 连续异常会自动累计：到 3 批会再发一条「连续批失败」告警。\n"),
                 key=f"batch-exception:{pack}", metrics={"pack": pack})
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

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
反馈驱动循环 —— 自动续跑 cross-seed 搜索，无需人盯。

原理
----
每次跑一批 `drive --limit N --apply`，跑完读 `DriveStats` 的三个信号：
  * `still_skipped > 0` 或 `backoff_hits > 0`  → 站点在退避/限流 → 下次间隔拉长
    ★ 但退避**按实际等待时长分级**（见 next_sleep）：站点打 1 分钟喷嚏不该罚 2 小时
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

调度（2026-09-11 起跑在 NAS 上）
--------------------------------------------------------
NAS 侧用 DSM 任务计划，每 15 分钟唤醒一次：
  控制面板 → 任务计划 → 用户定义的脚本，用户选 root，频率「每 15 分钟」
  脚本 = sh /volume2/docker_ssd/prowlarr_cross-seed_autohardlink/drive-loop/run.sh

`--once` 模式下每次唤醒只跑一批。批间隔 = `max(--min-sleep, 上一批 next_sleep 的结论)`，
由 `.drive-loop.state` 的 `last_sleep_sec` 跨进程传递 —— 于是「站点在退避就缓一缓」
真的会生效，而不只是往日志里写一行字（2026-09-12 之前就是那样，见 once_round）。

★★ 电脑端（Windows）已于 2026-09-12 退役，只保留 deploy.sh（见 README「电脑端已不参与」）。
   下面这两条是**当时**为什么要搬走的记录 —— 不是待办，是历史，别再照着它去配 Windows 任务。

★ 为什么当初要搬到 NAS（原本是 Windows 计划任务）—— 两个独立的坑，见 SUMMARY §14：
  ① Windows 任务计划的 <StopOnIdleEnd>true（默认配置，不是代码问题）：
     你一动鼠标/键盘就**直接 TerminateProcess 整个任务实例**，
     表现是批次「凭空消失」：没有 traceback、没有 finally 收尾、状态文件里
     running_pid 永远挂着，之后每轮都空转。
  ② 包装器 drive-loop-once.cmd 曾是 LF 行尾：cmd.exe 按字节块读批处理文件，
     LF-only 会让它从某行中间开始执行（REM 注释的单词被当命令跑），
     set 的变量全丢 → 留下 exit=9009 且**有 exit= 没有 start=**。已修成 CRLF。
     （该 .cmd 已于 2026-09-12 删除 —— 退役的不是"修好它"，是"不再需要它"。
       所以别看到"已修成 CRLF"就以为那个文件还在。）
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
# [电脑端已退役 2026-09-12] subprocess 原先只给 Windows 的 tasklist 分支用，
# 那支已注释掉（见 pid_alive）。
# ★ 2026-09-12 恢复启用：现在由**农场巡检** `check_farm()` 用（起 build-farm.sh --verify）。
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

# 通知（可选）。只往 NAS 本机的 spool 写纯文本事件文件，零凭据；
# 发信由 NAS 上的 notify-spool.sh 读 DSM 自己的 SMTP 配置完成（见 notify.py）。
# ★ 电脑端退役前是"Windows 写进 NAS 的 spool"，现在跑批和 spool 同在 NAS 上。
# ★ 用 try 包住：notify.py 缺失/损坏也不该让跑批起不来 —— 通知是附属功能。
try:
    import notify as _notify  # noqa: E402
except Exception:  # noqa: BLE001
    _notify = None

LOG = logging.getLogger("drive-loop")

# sidecar 状态库默认位置（与 reseed-state.py 的 DEFAULT_DB 保持一致）
DEFAULT_DB = os.environ.get("RESEED_STATE_DB", str(ROOT / "hlink" / "state.db"))

#: `--packs` 的默认名单 —— 本仓库里**唯一**一处「哪个包会被驱动」的声明。
#: ★ 之所以提成模块常量、而不是留在 argparse 那一行里：这个值同时被**两处**引用
#:   —— argparse 的默认值，和声明点清单里的对账（`reconcile_watch` 的第四类）。
#:   两处各写一份字面量就会漂；今天已经漂过一次同形状的（文档里写的
#:   `drive-loop.py:1487` 被我加几行注释推成了 1510）—— 所以**按符号引用，不按行号**。
#: ★ 它**不是**一行等着被"消除"的代码债，是一个产品决定：名单从 2 个包变成 3 个，
#:   会把 dc/frds 各自的**轮换频率从 1/2 掉到 1/3**（`once_round` 取模就是它），
#:   而换上来的是 `mbf` —— 一个记录在案的 0 匹配包。要不要换，不是重构能定的。
PACKS_DEFAULT = "dc-collection,frds-top250-2024"


# --------------------------------------------------------------------------- #
# cross-seed 的 compose 目录
# --------------------------------------------------------------------------- #
# 在 NAS 本机（DSM 计划任务跑）： /volume2/docker_ssd/prowlarr_cross-seed_autohardlink
#
# ★★ 2026-09-12：**电脑端已退役**，UNC 兜底已注释掉（保留可查，别删注释）。
#   留着的理由不是"以后可能还用" —— 是这段注释本身记着一个坑：2026-09-11 之前，
#   同一份代码要在 Windows 和 NAS 两边都能跑，所以这里得有"NAS 原生优先、
#   Windows 落 UNC"的顺序。现在只剩 NAS 一个执行环境，多一条候选路径
#   就多一个「哪天 NAS 路径写错，它会**悄悄**绕回 SMB 连自己」的静默降级点 ——
#   那种情况不会报错，只是变慢，属于最难查的一类。
#   要回退：取消下面那行的注释即可（代码本身没错，是场景没了）。
CROSSSEED_DIRS = (
    "/volume2/docker_ssd/prowlarr_cross-seed_autohardlink",
    # [电脑端已退役 2026-09-12] 原本是 Windows 经 SMB 跑时的兜底路径：
    # "//iSunker-DS423/docker_ssd/prowlarr_cross-seed_autohardlink",
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
BACKOFF_SLEEP = 60 * 120     # 站点在压我们 → 拉长到 2 小时
SNOOZE_SLEEP = 60 * 90       # 中等退避 → 放缓到 1.5 小时
ABORT_SLEEP = 60 * 180       # 提前中止（退避等太久），休整 3 小时

MIN_SLEEP = 60 * 30          # 硬下限：任何情况批间隔不少于 30 分钟
MAX_SLEEP = 60 * 240         # 硬上限：4 小时

# ---- 退避分级的阈值（2026-09-12）------------------------------------------- #
# `backoff_hits > 0` 只说明「见到过限流」，**不说明被耽误了多久**：实测的 429
# 只 snooze 30~60 秒，站点转头就恢复，跟「站点持续压着我们」是两回事。
# 一律罚 2 小时，等于把打喷嚏和重感冒当同一种病。所以按这批**实际等掉的时间**
# （`waited_sec`）分档 —— 没真耽误我们的，就别惩罚。
#
#   waited < BACKOFF_SHORT_SEC          → 喷嚏，按基准 45 分钟
#   BACKOFF_SHORT_SEC ≤ waited < BACKOFF_LONG_SEC → 放缓到 1.5 小时
#   waited ≥ BACKOFF_LONG_SEC           → 站点确实在压，拉满 2 小时
#
# ★ 想回到「命中就 2 小时」的老行为：把两个阈值都设成 0 即可。
# ★ 「等了 0 秒却记了一笔」是**故意**的：那一笔来自「窗口落在两次检查之间、
#   我们压根没等」的限流 —— 它确实发生过，记进 backoff_hits 供观测，但既然
#   没挡住我们，就不该改间隔。这正是本次分级的核心目的。
BACKOFF_SHORT_SEC = 180.0    # 3 分钟
BACKOFF_LONG_SEC = 600.0     # 10 分钟


def clamp(s: float) -> float:
    return max(MIN_SLEEP, min(MAX_SLEEP, s))


def next_sleep(stats: S.DriveStats) -> tuple[float, str]:
    """根据上一批的结果决定下次批间隔。返回 (秒, 原因)。"""
    if stats.aborted:
        return ABORT_SLEEP, f"提前中止：{stats.aborted}"
    # ★ still_skipped 与 backoff_hits 性质不同，不参与分级：
    #   前者是「真有片子没推进」（结果问题），后者只是「站点限过流」（过程噪声）。
    if stats.still_skipped > 0:
        return BACKOFF_SLEEP, f"仍有 {stats.still_skipped} 部被退避跳过"
    if stats.backoff_hits > 0:
        w = stats.waited_sec
        if w >= BACKOFF_LONG_SEC:
            return BACKOFF_SLEEP, (f"本轮 {stats.backoff_hits} 次退避、等了 "
                                   f"{w / 60:.1f} 分钟，站点在限流")
        if w >= BACKOFF_SHORT_SEC:
            return SNOOZE_SLEEP, (f"本轮 {stats.backoff_hits} 次退避、等了 "
                                  f"{w / 60:.1f} 分钟，放缓一档")
        return BASE_SLEEP, (f"短暂退避 {stats.backoff_hits} 次（{w:.0f} 秒），"
                            "站点已恢复，按基准")
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
                   "     ★ 改 **<compose>/drive-loop/run.sh** 里那一行"
                   "（--indexers HDFans,NanyangPT）——\n"
                   "       电脑端已退役，没有第二处要改了。\n"),
             key=f"indexer-missing:{','.join(missing)}", metrics={"missing": len(missing)})
    if extra:
        LOG.warning("⚠ --indexers 列了 %s，但 cross-seed 根本不会搜 ——"
                    " 状态机会把它们记成'搜过'，实际是假的（→ 永远不会去搜）。",
                    ", ".join(extra))
        emit("alert", f"--indexers 多了 {len(extra)} 个站：{', '.join(extra)}",
             body=(f"--indexers 列了：{', '.join(extra)}\n"
                   f"但 cross-seed 根本不会搜它们（不在它的 TORZNAB_URLS 里）。\n\n"
                   "后果：状态机会把这些站记成「搜过」，实际是假的 —— 片子永远不会被搜。\n\n"
                   "修法：从 --indexers 里删掉它们\n"
                   "     ★ 改 **<compose>/drive-loop/run.sh** 里那一行"
                   "（--indexers HDFans,NanyangPT）——\n"
                   "       电脑端已退役，没有第二处要改了。\n"
                   "     ⚠ 但删之前先分清是哪种「多了」—— 删错了会把新站**永远**排除：\n"
                   "       ① 只在 --indexers 里写过、.env 里没有它 → 照上面删掉。\n"
                   "       ② .env 的 TORZNAB_URLS 里**有**它 → 那是容器没重建\n"
                   "          （env_file 的改动不重建容器不生效），正确修法是\n"
                   "             sudo docker compose up -d --force-recreate cross-seed\n"
                   "          **不是**删 --indexers。\n"),
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


def env_value(env_path: Path, key: str) -> str:
    """从 .env 取一个值；取不到（文件不在 / 没这个键）返回 ""。

    ★ 用 `splitlines()` 而不是 `read_text().split("\\n")`：前者会把 CRLF 的
      `\\r` 一并剥掉。`.env` 是 CRLF，而 shell 那边的 `sed` **不会**剥
      —— §16.2.1.2 那个假漂移就是这么来的。Python 这边天然没这个坑，
      但**前提是用对方法**：拿 `split("\\n")` 就会把 `\\r` 留在值里。
    ★ 一律吞掉 OSError：这类"配置缺一项"不该让调用方炸。
    """
    try:
        for ln in env_path.read_text(encoding="utf-8").splitlines():
            if ln.startswith(key + "="):
                return ln.split("=", 1)[1].strip()
    except OSError:
        pass
    return ""


def prowlarr_cfg(args) -> tuple[str, str]:
    """从 --env 指的 .env 里取 (PROWLARR_URL, PROWLARR_API_KEY)。

    ★ 凭据**只从文件读**，不提供命令行开关 —— 同 `read_key_from_env` 的理由：
      避免 key 落进 shell 历史 / 进程表 / 聊天记录。
    """
    p = Path(getattr(args, "env", "") or "")
    if not p.is_file():
        return "", ""
    return env_value(p, "PROWLARR_URL"), env_value(p, "PROWLARR_API_KEY")


# --------------------------------------------------------------------------- #
# 跑一轮（一个包的一批）
# --------------------------------------------------------------------------- #
# --------------------------------------------------------------------------- #
# 收尾通知：每日台账（额度 §16.1 + 趋势 §16.3）+ 正在退避的即时告警
#
# ★ 为什么额度进**日报**而不是告警：额度是**慢性**问题（超了不会当场炸）。
#   即时通道必须留给**急性**故障 —— 否则就是 README 警告过的
#   「每 15 分钟一封骚扰 → 你去建过滤规则 → 连真告警一起过滤掉」（§16.1.3）。
#   真正急的那条（站点**此刻**正在退避）单独走 alert，见下。
#
# ★ 来源 B（问 Prowlarr /api/v1/indexerstats）**2026-09-12 起接在这里了**。
#   原先不接的理由是"字段名没拿真实响应核对过，不把没验证过的东西塞进每轮都跑的
#   无人值守路径"。当天用真响应核对过，结构是：
#       {"indexers":[{"indexerName":..., "numberOfQueries":..., ...}],
#        "userAgents":[...], "hosts":[...]}
#   —— 与 `S.prowlarr_indexer_stats` 的解析完全一致，理由不再成立。
#   而且它现在多了一个**更重要的用途**：把「Prowlarr 里有、我们没在用」的站也摆出来，
#   那是"有别的工具在用同一个 Prowlarr"的唯一信号（§16.6）。
#   ★ 拿不到时**只写一句原因**，绝不编数（见 `attach_prowlarr_quota` 的保证）。
# --------------------------------------------------------------------------- #
DAILY_FILE = HERE / ".daily-report.state"


def _daily_last() -> str:
    try:
        return json.loads(DAILY_FILE.read_text(encoding="utf-8")).get("last_day", "")
    except Exception:                       # 文件不存在 / 坏了 —— 都当"还没发过"
        return ""


def _daily_set(day: str) -> None:
    try:
        tmp = DAILY_FILE.with_suffix(".state.tmp")
        tmp.write_text(json.dumps({"last_day": day}), encoding="utf-8")
        os.replace(tmp, DAILY_FILE)         # 原子替换，别让下一轮读到半个文件
    except OSError:
        LOG.debug("每日台账标记写不进去（不影响跑批）", exc_info=True)


def alert_blocked_indexers(args, *, now: datetime | None = None) -> int:
    """有站点**此刻正在**退避 → alert（即时）。返回发了几条。

    ★ `now` 只为**可测**而存在（生产调用一律省略 → 用真实时钟）。
      起因是 2026-09-12：自测里 fixture 的解禁时刻是写死的 `NOW + 1 小时`，
      而这个函数内部读的是真实时钟 —— 于是自测**上午还过、11:00 一过必挂**，
      变成一颗按钟点引爆的定时炸弹。把「此刻」变成入参，测试才能钉死时间。

    ★ 判据是 `blocking_backoffs()`（状态非 OK **且解禁时间还没到**），
      不是 `snoozed_indexers()`（只要见过限流）。差别很要命：cross-seed 的
      `status` 列**不会自动清**回 OK —— 实测 HDFans 的 `retry_after` 早就过期了、
      状态还挂着 `RATE_LIMITED`。只看"见过限流"的话，每隔一个冷却期就会为
      **同一件早就过去的事**再喊一次，喊到人不再看它 —— 那正好毁掉告警通道。
    """
    if not getattr(args, "db_path", None):
        return 0
    try:
        blocked = S.blocking_backoffs(S.read_indexer_backoff(args.db_path), now)
    except Exception:                       # 读不到就当没这回事；通知是附属功能
        LOG.debug("读退避状态失败，跳过站点告警", exc_info=True)
        return 0
    n = 0
    for b in blocked:
        until = b.until.strftime("%m-%d %H:%M") if b.until else "未知"
        if emit("alert", f"站点退避中：{b.name}",
                body=(f"{b.name} 此刻在退避（{b.status}），解禁 {until}。\n"
                      "发给它的搜索会被跳过 —— drive-loop 自己会等它解禁，"
                      "**不需要手动处理**。\n"
                      "但如果**连续几天**都在退避，说明我们搜得太勤："
                      "把周期调大（--cadence-days），或者考虑换站。"),
                key=f"indexer-blocked:{b.name}",
                metrics={"indexer": b.name, "status": b.status}):
            n += 1
    if n:
        LOG.info("已投递 %d 条「站点正在退避」告警", n)
    return n


# --------------------------------------------------------------------------- #
# IYUU 辅种条数 —— §18.8 留下的**唯一生产级证伪点**
# --------------------------------------------------------------------------- #
# 搬迁（reseed_farm → reseed/）时推断：IYUU 不存目标目录、每次从 qB 现读，所以
# 搬迁对它**透明**。**唯一能证伪这个推断的观测**，就是看它次日 01:45（它的
# cron 是 `45 1 * * *`）跑完之后，`:3060` 上 `IYUU自动辅种` 的条数还在不在涨。
#
# ★ 只记账、**不告警**：这是个慢性观测（要几天才有结论），而即时 alert 通道必须
#   留给急性故障 —— 否则就是 §16.1.3 警告过的"骚扰多了你去建过滤规则，然后连真
#   告警一起过滤掉"。它冻住了也不该当场喊。
# ★ 数字必须同时进 `metrics`：notify 的 TSV 流水只记 ts/kind/title/**metrics**，
#   **不记正文**。只写在正文里，回头分析时是拿不到的。
IYUU_TAG = "IYUU自动辅种"
IYUU_BASELINE = 100     # 2026-09-12 搬迁实测（SUMMARY §18.8 的构成表）


def iyuu_verdict(n: int, baseline: int = IYUU_BASELINE) -> str:
    """条数 → 一句话结论。**纯函数**，好钉测试。"""
    if n > baseline:
        return f"仍在增长（基线 {baseline}）"
    if n == baseline:
        return f"与基线持平（{baseline}）"
    return f"⚠ **低于**基线 {baseline}"


def iyuu_watch(args) -> tuple[str, dict]:
    """问 :3060 要 `IYUU自动辅种` 的条数 → (给正文的一行, 给 metrics 的字典)。

    ★ **绝不抛**：它挂在每天一次的日报里，而日报挂在**每 15 分钟一批**的生产
      循环里。一次 qB 抖动不该让整份日报消失（同本函数上面各节的规矩）。
    ★ 读不到时 metrics 给 `n/a` —— **必须给**，否则 TSV 里"这次读失败了"和
      "那天根本没跑"长得一模一样，事后分不开。
    """
    url = getattr(args, "qbit_url", None)
    if not url:
        return "IYUU 辅种条数：跳过（没有 --qbit-url）", {"iyuu": "no-url"}
    try:
        n = len(S.qbit_tagged(url, IYUU_TAG))
    except Exception as e:              # noqa: BLE001 —— 附属观测，绝不拖垮日报
        LOG.debug("读 IYUU 辅种条数失败", exc_info=True)
        return f"IYUU 辅种条数：读不到（{type(e).__name__}: {e}）", {"iyuu": "n/a"}
    return f"IYUU 辅种条数：**{n}** —— {iyuu_verdict(n)}", {"iyuu": n}


# --------------------------------------------------------------------------- #
# 观测对账：a − b / b − c / 全场无人认领
# --------------------------------------------------------------------------- #
# ★ 判据本体**不在这个文件里**，在 `orchestrator/state.py`
#   （`count_found_lines` / `resolve_found_lines` / `unclaimed_searchees`）。
#   理由只有一条、但是硬的：**本进程跑在 NAS 宿主机上**
#   （drive-loop-nas.sh: /usr/bin/python3），而 `scripts/audit-found-*.py` 是
#   `check-deploy-drift.py` 里的 LOCAL_ONLY（"在 Windows 上跑"）——
#   那两个文件**根本不在 NAS 上**，就算拷上来，它们写死的 `//iSunker-DS423/...`
#   在 NAS 宿主机上也不存在。`orchestrator/state.py` 被部署两次
#   （构建上下文 + drive-loop/orchestrator/），是两侧**唯一都能到达**的地方。
#   两个脚本现在是薄壳，核的是同一份实现 —— 判据只有一份。
#
# ★ 为什么挂在**日报**里而不是每批：日报是这套系统里唯一"每天恰好一次"的
#   观测出口，而且 notify 只把 `metrics` 落进 TSV 流水（不记正文）——
#   放进 `report_daily` 的 metrics，这些数才真的**留得下来**。
#   同 `iyuu_watch`。
_REDACT_SUB = (
    (re.compile(r"(apikey=)[^,&\s)\]]+", re.I), r"\1<redacted>"),
    (re.compile(r"(passkey=)[^,&\s)\]]+", re.I), r"\1<redacted>"),
)


def _redact(s: str) -> str:
    for rx, rep in _REDACT_SUB:
        s = rx.sub(rep, s)
    return s


#: 对账读数台账：记下**每一格最后一次真的读到数**是什么时候。
#: ★ 为什么不并进 `.daily-report.state`：那个文件是 `_daily_set()` **整文件覆盖写**
#:   （`tmp.write_text(json.dumps({"last_day": day}))`）—— 并进去会被静默抹掉，
#:   而且是那种"这次抹了、下次才发现"的抹法。宁可多一个文件。
RECONCILE_FILE = HERE / ".reconcile.state"

#: `.reconcile.state` 里存「声明点基线」的保留键。
#: ★ 它**不是一格读数** —— 读数是「本次读到了什么」，基线是「**现状**（已接受的差集）」。
#:   前缀 `_` 是给未来的自己看的：`n/a` 记账那一圈只遍历 `metrics` 里的键，
#:   碰不到它，所以它会被原样带过去，不会被误当成"某个格子从没读到过"。
PACKS_BASELINE_KEY = "_packs_baseline"


def _packs_norm(d) -> dict:
    """把基线/本次读数归一成可比较的形状（缺字段补空、排序）。

    ★ 归一在**读**这一侧做，而不是在**写**那侧 —— 老版本写下的文件可能是
      `{"undriven": ["mbf"]}` 而没有 `unreg` 键，读的时候不补就会 KeyError。
    """
    d = d if isinstance(d, dict) else {}
    return {"undriven": sorted(d.get("undriven") or []),
            "unreg": sorted(d.get("unreg") or [])}


def _reconcile_read() -> dict:
    try:
        d = json.loads(RECONCILE_FILE.read_text(encoding="utf-8"))
    except Exception:                       # 文件不存在 / 坏了 —— 都当"从没读到过"
        return {}
    return d if isinstance(d, dict) else {}


def _reconcile_write(ok: dict) -> None:
    try:
        tmp = RECONCILE_FILE.with_suffix(".state.tmp")
        tmp.write_text(json.dumps(ok), encoding="utf-8")
        os.replace(tmp, RECONCILE_FILE)     # 原子替换，别让下一轮读到半个文件
    except OSError:
        LOG.debug("对账读数标记写不进去（不影响跑批）", exc_info=True)


def _age_h(sec: float) -> str:
    """把秒数说成人话。**只是给人看的**，不参与任何判据。"""
    if sec < 90:
        return f"{sec:.0f} 秒前"
    if sec < 5400:
        return f"{sec / 60:.0f} 分钟前"
    if sec < 36 * 3600:
        return f"{sec / 3600:.1f} 小时前"
    return f"{sec / 86400:.1f} 天前"


def reconcile_watch(args) -> tuple[str, dict]:
    """四类对账的读数 → (给日报正文的一段, 给 metrics 的字典)。

    四条各自的对账基准（都指回判据之外的**真实记录**）：
      · a − b：`] Found ` 那个字面量会吃到别的消息（实测 2231 vs 靶心 1011），
        所以判据是**六个字面量的合取**；a == b == 1011。
      · b − c：三包**共用一个 farm_root** → **生产口径**下 other_pack 恒非零
        （实测 865 / 146 / 1011）。所以这里报的是**全量口径**的 b − c，
        并且 metrics 名带 `all` —— 不许念成"生产里没有静默丢行"。
      · 无人认领：实测 1888 条里恰好 1 条（`0观影清单chrlee整理`，只含一个 xlsx）。
        这个数才恒为 0，且非零时**每条都指得出名字**。
      · 声明点〔`--packs`〕：`pack` 表 − `--packs` 的差集，两个方向各报一份。
        实测 = 登记 3 个（`dc-collection` / `frds-top250-2024` / `mbf`）、名单 2 个
        → 差集 = {`mbf`}。它是**唯一**那种"**认得出来、只是从来不排它**"的包：
        `pack` 表有行、`movie` 表有 4 行、`farm_root` 也有 → 在 unclaimed /
        report / trend 上**全绿**。抓不到它的原因不是判据算错了，是
        **没有一条判据的输入源包含 `--packs` 的实际值**（§18.18 那个形状）。
        基线 1；**涨到 2 就是又落下一个包**。

    ★ **口径的第三个维度：这次的读是「当日日志」，不是"全量"。**
      `--log` 指向的 `info.current.log` 由 cross-seed **按天轮转**
      （实测 09-12 当天 6.2 MB，旁边躺着 `info.2026-09-11.log` 3.5 MB），
      所以这三个数天然是「**从今天 00:00 到现在**」，会随一天推进而涨。
      ★ 这不是缺陷，但必须先说清楚 —— 否则"昨天 1011、今天日报说 400"
      会被当成判据坏了。手工核总数用 `scripts/audit-found-lines.py`
      （它读的就是同一个当日文件，两者应当对得上）。
      ★ 顺带：正因为按天轮转，这里**可以**整读全文 —— 不会涨到几百 MB。
      （对比 `STALE_ENV_TAIL_BYTES` 那边只读尾部：那是**每批都跑**的热路径。）

    ★ **绝不抛**：它挂在每天一次的日报里，而日报挂在**每 15 分钟一批**的生产
      循环里。一次 SMB/库抖动不该让整份日报消失（同 `iyuu_watch` 的规矩）。
    ★ 读不到时 metrics 给 `n/a` —— **必须给**，否则 TSV 里"这次读失败了"和
      "那天根本没跑"长得一模一样，事后分不开。
    ★★ `n/a` 还差一半：它**只说明这一次**。所以本函数末尾会把"每一格最后一次
      真的读到数"的时刻记进 `.reconcile.state`，并在有 `n/a` 时写进正文 ——
      刚抖一下 vs 连续三天读不到，从此分得开（#34）。
    ★★ 但"读不到"有个**反向的**坑：`StateStore(path)` 会**把不存在的库建出来**，
      于是"库不在"会伪装成"库是空的"→ 报出一个巨大的 `unclaimed`。这里问一句
      `is_file()`（见下面的注释）；**根因**已经在 `StateStore.__init__(create=False)`
      堵上 —— 这里这一问现在是第二道，不是唯一那道。
    ★★ **三个出口的判断顺序就是判据本身**，别随手调换：
        ① `not controls_ok`   —— 判据压根没走到（连基线字面量都没数到）
        ② `delta`             —— 形状数到了、正则没吃下（**含 b == 0 的极端形**）
        ③ `b == 0`            —— 走到这 ⇒ `a == 0`，是"真没有 Found 行"，不是"正则坏了"
      旧顺序是 ①③②，于是 `a > 0 且 b == 0`（delta = a > 0，最严重的那种）
      被 ③ 吞了，正文和 metrics 互相打脸。**错的不是数，是它指向的排查动作。**
      四条分支在 `tests/test_reconcile.py` §④ 里**逐条钉了 key**。
    """
    m: dict = {"fa": "n/a", "fb": "n/a", "fd": "n/a",
               "fb_c_all": "n/a", "fb_c_farm": "n/a", "unclaimed": "n/a",
               "packs_undriven": "n/a", "packs_unreg": "n/a"}
    lines: list[str] = []
    prev_ok = _reconcile_read()             # #34：每一格上次真的读到数是什么时候
    packs_baseline = None                   # 本次算出的新基线（没算就保持 None，别抹掉旧的）

    log_path = (getattr(args, "log", None) or [None])[0]
    text = None
    if log_path:
        try:
            text = Path(log_path).read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            LOG.debug("读 cross-seed 日志失败", exc_info=True)
            lines.append(f"观测对账：读不到日志（{type(e).__name__}）—— "
                         f"a−b **没跑成**，别念成 0")
    else:
        lines.append("观测对账：跳过（没有 --log）")

    if text is not None:
        c = S.count_found_lines(text)
        m.update(fa=c.a, fb=c.b, fd=c.delta)
        lines.append(
            f"观测对账 a−b〔当日日志〕：形状 {c.a} / 正则 {c.b} / 差 {c.delta}"
            f"（期望差 0；合取比 L1 单字面量收窄了 "
            f"{c.lit_counts.get(S.L1_LABEL, 0) - c.a} 行）")
        if not c.controls_ok:
            # 控制没过 = 判据没走到，下面的 0 什么都不说明。
            emit("alert", "观测对账：判据没走通",
                 body=("日志读了，但基线一个字面量都没数到 —— 说明**匹配逻辑坏了**，"
                       "不是「没有 Found 行」。\n"
                       f"日志: {log_path}\n总行数: {c.total_lines}\n"),
                 key="reconcile-controls", metrics={"fa": c.a, "fb": c.b})
        elif c.delta:
            # ★★★ 顺序很关键：这一支必须排在 `b == 0` **前面**。
            #   旧顺序是 `controls_ok → b == 0 → delta`，于是 `a > 0 且 b == 0`
            #   （delta = a > 0，**最严重**的那种「形状对、正则一条都没吃下」）
            #   被前面的 `b == 0` 吞了：正文说「要么真没搜出去过，要么日志抓错了」，
            #   而 metrics 里 `fa` 明明白白 > 0 —— **两个字段互相打脸**。
            #   看告警的人只读正文，于是会去查「为什么没搜」，而真问题是正则整条失效。
            #   ★ 错的不是数，是它**指向的排查动作**（同 §18.17.3 那条）。
            head = "\n".join("   " + _redact(s)[:190] for s in c.unparsed) or "   （没留样本）"
            zero = ""
            if c.b == 0:
                zero = (f"★★ b == 0：**一条都没吃下** —— 形状明明数到了 {c.a} 行。\n"
                        f"   这不是「今天没搜出去」（那要 a == 0），是正则**整条失效**。\n")
            emit("alert", f"观测对账：{c.delta} 行「形状对、正则没吃下」",
                 body=(zero +
                       "有行满足目标形状的六个字面量，但**生产正则 `_RE_FOUND` 没吃下**。\n"
                       "这些行在台账里等于**没发生过** —— 抓不到 = 不存在。\n"
                       f"日志: {log_path}\n"
                       "★ 常见成因：站名/片名里出现了正则不该吃的字符（09-12 修过一次）。\n"
                       "---- 没吃下的行 ----\n" + head + "\n"),
                 key="log-parse-miss", metrics={"fa": c.a, "fb": c.b, "fd": c.delta})
        elif c.b == 0:
            # ★ 走到这里 ⇒ `delta == 0` 且 `a == 0`（上面那支已把 delta > 0 接走）。
            #   即**形状一条都没数到** —— 不是「正则没吃下」（那样 delta 会 > 0），
            #   是**根本没有 Found 行**。§18.17.3：零命中既可能是没事，也可能是没跑。
            emit("alert", "观测对账：一条 Found 都没抓到",
                 body=(f"形状行 a == 0，正则行 b == 0（★ 不是「正则没吃下」——"
                       f"那样 delta 会大于 0，那是另一条告警）。\n"
                       "**这不是「干净」** —— 要么真没搜出去过，要么日志抓错了文件。\n"
                       "回灌靠这些行推「哪个站搜到了」，b 长期为 0 时状态机的「匹配到单种」\n"
                       "会一直是 0。\n"
                       f"日志: {log_path}\n总行数: {c.total_lines}\n"),
                 key="reconcile-empty", metrics={"fa": c.a, "fb": c.b})

    # b − c 与无人认领都要真库；库不可达时**分开报**，别让一条坏了带走另一条。
    store = snap = None
    try:
        db_p = getattr(args, "db", None)
        if db_p:
            # ★★ 必须先问「文件在不在」，不能直接把它交给 StateStore ——
            #    `StateStore.__init__` 的第一件事就是 mkdir + connect +
            #    `executescript(SCHEMA)`，**库不存在时会就地建一个空的**。
            #    那样「读不到」就变成了「读到了一个空库」：pack/movie 两张表全空
            #    → `pack_contexts()` 返回 `{}` → 库里**每一条** searchee 都算
            #    「无人认领」→ 报出一个巨大的假数 + 一条醒目告警，顺带在错位置
            #    写下一个空库。**沉默被念成了数字**，正是这一格要防的方向
            #    （而且它和「零命中既可能是没事也可能是没跑」是同一个形状）。
            #    ★ 对照 `read_crossseed_db()`：它自己 `raise FileNotFoundError`，
            #      所以 `--db-path` 那一路天然走 `n/a`。这里补的正是缺掉的那一问。
            if not Path(db_p).is_file():
                lines.append(f"观测对账：状态库不在（{db_p}）—— "
                             f"b−c 与无人认领**没跑成**，别念成 0")
                LOG.debug("状态库不存在，跳过 b−c / 无人认领：%s", db_p)
                db_p = None
            else:
                store = S.StateStore(db_p)
        if getattr(args, "db_path", None):
            snap = S.read_crossseed_db(args.db_path)
    except Exception as e:                  # noqa: BLE001
        LOG.debug("开库失败", exc_info=True)
        lines.append(f"观测对账：库读不到（{type(e).__name__}）—— b−c 与无人认领没跑成")

    try:
        if text is not None and store is not None:
            rv = S.resolve_found_lines(text, store)
            m.update(fb_c_all=rv.delta, fb_c_farm=rv.farm_lines)
            prod = "  ".join(
                f"{pk}: other_pack={d.get('other_pack', 0)}"
                for pk, d in sorted(rv.belong_prod.items()))
            lines.append(
                f"观测对账 b−c〔全量口径〕：{rv.b} − {rv.c} = {rv.delta}"
                f"（农场行 {rv.farm_lines}）\n"
                f"   ★ 同一批行的〔生产口径〕是另一个数：{prod or '(无包)'}\n"
                f"     —— 三包共用一个农场根，对任一包来说别的包的 searchee 天然就是"
                f" other_pack。\n"
                f"     这个数恒非零、大体恒定，**没有信息量**；要看真丢了什么，看下一行。")
    except Exception as e:                  # noqa: BLE001
        LOG.debug("b−c 对账失败", exc_info=True)
        lines.append(f"观测对账 b−c：算不出（{type(e).__name__}: {e}）")

    try:
        if store is not None and snap is not None:
            un = S.unclaimed_searchees(store, snap)
            m.update(unclaimed=len(un))
            if un:
                listing = "\n".join(f"   {p}" for _, p in un[:10])
                more = f"\n   …还有 {len(un) - 10} 条" if len(un) > 10 else ""
                lines.append(f"观测对账〔全场无人认领〕：**{len(un)}** 条\n{listing}{more}\n"
                             f"   ★ 三包合起来都不认它 —— 别的包的 searchee 会落进"
                             f"〔生产口径〕的 other_pack，\n"
                             f"     只有这个数才指得出**谁都不归**的那些。")
                emit("alert", f"农场里有 {len(un)} 条 searchee 谁都不归",
                     body=("cross-seed 库里的 searchee，**三个包合起来都认不出**。\n"
                           "它们不在任何包的 `dir_paths` 里，所以状态机看不见它们 ——\n"
                           "既是「白搜」（cross-seed 照搜，额度照烧），\n"
                           "也不会有任何片子因为它们的匹配而前进。\n"
                           "★ 常见形状：农场里混进了非媒体文件/目录"
                           "（实测那条是一个 `.xlsx` 清单）。\n\n"
                           f"共 {len(un)} 条：\n{listing}{more}\n"),
                     key="unclaimed-searchee", metrics={"unclaimed": len(un)})
            else:
                lines.append("观测对账〔全场无人认领〕：**0** 条"
                             "（三包合起来认得出库里每一条 searchee）")
    except Exception as e:                  # noqa: BLE001
        LOG.debug("无人认领对账失败", exc_info=True)
        lines.append(f"观测对账〔无人认领〕：算不出（{type(e).__name__}: {e}）")

    # ---- 声明点〔--packs〕：**登记了却没被驱动**的包 ----
    # ★★ 为什么必须单独立一条：上面那条「无人认领」问的是「农场里有没有谁都认不出的
    #    片」，而 `mbf` 这种「**认得出、只是从来不排它**」的包在它面前是**全绿**的 ——
    #    `pack` 表有行、`movie` 表有 4 行、`farm_root` 也有。实测它从建包起一直躺到
    #    今天没被驱动过一次，而**没有任何一条告警能抓到**：不是判据算错了，是
    #    **没有一条判据的输入源包含 `--packs` 的实际值**（§18.18 那个形状 ——
    #    全绿，因为规则根本没参与）。
    # ★ 两个方向都要报，而且**方向不同、后果不同**：
    #      pack 表 − `--packs` = 登记了却没被驱动 → 白登记：状态机有它、农场有它、
    #                            就是不排它，它的片子**永远不会被搜到**
    #      `--packs` − pack 表 = 在名单里但库里没登记 → 更糟：状态机看不见它的片子，
    #                            整包会被判成「别的包」（other_pack）而静默降级
    # ★ 这条**只报变化，不报现状**（2026-09-12 深夜改）。现状（例如 `mbf` 登记了
    #    却一直没被驱动）是**已接受**的，每天喊一次只会把告警喊成噪音 ——
    #    而噪音的代价是**真的出问题时没人看**。
    #      · 差集里出现了**基线里没有**的 → 发 alert（有新问题）
    #      · 与基线一致、或**缩回**基线之内 → **不发**（修好了不必喊）
    #    无论发不发，都把它采纳为新基线 —— 所以同一个差集只喊一次。
    #    ★ 缩也采纳：不然「删掉 mbf 打的那一行」之后基线还是旧的，
    #      将来它再被加回来时，「又冒出来了」这件事就没人报（那才是真要抓的）。
    # ★ 基线**不进代码、进状态文件**（`.reconcile.state` 的 `_packs_baseline`）：
    #    写进代码就分不清「回到基线」和「判据死了」（§18.19 的教训）。
    # ★ 但**日报正文照旧每天打印**完整差集 —— 不告警 ≠ 看不见。
    # ★ 「没给 `--packs`」必须给 `n/a` 而不是 0：调用方没传和名单对得上是两件事，
    #    TSV 里两者长得一样就没法事后分开（同上面 `fa`/`unclaimed` 的规矩）。
    try:
        plist = getattr(args, "packs", None)
        if store is None:
            lines.append("声明点对账〔--packs〕：状态库读不到 —— "
                         "登记 vs 驱动**没跑成**，别念成 0")
        elif not plist:
            lines.append(f"声明点对账〔--packs〕：跳过（调用方没给 `packs`；"
                         f"默认值是 {PACKS_DEFAULT}）")
        else:
            driven = [p.strip() for p in str(plist).split(",") if p.strip()]
            reg = [r["name"] for r in store.packs()]
            undriven = [p for p in reg if p not in driven]
            unreg = [p for p in driven if p not in reg]
            m.update(packs_undriven=len(undriven), packs_unreg=len(unreg))
            cur = {"undriven": sorted(undriven), "unreg": sorted(unreg)}
            packs_baseline = cur          # 无论告不告警都采纳
            prev_b = _packs_norm(prev_ok.get(PACKS_BASELINE_KEY))

            if PACKS_BASELINE_KEY not in prev_ok:
                # 第一次读数：现状不是新闻 → 记基线，**不告警**。
                # ★ 这一步同时是「mbf 这种躺着的老问题不再每天喊」的开关。
                note = ("   ★ 首次读数 → 已记为基线，**不告警**"
                        "（现状不是新闻；往后只报变化）。")
            else:
                grew = []
                for dim, label in (("undriven", "登记了却没被驱动"),
                                   ("unreg", "在名单里但库里没登记")):
                    new = [x for x in cur[dim] if x not in prev_b[dim]]
                    if new:
                        grew.append(f"{label}：新增 {'、'.join(new)}")
                if grew:
                    note = "   ★ 与基线相比**有变化** —— 已告警。"
                    emit(
                        "alert",
                        f"声明点对账：差集**变了**（{len(grew)} 类有新增）",
                        body=("`pack` 表登记的包，和 `--packs` 驱动的名单，"
                              "**差集变了**。\n"
                              "（本判据只报**变化**：与基线一致的现状不再每天喊。）\n\n"
                              + "\n".join("  ★ " + g for g in grew) + "\n\n"
                              f"  登记了却没被驱动（{len(undriven)}）："
                              f"{'、'.join(undriven) or '(无)'}\n"
                              "     ★ 白登记。它的片子永远不会被搜到，也不会有人报。\n"
                              "      要驱动它：把名字加进 `run.sh` 的 `--packs`（或改 "
                              f"`drive-loop.py` 的 `PACKS_DEFAULT`）；\n"
                              "      不想驱动它：在 `state.db` 里删掉那一行。\n\n"
                              f"  在名单里但库里没登记（{len(unreg)}）："
                              f"{'、'.join(unreg) or '(无)'}\n"
                              "     ★★ 更糟的一头 —— `--packs` 里的名字必须有 `pack` 表行，\n"
                              "      否则状态机看不见它的片子，整包会被判成别的包而静默降级。\n\n"
                              f"  当前名单：{PACKS_DEFAULT}（`--packs` 的默认值）\n"),
                        key="packs-mismatch",
                        metrics={"packs_undriven": len(undriven),
                                 "packs_unreg": len(unreg)})
                else:
                    note = "   ★ 与基线一致 —— 不告警（只报变化，不再每天喊）。"
            lines.append(
                f"声明点对账〔--packs〕：登记 {len(reg)} 个 / 驱动 {len(driven)} 个\n"
                f"   登记了却没被驱动（{len(undriven)}）："
                f"{'、'.join(undriven) or '(无)'}\n"
                f"   在名单里但库里没登记（{len(unreg)}）："
                f"{'、'.join(unreg) or '(无)'}\n"
                f"   ★ 前者是「白登记」：状态机有它、农场有它、**就是不排它** ——"
                f"它的片子永远不会被搜到，\n"
                f"     而它在 unclaimed / report / trend 上全是绿的。\n"
                f"{note}")
    except Exception as e:                  # noqa: BLE001
        LOG.debug("--packs 对账失败", exc_info=True)
        lines.append(f"声明点对账〔--packs〕：算不出（{type(e).__name__}: {e}）")

    try:
        if store is not None:
            store.con.close()
    except Exception:                       # noqa: BLE001
        pass

    # ---- #34：`n/a` 要配「上次成功读数时刻」 ----
    # ★ 为什么非要有这一行：`n/a` 本身**只说明这一次**。TSV 里一个已经连续
    #   三天读不到的格子，和一个昨天还好、今天抖了一下的格子，长得**一模一样** ——
    #   于是"判据长期失效"和"偶发抖动"在事后完全分不开。
    #   判据要能指回时间，才谈得上"指回判据之外的真实记录"。
    # ★ 只记**真的读到数**的那些格：`n/a` 不覆盖旧时间戳（否则一次失败就把
    #   "上次成功"抹成"从没成功过"，反而丢信息）。
    now_ts = time.time()
    live = dict(prev_ok)
    for k, v in m.items():
        if v != "n/a":
            live[k] = now_ts
    na = sorted(k for k, v in m.items() if v == "n/a")
    if na:
        marks = []
        for k in na:
            t = prev_ok.get(k)
            # ★ 「上次成功 X 前」和「从未成功读到过」是**两种处置**：
            #   前者去查这一次为什么抖（SMB/库占用），后者去查这个格子
            #   从装上那天起是不是根本没接上（输入源配错了）。所以两句都要写全。
            marks.append(f"{k}（上次成功 {_age_h(now_ts - t)}）" if t
                         else f"{k}（★ 从未成功读到过）")
        lines.append("观测对账〔本轮 n/a 的格子〕：" + "、".join(marks)
                     + "\n   ★ 括号里是**这个格子最后一次真的读到数**是什么时候 ——"
                       "刚抖一下 vs 长期读不到，差别全在这里。")
    if packs_baseline is not None:
        # ★ 只在**本轮真的算了差集**时才写。`--packs` 没给、或库读不到的那几轮，
        #   必须保留旧基线 —— 否则一次抖动就把「已接受的现状」抹成空，
        #   下一轮会把 `mbf` 这个老问题当成「新变化」再喊一遍（正是要避免的噪音）。
        live[PACKS_BASELINE_KEY] = packs_baseline
    _reconcile_write(live)
    return "\n".join(lines), m


def report_daily(args, *, force: bool = False, farm_note: str = "") -> bool:
    """每天最多投一次的台账：额度（来源 A+C）+ 新增做种趋势 + IYUU 辅种条数
    + 观测对账（a−b / b−c〔全量口径〕/ 全场无人认领 / 声明点〔--packs〕）。

    ★ 为什么必须自己记「今天发过没有」：notify 的**冷却只对 alert 生效**
      （`batch`/`info` 走 `.get(kind, "info")` → level=info，`_cooled` 根本不查）。
      也就是说同一个 batch 事件，**每一批都会真的写一个新文件进 spool**
      —— 45 分钟一批就是一天 30 多条。日报不能靠 notify 去重，得自己记。
    """
    today = datetime.now().strftime("%Y-%m-%d")
    if not force and _daily_last() == today:
        return False

    parts: list[str] = []
    if getattr(args, "db_path", None):
        try:
            lines = S.quota_snapshot(args.db_path)
            pl_url, pl_key = prowlarr_cfg(args)
            if pl_url and pl_key:
                S.attach_prowlarr_quota(lines, pl_url, pl_key, timeout=8)
                parts.append(S.render_quota(lines, limit=8))
            else:
                parts.append(S.render_quota(lines, limit=8))
                miss = "PROWLARR_URL" if not pl_url else "PROWLARR_API_KEY"
                parts.append(f"（来源 B 互校：没配 {miss}，跳过 —— 见 SUMMARY §16.1.4）")
        except Exception as e:              # noqa: BLE001 —— 一节坏了不该拖垮整份日报
            parts.append(f"站点额度台账：读不到（{type(e).__name__}: {e}）")
    else:
        parts.append("站点额度台账：跳过（没有 --db-path / 找不到 cross-seed.db）")

    try:
        with S.StateStore(args.db) as st:
            parts.append(st.trend(weeks=4).render())
    except Exception as e:                  # noqa: BLE001
        parts.append(f"新增做种趋势：算不出（{type(e).__name__}: {e}）")

    # 农场巡检那一行摘要（§16.2.2 任务 6）。★ 它**不是**可有可无的装饰：
    #   巡检每天才跑一次，而 `batch` 级通知是**每批都真的投一条**（见本函数开头的说明），
    #   所以「巡检还活着」这个心跳只能由日报带出来 —— 否则巡检哪天静默不跑了，
    #   从外面看与「一直没漂移」完全一样。这正是 §16.2 要防的那种坏法。
    if farm_note:
        parts.append(farm_note)

    iyuu_note, iyuu_metrics = iyuu_watch(args)
    parts.append(iyuu_note)

    # 观测对账（a−b / b−c〔全量口径〕/ 全场无人认领 / 声明点〔--packs〕）。
    # ★ 放在**日报里**而不是每批：日报是这套系统里唯一"每天恰好一次"的观测出口，
    #   而 notify 只把 `metrics` 落进 TSV 流水（不记正文）—— 进日报的 metrics，
    #   这些数才真的留得下来。同 iyuu_watch。
    rec_note, rec_metrics = reconcile_watch(args)
    if rec_note:
        parts.append(rec_note)

    body = "\n\n".join(parts)
    # ★ 数字要进 `metrics` 才落得进 TSV 流水（notify 只记 ts/kind/title/metrics，
    #   **不记正文**）—— 详见 iyuu_watch 的说明。
    if emit("batch", "每日台账", body=body, key="daily",
            metrics={"day": today, **iyuu_metrics, **rec_metrics}):
        _daily_set(today)
        LOG.info("已投递每日台账（额度 + 趋势）")
        return True
    return False


# --------------------------------------------------------------------------- #
# 农场巡检：把 `build-farm.sh --verify` 挂上来（SUMMARY §16.2.2 —— 任务 6）
# --------------------------------------------------------------------------- #
# 要解决的问题：农场（v3 硬链接）与它的那 49 条源之间会**慢慢漂移** ——
# 源里新增了片子、或者片子在源里被删/改名。漂移了不报错，只会安静地变坏：
#   源有农场无 → cross-seed 看不见这部，白等一轮；
#   农场有源无 → 农场那条还在，cross-seed **照样拿去搜 = 白烧站点额度**。
# 原先靠人工偶尔跑一次 `--verify`，所以漂移能存在很久没人知道。
#
# 四条约束（照 §16.2.2 抄；有改动的地方在注释里说明）：
#   1. `--verify` 有漂移 → **退出码 1**。这是 2026-09-12 09:52 才补上的：
#      在那之前它只打印计数、恒返回 0 —— 挂上去也**永远不会报警**，
#      那才是真正的前置条件（不是"没时间挂"）。
#   2. 有漂移 → `alert`（**即时**）。这是要人去处理的事，不能埋进日报里。
#   3. 零漂移 → **不出告警**，只留一行摘要由每日台账带出去，兼作"巡检还活着"的心跳。
#   4. ★★ **绝不自动 `--prune`**：prune 判「源没了」的依据正是那份期望集，
#      拿它自动删 = 把一次误判放大成**不可逆**的数据丢失。**只报告，删不删由人定。**
#      —— 这条有测试盯着（断言 argv 里永远不出现 --prune）。
#
# ★ 一处比 §16.2.2 更严的地方：**脚本本身跑不起来也算故障**，照样 alert。
#   退出码既不是 0 也不是 1，说明"根本没查成"。不这么判的话，"巡检静默地没在跑"
#   和"真的没漂移"从外面看一模一样 —— 那正是 §16.2 开头说的
#   「分不清'真的没漂移'和'还是没在检查'」，比不做校验更坏，因为它给的是**虚假的安心**。
FARM_CHECK_FILE = HERE / ".farm-check.state"
FARM_CHECK_MIN_GAP_SEC = 20 * 3600      # 约一天一次（用时间戳差值，绕开"跨天/时区"边界）
# 超时按**实测**给余量，不是拍脑袋：2026-09-12 在 NAS 上量到 `--verify` **4 秒**
# （475 条，本地 stat + 列 49 个目录；全是本机 I/O，没有网络往返）。
# 120 秒 = 30 倍余量 —— 日常远够，真卡死时又能及时收手去发告警。
# ★ 别为了"保险"把它调得很大：这个值同时也是**判据** —— 超时会被当成
#   「巡检跑不起来」而发 alert。调太大，等于把一次真故障从告警变成静默等待。
FARM_CHECK_TIMEOUT_SEC = 120


def _farm_check_read() -> dict:
    try:
        d = json.loads(FARM_CHECK_FILE.read_text(encoding="utf-8"))
    except Exception:                       # 文件不存在 / 坏了 —— 都当"还没查过"
        return {}
    return d if isinstance(d, dict) else {}


def _farm_check_write(note: str, *, now: float) -> None:
    try:
        tmp = FARM_CHECK_FILE.with_suffix(".state.tmp")
        tmp.write_text(json.dumps({"ts": now, "note": note}), encoding="utf-8")
        os.replace(tmp, FARM_CHECK_FILE)    # 原子替换，别让下一轮读到半个文件
    except OSError:
        LOG.debug("农场巡检标记写不进去（不影响跑批）", exc_info=True)


def _run_verify(argv: list[str]) -> tuple[int, str]:
    """真跑一次 `build-farm.sh --verify`。返回 (退出码, 输出)。

    ★ 超时兜底是**必须**的：这一步挂在批次收尾里，而收尾后面还有个 finally
      要落状态（跑了哪个包、下批间隔）。子进程真卡住时，宁可报一条"超时"，
      也不能让状态写不回去 —— 写不回去会让下一轮的闸门算错。
    ★ 用 PIPE 收 stdout+stderr：漂移明细只出现在 stdout，而 die() 走 stderr，
      两条都得看得到（合并成一条流，顺序也保住了）。
    """
    try:
        p = subprocess.run(
            argv, cwd=str(Path(argv[1]).parent),
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            timeout=FARM_CHECK_TIMEOUT_SEC,
            # ★ 显式传 COMPOSE_DIR：脚本里的默认值是写死的 NAS 绝对路径，
            #   这里用脚本自己所在的目录覆盖掉它 —— 以后装到别处也不用改脚本。
            env={**os.environ, "COMPOSE_DIR": str(Path(argv[1]).parent)},
        )
        return p.returncode, p.stdout.decode("utf-8", "replace")
    except subprocess.TimeoutExpired:
        return 124, f"build-farm.sh --verify 超时（> {FARM_CHECK_TIMEOUT_SEC} 秒）"
    except OSError as e:                    # sh 不在 / 脚本没执行权限 / 路径坏了
        return 127, f"起不了 build-farm.sh：{type(e).__name__}: {e}"


def check_farm(*, force: bool = False, now: float | None = None,
               runner=None) -> str:
    """跑一次农场巡检，返回一行摘要（由每日台账引用）。返回 "" = 库里没记录。

    间隔没到就直接返回**缓存的那一行**（默认 20 小时一次）—— 这样日报里
    永远有一句农场的话，而巡检本身不用每批都跑。

    ★ `now` / `runner` 只为**可测**而存在（生产调用一律省略）。
      —— 与 `alert_blocked_indexers(now=...)` 同一个理由：测试要能钉死时间、
      要能打桩子进程。否则这段代码只能靠"真跑一次 NAS"来验证。
    """
    now = time.time() if now is None else now
    cached = _farm_check_read()
    if not force and cached.get("ts") and \
            now - float(cached["ts"]) < FARM_CHECK_MIN_GAP_SEC:
        return str(cached.get("note") or "")

    script = first_existing("build-farm.sh")
    if not script:
        note = "农场巡检：跳过（compose 目录里找不到 build-farm.sh）"
        LOG.warning("%s", note)
        _farm_check_write(note, now=now)
        return note

    argv = ["sh", script, "--verify"]       # ★ 只有 --verify；永远不加 --prune
    rc, out = (runner or _run_verify)(argv)
    out = (out or "").strip()

    if rc == 0:
        note = "农场巡检：无漂移"
        LOG.info("%s", note)
    else:
        tail = "\n".join(out.splitlines()[-40:]) if out else "(无输出)"
        if rc == 1:
            note = "农场巡检：**有漂移**（已发告警，处理与否由你定）"
            title = "农场巡检：有漂移"
            head = ("农场（硬链接）与它的源对不上了。**只报告、不动手** —— "
                    "脚本从不自动删，`--prune` 跑不跑由你定。\n"
                    "· 补新建项：`sh build-farm.sh --apply`\n"
                    "· 删孤儿项：**确认源真的没了**再 `sh build-farm.sh --apply --prune`\n"
                    "★ 判「源没了」的依据就是同一份期望集，误判一次即不可逆，"
                    "所以这一步**故意**留给人。\n")
            key = "farm-drift"
        else:
            note = f"农场巡检：**跑不起来**（退出码 {rc}）—— 已发告警"
            title = "农场巡检跑不起来"
            head = ("这**不是**「没有漂移」，而是「根本没查成」 —— 退出码既不是 "
                    "0（无漂移）也不是 1（有漂移）。修好之前，农场有没有漂移"
                    "**无人知道**，别把它当成「一切正常」。\n")
            key = "farm-check-broken"
        LOG.warning("%s（退出码 %d）", note, rc)
        emit("alert", title, body=head + "\n---- 输出末尾 ----\n" + tail,
             key=key, metrics={"rc": rc})

    _farm_check_write(note, now=now)
    return note


def after_batch_reports(args) -> None:
    """跑批收尾的通知 + 农场巡检。

    ★ 外面再包一层 try —— 这些全是**附属功能**，任何一件出事都不该让整批算失败。
      （emit 自己已经吞异常了，但 `report_daily` 里还有读库/算趋势这些代码，
      `check_farm` 还要起子进程。）
    ★ 顺序：巡检**在日报之前**跑，好把它那一行摘要塞进本次日报里。
    """
    try:
        alert_blocked_indexers(args)
        farm_note = check_farm()
        report_daily(args, farm_note=farm_note)
    except Exception:                       # noqa: BLE001
        LOG.debug("收尾通知失败（不影响跑批）", exc_info=True)


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
        check_secs=args.backoff_check_secs,
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
    # 每天一次的台账（额度 + 趋势）+「有站点此刻在退避」的即时告警。
    # ★ 放在批次自己的 batch 事件**之后** —— 台账要反映刚回灌完的最新状态。
    after_batch_reports(args)
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
      **PID 会被复用**（Windows 上尤其容易撞到，Linux 内核的 pid_max 也会绕回）。
      批次被强杀后状态文件里留着 running_pid，
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
    """判断 pid 是否还在跑。

    ★ 原本这里为 Windows 分了一支（`os.kill(pid, 0)` 在 Windows 上**会真的
      把进程杀掉**，只能改用 `tasklist`）。电脑端退役后那支用不上了，
      注释保留在下面 —— 它记的是一个**反直觉的坑**：POSIX 上"发 0 号信号
      探测存活"是标准做法，搬到 Windows 上就变成"探测即击杀"。
    """
    if not pid:
        return False
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return False
    # [电脑端已退役 2026-09-12] Windows 专用的 tasklist 分支，现只剩 NAS(Linux) 一个环境：
    # if os.name == "nt":
    #     try:
    #         out = subprocess.run(
    #             ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
    #             capture_output=True, text=True, errors="replace", timeout=15,
    #         ).stdout
    #         return str(pid) in (out or "")
    #     except Exception:  # noqa: BLE001
    #         return False
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def batch_alive(st: dict) -> bool:
    """上一批是否**真的**还在跑：PID 存活 **且** 心跳新鲜。

    只看 PID 会被 PID 复用骗到（详见 Heartbeat 的说明）——
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


def log_result(pack: str, stats: S.DriveStats | None) -> float | None:
    """把本批结果写进日志，并**返回算出的下批间隔**（交给 once_round 落盘）。

    ★ 返回值这一环是 2026-09-12 补的：在那之前 `next_sleep()` 的结论只进日志、
      不落任何地方，于是 `--once` 模式下真正的闸门是写死的 `min_sleep`，
      「站点在限流就缓一缓」这条策略**压根没接线**。现在把它交出去。
      返回 None = 本批没动作（没待搜 / 计划为空），调用方按「无退避证据」处理。
    """
    if stats is None:
        LOG.info("[%s] 本批无动作（没待搜或计划为空）", pack)
        return None
    sleep_sec, reason = next_sleep(stats)
    LOG.info("[%s] %s | 原因：%s | 下次间隔 %.0f 分钟", pack,
             stats.render().splitlines()[0], reason, sleep_sec / 60)
    if stats.newly_seeding:
        LOG.info("  → 本轮新增做种 %d 部 🎉", stats.newly_seeding)
    if stats.still_skipped:
        LOG.warning("  → 仍有 %d 部被退避（站点侧 502/限流？见 SUMMARY §6.5）",
                    stats.still_skipped)
    return sleep_sec


def once_round(packs: list[str], args, api_key: str, min_sleep: float) -> int:
    """`--once` 单批模式：跨进程节流（防计划任务唤醒重叠）+ 包轮换持久化。

    - 上一批还在跑（pid 活着）→ 直接退出
    - 距上次批次结束不足 **闸门** 秒 → 直接退出（防猛打）
    - 否则跑「轮到的那个包」一批，并把 {结束时间, 包序号, 下批间隔} 写回状态文件

    ★ 闸门 = max(min_sleep, 上一批算出的间隔)。上一批撞了退避 → `next_sleep()`
      给 1.5~2 小时，这里就真的会等那么久；站点健康 → 45 分钟，但不短于
      `min_sleep`（默认 30 分钟）。2026-09-12 之前这里**只有** min_sleep 一项，
      `next_sleep()` 的结论不落盘、也就没人用 —— 退避分级形同虚设。
    """
    st = read_state()
    if batch_alive(st):
        LOG.info("上一批（pid %s）仍在运行，跳过本轮", st.get("running_pid"))
        return 0
    last_end = float(st.get("last_end_ts") or 0)
    last_sleep = float(st.get("last_sleep_sec") or 0)
    wait = clamp(max(min_sleep, last_sleep))
    gap = time.time() - last_end
    if last_end and gap < wait:
        # ★ 2026-09-12 改判据。原先这里是 `if wait > min_sleep:` → 一律打印
        #   「上一批报告站点在退避」——**在完全正常的健康档也成立**，因为健康档
        #   BASE_SLEEP(45 分钟) 本就大于 min_sleep(30 分钟)。实测 NAS 上 09-12
        #   10:00/10:15/10:30/11:15 四次跳过全是 45 分钟健康档，却全报「在退避」，
        #   而**同一批**上面那行刚说过「无退避、无新增（正常）」—— 一个批次的两行
        #   日志自相矛盾。这不是行为错（闸门确实按 45 分钟挡住了），是文案在
        #   **断言一个没有依据的原因**；下次真出限流时，这行会把人往错的方向带。
        #   真退避档只可能是 SNOOZE(90)/BACKOFF(120)/ABORT(180)，都**严格大于**
        #   BASE_SLEEP，所以判据要用「last_sleep 超过了健康档」而不是「超过了硬下限」。
        if last_sleep > BASE_SLEEP:
            why = "上一批报告站点在退避"
        elif min_sleep > last_sleep:
            # last_sleep 还没记录（0）或被 --min-sleep 抬到了更大 —— 此时是下限在管
            why = "按 --min-sleep 下限"
        else:
            why = "按上一批算出的批间隔"
        LOG.info("距上次批次结束仅 %.1f 分钟（< %.0f 分钟：%s），跳过本轮",
                 gap / 60, wait / 60, why)
        return 0

    idx = (int(st.get("last_pack_idx", -1)) + 1) % len(packs)
    pack = packs[idx]
    write_state({**st, "running_pid": os.getpid(), "heartbeat_ts": time.time()})
    LOG.info("[--once] 跑包 %s（第 %d/%d 个）", pack, idx + 1, len(packs))

    stats = None
    sleep_sec = None      # 本批算出的下批间隔；没跑成 / 无动作 → None（按无退避证据）
    rc = 0
    failed = False
    try:
        # 心跳线程只包住跑批阶段：跑完就停，免得和下面 finally 写状态打架
        with Heartbeat():
            stats = run_round(pack, args, api_key)
        sleep_sec = log_result(pack, stats)
        if stats is None:
            # 这个包没待搜 —— 看看是不是所有包都干完了（无人值守时必须出声）
            alert_if_all_done(packs, args.db)
            # ★ 农场巡检**不能只挂在「批次跑完了」那条路上**：它在
            #   after_batch_reports 里，而 run_round 没待搜时会**提前 return None**，
            #   根本走不到那里。于是"所有包都搜完了"的那几天，巡检会**跟着一起停**
            #   —— 而那恰恰是最该跑的时候：没在搜索不等于农场没漂移，
            #   只等于**没人看了**。等哪天真要搜了，漂移已经攒了几天。
            #   它自己有 20 小时间隔兜着，所以这里多调一次几乎总是空转（只读一个状态文件）。
            check_farm()
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
        # ★ last_sleep_sec 必须落盘 —— 下一轮的闸门读它（见 once_round 开头）。
        #   sleep_sec 为 None（没跑成 / 本包无待搜）时写 0，即「没有退避证据」，
        #   闸门退回 min_sleep 下限。
        #   注意这个 write_state 是**整体覆盖**、不合并 st（这是刻意的：顺便把
        #   heartbeat_ts 清掉，否则残留的心跳会让下一轮误判「上一批还在跑」）。
        write_state({"running_pid": None, "last_end_ts": time.time(),
                     "last_pack_idx": idx, "consec_abort": streak,
                     "last_sleep_sec": clamp(sleep_sec) if sleep_sec else 0.0})
    LOG.info("--once 完成。")
    return rc


def main() -> int:
    ap = argparse.ArgumentParser(description="反馈驱动循环：自动续跑 cross-seed 搜索")
    ap.add_argument("--packs", default=PACKS_DEFAULT,
                    help=f"包顺序，逗号分隔（轮流推进），默认 {PACKS_DEFAULT}")
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
    ap.add_argument("--backoff-check-secs", type=float, default=60.0,
                    help="★除了每 --check-every 条，再按秒数检查索引器退避，默认 60。"
                         "实测 429 只 snooze 55 秒，而 10 条×30s=300s 才看一眼 —— "
                         "窗口整段落在两次检查之间，退避就等于没发生（backoff_hits 恒 0）")
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

    # --once：单批模式（配合 DSM 计划任务）。跨进程节流 + 包轮换见 once_round()。
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

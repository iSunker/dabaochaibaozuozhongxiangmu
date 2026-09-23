#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
通知（Windows 侧）—— 只**写事件文件**，发信由 NAS 侧脚本负责。

职责划分
--------
* 本文件**没有一行凭据**：不 import smtplib、不读任何密码、不碰 SMTP。
  SMTP 配置由 NAS 自己的 DSM 通知设置提供，NAS 侧脚本直接用它
  （见 `notify-spool.sh` 顶部注释）。
* 为什么绕这一圈：用户选择「NAS 侧发」以避免在 Windows 上存邮件凭据。
  代价是推送有延迟（NAS 侧定时轮询），收益是凭据只留在 DSM 里。

★ 告警链路依赖 NAS —— 所以**每日摘要同时是心跳**：
  「该来的日报没来」本身就是 NAS/任务计划故障的信号。
  见 SUMMARY「通知」一节。

文件格式：刻意用**纯文本**而非 JSON
-----------------------------------
NAS 侧是 POSIX sh，解析 JSON 要么依赖 python3、要么引一个解析器进去。
改成一文件一事件的文本头，`grep` / `sed` 就能读，零依赖：

    # reseed-notify v1
    kind: alert
    level: alert
    ts: 2026-09-11 21:35:02
    host: DESKTOP-UOHUG09
    key: env-stale:/3/api/410
    title: .env 未生效：/3/api 返回 410 ×49
    metrics: url=http://prowlarr:9696/3/api code=410 n=49
    ---
    <正文若干行>

写入是**先写 .tmp 再 rename**（`os.replace`，同目录内原子）——
否则 NAS 侧的轮询可能读到写了一半的文件。

用法
----
    from notify import Notifier
    n = Notifier()                      # 默认指向 NAS spool；不可用时静默降级
    n.emit("batch", "dc-collection 本批完成", body=..., metrics={...})
"""
from __future__ import annotations

import json
import logging
import os
import re
import socket
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

LOG = logging.getLogger("notify")

#: 事件文件的扩展名。NAS 侧脚本只认这个，避免误读别的东西。
SUFFIX = ".txt"

#: spool 的位置。
#: ★★ 2026-09-12：**电脑端已退役**，UNC 兜底注释掉了。原先这里是"候选列表 +
#:   取第一个已存在的"（和 drive-loop.py 的 CROSSSEED_DIRS 同一个道理）——
#:   因为当时 drive-loop 可能跑在 Windows 上，也可能跑在 NAS 上。
#:   现在两边都在 NAS 上，多一条候选只会多一个"写进 UNC = 绕一圈 SMB 连自己"
#:   的静默降级点：不报错，只是慢。
#:   要回退：取消下面那行的注释即可。
SPOOL_CANDIDATES = (
    "/volume2/docker_ssd/prowlarr_cross-seed_autohardlink/notify/spool",
    # [电脑端已退役 2026-09-12] 原本是 Windows 跑批时的兜底路径：
    # "//iSunker-DS423/docker_ssd/prowlarr_cross-seed_autohardlink/notify/spool",
)

#: 兜底（一个都不存在时用这个）。保留旧名字 —— 文档/脚本里有引用。
DEFAULT_SPOOL = SPOOL_CANDIDATES[0]


def default_spool() -> Path:
    """挑一个 spool 目录：优先返回**已存在**的那个。

    ★ 一个都不存在时返回 NAS 原生路径：Notifier 自己会 `mkdir(parents=True)`，
      而搬迁后它更可能跑在 NAS 上。（不过正常情况下 spool 应该由 NAS 上的
      notify-spool.sh 先建好 —— 见该脚本注释。）
    """
    for c in SPOOL_CANDIDATES:
        if Path(c).is_dir():
            return Path(c)
    return Path(DEFAULT_SPOOL)

#: 冷却状态文件（gitignore）。同一 key 在冷却期内只发一次。
STATE_FILE = Path(__file__).resolve().parent / ".notify.state"

#: 同 key 的默认冷却时长。12 小时 = 一个持续存在的问题每天最多提醒 2 次。
#: ★ 必须冷却：像「容器 env 陈旧」这种未修复的问题，每 15 分钟唤醒一次就会
#:   每 15 分钟发一封邮件 —— 那不是告警，那是骚扰，结果是被无视。
DEFAULT_COOLDOWN_SEC = 12 * 3600

#: 单个生命周期内最多投递几条**告警**（防一次性喷出几百个 —— NAS 侧还要逐个发信）
#:
#: ★★★ 2026-09-23 修正语义，把两个**独立**的设计问题分开治。改动前它叫「单次运行
#:   最多几个事件文件」，而实现在两个方向上都跑偏了：
#:
#: **① 计数对象错了：它把 `batch` 也算进去。**
#:   `emit` 里那条闸门对**所有** kind 一视同仁，可这条上限的初衷只关于**告警**
#:   （「防一次性喷出几百个」喷的是告警）。后果是**批次挤占告警额度**：
#:   常驻模式下每轮回灌至少一条 `batch`，跑十来轮就用光了 —— ★ 到那时**真告警
#:   一个都发不出去**，唯一痕迹是日志里一行 WARNING。形状正是本项目最忌的那种
#:   「**该响的时候没响，而看起来一切正常**」（`ERR-AI-09`）。
#:   ⇒ 现在只对 `alert` 计数。`batch`/`info` **永不**因这条上限被丢。
#:
#: **② 计数窗口错了：常驻进程里它跨轮累积、永不归零。**
#:   配额的真实标的是「**一次喷发**」，所以随 `emit` 调用数累积**本来就是对的** ——
#:   麻烦在于**没有人告诉它一次喷发结束了**：常驻模式下进程活几周，
#:   `_count` 一路涨到 12 再也不会降。⇒ 新增 `reset_count()`，由调用方在**批与批
#:   之间**显式回收（`scripts/drive-loop.py` 的 `run_round` **底部**，
#:   即 `after_batch_reports()` 之后 —— 为什么不能放顶部见 `reset_count`）。
#:   ★ 与 `_cooldown_window`（`_read_state` 里那次修剪）**同一条纪律**：
#:     累加器必须**显式**回收，不能指望它自己瘦下来。
#:
#: ★ 关于「2026-09-13 邮件风暴」的原始意图（`summary/21` 第 21.7 节）：
#:   那场风暴的真根因是**重试无上界**（NAS 侧 `notify-spool.sh` 的 `MAX_SEND_TRIES`），
#:   本文件**当时根本不在链路上** —— 信还没发出，事件文件还压在 spool 里。
#:   ⇒ ①② 都不违背当初的意图。
MAX_PER_RUN = 12

#: 冷启动宽限额度（**一次性，不重置**）。原代码把 alert 也一并交给 `MAX_PER_RUN`，
#: 于是「进程刚起来时的自检告警」和「跑了十轮之后的急性告警」抢同一个计数器 ——
#: 前台那几条把额度吃光，后面真正要紧的就没份了（2026-09-23 实测：26 轮里每轮都报
#: 「已达上限 12 条」，而告警**一条都没发出去**）。
#: ★ 给启动期一个**更小**的独立额度，正是为了让上一条上限对它**失效**：
#:   自检重复顶多丢一两条，急性告警永远不会被启动噪音饿死。
#:   设 0 可关闭宽限（自检告警就回归受 `MAX_PER_RUN` 管）。
#:   1 = 每条**不同 key** 的自检告警都发；2 = 只发前两条不同的……
ALERT_STARTUP_GRACE = 2


def _fallback_key(title: str) -> str:
    """标题的**稳定**短摘要 —— 与 `_slug` 的兜底**必须同源**，但**不塌**。

    ★★ 为什么这个函数存在（2026-09-23，被**变异测试 D** 逼出来的）：
      第一版保险的判据写成 `if _slug(title): pass`（「slug 为空才改名」），
      而 `_slug` 对纯中文标题**返回的不是空串，是退化的 `"x0"`** ——
      它内部先剥成空串、再兜底 `hash(**已经被清空的那个变量**)` ⇒ 永远 `x0`。
      ⇒ 那条 `if` **永远为真**，保险**一次都没跑过**（死代码）。
      ⇒ 而同毫秒的两条中文告警**真的会**塌成同一个文件名、后一条把前一条
        `os.replace` 掉：**告警被静默吞掉一条**。实测：三条不同中文告警
        同毫秒 ⇒ spool 里只有 **1** 个文件。

    ★ 正确的判据是「**文件名是不是退化的**」，不是「slug 空不空」——
      而退化的判据只有 `_slug` 自己知道 ⇒ 这里**照它的形状重建**一个
      **区分标题**的短键：`hash(title)`（`_slug` 里那个 bug 是把 `s` 自己
      覆盖成空串再 hash，于是 hash 的是常量）。
    ★ 不追求与 `_slug` 逐字一致 —— 它连自己都不一致（同一函数两次调用
      因 `PYTHONHASHSEED` 而不同）。这里只要**同一进程内**对**不同标题**
      稳定地不同，就足以让撞在一起的两条不互相覆盖。
    """
    return f"x{abs(hash(title)) % (10 ** 8)}"

#: 标题/正文里的控制字符会破坏「一行一个字段」的格式，一律清掉
_CTRL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def _clean_line(s: str) -> str:
    """把任意文本压成**单行**：去控制字符、换行变空格、防注入假字段。"""
    return _CTRL.sub("", (s or "").replace("\r", " ").replace("\n", " ")).strip()


def _slug(s: str, limit: int = 40) -> str:
    """标题 → 文件名片段。只留 ASCII 安全字符；中文标题会退化成 hash。"""
    s = re.sub(r"[^A-Za-z0-9._-]+", "-", (s or "").strip()).strip("-")
    if not s:
        s = f"x{abs(hash(s)) % (10 ** 8)}"
    return s[:limit]


@dataclass
class Event:
    """一个待发事件。`kind` 决定 NAS 侧怎么处理。"""
    kind: str                     # alert | batch | info
    title: str
    body: str = ""
    key: str = ""                 # 去重键；空则由 kind+title 生成
    metrics: dict = field(default_factory=dict)

    @property
    def level(self) -> str:
        # NAS 侧按 level 决定「立刻发」还是「攒进日报」
        return {"alert": "alert", "batch": "info", "info": "info"}.get(self.kind, "info")

    @property
    def dedup_key(self) -> str:
        return self.key or f"{self.kind}:{_clean_line(self.title)}"


class Notifier:
    """把事件写进 NAS 的 spool 目录。**永不抛异常** —— 通知坏了不该拖垮跑批。"""

    def __init__(self, spool: str | os.PathLike | None = None, *,
                 enabled: bool = True,
                 cooldown_sec: float = DEFAULT_COOLDOWN_SEC,
                 state_path: Path | None = None,
                 dry_run: bool = False):
        self.spool = Path(spool or os.environ.get("NOTIFY_SPOOL") or default_spool())
        self.enabled = enabled and os.environ.get("NOTIFY_DISABLE", "") not in ("1", "true", "yes")
        self.cooldown_sec = cooldown_sec
        self.state_path = Path(state_path) if state_path else STATE_FILE
        self.dry_run = dry_run
        self.host = self._host()
        self._warned = False          # 同一次运行里 spool 不可用只喊一次
        self._count = 0
        #: 启动宽限已用掉的名额（见 `ALERT_STARTUP_GRACE`）。
        #: ★★ **进程内一次性**：只在 `__init__` 为 0，`reset_count()` **不动它**。
        #:   复位它会**每批重新打开后门**（见 `reset_count` 的注释）。
        #: ★ 必须是**单调递增的计数**，不能换成 `len(某个集合)` —— 同一条告警重复
        #:   出现时集合**不增长**，`len() < GRACE` 会**永远成立**（见 `emit` 那段）。
        self._startup_used = 0
        #: 本实例一共投出去了几条 —— **只是给日志/自省用的旁证**，不参与任何判定。
        #: ★ 存在的理由：本文件的失败方式是「**想都没想到要发**」，那时 spool 里
        #:   什么也没有，而唯一带这个数的 `batch` 行**自己也不发了**。
        #:   有了它，`drive-loop` 的批次 metrics 里能顺带带上一个「本进程至今发出 0 条」
        #:   的读数 —— 这比 spool 干净更好使（**给「该响没响」专配一个计数器**）。
        #: ★★ 它与 `_count` **一起**被 `reset_count()` 归零，所以它的语义是
        #:   「**自上次回收以来**投出去几条」—— 在 `drive-loop` 的用法下就**等于**
        #:   「本批投出去几条」。不留成一个独立的「生命周期累计」：
        #:   ★ (a) 常驻模式下单调涨，最后自己也变成噪音；
        #:   ★ (b) 更要紧 —— 两个计数器**同生共死**，「这批发了几条」与「这批还剩
        #:     多少额度」才不可能互相矛盾。留一个不重置的，就多一个**同词不同义**
        #:     的字段（本项目反复栽在这上面），也让「回收」这件事**有一半没生效**
        #:     却看不出来。
        self._delivered = 0

    # ---------------- 内部 ----------------
    @staticmethod
    def _host() -> str:
        try:
            return socket.gethostname()
        except Exception:  # noqa: BLE001
            return "?"

    def _read_state(self) -> dict:
        try:
            return json.loads(self.state_path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001 —— 没有 / 损坏都当空
            return {}

    def _write_state(self, st: dict) -> None:
        try:
            self.state_path.write_text(json.dumps(st, ensure_ascii=False),
                                       encoding="utf-8")
        except OSError as e:
            LOG.debug("写通知冷却状态失败（忽略）: %s", e)

    def _cooled(self, st: dict, key: str) -> bool:
        """同 key 是否还在冷却期内。

        ★ 只对 **alert** 生效（调用方负责判 level）。batch/info **不冷却**：
          冷却要解决的是「同一个**未修复的**问题反复吵你」——比如「容器 env 陈旧」
          这种不修就一直在的状态。而「本批新增做种 11 部」每一批都是**新信息**，
          冷却它只会让每日摘要数错（摘要正是靠 log 里的 batch 行统计的）。
        """
        if self.cooldown_sec <= 0:
            return False
        last = float(st.get(key) or 0)
        return last > 0 and (time.time() - last) < self.cooldown_sec

    def _render(self, ev: Event, now: float) -> str:
        ts = datetime.fromtimestamp(now).strftime("%Y-%m-%d %H:%M:%S")
        head = [
            "# reseed-notify v1",
            f"kind: {_clean_line(ev.kind)}",
            f"level: {ev.level}",
            f"ts: {ts}",
            f"host: {_clean_line(self.host)}",
            f"key: {_clean_line(ev.dedup_key)}",
            f"title: {_clean_line(ev.title)}",
        ]
        if ev.metrics:
            # ★★ 空格在**键**和**值**里都要换掉 —— 两边都会破坏 `k=v k=v` 的切分：
            #    · 值：`seeding:x=frds top` ⇒ 多出一段。
            #    · 键：**更阴** —— `seeding:my pack=1` 被下游按空格切开后成了
            #      `seeding:my`（**没有 `=`，整个键凭空消失**）+ `pack=1`（键**恰好
            #      等于 `pack`**）⇒ 而摘要正是靠 `pack=` **整键相等**来数批次的
            #      （`notify-spool.sh` 里那条 awk；`tests/README.md` 专门钉过
            #      「`packs=` 不是 `pack=`」）⇒ 一个含空格的包名会让该行被
            #      **误计为一批**，并污染 ok=0 计数与做种合计。
            #    ⇒ 键与值走**同一条**规范化，别只治值那一半。
            kv = " ".join(f"{_clean_line(str(k)).replace(' ', '_')}="
                          f"{_clean_line(str(v)).replace(' ', '_')}"
                          for k, v in ev.metrics.items())
            head.append(f"metrics: {kv}")
        body = (ev.body or "").rstrip()
        return "\n".join(head) + "\n---\n" + (body + "\n" if body else "")

    # ---------------- 对外 ----------------
    def reset_count(self) -> None:
        """回收本轮的告警配额 —— 由调用方在**批与批之间**调用。

        ★★ 为什么非要显式调用（2026-09-23 修）：配额要挡的是「**一次喷发**」，
          所以它**随 `emit` 累积本来就对**；错的是常驻模式下**没有人宣布喷发结束** ——
          进程活几周，`_count` 涨到 12 就再也不降，于是第 11 轮之后**所有**通知
          （含**真告警**）全被丢掉，唯一痕迹是日志里一行 WARNING。
          形状正是本项目最忌的「**该响的时候没响，而看起来一切正常**」。

        ★ 与 `_cooldown_window` 那条纪律同源：**累加器必须显式回收**，
          不能指望它自己瘦下来（见 `_read_state` 里那次修剪）。

        ★ 为什么是「批与批之间」而不是「每批一开始」（我第一版就写错了）：
          `run_round` 内部是**先** `emit("batch")`、**后** `after_batch_reports()`
          （台账 + 「有站点在退避」的即时告警）⇒ 若把回收放在 `emit` **之前**，
          重置后的第一条就被这一轮的 batch 自己吃掉，告警又轮空。
          ⇒ 正确位置是 `run_round` 底部 `after_batch_reports()` **之后**
             （`scripts/drive-loop.py`），那里天然就是「一轮的边界」。
        """
        self._count = 0
        self._delivered = 0
        # ★★ 宽限**不在这里复位** —— 它是**进程生命周期**的概念（「冷启动头几条」），
        #   不是「每批」的。这一行是变异测试 C 逼出来的：
        #   第一版把 `_startup_used = 0` 也写进了 `reset_count`，于是**每回收一次
        #   宽限后门就重新打开一次** ⇒ 常驻模式下每轮都白送 `ALERT_STARTUP_GRACE`
        #   条不受上限的告警，`MAX_PER_RUN` 形同虚设。
        #   ★ 那正是「上限失效」= #59 邮件风暴的形状，而且**变异 C 当时没变红**
        #     （因为复位宽限恰好补上了 `_count` 没归零的效果）—— 一个 bug 掩盖另一个。
        #   ⇒ 三个计数器的**时间尺度必须写清楚**：
        #       `_count`       每批回收   ← `reset_count()`
        #       `_delivered`   每批回收   ← 与 `_count` 同尺度（见 `_delivered` 注释）
        #       `_startup_used` **进程内一次性**，只在 `__init__` 里为 0

    @property
    def delivered(self) -> int:
        """**自上次 `reset_count()` 以来**投出去的条数（`drive-loop` 下 = 本批几条）。

        ★ 定位是**旁证读数**，不参与任何判定 —— 用来回答「日志在跑、但 spool 里
          空空的，它到底发过东西没有」。
        ★★ 语义与 `_count` **同尺度**（两者一起归零，见 `_delivered` 的注释）：
          说「本生命周期累计」而实际会被回收，正是本项目最忌的同词不同义。
        """
        return self._delivered

    def emit(self, kind: str, title: str, body: str = "", *,
             key: str | None = None, metrics: dict | None = None) -> bool:
        """写一个事件文件。返回是否真的写了（被冷却/禁用/失败 → False）。

        ★ 任何异常都在这里吞掉：通知是**附属功能**，绝不能让跑批失败。
        """
        if not self.enabled:
            return False
        try:
            ev = Event(kind=kind, title=title, body=body,
                       key=key or "", metrics=metrics or {})

            st = self._read_state()
            # 只有告警冷却（见 _cooled 的说明）；batch/info 每次都写
            if ev.level == "alert" and self._cooled(st, ev.dedup_key):
                LOG.debug("通知冷却中，跳过: %s", ev.dedup_key)
                return False

            # ★★ 配额**只对告警**（2026-09-23 修，见 MAX_PER_RUN 的注释①）。
            #   `batch`/`info` **永不**因这条上限被丢 —— 否则常驻模式下批次会把
            #   告警额度挤光，而症状是「真告警静默失踪、日志看着正常」。
            #   ★★ 判据取 **`kind`**（`ev.kind == "alert"`），**不是** `ev.level`：
            #     `level` 把 `batch` **和** `info` 都归成 `"info"`，而配额的原意
            #     是「防**告警**喷发」⇒ 边界必须画在 `kind` 上，画在 `level` 上
            #     等于让 `batch` 的孪生兄弟 `info` 继续偷告警的额度
            #     （本项目已有一条「`alert` 是 kind 不是 level」的教训）。
            #
            # ★★★ 这一段连踩过**三个**坑，全是变异测试逼出来的，同一族病根
            #     「**判据不可靠 / 靠反推**」。全留着当反面教材：
            #   ① 宽限判据写成 `len(_startup_seen) < GRACE` —— 那是个**集合**，
            #      同一条告警重复出现时它**不增长** ⇒ 条件**永远成立**
            #      ⇒ 后门永远开着，`MAX_PER_RUN` 彻底失效（= #59 风暴的形状）。
            #      ⇒ 换成**单调递增**的 `_startup_used`。
            #      ★ 是**变异 A** 逼出来的（闸门改回「所有 kind 都算」时本文件
            #        一条都没红 —— 宽限那条后门把 50 条批次全放过去了）。
            #   ② 名额在「投递成功后」才记账 ⇒ 被冷却/写盘失败挡掉的告警让名额
            #      永不消耗，后门同样关不上。⇒ **闸门处当场扣掉**。
            #   ③ 下游靠 `_startup_used` / `_count` **反推**「这条走没走宽限」。
            #      ⇒ 闸门处定死显式布尔 `_grace_used`，下游只读它。
            #   ★ 共同教训：**「一次性」状态的判据必须是单调量，状态在产生它的
            #     那一处当场写死** —— 不许下游反推、不许用可能不增长的派生量。
            _grace_used = False
            if ev.kind == "alert":
                if (ALERT_STARTUP_GRACE > 0
                        and self._startup_used < ALERT_STARTUP_GRACE):
                    self._startup_used += 1    # 名额当场扣掉
                    _grace_used = True         # ← 定死，下游只读它
                elif self._count >= MAX_PER_RUN:
                    LOG.warning("本次运行告警已达上限 %d 条，其余丢弃（见 spool 目录）",
                                MAX_PER_RUN)
                    return False

            now = time.time()
            text = self._render(ev, now)
            name = f"{int(now * 1000)}-{os.getpid()}-{_slug(ev.title)}{SUFFIX}"
            # ★★★ 同毫秒**撞名**保险（见 `_fallback_key`）：文件名是 NAS 侧的**唯一
            #   去重依据**（`notify-spool.sh` 的 `log_event` 拿它当去重键），而两条
            #   标题不同、slug 却**退化**的行会**双双**拿到同一个文件名：
            #   后一条把前一条 `os.replace` 掉 ⇒ 告警被**静默吞掉一条**。
            #   ★ `alert` 不冷却，这是它唯一能依赖的那条后路。
            #   ★★ 判据是「**文件名退化不退化**」，**不是**「slug 空不空」——
            #     第一版写的就是后者（`if _slug(...): pass`），而 `_slug` 对纯中文
            #     返回的是退化的 **`"x0"`（非空！）** ⇒ 那条 `if` 永远为真 ⇒
            #     保险**从未生效**、是**死代码**，同毫秒的两条中文告警照样互相覆盖。
            #     （实测：三条同毫秒中文告警只落地 **1** 个文件。）
            #     ★ 这是**变异测试 D** 抓出来的：拆掉这段保险，测试**一条都没红** ——
            #       因为 ⑥ 段那三条告警恰好落在**不同毫秒**，靠时间戳侥幸错开了。
            #     ⇒ 判据必须自己认得出「退化」，不能指望一个坏掉的派生值。
            #   ★ 只在退化时才动手 —— 正常（ASCII 标题）文件名**一个字都不改**，
            #     绝不误伤 `test_notify_drain` 那些靠文件名断言的老测试。
            slug = _slug(ev.title)
            if slug.startswith("x") and slug[1:].isdigit():
                # 退化（`x0` 那种）⇒ 换成**区分标题**的短键。
                name = (f"{int(now * 1000)}-{os.getpid()}-"
                        f"{_fallback_key(ev.title)}{SUFFIX}")

            if self.dry_run:
                LOG.info("[dry-run] 通知(%s) %s", ev.kind, _clean_line(ev.title))
                return False

            self.spool.mkdir(parents=True, exist_ok=True)
            tmp = self.spool / (name + ".tmp")
            tmp.write_text(text, encoding="utf-8")
            # 同目录 rename → 原子；NAS 侧轮询不会读到半截文件
            os.replace(tmp, self.spool / name)

            # 只记告警的去重时间戳 —— batch/info 不冷却，记了也只会让状态文件白长
            if ev.kind == "alert":
                st = {k: v for k, v in st.items()
                      if time.time() - float(v or 0) < self.cooldown_sec * 2}   # 顺手修剪
                st[ev.dedup_key] = now
                self._write_state(st)
                # ★ 判据用闸门处定死的 `_grace_used`（见那段注释③：不许在这里反推）。
                if not _grace_used:
                    self._count += 1

            self._delivered += 1
            LOG.info("已投递通知(%s) → %s", ev.kind, _clean_line(ev.title))
            return True
        except Exception as e:  # noqa: BLE001 —— 见 docstring
            if not self._warned:
                self._warned = True
                LOG.warning("投递通知失败（忽略，不影响跑批）: %s", e)
            return False


def notifier_from_args(args) -> Notifier:
    """从 drive-loop 的命令行参数造一个 Notifier。"""
    return Notifier(
        getattr(args, "notify_spool", None),
        enabled=not getattr(args, "no_notify", False),
        cooldown_sec=float(getattr(args, "notify_cooldown_hours", 12) or 12) * 3600,
        dry_run=bool(getattr(args, "dry_run", False)),
    )

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

#: spool 默认位置（NAS，经 SMB）。与 drive-loop.py 里日志/db 的写法一致，
#: 可用 NOTIFY_SPOOL 环境变量覆盖。
DEFAULT_SPOOL = ("//iSunker-DS423/docker_ssd/prowlarr_cross-seed_autohardlink"
                 "/notify/spool")

#: 冷却状态文件（gitignore）。同一 key 在冷却期内只发一次。
STATE_FILE = Path(__file__).resolve().parent / ".notify.state"

#: 同 key 的默认冷却时长。12 小时 = 一个持续存在的问题每天最多提醒 2 次。
#: ★ 必须冷却：像「容器 env 陈旧」这种未修复的问题，每 15 分钟唤醒一次就会
#:   每 15 分钟发一封邮件 —— 那不是告警，那是骚扰，结果是被无视。
DEFAULT_COOLDOWN_SEC = 12 * 3600

#: 单次运行最多写几个事件文件（防一次性喷出几百个 —— NAS 侧还要逐个发信）
MAX_PER_RUN = 12

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
        self.spool = Path(spool or os.environ.get("NOTIFY_SPOOL") or DEFAULT_SPOOL)
        self.enabled = enabled and os.environ.get("NOTIFY_DISABLE", "") not in ("1", "true", "yes")
        self.cooldown_sec = cooldown_sec
        self.state_path = Path(state_path) if state_path else STATE_FILE
        self.dry_run = dry_run
        self.host = self._host()
        self._warned = False          # 同一次运行里 spool 不可用只喊一次
        self._count = 0

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
            # 值里的空格会破坏 `k=v k=v` 的切分，一律换成下划线
            kv = " ".join(f"{_clean_line(str(k))}={_clean_line(str(v)).replace(' ', '_')}"
                          for k, v in ev.metrics.items())
            head.append(f"metrics: {kv}")
        body = (ev.body or "").rstrip()
        return "\n".join(head) + "\n---\n" + (body + "\n" if body else "")

    # ---------------- 对外 ----------------
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
            if self._count >= MAX_PER_RUN:
                LOG.warning("本次运行通知已达上限 %d 条，其余丢弃（见 spool 目录）",
                            MAX_PER_RUN)
                return False

            now = time.time()
            text = self._render(ev, now)
            name = f"{int(now * 1000)}-{os.getpid()}-{_slug(ev.title)}{SUFFIX}"

            if self.dry_run:
                LOG.info("[dry-run] 通知(%s) %s", ev.kind, _clean_line(ev.title))
                return False

            self.spool.mkdir(parents=True, exist_ok=True)
            tmp = self.spool / (name + ".tmp")
            tmp.write_text(text, encoding="utf-8")
            # 同目录 rename → 原子；NAS 侧轮询不会读到半截文件
            os.replace(tmp, self.spool / name)

            # 只记告警的去重时间戳 —— batch/info 不冷却，记了也只会让状态文件白长
            if ev.level == "alert":
                st = {k: v for k, v in st.items()
                      if time.time() - float(v or 0) < self.cooldown_sec * 2}   # 顺手修剪
                st[ev.dedup_key] = now
                self._write_state(st)

            self._count += 1
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

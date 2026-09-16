#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""ctx —— 看一眼「这个会话用了多少 context」。

为什么要有它：
  上下文快满时最危险的不是"被截断"，是**不知道** —— 于是会在快满的时候
  去做一件很长的事（比如又开始读一份 100 KB 的文档），然后中途被压缩，
  前半段的工作从记忆里消失。
  ★ 与 `ENVIRONMENT` `A.7`「『现在能做』依赖时间窗」同族：**「现在能做多长的事」依赖 context 窗**。

数据从哪来（**只读**）：
  Claude Code 把每个会话逐条落盘成 JSONL，**每条 API 响应里都带 `usage`**。
  ⇒ 不需要任何 hook，**事后读文件**就能算出每一刻的上下文占用：
        context ≈ input_tokens + cache_read_input_tokens + cache_creation_input_tokens
  （三者相加才是**这一轮实际送进去的全部输入**：
    `input` 是本轮新增、`cache_read` 是命中的缓存、`cache_creation` 是新写入缓存的。）

用法：
    python tools/ctx.py              # 当前会话一行读数（默认）
    python tools/ctx.py --watch 30   # 每 30 秒刷新一次（实时显示）
    python tools/ctx.py --hist       # 最近 30 次读数，看涨得多快
    python tools/ctx.py --limit 200000
    python tools/ctx.py --session <id 前缀>

★ 上限（`--limit`）**是估计值，不是承诺** —— 见文件末尾那段「这个数有多可信」。
"""
import argparse
import glob
import json
import os
import sys
import time
from datetime import datetime, timezone

sys.stdout.reconfigure(encoding="utf-8")

PROJ = os.path.expanduser("~/.claude/projects")
#: ★ 上限**是实测推断，不是官方数字** —— 见文件末尾「这个数有多可信」。
#:   依据：历史实测最大 context = **355,726** tokens（2026-09-14）**且那个会话没撞墙**
#:   ⇒ 真实上限 ≥ 356k。取 400k 作估计（宁可少报，不要虚报"快满了"）。
DEFAULT_LIMIT = 400_000


def find_session(prefix=None):
    """找 `~/.claude/projects/*/<session>.jsonl` 里**最近被改过**的那个。"""
    cands = []
    for p in glob.glob(os.path.join(PROJ, "*", "*.jsonl")):
        if prefix and not os.path.basename(p).startswith(prefix):
            continue
        cands.append((os.path.getmtime(p), p))
    if not cands:
        return None
    cands.sort(reverse=True)
    return cands[0][1]


def readings(path):
    """产出 (时刻, context_tokens, model, output_tokens)，按文件顺序。

    ★ 只认**带 usage 且 input 非 0** 的记录。
      实测：流式响应会把 `usage` 写好几遍，其中有些是 `input_tokens=0` 的占位
      （见下面的 `context≈0`）—— 把它们算进来会让曲线出现假的归零。
    """
    out = []
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            if '"usage"' not in line:
                continue
            try:
                d = json.loads(line)
            except Exception:
                continue
            m = d.get("message") or {}
            u = m.get("usage") or {}
            if not u:
                continue
            t = (u.get("input_tokens", 0)
                 + u.get("cache_read_input_tokens", 0)
                 + u.get("cache_creation_input_tokens", 0))
            if t <= 0:
                continue
            out.append((d.get("timestamp"), t, m.get("model", "?"),
                        u.get("output_tokens", 0)))
    return out


def bar(frac, width=30):
    frac = max(0.0, min(1.0, frac))
    n = int(round(frac * width))
    return "█" * n + "·" * (width - n)


def fmt(n):
    return f"{n:,}"


def line(rs, limit):
    if not rs:
        return "★ 还没有任何读数（这个会话可能刚开，或文件不是本会话的）"
    ts, tok, model, out = rs[-1]
    frac = tok / limit
    flag = ""
    if frac >= 0.90:
        flag = "  ★★ 很满：别再读大文件，先收口/落盘"
    elif frac >= 0.75:
        flag = "  ★ 偏满：长文档分块读、别开新长任务"
    elif frac >= 0.50:
        flag = "  ⚠ 过半"
    return (f"[{bar(frac)}] {frac*100:5.1f}%   "
            f"context≈{fmt(tok)} / 估计上限 {fmt(limit)}{flag}\n"
            f"           最后读数 {ts}   model={model}")


def trend(rs, n=30):
    """看上一条 → 这一条的增量（**按轮**，不是按时间）。"""
    if len(rs) < 2:
        return "（读数不足两条，看不出趋势）"
    tail = rs[-n:]
    out = []
    for i in range(1, len(tail)):
        d = tail[i][1] - tail[i - 1][1]
        out.append(d)
    pos = [d for d in out if d > 0]
    avg = sum(pos) / len(pos) if pos else 0
    return (f"最近 {len(out)} 次采样：涨 {len(pos)} 次、平/降 {len(out)-len(pos)} 次；"
            f"平均每次涨 ≈ {fmt(int(avg))} tokens"
            + (f"  ⇒ 按此速度还能走 ≈ {fmt(int((DEFAULT_LIMIT*0.9 - tail[-1][1]) / avg))} 次采样"
               if avg > 0 and tail[-1][1] < DEFAULT_LIMIT*0.9 else ""))


def main():
    ap = argparse.ArgumentParser(add_help=True)
    ap.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    ap.add_argument("--watch", type=float, metavar="SEC",
                    help="每 SEC 秒刷新（Ctrl-C 退出）")
    ap.add_argument("--hist", action="store_true", help="最近 30 次读数")
    ap.add_argument("--session", help="会话 id 前缀（默认取最近改过的那个）")
    a = ap.parse_args()

    path = find_session(a.session)
    if not path:
        print("★ 在 %s 下没找到 .jsonl" % PROJ)
        return 1
    sid = os.path.basename(path)[:-6]
    print("会话 %s" % sid)
    print("文件 %s" % path)
    print()

    if a.watch:
        try:
            while True:
                rs = readings(path)
                sys.stdout.write("\033[2J\033[H")      # 清屏 + 回左上
                print("会话 %s   （每 %gs 刷新，Ctrl-C 退出）\n" % (sid, a.watch))
                print(line(rs, a.limit))
                print()
                print(trend(rs))
                sys.stdout.flush()
                time.sleep(a.watch)
        except KeyboardInterrupt:
            print()
            return 0

    rs = readings(path)
    print(line(rs, a.limit))
    print()
    print(trend(rs))
    if a.hist:
        print()
        print("最近 30 次采样（时刻 / context / 相对上次的增量）：")
        tail = rs[-30:]
        prev = None
        for ts, tok, _m, _o in tail:
            d = "" if prev is None else "%+d" % (tok - prev)
            print("   %s  %-12s %s" % (ts, fmt(tok), d))
            prev = tok
    return 0


if __name__ == "__main__":
    sys.exit(main())

# --------------------------------------------------------------------------- #
# 这个数有多可信（**读之前先知道**）
# --------------------------------------------------------------------------- #
# ① **context 占用是实测的**（直接来自 API 响应的 usage），不是猜的。
# ② **上限是推断的** —— 我读不到模型配置。依据只有：
#      历史实测最大 355,726 tokens 且**那个会话没撞墙** ⇒ 上限 ≥ 356k。
#    取 400k。⇒ **百分比可能偏低**（若真实上限是 1M，那 70% 其实只有 28%）。
#    ★★ 所以：**用它看"涨得快不快"，别拿它当"还剩多少"的精确刻度。**
# ③ 「平均每次涨 N」是**按采样点**算的，而采样点密度不均（一次工具调用一条，
#    一轮回答可能好几条）⇒ 它衡量的是"这一阵子涨得快不快"，
#    **不是"还能聊几句"**。趋势那一行给的"还能走 N 次采样"同理，别当次数用。
# ④ 本工具**只读**那个 jsonl，不写任何东西、不联网、不碰生产。
#
# ★ 为什么不做成 hook（实时自动提示）：
#   hook 要注册进 settings，而**注册本身是写配置** —— 那会改到你所有会话的行为，
#   代价比收益大。**要实时就 `--watch 30`**：另开一个终端跑着，
#   它每 30 秒重读一次文件（文件是持续增长的），屏幕上就是实时读数。

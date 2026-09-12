#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""对账 a − b：日志里「Found」行有多少条**真的是** `_RE_FOUND` 吃下的那种。

a = 用**若干独立字面量**描述的「目标消息形状」命中行数（不含任何捕获组/量词/锚点）
b = 生产代码 `orchestrator.state._RE_FOUND` 命中行数
期望 a − b = 0：形状判据和正则判据说的是同一件事。

为什么需要它
------------
`_RE_FOUND` 是台账的唯一入口 —— 抓不到的行就是**没发生过**。
但这个正则有一串可选分支（`webhook|inject`）和一串非贪婪捕获组，
"少抓了"和"本来就没有"在结果上长得一模一样（都是 0）。

★ 第一版的教训（本脚本存在就是为了防它）：
  拿 `] Found ` 当基线 → 数到 2200，于是 a−b 报了 1189 的**假差**。
  因为那个字面量同时吃到两条别的消息：
  `[webhook] Found 0 torrents for {`（662 行）与
  `[webhook] Found N torrent file(s) to inject`（527 行）。
  基线**既不能用带锚点的正则**（那等于把被测逻辑抄一遍，属于循环论证），
  **也不能太松**（把别的消息吃进来）。

修法：用**独立字面量的合取**描述形状，且**每个字面量单独报数** ——
「是哪个词把行数砍下来的」一眼可见，不依赖任何捕获组。

★ 本脚本**引用生产代码里的那份正则**（`S._RE_FOUND`），不另抄一份字面量 ——
  抄一份的话，正则改了、脚本不报，对账就是自说自话。

用法
----
    python scripts/audit-found-lines.py

全程只读（只 open 日志），不碰库、不碰 NAS 的写路径。
日志是**滚动**的，两次跑的窗口不同 → 绝对数会变，看的是 a − b 这个差。
"""

from __future__ import annotations

import pathlib
import re
import sys

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(REPO))

import orchestrator.state as S          # noqa: E402

# ★ 输出强制 UTF-8：GBK 控制台下会在中途炸掉，
#   而**已经过的打印看着全是 ok** —— 极易误判成逻辑坏了。
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

LOG = pathlib.Path(
    r"//iSunker-DS423/docker_ssd/prowlarr_cross-seed_autohardlink"
    r"/cross-seed/logs/info.current.log")

RE_FOUND = S._RE_FOUND                  # ★ 生产代码那一份，不另抄
_LINE = re.compile(r"^\d{4}-\d\d-\d\d \d\d:\d\d:\d\d\.\d+ \w+: (?P<msg>.*)$")

# 目标形状用**独立字面量**描述（无捕获组、无量词、无锚点）
# ★ 名字与取值分开：上一版把**键**当取值去匹配（`if "L1 `] Found `" not in line`），
#   那个字符串永远不在日志里 → 全表 0，而 0 和"真的没有"长得一模一样。
#   现在下面有三道正向控制，0 不可能再冒充干净。
L1_FOUND   = "] Found "
L3_ON      = "] on "
L4_BY      = " by "
L5_DATADIR = " from dataDir ("
L6_DASH    = " - "
LITS = [
    ("L1 `] Found `",        L1_FOUND),
    ("L2 `[8hex...]`",       None),      # None = 用 HEX8 数
    ("L3 `] on `",           L3_ON),
    ("L4 ` by `",            L4_BY),
    ("L5 ` from dataDir (`", L5_DATADIR),
    ("L6 ` - `",             L6_DASH),
]
HEX8 = re.compile(r"\[[0-9a-f]{8}\.\.\.\]")


def redact(s: str) -> str:
    s = re.sub(r"(apikey=)[^,&\s)\]]+", r"\1<redacted>", s, flags=re.I)
    s = re.sub(r"(passkey=)[^,&\s)\]]+", r"\1<redacted>", s, flags=re.I)
    return s


def main() -> int:
    if not LOG.is_file():
        print(f"✗ 日志不可达: {LOG}", file=sys.stderr)
        return 2

    counts = {k: 0 for k, _ in LITS}
    n_lines = 0
    a_both = 0                 # 五个字面量全中 = 目标形状
    b = 0                      # _RE_FOUND 命中
    other_found: dict[str, int] = {}
    missed: list[str] = []
    g4: dict[str, int] = {}
    g3_odd = 0

    with LOG.open("r", encoding="utf-8", errors="replace") as fh:
        for raw in fh:
            n_lines += 1
            line = raw.rstrip("\r\n")
            if L1_FOUND not in line:
                continue
            hit = {k: (v in line if v else bool(HEX8.search(line)))
                   for k, v in LITS}
            for k, ok in hit.items():
                if ok:
                    counts[k] += 1
            if all(hit.values()):
                a_both += 1
                m = _LINE.match(line)
                msg = m.group("msg") if m else line
                mm = RE_FOUND.search(msg)
                if mm:
                    b += 1
                    g4[mm.group(4)] = g4.get(mm.group(4), 0) + 1
                    if re.search(r"[ ()(]", mm.group(3)):
                        g3_odd += 1
                elif len(missed) < 8:
                    missed.append(line)
            else:
                head = line.split("] Found ", 1)[1][:60] if "] Found " in line else line[:60]
                key = re.sub(r"\d+", "N", head.split("{")[0].strip())[:48]
                other_found[key] = other_found.get(key, 0) + 1

    print(f"日志 : {LOG.name}   总行数 {n_lines}")
    print()
    print("── 基线的每个字面量各自命中多少行（看是哪个词在收窄）──")
    for k, _ in LITS:
        print(f"   {k:<24} {counts[k]:>6}")
    print(f"   ★ 合取（目标形状）      {a_both:>6}")
    print()
    print(f"   b  _RE_FOUND 命中        {b:>6}")
    print(f"   ★ a − b                  {a_both - b:>6}   （期望 0）")
    print()
    print(f"   组 3（站名）带空格/括号  {g3_odd:>6}  ← 09-12 修掉的那类，>0 说明修法在生产里真的被走到")
    print(f"   组 4（硬锚点 \\w+）的值   {sorted(g4.items(), key=lambda kv: -kv[1])}")
    print()
    print("── 被 L1 吃到、但不是目标形状的**其它消息**（应当在这里，不该算进 a）──")
    for k, v in sorted(other_found.items(), key=lambda kv: -kv[1])[:6]:
        print(f"   {v:>6}  {k}")
    if missed:
        print()
        print("── ★ 目标形状但 _RE_FOUND 没吃下的行 ──")
        for s in missed:
            print(f"   {redact(s)[:190]}")

    # ── 正向控制：没有它们，上面的 0 既可能是"没事"也可能是"没跑" ──
    print()
    ok = True
    if n_lines == 0:
        print("✗ 控制①失败：读了 0 行 —— 日志路径/编码不对，下面所有数都不可信")
        ok = False
    if counts[LITS[0][0]] == 0:
        print("✗ 控制②失败：基线 L1 一行都没数到 —— 但历史版本数到过 2200，"
              "说明匹配逻辑坏了，0 是假的")
        ok = False
    if a_both == 0:
        print("✗ 控制③失败：目标形状 0 行 —— 日志里连一条 Found 都没有的话，"
              "a−b=0 是**空转**，不是干净")
        ok = False
    print("✓ 三道正向控制都过（读到了行、基线数到了、目标形状非空）—— 上面的数可信"
          if ok else "★ 控制没过：**不要**把上面的 0 当成干净")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

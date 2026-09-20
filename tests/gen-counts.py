#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""`tests/COUNTS.json` 的**唯一生产者** —— 断言条数的真源。

## 为什么有这个文件（2026-09-20）

用户的判断：**「每次改代码都在收'重建税'」**。病灶不是想法，是**同步** ——
同一个数（某脚本有多少条断言）在**两处手写**：

  · `tests/README.md` 的日期行（「N 个脚本、M 条断言」）
  · `tests/README.md` 的表格每一格

于是每加一条断言就要**手工改两处**，忘了就漂 —— 实测漂过（`1104 → 1124`，
以及 `test_once_gate.py` 从 32 加到 41 后两处**一起**漂、相互抵消、检查仍然绿）。

**处置 = 把「数」降级成派生数据**：

    源   = 跑一遍测试、数它的断言行     ← **只存在于这里**
    派生 = `tests/COUNTS.json`           ← 本脚本产出（人**不许**手改）
    派生 = `tests/README.md` 的生成区    ← `gen-counts.py` 渲染（人**不许**手改）

⇒ 从此「三处联动」变成「**跑一次生成器**」。

## 用法

    python tests/gen-counts.py            # 扫描 → 写 COUNTS.json → 重渲染 README 生成区
    python tests/gen-counts.py --check    # 只校验（不写）；不一致则**退出码 1**（可当闸门）

★ **必须真跑**（2026-09-20 实测，这是本文件最重要的一条设计约束）：
  断言是**运行时打印**出来的（`print(("  ok  " if ok else " FAIL ") + …)`），
  **源码里根本没有那些行** ⇒ 「扫描源码来数断言」这条路**不成立**：
  第一版这么写，把 28 个脚本数成 **1 条断言**（只数到 `test_readme_counts.py` 里
  那句正则字面量自己）。★ 同 `B.10` 第 14 条：**数出来的数看着完全正常。**
  ⇒ 所以本脚本**执行**每个 `test_*.py`，数它 stdout 里的断言行。
  代价：整套约 **40 秒** —— 但那是**机器的时间**，不是人的时间；
  而且只在**真的要更新数字时**跑一次（人的税从这里消失了）。

★ 数法必须与旧 `test_readme_counts.py` **逐字一致**（三种行型都要数）：
  `^  ok  ` / `^ FAIL ` / `: PASS` / `: FAIL`。只数第一种会漏（实测少 8 条）。
"""
import argparse
import datetime
import json
import pathlib
import re
import subprocess
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HERE = pathlib.Path(__file__).resolve().parent          # tests/
COUNTS = HERE / "COUNTS.json"
README = HERE / "README.md"

#: 断言行型 —— ★ 与旧 `test_readme_counts.py` 的 `_ASSERT_LINE` **同一个正则**。
#: 改这里等于改"什么叫一条断言"，会与历史读数不可比 ⇒ 别动。
ASSERT_LINE = re.compile(r"^  ok  |^ FAIL |: PASS|: FAIL")

#: 生成区标记。★ 只重写这两个标记之间的东西 —— 区外（人写的「为什么这么测」
#: 那些注解）**一个字都不碰**。那是本仓最值钱的东西，机器不许碰。
BEGIN = "<!-- counts:auto:begin（本节由 tests/gen-counts.py 生成，别手改）-->"
END = "<!-- counts:auto:end -->"

#: 占位符 —— ★ 它**不是**注解的真源，只用于"这个脚本还没被写过注解"。
#:   ★★ 关键：**不能**把渲染结果里的占位符再读回来当真源（第一版就这么栽的，见 `scan()` 头注）。
PLACEHOLDER = "★ **待补**：这一格是「钉住什么」，人写、不生成。"


def count_asserts(path: pathlib.Path) -> tuple:
    """**真跑**一个测试脚本，数它 stdout 里的断言行。返回 (条数, 退出码)。

    ★ 为什么必须跑：断言行是 `print()` 出来的，源码里没有（见模块头注）。
    ★ 超时给足：单个脚本最慢的约几秒；300s 是给"卡死"留的判据，不是常态。
    """
    r = subprocess.run([sys.executable, str(path)], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=300)
    n = sum(1 for line in (r.stdout or "").split("\n") if ASSERT_LINE.search(line))
    return n, r.returncode


def scan(readme_text: str, prev_notes: dict = None) -> dict:
    """产出源字典。★ 表格每一格的「钉住什么」从 README / 上一份 COUNTS.json 里**保留**。

    ★★ **一条实测教训（2026-09-20，第一版就在这里栽了）**：
      第一版只用"当前 README"当 notes 的来源 ⇒ **第二次跑生成器就把 28 条注解全换成占位符**
      （因为渲染过之后 README 里的注解已经变成了占位符，于是它被当成了真源）。
      实测：跑两遍生成器 ⇒ `diff` 显示 **28 行注解全丢**。
      ⇒ 判据：**notes 必须从「上一份 COUNTS.json」优先取** —— 它是**人写的内容的存档**，
        而 README 只是它的**渲染结果**（渲染结果不能反过来当真源）。
      ★ 同 `A.11`「同一事实只在一处维护」：注解的真源是 **`COUNTS.json`**，
        README 与它不一致时以它为准。
    """
    files = sorted(p.name for p in HERE.glob("test_*.py"))
    by_file, fails = {}, []
    for name in files:
        n, rc = count_asserts(HERE / name)
        by_file[name] = n
        if rc != 0:
            fails.append(name)

    # 注解优先级：① 上一份 COUNTS.json（**真源**）→ ② 当前 README（首次生成时用）
    from_readme = dict(re.findall(r"^\| `(test_\w+\.py)` \| \d+ \| (.+?)\|?$", readme_text, re.M))
    prev = prev_notes or {}
    notes = {}
    for k in by_file:
        for cand in (prev.get(k), from_readme.get(k)):
            if cand and PLACEHOLDER not in cand:
                notes[k] = cand.strip()
                break
        else:
            notes[k] = PLACEHOLDER

    return {
        "by_file": by_file,
        "notes": notes,
        "scripts": len(files),
        "total": sum(by_file.values()),
        "failures": len(fails),
        "failed_files": fails,
        "measured_at": datetime.date.today().isoformat(),
        "command": "python tests/gen-counts.py",
    }


def render(data: dict) -> str:
    """把源渲染成 README 生成区的内容。★ 排序 = 文件名字典序（确定性的，两次跑必相同）。"""
    out = [BEGIN, ""]
    out.append("| 文件 | 断言 | 钉住什么 |")
    out.append("|---|---:|---|")
    for name in sorted(data["by_file"]):
        note = data["notes"].get(name) or "★ **待补**：这一格是「钉住什么」，人写、不生成。"
        out.append(f"| `{name}` | {data['by_file'][name]} | {note} |")
    out.append("")
    d = data["measured_at"] or "（未测）"
    f = data["failures"] if data["failures"] is not None else "?"
    out.append(f"{d} 实测：**{data['scripts']} 个脚本、{data['total']} 条断言、{f} 失败**"
               f"　← ★ 这行由 `{data['command']}` 生成（含表格，整块都是），**别手改**。")
    out.append(END)
    return "\n".join(out)


def splice(readme_text: str, block: str) -> str:
    """把生成区替换掉；没有标记就在表格前插一个。"""
    if BEGIN in readme_text and END in readme_text:
        i = readme_text.index(BEGIN)
        j = readme_text.index(END) + len(END)
        return readme_text[:i] + block + readme_text[j:]
    raise SystemExit("★ README 里没有生成区标记 —— 先按本脚本头注手动放一对标记，别猜。")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true",
                    help="只校验 COUNTS.json 与 README 生成区是否一致（不写）")
    a = ap.parse_args()

    readme_text = README.read_text(encoding="utf-8")
    prev = json.loads(COUNTS.read_text(encoding="utf-8")) if COUNTS.exists() else {}
    fresh = scan(readme_text, prev.get("notes"))
    fresh_str = json.dumps(fresh, ensure_ascii=False, indent=2) + "\n"

    if a.check:
        bad = []
        if not COUNTS.exists():
            bad.append("COUNTS.json 不存在 —— 跑一次 `python tests/gen-counts.py`")
        else:
            old = json.loads(COUNTS.read_text(encoding="utf-8"))
            for k in ("scripts", "total", "by_file"):
                if old.get(k) != fresh.get(k):
                    bad.append(f"COUNTS.json 的 {k} 与实扫不符：{old.get(k)!r} → {fresh.get(k)!r}")
        want_block = render(prev if COUNTS.exists() else fresh)
        if BEGIN in readme_text and want_block not in readme_text:
            bad.append("README 的生成区与 COUNTS.json 不一致（跑生成器重渲）")
        if bad:
            print("★ 不一致（真源 `tests/COUNTS.json` 说了算）：")
            for b in bad:
                print("   " + b)
            return 1
        print(f"[ok] COUNTS.json 与 README 生成区一致："
              f"{fresh['scripts']} 脚本 / {fresh['total']} 条断言")
        return 0

    with open(COUNTS, "w", encoding="utf-8", newline=chr(10)) as fp:
        fp.write(fresh_str)
    new_readme = splice(readme_text, render(fresh))
    with open(README, "w", encoding="utf-8", newline=chr(10)) as fp:
        fp.write(new_readme)
    print(f"→ {COUNTS.relative_to(HERE.parent)}（{fresh['scripts']} 脚本 / {fresh['total']} 条断言）")
    print(f"→ {README.relative_to(HERE.parent)} 的生成区已重渲")
    return 0


if __name__ == "__main__":
    sys.exit(main())

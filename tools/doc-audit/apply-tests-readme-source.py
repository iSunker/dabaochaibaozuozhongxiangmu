#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""一次性：把 `tests/README.md` 改成「源 + 派生」形状（2026-09-20）。

做三件事（**默认 dry-run**）：

1. **搬历史**：L15–L37 那 **12 条**追加式日期行 → `summary/31-测试计数的口径与历史.md`
   ★ 每条**逐字搬**，README 里只留**当前那条**（由生成器渲染）。
   理由：那 12 条是「每跑一次就追加一行」的入口 —— 留着就还会有人手写数字。

2. **插生成区标记**：在 `## 各测什么` 的表格外面包一对
   `<!-- counts:auto:begin -->` / `<!-- counts:auto:end -->`。
   ★ **区外的字一个不动**（那些「钉住什么」的注解是本仓最值钱的东西）。

3. **不生成数字** —— 数字由 `gen-counts.py` 渲染。本脚本只放标记。

★ 铁律：**「钉住什么」那一列必须原样保留** ⇒ 本脚本把表格逐行拆成
  (文件名, 数字, 注解) 三部分，注解**逐字**交回给 `gen-counts.py`。
"""
import argparse
import pathlib
import re
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

REPO = pathlib.Path(__file__).resolve().parent.parent.parent
README = REPO / "tests" / "README.md"
HISTORY = REPO / "summary" / "31-测试计数的口径与历史.md"

BEGIN = "<!-- counts:auto:begin（本节由 tests/gen-counts.py 生成，别手改）-->"
END = "<!-- counts:auto:end -->"
# ★ 行尾那个 `|` **可缺** —— 实测 `test_readme_counts.py` 那一行就少了它
#   （表格式的既存小缺陷，渲染起来看不出）。照"只认规范形态"写会**静默漏掉一行**，
#   而漏掉的那一行恰好是本文件自己 ⇒ 正是 `B.10` 第 14 条那个形状。
ROW = re.compile(r"^\| `(test_\w+\.py)` \| (\d+) \| (.+?)\|?$")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()

    lines = README.read_text(encoding="utf-8").split("\n")

    # ---- ① 定位日期行（连续那段：从第一条 "20xx-xx-xx 实测：" 到最后一个日期行的下一行）----
    date_idx = [i for i, l in enumerate(lines)
                if re.match(r"^\d{4}-\d{2}-\d{2} 实测：\*\*\d+ 个脚本、\d+ 条断言", l)]
    if not date_idx:
        raise SystemExit("★ 找不到日期行 —— 先回读你实际拿到了什么")
    print(f"找到 {len(date_idx)} 条日期行：L{date_idx[0]+1}–L{date_idx[-1]+1}")

    # 历史段 = 从第一条日期行到「表格小节之前」，但只搬**日期行及其续行**。
    # 续行判据：不是日期行、不是空行结尾的段落边界 —— 用「下一个 `## ` 或空行 + 非续行」界定。
    hist_block = [lines[i] for i in date_idx]
    keep_idx = set(date_idx[-1:])          # ★ 只留**最后一条**（当前那条）

    # ---- ② 定位表格 ----
    tbl_start = next(i for i, l in enumerate(lines) if l.startswith("| 文件 | 断言 |"))
    tbl_end = tbl_start
    while tbl_end + 1 < len(lines) and lines[tbl_end + 1].startswith("|"):
        tbl_end += 1
    print(f"表格 L{tbl_start+1}–L{tbl_end+1}（{tbl_end-tbl_start-1} 行数据）")
    rows = [l for l in lines[tbl_start:tbl_end + 1] if ROW.match(l)]
    print(f"  其中可解析的 `test_*.py` 行：{len(rows)}")
    notes = {ROW.match(l).group(1): ROW.match(l).group(3) for l in rows}
    print(f"  注解总长 {sum(len(v) for v in notes.values())} 字符 —— **一个字都不许改**")

    if not a.apply:
        print("\n（dry-run —— 加 --apply 才写）")
        print(f"会把 {len(date_idx)} 条日期行搬进 {HISTORY.relative_to(REPO)}，README 只留最后一条")
        print("会在表格外包一对生成区标记；表格里的数字行将由 gen-counts.py 重渲")
        return 0

    # ---- ③ 写历史文件（逐字搬）----
    HISTORY.write_text(
        "# §31 测试计数的口径与历史\n\n"
        "> ★ **本文件是 2026-09-20 从 `tests/README.md` **逐字搬来**的**（原 L15–L37）。\n"
        "> 搬的理由：那些是「**每跑一次就追加一行**」的读数 —— 留在 README 里，就还会有人\n"
        "> 往里手写数字。⇒ 数字已降级成**派生数据**（`tests/COUNTS.json` + `gen-counts.py`），\n"
        "> **历史读数挪到这里留档**，README 只留**当前那一条**（由生成器渲染）。\n"
        "> ★ 口径（别改）：`^  ok  ` / `^ FAIL ` / `: PASS` / `: FAIL` **三种行型都要数** ——\n"
        "> 只数第一种会漏（实测少 8 条）。见 `tests/gen-counts.py` 的 `ASSERT_LINE`。\n\n"
        "---\n\n" + "\n\n".join(hist_block) + "\n",
        encoding="utf-8", newline=chr(10))
    print(f"→ {HISTORY.relative_to(REPO)}（{len(hist_block)} 条）")

    # ---- ④ README：删历史、包标记 ----
    out = []
    for i, l in enumerate(lines):
        if i in date_idx and i not in keep_idx:
            continue
        out.append(l)
    lines = out
    # 重新定位表格
    tbl_start = next(i for i, l in enumerate(lines) if l.startswith("| 文件 | 断言 |"))
    tbl_end = tbl_start
    while tbl_end + 1 < len(lines) and lines[tbl_end + 1].startswith("|"):
        tbl_end += 1
    # 保留「钉住什么」的注解行（数字会被生成器重写）
    body = [f"| `{n}` | {notes[n]} |" for n in notes]        # 占位（生成器会覆盖数字）
    lines[tbl_start:tbl_end + 1] = [BEGIN, "", "| 文件 | 断言 | 钉住什么 |", "|---|---:|---|",
                                    *body, "", END]
    README.write_text("\n".join(lines), encoding="utf-8", newline=chr(10))
    print(f"→ {README.relative_to(REPO)} 已插生成区标记")
    print("★ 下一步：`python tests/gen-counts.py` 重渲数字")
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""提取 md 标题树。

★ 围栏规则按 CommonMark，不是"见到 ``` 就翻"：
  开栏 = 行首 0~3 个空格 + >=3 个反引号/波浪号 + 可选 info string
  闭栏 = 同种字符、**不短于**开栏、且**后面什么都没有**
  —— 用"见到就翻"的写法，SUMMARY.md 会在 L5815 附近失步，
     之后整条尾巴被吞掉（实测少 115 个标题：h2 少 5、h3 少 38、h4 少 72）。

用法：python 01_headings.py <文档目录>      （默认当前目录）
输出：<脚本目录>/out/headings.tsv
"""
import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

TOOLS = Path(__file__).resolve().parent           # out/ 永远跟着脚本走，不往文档树里拉屎
REPO = TOOLS.parent.parent                        # <repo>/tools/doc-audit → <repo>
DOCS = Path(sys.argv[1] if len(sys.argv) > 1 else REPO).resolve()
OUT = TOOLS / "out"

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mdwalk import doc_files, iter_lines as walk, scan_defects  # noqa: E402

HEAD = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")


def extract(path):
    rows, stack = [], []
    for lineno, line in walk(path):
        h = HEAD.match(line)
        if not h:
            continue
        lvl, title = len(h.group(1)), h.group(2).strip()
        while stack and stack[-1][0] >= lvl:
            stack.pop()
        parent = stack[-1][2] if stack else ""
        slug = "%s/%s" % (parent, title) if parent else title
        rows.append((path.name, lvl, lineno, slug, title, parent))
        stack.append((lvl, title, slug))
    return rows


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    all_rows = []
    # ★ doc_files 而非 DOCS.glob("*.md")：SUMMARY 的正文已拆到 summary/（2026-09-16），
    #   只扫顶层会让 24 章的标题**静默**从标题树里消失。
    files = doc_files(DOCS)
    if not files:
        print("[!!] %s 下没有 .md —— 文档目录传对了吗？" % DOCS)
        return
    n_def = scan_defects(files)
    if n_def:
        print("    ↑ 围栏缺陷会同时骗解析器和渲染器，**先修再计数**")
    print()

    for f in files:
        rows = extract(f)
        all_rows.extend(rows)
        prev = 0
        for _, lvl, ln, _, title, _ in rows:
            if lvl > prev + 1:
                print("[!] 层级跳跃 %s:%d h%d→h%d %r" % (f.name, ln, prev, lvl, title))
            prev = lvl
        lv = {}
        for _, lvl, _, _, _, _ in rows:
            lv[lvl] = lv.get(lvl, 0) + 1
        print("  %-16s %4d 标题   %s" % (
            f.name, len(rows),
            "  ".join("h%d=%d" % (k, lv[k]) for k in sorted(lv))))
    with (OUT / "headings.tsv").open("w", encoding="utf-8") as fp:
        fp.write("file\tlevel\tline\tslug\ttitle\tparent\n")
        for r in all_rows:
            fp.write("\t".join(map(str, r)) + "\n")
    print("[ok] %d 个标题 → %s" % (len(all_rows), OUT / "headings.tsv"))


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""terms.txt 里每个词扫全部 md，输出命中位置 + 跨文件分布。

用法：python 03_terms.py <文档目录>
输入：<脚本目录>/terms.txt
输出：<脚本目录>/out/terms.tsv
"""
import re
import sys
from collections import Counter
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

TOOLS = Path(__file__).resolve().parent
REPO = TOOLS.parent.parent
DOCS = Path(sys.argv[1] if len(sys.argv) > 1 else REPO).resolve()
OUT = TOOLS / "out"

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mdwalk import doc_files, iter_lines as walk, scan_defects  # noqa: E402


def main():
    tf = TOOLS / "terms.txt"
    if not tf.exists():
        print("[!!] 找不到 %s" % tf)
        return
    terms = [t.strip() for t in tf.read_text(encoding="utf-8").splitlines()
             if t.strip() and not t.startswith("#")]
    OUT.mkdir(parents=True, exist_ok=True)
    rows = []
    # ★ doc_files 而非 DOCS.glob("*.md")：SUMMARY 正文已拆到 summary/（2026-09-16）。
    #   ★ 注意口径变了：文件数由 3 变 27，于是下面「跨 >=2 个文件」的判据更宽了 ——
    #     一条关键词若在 §13 和 §20 各出现一次，以前算「1 个文件」（同属 SUMMARY.md），
    #     现在算「2 个文件」。**那是分章带来的，不是新出现的重复**，逐条过时要知道。
    files = doc_files(DOCS)
    for f in files:
        for lineno, line in walk(f):
            for t in terms:
                if t in line:
                    rows.append((t, f.name, lineno, line.strip()[:120]))
    rows.sort()
    with (OUT / "terms.tsv").open("w", encoding="utf-8") as fp:
        fp.write("term\tfile\tline\tcontext\n")
        for r in rows:
            fp.write("\t".join(map(str, r)) + "\n")

    per = Counter(r[0] for r in rows)
    spread = {t: len({r[1] for r in rows if r[0] == t}) for t in per}
    print("[ok] %d 条命中，%d/%d 个关键词有命中，跨 %d 个文件 → %s\n"
          % (len(rows), len(per), len(terms), len(files), OUT / "terms.tsv"))

    print("★ 只出现在 1 个文件里的（= 只维护一处，健康）：")
    for t in sorted(per):
        if spread[t] == 1:
            print("   %4d 次 / 1 文件   %s" % (per[t], t))
    print()
    print("★★ 跨 >=2 个文件的（= 「同一事实多处出现」的嫌疑，逐条过）：")
    multi = sorted(((spread[t], per[t], t) for t in per if spread[t] >= 2), reverse=True)
    for sp, n, t in multi:
        print("   %4d 次 / %d 文件   %s" % (n, sp, t))
    print()
    zero = [t for t in terms if t not in per]
    if zero:
        print("⚠ 一个都没命中的关键词（清单写错了，或事实已消失）：%s" % ", ".join(zero))


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""引用对账：扫所有跨文档锚点，查目标是否真的存在。

管的锚点家族（**六族**，不只原文案的三种）：
  1) §N / §N.M / §N.M.K / §N.M.K.L      → SUMMARY 的编号标题（## 19. / ### 19.1 / §20.8 也算）
  2) ERR-XX-NN                          → ENVIRONMENT.md 的 H3 条目
  3) README「…」 / ENVIRONMENT「…」      → 对应文档的标题（子串命中，必须唯一）
  4) A.N / B.N                          → ENVIRONMENT.md 自己的 H2
  5) 弯路 #N                             → **LEGACY 标签**，不是标题锚点（见下）
  6) （围栏内的引用不算——代码示例里的 §N 是示例，不是引用）

★ 关于 弯路 #N：`走过的弯路.md` 已在 373b1ea 拆掉并入 ENVIRONMENT.md，
  所以它**永远不可能**再命中标题。它的解析器是 ENVIRONMENT.md 顶部那条
  `按「第几项弯路」反查（1..20）` 的 grep。因此单独归为 LEGACY，
  不计进「悬空」——否则 20 条真引用会被 20 条假警报淹掉。

用法：python 02_refs.py <文档目录>
输出：<脚本目录>/out/refs.tsv
"""
import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

TOOLS = Path(__file__).resolve().parent
REPO = TOOLS.parent.parent
DOCS = Path(sys.argv[1] if len(sys.argv) > 1 else REPO).resolve()
OUT = TOOLS / "out"

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mdwalk import iter_lines as walk, scan_defects  # noqa: E402

REF_SEC = re.compile(r"§\s?(\d+(?:\.\d+){0,3})")
REF_ERR = re.compile(r"\bERR-([A-Z]+)-(\d{2})\b")
REF_WW = re.compile(r"弯路\s*#(\d+)")
REF_AB = re.compile(r"`([AB]\.\d+)")
REF_README = re.compile(r"README「([^」]+)」")
REF_ENV = re.compile(r"ENVIRONMENT(?:\.md)?「([^」]+)」")

HEAD_SEC = re.compile(r"^#{2,5}\s+§?\s*(\d+(?:\.\d+)*)\b")
HEAD_ERR = re.compile(r"^#{2,5}\s+(ERR-[A-Z]+-\d{2})\b")
HEAD_AB = re.compile(r"^##\s+([AB]\.\d+)\b")
HEAD_ANY = re.compile(r"^#{1,6}\s+(.*?)\s*$")


def collect(root):
    secs, errs, abs_, heads = set(), set(), set(), {}
    for f in sorted(root.glob("*.md")):
        title_set = set()
        for _, line in walk(f):
            for rx, bag in ((HEAD_SEC, secs), (HEAD_ERR, errs), (HEAD_AB, abs_)):
                m = rx.match(line)
                if m:
                    bag.add(m.group(1))
            h = HEAD_ANY.match(line)
            if h:
                title_set.add(h.group(1).strip())
        heads[f.name] = title_set
    return secs, errs, abs_, heads


def resolve(n, secs):
    """从最具体往最粗找，返回 OK / WEAK / DANGLING。"""
    parts = n.split(".")
    for i in range(len(parts), 0, -1):
        if ".".join(parts[:i]) in secs:
            return "OK" if i == len(parts) else "WEAK"
    return "DANGLING"


def anchor(title, heads, doc):
    hits = [h for h in heads.get(doc, ()) if title in h]
    if len(hits) == 1:
        return "OK", ""
    if len(hits) == 0:
        return "ANCHOR-MISS", ""
    return "ANCHOR-AMBIG", "%d 条:%s" % (len(hits), " | ".join(sorted(hits)[:2])[:70])


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    secs, errs, abs_, heads = collect(DOCS)
    if not heads:
        print("[!!] %s 下没有 .md —— 文档目录传对了吗？" % DOCS)
        return
    scan_defects(sorted(DOCS.glob("*.md")))
    print("目标集合：编号标题 %d · ERR 条目 %d · A/B 条 %d · README 标题 %d · ENV 标题 %d\n"
          % (len(secs), len(errs), len(abs_),
             len(heads.get("README.md", ())), len(heads.get("ENVIRONMENT.md", ()))))

    rows = []
    for f in sorted(DOCS.glob("*.md")):
        for lineno, line in walk(f):
            hint = line.strip()[:80]
            for m in REF_SEC.finditer(line):
                n = m.group(1)
                rows.append((f.name, lineno, "§" + n, resolve(n, secs),
                             "SUMMARY", hint))
            for m in REF_ERR.finditer(line):
                k = "ERR-%s-%s" % (m.group(1), m.group(2))
                rows.append((f.name, lineno, k,
                             "OK" if k in errs else "DANGLING", "ENVIRONMENT", hint))
            for m in REF_AB.finditer(line):
                k = m.group(1)
                rows.append((f.name, lineno, k,
                             "OK" if k in abs_ else "DANGLING", "ENVIRONMENT", hint))
            for m in REF_WW.finditer(line):
                rows.append((f.name, lineno, "弯路#%s" % m.group(1), "LEGACY",
                             "走过的弯路.md（已拆）", hint))
            for m in REF_README.finditer(line):
                st, extra = anchor(m.group(1), heads, "README.md")
                rows.append((f.name, lineno, "README「%s」" % m.group(1), st, extra, hint))
            for m in REF_ENV.finditer(line):
                st, extra = anchor(m.group(1), heads, "ENVIRONMENT.md")
                rows.append((f.name, lineno, "ENVIRONMENT「%s」" % m.group(1), st, extra, hint))

    with (OUT / "refs.tsv").open("w", encoding="utf-8") as fp:
        fp.write("src\tline\tref\tstatus\ttarget\thint\n")
        for r in rows:
            fp.write("\t".join(map(str, r)) + "\n")

    def tally(st):
        return [r for r in rows if r[3] == st]

    print("[ok] 共 %d 条引用 → %s\n" % (len(rows), OUT / "refs.tsv"))
    for st, label in (("DANGLING", "★ 悬空（目标根本不存在）"),
                      ("WEAK", "△ 半悬空（父节点在、这一层不在）"),
                      ("ANCHOR-MISS", "★ 锚点无命中"),
                      ("ANCHOR-AMBIG", "★ 锚点命中多于一")):
        hit = tally(st)
        print("%s：%d 条" % (label, len(hit)))
        for r in hit[:15]:
            print("   %s:%d  %s" % (r[0], r[1], r[2]))
            print("        %s" % r[5])
        if len(hit) > 15:
            print("   ...（共 %d，其余见 refs.tsv）" % len(hit))
        print()
    legacy = tally("LEGACY")
    print("LEGACY（弯路 #N，非悬空，靠 ENVIRONMENT.md 顶部的反查 grep 解析）：%d 条，编号 %s"
          % (len(legacy), sorted({r[2] for r in legacy}, key=lambda x: int(x.split("#")[1]))))


if __name__ == "__main__":
    main()

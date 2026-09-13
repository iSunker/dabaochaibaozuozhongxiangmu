#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""mdwalk —— 三份文档共用的「按 CommonMark 走行 + 报围栏缺陷」小模块。

为什么需要它（实测教训）：
  「见到 ``` 就翻」的写法，在 SUMMARY.md 的 **L5478** 处永久错位 ——
  那一行的形态是 `**已沉淀成工具**：``` `（三反引号在**行尾**），
  CommonMark 说这是**内联代码**，不是围栏；而它会把下一行的裸 ``` **一起吃掉**。
  于是朴素解析器把 5480 行的裸 ``` 当成了「开栏」，从此错位，
  一路吞掉 100+ 个真标题（`#### 18.11.2` … `### 18.15` 全没被数到）。

规则（够用且不脆）：
  ① 围栏行 = 去掉可选引用前缀 `> ` 之后，**整行**是 `^ {0,3}(`{3,}|~{3,})\s*\S*$`
  ② 闭栏必须同种字符、长度 >= 开栏、且后面什么都没有
  ③ 行内出现、又不构成围栏行的反引号串，按**内联代码**处理：
     成对的就地抵消；落单的挂起，吃掉后面第一个等长的串
  ④ 收尾时若还挂着围栏或内联串 —— 报 defect，**不静默**
"""
import re
import sys

sys.stdout.reconfigure(encoding="utf-8")

QUOTE = re.compile(r"^(?: {0,3}> ?)+")
DELIM = re.compile(r"^ {0,3}(`{3,}|~{3,})\s*(\S*)\s*$")
RUN = re.compile(r"`{3,}")


def _core(line):
    """剥掉行首的引用前缀，用来判「这一行整体是不是一个围栏」。"""
    m = QUOTE.match(line)
    return line[m.end():] if m else line


def iter_lines(path):
    """产出 (行号, 行文本)，跳过围栏内部。"""
    fence = None            # (字符, 长度)
    inline = None           # 挂起的内联串长度
    for n, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        core = _core(raw)
        d = DELIM.match(core)
        if fence is not None:
            if d and d.group(1)[0] == fence[0] and len(d.group(1)) >= fence[1] \
                    and not d.group(2).strip():
                fence = None
            continue
        if inline is None and d:
            fence = (d.group(1)[0], len(d.group(1)))
            continue
        # 非围栏行：把内联反引号串按成对/挂起处理，避免它污染围栏状态
        i = 0
        while i < len(raw):
            if raw[i] != "`":
                i += 1
                continue
            j = i
            while j < len(raw) and raw[j] == "`":
                j += 1
            ln = j - i
            if inline is None:
                inline = ln
            elif inline == ln:
                inline = None
            i = j
        yield n, raw
    if fence is not None:
        print("[!] %s 收尾时围栏未闭合：%r —— 后面的标题会全被吞" % (path.name, fence))
    if inline is not None:
        print("[!] %s 收尾时还有落单的内联反引号串（长度 %d）" % (path.name, inline))


def defects(path):
    """报「围栏缺陷」：行内三反引号（既骗解析器也骗渲染器）+ 未闭合围栏。"""
    out = []
    for n, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if RUN.search(raw) and not DELIM.match(_core(raw)):
            out.append((n, "内联三反引号", raw.strip()[:100]))
    return out


def scan_defects(paths):
    total = 0
    for p in paths:
        d = defects(p)
        if d:
            print("★ %s —— %d 处围栏缺陷：" % (p.name, len(d)))
            for n, kind, t in d:
                print("    L%-6d [%s] %s" % (n, kind, t))
        total += len(d)
    return total

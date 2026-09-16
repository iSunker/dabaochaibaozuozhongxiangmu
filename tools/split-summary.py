#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""把 SUMMARY.md 拆成「入口 + 分章目录」—— **字节不变**地把 8305 行切到 summary/。

为什么拆（2026-09-16）：
  SUMMARY.md 一家 516 KB / 8305 行，占三份文档总量的 62%。查一句「驱动层为什么
  迁到 NAS」最坏要吞 516 KB，而那一章只有 12.6 KB —— 差 40 倍。
  ★ 字面意义的「无损压缩」**做不到**：全量重复率 0.1%（#113 实测定论），
    代码只占 12.4%，剩下 87% 是散文且句句是踩坑记录。所以本脚本压的不是文件，
    是**「整份读」这个动作**。

本脚本干的事：
    SUMMARY.md        → L1..导航结束（入口：导航 + §N→文件 表）
    summary/NN-名.md  → §0..§23 共 24 章

无损的定义（**可机器证明，不是承诺**）：
    把 summary/*.md 按序拼接 ⇔ 原 SUMMARY.md 从第一个章标题起的全部字节。
    逐个字节相同，行尾（CRLF）原样保留。
    ★ 原始文本永久可从 git 父提交取回：`git show <父提交>:SUMMARY.md`。

两个必须遵守的约束（都不是猜的）：
  ① **必须围栏感知** —— 直接 `grep '^## '` 会数错：文档里有 `# ---------- 源清单`
     这类**代码注释冒充标题**（我第一版 awk 就踩了）。复用 mdwalk.iter_lines。
     ★ 而**不用** mdwalk 也是错的：01_headings.py:8 记着朴素解析器会在 L5478 的
     **行尾三反引号**处永久错位，一路吞掉 100+ 个真标题。围栏规则必须按 CommonMark。
  ② **必须在字节层切** —— 工作区是 CRLF，`read_text()` 会丢掉 `\r`，
     于是"字节不变"当场破功。这里按 `b'\n'` 切、用同一分隔符拼回，
     重建是恒等式（`b'\n'.join(data.split(b'\n')) == data`），不依赖任何假设。

用法：
    python tools/split-summary.py            # 预览（默认 dry-run，不写盘）
    python tools/split-summary.py --apply    # 执行
"""
import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

TOOLS = Path(__file__).resolve().parent
REPO = TOOLS.parent
SRC = REPO / "SUMMARY.md"
OUTDIR = REPO / "summary"

sys.path.insert(0, str(TOOLS / "doc-audit"))
from mdwalk import iter_lines as walk  # noqa: E402

# 章起始 = **恰好二级**标题 + 数字编号。
#   `## 18. 目录布局…` 与 `## §21 IYUU…` 两种写法都要认（21~23 章没有点号）。
#   `##(?!#)` 保证是 H2 —— §18 里那一堆 `### 18.19` 是 H3，不是章边界。
#   没有数字的 `## 导航（先读这里 30 秒）` 因此被排除 ⇒ 它留在入口里，正是我们要的。
SEC = re.compile(r"^##(?!#)\s+§?\s*(\d+)(?:[.\s]|$)")

# §号 → 文件名短名。**显式写死，不从标题现推**：
#   §18 标题含 `/`、§15 含 `：`，Windows 文件名不许有 `/`，自动推导会推出脏名；
#   而且写死才能一眼看出「哪个编号对应哪个文件」，改起来也不用重跑脚本。
NAMES = {
    0: "占位符约定",
    1: "目标",
    2: "拓扑",
    3: "关键决策与踩过的坑",
    4: "各文件最终状态",
    5: "进度",
    6: "已了结的坑",
    7: "其它非阻塞问题",
    8: "安全约定",
    9: "环境备忘",
    10: "v2多包支持",
    11: "单片状态机",
    12: "收尾归档",
    13: "接手会话",
    14: "驱动层迁到NAS",
    15: "通知发信与ssmtp路径坑",
    16: "待做的四个自动化",
    17: "首次真跑的探针发现",
    18: "目录布局调整",
    19: "原理技术与风险须知",
    20: "观测层语义收敛",
    21: "IYUU保存目录与旧根漏网",
    22: "matched_indexers恒空与HDtime的429",
    23: "卷归属复核与SMB探针分辨力",
    24: "SUMMARY分章与本轮收口",
    25: "三轮收口与等触发",
}


def truncate_entry():
    r"""把 SUMMARY.md 截成「只剩入口」—— 正文部分已经进了 summary/。

    ★ 为什么单独一步、还要 `--truncate-entry` 显式触发：
      切分（--apply）和截断是**两件事**，中间夹着「人给入口补 §N→文件 表」。
      第一版把两件事都算成 --apply 干的，于是补完表就以为完事了 ——
      **正文在两个地方各留了一份**（doc-audit 立刻看出来：标题 573 → 924，
      各章标题被数了两遍；引用 1048 → 1458 同理）。
      自检没发现，是因为「切分无损」和「入口已更新」是**两条不同的断言**，
      当时那条 cmp 只证明了前者。

    ★ 截断前必须验证：**待删的正文 ⇔ summary/ 里全部文件的拼接**，逐字节相同。
      对不上就说明两边已经不同步，此时截断 = 静默丢数据 —— 所以拒绝。
    """
    if not OUTDIR.is_dir() or not list(OUTDIR.glob("*.md")):
        print("✗ %s 里没有章文件 —— 先跑 --apply" % OUTDIR)
        return 1

    data = SRC.read_bytes()
    lines = data.split(b"\n")
    full = lines[:-1]

    first = None
    for lineno, text in walk(SRC):
        if SEC.match(text):
            first = lineno
            break
    if first is None:
        print("✗ 没找到第一个章标题 —— SUMMARY.md 是不是已经截过了？")
        return 1

    head = b"\n".join(full[:first - 1]) + b"\n"
    tail = b"\n".join(full[first - 1:]) + b"\n"
    body = b"".join(p.read_bytes() for p in sorted(OUTDIR.glob("*.md")))

    if body != tail:
        print("✗ 拒绝截断：SUMMARY.md 里待删的正文与 summary/ 的拼接**不一致**")
        print("   待删 %d B  vs  summary/ %d B" % (len(tail), len(body)))
        return 1

    SRC.write_bytes(head)
    print("✓ SUMMARY.md 截到入口：%d 行 / %d B（原来 %d 行 / %d B）"
          % (head.count(b"\n"), len(head), len(full), len(data)))
    print("  正文 %d B 现在只在 summary/ 里，两边逐字节相同" % len(body))
    return 0


def main():
    apply = "--apply" in sys.argv
    if not SRC.is_file():
        print("✗ 找不到 %s" % SRC)
        return 1

    data = SRC.read_bytes()
    # ★ 按 b'\n' 切，**丢掉末尾那个空串**：剩下的每个元素都是「一整行，不含收尾 \n」。
    #   于是「整份 ↔ 逐行」是恒等式：  b'\n'.join(full) + b'\n'  ==  data
    #   —— 不依赖 LF/CRLF 假设（\r 只是行长里的一个普通字节，原样带着走）。
    lines = data.split(b"\n")
    full = lines[:-1]
    if b"\n".join(full) + b"\n" != data:
        print("✗ 原文不是以 \\n 收尾 —— 本脚本的前提不成立，拒跑")
        return 1

    # ---- 找真章标题（围栏外、恰好 H2、带编号）----
    # walk() 只产出围栏**外**的行；用它给的行号回查 lines（行号 1-based）。
    starts = []                          # [(章号, 行号1based, 标题)]
    for lineno, text in walk(SRC):
        m = SEC.match(text)
        if m:
            starts.append((int(m.group(1)), lineno, text.strip()))
    if not starts:
        print("✗ 一个章标题都没找到 —— 围栏状态是不是没收敛？")
        return 1

    nums = [s[0] for s in starts]
    if nums != sorted(nums) or len(set(nums)) != len(nums):
        print("✗ 章号不是严格递增/有重复：%s" % nums)
        return 1

    missing = [n for n in nums if n not in NAMES]
    if missing:
        print("✗ NAMES 里缺这些章号的短名：%s —— 先补上再跑" % missing)
        return 1

    entry_end = starts[0][1] - 1         # 入口 = 第一个章标题之前的全部行（0-based 切片右界）
    entry = b"\n".join(full[:entry_end]) + b"\n"

    # ---- 切块 ----
    chunks = []                          # [(章号, 文件名, 字节)]
    for i, (num, ln, _t) in enumerate(starts):
        lo = ln - 1                      # 0-based 起
        hi = (starts[i + 1][1] - 1) if i + 1 < len(starts) else len(full)
        # ★★ 每块必须**自带收尾 \n**。
        #    第一版漏了这一步：`b"\n".join(切片)` 不给末行补换行 ——
        #    那个 \n 是「切到下一块去的分隔符」，不跟着块走。
        #    后果不是少字节，而是**把每章末尾的空行并进了下一章的标题行**
        #    （`---\r\n` + `\r` + `## 1. …` ⇒ 空行没了、标题行多了个 \r）。
        #    24 个边界丢 23 行 —— 与实测的「少 23 行 / 23 字节」严丝合缝。
        chunks.append((num, "%02d-%s.md" % (num, NAMES[num]),
                       b"\n".join(full[lo:hi]) + b"\n"))

    # ---- 无损自检 ----
    # ★★ 这里**不能**用 b"\n".join(chunks) 去拼 —— 那恰好会把上面漏掉的收尾 \n
    #    又补回来，于是**自检与 bug 自洽，永远绿**。第一版就是这么写的：
    #    dry-run 两条自检全过，落盘后一 cmp 才露馅（见上）。这是本仓反复记档的
    #    「假测试」形状 —— 判据必须用**与落盘完全相同的字节**去拼，即 b"".join。
    rebuilt = b"".join(c[2] for c in chunks)
    expect = b"\n".join(full[entry_end:]) + b"\n"
    ok = rebuilt == expect
    whole_ok = entry + rebuilt == data

    print("入口 SUMMARY.md : %d 行  %d B" % (entry_end, len(entry)))
    print("分章 %d 个       : %d B" % (len(chunks), len(rebuilt)))
    print()
    print("%-4s %-34s %8s %7s  %s"
          % ("§", "文件（summary/ 下）", "字节", "行数", "标题"))
    for num, name, body in chunks:
        title = next(t for n, _, t in starts if n == num)
        title = SEC.sub("", title).strip() or title
        assert body.endswith(b"\n"), "块没带收尾换行"     # ★★ 见上面第一版的教训
        print("%-4d %-34s %8d %7d  %s"
              % (num, name, len(body), body.count(b"\n"), title[:40]))

    print()
    print("无损自检  分章拼回 ⇔ 原文尾段 : %s" % ("✓ 逐字节相同" if ok else "✗ 不一致！"))
    print("无损自检  入口 + 分章 ⇔ 原文   : %s" % ("✓ 逐字节相同" if whole_ok else "✗ 不一致！"))
    if not (ok and whole_ok):
        print("\n✗ 自检没过，**不写盘**。")
        return 1

    if not apply:
        print("\n（dry-run）确认无误后执行： python tools/split-summary.py --apply")
        return 0

    if OUTDIR.exists() and any(OUTDIR.glob("*.md")):
        print("\n✗ %s 里已有 .md —— 本脚本是一次性的，**不覆盖**。" % OUTDIR)
        print("  要重来请先 git 恢复：git checkout -- SUMMARY.md && rm -rf summary/")
        return 1

    OUTDIR.mkdir(exist_ok=True)
    for _, name, body in chunks:
        (OUTDIR / name).write_bytes(body)
    print("\n✓ 写入 %d 个章文件 → %s/" % (len(chunks), OUTDIR))
    print("→ 入口 SUMMARY.md **尚未改动**：请手工补「§N → 文件」表。")
    return 0


if __name__ == "__main__":
    # 两步走：先 --apply 铺章文件，人补完入口的 §N→文件 表，再 --truncate-entry 收口。
    if "--truncate-entry" in sys.argv:
        sys.exit(truncate_entry())
    sys.exit(main())

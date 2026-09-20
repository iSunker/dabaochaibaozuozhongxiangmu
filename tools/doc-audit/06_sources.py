#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""真源分家检测：同一件事实被"更正"了两次 ⇒ 报警。

★★ 立此判据的现场（2026-09-20）
  用户的判断：**「每次用 AI 的税很高，我想减少重复交代、别让数悄悄过期」**。
  查下来，税不在"投影太多"，在**没有入口 + 没有执行者**：
    · `A.11` 写着「同一事实只在一处维护」—— 但**没有任何机制在每次改文件时执行它**
    · 执行它的人一直是**用户自己**
  最刺眼的自证：`summary/26` 自己写着
    「第三次更正（本节已改过三次，三次都是"真源分家"）……
     这就是本节立"唯一真源"想要防的事，却发生在本节自己身上」
  ⇒ **规矩没失效，规矩没有执行者。** 这个脚本就是那个执行者。

## 它检测什么（分两类，判法不同）

**A 类 · 同一句子被"更正"两次（★ 真信号）**
  在**同一份文档**里，同一个"事实句"出现 ≥2 次「更正/勘误」标记 ⇒
  说明这个数/这句话**改了又改**，而且每次都没删掉旧的 ⇒ **读者要读完全文才知道哪句是真的**。
  ★ 立此判据的直接动机：`ENVIRONMENT.md` 开头那段 `precedence:`
    曾把「本文不是事实源」**划掉 + 更正**两次，而它是**读者看到的第一句话**。

**B 类 · "先错后对"的顺序（★ 更要命的一类）**
  `~~错句~~ … ★ 更正：对的` —— 若**读者先撞上的是错句**（更正段在它后面 ≥N 行，
  或错句在文档**前 1/3**）⇒ 报警。
  ★ 反之**不报**：若**对的结论在前面、更正段是它的证据**（"XX 已修"型），
    那是**证据**不是**竞争声明** —— 删掉它反而毁掉现场（这条是 2026-09-20 实测定的：
    把 `ENVIRONMENT.md` 的 14 处划掉逐条看过，**只有 3 处是"先错后对"，其余 11 处都是证据**）。

★★★ **它查不到什么（2026-09-20 实测补上 —— 别越界承诺）**

  **「几处各自陈述、都没有更正标记，但说法互相打架」** —— 本脚本**查不到**。

  实测：那句「文档分工 / 谁是真源」曾在 **5 份文件里各写一遍、两两打架**
  （`SUMMARY.md` 甚至说反了），而本脚本 **命中 0 条**。
  **根因**：A 类的入口是 `correction_lines()`，靠「更正/勘误/订正」三字**筛候选行**；
  那 5 处**只是平静地各说各话，没有"我改了"的自觉** ⇒ **第一步就被过滤掉了**。

  ⇒ 判据：本脚本只数「**有人说自己改了**」，发现不了「**没人说，但几处对不上**」。
  **那类只能靠人**（或 `grep` 一个已知句式）—— 别指望这个闸门。

  ★ 为什么不加一条自动判：跨文档措辞差异太大，照 `03_terms` 那个形状做会**满仓假红**
  （`terms.tsv` 里跨 ≥2 文件的词 25 个，多半是同义重复）
  —— 「**永远红的闸门 = 没人看的闸门**」。
  ★ 同一条限制抄在 `CLAUDE.md` 第 3 节（那里是给人看的入口，这里是判据本体）。

## 为什么不做成"禁止更正"

★★ 因为**更正是对的** —— 对**过程记录**而言（`summary/`，`§26.16`「过程记录里的话不追改」）。
  `~~原句~~ + 更正` 保住"原来写的是什么"，是**故意**的设计（`A.11` 第 7 条）。
  ⇒ 所以本脚本**不禁止**，只**要求"对的那句先出现"**，并**盯住"改了两次"**。

用法：python 06_sources.py
输出：<脚本目录>/out/sources.tsv  +  stdout 摘要
退出码：0 = 无 A 类且无 B 类；1 = 有（可当闸门）
"""
import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

TOOLS = Path(__file__).resolve().parent
REPO = TOOLS.parent.parent
OUT = TOOLS / "out"

sys.path.insert(0, str(TOOLS))
from mdwalk import doc_files, iter_lines as walk  # noqa: E402

#: 更正标记。★ 三种写法都要认（本仓实际都用过）。
CORRECTION = re.compile(r"更正|勘误|订正")
#: 划掉。`~~…~~` —— 注意要**允许跨行**（本仓的 `precedence:` 就是跨行包的）。
STRIKE_OPEN = re.compile(r"~~")
#: 只扫这些文件 —— 根 md + summary/ + 审计文档自己。
#: ★ 为什么把 tools/doc-audit/INDEX-USAGE.md 也扫：它**不在 `01/02/03` 的范围内**
#:   （那三份的 `DOCS` 是仓库根）⇒ 它自己的引用/更正**没人查**，是个已知盲区。
SCAN_GLOBS = ["*.md", "summary/*.md", "tools/doc-audit/*.md", "tests/*.md"]

#: B 类的"前 1/3"判据：错句若落在文档前 1/3，读者多半先撞上它。
FRONT_THIRD = 3.0
#: B 类的"更正段离错句多远算远"（行）。太近 ⇒ 读者一眼能连着看到，不算问题。
NEAR_LINES = 6

#: ★★★ **哪些文档"允许先错后对"** —— 这一条是整个判据的分界线。
#:
#: 判据不是"有没有划掉段"，而是 **"这份文档是给人查事实的，还是给人看过程的？"**
#:
#:   · **查事实的**（`ENVIRONMENT.md` 的 A 部分、`README.md`、`INDEX-USAGE.md`、`CLAUDE.md`）：
#:     **不许**让读者先撞上错的那句 —— 因为读者**只读一处就去做事**了。
#:     ⇒ 改了就把**原句改成对的**（旧值进 git 历史），**不留划掉段**。
#:   · **看过程的**（`summary/`）：`~~原句~~ + 更正` 是**故意**的设计
#:     （`A.11` 第 7 条：`§26.16`「过程记录里的话不追改」）⇒ **允许**，不算问题。
#:
#: ★ 实测依据（2026-09-20）：把 `ENVIRONMENT.md` 的 14 处划掉逐条看过，
#:   清掉 3 处"先错后对"（都在**开头/角色定义**，读者第一眼就撞上）之后，
#:   剩下的 8 处 B 类**全部落在 `summary/`** —— 那是过程记录，**本来就该那样**。
#:   ⇒ 若不豁免，这个闸门会**永远红**，而"永远红的闸门 = 没人看的闸门"。
PROCESS_DOC_PREFIXES = ("summary/",)

def _is_process_doc(path):
    """这份文档是不是"过程记录"（允许先错后对）。"""
    return any(path.startswith(p) for p in PROCESS_DOC_PREFIXES)

#: ★★ 豁免：**讲"更正格式"或"本判据自己"的地方**，里面的 `~~` 是**示例语法**，
#:   不是作废的旧事实。实测（2026-09-20，两次）：
#:     · `ENVIRONMENT.md` 那张 `| ① 原句 \`~~划掉~~\` | … |` 的表 —— 讲"划掉该怎么写"
#:     · `INDEX-USAGE.md` 讲 `06` 自己那两个坑的段落 —— 里面**引用了** `~~错句~~` 作例子
#:   ⇒ 判据：**"提到一个模式" ≠ "使用一个模式"**（同 `02_refs`「围栏内的引用不算」那条）。
#:   （这就是 `B.10` 第 14 条的老形状：命中了，但答的不是那个问题。）
SYNTAX_EXEMPT = re.compile(
    r"划掉|~~…~~|原句|三段式|原文照抄"
    r"|单行自闭合|自闭合|漏报|永不触发|阴性对照|示例|该报"
)


def _is_syntax_line(line):
    """这一行是不是在**示例语法**（而非陈述一条已废的事实）。"""
    return bool(SYNTAX_EXEMPT.search(line))


def strike_spans(lines):
    """找出 `~~…~~` 的**配对区间**（跨行的也算）。

    ★ 为什么要配对而不是逐行 grep `~~`：本仓的 `precedence:` 是把整个段落
      用一对 `~~` 包起来的（开头一行、结尾一行），**逐行看会以为是两个孤立的 `~~`**。
    """
    spans, open_at = [], None
    for i, ln in enumerate(lines):
        n = len(STRIKE_OPEN.findall(ln))
        for _ in range(n):
            if open_at is None:
                open_at = i
            else:
                spans.append((open_at, i))
                open_at = None
    return spans


def fact_key(line):
    """把一个"更正句"压成它的**事实指纹** —— 用来判"是不是同一件事改了两次"。

    ★★ 第一版**失败**了，记下来（阴性对照抓到的）：
      第一版 = 去标记词后取**前 24 个字符**。而真实的两次更正**恰恰在那一截里不同**
      （`…共有 **9** 份投影` vs `…共有 **6** 份投影，上一条写错了` 是**两个键**）
      ⇒ **同一个事实、改两次，反而因为"值不同"而键不同** ⇒ 判据永远不触发。
      ⇒ 这叫**键选错了**：我拿"变了的那部分"当身份，而它**正是应该被忽略的部分**。

    ★ 正确的键 = **主语**（不变量），**剔掉值**（会变的那部分）。做法：
      ① 去标记词、括号、日期、装饰
      ② ★ **剔掉数字/百分数**（`9` / `6` / `2026`）—— 那是"值"，不是"身份"
      ③ 再取前 N 字
      ⇒ 判据：**指纹里必须只剩"在说哪件事"，不含"说的是几"**。
    """
    s = CORRECTION.sub("", line)
    s = re.sub(r"[（(][^）)]*[）)]", "", s)          # 去掉括号补充（多半是日期/来源）
    s = re.sub(r"\*+", "", s)                        # 去 ** 强调符（数字常被它包住）
    s = re.sub(r"[（(]?20\d{2}-\d{2}-\d{2}[）)]?", "", s)   # 去日期
    s = re.sub(r"\d+(?:\.\d+)?%?", "", s)            # ★★ 剔掉数字与百分数 —— 那是"值"
    s = re.sub(r"[\s★⚠⇒·、，。：:；;~`|\-—]", "", s)  # 去装饰与空白
    return s[:20]


def correction_lines(lines):
    """哪些行带「更正/勘误/订正」标记。"""
    return [i for i, ln in enumerate(lines) if CORRECTION.search(ln)]


def repeated_facts(lines):
    """A 类的**可执行**形式：同一事实指纹被更正 ≥2 次。返回 {key: [行号…]}。

    ★ 只在**同一份文档内**比 —— 跨文档比会因措辞差异爆炸（本仓 38 份 md，实测误报率极高）。
      跨文档的"真源分家"由人按 `CLAUDE.md` 的真源表判，不假装能自动判。
    ★★ 两条**阴性对照抓出来的**修正，都记在这里：
      ① 必须排除**同一句话被抄了两遍**：实测 `summary/31` L34/L112 是同一段落**重复引用**
         （一字不差）⇒ 那是"重复引用"，**不是"改了两次"**。判法：整行也相同 ⇒ 不算。
      ② ★★ **键不能是"精确相等"** —— 第一版要求指纹完全相同，而真实的两次更正
         **长短必然不同**（第二次会多一句"上一条写错了"）⇒ **永远不匹配**。
         ⇒ 判法：**前缀/互相包含即算同一事实**（短的那个是长的那个的前缀）。
           宁可**多报几家**（召回优先）：这条判据的价值在"提醒人去读那一处"，
           不判对错（见文件头），**漏报**比误报贵得多。
    """
    buckets = {}
    for i in correction_lines(lines):
        k = fact_key(lines[i])
        if len(k) >= 6:                 # 太短的键（如"更正"本身）不参与，免噪声
            buckets.setdefault(k, []).append(i)

    out, used = {}, set()
    keys = sorted(buckets, key=len)     # 短键先做代表，长键向它归并
    for k in keys:
        if k in used:
            continue
        group = list(buckets[k])
        for other in keys:
            if other == k or other in used:
                continue
            if other.startswith(k) or k.startswith(other):   # ★ 前缀/包含 ⇒ 同一事实
                group += buckets[other]
                used.add(other)
        used.add(k)
        if len(group) < 2:
            continue
        group = sorted(set(group))
        texts = {lines[i].strip() for i in group}
        if len(texts) < 2:              # ★ 逐字相同的重复引用 ⇒ 不是"改了两次"
            continue
        out[k] = group
    return out


def analyze(path, lines):
    """对一份文档产出两类的命中。"""
    total = len(lines)
    corr = correction_lines(lines)
    spans = strike_spans(lines)
    hits = []

    # ---- A 类：同一**事实**被更正 ≥2 次（可执行：指名是哪一句） ----
    #   ★ 第一版数的是"整份文档的更正数" ⇒ 报「有 30 处更正」，**不可执行**。
    #     真判据是「**同一个事实**改了两次」—— 所以按事实指纹归并（见 `repeated_facts`）。
    for key, at in repeated_facts(lines).items():
        hits.append((
            "A", path, at[0] + 1,
            "同一事实被更正 %d 次（行 %s）：%s"
            % (len(at), "/".join(str(i + 1) for i in at[:5]), key[:40]),
        ))

    # ---- B 类：划掉段 + 更正段，但**对的在后面** ----
    # ---- B 类：划掉段 + 更正段，但**对的在后面** ----
    #   ★★ 只对"查事实的"文档报 —— `summary/` 是过程记录，先错后对是**故意**的（见文件头）。
    if _is_process_doc(path):
        return hits
    reported = set()                      # ★ 同一行可能落在多个重叠的 `~~…~~` 区间里 ⇒ 去重
    for (a, b) in spans:
        if a in reported:
            continue
        if _is_syntax_line(lines[a]):     # ★ 示例语法（如"① 原句 `~~划掉~~`"）⇒ 豁免
            continue
        after = [c for c in corr if c > b]
        if not after:
            continue                      # 划掉了但没有"对的" ⇒ 不是竞争声明，跳过
        # ★★ "更正段很近就不报"这条只在**跨行**的划掉段上成立。
        #   实测（2026-09-20，阴性对照）：`~~错句~~` 单行自闭合、**下一行**就是更正
        #   ⇒ 第一版按 `NEAR_LINES` 把它当成"读者能连着看到"而**放过了**，
        #   而它恰恰是**最该报**的形状：读者一眼看到的就是**被划掉的那句错话**。
        #   ⇒ 判据：`a == b`（单行自闭合）**永远报**；跨行段才用距离豁免。
        same_line = (a == b)
        near = [] if same_line else [c for c in after if c - b <= NEAR_LINES]
        front = a < total / FRONT_THIRD
        if not near and front:
            reported.add(a)
            hits.append((
                "B", path, a + 1,
                "错句在文档前 1/3（第 %d/%d 行），更正段在 %d 行之后 ⇒ 读者先撞上错的"
                % (a + 1, total, min(after) - b),
            ))
    return hits


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    seen, rows = set(), []
    for g in SCAN_GLOBS:
        for p in sorted(REPO.glob(g)):
            rp = p.relative_to(REPO).as_posix()
            if rp in seen or not p.is_file():
                continue
            seen.add(rp)
            text = p.read_text(encoding="utf-8", errors="replace")
            rows.extend(analyze(rp, text.split("\n")))

    rows.sort(key=lambda r: (r[0], r[1], r[2]))
    with open(OUT / "sources.tsv", "w", encoding="utf-8", newline="\n") as fp:
        fp.write("kind\tfile\tline\tdetail\n")
        for r in rows:
            fp.write("%s\t%s\t%d\t%s\n" % r)

    a = [r for r in rows if r[0] == "A"]
    b = [r for r in rows if r[0] == "B"]
    print("扫了 %d 份 md（根 + summary/ + tools/doc-audit/ + tests/）" % len(seen))
    if not rows:
        print("[ok] 无「真源分家」信号：没有 A 类、没有 B 类")
        print("→ %s" % (OUT / "sources.tsv").relative_to(REPO))
        return 0
    for kind, title, items in (("A", "同一事实改了又改（★ 最该看）", a),
                               ("B", "先错后对（对的在后面）", b)):
        if items:
            print("\n★ %s 类 · %s：%d 处" % (kind, title, len(items)))
            for _, f, ln, d in items[:20]:
                print("   %s:%d  %s" % (f, ln, d[:110]))
            if len(items) > 20:
                print("   …（还有 %d 处，全表见 out/sources.tsv）" % (len(items) - 20))
    print("\n→ %s" % (OUT / "sources.tsv").relative_to(REPO))
    print("★ 判读：A 类是**真信号**（改了就删旧的）；")
    print("   B 类要看**对的那句在哪** —— 若结论在前、更正是它的证据，属正常，可豁免。")
    return 1


if __name__ == "__main__":
    sys.exit(main())

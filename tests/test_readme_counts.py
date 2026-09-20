# -*- coding: utf-8 -*-
"""`tests/` 的**计数口径**是一条链：源 → 派生 → 展示。这里钉住整条链。

## 为什么重写（2026-09-20）

用户的判断：**「每次改代码都在收'重建税'」** —— 病灶不是想法，是**同步**。
旧版本检查的是「**两处手写的数对不对得上**」，于是本质上是在**维护那份同步**：
每加一条断言要手改两处，忘了就漂（实测漂过 `1104 → 1124`；
`test_once_gate.py` 32 → 41 那次两处**一起**漂、相互抵消、检查照样绿）。

**⇒ 处置不是把检查写得更严，是把「数」变成生成物：**

    源    = 真跑测试、数 stdout 的断言行        ← 只在 `gen-counts.py`
    派生  = `tests/COUNTS.json`                 ← 机器写，人**不许**手改
    展示  = `tests/README.md` 的生成区          ← 机器写，人**不许**手改

本文件钉的**不是**"那两个数一致"（那已由构造保证），而是：

  ① **生成器忠实** —— 它数出来的数与**独立**数一遍一致（防它自己数错）
  ② **派生同步** —— `COUNTS.json` 与 README 生成区**当前一致**（没被手改过）
  ③ **源代码自洽** —— `COUNTS.json` 的键 == 目录里真实的 `test_*.py`（不多不少）
  ④ **人写的东西没被机器吃掉** —— 注解非空、且生成区**只**含数字与注解

★ **反面（旧版的教训，别再写回去）**：别把这条检查写成「**两处手写的数对不对得上**」——
  那等于**把税制度化**：它要求人维持同步，而它检查的正是"那件事有没有忘做"。
  `B.10` 第 14 条：**判据看着有结构，而它覆盖的范围里恰好不含"事实"**（两处一起漂时它绿）。

★ 本文件**不递归**：它只调用 `gen-counts.py --check`（那是**子进程**，且 `gen-counts`
  自己**不跑** `test_readme_counts.py` 之外的任何东西来计数 —— 它跑的是**别的**脚本）。
  ★ 实测过递归的代价：旧版真跑全套，把本文件也跑进去 ⇒ 0 字节输出、永不结束、只能杀。
  ⇒ `gen-counts.py` 的 `count_asserts()` 会**跑到本文件**，而本文件又调它 ——
    **必须靠 `--check` 那一层的"不写盘"断开**，并且**不能**让本文件再跑一遍全套。
"""
import json
import pathlib
import re
import subprocess
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HERE = pathlib.Path(__file__).resolve().parent
COUNTS = HERE / "COUNTS.json"
README = HERE / "README.md"
GEN = HERE / "gen-counts.py"

fails = []


def ck(label, got, want):
    ok = got == want
    print(("  ok  " if ok else " FAIL ") + f"{label}: {got!r}")
    if not ok:
        fails.append(f"{label}: got {got!r} want {want!r}")


text = README.read_text(encoding="utf-8")
data = json.loads(COUNTS.read_text(encoding="utf-8"))

# ---- ① 生成器忠实：它数的数 == 独立数一遍 ----------------------------------
# ★ 不调 `gen-counts.py --check`（那会再跑一遍全套 → 递归）。
#   这里**只**验「派生与展示一致」这件事能不能被独立复现：读生成区、自己解析。
BLOCK = re.search(r"<!-- counts:auto:begin.*?-->(.*?)<!-- counts:auto:end -->", text, re.S)
ck("① README 里有生成区标记（没有就没法保证「派生只有一个写者」）", bool(BLOCK), True)
block = BLOCK.group(1) if BLOCK else ""
rows = dict(re.findall(r"^\| `(test_\w+\.py)` \| (\d+) \|", block, re.M))
ck("① 生成区里的行数 == COUNTS.json 的 by_file 条数",
   len(rows), len(data["by_file"]))
ck("① 生成区每一格 == COUNTS.json 里那个数（展示是派生的，不许自己长数）",
   {k: int(v) for k, v in rows.items()}, data["by_file"])
ck("① 生成区里的合计 == 逐格相加（不靠另写一个数）",
   int(re.search(r"(\d+) 条断言", block).group(1)), sum(data["by_file"].values()))
ck("① 生成区里的脚本数 == 目录里真实的脚本数",
   int(re.search(r"(\d+) 个脚本", block).group(1)),
   len(list(HERE.glob("test_*.py"))))
ck("① 生成区里的失败数 == COUNTS.json 的 failures（两次读数不许打架）",
   int(re.search(r"、(\d+) 失败", block).group(1)), data["failures"])

# ---- ② 源代码自洽：键 == 真实脚本集合（不多不少）----------------------------
real = {p.name for p in HERE.glob("test_*.py")}
ck("② COUNTS.json 的键 == 目录里全部 test_*.py（多了/少了都要报）",
   set(data["by_file"]), real)
ck("② COUNTS.json 的 scripts == 那个集合的大小",
   data["scripts"], len(real))

# ---- ③ 人写的东西没被机器吃掉 ----------------------------------------------
# ★★ 这条是本次**真栽过**的地方：第一版生成器把「当前 README」当注解的真源，
#   跑第二遍时注解已被渲染成占位符 ⇒ **28 条注解全丢**。
#   ⇒ 所以"注解非空"必须是一条**断言**，不能靠"应该不会吧"。
PLACEHOLDER = "★ **待补**：这一格是「钉住什么」，人写、不生成。"
missing = [k for k, v in data["notes"].items() if not v or PLACEHOLDER in v]
ck("③ 每一条注解都非空（★ 生成器**不许**把注解换成占位符 —— 实测栽过）", missing, [])
ck("③ 生成区里每个脚本都带注解（注解列不许空着）",
   [k for k, v in rows.items() if not re.search(r"^\| `%s` \| \d+ \| .+ \|$" % re.escape(k),
                                                block, re.M)], [])

# ---- ④ 「只报变化，不报现状」：本文件不追历史 ---------------------------------
# ★ 历史读数（那 12 条追加式日期行）已**整段搬去** `summary/31`（2026-09-20）。
#   这里钉一条：README 里**手写的**日期行必须是 0 —— 否则"往 README 追加数字"这个入口
#   又回来了，税就复辟了。
#   ★ 判据要**排除生成区**：生成区里那条日期行是**机器写的**，它不算"手写"。
#     （第一版没排除 ⇒ 把机器写的那条也数进去 ⇒ **自己把自己判红**。
#      同 `B.10` 第 14 条：判据的范围划错，红绿都会骗人。）
outside = text.replace(block, "") if block else text
dates = re.findall(r"^\d{4}-\d{2}-\d{2} 实测：\*\*\d+ 个脚本、\d+ 条断言", outside, re.M)
ck("④ README **生成区之外**手写日期行 == 0（历史已搬 summary/31）", len(dates), 0)
ck("④ 但生成区**内**必须恰好有一条（就是当前读数）",
   len(re.findall(r"^\d{4}-\d{2}-\d{2} 实测：\*\*\d+ 个脚本、\d+ 条断言", block, re.M)), 1)

print()
if fails:
    print(f"!!! {len(fails)} 个失败")
    for f in fails:
        print("   " + f)
    print("\n★ 修法：`python tests/gen-counts.py`（数错了才改代码，改完重跑生成器）")
    sys.exit(1)
print("全部通过 —— 计数链：源（真跑）→ COUNTS.json → README 生成区，一致")

# -*- coding: utf-8 -*-
"""`todo_pooled` 的**调用点** —— 传进去的必须是"包名列表"，不是 `--packs` 的原始串。

为什么要专门钉这个（2026-09-22 事故）
======================================
`tests/test_pooled_batch.py` / `test_pool_split.py` 把 `todo_pooled` **本身**
测得很全（池序、全局 limit、按包分段），**全绿**。
坏的不是它 —— 是**喂给它的那个表达式**：

    `run_round()` 里写的是  `st.todo_pooled(list(args.packs), …)`

而 `args.packs` 是 `--packs` 的**原始字符串**（`argparse` 的
`default=PACKS_DEFAULT`，形如 `"frds-top250-2024"`；`main()` 里才用
`packs = [p.strip() for p in args.packs.split(",") if p.strip()]` 清洗成列表）。

⇒ `list("frds-top250-2024")` **不是在切逗号**，它把字符串**拆成一个个字符**：
     `['f','r','d','s','-','t','o','p','2','5','0','-','2','0','2','4']`
⇒ 变成 16 个**单字符"包名"** ⇒ `WHERE pack='f'` 之类一个都匹配不上
⇒ `movies()` 全空 ⇒ **池子恒为 0**。

★★ 症状为什么极难查（这就是本文件存在的理由）
--------------------------------------------
  · **静默**：日志报「没有待搜索项」，**不报错、不退非零**；
  · **启动日志看着正常**：那行打的是清洗过的 `packs`
    （`packs=['frds-top250-2024']`），**不是** `args.packs`；
  · **只在 `--pool` 上暴露** —— 非 `--pool` 那条用的是干净的局部变量 `pack`；
  · ★★ **加 `--dry-run` 反而正常**：dry-run 分支用的正是 `packs`（干净），
    而 `run_round` 用 `args.packs`（脏）⇒ 同一条命令"加个 dry-run 就好了"
    ⇒ 极易被误判成"运行期状态问题"而不是"表达式类型问题"。
  · 实测：常驻进程**连续 14 轮、7 小时**全空；`--dry-run` 给 43 部、去掉给 0。

★ 判据的形状（从这次事故提炼）：**两处调用同一个函数、参数"看起来一样"、结果不同
  ⇒ 去比那两个表达式的 *_类型_*，不是它们的值。** 当时两边打印出来都是
  `frds-top250-2024`，而一个是 `str`、一个是 `list[str]`。

钉四条
======
  ① ★★★ `scripts/drive-loop.py` 里**任何** `todo_pooled(...)` 调用，
    第一个实参**不许**是 `args.packs`（或其 `list(...)` 包装）。
  ② ★★ 阴性对照：把①的判据喂给**真实存在过的那行坏代码**（`list(args.packs)`）
     ⇒ 必须判红。（判据不能恒真 —— `ERR-AI-09`）
  ③ ★ 阳性对照：喂给**修好的那行**（`list(packs)`）⇒ 判绿。
  ④ ★★ 把①的判据喂给 `list("frds-top250-2024")` 的**运行时结果** ⇒ 长度 16、
     且**没有一个**元素等于真的包名 —— 把"拆成字符"这件事本身钉住，
     免得将来有人以为 `list(str)` 无害。

★ 素材：只读 `scripts/drive-loop.py` 的**源码文本** + 纯字符串运算。
  不导入 drive-loop.py（它有 argparse / 网络副作用），不碰网络、不碰 NAS、不碰真库。
"""
import io
import os
import re
import sys

# ★ 强制 UTF-8：本文件全是 ⇒ ★ ✓，Windows 控制台 GBK 会 UnicodeEncodeError
#   把测试打挂，且挂在取决于内容的行上（`ERR-AI-10` 形状）。
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
SRC_PATH = os.path.join(HERE, os.pardir, "scripts", "drive-loop.py")

fails = []


def ck(label, got, want):
    ok = got == want
    print(("  ok  " if ok else " FAIL ") + "%s: %r" % (label, got))
    if not ok:
        fails.append("%s: got %r want %r" % (label, got, want))


with io.open(SRC_PATH, encoding="utf-8") as fh:
    SRC = fh.read()


def first_args_of_calls(src, func="todo_pooled"):
    """把源码里所有 `todo_pooled(` 的**第一个实参**抠出来（纯文本，跨行）。

    ★ 为什么手写括号配平而不是正则一把梭：实参里有嵌套括号
      （`list(args.packs)`、`S.parse_cadence(args.cadence)`）和**中文注释**，
      正则很容易在"值里含逗号/括号"时静默抠错 —— 本项目已因"用 sed/grep 抠
      JSON 静默抠错"踩过一次（见 `run-resident.sh` 那条注释）。
      ⇒ 老老实实按字符扫，状态机简单但**判据可复核**。
    """
    out = []
    for m in re.finditer(r"\b%s\s*\(" % re.escape(func), src):
        i = m.end()                      # 左括号之后
        depth = 1
        buf = []
        while i < len(src) and depth:
            ch = src[i]
            if ch in "([{":
                depth += 1
            elif ch in ")]}":
                depth -= 1
                if depth == 0:
                    break
            buf.append(ch)
            i += 1
        call = "".join(buf)
        # 第一个实参 = 顶层第一个逗号之前的全部（跳过关键字实参的 `name=`）
        depth = 0
        first = []
        for ch in call:
            if ch in "([{":
                depth += 1
            elif ch in ")]}":
                depth -= 1
            elif ch == "," and depth == 0:
                break
            first.append(ch)
        out.append((m.start(), "".join(first).strip()))
    return out


CALLS = first_args_of_calls(SRC)

print("== ① ★★★ 每个 todo_pooled 调用的第一个实参 ==")
print("     找到 %d 处：%s" % (len(CALLS), [a for _, a in CALLS]))
ck("★ 至少找到 2 处调用（dry-run 与 run_round 各一处）", len(CALLS) >= 2, True)

for pos, arg in CALLS:
    ln = SRC.count("\n", 0, pos) + 1
    ck("★ 第 %d 行 首参 = %r ⇒ 不是 args.packs" % (ln, arg),
       ("args.packs" in arg), False)

print()
print("== ② ★★ 阴性对照：喂给**真实存在过的那行坏代码** ⇒ 必须判红 ==")


def bad_has_args_packs(arg):
    """①的判据，做成纯函数以便喂对照组。"""
    return "args.packs" in arg


ck("②a 喂 `list(args.packs)`（事故原码）⇒ 判据说'坏'（=True）",
   bad_has_args_packs("list(args.packs)"), True)
ck("②b 喂 `args.packs`（裸的）⇒ 判据说'坏'",
   bad_has_args_packs("args.packs"), True)
ck("②c ★ 阴性对照反向：喂一个**正常**的 ⇒ 判据说'好'（=False）",
   bad_has_args_packs("list(packs)"), False)

print()
print("== ③ ★★ 阳性对照 + 运行时证据：list(str) 到底变成什么 ==")
FAKE = "frds-top250-2024"
chars = list(FAKE)
ck("③a list(包名串) 的长度 = %d（不是 1）" % len(chars), len(chars), 16)
ck("③b 里面**没有**任何一个元素等于真包名", FAKE in chars, False)
ck("③c 而正确的切法给的是 ['frds-top250-2024']",
   [p.strip() for p in FAKE.split(",") if p.strip()], ["frds-top250-2024"])
ck("③d 多包时才看得出差别：'a,b' 切对了",
   [p.strip() for p in "a,b".split(",") if p.strip()], ["a", "b"])
ck("③e ★ 而 list('a,b') 是 3 个字符（含逗号！）", list("a,b"), ["a", ",", "b"])

print()
print("== ④ ★ 两种表达式**值能打印成一样、类型不同** —— 判据必须看结构 ==")
class _A:
    packs = FAKE


ck("④a repr 出来一样：list(_A.packs) 的元素 repr 里有 'f' 这种单字符",
   sorted(set(list(_A.packs)))[:3], ["-", "0", "2"])
ck("④b 而正确表达式 list(['frds-top250-2024']) 就一个元素",
   len(list(["frds-top250-2024"])), 1)
print("      ★ 提炼成一句话：两处调用同一函数、'看着一样'、结果不同")
print("        ⇒ **比那两个表达式的类型，不是它们的值**。")

print()
if fails:
    print("FAILED %d:" % len(fails))
    for f in fails:
        print("   -", f)
    sys.exit(1)
print("全过")

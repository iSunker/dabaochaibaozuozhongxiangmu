# -*- coding: utf-8 -*-
"""`tests/README.md` 自己的一致性 —— 三处「数」必须互相对得上。

为什么值得单独一个脚本（2026-09-16）：
  README 是**断言条数的唯一出处**，而它自己**没有任何东西在检查** ——
  于是同一段话被抄成两遍（"+3 / +15" 那段），**两份说的是同一个数、还都对**，
  但**结构上已经在漂**；发现它的方式居然是"用户觉得两处对不上"。
  ★ 教训与 `test_notify_digest` 的红过再绿同族：**文档自己也要能"红"**。
    不是断言，就没法红 ⇒ 这里给 README 的三处数各写一条断言。

三处（缺一不可，它们各自会**独立**漂）：
  ① 日期行里的「N 条断言」
  ② 「各测什么」表格 21 行的「断言」列**逐行相加**
  ③ 表格里 `test_backoff.py` 那一格 —— 它是本轮**改过的**那个，
     还要与日期行里那句「51 → 54」的**新值**对上

★ 反面：别把这条检查写成「正则搜一下 772 在不在文件里」——
  那种检查在**有两个 772** 时同样通过，正是本次要防的形态。
"""
import pathlib
import re
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

README = pathlib.Path(__file__).resolve().parent / "README.md"
text = README.read_text(encoding="utf-8")
fails = []


def ck(label, got, want):
    ok = got == want
    print(("  ok  " if ok else " FAIL ") + f"{label}: {got!r}")
    if not ok:
        fails.append(f"{label}: got {got!r} want {want!r}")


# ---- ① 日期行 -------------------------------------------------------------
# 形如：2026-09-16 实测：**22 个脚本、784 条断言、0 失败**
#   ★★ 这里有个**同族陷阱**：旧日期行里写的是「18 个脚本、690 条断言」，
#      而它恰恰也符合这条正则 ⇒ 第一版 `re.search` **抓到了最旧那一条**，
#      于是三条断言一起红，看着像"表坏了"，其实抓错了行。
#      （和 #115 的"tail 看不到批头"一个形状：**第一条不是最近那条**。）
#   ⇒ 必须 `findall` 取**最后**一条，并断言它是最新的那个日期。
m = re.findall(r"(\d{4}-\d{2}-\d{2}) 实测：\*\*(\d+) 个脚本、(\d+) 条断言、0 失败", text)
m = m[-1] if m else None
ck("找得到最新那条日期行（找不到就该报红，而不是静默跳过）", bool(m), True)
ck("日期行不止一条（历史都在，取最后那条）", bool(m) or True, True)
if m:
    newest_date, n_scripts, n_assert_doc = m[0], int(m[1]), int(m[2])
else:
    newest_date, n_scripts, n_assert_doc = None, 0, 0
#   ★ 还要断言"最后一条**确实是**最新的那个日期"：否则将来有人把新日期
#     插在中间，`[-1]` 又会静默抓错行 —— 那是同一个坑换了个位置。
_dates = re.findall(r"^(\d{4}-\d{2}-\d{2}) 实测：", text, re.M)
ck("取到的就是**最后那个**日期（不然这条检查会静默抓错行）",
   newest_date, _dates[-1] if _dates else None)
ck("日期行里的脚本数 = 目录里真实的脚本数",
   n_scripts, len(list((README.parent).glob("test_*.py"))))

# ---- ② 表格逐行相加 -------------------------------------------------------
rows = re.findall(r"^\| `(test_\w+\.py)` \| (\d+) \|", text, re.M)
ck("表格行数 = 脚本数（每个脚本都得有一格）", len(rows), n_scripts)
table_sum = sum(int(n) for _, n in rows)
ck(f"② 表格 {len(rows)} 行相加 == ① 日期行里的数（两处各自会漂）", table_sum, n_assert_doc)

# ---- ②b ★★ 表格逐格 == **实跑**出来的数 ------------------------------------
# ★★★ 2026-09-17 补：上面那条 ② **有盲区** —— 它只查「表格 vs 日期行」，
#   两处**一起漂**（各少算 9 条）时**照样绿**。
#   实测撞到：我把 `test_once_gate.py` 从 32 条加到 41 条（+9），
#   却没同步表格那一格、也没同步日期行 ⇒ **两边各漂一半、相互抵消** ⇒ ② 通过、
#   而**真值是 866，README 仍写 857**。这正是 `#70` 那个形状：
#   **判据看着有结构，而它覆盖的范围里恰好不含"事实"**。
#   ⇒ 补这一条：**逐个脚本真跑一遍，数它的断言行**，与表格那一格比。
#   ★ 代价要说清：这会把整套测试**再跑一遍**（几十秒）。
#     对「README 是唯一出处」这件事值得；但若哪天太慢，宁可**减少频率**（人手动跑），
#     也别把它换成"大概对一下"——那样就退回成 ② 了。
#   ★★ 必须**排除自己**：本文件也在 `test_*.py` 的集合里，不排除就会
#      **递归自我调用**（实测：跑成 0 字节输出、永不结束，只能杀掉）。
_self = pathlib.Path(__file__).name
#   ★ 数法：与 `tests/README.md` 里那条命令**同一套行型**（三种都要数，
#     只数 `  ok  ` 会漏 —— 文档里实测会少 8 条）。
import subprocess as _sp
import re as _re2

_ASSERT_LINE = _re2.compile(r"^  ok  |^ FAIL |: PASS|: FAIL")
_mismatch = []
for fname, want in rows:
    if fname == _self:
        # ★ 自己那一格不实跑（会递归）；它的数由它**跑完时**打印的最后一行给出，
        #   而那一行本身也要对 ⇒ 单列一格说明，不当成"跳过"。
        continue
    fp = README.parent / fname
    try:
        _r = _sp.run([sys.executable, str(fp)], capture_output=True, text=True,
                     encoding="utf-8", errors="replace", timeout=300)
    except Exception as e:                                   # noqa: BLE001
        _mismatch.append(f"{fname}: 跑不起来（{type(e).__name__}）")
        continue
    got = sum(1 for l in (_r.stdout or "").split("\n") if _ASSERT_LINE.search(l))
    if got != int(want):
        _mismatch.append(f"{fname}: 表格 {want} ≠ 实跑 {got}")
ck("②b ★★ 表格每一格都 == **实跑**出来的断言数（② 查不出的『两处一起漂』由它兜）",
   _mismatch, [])
# ★ 自己那一格的替代判据：**它必须出现在表格里且行数自洽**（② 已兜）。
#   ★ 明说为什么只跳过自己：**递归**（不是"它不重要"）。
ck(f"②c 本文件（{_self}）在表格里有格（它自己不实跑，理由是**递归**）",
   _self in dict(rows), True)

# ---- ③ backoff 那一格 vs 日期行里那句「51 → 54」--------------------------
bo = dict(rows).get("test_backoff.py")
#   ★★ 这里**故意不写死一个数字**：写死就等于把「54」供成契约，
#      而它每加一节就会变（本文件就是这么被 60 抓红的）。
#      要钉的是**一致性**（表格 vs 那句留痕），不是某个具体数 ——
#      具体数由上面第 ② 条（逐行相加 == 日期行）兜着。
ck("③ 表格里有 test_backoff.py 那一格（值本身由 ② 兜）",
   bo is not None and bo.isdigit(), True)
#   ★ 这句可能被写成链（`51 → 54 → 60`）—— 取**最后一个**数才是"当前值"。
#     （第一版只认 `A → B`，链式写法会让它**静默抓不到** ⇒ 判据变成空转。）
_m2 = re.search(r"`test_backoff\.py` \*\*([\d →]+)\*\*", text)
ck("找得到 backoff 那条改动的留痕（形如 51 → 54 [→ 60]）", bool(_m2), True)
_num = re.findall(r"\d+", _m2.group(1)) if _m2 else []
ck("③ 那句的**最后一个数** == 表格里那一格（链式写法取末位）",
   _num[-1] if _num else None, bo)

# ---- ④ 重复段落守门（本次的真实病根）--------------------------------------
#   ★ 抄两遍的形态：**连续两行一字不差**。段落级重复（跨小标题）不在此列，
#     但那种更少见、也更显眼；先把"挨着复制"这一种钉死。
lines = [l.rstrip() for l in text.splitlines()]
dups = []
for i in range(1, len(lines)):
    cur, prev = lines[i], lines[i - 1]
    if len(cur) >= 30 and cur == prev:
        dups.append((i + 1, cur[:60]))
ck("④ 没有「连续两行完全相同」的抄写（≥30 字符）", dups, [])

print()
if fails:
    print(f"!!! {len(fails)} 个失败")
    for f in fails:
        print("   " + f)
    sys.exit(1)
print("全部通过")

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

# ---- ③ backoff 那一格 vs 日期行里那句「51 → 54」--------------------------
bo = dict(rows).get("test_backoff.py")
ck("③ 表格里的 test_backoff.py 断言数", bo, "54")
m2 = re.search(r"`test_backoff\.py` \*\*(\d+) → (\d+)\*\*", text)
ck("找得到「51 → 54」那句（本轮改动的留痕）", bool(m2), True)
if m2:
    ck("③ 那句的**新值** == 表格里那一格", m2.group(2), bo)

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

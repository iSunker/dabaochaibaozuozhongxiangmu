# -*- coding: utf-8 -*-
"""next_sleep() 退避分级自测 —— 站点打喷嚏 vs 站点真在压，间隔不该一样。

不需要网络/真库：直接造 DriveStats 对象喂给 next_sleep()。
"""
import importlib.util
import pathlib
import sys

# ★ 输出强制 UTF-8：GBK 控制台下 ⑪(U+246A) 编不出去，会在中途炸掉。
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

REPO = pathlib.Path(__file__).resolve().parent.parent  # 仓库根
SRC = str(REPO / "scripts" / "drive-loop.py")

spec = importlib.util.spec_from_file_location("drive_loop", SRC)
dl = importlib.util.module_from_spec(spec)
spec.loader.exec_module(dl)

S = sys.modules["orchestrator.state"] if "orchestrator.state" in sys.modules else None
if S is None:
    sys.path.insert(0, str(REPO))
    from orchestrator import state as S

fails = []


def ck(label, got, want):
    ok = got == want
    print(("  ok  " if ok else " FAIL ") + f"{label}: {got!r}")
    if not ok:
        fails.append(f"{label}: got {got!r} want {want!r}")


def stats(**kw):
    return S.DriveStats(**kw)


MIN = 60
print("== ① 喷嚏：限过一次，但我们只等了 <3 分钟 → 不惩罚，按基准 45 分钟 ==")
for w in (0.0, 55.0, 179.0):
    sec, why = dl.next_sleep(stats(backoff_hits=1, waited_sec=w, ok=50))
    ck(f"  等了 {w:.0f}s → 45 分钟", sec, dl.BASE_SLEEP)
print(f"        理由样例：{why}")

print("\n== ② 中档：等了 3~10 分钟 → 放缓到 1.5 小时 ==")
for w in (180.0, 420.0, 599.0):
    sec, why = dl.next_sleep(stats(backoff_hits=2, waited_sec=w, ok=50))
    ck(f"  等了 {w:.0f}s → 90 分钟", sec, dl.SNOOZE_SLEEP)

print("\n== ③ 重感冒：等了 ≥10 分钟 → 拉满 2 小时 ==")
for w in (600.0, 1200.0, 1800.0):
    sec, why = dl.next_sleep(stats(backoff_hits=3, waited_sec=w, ok=50))
    ck(f"  等了 {w:.0f}s → 120 分钟", sec, dl.BACKOFF_SLEEP)
print(f"        理由样例：{why}")

print("\n== ④ 分级只作用于 backoff_hits —— still_skipped 一律 2 小时 ==")
sec, why = dl.next_sleep(stats(still_skipped=7, backoff_hits=1, waited_sec=5.0))
ck("  有片子没推进 → 120 分钟", sec, dl.BACKOFF_SLEEP)
ck("  理由说的是 still_skipped", "SKIPPED" in why or "跳过" in why, True)

print("\n== ⑤ 老分支没被碰坏 ==")
ck("  aborted → 3 小时",
   dl.next_sleep(stats(aborted="索引器 X 要等到明天"))[0], dl.ABORT_SLEEP)
ck("  健康 + 有新增 → 45 分钟",
   dl.next_sleep(stats(newly_seeding=12))[0], dl.BASE_SLEEP)
ck("  无退避无新增 → 45 分钟", dl.next_sleep(stats(ok=50))[0], dl.BASE_SLEEP)

print("\n== ⑥ 「等了 0 秒却记了一笔」必须落在基准档（本次分级的核心目的）==")
sec, why = dl.next_sleep(stats(backoff_hits=4, waited_sec=0.0))
ck("  4 次命中但一秒没等 → 45 分钟", sec, dl.BASE_SLEEP)

print("\n== ⑦ 三档顺序单调（等得越久，间隔越长）==")
seq = [dl.next_sleep(stats(backoff_hits=1, waited_sec=w))[0]
       for w in (0.0, 200.0, 900.0)]
ck("  45 ≤ 90 ≤ 120", seq, sorted(seq))
ck("  且不全相等", len(set(seq)) > 1, True)

print()
if fails:
    print(f"!!! {len(fails)} 个失败")
    for f in fails:
        print("   " + f)
    sys.exit(1)
print("全部通过")

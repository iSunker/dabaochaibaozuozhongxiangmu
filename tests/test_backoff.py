# -*- coding: utf-8 -*-
"""退避检测的离线自测 —— 复刻 2026-09-12 那次「55 秒 snooze 被整段错过」的现场。

不起网络、不碰真库：cross-seed.db 用临时库伪造，post_webhook 与时钟全部注入。
"""
import os, pathlib, sqlite3, sys, tempfile, datetime
# 仓库根 = 本文件的上上级目录（tests/ 的上一层）。
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from orchestrator import state as S

# ★ 输出强制 UTF-8：GBK 控制台下 ⑪(U+246A) 编不出去，会在中途炸掉。
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

Q = S.IndexerBackoff
fails = []


def ck(label, got, want):
    ok = got == want
    print(("  ok  " if ok else " FAIL ") + f"{label}: {got!r}")
    if not ok:
        fails.append(f"{label}: got {got!r} want {want!r}")


def make_db(rows):
    """rows: [(id, name, status, retry_after_ms|None, active)]"""
    p = os.path.join(tempfile.mkdtemp(), "cross-seed.db")
    con = sqlite3.connect(p)
    con.execute("CREATE TABLE indexer (id INTEGER PRIMARY KEY, name varchar(255), "
                "url varchar(255), status varchar(255), retry_after INTEGER, "
                "active boolean)")
    for i, n, st, ra, act in rows:
        con.execute("INSERT INTO indexer VALUES(?,?,?,?,?,?)",
                    (i, n, f"http://prowlarr:9696/{i}/api", st, ra, act))
    con.commit()
    con.close()
    return p


def ms(dt):
    return int(dt.timestamp() * 1000)


class Clock:
    """假时钟：monotonic 和 now 一起走，sleep 只是把两者推快。"""

    def __init__(self, start=None):
        self.t = (start or datetime.datetime.now()).replace(microsecond=0)
        self.mono = 0.0
        self.slept = []

    # -- 注入给 DriveSession --
    def monotonic(self):
        return self.mono

    def now(self):
        return self.t

    def sleep(self, s):
        self.slept.append(round(s, 1))
        self.mono += s
        self.t += datetime.timedelta(seconds=s)

    def advance(self, s):
        self.mono += s
        self.t += datetime.timedelta(seconds=s)


def run_session(db, *, n=12, check_secs=60.0, max_wait=1800.0, interval=30.0,
                on_item=None, **kw):
    """跑一轮假批次，返回 (stats, session, clock)。"""
    clock = Clock()
    calls = [0]
    orig = S.post_webhook

    def fake_post(pth, **kwargs):
        calls[0] += 1
        if on_item:
            on_item(calls[0], clock)
        # 时间只由 run() 的 interval sleep（= 注入的 clock.sleep）推进，
        # 这里**不能**再 advance 一次，否则一个条目走 60 秒，检查节奏全乱。
        return 204

    S.post_webhook = fake_post
    try:
        sess = S.DriveSession(url="http://x", api_key="k", crossseed_db=db,
                              interval=interval, check_every=10, check_secs=check_secs,
                              max_wait=max_wait, sleep=clock.sleep, now=clock.now,
                              monotonic=clock.monotonic, **kw)
        stats = sess.run([f"/p/{i}" for i in range(n)])
        return stats, sess, clock
    finally:
        S.post_webhook = orig


def set_row(db, iid, status, retry_after, active=1):
    con = sqlite3.connect(db)
    con.execute("UPDATE indexer SET status=?, retry_after=?, active=? WHERE id=?",
                (status, retry_after, active, iid))
    con.commit()
    con.close()


print("== ① 现场复刻：55 秒的短退避发生在批次中途 ==")
db = make_db([(2, "HDFans", "OK", None, 1)])


def hit_429(call_no, clock):
    if call_no == 2:                     # 第 2 条发出后，cross-seed 被 429
        set_row(db, 2, "RATE_LIMITED", ms(clock.t + datetime.timedelta(seconds=55)))


st, sess, clock = run_session(db, n=12, on_item=hit_429)
ck("检出 1 次退避（修复前恒为 0）", st.backoff_hits, 1)
ck("没误判成中止", st.aborted, None)
ck("照发完了 12 条", st.ok, 12)
print(f"       等待序列: {clock.slept}  waited={st.waited_sec}")

print("\n== ② 退避窗口在两次检查之间**已经过去** —— 也要记这一笔 ==")
db2 = make_db([(2, "HDFans", "OK", None, 1)])


def hit_429_instant(call_no, clock):
    if call_no == 2:
        set_row(db2, 2, "RATE_LIMITED", ms(clock.t + datetime.timedelta(milliseconds=1)))


st2, _, _ = run_session(db2, n=12, on_item=hit_429_instant)
ck("已经解禁也记账（new retry_after ≠ 上次）", st2.backoff_hits, 1)
ck("已解禁就不必等", st2.waited_sec, 0.0)

print("\n== ③ 库里躺着一小时前的残值 —— 批次开头**不许**白记一笔 ==")
db3 = make_db([(2, "HDFans", "RATE_LIMITED", ms(datetime.datetime.now()
                                                - datetime.timedelta(hours=1)), 1)])
st3, _, _ = run_session(db3, n=12)
ck("残值不算命中", st3.backoff_hits, 0)
ck("残值不挡路", st3.waited_sec, 0.0)

print("\n== ④ 禁用的索引器（active=0）的退避不该挡路 ==")
db4 = make_db([(1, "prowlarr#1", "RATE_LIMITED",
                ms(datetime.datetime.now() + datetime.timedelta(hours=1)), 0)])
st4, sess4, _ = run_session(db4, n=12)
ck("不挡路", st4.waited_sec, 0.0)
ck("不记账", st4.backoff_hits, 0)
ck("不中止", st4.aborted, None)

print("\n== ⑤ 真·长退避正在挡路：记住 + 等到解禁 ==")
db5 = make_db([(2, "HDFans", "RATE_LIMITED",
                ms(datetime.datetime.now() + datetime.timedelta(seconds=120)), 1)])
st5, _, c5 = run_session(db5, n=12)
ck("记 1 笔", st5.backoff_hits, 1)
# 秒以下的小数来自测试造数据时 now() 的微秒（假时钟从整秒起步），给个区间即可
ck("等到解禁（≈122s）", 119 <= st5.waited_sec <= 124, True)
ck("13 条目全发完", st5.ok, 12)

print("\n== ⑥ 挡太久（> max_wait）→ 中止 ==")
db6 = make_db([(2, "HDFans", "RATE_LIMITED",
                ms(datetime.datetime.now() + datetime.timedelta(hours=3)), 1)])
st6, _, _ = run_session(db6, n=12, max_wait=1800.0)
ck("中止", bool(st6.aborted), True)
ck("一条都没发", st6.sent, 0)
# ★★ 中止要**分类**（#45）：这一种是**良性**的 —— 站点在退避、等到超过上限就先收工，
#    剩下的条目下轮重新排上。它和「webhook 401」是两件事，下游据此分开计数。
ck("★ 分类是 indexer-backoff（**良性**，不是真故障）",
   st6.aborted_kind, "indexer-backoff")

print("\n== ⑦ check_secs 关掉（=0）时退回老行为：只按条数检查 ==")
db7 = make_db([(2, "HDFans", "OK", None, 1)])


def hit_429_7(call_no, clock):
    if call_no == 2:
        set_row(db7, 2, "RATE_LIMITED", ms(clock.t + datetime.timedelta(seconds=55)))


st7, _, _ = run_session(db7, n=6, check_secs=0.0, on_item=hit_429_7)
ck("条数没到就不看（6 条 < 10）", st7.backoff_hits, 0)
ck("也就没有等待", st7.waited_sec, 0.0)

print("\n== ⑧ ★★ 两个计数分开：站点退避超时**不是**「批失败」（#45） ==")
# ★ 这一节钉的是**2026-09-13 生产里看到的那一格**：同一批的 TSV 既写
#   `ok=22 failed=0`，又写「连续 3 批失败（索引器 HDtime 要等到 …）」——
#   一个名字盖了两种模型（同 `NanyangPT` vs `NanyangPT (南洋)` 的形状）。
#   下面每一格都对着那条真实记录。
import importlib.util as _ilu                       # noqa: E402

_spec = _ilu.spec_from_file_location(
    "drive_loop_backoff", str(pathlib.Path(__file__).resolve().parent.parent
                              / "scripts" / "drive-loop.py"))
dl = _ilu.module_from_spec(_spec)
_spec.loader.exec_module(dl)

_ev = []
dl.emit = lambda kind, title, body="", *, key=None, metrics=None: (
    _ev.append((kind, title, body, key, metrics)) or True)


def _backoff(reason="索引器 HDtime 要等到 2026-09-13 03:00:11（169 分钟 > 上限 30 分钟）"):
    return S.DriveStats(aborted=reason, aborted_kind="indexer-backoff", ok=22)


def _auth():
    return S.DriveStats(aborted="webhook 返回 401（鉴权/路径问题），已停",
                        aborted_kind="webhook-auth")


_ev.clear()
ck("良性收工 1 批 → (真失败, 收工) = (0, 1)",
   dl.update_abort_streak((0, 0), _backoff()), (0, 1))
ck("★ 只涨「收工」，**一点失败都没涨**", dl.update_abort_streak((0, 0), _backoff())[0], 0)

n = (0, 0)
for _ in range(3):
    n = dl.update_abort_streak(n, _backoff())
ck("连 3 批良性 → 计数到 3", n, (0, 3))
ck("★ 发的 alert key 是 consec-backoff（**不是** consec-abort）",
   [e[3] for e in _ev], ["consec-backoff"])
ck("★ 标题**不**出现「批失败」", "批失败" in _ev[0][1], False)
ck("★ 正文点明「不是失败」+ 说清下轮会重排",
   ("不是" in _ev[0][2] and "重新排上" in _ev[0][2]), True)
ck("★ 正文**不**再把人指去 force-recreate（那是上一版对退避场景的误导）",
   "force-recreate" in _ev[0][2], False)

# 反向：真故障走另一条路，key 与文案都不一样
_ev.clear()
ck("真故障 → (1, 0)：良性那格空着，不动",
   dl.update_abort_streak((0, 0), _auth()), (1, 0))
_ev.clear()
n = (0, 0)
for _ in range(3):
    n = dl.update_abort_streak(n, _auth())
ck("连 3 批真故障 → (3, 0)", n, (3, 0))
ck("★ 真故障的 key 是 consec-abort", [e[3] for e in _ev], ["consec-abort"])
ck("★ 真故障才说「批失败」", "批失败" in _ev[0][1], True)

# ★★ 互不干扰：中间夹一批良性，**不许**把真失败冲回 0 ——
#    这一格是本节存在的一半理由：写成"互相清零"的话，真实故障会被
#    交替出现的退避批次反复掩盖，**永远到不了 3**，告警等于没有。
_ev.clear()
_after = dl.update_abort_streak(dl.update_abort_streak((2, 0), _backoff()), _auth())
ck("★★ 真失败 ×2 → 夹 1 批良性 → 真失败**不被冲掉**", _after, (3, 1))
ck("★★ 而且这一批就报了（3 批真失败，中间那批良性没掩盖它）",
   [e[3] for e in _ev], ["consec-abort"])
# 反向：良性也不被真失败冲掉，且**总数**把两边都算进去（谁也别想被掩盖）
_ev.clear()
_s = dl.update_abort_streak((0, 0), _auth())        # 1 批真失败
for _ in range(3):
    _s = dl.update_abort_streak(_s, _backoff())     # 再 3 批良性
ck("真失败 1 + 良性 3 → (1, 3)", _s, (1, 3))
ck("★ 良性这边到 3 就报（那批真失败没把它冲回 0）",
   [e[3] for e in _ev], ["consec-backoff"])
ck("★ 混着出现时，标题把「共 4 批没跑成」写出来（否则 3 会被念成「连续 3 批」）",
   "共 4 批没跑成" in _ev[0][1], True)
# ★ 反向控制：**整批异常**也按真失败算（它可一点都"良性"不起来）
_ev.clear()
ck("整批异常 → 真失败",
   dl.update_abort_streak((0, 0), None, failed=True), (1, 0))
# ★ 兜底方向：`aborted` 非空却认不出种类 → **按真失败算**（宁可吵，不可静默）
ck("★ 认不出种类 → 按真失败算（宁可吵不可静默）",
   dl.update_abort_streak((0, 0), S.DriveStats(aborted="说不清的原因")), (1, 0))
# ★ 正常跑完（含"本包无待搜"）→ **两个都清零**（这是唯一的清零路径）
ck("★★ 正常跑完 → 两个计数都清零",
   dl.update_abort_streak((5, 5), S.DriveStats(ok=50)), (0, 0))
ck("没跑（stats=None 且没 failed）→ 也清零",
   dl.update_abort_streak((5, 5), None), (0, 0))
# ★ 常见情况下不补那句括号（补了是噪音）—— 上一条刚确认 5+5 被清零了，
#   这里单独跑一条干净的 3 连良性，确认标题就是简单的「连续 3 批提前收工」。
_ev.clear()
n = (0, 0)
for _ in range(3):
    n = dl.update_abort_streak(n, _backoff())
ck("★ 单一成因时不啰嗦（标题里没有「共 … 批」）", "共 " in _ev[0][1], False)

print()
if fails:
    print(f"!!! {len(fails)} 个失败")
    for f in fails:
        print("   " + f)
    sys.exit(1)
print("全部通过")

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

print("\n== ⑦ check_secs 关掉（=0）时退回老行为：只按条数检查 ==")
db7 = make_db([(2, "HDFans", "OK", None, 1)])


def hit_429_7(call_no, clock):
    if call_no == 2:
        set_row(db7, 2, "RATE_LIMITED", ms(clock.t + datetime.timedelta(seconds=55)))


st7, _, _ = run_session(db7, n=6, check_secs=0.0, on_item=hit_429_7)
ck("条数没到就不看（6 条 < 10）", st7.backoff_hits, 0)
ck("也就没有等待", st7.waited_sec, 0.0)

print()
if fails:
    print(f"!!! {len(fails)} 个失败")
    for f in fails:
        print("   " + f)
    sys.exit(1)
print("全部通过")

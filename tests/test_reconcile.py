# -*- coding: utf-8 -*-
"""观测对账的三条判据（a−b / b−c 两口径 / 全场无人认领）—— 离线合成，不碰农场。

为什么要把这三条钉住
====================
它们全是"**报个数出来**"的判据，而"报 0"在这类判据里是最危险的输出：
既可能是"没事"，也可能是"判据根本没走到"。历史上这个项目在这上面栽过三次
（§16.6.5 的字面量太松、§18.17 的静默通道、NanyangPT 的名字盖了两个模型）。
所以本文件**不测"数为 0"**，只测"换个输入，数跟着变、且变的方向可预期"。

★ 三条各自的对账基准（都取自判据之外的**真实记录**，不是照着实现抄的）：
  ① `count_found_lines`：照 `scripts/audit-found-lines.py` 手工跑出来的口径 ——
     L1 那一个字面量会把 `Found 0 torrents for {` 与 `Found N torrent file(s)
     to inject` 一起吃进来（历史实测 2200 vs 靶心 1011），所以**必须**是合取。
  ② `resolve_found_lines`：三包**共用一个 farm_root**（`fix-statedb-farm-root.py`：
     「有 3 行 farm_root 指向旧路径」）→ 生产口径下别的包的 searchee 必然落到
     other_pack。2026-09-12 实测 865 / 146 / 1011，**不是 0**。
  ③ `unclaimed_searchees`：2026-09-12 实测 1888 条里**恰好 1 条**无人认领
     （`0观影清单chrlee整理`，农场里只含一个 xlsx）。合成用例复刻这个形状。

素材全部合成：SQLite 在 `tempfile.mkdtemp()` 里现造，没有网络、没有 NAS、没有真库。
"""
import os
import pathlib
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from orchestrator.state import (            # noqa: E402
    CrossSeedSnapshot, L1_LABEL, StateStore, count_found_lines,
    resolve_found_lines, unclaimed_searchees,
)

# ★ 输出强制 UTF-8：GBK 控制台下会在中途炸掉，
#   而**已经过的断点看着全是 ok** —— 极易误判成代码坏了。
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

fails = []


def ck(label, got, want):
    ok = got == want
    print(("  ok  " if ok else " FAIL ") + f"{label}: {got!r}")
    if not ok:
        fails.append(f"{label}: got {got!r} want {want!r}")


# --------------------------------------------------------------------------- #
# ① a − b
# --------------------------------------------------------------------------- #
# 四行里三行是靶心形状，一行是**被 L1 吃到但不是靶心**的其它消息。
# 这正是那个 2200 的坑：只看 L1 会数出 4，合取才数得出 3。
#
# ★ 行的形状**照生产日志抄**（2026-09-12 从 info.current.log 取的原样）：
#     [webhook] Found <searchee名> [hash...] on <站名> by <判定> from dataDir (<路径>) - <尾巴>
#   组3 = 站名、组4 = **判定**（MATCH / MATCH_PARTIAL / MATCH_SIZE_ONLY），
#   组5 = searchee 路径。★ 第一版合成时把组4 写成了 `webhook`/`inject` ——
#   那是**合成的形状**，生产里从不出现；拿它当判据就是"合成数据自说自话"。
LOG4 = "\n".join([
    '2026-09-12 01:00:00.000 info: [webhook] Found 0 torrents for {"a":1}',
    '2026-09-12 01:00:01.000 info: [webhook] Found The.Movie.2020 [abcd1234...]'
    ' on HDFans by MATCH from dataDir (/v/farm/The.Movie.2020) - MATCH',
    '2026-09-12 01:00:02.000 info: [inject] Found 南洋寻子 [deadbeef...]'
    ' on NanyangPT (南洋) by MATCH_PARTIAL from dataDir (/v/farm/Nanyang) - MATCH_PARTIAL',
    '2026-09-12 01:00:03.000 info: [webhook] Found Other.2019 [0badf00d...]'
    ' on HDFans by MATCH_SIZE_ONLY from dataDir (/v/farm/Other.2019) - MATCH_SIZE_ONLY',
])

print("== ① a − b：合取才是靶心，L1 不是 ==")
r = count_found_lines(LOG4)
ck("总行数", r.total_lines, 4)
ck("L1 单字面量（那个 2200 的坑）", r.lit_counts.get(L1_LABEL), 4)
ck("a  合取形状", r.a, 3)
ck("b  _RE_FOUND", r.b, 3)
ck("a − b", r.delta, 0)
ck("其它消息被分出去（不进 a）", sum(r.other_found.values()), 1)
ck("控制通过", r.controls_ok, True)
ck("组3 带括号的站名（09-12 修掉的那类）", r.group3_odd, 1)
ck("组4 = 判定，三种都认得",
   sorted(r.group4), ["MATCH", "MATCH_PARTIAL", "MATCH_SIZE_ONLY"])
ck("没有漏行", r.unparsed, [])

print("== ① 反向：靶心形状但 _RE_FOUND 吃不下 → a − b = 1 ==")
# ★ 这一格同时**量出了基线的松紧**：六个字面量**没有**钉住 `[webhook]|[inject]`
#   那个标签，而 `_RE_FOUND` 钉了。所以基线是正则的**超集**，恰好松这一个词。
#   今天生产上 a == b（1011），说明没有别的标签的 Found 行 —— 但这是**实测**，
#   不是**结构保证**。有了这一格，那个"恰好"就有人看着了。
LOG_MISS = LOG4 + "\n" + (
    '2026-09-12 01:00:04.000 verbose: [search] Found Miss.2021 [cafebabe...]'
    ' on HDFans by MATCH from dataDir (/v/farm/Miss.2021) - MATCH')
rm = count_found_lines(LOG_MISS)
ck("a 吃到 4 条", rm.a, 4)
ck("b 只吃下 3 条", rm.b, 3)
ck("a − b 非零", rm.delta, 1)
ck("漏的那条被留证", len(rm.unparsed), 1)

print("== ① 空转 vs 判据坏掉：两个都要能分辨 ==")
re_ = count_found_lines("")
ck("读 0 行 → 控制不过", re_.controls_ok, False)
ck("读 0 行 → a、b 都是 0", (re_.a, re_.b), (0, 0))
# 只有别的消息、一条靶心都没有：控制**通过**（读到行、L1 数到了），b = 0。
# ★ 这就是"空转"：判据走到了，只是真没有 Found 行。它该报的是告警，
#   不是"控制没过" —— 混在一起就分不清「判据坏了」和「真的没发生」。
rz = count_found_lines('2026-09-12 01:00:00.000 info: [webhook] Found 0 torrents for {"a":1}')
ck("只有别的消息 → 控制通过", rz.controls_ok, True)
ck("只有别的消息 → b = 0（空转，不是控制失败）", rz.b, 0)

# --------------------------------------------------------------------------- #
# 合成库：两个包**共用一个农场根**（生产就是这个形状）
# --------------------------------------------------------------------------- #
FARM = "/vol1/farm"
A_ROOT = "/vol1/tv"
B_ROOT = "/vol1/movies"

db = os.path.join(tempfile.mkdtemp(), "t.db")
st = StateStore(db)
st.upsert_pack("alpha", A_ROOT, roots=[A_ROOT], farm_root=FARM)
st.register_dirs("alpha", [("Show.S01", A_ROOT + "/Show.S01")])
st.upsert_pack("beta", B_ROOT, roots=[B_ROOT], farm_root=FARM)
st.register_dirs("beta", [("Movie.A", B_ROOT + "/Movie.A")])

# 三条 searchee：两条归 A/B（**农场路径**，v3 之后 cross-seed 报的就是这个），
# 一条在农场里但哪个包都不认 —— 复刻真实的那个 xlsx。
SNAP = CrossSeedSnapshot(searchee_paths={
    "Show.S01":          FARM + "/Show.S01",
    "Movie.A":           FARM + "/Movie.A",
    "0观影清单chrlee整理": FARM + "/0观影清单chrlee整理",
})

# --------------------------------------------------------------------------- #
# ② b − c：**两种口径的数不一样，而且各自都对**
# --------------------------------------------------------------------------- #
print("== ② 两口径：同一批行，by 谁试，other_pack 完全不是一个数 ==")
LOG2 = "\n".join([
    '2026-09-12 01:00:00.000 info: [webhook] Found Show.S01 [abcd1234...]'
    ' on HDFans by MATCH from dataDir (%s/Show.S01) - MATCH' % FARM,
])
rv = resolve_found_lines(LOG2, st)
ck("b", rv.b, 1)
ck("c 全量口径归到单片", rv.c, 1)
ck("全量口径 b − c", rv.delta, 0)
# ★ 全量口径：所有包一起试 → 这一行归给 alpha，other_pack = 0。
ck("〔全量口径〕归到 alpha", rv.belong_all, {"in_pack": 1})
# ★★ 生产口径：sync_pack 一次只给一个包 —— 对 beta 来说这条**必然**是 other_pack。
#    实测在生产上就是 865 / 146 / 1011，不是 0。
ck("〔生产口径〕alpha 看它是 in_pack", rv.belong_prod["alpha"], {"in_pack": 1})
ck("〔生产口径〕beta  看它是 other_pack", rv.belong_prod["beta"], {"other_pack": 1})
ck("农场行计数（这一行确实在农场根下）", (rv.farm_lines, rv.orig_lines), (1, 0))
ck("组5 路径留证（给无人认领复用）", rv.paths, [FARM + "/Show.S01"])

# --------------------------------------------------------------------------- #
# ③ 全场无人认领
# --------------------------------------------------------------------------- #
print("== ③ 无人认领：三包合起来都认不出的那些 ==")
un = unclaimed_searchees(st, SNAP)
ck("恰好 1 条", len(un), 1)
ck("就是那条（★ 与实测同名同形状）", un[0][1], FARM + "/0观影清单chrlee整理")
# ★ 正向控制：A/B 两条**不能**出现在结果里 —— 否则"认得出"这件事没被证明。
ck("alpha 那条没被误报", any("Show.S01" == n for n, _ in un), False)
ck("beta  那条没被误报", any("Movie.A" == n for n, _ in un), False)

print("== ③ 反向：补上一个包认领它，数就掉到 0 ==")
st.register_dirs("alpha", [("观影清单", FARM + "/0观影清单chrlee整理")])
ck("补登记后归零", unclaimed_searchees(st, SNAP), [])
# 再撤掉，确认这个 0 是"改对了"而不是"判据死了"
st.con.execute("DELETE FROM movie WHERE dir_name='观影清单'")
st.con.commit()
ck("撤掉后又回到 1", len(unclaimed_searchees(st, SNAP)), 1)

# --------------------------------------------------------------------------- #
# ④ 接线层：`drive-loop.reconcile_watch()` 绝不抛，且**真的报警**
# --------------------------------------------------------------------------- #
# ★ 这一节钉的不是"数算得对"（上面已经钉了），而是三件更容易静默坏掉的事：
#   ① 它挂在每天一次的日报里，日报挂在**每 15 分钟一批**的生产循环里 ——
#      它抛一次，整份日报就没了；
#   ② 读不到时 metrics 必须给 `n/a`，不能给 0 —— 否则 TSV 里
#      "这次读失败了"和"那天根本没跑"长得一模一样；
#   ③ 差不为 0 时**必须真的发 alert** —— 只写进正文的告警等于没发。
import argparse                      # noqa: E402
import contextlib                    # noqa: E402
import importlib.util                # noqa: E402
import io                            # noqa: E402
import re                            # noqa: E402
import sqlite3                       # noqa: E402

DRIVE_LOOP = pathlib.Path(__file__).resolve().parent.parent / "scripts" / "drive-loop.py"


def _load(path, name):
    """按 tests/README.md 的规矩：importlib 载**真的那份**，且先登记 sys.modules。"""
    if str(path.parent.parent) not in sys.path:
        sys.path.insert(0, str(path.parent.parent))
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod          # ★ 不登记的话 dataclass 会炸
    with contextlib.redirect_stdout(io.StringIO()), \
         contextlib.redirect_stderr(io.StringIO()):
        try:
            spec.loader.exec_module(mod)
        except SystemExit:
            pass
    return mod


print("== ④ reconcile_watch：绝不抛，读不到给 n/a 而不是 0 ==")
D = _load(DRIVE_LOOP, "drive_loop_reconcile")
events: list = []
D.emit = lambda kind, title, body="", *, key=None, metrics=None: (
    events.append((kind, title, body, key, metrics)) or True)

LOG_A = os.path.join(tempfile.mkdtemp(), "info.log")
pathlib.Path(LOG_A).write_text(LOG4, encoding="utf-8")
LOG_B = os.path.join(tempfile.mkdtemp(), "info2.log")
pathlib.Path(LOG_B).write_text(LOG_MISS, encoding="utf-8")

note, m = D.reconcile_watch(argparse.Namespace(log=None, db=None, db_path=None))
ck("没有 --log：不抛", isinstance(note, str), True)
ck("没有 --log：fa 是 n/a（★ 不是 0）", m["fa"], "n/a")
ck("没有 --log：正文点名「跳过」", "跳过" in note, True)

note, m = D.reconcile_watch(argparse.Namespace(log=[LOG_A], db=None, db_path=None))
ck("有日志：fa / fb 是真数", (m["fa"], m["fb"]), (3, 3))
ck("有日志：a − b", m["fd"], 0)
ck("没库：b−c 给 n/a", m["fb_c_all"], "n/a")
ck("没库：无人认领给 n/a（不是 0）", m["unclaimed"], "n/a")
ck("差值 0 时**不发**告警", events, [])

print("== ④ 差不为 0 → 必须真的发 alert，且 key 固定 ==")
events.clear()
note, m = D.reconcile_watch(argparse.Namespace(log=[LOG_B], db=None, db_path=None))
ck("差值 1 被报出来", m["fd"], 1)
ck("发了一条 alert", [e[0] for e in events], ["alert"])
ck("key 是 log-parse-miss（冷却靠它去重）", events[0][3], "log-parse-miss")
# ★ 留证行必须在**告警正文**里（只在日报正文里不算 —— 告警和日报是两条路）
ck("告警正文带留证行", "Miss.2021" in events[0][2], True)

print("== ④ 库可达 → b−c 与无人认领都是真数 ==")
events.clear()


def _fake_read(_p, *a, **k):
    return SNAP


D.S.read_crossseed_db = _fake_read        # 真库里那 1888 行的形状，用 SNAP 复刻
db2 = os.path.join(tempfile.mkdtemp(), "t2.db")
st2 = StateStore(db2)
# ★ 两个包都要登记 —— 只登记 alpha 的话，beta 那条会被正确地报成"无人认领"，
#   于是本节测的就不是接线而是夹具（第一版就是这么错的，数报了 2）。
st2.upsert_pack("alpha", A_ROOT, roots=[A_ROOT], farm_root=FARM)
st2.register_dirs("alpha", [("Show.S01", A_ROOT + "/Show.S01")])
st2.upsert_pack("beta", B_ROOT, roots=[B_ROOT], farm_root=FARM)
st2.register_dirs("beta", [("Movie.A", B_ROOT + "/Movie.A")])
pathlib.Path(LOG_A).write_text(
    '2026-09-12 01:00:00.000 info: [webhook] Found Show.S01 [abcd1234...]'
    ' on HDFans by MATCH from dataDir (%s/Show.S01) - MATCH' % FARM, encoding="utf-8")
note, m = D.reconcile_watch(argparse.Namespace(log=[LOG_A], db=db2, db_path="<stub>"))
ck("b − c〔全量口径〕", m["fb_c_all"], 0)
ck("农场行计数", m["fb_c_farm"], 1)
ck("无人认领 = 1（SNAP 里那条）", m["unclaimed"], 1)
ck("无人认领发了 alert", [e[3] for e in events if e[0] == "alert"],
   ["unclaimed-searchee"])
ck("正文点名那条路径（只报数 = 换个地方藏）",
   FARM + "/0观影清单chrlee整理" in note, True)

print()
if fails:
    print(f"★ {len(fails)} 条失败：")
    for f in fails:
        print("   " + f)
    sys.exit(1)
print("✓ 全过")

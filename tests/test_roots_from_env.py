# -*- coding: utf-8 -*-
"""`init --roots-from-env` 的**取值来源**：首选 FARM_SOURCES，缺席时退回 DATA_DIRS。

为什么要单独钉这一个
====================
`init` 是"加一个新包"这条路上**第一步**（也是唯一一步会写 `pack` 表的地方）。
它取根的来源在 v3 里**换过位置**：

    切换前   DATA_DIRS    = 那 49 条**源目录**   → 读它正确
    切换动作 = 把 DATA_DIRS 改成农场那一条
    切换后   DATA_DIRS    = /…/reseed_farm（cross-seed 的**输入**）
             FARM_SOURCES = 那 49 条源目录

所以「照旧逻辑读 DATA_DIRS + `--match <包关键词>`」在切换后**一条都挑不到**，
直接报「没挑到任何根」。这是**死路但不挡路**：平时没人跑 init，只有真加包那天才踩。

★ 这不是新设计，是**补上同一个切换里漏改的那一个工具**：
  `scripts/build-farm.sh:132-155` 早就是「优先 FARM_SOURCES，退回 DATA_DIRS」，
  连退回时的报错文案都写好了（`build-farm.sh:178-181`）。本文件钉的就是
  "两个工具读同一个键、同一种优先顺序"。

★ 期望值指回**判据之外的真实记录**（2026-09-12 实测，只读）：
  生产 `.env` 的 `DATA_DIRS` **1 条**（= reseed_farm）、`FARM_SOURCES` **49 条**
  = 1(FRDS) + 1(MBF) + 47(DC)；而 `state.db` 里三个包的 `roots` 分别是
  1 / 1 / 47。合成用例复刻这个形状。

全部离线：.env 是 `tempfile.mkdtemp()` 里现造的，不碰生产 `.env`、不碰 NAS。
"""
import importlib.util
import os
import pathlib
import sys
import tempfile

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

# ★ 输出强制 UTF-8：GBK 控制台下会在中途炸掉，而**已经过的断点看着全是 ok**。
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


def _load(path, name):
    """按 tests/README.md 的规矩：importlib 载**真的那份**，且先登记 sys.modules。"""
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod          # ★ 不登记的话 dataclass 会炸
    spec.loader.exec_module(mod)
    return mod


RS = _load(REPO / "scripts" / "reseed-state.py", "reseed_state_roots")


def _envfile(farm_sources=None, data_dirs=None):
    """造一个最小 .env。键给了才写 —— 用不着伪造别的行。"""
    lines = []
    if farm_sources is not None:
        lines.append("FARM_SOURCES=" + farm_sources)
    if data_dirs is not None:
        lines.append("DATA_DIRS=" + data_dirs)
    d = tempfile.mkdtemp()
    p = os.path.join(d, ".env")
    pathlib.Path(p).write_text("\n".join(lines) + "\n", encoding="utf-8")
    return p


# ★ 复刻生产的形状：农场 1 条、源根 3 条（一篇一包）
FARM = "/volume1/video/download/reseed/reseed_farm"
SRC_FRDS = "/volume1/video/download/movies/DouBan_IMDB.TOP250.Movies.Mixed.Collection"
SRC_MBF = "/volume1/video/download/TV/My.Brilliant.Friend.S01-S04.2018"
SRC_DC = "/volume1/video/download/movies/DC相关剧集全系列大合集"
SRCES = ",".join([SRC_FRDS, SRC_MBF, SRC_DC])

print("== ① 两个键都在 → 取 FARM_SOURCES（切换后的源清单）==")
p = _envfile(farm_sources=SRCES, data_dirs=FARM)
nas, loc, notes = RS._roots_from_env(p, ["DouBan_IMDB"], None, "/volume1")
ck("挑到 1 条", len(nas), 1)
ck("挑到的是源根（不是农场那条）", nas[0], SRC_FRDS)
ck("说明里点名 FARM_SOURCES", "FARM_SOURCES" in notes[0], True)
# ★ 反向控制：**不许**出现退回提示 —— 出现了就说明它其实读的是 DATA_DIRS。
ck("没有退回提示", any("退回来源" in n for n in notes), False)

print("== ① 反转：把 --match 换成农场那条的关键词，也**不该**命中 ==")
# ★ 这一格防的是「两个键都读、谁先命中算谁」那种含糊实现：
#   农场那条必须**看不见** —— 它对 FARM_SOURCES 来说根本不存在。
nas2, _, _ = RS._roots_from_env(p, ["reseed_farm"], None, "/volume1")
ck("农场关键词挑不到任何根（证明没读 DATA_DIRS）", nas2, [])

print("== ② FARM_SOURCES 缺席 → 退回 DATA_DIRS，且**必须说出来** ==")
p2 = _envfile(data_dirs=SRCES)
nas, _, notes = RS._roots_from_env(p2, ["DouBan_IMDB"], None, "/volume1")
ck("退回后仍挑得到", nas, [SRC_FRDS])
ck("说明里点名 DATA_DIRS", "DATA_DIRS" in notes[0], True)
ck("★ 说明了这是退回来源（不静默）", any("退回来源" in n for n in notes), True)

print("== ③ 两个键都没有 → 报错文案必须同时提到两个键 ==")
p3 = _envfile()
nas, _, notes = RS._roots_from_env(p3, ["x"], None, "/volume1")
ck("挑不到根", nas, [])
ck("同时点名 FARM_SOURCES", "FARM_SOURCES" in notes[0], True)
ck("同时点名 DATA_DIRS", "DATA_DIRS" in notes[0], True)

print("== ④ --match 挑不中 → 文案点名**实际用的那个键**与条数 ==")
# ★ 这正是 v3 之后照旧逻辑会看到的报错：DATA_DIRS 只有 1 条（农场），
#   --match <包关键词> 一条都不含 → 报「DATA_DIRS 共 1 条，没有一条包含 [...]」。
p4 = _envfile(data_dirs=FARM)
nas, _, notes = RS._roots_from_env(p4, ["DouBan_IMDB"], None, "/volume1")
ck("挑不到", nas, [])
ck("条数是农场的 1 条", "共 1 条" in notes[0], True)
ck("点名的是退回后的键 DATA_DIRS", "DATA_DIRS" in notes[0], True)

print("== ⑤ 多匹配（OR）+ 本地根映射 ==")
nas, loc, _ = RS._roots_from_env(p, ["DouBan_IMDB", "My.Brilliant.Friend"],
                                 "//NAS", "/volume1")
ck("OR 挑到 2 条", len(nas), 2)
ck("★ 顺序按 .env 里的顺序", nas, [SRC_FRDS, SRC_MBF])
ck("本地根把 /volume1 换成 //NAS", loc[0], "//NAS" + SRC_FRDS[len("/volume1"):])

print("== ⑥ ★ 回归核心：v3 那个形状下，照旧逻辑会挑 0 ==")
# ★ 这一格是整份文件的理由 —— 它把「换键」这件事**量成一个数**：
#   同一个 .env、同一个 --match，FARM_SOURCES 在 → 挑得到；只有 DATA_DIRS → 挑 0。
#   两格用的是**同一份** SRCES，所以差异只可能来自取值来源。
p6 = _envfile(farm_sources=SRCES, data_dirs=FARM)
new_nas, _, _ = RS._roots_from_env(p6, ["DC相关剧集全系列大合集"], None, "/volume1")
ck("改后（FARM_SOURCES）挑得到 DC 那 1 条", len(new_nas), 1)
ck("它确实是 DC 那条", new_nas == [SRC_DC], True)
# 反向控制：把 FARM_SOURCES 拿掉，同一句话就挑不到了 —— 证明上面那个 1
# 是**键换对了**换来的，不是判据天生就会返回 1。
p6b = _envfile(data_dirs=FARM)
gone, _, _ = RS._roots_from_env(p6b, ["DC相关剧集全系列大合集"], None, "/volume1")
ck("★ 只有 DATA_DIRS 时挑到 0（这就是 v3 之后的死路）", gone, [])

print()
if fails:
    print(f"★ {len(fails)} 条失败：")
    for f in fails:
        print("   " + f)
    sys.exit(1)
print("✓ 全过")

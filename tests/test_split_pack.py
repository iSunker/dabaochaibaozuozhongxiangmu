# -*- coding: utf-8 -*-
"""`scripts/diag/split-pack.py` —— 大包按季拆分：**季界判据**的离线回归。

它钉的是**判据本体**，不是"这个包拆没拆成"。三样东西各有一个"悄悄退化"的失效模式：

  ① **档 1（文件名 `SxxExx`）真的认出了季号**
     ★ 失效模式：正则写得太宽（认了裸 `E05`）⇒ **把无季信息的包也"拆"了**
       ⇒ 产出**编出来**的季界 ⇒ 发出去一个错种。这是本文件**最该钉**的一条。
     ★ 反向也要钉：正则写得太窄（认不出 `s1e5` / `S01.E05` / `S01-E05`）
       ⇒ 明明有季号的包被判成"判不出"。

  ② **档 3（裸集号 `E01..E24`）必须"拒绝猜"，退出码 3**
     ★ 失效模式：哪天有人给它加一个"按文件大小聚类"的启发式 ⇒
       **从"报判不出"退化成"给一个编的方案"**，而**输出看起来完全正常**。
     ★ 所以这里钉的不只是"判不出"，还有**它不产出方案**（没有季号、没有拟命令）。

  ③ **没有任何写盘路径 / 不带"自动执行"的能力**
     ★ 失效模式：有人给它加个 `--apply` 直接建链接 ⇒ 越过了 `A.10`（AI 不写 NAS）
       与 `A.16`（源是硬链接目标，动它可能写穿）。
     ★ 判据是**AST 层面**：模块里**不许**出现 `open(...,"w")` / `os.link` /
       `os.makedirs` / `shutil` / `subprocess` —— 不是 grep 字符串（注释里允许出现这些词）。

★ 数法/行形：只打印 `  ok  ` / ` FAIL `（`tests/README.md` 形状 A）。
★ 本文件用 `tempfile.mkdtemp()` 造**合成目录树**，不碰 NAS、不碰真库、不联网。
"""
from __future__ import annotations

import ast
import importlib.util
import pathlib
import sys
import tempfile

REPO = pathlib.Path(__file__).resolve().parent.parent
SCRIPT = REPO / "scripts" / "diag" / "split-pack.py"

_ok = 0
_bad = 0


def ck(name: str, cond: bool, extra: str = "") -> None:
    global _ok, _bad
    if cond:
        _ok += 1
        print(f"  ok   {name}")
    else:
        _bad += 1
        print(f"  FAIL {name}{('  —— ' + extra) if extra else ''}")


# ---- 把脚本当模块导进来（它有 `if __name__` 守卫，导入不会跑 main）----
_spec = importlib.util.spec_from_file_location("split_pack", SCRIPT)
sp = importlib.util.module_from_spec(_spec) if _spec else None
if sp is not None:
    try:
        _spec.loader.exec_module(sp)
    except Exception as e:            # noqa: BLE001
        print(f"  FAIL 导不进 split-pack.py：{type(e).__name__}: {e}")
        sp = None

ck("前提：split-pack.py 存在且可导入", sp is not None, f"{SCRIPT}")

if sp is None:
    print(f"\n{'=' * 60}")
    print(f"断言 {_ok + _bad} 条：{_ok} 过 / {_bad} 失败")
    sys.exit(1)

# ==========================================================================
print("\n① 档 1 · 文件名里的季号 —— 该认的认、不该认的不认")
# --------------------------------------------------------------------------
# 该认的（正向）
CANON = [
    ("[夺爱].Duo.Ai.2011.S01E05.1080p.WEB-DL.AAC-CMCTV.mkv", 1, 5),
    ("[夺爱].Duo.Ai.2011.S02E03.1080p.WEB-DL.AAC-CMCTV.mkv", 2, 3),
    ("Show.S1E05.1080p.mkv", 1, 5),                     # 一位数季/集
    ("Show.s1e5.mkv", 1, 5),                            # 全小写
    ("Show.S01.E05.mkv", 1, 5),                         # 点分
    ("Show.S01-E05.mkv", 1, 5),                         # 连字符
    ("Show.S01E156.mkv", 1, 156),                       # 三位集号（长篇剧）
    ("Friends.S10E17.2160p.mkv", 10, 17),               # 双位数季
]
for fname, want_s, want_e in CANON:
    ck(f"认得出 {fname}  ⇒ S{want_s:02d}E{want_e:02d}",
       sp.season_of(fname) == want_s and sp.episode_of(fname) == want_e,
       f"得到 season={sp.season_of(fname)} episode={sp.episode_of(fname)}")

# ★★ 不该认的（反向）—— 这些是"档 3"，认了就是在编
REJECT = [
    ("[夺爱].Duo.Ai.2011.E05.1080p.WEB-DL.AAC-CMCTV.mkv", "裸集号 E05"),
    ("Show.2011.EP05.mkv", "EP05（不是 Exx）"),
    ("Show.1080p.mkv", "压根没有季集号"),
    ("Movie.2011.2160p.HEVC.mkv", "电影"),
    ("Show.S01.mkv", "只有季、没有集 —— 不成对，档 1 判不了它"),
]
for fname, why in REJECT:
    ck(f"不认 {fname}（{why}）", sp.season_of(fname) is None,
       f"却认出 season={sp.season_of(fname)}")

# ==========================================================================
print("\n② 档 2 · 季层目录名")
# --------------------------------------------------------------------------
DIR_OK = [
    ("S01", 1), ("s02", 2), ("Season 3", 3), ("Season.4", 4),
    ("第5季", 5), ("S01.1080p.WEB-DL", 1),
]
for d, want in DIR_OK:
    ck(f"目录名 {d!r} ⇒ 季 {want}", sp.season_of_dir(d) == want,
       f"得到 {sp.season_of_dir(d)}")
DIR_NO = [
    ("E01", "集目录，不是季"), ("Extras", "花絮"), ("Sample", "样片"),
    ("Subs", "字幕"), ("[夺爱].Duo.Ai.2011.Complete.1080p", "发布名本身，不是季层"),
]
for d, why in DIR_NO:
    ck(f"目录名 {d!r} 不算季（{why}）", sp.season_of_dir(d) is None,
       f"却得到 {sp.season_of_dir(d)}")

# ==========================================================================
print("\n③ 分组：档 1 端到端（合成目录树）")
# --------------------------------------------------------------------------
tmp = tempfile.mkdtemp(prefix="split-pack-test-")
pack = pathlib.Path(tmp) / "[夺爱].Duo.Ai.2011.Complete.WEB-DL.4K.HEVC.AAC-CMCTV"
pack.mkdir(parents=True)
# S01 两集、S02 两集，另加一个**裸集号**文件（应当被判为"归不到季"）
for name in ("[夺爱].Duo.Ai.2011.S01E01.1080p.CMCTV.mkv",
             "[夺爱].Duo.Ai.2011.S01E02.1080p.CMCTV.mkv",
             "[夺爱].Duo.Ai.2011.S02E01.1080p.CMCTV.mkv",
             "[夺爱].Duo.Ai.2011.S02E02.1080p.CMCTV.mkv",
             "[夺爱].Duo.Ai.2011.E99.1080p.CMCTV.mkv"):
    (pack / name).write_bytes(b"")
# 一个非视频文件，必须**不被**当成入口
(pack / "cover.jpg").write_bytes(b"")

files = sp.walk_videos(str(pack))
ck("walk_videos 只收视频（cover.jpg 不算）", len(files) == 5, f"得到 {len(files)}")

groups, unknown = sp.group_by_name(str(pack), files)
ck("档 1 分出 2 季", sorted(groups) == [1, 2], f"得到 {sorted(groups)}")
ck("S01 有 2 个文件", len(groups.get(1, [])) == 2, f"{len(groups.get(1, []))}")
ck("S02 有 2 个文件", len(groups.get(2, [])) == 2, f"{len(groups.get(2, []))}")
ck("裸集号 E99 落进 unknown（不硬塞）", len(unknown) == 1, f"得到 {unknown}")

# ★★ 反向：把文件名里的季号拿掉 ⇒ 必须**整体判不出**（不是"随便给一季"）
bare = pathlib.Path(tmp) / "BarePack"
bare.mkdir()
for e in range(1, 5):
    (bare / f"Bare.E{e:02d}.1080p.mkv").write_bytes(b"")
bfiles = sp.walk_videos(str(bare))
bgroups, bunknown = sp.group_by_name(str(bare), bfiles)
ck("★★ 裸集号包 ⇒ 档 1 **一个季都判不出**（不猜）", bgroups == {},
   f"却得到 {sorted(bgroups)}")
ck("★★ 且那 4 个文件全部落在 unknown（没被静默丢掉）", len(bunknown) == 4,
   f"得到 {len(bunknown)}")

# ==========================================================================
print("\n④ 命名派生：从源发布名机械换季位")
# --------------------------------------------------------------------------
names, why = sp.derive_names("[夺爱].Duo.Ai.2011.Complete.WEB-DL.4K.HEVC.AAC-CMCTV", [1, 2])
ck("派生成功（不报 why）", why is None, f"why={why}")
ck("S01 名字换掉 Complete 那一格",
   names.get(1) == "[夺爱].Duo.Ai.2011.S01.WEB-DL.4K.HEVC.AAC-CMCTV", f"{names.get(1)}")
ck("S02 同理", names.get(2) == "[夺爱].Duo.Ai.2011.S02.WEB-DL.4K.HEVC.AAC-CMCTV",
   f"{names.get(2)}")
ck("★ 其余字段**逐字保留**（只动那一格）",
   names.get(1, "").count(".") == "[夺爱].Duo.Ai.2011.Complete.WEB-DL.4K.HEVC.AAC-CMCTV".count("."),
   "字段数变了 ⇒ 不是「机械截取」了")

# Friends 那种（`Complete.Series` + 年份区间）
fn, fwhy = sp.derive_names(
    "Friends.The.Complete.Series.1994-2003.2160p.UHD.Blu-ray.REMUX.HEVC.DTS-HD.MA5.1-HDH", [1, 10])
ck("Friends 派生成功", fwhy is None, f"why={fwhy}")
ck("Friends 的季位落在 Complete 那一格",
   fn.get(1) == "Friends.The.S01.Series.1994-2003.2160p.UHD.Blu-ray.REMUX.HEVC.DTS-HD.MA5.1-HDH",
   f"{fn.get(1)}")
print("  --   ★ Friends 那个派生结果**语义可疑**（只换了 Complete、留着 Series）——")
print("      ★ 这是**已知的判据弱点**，不是断言失败：真名字要按站点/我们要发的那个定。")

# 派生不出来时**必须报 why**，不许硬塞
n2, w2 = sp.derive_names("SomeShow.2011.1080p.WEB-DL.mkv", [1, 2])
ck("★ 找不到季位 ⇒ 报 why、不产出名字", w2 is not None and n2 == {},
   f"names={n2} why={w2}")

# ==========================================================================
print("\n⑤ 只读纪律 —— 用**绊线**证明「跑一遍不写盘」，而不是靠黑白名单")
# --------------------------------------------------------------------------
# ★★ 为什么不用 AST 黑白名单：它**证不完**（`__import__("os").makedirs` 就绕过去了 ——
#    实测过：第一版黑名单**漏掉**了这个变异，断言仍是绿的，即 `ERR-AI-05` 那个形状
#    「绿，但绿是因为规则压根没参与匹配」）。
# ⇒ 换成一个**能真正兜住**的判据：把危险函数**换成会抛的桩**，然后**真跑一遍** ——
#    桩没响 = 那段路径确实没被走到。
import builtins                                    # noqa: E402
import pathlib as _pl                              # noqa: E402
import tempfile as _tf                             # noqa: E402

# ★★ 先造好夹具，**再**上绊线 —— 否则绊线会先把夹具自己拦住
#    （实测：`sp.os` 与 `tempfile` 用的是**同一个模块对象**，改它就是改全局）。
trip_tmp = _tf.mkdtemp(prefix="split-pack-trip-")
trip_pack = _pl.Path(trip_tmp) / "Show.Complete.1080p"
trip_pack.mkdir(parents=True)
for s, e in ((1, 1), (1, 2), (2, 1)):
    (trip_pack / f"Show.S{s:02d}E{e:02d}.1080p.mkv").write_bytes(b"")

_saved = {}

def _trip(name):
    def _boom(*a, **k):
        raise AssertionError(f"绊线响了：{name} 被调用（本脚本必须只读）")
    return _boom

# 保留**读**用的那几个（open 读、os.scandir、os.walk、os.path.*）不动。
_WRITE_NAMES = ("link", "symlink", "makedirs", "mkdir", "remove", "unlink",
                "rmdir", "rename", "chmod", "chown", "system", "truncate")
for n in _WRITE_NAMES:
    if hasattr(sp.os, n):
        _saved[n] = getattr(sp.os, n)
        setattr(sp.os, n, _trip(f"os.{n}"))
# `open` 也设桩，但**放行读模式**（本脚本要读目录树）
_real_open = builtins.open
def _open_guard(file, mode="r", *a, **k):
    if any(c in str(mode) for c in "wax+"):
        raise AssertionError(f"绊线响了：open({file!r}, mode={mode!r}) —— 本脚本必须只读")
    return _real_open(file, mode, *a, **k)
builtins.open = _open_guard

_tripped = None
_fired = False
# ★★ 反向检查**必须在拆绊线之前做** —— 否则"绊线会响吗"这个问题问的是
#    一个已经被拆掉的绊线（第一版就栽在这里：`finally` 先拆了，反向检查恒绿为"不响"）。
try:
    # ★ 直接调 `main()` 会读 `sys.argv` ⇒ 显式喂 argv（不改全局，用局部替换）
    _argv_bak = sys.argv
    sys.argv = ["split-pack.py", str(trip_pack), "--emit-cmds"]
    try:
        _rc = sp.main()
    finally:
        sys.argv = _argv_bak
    # ★ 反向（仍带电时试一次）：绊线**确实会响**
    try:
        sp.os.makedirs("/tmp/should-not-happen", exist_ok=True)
    except AssertionError:
        _fired = True
except AssertionError as e:
    _tripped = str(e)
    _rc = None
finally:
    for n, fn in _saved.items():
        setattr(sp.os, n, fn)
    builtins.open = _real_open

ck("★★ 绊线：跑一遍真流程（含 --emit-cmds），**没有任何写盘/执行调用被触发**",
   _tripped is None, f"绊线响了：{_tripped}")
ck("★ 且那一遍正常出了方案（说明绊线没把它自己跑挂）",
   _tripped is None and _rc == 0, f"rc={_rc}")
ck("★★ 反向：绊线**真的会响**（证明上面那条不是假绿）", _fired,
   "绊线挂上了却不抛 ⇒ 那条断言恒真")
print("  --   ★ 这条为什么比 AST 黑名单强：黑名单漏掉过 `__import__(\"os\").makedirs`")
print("      （实测：第一版断言**仍是绿的** —— `ERR-AI-05` 形状），绊线兜住了整类。")

# ★ subprocess / shutil 连 import 都不许
src = SCRIPT.read_text(encoding="utf-8")
tree = ast.parse(src)
BAD_MODULES = {"subprocess", "shutil"}
imported = set()
for node in ast.walk(tree):
    if isinstance(node, ast.Import):
        imported.update(a.name.split(".")[0] for a in node.names)
    if isinstance(node, ast.ImportFrom) and node.module:
        imported.add(node.module.split(".")[0])
ck("★ 不 import subprocess / shutil", not (imported & BAD_MODULES),
   f"发现：{sorted(imported & BAD_MODULES)}")
ck("★ 不用 os.system（文本层再钉一道）", "os.system" not in src, "出现了 os.system")

# ==========================================================================
print("\n⑤b 档 3 的**外部季界入口**（`26.38-A`）：Torznab attr 只读不判")
# --------------------------------------------------------------------------
# ★★ 为什么钉这三个函数：档 3 的正路是**外部季界**（Torznab 优先），
#    所以「从响应里取季号」这条路**至少要有入口**。★ 但纪律不能因此松：
#    **取不到季号就必须还是判不出（rc=3）**，不许因为"多了个函数"就偷偷开始猜。
# ★ 凭据形状的值拼出来，不在源码里留字面量（推前扫描会扫到这个文件）。
_RSS = (
    '<rss><item><title>A.S02.1080p</title>'
    '<torznab:attr name="season" value="2"/>'
    '<torznab:attr name="rageid" value="99"/>'
    "</item><item><title>B.S01.1080p</title></item></rss>"
)
_its = sp.items_of(_RSS)
ck("items_of：切出 2 个 item", len(_its) == 2, f"得到 {len(_its)}")
ck("★ item 整块留下（attr 还在，没被截掉）",
   "<torznab:attr" in _its[0], "item 被截断了 ⇒ 取不到季号")
ck("attrs_of 列出**所有** attr（含 rageid）",
   sp.attrs_of(_its[0]) == [("season", "2"), ("rageid", "99")],
   f"{sp.attrs_of(_its[0])}")
ck("★ season_from_attrs 取到 2", sp.season_from_attrs(_its[0]) == 2,
   f"{sp.season_from_attrs(_its[0])}")
ck("★ 没有 season 的 item ⇒ None（**不编**）",
   sp.season_from_attrs(_its[1]) is None, f"{sp.season_from_attrs(_its[1])}")
ck("★★ `rageid` 那类**锚**不算季号（它只是『去别处查』的入口）",
   sp.season_from_attrs('<torznab:attr name="rageid" value="99"/>') is None,
   "把 rageid 当成季号了 —— 那是编")
ck("season 值不是数字 ⇒ None（不抛、不编）",
   sp.season_from_attrs('<torznab:attr name="season" value="S02"/>') is None,
   "非数字值没被挡住")
# ★★ 反向（最关键的一格）：**这几个函数存在**不许让档 3 松口 ——
#    判据仍然是"真跑一遍、真退出码 3"（下面 ⑥ 那条；这里钉住它有 attr 入口也没用）。
ck("★★ 有 attr 入口**也不改**档 3 的纪律（`--season-hint` 不在本脚本里）",
   "season_from_attrs" in SCRIPT.read_text(encoding="utf-8")
   and "--season-hint" not in SCRIPT.read_text(encoding="utf-8"),
   "本脚本给档 3 加了个『按 hint 拆』的开关 ⇒ 那就是开始猜了")

# ==========================================================================
print("\n⑥ 档 3 的行为：拒绝猜 + 退出码 3（跑真进程，判真退出码）")
# --------------------------------------------------------------------------
import subprocess as _sp  # noqa: E402  ★ 本文件自己允许用它（被钉的是被测脚本）

r = _sp.run([sys.executable, str(SCRIPT), str(bare)],
            capture_output=True, text=True, encoding="utf-8", timeout=60)
ck("★★ 裸集号包 ⇒ 退出码 3（判不出，不是 0）", r.returncode == 3,
   f"rc={r.returncode} out={r.stdout[-200:]}")
ck("★★ 且明确打了「判不出季界」", "判不出季界" in r.stdout, r.stdout[-300:])
ck("★★ 且**不产出任何季号**（没有 S01/S02 出现在方案里）",
   "判到" not in r.stdout, "出现「判到 N 季」⇒ 它给了方案（那就是在猜）")
ck("★ 且打了后续两条路线（Torznab / TMDB）",
   "Torznab" in r.stdout and "TMDB" in r.stdout, "没给后续路线")
ck("★ 且拟命令**没**被打印（--emit-cmds 没给时本来也不该有；这里是双保险）",
   "mkdir -p" not in r.stdout, "打印了拟命令")

# 反向：有一个真季号的包 ⇒ rc 0 且给出方案
r2 = _sp.run([sys.executable, str(SCRIPT), str(pack), "--emit-cmds"],
             capture_output=True, text=True, encoding="utf-8", timeout=60)
ck("★ 有两季的包 ⇒ 退出码 0", r2.returncode == 0, f"rc={r2.returncode} {r2.stdout[-200:]}")
ck("★ 打出「判到 2 季」", "判到" in r2.stdout and "2 季" in r2.stdout, r2.stdout[-300:])
ck("★ --emit-cmds 时打印拟命令", "mkdir -p" in r2.stdout, "没打印")
ck("★★ 拟命令里**没有** `ln -s`（要的是硬链接，不是软链）",
   "ln -s" not in r2.stdout, "出现了软链接命令")

# 单季包 ⇒ 明确说"不用拆"（用户 2026-09-21 判据：1 季不算大包）
single = pathlib.Path(tmp) / "OneSeason"
single.mkdir()
for e in range(1, 4):
    (single / f"Show.S01E{e:02d}.1080p.mkv").write_bytes(b"")
r3 = _sp.run([sys.executable, str(SCRIPT), str(single)],
             capture_output=True, text=True, encoding="utf-8", timeout=60)
ck("★ 单季包 ⇒ 退出码 0 且说「不叫大包 / 不用拆」",
   r3.returncode == 0 and "不用拆" in r3.stdout, f"rc={r3.returncode} {r3.stdout[-200:]}")

# 不存在的目录 ⇒ 退出码 2（"读不到"≠"没有"）
r4 = _sp.run([sys.executable, str(SCRIPT), str(pathlib.Path(tmp) / "nope")],
             capture_output=True, text=True, encoding="utf-8", timeout=60)
ck("★ 目录不存在 ⇒ 退出码 2，且提示「读不到≠没有」",
   r4.returncode == 2 and "不是" in r4.stdout, f"rc={r4.returncode}")

print(f"\n{'=' * 60}")
print(f"断言 {_ok + _bad} 条：{_ok} 过 / {_bad} 失败")
sys.exit(0 if _bad == 0 else 1)

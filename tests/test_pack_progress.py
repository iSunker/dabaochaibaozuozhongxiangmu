# -*- coding: utf-8 -*-
"""各包进度（`pack_progress`）—— 日报新节 + `#95` 的空格键加固。

钉的是**三件互相独立的事**，每一件都对应 `#90–#97` 里的一条订正：

  ① `#95` **包名含空格会让 metrics 字段裂开，且碎片能伪造出 `pack=` 键。**
     这是本文件里**最重**的一条 —— 摘要数批次靠的是 `pack=` **整键相等**
     （`notify-spool.sh` 里那条 awk，`test_notify_digest.py` 专门钉过
     「`packs=` 不是 `pack=`」）。所以：

         seeding:my pack=1 ok=50
                    ↑ 按空格切开 ⇒ "seeding:my"（没有 `=`，键消失）
                                   + "pack=1"（键恰好 = `pack`！）

     ⇒ 一个叫 `my pack` 的包会让该行被**误计为一批**。
     ★ 修法在**写入端**（`notify.py` 的键也做 `.replace(' ', '_')`），
       不动已部署的 `notify-spool.sh`。

  ② `#96` **新节必须落在 `report_daily` 那个 `try/with S.StateStore` 里。**
     读不到时给 `n/a`，**不许给 0** —— `n/a` / `0` / 「没事」是三件事
     （`ERR-AI-03`）。这里用 stub 掉 `StateStore` 的办法直接验。

  ③ `#97` **计数只有一份。** `sync_pack` 与 `pack_progress` 必须走**同一个**
     表达式；两处各写一遍就会静默分叉（两个数"看着都对"却对不上）。

★ 行形用既有的 `  ok  ` / ` FAIL `（不造第四种，`tests/README.md:63-67`）；
  节编号不越过 `⑩`（`⑪` 在 GBK 控制台下编不出去，会把脚本从中间打断）。
★ 全部离线：SQLite 都在 `tempfile` 里现造，不碰 NAS、不碰生产库、不发信。
"""
import importlib.util
import io
import contextlib
import pathlib
import sys
import tempfile

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from orchestrator.state import (            # noqa: E402
    STAGE_SEEDING, STAGE_PENDING, StateStore, pack_progress, pack_seeding_total,
)

# ★ 输出强制 UTF-8：GBK 控制台下会在中途炸掉，而**已经过的断点看着全是 ok**
#   —— 极易误判成代码坏了（`ERR-OS-04` / `ERR-ENC-01`）。
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

fails: list[str] = []


def ck(label, got, want):
    ok = got == want
    print(("  ok  " if ok else " FAIL ") + f"{label}: {got!r}")
    if not ok:
        fails.append(f"{label}: got {got!r} want {want!r}")


def ck_true(label, cond, extra=""):
    print(("  ok  " if cond else " FAIL ") + label + (f"  —— {extra}" if extra and not cond else ""))
    if not cond:
        fails.append(f"{label}{('  —— ' + extra) if extra else ''}")


def _load(path, name):
    """按 `tests/README.md` 的规矩：importlib 载**真的那份**，且**先**登记 `sys.modules`。

    ★ 不登记的话，被测文件里的 `@dataclass` 会炸一个看着毫不相干的
      `AttributeError: 'NoneType' object has no attribute '__dict__'`（`ERR-PY-03`）。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod                 # ★ 必须在 exec_module 之前
    with contextlib.redirect_stdout(io.StringIO()), \
         contextlib.redirect_stderr(io.StringIO()):
        try:
            spec.loader.exec_module(mod)
        except SystemExit:
            pass
    return mod


# --------------------------------------------------------------------------- #
# ① notify.py：空格键规范化 —— 判据**成对**（既要断言不再伪造，也要断言旧写法会伪造）
# --------------------------------------------------------------------------- #

print("== ① notify：键里的空格要被规范化，且**不许**再伪造出 `pack=` 键 ==")
NOTIFY = REPO / "scripts" / "notify.py"
NT = _load(NOTIFY, "notify_pack_progress")

_n = NT.Notifier.__new__(NT.Notifier)
_n.host = "lab"


def _metrics_line(pairs: dict) -> str:
    ev = NT.Event(kind="batch", title="t", metrics=pairs)
    out = _n._render(ev, 0.0)
    return [ln for ln in out.splitlines() if ln.startswith("metrics:")][0]


def _keys_of(line: str) -> list:
    """复刻 NAS 侧 awk 的切法：按**单个空格**切开，取第一个 `=` 之前的整串。"""
    body = line.split("metrics: ", 1)[1]
    out = []
    for tok in body.split(" "):
        p = tok.find("=")
        if p > 0:
            out.append(tok[:p])
    return out


# ①a 含空格的键：规范化后键**原样连在一起**（不再裂开）
line = _metrics_line({"seeding:my pack": 1, "ok": 50})
ck("含空格键 → 键被规范化", "seeding:my_pack=1" in line, True)
ck("含空格键 → 切出的键列表", _keys_of(line), ["seeding:my_pack", "ok"])

# ①b ★★ 关键断言：**不许**出现键恰好等于 `pack` 的碎片
ck_true("★ 不再伪造出 `pack=` 键（否则该行会被误计为一批）",
        "pack" not in _keys_of(line),
        f"切出的键={_keys_of(line)!r}")

# ①c 值里的空格照旧被规范化（原有行为，不许被本次改动破坏）
line_v = _metrics_line({"seeding:x": "frds top"})
ck("值含空格 → 值的空格仍换成下划线", "seeding:x=frds_top" in line_v, True)

# ①d ★ 阴性对照：这条判据**必须能红** —— 直接复刻**旧写法**（键不换空格）
_old = " ".join(f"{NT._clean_line(str(k))}={NT._clean_line(str(v)).replace(' ', '_')}"
                for k, v in {"seeding:my pack": 1, "ok": 50}.items())
_old_line = f"metrics: {_old}"
ck_true("★ 阴性对照：旧写法（键不换空格）**确实**会伪造出 `pack` 键",
        "pack" in _keys_of(_old_line),
        f"旧写法切出={_keys_of(_old_line)!r} —— 若这里不红，说明上面那条断言恒真")

# --------------------------------------------------------------------------- #
# ② pack_progress：结构化输出 + 空集 ≠ 读不到
# --------------------------------------------------------------------------- #

print()
print("== ② pack_progress：每包 (做种/总数/时刻)，空集 ≠ 读不到 ==")

_tmp = pathlib.Path(tempfile.mkdtemp(prefix="packprog-lab-"))
db = _tmp / "state.db"

print("  -- 夹具建库（`create=True` —— 生产默认不建，见 StateStore.__init__ / `ERR-SQL-04`）--")
with StateStore(db, create=True) as st:
    st.upsert_pack("alpha", "/volume1/video/a", max_depth=2)
    st.register_dirs("alpha", [("m1", "/volume1/video/a/m1"),
                              ("m2", "/volume1/video/a/m2"),
                              ("m3", "/volume1/video/a/m3")])
    # m1 设为 SEEDING、m2 设 MATCHED（不该计入 seeding）、m3 留 PENDING
    st.con.execute("UPDATE movie SET stage=? WHERE pack=? AND dir_name=?", (STAGE_SEEDING, "alpha", "m1"))
    st.con.execute("UPDATE movie SET stage='MATCHED' WHERE pack=? AND dir_name=?", ("alpha", "m2"))
    st.con.commit()
# ④ 每包**自己**的时刻（`mark_scan` 是生产里唯一写它的地方）
with StateStore(db) as st:
    st.mark_scan("alpha", finished=True)

with StateStore(db, create=True) as st:
    rows = pack_progress(st)
    ck("包数", len(rows), 1)
    ck("包名", rows[0]["name"], "alpha")
    ck("做种数（只有 SEEDING 计入）", rows[0]["seeding"], 1)
    ck("总数（= 声明过的单片数）", rows[0]["total"], 3)
    # ④ 每包带**自己**的时刻，不是全局「截至」—— 断言"有值"即可（`mark_scan` 写的是 now）
    ck_true("每包自己的 scan_finished_at 有值（不是 None、不是全局截至）",
            bool(rows[0]["scanned_at"]), f"got {rows[0]['scanned_at']!r}")

# ②b `total` 的定义：多于 init --dry-run 是**定义**，不是 bug
with StateStore(db) as st:
    st.register_dirs("alpha", [("gone-now", "/volume1/video/a/gone-now")])
with StateStore(db) as st:
    rows2 = pack_progress(st)
    ck("★ 重跑 init 前 total 会大于 dry-run 的数（register_dirs 从不删行）",
       rows2[0]["total"], 4)

# ②c ★★ 空集 ≠ 读不到：一个包都没有时返回**空列表**，不是 None、不是抛
empty = _tmp / "empty.db"
with StateStore(empty, create=True) as st:
    ck("库在、但一个包都没登记 → 空列表", pack_progress(st), [])

# --------------------------------------------------------------------------- #
# ③ 计数只有一份（#97）：pack_seeding_total 与 sync_pack 同源
# --------------------------------------------------------------------------- #

print()
print("== ③ 计数只有一份（#97）==")

_STATE_SRC = (REPO / "orchestrator" / "state.py").read_text(encoding="utf-8")
ck_true("★ sync_pack 不再自己写计数（改调共用函数）",
        "rep.seeding, _ = pack_seeding_total(store, pack_name)" in _STATE_SRC,
        "没找到那一行 —— 计数可能又被复制成两份了")
_NEEDLE = 'r["stage"] == STAGE_SEEDING'
ck("★ `stage == STAGE_SEEDING` 表达式只剩一处（在 pack_seeding_total 里）",
   _STATE_SRC.count(_NEEDLE), 1)

with StateStore(db) as st:
    a = pack_seeding_total(st, "alpha")
    rows = pack_progress(st)
    b = (rows[0]["seeding"], rows[0]["total"])
    ck("★ 两条路给出同一个数", a, b)

# --------------------------------------------------------------------------- #
print()
if fails:
    print(f"★ {len(fails)} 条失败：")
    for f in fails:
        print("   " + f)
    sys.exit(1)
print("✓ 全过")

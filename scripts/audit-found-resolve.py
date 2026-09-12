#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""对账 b − c：Found 行里的 searchee 路径，走**生产代码本身**能不能归到单片。

b = `_RE_FOUND` 命中行数（`audit-found-lines.py` 已对平：a − b = 0）
c = 其中 `_resolve_searchee_to_pack()` 判成 **in_pack**（即真的归到了单片）的行数
期望 b − c = 0：抓到的行不光是"抓到了"，还真的**落到了某个单片上**。

★ 与第一版的区别（重要）：第一版自己**重写了一遍** roots/dpaths/farm 的拼装逻辑，
  那是"用我的模型去核对生产模型"——属于循环论证。
  这一版走真正的 `StateStore.roots/dir_paths/farm_dir_paths/farm_root` 和真正的
  `_resolve_searchee_to_pack()`，只把 searchee 路径替换成日志里那一条。

★ 这道对账**覆盖不到农场那条防线**：见下面 `farm_lines` 那几行输出。
  只要日志里还没有 `[inject] Found … from dataDir (/…/reseed/reseed_farm/…)`，
  农场分支的流量就是 0，`b − c = 0` 说的是**原路径**干净。
  农场路径目前只出现在 `[inject] Skipping match … due to title mismatch` 里，
  那种行 `_RE_FOUND` 根本不匹配（也不是 Found 行）。

只读：库用 `mode=ro` 拿不到（UNC 不支持 file:// authority），改用
  **裸 UNC 路径 + `PRAGMA query_only = ON`**（就是生产 `_open_csdb()` 那套）。
  已确认库旁没有 state.db-wal / -shm / -journal（journal_mode=delete，事务干净），
  所以直读不会漏任何已提交事务。

用法
----
    python scripts/audit-found-resolve.py

全程只读；不写任何本地文件（连 `state.db` 都不碰，见 `ro_store()`）。
"""

from __future__ import annotations

import pathlib
import re
import sqlite3
import sys
import types

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(REPO))

import orchestrator.state as S          # noqa: E402

# ★ 输出强制 UTF-8：GBK 控制台下会在中途炸掉，
#   而**已经过的打印看着全是 ok** —— 极易误判成逻辑坏了。
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

NAS = pathlib.Path(r"//iSunker-DS423/docker_ssd/prowlarr_cross-seed_autohardlink")
LOG = NAS / "cross-seed/logs/info.current.log"
DB = NAS / "drive-loop/hlink/state.db"

RE_FOUND = S._RE_FOUND
B_PREV = 1011          # 2026-09-12 实测的 b（audit-found-lines.py 报出），仅作参照

NEW_FARM = "/volume1/video/download/reseed/reseed_farm/"
OLD_FARM = "/volume1/video/download/reseed_farm/"


def open_ro(p: pathlib.Path) -> sqlite3.Connection:
    """只读打开 —— 库里绝不放行任何写（query_only 是硬闸）。"""
    con = sqlite3.connect(str(p))                  # 裸路径：UNC 只有这一种开法能成
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA query_only = ON")          # ★ 硬闸：本连接从此拒绝任何写
    if not con.execute("PRAGMA query_only").fetchone()[0]:
        raise RuntimeError("query_only 没设上 —— 拒绝继续")
    return con


def ro_store(con: sqlite3.Connection) -> "S.StateStore":
    """用**真的** StateStore 方法 + 只读连接 —— 不落任何本地文件。

    `object.__new__` 绕过 `__init__`：那条路会 mkdir + executescript + commit，
    对着 UNC 上的**生产库**跑它就等于写库。这里只借方法，不借构造。
    """
    st = object.__new__(S.StateStore)
    st.path = pathlib.Path("<ro>")
    st.con = con
    return st


def sname(path: str) -> str:
    return path.rstrip("/").rsplit("/", 1)[-1]


def snap_for(path: str) -> "S.CrossSeedSnapshot":
    """造一个只含一条 searchee 的快照 —— 和 read_crossseed_db() 的形状一致。

    ★ 坑（第一版就栽在这）：`searchee_paths` 的**键是 searchee 名**，值是路径。
      得先把**名字**当第一个实参传给 `_resolve_searchee_to_pack`，它才 `.get()` 得到；
      传成整条路径 → 取到 "" → 静默退化成"只按名字猜"的兜底分支，
      于是每一行都走错分支，报出来的 440 全是不算数的。
      当时**是下面那道控制①**把它当场抓出来的（控制①返回 unresolved 而不是 in_pack）。
    """
    return types.SimpleNamespace(searchee_paths={sname(path): path})


def main() -> int:
    if not LOG.is_file() or not DB.is_file():
        print(f"✗ 缺文件: log={LOG.is_file()} db={DB.is_file()}", file=sys.stderr)
        return 2

    con = open_ro(DB)
    store = ro_store(con)

    packs = [r["name"] for r in store.packs()]
    ctx: dict[str, dict] = {}
    for pk in packs:
        roots = store.roots(pk)
        dirs = {r["dir_name"] for r in store.movies(pk)}
        dpaths = store.dir_paths(pk)
        farm = store.farm_root(pk)
        dpaths.update(store.farm_dir_paths(pk))
        ctx[pk] = dict(roots=roots, dirs=dirs, dpaths=dpaths, farm=farm)
        print(f"   {pk}: roots={len(roots)} 单片={len(dirs)} dpaths={len(dpaths)}"
              f" farm={farm or '(未登记)'}")

    # ── 正向控制（先证明"这套解析真的能解析"，否则下面的 0 什么都不是）──
    print()
    ok = True
    probe = None
    for pk, d in ctx.items():
        for mp, dn in d["dpaths"].items():
            snap = snap_for(mp)
            got, belong = S._resolve_searchee_to_pack(sname(mp), snap, d["roots"],
                                                      d["dirs"], d["dpaths"], d["farm"])
            probe = (pk, mp, got, belong, dn)
            break
        if probe:
            break
    if probe is None:
        print("✗ 控制①失败：库里一条 movie.path 都取不到 —— 下面所有 0 都不可信")
        ok = False
    elif probe[2] is None:
        print(f"✗ 控制①失败：拿库**自己**的路径 {probe[1][:90]!r} 去解析，"
              f"居然归不到单片（belong={probe[3]}）—— 解析链是坏的，"
              f"下面报的 other_pack 全是假象")
        ok = False
    else:
        print(f"✓ 控制①：库自带路径可归片  {probe[1][:60]}… → {probe[2]!r}"
              f"（belong={probe[3]}）")

    # ── 逐行对账 ──
    b = 0
    belong_n: dict[str, int] = {}
    hit_dirs: dict[str, int] = {}
    farm_lines = 0
    orig_lines = 0
    samples: dict[str, list[str]] = {}
    t_first = t_last = ""
    pre_kind: dict[str, int] = {}

    f = re.compile(r"^\d{4}-\d\d-\d\d \d\d:\d\d:\d\d\.\d+ \w+: (?P<msg>.*)$")
    with LOG.open("r", encoding="utf-8", errors="replace") as fh:
        for raw in fh:
            if "] Found " not in raw:
                continue
            m = f.match(raw.rstrip("\r\n"))
            if not m:
                continue
            mm = RE_FOUND.search(m.group("msg"))
            if not mm:
                continue
            b += 1
            ts = raw[:19]
            t_first = t_first or ts
            t_last = ts
            p = S._norm_path(mm.group(5))
            kind = ("新农场根" if p.startswith(NEW_FARM) else
                    "旧农场根" if p.startswith(OLD_FARM) else "原目录")
            pre_kind[kind] = pre_kind.get(kind, 0) + 1
            is_farm = any(d["farm"] and p.startswith(S._norm_path(d["farm"]) + "/")
                          for d in ctx.values())
            farm_lines += 1 if is_farm else 0
            orig_lines += 0 if is_farm else 1

            best = None
            for pk, d in ctx.items():
                got, belong = S._resolve_searchee_to_pack(sname(p), snap_for(p), d["roots"],
                                                          d["dirs"], d["dpaths"], d["farm"])
                if got:
                    best = (pk, got, belong)
                    break
                if belong == "in_pack":
                    best = (pk, None, belong)
            if best is None:
                belong = "other_pack"
            else:
                _, got, belong = best
                if got:
                    hit_dirs[got] = hit_dirs.get(got, 0) + 1
            belong_n[belong] = belong_n.get(belong, 0) + 1
            if len(samples.get(belong, [])) < 3:
                samples.setdefault(belong, []).append(p[:120])

    c = belong_n.get("in_pack", 0)
    print()
    print(f"  b  Found 行                 : {b}   （参照 {B_PREV}，"
          f"差 {b - B_PREV} —— 日志是滚动的，差不为 0 正常）")
    print(f"     时间跨度                 : {t_first}  →  {t_last}")
    print(f"     组5 路径前缀分布         : {pre_kind}")
    print(f"     组5 落在农场根下         : {farm_lines}"
          f"   ← ★ 这一格恒为 0 时，下面那个 0 覆盖不到农场防线")
    print(f"     组5 是原路径             : {orig_lines}")
    print(f"  c  in_pack（真归到单片）    : {c}")
    print(f"     归到单片的不同片子数     : {len(hit_dirs)}   最多: "
          f"{sorted(hit_dirs.items(), key=lambda kv: -kv[1])[:5]}")
    print()
    print(f"  ★ b − c                     : {b - c}   （= other_pack + unresolved）")
    for k in ("other_pack", "unresolved", "in_pack"):
        print(f"       {k:<12} {belong_n.get(k, 0)}")
    for k, v in samples.items():
        if k != "in_pack":
            print(f"       ── {k} 样本 ──")
            for s in v:
                print(f"          {s}")

    if ok and c == 0:
        print()
        print("★ 控制②失败：c=0，但控制①证明解析链是通的 —— "
              "0 说明的是**日志里的路径一条都不是本库的路径**，不是干净")
        ok = False
    print()
    print("✓ 控制全过 —— 上面的数可信" if ok else "★ 控制没过：不要把这些数当结论")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

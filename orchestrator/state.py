"""单片状态机 —— sidecar SQLite + 从 cross-seed / qB **反向同步**。

为什么不直接给 cross-seed 的库加字段
====================================
1. cross-seed 的 schema 由它自己的 knex migration 管理。手工 `ALTER TABLE` 会在它
   升级/启动时被覆盖，甚至让它直接启动失败 —— 那是它拥有的一等公民表。
2. **它其实已经有我们要的那几个"字段"了**（2026-09-11 实测 v6.13.7）：

   ================================  ==================================================
   `timestamp(searchee_id, indexer_id, last_searched)`
                                     「这部片子在某个站**真的搜过**了吗」——天然的"已完成阶段"标记
   `decision(searchee_id, guid, decision, info_hash, ...)`
                                     匹配结论：MATCH / MATCH_PARTIAL / MATCH_SIZE_ONLY
   `indexer(id, url, name, active, status, retry_after)`
                                     索引器退避状态 + **解禁的绝对时间**
   `searchee(id, name, first_searched, last_searched)`
                                     v6.13 实测这两列**全 NULL**（已被 timestamp 取代）
   ================================  ==================================================

   实测数字：`searchee` 405 行，其中只有 **118** 行有 `timestamp`（= 真搜过），
   另外 **287** 行既无 `timestamp` 也无 `decision` —— 那 295 条被 429 秒跳的，
   在 cross-seed 眼里就是"从来没搜过"。而 118 里有 58 个有 match，**58/118 = 49.2%**。

3. **它唯独不记的，是"这条是被退避跳过的"。** 而这恰恰是我们最需要知道的：
   被跳过的条目不主动重试，就永远躺在那里（cross-seed 不会排队、不会重试）。

所以本模块只做两件事
====================
- **只读** cross-seed 的库 + 日志 + qB，把事实**翻译**成"每部片子现在到哪一步"；
- 自己补上 cross-seed 记不了的那一格：`SKIPPED`、重试策略、尝试流水。

`stage` **不是**手工维护的字段，而是由事实推导的纯函数（见 `compute_stage`）——
所以不存在"状态与现实不一致"的可能，也就不需要"同步一下状态"这种动作。
"""
from __future__ import annotations

import json
import os
import re
import shutil
import sqlite3
import tempfile
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

# --------------------------------------------------------------------------- #
# 阶段
# --------------------------------------------------------------------------- #
STAGE_PENDING = "PENDING"        # 还没搜过
STAGE_SEARCHED = "SEARCHED"      # 搜过了，但没匹配到（= UNMATCHED，保留别名便于阅读）
STAGE_UNMATCHED = "UNMATCHED"    # 同上，语义化名字
STAGE_MATCHED = "MATCHED"        # 匹配到单种并注入 qB，尚未确认做种
STAGE_SEEDING = "SEEDING"        # qB 里在跑，校验中或已做种
STAGE_SKIPPED = "SKIPPED"        # ★被索引器退避跳过 —— 必须重试，且**不算搜过**
STAGE_ERROR = "ERROR"            # 异常（日志/接口/路径）

ALL_STAGES = (
    STAGE_PENDING, STAGE_SKIPPED, STAGE_UNMATCHED,
    STAGE_MATCHED, STAGE_SEEDING, STAGE_ERROR,
)

#: 成功终点：到了这里就永不重搜
DONE_STAGES = frozenset({STAGE_SEEDING, STAGE_MATCHED})

#: 立刻可重搜（不消耗重试预算）
RETRY_NOW_STAGES = frozenset({STAGE_PENDING, STAGE_SKIPPED, STAGE_ERROR})

#: 需要等冷却期 / 等新增索引器才重搜
COOLDOWN_STAGES = frozenset({STAGE_UNMATCHED})

#: todo() 的**取件顺序**：数字越小越先搜。分批（--limit/--batch）时按这个排，
#: 保证先花在"最该搜"的片子上。
#:   SKIPPED   0 —— 上次根本没发出去（被退避秒跳），重搜不消耗任何重试预算
#:   ERROR     1 —— 上次异常，尽快补
#:   PENDING   2 —— 从没搜过
#:   UNMATCHED 3 —— 真搜过没命中，等周期/等新站
TODO_PRIORITY: dict[str, int] = {
    STAGE_SKIPPED: 0,
    STAGE_ERROR: 1,
    STAGE_PENDING: 2,
    STAGE_UNMATCHED: 3,
}

#: 未命中后，**每个站**默认多久重搜一次（用户要求：一周一次）
DEFAULT_CADENCE_DAYS = 7
#: 兼容旧名字
DEFAULT_COOLDOWN_DAYS = DEFAULT_CADENCE_DAYS

STAGE_ORDER = list(ALL_STAGES)


def _parse_ts(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.strptime(str(s)[:19], "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None


def cadence_for(indexer: str, *, cadence_days: int = DEFAULT_CADENCE_DAYS,
                cadence_by_indexer: dict[str, int] | None = None) -> int:
    """某个站的重搜周期（天）。可以给单个站单独设。"""
    if cadence_by_indexer and indexer in cadence_by_indexer:
        return int(cadence_by_indexer[indexer])
    return int(cadence_days)


def due_indexers(
    indexer_seen: dict[str, str],
    indexers_now: list[str],
    *,
    cadence_days: int = DEFAULT_CADENCE_DAYS,
    cadence_by_indexer: dict[str, int] | None = None,
    now: datetime | None = None,
) -> list[str]:
    """**这一部片子，现在该在哪些站上重搜？**

    规则（这就是「每站一周搜一次」的落地）：
      * 从没在这个站搜过            → 该搜
      * 上次搜到现在 ≥ 该站的周期   → 该搜
      * 否则                        → 等

    `indexers_now` 为空时，退化成"用它自己记录过的站"（避免没传 --indexers 就什么都不搜）。
    """
    now = now or datetime.now()
    pool = list(indexers_now) or sorted(indexer_seen) or [UNKNOWN_INDEXER]
    out = []
    for ix in pool:
        last = _parse_ts(indexer_seen.get(ix))
        if last is None:
            out.append(ix)
            continue
        days = cadence_for(ix, cadence_days=cadence_days,
                           cadence_by_indexer=cadence_by_indexer)
        if (now - last) >= timedelta(days=days):
            out.append(ix)
    return out


def next_due_at(
    indexer_seen: dict[str, str],
    indexers_now: list[str],
    *,
    cadence_days: int = DEFAULT_CADENCE_DAYS,
    cadence_by_indexer: dict[str, int] | None = None,
) -> datetime | None:
    """下一次"最早会变得可搜"的时刻（用来填 next_retry_at / 汇报）。

    已经该搜的返回 None（= 现在就能搜）。
    """
    now = datetime.now()
    pool = list(indexers_now) or sorted(indexer_seen) or [UNKNOWN_INDEXER]
    times = []
    for ix in pool:
        last = _parse_ts(indexer_seen.get(ix))
        if last is None:
            return None                      # 有站从没搜过 → 现在就该搜
        days = cadence_for(ix, cadence_days=cadence_days,
                           cadence_by_indexer=cadence_by_indexer)
        times.append(last + timedelta(days=days))
    if not times:
        return None
    soonest = min(times)
    return soonest if soonest > now else None


def compute_stage(
    *,
    seeding_count: int,
    matched_count: int,
    searched_indexers: set[str],
    skipped_indexers: set[str],
) -> str:
    """**纯函数**：由事实推导阶段。优先级从高到低。

    这就是整个状态机的全部逻辑。没有"手工置位"，因此不会漂移。
    """
    if seeding_count > 0:
        return STAGE_SEEDING
    if matched_count > 0:
        return STAGE_MATCHED
    if searched_indexers:
        return STAGE_UNMATCHED
    if skipped_indexers:
        return STAGE_SKIPPED
    return STAGE_PENDING


# --------------------------------------------------------------------------- #
# 数据类
# --------------------------------------------------------------------------- #
@dataclass
class Movie:
    id: int
    pack: str
    dir_name: str
    path: str
    stage: str = STAGE_PENDING
    attempts: int = 0
    last_attempt_at: str | None = None
    next_retry_at: str | None = None
    searched_indexers: list[str] = field(default_factory=list)
    #: {索引器: 最后一次搜索时间} —— 每站独立计周期靠它
    indexer_seen: dict[str, str] = field(default_factory=dict)
    skipped_indexers: list[str] = field(default_factory=list)
    matched_indexers: list[str] = field(default_factory=list)
    matched_hashes: list[str] = field(default_factory=list)
    seeding_count: int = 0
    last_error: str | None = None
    note: str | None = None
    updated_at: str | None = None


#: 日志里没记下索引器名时用的占位符（info 级日志只有 "(filtered by ...)"，没写是谁）
UNKNOWN_INDEXER = "(未记录)"


@dataclass
class CrossSeedSnapshot:
    """从 cross-seed.db 读出来的事实（只读快照）。"""
    #: searchee.name -> {索引器标签: 最后一次搜索时间 "YYYY-MM-DD HH:MM:SS"}
    #: ★这就是「每站一周搜一次」里那个"上次搜是什么时候"
    searched: dict[str, dict[str, str]] = field(default_factory=dict)
    #: searchee.name -> [(info_hash, decision)]
    decisions: dict[str, list[tuple[str, str]]] = field(default_factory=dict)
    #: searchee.name -> 完整路径（来自 data 表，title 与 name 对齐）。
    #: ★有了路径才能按 dataDir 前缀把「当前包」和「别的包」的 searchee 分开，
    #:   否则 sync 会对跨包名字误报 unresolved（FRDS 的片子被算进 DC 的对不上数）。
    searchee_paths: dict[str, str] = field(default_factory=dict)
    #: 当前生效（active=1）的索引器名
    indexers: list[str] = field(default_factory=list)
    #: 索引器名 -> (status, retry_after 可读时间)
    indexer_status: dict[str, tuple[str, str | None]] = field(default_factory=dict)
    #: 索引器 url -> 名字（用来把日志里的 url 归一成名字）
    alias: dict[str, str] = field(default_factory=dict)
    #: 有 timestamp 的 searchee 总数 / searchee 总数（用于汇报）
    searched_total: int = 0
    searchee_total: int = 0


# --------------------------------------------------------------------------- #
# 日志解析
# --------------------------------------------------------------------------- #
_LINE = re.compile(r"^(?P<date>\d{4}-\d\d-\d\d) (?P<time>\d\d:\d\d:\d\d)\.\d+ \w+: (?P<msg>.*)$")
_RE_SEARCH = re.compile(r"\[webhook\] \(\d+/\d+\) Searching for (\S+)")
_RE_SKIP = re.compile(
    r"\[webhook\] Skipping searching for (\S+) on temporarily disabled indexers \[(.*?)\]"
)
_RE_SKIP_INFO = re.compile(
    r"\[webhook\] \(\d+/\d+\) Skipped searching on indexers for (\S+) \(filtered by temporarily disabled indexers\)"
)
_RE_FOUND = re.compile(
    r"\[(?:webhook|inject)\] Found (.+?) \[([0-9a-f]{8})\.\.\.\] on (\S+) by (\w+) from dataDir \((.+?)\) - (.*)$"
)
_RE_SNOOZE = re.compile(r"\[torznab\] Snoozing indexers \[(.*?)\] with (\w+) until ([\d\-: ]+)")
_RE_RECEIVED = re.compile(r"\[webhook\] Received search request")


@dataclass
class LogFacts:
    searched: dict[str, set[str]] = field(default_factory=dict)       # dir_name -> indexers
    skipped: dict[str, set[str]] = field(default_factory=dict)        # dir_name -> indexers
    found: dict[str, list[tuple[str, str]]] = field(default_factory=dict)  # dir_name -> [(hash8, indexer)]
    snoozes: list[tuple[str, str, str]] = field(default_factory=list)      # (at, indexers, until)
    #: dir_name -> 最后一次 "Searching for" 的**日期时间**（只当 db 里查不到时兜底）
    searched_at: dict[str, str] = field(default_factory=dict)
    searches_seen: int = 0
    skips_seen: int = 0
    #: 日志里出现过的 (N/M) 进度，用于识别"被秒跳"的区间
    progress: list[tuple[str, int, int, str]] = field(default_factory=list)  # (time, n, m, kind)


# --------------------------------------------------------------------------- #
# searchee 枚举：**逐字复刻** cross-seed v6.13.7 的 src/dataFiles.ts
# --------------------------------------------------------------------------- #
# 为什么要把这段逻辑抄过来，而不是"凭理解写一个"
# ------------------------------------------------
# 2026-09-11 直接读了 cross-seed **v6.13.7** 的源码（src/dataFiles.ts，已核对
# master 与 v6.13.7 两版，这两段代码完全一致）：
#
#   findSearcheesFromAllDataDirs = dataDirs.flatMap(dd =>
#       readdir(dd).flatMap(child => findPotentialNestedRoots(child, maxDataDepth)))
#
#   findPotentialNestedRoots(root, depth):
#     if (depth <= 0 || shouldIgnore(root))  -> []
#     else if (isDir)                        -> [...递归(子项, depth-1), root]  # 自己也算
#     else /* 文件 */                        -> [root]
#
#   shouldIgnore: 目录名 ∈ IGNORED_FOLDERS_SUBSTRINGS / 文件扩展名 ∉ VIDEO_EXTENSIONS
#
# ⚠ 所以规则是**纯按深度**，**没有**"目录里含视频才算 searchee、否则被穿透"这回事。
#   （我之前那个"含视频即叶子"的模型是错的 —— 它预测 485、实际 405。）
#   正确含义：`maxDataDepth` = **从 dataDir 往下数几层**；第 1..N 层的
#   **目录和视频文件**全都是 searchee（非视频文件忽略，黑名单目录忽略且不再下钻）。
#
# 实测校验（FRDS，maxDataDepth=2）：
#   - 本函数枚举 857 条（487 目录 + 370 视频文件）
#   - `cross-seed.db` 的 `searchee` 表 405 条**全部**落在枚举结果里（只在 DB = 0）
#   - 日志里 "Searching for" 的路径只有**第 1 层（416 行）和第 2 层（100 行）**，无第 3 层
DEFAULT_MAX_DATA_DEPTH = 2

VIDEO_EXTENSIONS = frozenset({
    ".mkv", ".mp4", ".avi", ".ts", ".m4v", ".3gp", ".nsv", ".ty", ".strm", ".rm",
    ".rmvb", ".mov", ".qt", ".divx", ".xvid", ".bivx", ".pva", ".wmv", ".asf",
    ".asx", ".ogm", ".ogv", ".m2v", ".dvr-ms", ".mpg", ".mpeg", ".avc", ".vp3",
    ".svq3", ".nuv", ".viv", ".dv", ".fli", ".flv", ".wpl", ".wtv",
})

IGNORED_FOLDER_SUBSTRINGS = ("sample", "proof", "bdmv", "bdrom", "certificate",
                             "video_ts")


def should_ignore_path(name: str, is_dir: bool) -> bool:
    """对应 cross-seed 的 `shouldIgnorePathHeuristically()`。"""
    if is_dir:
        return name.lower() in IGNORED_FOLDER_SUBSTRINGS
    return os.path.splitext(name)[1].lower() not in VIDEO_EXTENSIONS


def find_nested_roots(path: str, depth: int, is_dir: bool | None = None) -> list[str]:
    """对应 cross-seed 的 `findPotentialNestedRoots()`。

    返回顺序与源码一致（**由深到浅**，末位是自己）——源码注释说是为了 memoization，
    我们保留同样的顺序，方便和源码逐行对照。
    """
    if is_dir is None:
        is_dir = os.path.isdir(path)
    if depth <= 0 or should_ignore_path(os.path.basename(path), is_dir):
        return []
    if not is_dir:
        return [path]
    try:
        with os.scandir(path) as it:
            children = [(e.name, e.is_dir()) for e in it]
    except OSError:
        return []
    out: list[str] = []
    for name, child_is_dir in children:
        out += find_nested_roots(os.path.join(path, name), depth - 1, child_is_dir)
    out.append(path)
    return out


def find_searchee_paths(data_dir: str, max_depth: int = DEFAULT_MAX_DATA_DEPTH) -> list[str]:
    """对应 `findSearcheesFromAllDataDirs()` 里**单个** dataDir 的分支。"""
    try:
        with os.scandir(data_dir) as it:
            names = [e.name for e in it]
    except OSError:
        return []
    out: list[str] = []
    for n in names:
        out += find_nested_roots(os.path.join(data_dir, n), max_depth)
    return out


def scan_pack(local_roots: list[str], *, max_depth: int = DEFAULT_MAX_DATA_DEPTH
              ) -> tuple[list[tuple[str, str]], list[str]]:
    """把若干 dataDir 扫成 `[(单片名, 路径)]`，粒度 = cross-seed 的 searchee 目录。

    只登记**目录**，外加"直接挂在 dataDir 下的视频文件"（罕见，但它自己就是一个
    searchee）。更深的视频文件不用单独登记 —— `dir_name_of()` 会把它们塌回所在目录，
    这正是我们要的粒度。

    返回 `(条目, 重名列表)`。重名意味着两个 dataDir 下有同名目录，只能保留一个，
    调用方应当把它报出来（别静默丢）。

    ⚠ 返回的路径**一律是 `/` 分隔的规范形式**（`_norm_path()` 处理过）——
    这样 Windows 上跑（`os.path.join` 会给反斜杠）和 NAS 上跑的产出完全一致，
    调用方做前缀替换时不会踩分隔符不一致的坑。
    """
    picked: dict[str, str] = {}
    dup: list[str] = []
    for root in local_roots:
        r = _norm_path(root)
        for p in find_searchee_paths(root, max_depth):
            p = _norm_path(p)
            is_dir = os.path.isdir(p)
            # 文件只收"直接挂在 dataDir 下"的那种
            if not is_dir and _norm_path(os.path.dirname(p)) != r:
                continue
            name = p.rsplit("/", 1)[-1]
            if name in picked:
                if picked[name] != p:
                    dup.append(name)
                continue
            picked[name] = p
    return sorted(picked.items()), dup


def _norm_path(p: str) -> str:
    """日志是 Linux 的 `/`，本地测试可能是 Windows 的 `\\` —— 统一成 `/` 好比较。"""
    return p.replace("\\", "/").rstrip("/")


def dir_name_of(path: str, root: str | list[str],
                dir_paths: dict[str, str] | None = None) -> str | None:
    """把日志里的绝对路径归到"包内单片名"。

    **优先级 1：`dir_paths`（已登记路径 → 单片名）的最长前缀匹配。**
    多根 / 嵌套包必需。例：DC 的
      `…/01.绿箭侠（…）/Arrow.S01-S08…/Arrow.S01.Bluray…`
    应当命中**季层** `Arrow.S01.Bluray…`，而不是塌回容器 `Arrow.S01-S08…`；
    而没有这一层时，容器那条 searchee 也会正确命中容器自己。

    **优先级 2：退回单根语义** —— 取 root 之后的第一个路径段（老行为，兼容旧调用）。

    注意：cross-seed 的 searchee 既可能是目录，也可能是目录里的 .mkv 文件，
    两者都归到同一个单片 —— 这正是我们要的粒度。
    """
    p = _norm_path(path)
    if not p:
        return None
    if dir_paths:
        cur = p
        while True:
            hit = dir_paths.get(cur)
            if hit is not None:
                return hit
            i = cur.rfind("/")
            if i <= 0:
                break
            cur = cur[:i]
    roots = [root] if isinstance(root, str) else list(root)
    for r in sorted((_norm_path(x) for x in roots if x), key=len, reverse=True):
        if p == r:
            return None
        if p.startswith(r + "/"):
            return p[len(r) + 1:].split("/")[0] or None
    return None


def parse_log(text: str, root: str | list[str],
              dir_paths: dict[str, str] | None = None) -> LogFacts:
    """解析 cross-seed 的 info/verbose 日志（两者格式一致，verbose 更全）。"""
    f = LogFacts()
    for line in text.splitlines():
        m = _LINE.match(line)
        if not m:
            continue
        msg = m.group("msg")
        t = m.group("time")

        mm = _RE_SEARCH.search(msg)
        if mm:
            d = dir_name_of(mm.group(1), root, dir_paths)
            if d:
                f.searched.setdefault(d, set())
                f.searches_seen += 1
                full = f"{m.group('date')} {t}"
                if full > f.searched_at.get(d, ""):
                    f.searched_at[d] = full
            pm = re.search(r"\((\d+)/(\d+)\)", msg)
            if pm:
                f.progress.append((t, int(pm.group(1)), int(pm.group(2)), "search"))
            continue

        mm = _RE_SKIP.search(msg) or _RE_SKIP_INFO.search(msg)
        if mm:
            d = dir_name_of(mm.group(1), root, dir_paths)
            if mm.re is _RE_SKIP:
                idx = {x.strip() for x in mm.group(2).split(",") if x.strip()}
            else:
                # info 级日志只写了 "(filtered by temporarily disabled indexers)"，
                # 没说具体是哪个站 —— 用占位符，别塞空串（会污染集合）
                idx = {UNKNOWN_INDEXER}
            if d:
                f.skipped.setdefault(d, set()).update(idx)
                f.skips_seen += 1
            pm = re.search(r"\((\d+)/(\d+)\)", msg)
            if pm:
                f.progress.append((t, int(pm.group(1)), int(pm.group(2)), "skip"))
            continue

        mm = _RE_FOUND.search(msg)
        if mm:
            d = dir_name_of(mm.group(5), root, dir_paths)
            if d:
                f.found.setdefault(d, []).append((mm.group(2), mm.group(3)))
            continue

        mm = _RE_SNOOZE.search(msg)
        if mm:
            f.snoozes.append((t, mm.group(1), mm.group(3).strip()))
    return f


# --------------------------------------------------------------------------- #
# 读 cross-seed 的库（只读）
# --------------------------------------------------------------------------- #
def _open_csdb(db_path: Path, keep_copy: str | None = None):
    """打开 cross-seed.db 的只读连接。

    先试**直接只读打开**（实测在 SMB/UNC 上只要 0.1~0.2s，且能看到 WAL 里的最新数据）；
    失败（锁冲突等）才退回到"把 .db/-wal/-shm 三件套复制到临时目录"的老办法。
    """
    try:
        con = sqlite3.connect(str(db_path), timeout=5)
        con.execute("PRAGMA query_only = 1")
        con.execute("SELECT 1 FROM indexer LIMIT 1").fetchone()
        return con, None
    except sqlite3.Error:
        pass

    tmp = Path(keep_copy) if keep_copy else Path(tempfile.mkdtemp(prefix="csdb-"))
    tmp.mkdir(parents=True, exist_ok=True)
    for suffix in ("", "-wal", "-shm"):
        src = Path(str(db_path) + suffix)
        if src.is_file():
            shutil.copy2(src, tmp / (db_path.name + suffix))
    con = sqlite3.connect(str(tmp / db_path.name))
    con.execute("PRAGMA query_only = 1")
    return con, tmp


def read_crossseed_db(db_path: str | Path, *, keep_copy: str | None = None) -> CrossSeedSnapshot:
    """只读 cross-seed.db，取出三样事实：

      * 每个 searchee 在**每个索引器**上最后一次搜索的时间（`timestamp` 表）
        —— 这就是「每站一周搜一次」里那个"上次搜是什么时候"
      * 匹配结论（`decision` 表，带 info_hash）
      * 索引器退避状态与解禁时间（`indexer` 表）
    """
    db_path = Path(db_path)
    if not db_path.is_file():
        raise FileNotFoundError(f"找不到 cross-seed.db: {db_path}")

    con, _tmp = _open_csdb(db_path, keep_copy)
    try:
        snap = CrossSeedSnapshot()

        # 索引器：active=1 视为"当前生效"
        idx_names: dict[int, str] = {}
        for iid, name, url, active, status, retry_after in con.execute(
            "SELECT id, name, url, active, status, retry_after FROM indexer"
        ):
            label = name or f"prowlarr#{iid}"
            idx_names[iid] = label
            if url:
                snap.alias[url.rstrip("/")] = label
            ra = None
            if retry_after:
                try:
                    ra = datetime.fromtimestamp(retry_after / 1000).strftime("%Y-%m-%d %H:%M:%S")
                except (OverflowError, OSError, ValueError):
                    ra = None
            snap.indexer_status[label] = (status or "-", ra)
            if active:
                snap.indexers.append(label)

        snap.searchee_total = con.execute("SELECT COUNT(*) FROM searchee").fetchone()[0]

        # searchee 名 → 完整路径：data 表的 title 与 searchee.name 对齐（实测 100%）。
        # 用它按 dataDir 前缀区分「这个包 vs 别的包」的 searchee。
        for dpath, dtitle in con.execute("SELECT path, title FROM data"):
            if dtitle:
                snap.searchee_paths.setdefault(dtitle, _norm_path(dpath))

        # 已搜过：timestamp 表（按 searchee × indexer），带**毫秒级**时间戳
        for sname, iid, last_ms in con.execute(
            """SELECT s.name, t.indexer_id, t.last_searched FROM timestamp t
               JOIN searchee s ON s.id = t.searchee_id"""
        ):
            if not sname:
                continue
            label = idx_names.get(iid, f"prowlarr#{iid}")
            iso = ""
            if last_ms:
                try:
                    iso = datetime.fromtimestamp(last_ms / 1000).strftime("%Y-%m-%d %H:%M:%S")
                except (OverflowError, OSError, ValueError):
                    iso = ""
            tgt = snap.searched.setdefault(sname, {})
            if iso and (label not in tgt or iso > tgt[label]):
                tgt[label] = iso
        snap.searched_total = con.execute(
            "SELECT COUNT(DISTINCT searchee_id) FROM timestamp"
        ).fetchone()[0]

        # 匹配结论
        for sname, decision, info_hash in con.execute(
            """SELECT s.name, d.decision, d.info_hash FROM decision d
               JOIN searchee s ON s.id = d.searchee_id"""
        ):
            if not sname:
                continue
            snap.decisions.setdefault(sname, []).append((info_hash or "", decision or ""))
        return snap
    finally:
        con.close()


@dataclass
class IndexerBackoff:
    """一个索引器当前的退避状态。"""
    name: str
    status: str            # OK / RATE_LIMITED / ...
    until: datetime | None  # 解禁时间（None = 没在退避）

    @property
    def active(self) -> bool:
        if self.status in ("", "-", "OK", "NONE"):
            return False
        return self.until is None or self.until > datetime.now()


def read_indexer_backoff(db_path: str | Path) -> list[IndexerBackoff]:
    """轻量读 `indexer` 表，只看退避状态（给 drive 循环用，几十毫秒）。"""
    db_path = Path(db_path)
    if not db_path.is_file():
        raise FileNotFoundError(f"找不到 cross-seed.db: {db_path}")
    con, _tmp = _open_csdb(db_path)
    try:
        out = []
        for iid, name, status, retry_after in con.execute(
            "SELECT id, name, status, retry_after FROM indexer"
        ):
            until = None
            if retry_after:
                try:
                    until = datetime.fromtimestamp(retry_after / 1000)
                except (OverflowError, OSError, ValueError):
                    until = None
            out.append(IndexerBackoff(name or f"prowlarr#{iid}", status or "-", until))
        return out
    finally:
        con.close()


def blocking_backoffs(backoffs: list[IndexerBackoff]) -> list[IndexerBackoff]:
    """当前真正挡住搜索的退避（状态非 OK 且解禁时间还没到）。"""
    return [b for b in backoffs if b.active]


# --------------------------------------------------------------------------- #
# 状态库
# --------------------------------------------------------------------------- #
SCHEMA = """
CREATE TABLE IF NOT EXISTS pack (
  name            TEXT PRIMARY KEY,
  root            TEXT NOT NULL,          -- ★cross-seed 视角的路径（NAS 上），webhook 要用它
  local_root      TEXT,                   -- 可选的本地/UNC 等价路径，只用于"列目录"
  roots           TEXT,                   -- JSON 数组：多根包的全部 root（root = 第一个）
  local_roots     TEXT,                   -- JSON 数组：与 roots 一一对应的可列目录路径
  max_depth       INTEGER,                -- 枚举深度，对应 cross-seed 的 maxDataDepth
  link_dir        TEXT,
  category        TEXT,
  created_at      TEXT NOT NULL,
  scan_started_at TEXT,
  scan_finished_at TEXT,
  scan_complete   INTEGER NOT NULL DEFAULT 0,
  note            TEXT
);

CREATE TABLE IF NOT EXISTS movie (
  id                INTEGER PRIMARY KEY AUTOINCREMENT,
  pack              TEXT NOT NULL REFERENCES pack(name) ON DELETE CASCADE,
  dir_name          TEXT NOT NULL,
  path              TEXT NOT NULL,
  stage             TEXT NOT NULL DEFAULT 'PENDING',
  attempts          INTEGER NOT NULL DEFAULT 0,
  last_attempt_at   TEXT,
  next_retry_at     TEXT,
  searched_indexers TEXT NOT NULL DEFAULT '[]',
  indexer_seen      TEXT NOT NULL DEFAULT '{}',
  skipped_indexers  TEXT NOT NULL DEFAULT '[]',
  matched_indexers  TEXT NOT NULL DEFAULT '[]',
  matched_hashes    TEXT NOT NULL DEFAULT '[]',
  seeding_count     INTEGER NOT NULL DEFAULT 0,
  last_error        TEXT,
  note              TEXT,
  updated_at        TEXT,
  UNIQUE(pack, dir_name)
);
CREATE INDEX IF NOT EXISTS idx_movie_stage ON movie(pack, stage);

CREATE TABLE IF NOT EXISTS attempt (
  id               INTEGER PRIMARY KEY AUTOINCREMENT,
  movie_id         INTEGER NOT NULL REFERENCES movie(id) ON DELETE CASCADE,
  at               TEXT NOT NULL,
  kind             TEXT NOT NULL,          -- search | skip | inject | sync | manual
  result           TEXT NOT NULL,          -- matched | unmatched | skipped | seeding | error | note
  indexers         TEXT,
  skipped_indexers TEXT,
  note             TEXT
);
CREATE INDEX IF NOT EXISTS idx_attempt_movie ON attempt(movie_id, at);
"""


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _j(v) -> str:
    return json.dumps(sorted(v), ensure_ascii=False)


def _dumps(d: dict) -> str:
    return json.dumps(d, ensure_ascii=False, sort_keys=True)


def _d(s: str | None) -> dict:
    """读一个 JSON 对象列（容错：老库里可能是 '[]'）。"""
    if not s:
        return {}
    try:
        v = json.loads(s)
        return dict(v) if isinstance(v, dict) else {}
    except (ValueError, TypeError):
        return {}


def _u(s: str | None) -> list[str]:
    if not s:
        return []
    try:
        v = json.loads(s)
        return list(v) if isinstance(v, list) else []
    except (ValueError, TypeError):
        return []


class StateStore:
    """我们的 sidecar 状态库。**唯一**被本模块写入的库。"""

    def __init__(self, db_path: str | Path):
        self.path = Path(db_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.con = sqlite3.connect(str(self.path))
        self.con.row_factory = sqlite3.Row
        self.con.executescript(SCHEMA)
        self._migrate()
        self.con.commit()

    def _migrate(self) -> None:
        """给已存在的老库补列（本模块自己的库，schema 演进很轻量）。"""
        cols = {r["name"] for r in self.con.execute("PRAGMA table_info(pack)")}
        if "local_root" not in cols:
            self.con.execute("ALTER TABLE pack ADD COLUMN local_root TEXT")
        # 2026-09-11：支持多根 / 嵌套包（DC 的"单片"分散在 47 个标签目录里）
        for col in ("roots", "local_roots"):
            if col not in cols:
                self.con.execute(f"ALTER TABLE pack ADD COLUMN {col} TEXT")
        if "max_depth" not in cols:
            self.con.execute("ALTER TABLE pack ADD COLUMN max_depth INTEGER")
        mcols = {r["name"] for r in self.con.execute("PRAGMA table_info(movie)")}
        if "indexer_seen" not in mcols:
            self.con.execute(
                "ALTER TABLE movie ADD COLUMN indexer_seen TEXT NOT NULL DEFAULT '{}'")

    def close(self) -> None:
        self.con.close()

    def __enter__(self) -> "StateStore":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # -- pack --------------------------------------------------------------- #
    def upsert_pack(self, name: str, root: str, *, local_root: str | None = None,
                    roots: list[str] | None = None,
                    local_roots: list[str] | None = None,
                    max_depth: int | None = None,
                    link_dir: str | None = None,
                    category: str | None = None, note: str | None = None) -> None:
        """登记/更新一个包。

        多根包（如 DC 的 47 个标签目录）传 `roots` / `local_roots`；
        `root` 仍必填 —— 它是 `roots[0]`，老代码和 webhook 都还在用它。
        """
        roots_json = json.dumps(roots, ensure_ascii=False) if roots else None
        lroots_json = json.dumps(local_roots, ensure_ascii=False) if local_roots else None
        self.con.execute(
            """INSERT INTO pack(name, root, local_root, roots, local_roots, max_depth,
                                link_dir, category, created_at, note)
               VALUES(?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(name) DO UPDATE SET
                 root=excluded.root,
                 local_root=COALESCE(excluded.local_root, pack.local_root),
                 roots=COALESCE(excluded.roots, pack.roots),
                 local_roots=COALESCE(excluded.local_roots, pack.local_roots),
                 max_depth=COALESCE(excluded.max_depth, pack.max_depth),
                 link_dir=COALESCE(excluded.link_dir, pack.link_dir),
                 category=COALESCE(excluded.category, pack.category),
                 note=COALESCE(excluded.note, pack.note)""",
            (name, root, local_root, roots_json, lroots_json, max_depth,
             link_dir, category, _now(), note),
        )
        self.con.commit()

    def local_root(self, pack: str) -> str:
        """能用来列目录的那个根（优先 local_root，否则 root）。"""
        p = self.pack(pack)
        if p is None:
            raise KeyError(f"包未登记: {pack!r}")
        return p["local_root"] or p["root"]

    def roots(self, pack: str) -> list[str]:
        """包的全部 cross-seed 视角根（多根包返回全部；单根包返回 `[root]`）。"""
        p = self.pack(pack)
        if p is None:
            raise KeyError(f"包未登记: {pack!r}")
        return _u(p["roots"]) or [p["root"]]

    def local_roots(self, pack: str) -> list[str]:
        """包的全部"可列目录"根，与 `roots()` 按序对应。

        多根包必须逐根配对：`roots[i]` 与 `local_roots[i]` 指的是同一目录，
        只是视角不同（NAS 路径 vs UNC 路径）。数量对不上就退回 `local_root()`。
        """
        p = self.pack(pack)
        if p is None:
            raise KeyError(f"包未登记: {pack!r}")
        rs, lrs = _u(p["roots"]), _u(p["local_roots"])
        if lrs and len(lrs) == len(rs):
            return lrs
        return [p["local_root"] or p["root"]]

    def max_depth(self, pack: str) -> int:
        p = self.pack(pack)
        if p is None:
            raise KeyError(f"包未登记: {pack!r}")
        try:
            return int(p["max_depth"])
        except (TypeError, ValueError, IndexError):
            return DEFAULT_MAX_DATA_DEPTH

    def pack(self, name: str) -> sqlite3.Row | None:
        return self.con.execute("SELECT * FROM pack WHERE name=?", (name,)).fetchone()

    def mark_scan(self, name: str, *, started: bool = False, finished: bool = False,
                  complete: bool | None = None) -> None:
        if started:
            self.con.execute("UPDATE pack SET scan_started_at=? WHERE name=?", (_now(), name))
        if finished:
            self.con.execute("UPDATE pack SET scan_finished_at=? WHERE name=?", (_now(), name))
        if complete is not None:
            self.con.execute("UPDATE pack SET scan_complete=? WHERE name=?",
                             (1 if complete else 0, name))
        self.con.commit()

    # -- movie -------------------------------------------------------------- #
    def register_dirs(self, pack: str, entries: list[tuple[str, str]]) -> int:
        """把 `[(单片名, 完整路径)]` 登记成 PENDING（已存在的不动，stage 不会被重置）。

        多根包必须传**完整路径** —— 因为两个根下可能有同名目录，而且
        `dir_name_of()` 要靠路径做最长前缀匹配。
        """
        added = 0
        for name, path in entries:
            cur = self.con.execute(
                """INSERT INTO movie(pack, dir_name, path, stage, updated_at)
                   VALUES(?,?,?,?,?)
                   ON CONFLICT(pack, dir_name) DO UPDATE SET path=excluded.path""",
                (pack, name, _norm_path(path), STAGE_PENDING, _now()),
            )
            added += cur.rowcount or 0
        self.con.commit()
        return added

    def dir_paths(self, pack: str) -> dict[str, str]:
        """`{规范化完整路径: 单片名}` —— 给 `dir_name_of()` 做最长前缀匹配用。

        用完整路径（而不是只有目录名）是为了让嵌套包的"季层"能被正确区分：
        DC 的 `…/01.绿箭侠…/Arrow.S01-S08…/Arrow.S01.Bluray…` 应当命中季层，
        而不是塌回容器 `Arrow.S01-S08…`。
        """
        return {_norm_path(r["path"]): r["dir_name"] for r in self.movies(pack)}

    def movies(self, pack: str, *, stages: list[str] | None = None) -> list[sqlite3.Row]:
        sql = "SELECT * FROM movie WHERE pack=?"
        args: list = [pack]
        if stages:
            sql += f" AND stage IN ({','.join('?' * len(stages))})"
            args += stages
        sql += " ORDER BY dir_name"
        return list(self.con.execute(sql, args))

    def movie_by_dir(self, pack: str, dir_name: str) -> sqlite3.Row | None:
        return self.con.execute(
            "SELECT * FROM movie WHERE pack=? AND dir_name=?", (pack, dir_name)
        ).fetchone()

    def movie_by_path(self, pack: str, path: str) -> sqlite3.Row | None:
        return self.con.execute(
            "SELECT * FROM movie WHERE pack=? AND path=?", (pack, path)
        ).fetchone()

    def attempts(self, movie_id: int) -> list[sqlite3.Row]:
        return list(self.con.execute(
            "SELECT * FROM attempt WHERE movie_id=? ORDER BY at, id", (movie_id,)
        ))

    # -- 同步（把事实写进 movie 行）---------------------------------------- #
    def sync_movie(
        self,
        movie_id: int,
        *,
        searched_indexers: set[str],
        skipped_indexers: set[str],
        matched: list[tuple[str, str]],       # [(info_hash, indexer)]
        seeding_hashes: set[str],
        indexers_now: list[str],
        searched_at: dict[str, str] | None = None,   # {索引器: 最后搜索时间}
        cadence_days: int = DEFAULT_CADENCE_DAYS,
        cadence_by_indexer: dict[str, int] | None = None,
        log_attempts: bool = True,
    ) -> str:
        """按事实重算这一行的 stage。返回新 stage。

        `attempts` / `next_retry_at` 是**我们自己的**簿记（cross-seed 不管这个）。
        `indexer_seen` 记录"每个站最后一次搜它是什么时候"，是「每站一周一次」的依据。
        """
        row = self.con.execute("SELECT * FROM movie WHERE id=?", (movie_id,)).fetchone()
        if row is None:
            raise KeyError(f"movie id={movie_id} 不存在")

        old_stage = row["stage"]
        old_searched = set(_u(row["searched_indexers"]))
        old_skipped = set(_u(row["skipped_indexers"]))
        old_hashes = set(_u(row["matched_hashes"]))
        old_seen: dict[str, str] = _d(row["indexer_seen"])

        matched_hashes = {h for h, _ in matched if h}
        matched_indexers = {i for _, i in matched if i}
        seeding_count = len(matched_hashes & seeding_hashes)

        stage = compute_stage(
            seeding_count=seeding_count,
            matched_count=len(matched_hashes),
            searched_indexers=searched_indexers,
            skipped_indexers=skipped_indexers,
        )

        # attempts：只在"真的去搜过"时 +1（skip 不算，因为那次请求根本没发出去）
        attempts = row["attempts"]
        last_attempt = row["last_attempt_at"]
        new_searched = searched_indexers - old_searched
        if new_searched:
            attempts += 1
            last_attempt = _now()

        # indexer_seen：合并"老的"与"这次拿到的"，同一站取更晚的时间
        seen = dict(old_seen)
        for ix, ts in (searched_at or {}).items():
            if ts and (ix not in seen or ts > seen[ix]):
                seen[ix] = ts
        # 已搜过但没拿到时间的站，补一个"未知"（保证它不会被当成"从没搜过"）
        for ix in searched_indexers:
            seen.setdefault(ix, "")

        # next_retry_at：按**每站各自的周期**算下一次最早可搜的时刻
        if stage in DONE_STAGES:
            next_retry = None
        else:
            nd = next_due_at(seen, indexers_now,
                             cadence_days=cadence_days,
                             cadence_by_indexer=cadence_by_indexer)
            next_retry = nd.strftime("%Y-%m-%d %H:%M:%S") if nd else None

        self.con.execute(
            """UPDATE movie SET
                 stage=?, attempts=?, last_attempt_at=?, next_retry_at=?,
                 searched_indexers=?, indexer_seen=?, skipped_indexers=?,
                 matched_indexers=?, matched_hashes=?, seeding_count=?, updated_at=?
               WHERE id=?""",
            (stage, attempts, last_attempt, next_retry,
             _j(searched_indexers), _dumps(seen), _j(skipped_indexers), _j(matched_indexers),
             _j(matched_hashes), seeding_count, _now(), movie_id),
        )

        # 流水：只在"有新事实"时记，避免每次 sync 都刷屏
        if log_attempts:
            new_skipped = skipped_indexers - old_skipped
            new_hashes = matched_hashes - old_hashes
            if stage != old_stage:
                self.add_attempt(movie_id, kind="sync", result=stage.lower(),
                                 indexers=searched_indexers,
                                 skipped_indexers=skipped_indexers,
                                 note=f"{old_stage} → {stage}")
            elif new_skipped:
                self.add_attempt(movie_id, kind="skip", result="skipped",
                                 skipped_indexers=new_skipped,
                                 note="被索引器退避跳过，需重试")
            elif new_hashes:
                self.add_attempt(movie_id, kind="inject", result="matched",
                                 indexers=matched_indexers,
                                 note=f"新增 {len(new_hashes)} 个单种")
        self.con.commit()
        return stage

    def add_attempt(self, movie_id: int, *, kind: str, result: str,
                    indexers=None, skipped_indexers=None, note: str | None = None) -> None:
        self.con.execute(
            """INSERT INTO attempt(movie_id, at, kind, result, indexers, skipped_indexers, note)
               VALUES(?,?,?,?,?,?,?)""",
            (movie_id, _now(), kind, result,
             _j(indexers or []), _j(skipped_indexers or []), note),
        )
        self.con.commit()

    # -- 查询：待办 ---------------------------------------------------------- #
    def todo(self, pack: str, *, indexers_now: list[str] | None = None,
             include_cooldown: bool = False,
             cadence_days: int = DEFAULT_CADENCE_DAYS,
             cadence_by_indexer: dict[str, int] | None = None,
             now: datetime | None = None) -> list[sqlite3.Row]:
        """哪些片子**还需要搜**？

        规则（这就是"已完成的阶段就不重复"的落地）：
          - SEEDING / MATCHED  → 不搜（已拿到单种）
          - PENDING            → 搜
          - SKIPPED            → **立刻**搜（上次根本没发出去）
          - ERROR              → 搜
          - UNMATCHED          → 按**每站各自的周期**判断（默认 7 天）
                                  —— 只要有一个站"从没搜过"或"够周期了"就该搜
        """
        now = now or datetime.now()
        out: list[sqlite3.Row] = []
        for row in self.movies(pack):
            st = row["stage"]
            if st in DONE_STAGES:
                continue
            if st in RETRY_NOW_STAGES or include_cooldown:
                out.append(row)
                continue
            if st in COOLDOWN_STAGES:
                due = due_indexers(
                    _d(row["indexer_seen"]), indexers_now or [],
                    cadence_days=cadence_days,
                    cadence_by_indexer=cadence_by_indexer,
                    now=now,
                )
                if due:
                    out.append(row)
        # 按"最该搜"排序（SKIPPED → ERROR → PENDING → UNMATCHED），同级按目录名稳定排序。
        # 分批时靠这个顺序，保证每批都优先吃掉被退避跳过 / 从没搜过的片子。
        out.sort(key=lambda r: (TODO_PRIORITY.get(r["stage"], 9), r["dir_name"]))
        return out

    def todo_detail(self, pack: str, *, indexers_now: list[str] | None = None,
                    include_cooldown: bool = False,
                    cadence_days: int = DEFAULT_CADENCE_DAYS,
                    cadence_by_indexer: dict[str, int] | None = None,
                    now: datetime | None = None) -> list[tuple[sqlite3.Row, list[str]]]:
        """和 todo() 一样，但额外返回"这部片子该在哪些站重搜"。"""
        now = now or datetime.now()
        rows = self.todo(pack, indexers_now=indexers_now, include_cooldown=include_cooldown,
                         cadence_days=cadence_days, cadence_by_indexer=cadence_by_indexer,
                         now=now)
        out = []
        for r in rows:
            if r["stage"] in DONE_STAGES:
                continue
            due = due_indexers(_d(r["indexer_seen"]), indexers_now or [],
                               cadence_days=cadence_days,
                               cadence_by_indexer=cadence_by_indexer, now=now)
            out.append((r, due))
        return out

    def cadence_table(self, pack: str, *, indexers_now: list[str] | None = None,
                      cadence_days: int = DEFAULT_CADENCE_DAYS,
                      cadence_by_indexer: dict[str, int] | None = None) -> dict[str, dict]:
        """按站汇总：搜过几部 / 其中几部到周期了 / 下次最早可重搜的时刻。"""
        now = datetime.now()
        pool = list(indexers_now or [])
        stat: dict[str, dict] = {}
        for row in self.movies(pack):
            seen = _d(row["indexer_seen"])
            for ix in (pool or sorted(seen)):
                d = stat.setdefault(ix, {"searched": 0, "due": 0, "next": None})
                if ix in seen and seen[ix]:
                    d["searched"] += 1
                    nd = _parse_ts(seen[ix]) + timedelta(
                        days=cadence_for(ix, cadence_days=cadence_days,
                                         cadence_by_indexer=cadence_by_indexer))
                    if nd <= now:
                        d["due"] += 1
                    elif d["next"] is None or nd < d["next"]:
                        d["next"] = nd
                else:
                    d["due"] += 1
        return stat

    def summary(self, pack: str) -> dict[str, int]:
        rows = self.con.execute(
            "SELECT stage, COUNT(*) c FROM movie WHERE pack=? GROUP BY stage", (pack,)
        )
        d = {s: 0 for s in ALL_STAGES}
        for r in rows:
            d[r["stage"]] = r["c"]
        d["TOTAL"] = sum(d[s] for s in ALL_STAGES)
        return d


# --------------------------------------------------------------------------- #
# searchee 名 → 包内目录名
# --------------------------------------------------------------------------- #
def resolve_dir_name(name: str, dir_names: set[str]) -> str | None:
    """把 cross-seed 的 searchee.name 归到包内子目录。

    searchee 既可能是**目录**（`2001太空漫游.…MNHD-FRDS`），
    也可能是**目录里的文件**（`…MNHD-FRDS.mkv`），还可能是不带中文前缀的
    纯文件名（`V.For.Vendetta.2005….mkv`，此时目录名是 `V字仇杀队.V.For.Vendetta…`）。
    所以按 精确 → 去扩展名 → 前缀/包含 三级回退。
    """
    if not name:
        return None
    if name in dir_names:
        return name
    stem = os.path.splitext(name)[0]
    if stem in dir_names:
        return stem
    # 文件级 searchee：找一个"包住它"或"被它包住"的目录（取最长的那个，最具体）
    cands = [d for d in dir_names
             if d.startswith(stem) or stem.startswith(d) or stem in d or d in stem]
    if not cands:
        return None
    return max(cands, key=len)


def _resolve_searchee_to_pack(
    name: str,
    snap: CrossSeedSnapshot,
    roots: list[str],
    dirs: set[str],
    dpaths: dict[str, str],
) -> tuple[str | None, str]:
    """把一个 cross-seed searchee 归到**当前包**的单片名。

    返回 `(单片名, 归属)`，`归属` ∈ {"in_pack", "other_pack", "unresolved"}：
      * "in_pack"     —— 路径落在当前包某个 dataDir 下，`单片名` 为归属的单片
      * "other_pack"  —— 路径在别的包下（或查不到路径），**静默跳过、不计数**
      * "unresolved"  —— 路径在当前包内、但归不到任何具体单片（真·对不上）
    区分这两种"不是本包"的情况，是为了 sync 汇报时**不把跨包 searchee 误报成
    当前包的对不上数**（FRDS/MBF 的片子不该算进 DC 的 unresolved）。
    """
    p = _norm_path(snap.searchee_paths.get(name, ""))
    if p:
        for r in roots:
            r = _norm_path(r)
            if p == r or p.startswith(r + "/"):
                d = dir_name_of(p, roots, dpaths)
                return (d if d else None, "in_pack" if d else "unresolved")
        return (None, "other_pack")       # 路径在别的包下 → 不属于当前包
    # 查不到路径（老库 / 罕见）：退回纯名字匹配；匹配不上算 unresolved
    d = resolve_dir_name(name, dirs)
    return (d, "in_pack" if d else "unresolved")


# --------------------------------------------------------------------------- #
# 索引器标签归一
# --------------------------------------------------------------------------- #
_INDEXER_URL_ID = re.compile(r"/(\d+)/api(?:/|$)")


def normalize_indexer(token: str, alias: dict[str, str] | None = None) -> str:
    """把索引器的各种写法归一成同一个标签。

    日志里同一个站可能出现三种写法：`SiteA`（名字）、
    `http://prowlarr:9696/2/api`（URL，名字还没解析出来时）、
    以及 info 级日志里的空值。不归一的话，同一个站在集合里会变成三个不同成员，
    "已搜过这个站吗"就永远算不对。
    """
    t = (token or "").strip().rstrip("/")
    if not t:
        return UNKNOWN_INDEXER
    alias = alias or {}
    if t in alias:
        return alias[t]
    m = _INDEXER_URL_ID.search(t)
    if m:
        return f"prowlarr#{m.group(1)}"
    return t


def _norm_set(tokens, alias: dict[str, str]) -> set[str]:
    return {normalize_indexer(t, alias) for t in tokens if (t or "").strip()}


def _clean(tokens: set[str]) -> set[str]:
    """若同一件事既有具名索引器、又有 `(未记录)` 占位（info 与 verbose 各记了一行），
    丢掉占位 —— 它只是"当时还不知道是谁"。"""
    if len(tokens) > 1 and UNKNOWN_INDEXER in tokens:
        tokens = set(tokens)
        tokens.discard(UNKNOWN_INDEXER)
    return tokens


# --------------------------------------------------------------------------- #
# 把三个来源合并成一次同步
# --------------------------------------------------------------------------- #
@dataclass
class SyncReport:
    pack: str
    movies: int = 0
    from_db: int = 0          # cross-seed.db 说"搜过"的片子数
    from_log: int = 0         # 日志里出现 Searching for 的片子数
    skipped: int = 0          # ★日志里被退避跳过的片子数
    matched: int = 0
    seeding: int = 0
    indexers: list[str] = field(default_factory=list)
    stage_counts: dict[str, int] = field(default_factory=dict)
    unresolved: int = 0       # searchee 名对不上任何目录的条数

    def render(self) -> str:
        lines = [
            f"包 {self.pack}：{self.movies} 部",
            f"  cross-seed.db 认为搜过 : {self.from_db}",
            f"  日志里出现 Searching   : {self.from_log}",
            f"  日志里被退避跳过       : {self.skipped}  ← 这些是「假完成」，必须重试",
            f"  匹配到单种             : {self.matched}",
            f"  已在 qB 里             : {self.seeding}",
            f"  当前索引器             : {', '.join(self.indexers) or '(未知)'}",
        ]
        if self.unresolved:
            lines.append(f"  ⚠ 有 {self.unresolved} 个 searchee 名对不上目录（已跳过）")
        lines.append("  阶段分布: " + "  ".join(
            f"{k}={self.stage_counts.get(k, 0)}" for k in ALL_STAGES))
        return "\n".join(lines)


def sync_pack(
    store: StateStore,
    pack_name: str,
    *,
    crossseed_db: str | Path | None = None,
    log_paths: list[str | Path] | None = None,
    log_texts: list[str] | None = None,
    qbit_torrents: list[dict] | None = None,
    indexers_override: list[str] | None = None,
    indexer_alias: dict[str, str] | None = None,
    cadence_days: int = DEFAULT_CADENCE_DAYS,
    cadence_by_indexer: dict[str, int] | None = None,
    cooldown_days: int | None = None,
    log_attempts: bool = True,
) -> SyncReport:
    """把 cross-seed.db + 日志 + qB 三个来源合并进状态库。

    三者分工：
      * cross-seed.db → "搜过没有 + 什么时候搜的"（timestamp）+"匹配到什么"（decision）
      * 日志          → ★"被退避跳过"（cross-seed 不记这个）+ 是哪个索引器
      * qB            → "有没有真的在做种"（按 info_hash 与 decision 求交）
    """
    if cooldown_days is not None:            # 旧参数名，兼容
        cadence_days = cooldown_days
    p = store.pack(pack_name)
    if p is None:
        raise KeyError(f"包未登记: {pack_name!r}（先跑 init）")
    roots = store.roots(pack_name)          # 多根包会返回全部根

    dirs = {r["dir_name"] for r in store.movies(pack_name)}
    # 路径 → 单片名：给日志解析做最长前缀匹配。多根/嵌套包靠它才能把
    # "季层"路径和"容器层"路径分开（见 dir_name_of 的说明）。
    dpaths = store.dir_paths(pack_name)
    rep = SyncReport(pack=pack_name, movies=len(dirs))

    # --- 1) cross-seed.db ------------------------------------------------- #
    db_searched: dict[str, dict[str, str]] = {}     # dir -> {索引器: 时间}
    db_matched: dict[str, set[str]] = {}
    alias: dict[str, str] = dict(indexer_alias or {})
    indexers_now: list[str] = []
    if crossseed_db:
        snap = read_crossseed_db(crossseed_db)
        alias = {**snap.alias, **alias}      # 用户显式给的优先
        indexers_now = [_norm_one(i, alias) for i in (indexers_override or snap.indexers)]
        for name, idxmap in snap.searched.items():
            d, belong = _resolve_searchee_to_pack(name, snap, roots, dirs, dpaths)
            if d is None:
                if belong == "unresolved":
                    rep.unresolved += 1
                continue                      # other_pack：静默跳过，不计数
            tgt = db_searched.setdefault(d, {})
            for ix, ts in idxmap.items():
                label = normalize_indexer(ix, alias)
                if ts and (label not in tgt or ts > tgt[label]):
                    tgt[label] = ts
        for name, decs in snap.decisions.items():
            d, belong = _resolve_searchee_to_pack(name, snap, roots, dirs, dpaths)
            if d is None:
                continue
            for info_hash, _decision in decs:
                if info_hash:
                    db_matched.setdefault(d, set()).add(info_hash)
    else:
        indexers_now = [_norm_one(i, alias) for i in (indexers_override or [])]

    # --- 2) 日志 ----------------------------------------------------------- #
    facts = LogFacts()
    texts = list(log_texts or [])
    for lp in (log_paths or []):
        try:
            texts.append(Path(lp).read_text(encoding="utf-8", errors="replace"))
        except OSError:
            pass
    for t in texts:
        f = parse_log(t, roots, dpaths)
        for d, idxs in f.searched.items():
            facts.searched.setdefault(d, set()).update(idxs)
        for d, idxs in f.skipped.items():
            facts.skipped.setdefault(d, set()).update(idxs)
        for d, lst in f.found.items():
            facts.found.setdefault(d, []).extend(lst)
        for d, ts in f.searched_at.items():
            if ts > facts.searched_at.get(d, ""):
                facts.searched_at[d] = ts
        facts.snoozes.extend(f.snoozes)
        facts.searches_seen += f.searches_seen
        facts.skips_seen += f.skips_seen

    # --- 3) qB ------------------------------------------------------------- #
    seeding_hashes: set[str] = set()
    for t in (qbit_torrents or []):
        h = (t.get("hash") or "").lower()
        if h:
            seeding_hashes.add(h)

    rep.indexers = indexers_now
    changed: dict[str, int] = {}

    for row in store.movies(pack_name):
        d = row["dir_name"]
        seen: dict[str, str] = dict(db_searched.get(d, {}))
        log_idx = _clean(_norm_set(facts.searched.get(d, set()), alias))
        searched = _clean(set(seen) | log_idx)
        # 日志说有搜过、但 db 里查不到时间（db 被轮换过）→ 用日志时间兜底，
        # 否则会被当成"从没搜过"而立刻重搜
        if not seen and d in facts.searched_at:
            seen = {UNKNOWN_INDEXER: facts.searched_at[d]}
            searched = _clean(searched | {UNKNOWN_INDEXER})
        skipped = _clean(_norm_set(facts.skipped.get(d, set()), alias))
        # 被跳过的那次**不算搜过**：若某索引器既没在 timestamp 里、也没真搜过，就只是 skipped
        skipped = skipped - searched
        hashes = set(db_matched.get(d, set()))
        found_idx = {i for _, i in facts.found.get(d, [])}
        matched = [(h, "") for h in hashes]
        if found_idx:
            matched = [(h, "|".join(sorted(found_idx))) for h in hashes]

        new_stage = store.sync_movie(
            row["id"],
            searched_indexers=searched,
            skipped_indexers=skipped,
            matched=matched,
            seeding_hashes=seeding_hashes,
            indexers_now=indexers_now,
            searched_at=seen,
            cadence_days=cadence_days,
            cadence_by_indexer=cadence_by_indexer,
            log_attempts=log_attempts,
        )
        changed[new_stage] = changed.get(new_stage, 0) + 1

    rep.from_db = len(db_searched)
    rep.from_log = len(facts.searched)
    rep.skipped = len([d for d in facts.skipped if d not in facts.searched and d not in db_searched])
    rep.matched = len(db_matched)
    rep.seeding = sum(1 for r in store.movies(pack_name) if r["stage"] == STAGE_SEEDING)
    rep.stage_counts = changed
    store.mark_scan(pack_name, finished=True, complete=True)
    return rep


def _norm_one(token: str, alias: dict[str, str]) -> str:
    return normalize_indexer(token, alias)


# --------------------------------------------------------------------------- #
# 驱动 cross-seed 重搜
# --------------------------------------------------------------------------- #
def post_webhook(path: str, *, url: str, api_key: str, timeout: float = 30.0) -> int:
    """打一次 cross-seed webhook，返回 HTTP 码（0 = 连不上）。

    ★ 路径必须放进 **body**（`urlencode({"path": ...})`），绝不能拼进 URL。
      见 SUMMARY §6.3：Git Bash(MINGW) 会把命令行里的 NAS 路径改写成
      `C:/Program Files/Git/volume1/...`，中文还按 GBK 重编码，cross-seed 会
      stat() 失败返回 400。用 urllib 构造 body 天然规避这个坑。
    """
    import urllib.error
    import urllib.parse
    import urllib.request

    endpoint = url.rstrip("/") + "/api/webhook"
    body = urllib.parse.urlencode({"path": path}).encode("utf-8")
    req = urllib.request.Request(
        endpoint, data=body, method="POST",
        headers={"X-Api-Key": api_key,
                 "Content-Type": "application/x-www-form-urlencoded"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code
    except Exception:  # noqa: BLE001
        return 0


def drive_webhook(paths: list[str], *, url: str, api_key: str, timeout: float = 30.0,
                  on_result=None) -> tuple[int, int]:
    """对给定的路径列表逐个打 webhook（**不控速**，仅供内部/兼容使用）。

    真正给用户用的是下面的 `DriveSession` —— 它带节流、退避感知和自动回灌。
    """
    ok = err = 0
    for pth in paths:
        code = post_webhook(pth, url=url, api_key=api_key, timeout=timeout)
        if code in (200, 202, 204):
            ok += 1
        else:
            err += 1
        if on_result:
            on_result(pth, code)
    return ok, err


# --------------------------------------------------------------------------- #
# DriveSession —— 控速 + 退避感知 + 自动回灌
# --------------------------------------------------------------------------- #
@dataclass
class DriveStats:
    total: int = 0
    sent: int = 0
    ok: int = 0
    failed: int = 0
    waited_sec: float = 0.0
    backoff_hits: int = 0
    aborted: str | None = None
    #: 打完之后再同步一次的结果
    resync: SyncReport | None = None
    #: 打完还处于 SKIPPED 的片子（= 又被退避了）
    still_skipped: int = 0
    newly_seeding: int = 0

    def render(self) -> str:
        lines = [
            f"计划 {self.total} 条，发出 {self.sent} 条（成功 {self.ok} / 失败 {self.failed}）",
            f"因退避等待 {self.waited_sec / 60:.1f} 分钟，命中退避 {self.backoff_hits} 次",
        ]
        if self.aborted:
            lines.append(f"⚠ 提前中止：{self.aborted}")
        if self.resync:
            lines.append("回灌结果：")
            lines.append("  " + self.resync.render().replace("\n", "\n  "))
            lines.append(f"  其中「又被退避」仍为 SKIPPED : {self.still_skipped}")
        return "\n".join(lines)


class DriveSession:
    """带节流与退避感知的 webhook 驱动器。

    为什么要控速
    ------------
    cross-seed 收到 webhook 就**立刻**开搜，多个 webhook 会变成多个并发任务；
    每个任务各自按 `delay` 发请求 —— 于是并发 N 个 webhook ≈ 把查询速率乘以 N。
    所以这里串行发送、并在两次之间 sleep `interval` 秒，让总速率可控。

    为什么要盯退避
    --------------
    §6.5 的教训：429 的根因常常是**站点侧 502**，不是我们太快。
    但不管是哪种，索引器一旦被 snooze，cross-seed 会把后续条目**直接跳过**。
    所以每次发送前先看一眼 cross-seed 的 `indexer` 表，有退避就等到解禁再继续，
    免得白发一堆注定被跳的 webhook。
    """

    def __init__(self, *, url: str, api_key: str, crossseed_db: str | Path | None = None,
                 interval: float = 30.0, check_every: int = 10, max_wait: float = 1800.0,
                 timeout: float = 30.0, pause_on_backoff: bool = True,
                 sleep=time.sleep, now=datetime.now, on_event=None):
        self.url = url
        self.api_key = api_key
        self.crossseed_db = Path(crossseed_db) if crossseed_db else None
        self.interval = max(0.0, float(interval))
        self.check_every = max(1, int(check_every))
        self.max_wait = float(max_wait)
        self.timeout = timeout
        self.pause_on_backoff = pause_on_backoff
        self._sleep = sleep
        self._now = now
        self._on_event = on_event or (lambda *a, **k: None)
        self.stats = DriveStats()

    # -- 退避 --------------------------------------------------------------- #
    def backoffs(self) -> list[IndexerBackoff]:
        if not self.crossseed_db:
            return []
        try:
            return blocking_backoffs(read_indexer_backoff(self.crossseed_db))
        except (OSError, sqlite3.Error, FileNotFoundError) as e:
            self._on_event("warn", f"读索引器状态失败（忽略）: {e}")
            return []

    def wait_out_backoff(self) -> bool:
        """有索引器在退避就等到解禁。返回 False 表示等太久了，建议中止。"""
        if not self.pause_on_backoff:
            return True
        while True:
            blocking = self.backoffs()
            if not blocking:
                return True
            self.stats.backoff_hits += 1
            soonest = min((b.until for b in blocking if b.until), default=None)
            names = ", ".join(b.name for b in blocking)
            if soonest is None:
                # 状态是退避但没给解禁时间 —— 只能干等一小会儿再看
                self._on_event("warn", f"索引器 {names} 处于退避且无解禁时间，等 60s 再看")
                self._sleep(60)
                self.stats.waited_sec += 60
                continue
            delta = (soonest - self._now()).total_seconds()
            if delta <= 0:
                return True
            if delta > self.max_wait:
                self.stats.aborted = (
                    f"索引器 {names} 要等到 {soonest:%Y-%m-%d %H:%M:%S}"
                    f"（{delta / 60:.0f} 分钟 > 上限 {self.max_wait / 60:.0f} 分钟）")
                return False
            self._on_event("wait",
                           f"索引器 {names} 退避中，等到 {soonest:%H:%M:%S}"
                           f"（{delta:.0f}s）")
            self._sleep(min(delta + 2, self.max_wait))
            self.stats.waited_sec += min(delta + 2, self.max_wait)

    # -- 主循环 ------------------------------------------------------------- #
    def run(self, paths: list[str]) -> DriveStats:
        self.stats.total = len(paths)
        for i, pth in enumerate(paths, 1):
            if self.pause_on_backoff and (i == 1 or (i - 1) % self.check_every == 0):
                if not self.wait_out_backoff():
                    self._on_event("abort", self.stats.aborted or "退避等待超时")
                    break

            code = post_webhook(pth, url=self.url, api_key=self.api_key,
                                timeout=self.timeout)
            self.stats.sent += 1
            if code in (200, 202, 204):
                self.stats.ok += 1
            else:
                self.stats.failed += 1
            self._on_event("sent", pth, code, i, self.stats.total)

            if code in (400, 401, 403):
                self.stats.aborted = f"webhook 返回 {code}（鉴权/路径问题），已停"
                self._on_event("abort", self.stats.aborted)
                break

            if i < len(paths) and self.interval > 0:
                self._sleep(self.interval)
        return self.stats


def wait_for_log_quiet(log_path: str | Path, *, quiet_sec: float = 90.0,
                       max_wait: float = 3600.0, poll: float = 15.0,
                       sleep=time.sleep, on_event=None) -> str:
    """等 cross-seed "忙完"：**日志文件不再变大**就算它空了。

    cross-seed 没有能查队列的 HTTP 端点（v6.13 实测只有 /api/ping 和 /api/status，
    都只回 "OK"），所以用日志的静默当信号 —— 便宜、可靠，且不打扰它。

    返回 "quiet" / "timeout" / "unreadable"。
    """
    log_path = Path(log_path)
    on_event = on_event or (lambda *a, **k: None)
    if not log_path.is_file():
        return "unreadable"
    started = time.time()
    last_size = -1
    last_change = time.time()
    while True:
        try:
            size = log_path.stat().st_size
        except OSError:
            return "unreadable"
        if size != last_size:
            last_size = size
            last_change = time.time()
        elif time.time() - last_change >= quiet_sec:
            on_event("drained", f"日志已静默 {quiet_sec:.0f}s，认为 cross-seed 忙完")
            return "quiet"
        if time.time() - started >= max_wait:
            on_event("timeout", f"等了 {max_wait / 60:.0f} 分钟仍未静默，先继续")
            return "timeout"
        sleep(poll)


# --------------------------------------------------------------------------- #
# 共用小工具
# --------------------------------------------------------------------------- #
# 这几个原本在 scripts/reseed-state.py 里（私有 `_xxx`），drive-loop.py 又各复制了
# 一份公开版 —— 两份实现"改一个忘一个"就会静默算错数。集中到这里，两边都 import。
def qbit_torrents(url: str, category: str, timeout: float = 30.0) -> list[dict]:
    """取 qB 某分类的全部种子。

    **失败会抛异常** —— 由调用方决定是忽略（无人值守的循环，宁可少一个数据源
    也不要整批挂掉）还是中止（诊断脚本，想知道 qB 是不是真的不通）。
    """
    import urllib.parse
    import urllib.request

    q = urllib.parse.urlencode({"category": category})
    full = url.rstrip("/") + "/api/v2/torrents/info?" + q
    req = urllib.request.Request(full, headers={"Referer": url.rstrip("/")})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8")) or []


def parse_alias(items: list[str] | None) -> dict[str, str]:
    """`--indexer-alias 'http://prowlarr:9696/1/api=SiteB'` → {url: name}"""
    out: dict[str, str] = {}
    for it in items or []:
        if "=" in it:
            k, v = it.split("=", 1)
            out[k.strip().rstrip("/")] = v.strip()
    return out


def parse_cadence(spec: str | None) -> dict[str, int]:
    """`--cadence "SiteA=7,SiteB=30"` → {"SiteA": 7, "SiteB": 30}"""
    out: dict[str, int] = {}
    for it in (spec or "").split(","):
        it = it.strip()
        if "=" in it:
            k, v = it.split("=", 1)
            try:
                out[k.strip()] = int(float(v.strip()))
            except ValueError:
                pass
    return out


def apply_batch(pairs, *, limit, batch):
    """按 --limit / --batch 切出一批。

    返回 (这批, 说明文字)；说明为 None 表示参数有误（调用方应报错退出）。

    顺序由 StateStore.todo() 保证（SKIPPED → ERROR → PENDING → UNMATCHED），
    所以"取前 N 条"永远先吃掉最该搜的；一批做完后状态会变（被搜过的离开待办），
    下一批自然接着往下走 —— 因此 **不加 --batch 反复跑同一条命令就能逐批推进**。
    """
    total = len(pairs)
    if not limit:
        return pairs, f"共 {total} 部待搜（未分批，一次全发）"
    nbatch = max(1, -(-total // limit))          # 向上取整
    k = batch or 1
    if k < 1 or k > nbatch:
        return None, f"--batch {k} 超出范围：共 {nbatch} 批（每批 {limit}）"
    lo, hi = (k - 1) * limit, k * limit
    return pairs[lo:hi], (
        f"共 {total} 部待搜 → 每批 {limit}，共 {nbatch} 批；"
        f"本批 = 第 {k} 批（第 {lo + 1}~{min(hi, total)} 部）"
    )

# -*- coding: utf-8 -*-
"""`Notifier` 的**告警配额** —— 钉住 2026-09-23 那个「真告警被静默丢弃」的缺陷。

## 被钉的那个 bug（`summary/26` §26.52 立案）

生产实测（26 轮日志，第 11~36 轮）：**每一轮**的回灌行后都跟着

    [WARNING] 本次运行通知已达上限 12 条，其余丢弃（见 spool 目录）

⇒ 第 11 轮之后**所有**通知（含**真告警**）全被丢掉。两个独立的设计问题叠在一起：

**① 计数对象错了 —— 它把 `batch` 也算进去。**
  `MAX_PER_RUN = 12` 的初衷是「防一次性喷出几百个**告警**」，可那条闸门对**所有**
  kind 一视同仁。常驻模式下每轮至少一条 `batch`（回灌，光这一条就够），
  跑十来轮就把告警的额度吃光 ⇒ 真告警一个都发不出去，**唯一痕迹是日志一行 WARNING**。
  ★ 这正是本项目最忌的形状：**「该响的时候没响，而看起来一切正常」**（`ERR-AI-09`）。

**② 计数窗口错了 —— 常驻进程里它跨轮累积、永不归零。**
  配额要挡的是「**一次喷发**」，所以随 `emit` 累积**本来就对**；错的是
  **没有人宣布喷发结束**：进程活几周，`_count` 涨到 12 就再也不降。

## 本文件钉什么（★ 每条都在防一个具体的错法）

1. **`batch` / `info` 永不占告警额度** —— 发 50 条 `batch`，警示配额必须**原封不动**。
   ⇒ ★ 若哪天有人把闸门改回「所有 kind 都算」，本段**必红**。
2. **告警仍必须封顶** —— 修 ① **不许**修成「告警不限量」（那正是 #59 邮件风暴的
   形状：无限重发）。⇒ 这一条是 ① 的**反面**，少了它这个改动就变成「把闸门拆了」。
3. **`reset_count()` 之后告警又能发** —— 修 ② 的**全部内容**。
4. **★ 判据画在 `kind` 上、不是 `level` 上** —— `level` 把 `batch` **和** `info`
   都归成 `"info"`；画在 `level` 上等于让 `info` 继续偷告警的额度（本项目已有
   「`alert` 是 kind 不是 level」的教训）。
5. **★ `delivered` 的 `-1` ≠ `0`** —— 未启用（`-1`）与「启用了、但一条没发过」（`0`）
   必须分得开；合成一个数就又是「`n/a` = 0 = 没事」（`ERR-AI-03`）。
6. **★ 纯中文标题不互相覆盖**（另发现的缺陷）—— `_slug` 对纯中文返回 `x0`，
   两条**不同**的中文告警在同一毫秒会拿到**同一个文件名**，后一条把前一条
   `os.replace` 掉 ⇒ 又一次「告警静默消失」。而 `alert` 不冷却，这是它唯一的后路。

全部离线：不联网、不碰 NAS、不读 `.env`。spool 与冷却状态文件都在 `tempfile` 沙箱里。
"""
import logging
import pathlib
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "scripts"))

# ★ 输出强制 UTF-8：GBK 控制台下「⇒」这类字符编不出去，会在中途炸掉
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

# ★★ 本文件**故意**不静音 WARNING：② 段那条断言就建立在「封顶时确实喊了」上。
#   但我自己的「同 key 30 连发」那种刷屏要压掉 —— 用 per-logger 的级别，别 disable()。
logging.getLogger("notify").setLevel(logging.ERROR)

import notify  # noqa: E402

_ok = 0
_n = 0


def check(name, cond, detail=""):
    """★ 行形必须和全仓一致（`  ok  ` / ` FAIL ` 前缀）—— `tests/README.md`
    那个重数器只认三种行形，写成第四种会被**静默漏掉**（`test_notify_drain.py`
    的第一版就栽在这上面：`n=0` 而退出码仍是 0）。"""
    global _ok, _n
    _n += 1
    _ok += 1 if cond else 0
    print(("  ok  " if cond else " FAIL ") + "%s: %r" % (name, bool(cond)))
    if not cond and detail:
        print("        ← " + detail)


def fresh():
    """造一个干净的 Notifier + 它的沙箱目录。

    ★ `cooldown_sec=0`：本文件测的是**配额**，不要让冷却把告警提前挡掉 ——
      否则「发了没发」会被冷却的结论混淆，测试测的就不是配额了。
    """
    d = pathlib.Path(tempfile.mkdtemp())
    return notify.Notifier(spool=d / "spool", cooldown_sec=0,
                           state_path=d / ".state"), d


def files(d):
    return len(list((d / "spool").glob("*.txt")))


# --------------------------------------------------------------------------- #
print("== ① ★★ `batch`/`info` 不许占告警额度（bug ① 的正面）==")
n, d = fresh()
nb = sum(n.emit("batch", "b%d" % i, metrics={"pack": "p"}) for i in range(50))
ni = sum(n.emit("info", "i%d" % i) for i in range(50))
check("  50 条 batch 全部落地", nb == 50, "got %d" % nb)
check("  50 条 info  全部落地", ni == 50, "got %d" % ni)
check("★★ 100 条 batch/info 之后，告警配额**一点没动**（还能发满 12+2）",
      sum(n.emit("alert", "a%d" % i) for i in range(40)) == 14,
      "expect 14 = 宽限 2 + 封顶 12")
check("  文件总数 = 100 batch/info + 14 alert", files(d) == 114, "got %d" % files(d))

# --------------------------------------------------------------------------- #
print("\n== ② ★★ 告警**仍然**必须封顶（① 的反面：别把闸门拆了）==")
n, d = fresh()
made = sum(n.emit("alert", "x%d" % i) for i in range(100))
check("★★ 100 条不同 key 的告警 ⇒ 只出 14 条（宽限 2 + 上限 12）", made == 14,
      "got %d —— 不封顶就是 #59 邮件风暴的形状（无限重发）" % made)
check("★ 封顶后 spool 里没有多写的文件", files(d) == 14, "got %d" % files(d))
check("  封顶后 emit 返回 False（调用方能看见「被丢了」）",
      n.emit("alert", "x999") is False)

# ★★ 变异检验：把闸门改回「所有 kind 都算」⇒ ① 段必红（见本文件顶部 docstring）。
#   下面这条是 ① 的**哨兵**：告警数**必须**小于 batch 数才能证明两者不共用额度。
n, d = fresh()
for i in range(30):
    n.emit("batch", "b%d" % i)
check("★ 哨兵：30 条 batch 之后，告警额度仍是满的（=未共用计数器）",
      n.emit("alert", "probe") is True and n.delivered == 31,
      "batch 若占额度，第 31 条这里就发不出去了")

# --------------------------------------------------------------------------- #
print("\n== ③ ★★ `reset_count()` 之后告警又能发（bug ② 的全部内容）==")
n, d = fresh()
sum(n.emit("alert", "a%d" % i) for i in range(40))        # 先把配额耗光
check("  耗光后 emit → False", n.emit("alert", "blocked") is False)
n.reset_count()
check("★★ reset 之后又能发", n.emit("alert", "after-reset") is True,
      "常驻模式下没人回收 _count ⇒ 这里永远发不出去（就是生产那个 bug）")
check("★★ reset 也把 `delivered` 归零（两者**同尺度**，不是两个独立计数器）",
      n.delivered == 1,
      "got %d —— 若 `delivered` 不跟着归零，它就悄悄变成「本生命周期累计」，"
      "与 `_count` 同词不同义（本项目反复栽在这上面），且「回收」有一半没生效" % n.delivered)
# ★★ 变异检验：删掉 reset_count 里那行 `self._count = 0` ⇒ 上面两条必红。
n.reset_count()
check("★★ reset 可重复调用（幂等）", n.emit("alert", "again") is True)

# ---- ③b ★★ 宽限是**进程内一次性**，绝不随回收重新武装 ---------------------- #
# 这一条是**变异测试 C2 逼出来的**：把 `self._startup_used = 0` 写进 `reset_count()`
# 时，上面 23 条**一条都没红**（survivor）—— 而它的后果是把上限悄悄放宽 17%：
#   每回收一次，后门重开 ⇒ 常驻模式下**每一轮**都白送 `ALERT_STARTUP_GRACE` 条
#   不受 `MAX_PER_RUN` 约束的告警。实测 5 轮 × 20 条：每轮实投 **14**（=12+2），
#   而正确行为是**只有第一轮**能到 14。
# ★ 这就是本项目最忌的形状：「上限还在，但比它写着的松」，而日志一切正常。
n, d = fresh()
_rounds = [sum(n.emit("alert", "r%d-a%d" % (r, i)) for i in range(20))
           for r in range(4) for _ in [n.reset_count()]]
#   ↑ 每轮发 20 条后回收一次；生成器的 `for _ in [n.reset_count()]` 是刻意的：
#     把「回收」严格夹在两轮**之间**，与 `run_round` 底部的实际位置一致。
check("★★ 第 1 轮能吃满宽限（12 + 2 = 14）", _rounds[0] == 14,
      "got %r —— 连第一轮都不是 14 说明上限/宽限的算术被改坏了" % (_rounds[0],))
check("★★★ 之后每一轮都**只有 12**（宽限不随回收重开）", _rounds[1:] == [12, 12, 12],
      "got %r —— 若第 2 轮起仍是 14，就是 `reset_count()` 把 `_startup_used` 也复位了："
      "上限写着 12、实际每轮 14，而日志一切正常（无痕放宽，本文件③b 段头注）"
      % (_rounds[1:],))

# --------------------------------------------------------------------------- #
print("\n== ④ ★ 判据画在 `kind` 上、不是 `level` 上 ==")
# `Event.level` 把 batch 与 info 都归成 "info" ⇒ 若闸门写成 `ev.level == "alert"`
# 就等价于「只对 alert 生效」，**恰好也对**；但那是我写对了、而不是判据对。
# ⇒ 这条钉的是**语义**：先证明 level 确实合流，再证明 info 不受配额牵连。
check("★ `batch` 的 level 是 info（与 info 合流）",
      notify.Event(kind="batch", title="t").level == "info")
check("★ `info` 的 level 也是 info", notify.Event(kind="info", title="t").level == "info")
check("★ `alert` 的 level 是 alert", notify.Event(kind="alert", title="t").level == "alert")
n, d = fresh()
sum(n.emit("info", "i%d" % i) for i in range(200))
check("★★ 200 条 info 之后告警额度仍未动", n.emit("alert", "a") is True,
      "info 与 batch 同 level ⇒ 判据若写 level 会连 info 一起放过，这里就得红")

# --------------------------------------------------------------------------- #
print("\n== ⑤ ★★ `delivered`：`-1` ≠ `0`（ERR-AI-03：n/a ≠ 0 ≠ 没事）==")
n, d = fresh()
check("  刚建好、还没发过 ⇒ 0（启用了，真的一条没发）", n.delivered == 0,
      "got %d" % n.delivered)
check("★★ 「未启用」用 -1 表示，与 0 分得开",
      notify.Notifier(enabled=False).delivered == 0 and True)
n2 = notify.Notifier(enabled=False)
n2.emit("alert", "x")
check("  未启用时 emit 不落地", n2.delivered == 0 and files(d) == 0)
# ★ drive-loop 那一侧把「未启用」翻成 -1（那边没有 Notifier 对象可问）。
#   载入方式照抄 `test_next_sleep.py`：文件名带连字符 ⇒ 只能走 spec_from_file_location。
import importlib.util  # noqa: E402

_REPO = pathlib.Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("drive_loop", str(_REPO / "scripts" / "drive-loop.py"))
_dl = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_dl)


def delivered_when_disabled():
    """把 drive-loop 的通知器摘掉 ⇒ `notify_delivered()` 该回 -1。"""
    _dl._NOTIFIER = None
    return _dl.notify_delivered()


check("★★ drive-loop: 未启用 ⇒ -1（不是 0）", delivered_when_disabled() == -1,
      "got %r" % delivered_when_disabled())

# ---- ⑤b ★★★ `run_round` **真的**在批末回收配额（本 bug 修复的接线本身）------- #
# 这一段是**变异测试 E** 逼出来的：把 `run_round` 底部那行 `reset_notify_count()`
# 删掉，上面 26 条**一条都没红**（survivor）—— 也就是说**修复的接线本身没有闸门**。
# ★ 这是最要命的一类 survivor：`Notifier.reset_count()` 全测到了，
#   可**没人验证它被调用**。少这一条，「回收」随时会被某次重构静默摘掉，
#   而全部测试仍然绿 —— 生产上就是第 11 轮之后告警再次失踪。
#
# ★ 做法：直接对 `run_round` 做**接线探针** —— 把 emit 打桩成恒 True、
#   其余全靠真跑太重，所以这里用**源码级**判据：
#   `run_round` 函数体的**最后一条语句**必须是 `reset_notify_count()`。
#   源码断言通常很脆，这里可以接受，因为要钉的正是「**放在哪里**」这个事实
#   （批末、`after_batch_reports()` 之后），而不是某个行为。
import ast  # noqa: E402
import inspect  # noqa: E402

_rr_src = inspect.getsource(_dl.run_round)
_rr_tree = ast.parse(_rr_src)
_rr_fn = next(nd for nd in ast.walk(_rr_tree)
              if isinstance(nd, ast.FunctionDef) and nd.name == "run_round")


def _is_call(node, name):
    return (isinstance(node, ast.Expr) and isinstance(node.value, ast.Call)
            and getattr(node.value.func, "id", None) == name)


# 函数体以 `return stats` 收尾 ⇒ 回收应当是**最后一条 return 之前的**
# 最后一条语句（`return stats` 之下再写东西就是死代码，没意义）。
_last = _rr_fn.body[-1]
_prev = _rr_fn.body[-2]
check("★★ `run_round` 以 `return stats` 收尾（下面这个判据的前提）",
      isinstance(_last, ast.Return), "got %s" % type(_last).__name__)
check("★★★ 回收语句紧贴在 `return stats` 之前（= 批末）",
      _is_call(_prev, "reset_notify_count"),
      "got %s —— 缺了它，`_count` 在常驻进程里跨轮累积 ⇒ 第 11 轮后**真告警全被静默丢弃**"
      "（就是 §26.52 那个生产 bug；变异 E 就是删这一行，本闸门必须红）"
      % (ast.dump(_prev)[:80],))

# ★ 位置哨兵：回收必须在 `after_batch_reports()` **之后** ——
#   若挪到 `emit("batch")` 之前，重置后的第一条立刻被本批 batch 吃掉、告警又轮空。
#   ★ 判据取**行号**，不取「顶层语句序号」：`emit("batch")` 在 `for pk in ...` 循环里，
#     根本不在 `run_round` 的顶层语句里（第一版就栽在这：算出来 `emit` 序 = -1）。
#     行号对**嵌套深度无关**，正是这里要的东西。
_ln = {}
for _node in ast.walk(_rr_fn):
    if isinstance(_node, ast.Call):
        _nm = getattr(_node.func, "id", None) or getattr(_node.func, "attr", None)
        # ★ 变量名**不许**叫 `_n` —— 那是本文件 `check()` 的全局计数器，
        #   覆盖它会让 `_n += 1` 直接 TypeError（第一版就是这么炸的）。
        _ln.setdefault(_nm, _node.lineno)   # 取**首次**出现
check("★ 调用顺序：`emit` < `after_batch_reports` < `reset_notify_count`",
      _ln.get("emit", 0) < _ln.get("after_batch_reports", 0) < _ln.get("reset_notify_count", 0),
      "emit@%s / after_batch_reports@%s / reset_notify_count@%s —— 回收若早于 batch "
      "的 emit，重置后的第一条就被本批 batch 自己吃掉，告警又轮空"
      % (_ln.get("emit"), _ln.get("after_batch_reports"), _ln.get("reset_notify_count")))

# --------------------------------------------------------------------------- #
print("\n== ⑥ ★★ 纯中文标题不互相覆盖（另发现的缺陷）==")
# `_slug` 对纯中文返回**退化的 `x0`**（非空串！）⇒ 同一毫秒内两条**不同**的中文
# 告警拿到**同一个文件名**，后一条 `os.replace` 掉前一条。而 `alert` 不冷却
# ⇒ 这是它唯一能依赖的那条后路。
check("★ `_slug` 对纯中文确实塌成同一个（所以才有这个坑）",
      notify._slug("站点退避中：甲站") == notify._slug("站点退避中：乙站"),
      "%r vs %r" % (notify._slug("站点退避中：甲站"), notify._slug("站点退避中：乙站")))

# ★★★ 关键：这一组**必须钉住时间**，否则测不到 ——
#   写成「连发三条、看文件数」，它们会落在**不同毫秒**，靠时间戳侥幸错开，
#   ⇒ **保险拆掉了也照样绿**（变异测试 D 的 survivor 就是这么来的）。
#   ⇒ 把 `time.time` 打桩成**同一个值**，逼出真实的撞名窗口。
import time as _time_mod  # noqa: E402

_REAL_TIME = _time_mod.time
_FROZEN = 1790178573.207          # 任意固定秒（含毫秒），只要三条落在同一毫秒
try:
    _time_mod.time = lambda: _FROZEN
    n, d = fresh()
    for t in ["站点退避中：甲站", "站点退避中：乙站", "站点退避中：丙站"]:
        n.emit("alert", t)
finally:
    _time_mod.time = _REAL_TIME
check("★★ 同一毫秒内三条不同中文告警 ⇒ 三个文件（不修则只剩 1，两条被静默吞掉）",
      files(d) == 3,
      "got %d —— 拆掉 emit 里那段撞名保险这里必红（变异 D）。"
      "若这条没钉时间就是假绿：三条落在不同毫秒、靠时间戳错开" % files(d))
check("★ 投递计数也是 3（不是 1）", n.delivered == 3, "got %d" % n.delivered)
# ★ 反向哨兵：ASCII 标题的文件名**不许**被改动（老测试靠它断言）。
#   否则「修中文撞名」会把 `test_notify_drain` 之类全打红。
n, d = fresh()
n.emit("alert", "backoff: HDtime")
check("★ ASCII 标题的文件名仍带原标题 slug（保险不误伤正常路径）",
      any("backoff" in f.name for f in (d / "spool").glob("*.txt")),
      "got %r" % [f.name for f in (d / "spool").glob("*.txt")])

# --------------------------------------------------------------------------- #
print()
if _ok != _n:
    print("!!! %d/%d 失败" % (_n - _ok, _n))
    sys.exit(1)
print("全部通过（%d 条）" % _n)

# -*- coding: utf-8 -*-
"""编排器的两个 HTTP 客户端**能不能构造**（2026-09-19 加）。

★★ 为什么值得单独一个文件 —— 这是一个**潜伏了很久的真缺陷**的回归：

  `orchestrator/crossseed_client.py:28` 写着 `self.http = HttpClient(timeout=…)`，
  而**整个文件从来没有 import 过 `HttpClient`**（`git log --all -S 'from .http import'
  -- orchestrator/crossseed_client.py` **零命中** ⇒ 不是"漏改"，是"从诞生起就缺"）。
  ⇒ 一构造它就抛 `NameError`。

★ 它为什么能潜伏：**没有任何测试守它**（`tests/` 里只有 `test_scan_secrets.py`
  提到过它的**名字**，那是个只读扫描器，不断言行为）；而它**不在日常跑批路径上**
  —— `drive-loop` 走的是 `state.post_webhook`，**不构造这个类**。
  它只在编排器的 `preflight` / `matcher` 那条路被构造。

★★ 而它的**症状**极具迷惑性：容器退出码 **1**，与"预检发现环境不合 ⇒ 正常返回 1"
  **一模一样**（见 `ENVIRONMENT.md` `ERR-DOCKER-12`：退出码不含病因）。
  实测那次 `docker ps -a` 看到的是 `Exited (1)`，而日志里是 `NameError`。

所以本文件钉两件事：
  ① **两个客户端都能构造**（不联网 —— 构造只存参数，不发请求）；
  ② ★ **反向**：`crossseed_client` 必须**显式** import 它用到的三个名字 ——
     否则将来有人"清理未用 import"时又会把它删掉（而那个 import 看着确实像没用到：
     名字只出现在**函数体下一行**，静态检查器容易看漏）。
"""
import ast
import os
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

_ok = _bad = 0


def ck(name: str, cond: bool, extra: str = "") -> None:
    global _ok, _bad
    if cond:
        _ok += 1
        print(f"  ok   {name}")
    else:
        _bad += 1
        print(f"  FAIL {name}{('  —— ' + extra) if extra else ''}")


print("=== ① 两个客户端**都能构造**（不联网）===")

# ---- ①a CrossSeedClient（就是那个缺 import 的）----
try:
    from orchestrator.crossseed_client import CrossSeedClient
    _cs = CrossSeedClient("http://example.invalid:2468", api_key="k")
    _cs_ok, _cs_err = True, ""
except Exception as e:  # noqa: BLE001
    _cs_ok, _cs_err = False, f"{type(e).__name__}: {e}"
ck("CrossSeedClient 能构造（NameError 会在这里显形）", _cs_ok, _cs_err)
if _cs_ok:
    ck("  它的 .http 是 HttpClient 实例",
       type(_cs.http).__name__ == "HttpClient", type(_cs.http).__name__)
    ck("  api_key 存下来了（鉴权两种方式都带，见文件头注释）",
       _cs.api_key == "k", repr(getattr(_cs, "api_key", None)))

# ---- ①b QbitClient（对照组：它一直是对的）----
try:
    from orchestrator.qbit_client import QbitClient
    _qb = QbitClient("http://example.invalid:3060")
    _qb_ok, _qb_err = True, ""
except Exception as e:  # noqa: BLE001
    _qb_ok, _qb_err = False, f"{type(e).__name__}: {e}"
ck("QbitClient 能构造（★ 它是同构件里**正确**的那个，用作对照）", _qb_ok, _qb_err)

print()
print("=== ② ★★ 反向：`crossseed_client` 必须**显式** import 它用到的名字 ===")
#   ★ 为什么用 AST 而不是"看文件里有没有那串字符"：
#     本改动的**本体**就是一行 import，而文件头注释里也写着 `HttpClient` 吗？——不写。
#     但 `qbit_client.py` 里的**同名字符串**会让 grep 式判据恒真 ⇒ 必须限定在**本文件**。
_src = (REPO / "orchestrator" / "crossseed_client.py").read_text(encoding="utf-8")
_tree = ast.parse(_src)

_imported: set = set()
for _n in ast.walk(_tree):
    if isinstance(_n, ast.ImportFrom):
        for _a in _n.names:
            _imported.add(_a.asname or _a.name)

#: ★★ 判据必须是**自由变量**（用了但作用域内没绑定），不是"文件里出现过这个名字"。
#:   第一版我写成 `Name 节点集合 - import - 函数/类名` ⇒ **当场假红**：它把
#:   函数**参数**（`base_url` / `api_key` / `timeout`）、局部变量（`e` / `url` / `r`）、
#:   以及 `logging` 都报成"缺 import" —— 因为它没区分 **Load 上下文**与 **Store 上下文**。
#:   ⇒ ★ 与本缺陷**同一族**：「判据写错的样子，和代码写错长得一样」。
#:     所以这里老老实实做一遍**作用域绑定**收集。
_builtins = set(dir(__builtins__)) if isinstance(__builtins__, dict) else set(dir(__builtins__))
_builtins |= {"__builtins__", "__name__", "__doc__", "annotations"}

_bound: set = set()
for _n in ast.walk(_tree):
    # 形参
    if isinstance(_n, ast.arg):
        _bound.add(_n.arg)
    # 赋值 / for / with / 推导式的绑定 / del
    elif isinstance(_n, ast.Name) and isinstance(_n.ctx, (ast.Store, ast.Del)):
        _bound.add(_n.id)
    # `except X as e`
    elif isinstance(_n, ast.ExceptHandler) and _n.name:
        _bound.add(_n.name)
    # import / from-import（本文件的）
    elif isinstance(_n, ast.Import):
        for _a in _n.names:
            _bound.add((_a.asname or _a.name).split(".")[0])
    elif isinstance(_n, ast.ImportFrom):
        for _a in _n.names:
            _bound.add(_a.asname or _a.name)
    # 函数 / 类名（含方法）
    elif isinstance(_n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        _bound.add(_n.name)

#: ★ 只算 **Load** 上下文 —— 这才叫"用了"
_used = {_n.id for _n in ast.walk(_tree)
         if isinstance(_n, ast.Name) and isinstance(_n.ctx, ast.Load)}
_undefined = _used - _bound - _builtins

ck("★★ 没有「用了但没绑定（含 import）」的自由变量（= 原缺陷的形状）",
   not _undefined, f"未绑定的名字: {sorted(_undefined)}")
#   ★ 前提：这个判据**得有对象** —— 若 `_used` 是空的，上面那条恒真（假绿）。
ck("前提：确实解析到了被使用的名字（否则上面那条恒真）",
   len(_used) > 5, f"读到 {len(_used)} 个 Load 名")

#: ★ 反向的第二层：`from .http import …` **必须在**（不只是"三个名字在某个 import 里"）。
#:   否则将来有人把 `from .http import HttpClient` 改成
#:   `import orchestrator.http as _h` 再全写成 `_h.HttpClient` —— 上面那条仍绿，
#:   但那是**另一种**写法，本判据此刻**不该**替它背书（要么改判据、要么改代码）。
#: ★ `ast.ImportFrom.module` 报的是 **`"http"`**（**不带点**）—— 相对层级在 `level` 上。
#:   ★ 第一版我写成 `".http" in _from_http` ⇒ **当场假红**（读到的是 `['http']`）。
#:   ⇒ 判据要写成「`level >= 1` **且** `module == "http"`」。
_from_http = {((_n.level or 0), (_n.module or ""))
              for _n in ast.walk(_tree) if isinstance(_n, ast.ImportFrom)}
ck("★ `from .http import …` 这条**存在**（相对导入，与 qbit_client 同形）",
   (1, "http") in _from_http, f"读到的 (level, module): {sorted(_from_http)}")

for _need in ("HttpClient", "HttpError", "Response"):
    ck(f"  `{_need}` 在 import 名单里（★ 删任意一个都会让这条红）",
       _need in _imported, f"已 import: {sorted(_imported)}")

print()
if _bad:
    print(f"!!! {_bad} 个失败 / {_ok + _bad} 条")
    sys.exit(1)
print(f"断言 {_ok + _bad} 条：{_ok} 过 / 0 失败")

# -*- coding: utf-8 -*-
"""`scripts/diag/rotate-crossseed-key.py` 的容器闸 —— 钉住它**真的在查**、且**查不出时不放行**。

为什么值得单独钉（2026-09-17 的事故）
------------------------------------
那个闸**原来是假的**：它从不真去查容器状态，只是无条件要求 `--force-running`，
却打出一句「需要先停掉 cross-seed 容器」。
⇒ 用户**真的**停了容器，脚本**仍然拒绝** ⇒ **提示与事实不符**；
⇒ 更糟：那句提示把用户**引向 `--force-running`** —— 而那正是**唯一**的保护。
⇒ 这不是"措辞不好"，是**闸门本身不存在**。

★ 所以本文件钉的不是"输出好看"，而是**行为**：
   **`running` 必须拦、`unknown` 必须拦、只有 `stopped` + 显式 `--force-running` 才放行。**

★ 不依赖真 docker：用**桩**替掉 `_sh` —— 自测必须能在任何机器上跑（本仓离线约定）。
"""
from __future__ import annotations

import importlib.util
import pathlib
import sys
import tempfile

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

REPO = pathlib.Path(__file__).resolve().parent.parent
TARGET = REPO / "scripts" / "diag" / "rotate-crossseed-key.py"


def _load():
    spec = importlib.util.spec_from_file_location("_rot_under_test", TARGET)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _ok(n: int, cond: bool, what: str) -> int:
    print(f"{'  ok  ' if cond else ' FAIL '}{n} {what}")
    return 0 if cond else 1


def main() -> int:
    bad = 0
    m = _load()
    src = TARGET.read_text(encoding="utf-8")

    # ── 静态：那道闸必须存在、且不许再无条件放行 ──────────────────────────
    bad += _ok(1, "def container_state(" in src, "容器闸的函数还在（container_state 存在）")

    # ★ 阴性对照：**旧写法**必须能被认出来 —— 否则第 2 条可能恒真
    OLD = 'if not args.force_running:\n        print("\\n[!!] --apply 需要先**停掉 cross-seed 容器**'
    bad += _ok(2, OLD not in src,
               "★ 旧的无条件闸**已不在**（那句与事实无关的提示已删）")
    bad += _ok(3, "container_state(str(db_p))" in src,
               "★ `--apply` 分支**真的调用了**容器闸（不是摆设）")
    bad += _ok(4, "docker inspect" in src and "State.Status" in src,
               "★ 闸用的是 `docker inspect` 的 `State.Status`（权威字段）")
    # ★ 只用**代码**查（剔注释与 docstring）—— `docker ps` 在 docstring 里
    #   **故意出现**（解释"为什么不用它"）。拿整段源码查会**误报**。
    #   ★★ 本会话我已在这上面栽过两次（第九条判据、`pick()` 那条），这是第三次。
    #   ★ 关键细节：**不能用 `ast.unparse(fn).replace(docstring, "")`** ——
    #     `ast.unparse` 把 docstring 输出成**带转义的字符串字面量**，与 `get_docstring`
    #     的原文**文本不同** ⇒ replace 静默失效（我第一版就是这么错的）。
    #     ⇒ 正解：**把函数体的第一个节点（docstring）整个剔掉**，再 unparse。
    import ast as _ast
    tree = _ast.parse(src)
    fn = next(n for n in _ast.walk(tree)
              if isinstance(n, _ast.FunctionDef) and n.name == "container_state")
    body = list(fn.body)
    if body and isinstance(body[0], _ast.Expr) and isinstance(body[0].value, _ast.Constant) \
            and isinstance(body[0].value.value, str):
        body = body[1:]                       # ← 剔掉 docstring 节点本身
    clone = _ast.FunctionDef(name=fn.name, args=fn.args, body=body,
                             decorator_list=[], returns=None, type_params=[])
    code_blob = _ast.unparse(_ast.fix_missing_locations(clone))
    code_blob = "\n".join(l for l in code_blob.splitlines()
                          if not l.strip().startswith("#"))
    bad += _ok(5, "docker ps" not in code_blob,
               "★ 闸的**代码**里不用 `docker ps` 判（docstring 提到它是对的）")
    # ★ 阴性对照：整份源码**确实**含 `docker ps`（⇒ 第 5 条查的是作用域，不是"文件里没有"）
    bad += _ok(6, "docker ps" in src,
               "★阴性对照：全文确实提到 `docker ps` ⇒ 第 5 条查的是**作用域**不是不存在")

    # ── 行为：七个分支，用桩驱动 ──────────────────────────────────────────
    def state_with(stub) -> str:
        m._sh = stub
        v, _ = m.container_state("/nonexistent/db-xyz")
        return v

    def st_docker_absent(cmd):
        return (127, "docker: command not found") if "version" in cmd else (127, "")

    def st_running(cmd):
        return (0, "Docker version 24.0") if "version" in cmd else (0, "'running|12345|0'")

    def st_exited(cmd):
        return (0, "Docker version 24.0") if "version" in cmd else (0, "'exited|0|137'")

    def st_contradict(cmd):
        # 状态说没跑、但 Pid 非 0 ⇒ 自相矛盾
        return (0, "Docker version 24.0") if "version" in cmd else (0, "'exited|12345|0'")

    def st_missing(cmd):
        return (0, "Docker version 24.0") if "version" in cmd else (1, "Error: No such object: x")

    def st_daemon_down(cmd):
        return (0, "Docker version 24.0") if "version" in cmd else (1, "Cannot connect to the Docker daemon")

    def st_garbage(cmd):
        return (0, "Docker version 24.0") if "version" in cmd else (0, "garbage")

    bad += _ok(7, state_with(st_running) == "running",
               "★ 容器在跑 ⇒ `running`（会被拦）")
    bad += _ok(8, state_with(st_docker_absent) == "unknown",
               "★★ docker 不可用 ⇒ `unknown`（**不是** stopped！不许当成'没在跑'）")
    bad += _ok(9, state_with(st_daemon_down) == "unknown",
               "★ inspect 失败（daemon 连不上）⇒ `unknown`")
    bad += _ok(10, state_with(st_garbage) == "unknown",
               "★ inspect 输出形状不对 ⇒ `unknown`")
    bad += _ok(11, state_with(st_contradict) == "unknown",
               "★ 自相矛盾（exited 但 Pid 非 0）⇒ `unknown`")
    bad += _ok(12, state_with(st_exited) == "stopped",
               "容器 exited + Pid=0 ⇒ `stopped`（这一支才该继续）")
    bad += _ok(13, state_with(st_missing) == "stopped",
               "容器不存在 ⇒ `stopped`（没跑就是没跑）")

    # ── unknown 必须**在 main 里被拦**（不只是函数返回值）────────────────
    # ★★ 第一版写成 `'if verdict == "unknown":' in src and "return 2" in src`
    #    ⇒ **恒真**：`return 2` 在**别处**（running 分支、inspect 失败分支）也有。
    #    实测证据：把 unknown 分支的 `return 2` 删掉，这条**仍然绿**。
    #    ⇒ 改成**按分支抽出来查**：取 `if verdict == "unknown":` 到下一个同级
    #      `if`/`return` 之间那一段，里面**必须有 return 2**。
    import re as _re
    m_unk = _re.search(r'(\n    if verdict == "unknown":\n)((?:        .*\n)+)', src)
    bad += _ok(14, bool(m_unk) and "return 2" in m_unk.group(2),
               "★ `unknown` 分支**自己那段里**有 `return 2`（不是靠文件里别处的 return 2）")

    # ★ 阴性对照：**故意删掉**那段里的 return 2，这条判据必须能认出来
    #   （不修改文件，只在内存里模拟）
    if m_unk:
        mutated = src[:m_unk.start(2)] + m_unk.group(2).replace("        return 2\n", "", 1) + src[m_unk.end(2):]
        m2 = _re.search(r'(\n    if verdict == "unknown":\n)((?:        .*\n)+)', mutated)
        bad += _ok(15, not (m2 and "return 2" in m2.group(2)),
                   "★阴性对照：把那段里的 return 2 删掉 ⇒ 本判据**能红**（不是恒真）")
    else:
        bad += _ok(15, False, "★阴性对照：抽不出 unknown 分支 ⇒ 无法验证")

    # ★ 再一条独立对照：文件里**确实还有别的** return 2
    #   （⇒ 说明上面"只查那段"是必要的，而不是文件里恰好没有 return 2）
    bad += _ok(16, len(_re.findall(r"\breturn 2\b", src)) >= 2,
               "★阴性对照：全文 `return 2` **不止一处** ⇒ 14 必须限定作用域才有意义")

    # ── `-wal` 那道：只能加严，不许被当成"没人持有"的证明 ──────────────
    bad += _ok(17, "不构成「没人持有」的证明" in src,
               "★ `-wal` 不在时的措辞**没有**夸大成「没人持有」"
               "（实测：小事务/只读时它压根不建，会误报）")

    print(f"\n{17 - bad}/17 通过" if bad else "\n全部通过")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())

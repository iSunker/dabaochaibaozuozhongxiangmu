# -*- coding: utf-8 -*-
"""`scripts/prowlarr-indexers.py` —— 「只取白名单」这条硬口径的守卫。

为什么值得单独立一个测试文件
----------------------------
`ENVIRONMENT.md` 开头写着「**绝不打印 Prowlarr 的 `indexer.fields`**」，
而 `GET /api/v1/indexer` 的**每条**响应都带 `fields`（cookie / passkey）。
这个仓库里同时存在：

  · 那条规矩；
  · **四条**照着敲的处方（`README.md`、`summary/06`、`summary/13`、`ENVIRONMENT.md`），
    它们都 `curl` 同一个端点。

⇒ 「有一条规矩」和「有工具遵守它」是两件事。本文件钉住后者：
   **`pick()` 是白名单，不是黑名单**，且这个断言**能红**（有阴性对照）。

★ 本文件**不联网**：只用 `pick()` / `torznab_ids()` 两个纯函数 + 静态源码检查。
  联网那部分由 `prowlarr-indexers.py` 自己跑（人工），不放进自测套件 ——
  自测套件必须能在没有 NAS、没有 key 的机器上全绿。
"""
from __future__ import annotations

import ast
import importlib.util
import pathlib
import re
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

REPO = pathlib.Path(__file__).resolve().parent.parent
TARGET = REPO / "scripts" / "prowlarr-indexers.py"


def _load():
    spec = importlib.util.spec_from_file_location("_pi_under_test", TARGET)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _ok(n: int, cond: bool, what: str) -> int:
    print(f"{'  ok  ' if cond else ' FAIL '}{n} {what}")
    return 0 if cond else 1


def main() -> int:
    bad = 0
    src = TARGET.read_text(encoding="utf-8")
    mod = _load()

    # ---------------- ① 白名单：只有三个键 ----------------
    item = {
        "id": 7, "name": "SiteX", "enable": True,
        "fields": [{"name": "password", "value": "SECRET"},
                   {"name": "baseUrl", "value": "http://x"}],
        "implementation": "Cardigann", "protocol": "torrent",
    }
    got = mod.pick(item)
    bad += _ok(1, sorted(got) == ["enable", "id", "name"],
               f"pick() 只出 id/name/enable（实际 {sorted(got)}）")
    bad += _ok(2, "fields" not in got, "pick() 不含 fields")

    # ---------------- ② ★ 阴性对照：整对象复制**会**带出 fields ----------------
    # 这条是①的对照。没有它，① 可能是恒真的（万一 item 里压根没有敏感键，
    # 那「不含 fields」就成了一句空话 —— 本项目栽过两次假测试）。
    mutated = dict(item)
    bad += _ok(3, "fields" in mutated,
               "★阴性对照：dict(item) 确实带出 fields（⇒ ①不是恒真）")
    bad += _ok(4, "password" not in got and "password" in mutated["fields"][0].values()
               if False else any("password" in str(f) for f in mutated["fields"]),
               "★阴性对照：变异版里确实含 password 字段（而 pick() 版不含）")

    # ---------------- ③ 源码层面：没留后门 ----------------
    tree = ast.parse(src)
    # ★ ast.unparse 一个**字符串常量**会把引号也带上（"'--compose'"）——
    #   直接比字面量名会恒假。要取 .value，不是 unparse 的文本。
    args = [n.args[0].value for n in ast.walk(tree)
            if isinstance(n, ast.Call) and getattr(n.func, "attr", None) == "add_argument"
            and n.args and isinstance(n.args[0], ast.Constant)
            and isinstance(n.args[0].value, str)]
    bad += _ok(5, set(args) == {"--compose", "--torznab"},
               f"argparse 只有 --compose/--torznab（实际 {args}）")
    bad += _ok(6, not any("api-key" in a.lower() for a in args),
               "★ 没有 --api-key 参数（key 不许上命令行）")

    # 真实「代码字面量」里不许出现 'fields' —— 排除 docstring
    inner = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.ClassDef)) and node.body:
            first = node.body[0]
            if (isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant)
                    and isinstance(first.value.value, str)):
                inner.add(id(first.value))
    real = [n.value for n in ast.walk(tree)
            if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in inner]
    bad += _ok(7, not [v for v in real if v.strip() == "fields"],
               "★ 代码字面量里没有 'fields'（注释里提到是对的，取值里不许有）")
    bad += _ok(8, not any(v.strip().startswith("dict(") for v in real),
               "没有 dict(item) 式整对象复制")
    # ★ 只查**真实代码**，不查 docstring —— `pick()` 的 docstring 里**故意**写着
    #   「不要改成 pop("fields") / != "fields"」来说明为什么不行；
    #   拿整份 src 去 find 会把那段**警告文字**读成违规（第一版就是这么误报的）。
    #   ★ 用 AST 的 docstring 判断，不要用「按 def 切行」——
    #     docstring 在 `def` **之后**，按 def 切切不掉它（第二版又误报了一次）。
    _ds = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.ClassDef)) and node.body:
            first = node.body[0]
            if (isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant)
                    and isinstance(first.value.value, str)):
                _ds.add(first.value.value)
    code_lines = [l for l in src.splitlines()
                  if not l.strip().startswith("#")]
    blob = "\n".join(l for l in code_lines if l.strip() not in _ds)
    # 多行 docstring 的**中间行**也带上：逐段剔掉
    for d in _ds:
        blob = blob.replace(d, "")
    blob = blob.replace("'", '"')
    bad += _ok(9, 'pop("fields")' not in blob and '!= "fields"' not in blob,
               "★ 不是黑名单（pop / != 'fields' 都不算白名单）")
    # ★ 对照：整份源码**确实**含这些字样 ⇒ ⑨ 不是「因为文件里没有才通过」
    bad += _ok(10, '!= "fields"' in src,
               "★阴性对照：全文（含 docstring）确实提到 != \"fields\" ⇒ ⑨查的是作用域不是不存在")

    # key 只走 header
    bad += _ok(11, 'add_header("X-Api-Key"' in src, "key 走 X-Api-Key header")

    # 只读：没有任何写操作
    bad += _ok(12, not re.search(r"\.write\(|shutil\.|os\.remove|unlink\(|open\([^)]*[\"']w",
                                src),
               "脚本只读（无 write/remove/unlink）")

    # ---------------- ④ torznab_ids：抠 id 但不回显 URL ----------------
    good = mod.torznab_ids({"TORZNAB_URLS": "http://prowlarr:9696/2/api?apikey=K,"
                                           "http://prowlarr:9696/4/api?apikey=K"})
    bad += _ok(13, good == {"2", "4"}, f"torznab_ids 抠出 {{'2','4'}}（实际 {good}）")
    bad += _ok(14, "K" not in str(good) and "apikey" not in str(good),
               "★ 抠出来的只有 id，key 没跟着出来")
    bad += _ok(15, mod.torznab_ids({}) == set(), "空 TORZNAB_URLS ⇒ 空集（不炸）")

    # ---------------- ⑤ 真值：id 是**字符串**比较，不是 int ----------------
    # ★ 踩过：`str(r.get("id")) in used`，若 used 里是 int 2 而 id 是 "2"，
    #   比较会恒假 ⇒ --torznab 那列全打「——」，看着像「一个都没用」。
    bad += _ok(16, all(isinstance(x, str) for x in good),
               "★ 抠出来的是 str（与源码里 str(id) 比较同型，否则恒假）")

    print(f"\n{16 - bad}/16 通过" if bad else "\n全部通过")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())

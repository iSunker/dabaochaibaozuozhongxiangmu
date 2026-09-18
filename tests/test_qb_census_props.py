# -*- coding: utf-8 -*-
"""钉住 `qb-census-savepath.py` 属性 dump 的**三种形态分得开**（#63 的修 ⇒ #64 的回归）。

背景：qB v4.6.5 的 `/api/v2/torrents/properties` **不返回 content_path**（实测 10/10）。
旧代码 `v = pr.get(k)` → None → `depth(None, 4)` → 印「(空)」，而注释又把它解释成
「content_path 为空是**信号**（qB 没能建立起内容路径）」—— 于是一个**取错接口**的
问题被印成了 qB 的病症。假读数比不读数更坏：它让人去查「qB 为什么不知道」。

012bcbb 的修法：**缺键有它自己的字面**。
    缺键   → 「(字段不存在)」      ← 新增
    真空串 → 「(空)」
    有值   → 前 4 段

★★ 红过再绿（#64 的判据，手工一次）：
    git checkout 012bcbb^ -- scripts/qb-census-savepath.py   # 把修法回退掉
    python tests/test_qb_census_props.py                     # 必须**红**（§① §③ 会红）
    git checkout HEAD -- scripts/qb-census-savepath.py       # 恢复
    python tests/test_qb_census_props.py                     # 必须绿
  红的是「缺键被印成 (空)」那一族；**一份在旧代码上也全绿的用例等于没测到东西**。

★ 为什么用 temp 树 + 假 .env（而不是直接载仓库里那份）
  被测脚本在**模块顶层**读 `<仓库>/.env`，读不到就 `sys.exit(1)`；而 importlib 载入时
  `SystemExit` 被吞掉 ⇒ 模块载不动、`main` 根本不存在。把真文件**逐字节拷**到
  `<tmp>/scripts/` 下、配一份 `<tmp>/.env`，`REPO = __file__/../..` 就指到 tmp
  ⇒ 这份测试**不依赖仓库里有没有真 .env**，也不碰真凭据（`call` 全程打桩）。
  拷的是**真的那个文件**（tests/README 的规矩：别切源码再 exec）。
"""
from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import pathlib
import shutil
import sys
import tempfile

REPO = pathlib.Path(__file__).resolve().parent.parent
SUBJECT = REPO / "scripts" / "diag" / "qb-census-savepath.py"

try:
    sys.stdout.reconfigure(encoding="utf-8")   # GBK 控制台会炸（tests/README.md）
except Exception:
    pass

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


# ── 沙箱：把真文件拷进 temp 树，配一份假 .env ────────────────────────────────
#   凭据用变量拼出来（tests/README：闸门自己的样本不许在源码里留字面量）。
_TD = pathlib.Path(tempfile.mkdtemp(prefix="qbcensus-"))
(_TD / "scripts").mkdir()
shutil.copy2(SUBJECT, _TD / "scripts" / SUBJECT.name)
(_TD / ".env").write_text(
    "NAS_IP=127.0.0.1\nQBIT_USER=u\nQBIT_PASSWORD=%s\n" % ("FAKE" + "PW"),
    encoding="utf-8")

_spec = importlib.util.spec_from_file_location("qb_census_mod", _TD / "scripts" / SUBJECT.name)
mod = importlib.util.module_from_spec(_spec)
sys.modules["qb_census_mod"] = mod          # ★ 必须早于 exec_module（tests/README）
with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
    try:
        _spec.loader.exec_module(mod)
    except SystemExit:
        pass

# ── 合成现场 ────────────────────────────────────────────────────────────────
#   ★ info 行里**故意带上 content_path** —— 真机上它就在那儿。于是「properties 缺键
#     印成 (字段不存在)」这一条同时证明了：取的是 properties 那个接口，没有偷偷退回 info。
PATH5 = "/volume1/video/download/reseed_singles/HDFans"        # 第 5 段 = 站点名
NAME = "某部片子.2026.2160p"
INFO = [
    {"hash": "a" * 40, "state": "error", "name": NAME, "save_path": PATH5,
     "content_path": PATH5 + "/" + NAME},
    {"hash": "b" * 40, "state": "stalledUP", "save_path": "/volume1/video/download/reseed/huya"},
]
PREF = {"save_path": "/volume1/video/download/reseed",
        "temp_path": "", "temp_path_enabled": False}

# 真机形状：有 save_path，download_path 是真空串，**压根没有 content_path**。
PROPS = {"save_path": PATH5 + "/" + NAME,
         "download_path": "",
         "total_size": 4522952870, "total_downloaded": 1074071,
         "seeds": 0, "peers": 0, "dl_speed": 0}


def run(props, fail_props=False):
    """跑一次真的 `main()`，`call()` 换成桩。返回 (rc, stdout, 被调过的接口)。"""
    seen = []

    def fake_call(path, data=None):
        seen.append(path)
        if fail_props and "/torrents/properties" in path:
            raise OSError("qB 不通")
        if path.endswith("/auth/login"):
            return b"Ok."
        if "/app/preferences" in path:
            return json.dumps(PREF).encode()
        if "/torrents/info" in path:
            return json.dumps(INFO).encode()
        if "/torrents/properties" in path:
            return json.dumps(props).encode()
        raise AssertionError("未预期的接口：%s" % path)

    mod.call = fake_call
    old_argv = sys.argv
    sys.argv = [SUBJECT.name]
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            rc = mod.main()
    finally:
        sys.argv = old_argv
    return rc, buf.getvalue(), seen


def props_block(out):
    """只取属性 dump 那一段（前半段的 save_path 桶是另一回事）。"""
    return out.split("=== 挑 1 条", 1)[-1]


def line_for(block, key):
    """按**键名**取那一行（不按列宽 —— 改个 `%-18s` 不该让测试红）。"""
    for ln in block.splitlines():
        s = ln.strip()
        if s.startswith(key + " "):
            return s
    return None


def val_of(block, key):
    ln = line_for(block, key)
    return ln[len(key):].strip() if ln else None


print("=== ① 真机形状：properties 没有 content_path ===")
rc, out, seen = run(PROPS)
ck("main 正常返回（桩没炸）", rc == 0, out[-300:])
b = props_block(out)
ck("★ 缺键 → 「(字段不存在)」", val_of(b, "content_path") == "(字段不存在)",
   repr(val_of(b, "content_path")))
ck("★★ 不许印成「(空)」（这是 #63 那条假读数本身）",
   "(空)" not in (line_for(b, "content_path") or ""), repr(line_for(b, "content_path")))
ck("   真空串的 download_path 仍印「(空)」（两种形态在同一段里分得开）",
   val_of(b, "download_path") == "(空)", repr(val_of(b, "download_path")))
ck("★ 缺键时给出改口的指引", "不在这个接口的返回里" in out)
ck("   properties 接口真的被调过", any("/torrents/properties" in c for c in seen), repr(seen))
ck("★★ 没偷偷退回 info —— 本现场的 info 行里其实**有** content_path",
   all("content_path" in t for t in INFO if t["state"] == "error")
   and val_of(b, "content_path") == "(字段不存在)")

print("\n=== ② 脱敏：第 5 段（站点名）与资源名都不许出现 ===")
ck("   save_path 只印前 4 段", val_of(b, "save_path") == "/volume1/video/download/reseed_singles",
   repr(val_of(b, "save_path")))
ck("★★ 整份输出里没有站点名（第 5 段）", "HDFans" not in out)
ck("★★ 整份输出里没有资源名", NAME not in out)

print("\n=== ③ properties 的 content_path 有值 ===")
rc, out3, _ = run(dict(PROPS, content_path=PATH5 + "/" + NAME))
b3 = props_block(out3)
ck("有值 → 只印前 4 段", val_of(b3, "content_path") == "/volume1/video/download/reseed_singles",
   repr(val_of(b3, "content_path")))
ck("★ 键在 ⇒ 不出那句指引", "不在这个接口的返回里" not in out3)
ck("   也不该有「(字段不存在)」", "(字段不存在)" not in b3)
ck("★ 有值档同样不泄漏站点名 / 资源名", "HDFans" not in out3 and NAME not in out3)
ck("   total_size 印的是数", val_of(b3, "total_size") == "4522952870", repr(val_of(b3, "total_size")))

print("\n=== ④ properties 的 content_path 是真空串（键在、值为空） ===")
rc, out4, _ = run(dict(PROPS, content_path=""))
b4 = props_block(out4)
ck("真空串 → 「(空)」（与缺键分得开）", val_of(b4, "content_path") == "(空)",
   repr(val_of(b4, "content_path")))
ck("★ 键是全的 ⇒ 整段一个「(字段不存在)」都不该有", "(字段不存在)" not in b4)
ck("   键在 ⇒ 不出那句指引", "不在这个接口的返回里" not in out4)

print("\n=== ⑤ ★ 这里钉的是**现状**，不是期望：键在、值是 null ===")
rc, out5, _ = run(dict(PROPS, content_path=None))
b5 = props_block(out5)
ck("★ null 仍印「(空)」—— 012bcbb 的修法**没覆盖这一格**（null 与空串同形）",
   val_of(b5, "content_path") == "(空)", repr(val_of(b5, "content_path")))
ck("   但键在 ⇒ 那句「不在这个接口的返回里」**不许**出（判据是 `k not in pr`，不是「空值」）",
   "不在这个接口的返回里" not in out5)
#   真机今天返回的是**空串**，所以上面这一格现在还咬不到人；把它写下来是为了
#   下次动这段时知道边界在哪 —— 它是「现状」，不是「期望」。

print("\n=== ⑥ 属性接口炸了不许带走整趟普查 ===")
rc, out6, _ = run(PROPS, fail_props=True)
ck("不抛、给一句话", rc == 0 and "属性接口失败" in out6, out6[-200:])
ck("★ 前半段（state 分布 / 桶）照样打完", "state 分布" in out6 and "选中" in out6)

print("\n=== ⑦ 收尾：出口码 ===")
ck("rc 全是 0", run(PROPS)[0] == 0 and run(PROPS, fail_props=True)[0] == 0)

print(f"\n{'=' * 60}")
print(f"断言 {_ok + _bad} 条：{_ok} 过 / {_bad} 失败")
sys.exit(0 if _bad == 0 else 1)

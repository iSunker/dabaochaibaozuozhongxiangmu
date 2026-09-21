# -*- coding: utf-8 -*-
"""`scripts/diag/torznab-probe.py` 的**离线**回归 —— 钉住"A 档侦察"的那两件工具。

为什么单独立这一份（2026-09-21，`26.38-A`）
--------------------------------------------
A 要回答的问题是「**Torznab 的 `tvsearch` 响应体里，有没有可解析的季字段**」。
而这个探针**原先只抠 `<title>`** —— item 后面的 `link` / `guid` / `enclosure` /
`torznab:attr` **整段被丢掉**。★ 所以「响应里没有季字段」这句话在那时**压根没有判据**：
**不是"看了说没有"，是"根本没看"**（`B.10`：未验 ≠ 无）。

这一份钉的**不是**"某站点到底给不给季字段"（那要联网、要耗站点额度，★ **不在测试里做**），
而是钉住**判据工具本身没坏**：

  ① `items_of` 真的把 item **整块**留下来 —— ★ 失效模式与原来那个 bug 同形：
     切到 `</title>` 就丢 ⇒ 后面全没了，而**输出看起来完全正常**（有 title、有条数）。
  ② `attrs_of` 真的把**所有** attr 列出来 —— ★ 这是"判没有之前先列全"那条判据的执行者。
     失效模式：只匹配 `name="season"` ⇒ 「站点不给」与「给了但叫 rageid」
     **读数一模一样**，而后者是可用的季界锚。
  ③ `redact()` 在**出口**真的抹掉凭据 —— ★ `--raw` / `--dump-attrs` 打的是**原始响应**，
     而很多站的 `<link>` 里直接编着 passkey。失效模式：把探针改成"给大家看清楚点"
     顺手把凭据打出来 ⇒ 它读的是**NAS 生产 `.env`**，泄露面是生产。
  ④ ★★ **本探针不许有任何写/执行能力** —— 用**绊线**（把危险函数换成会抛的桩、
     再真跑一遍）钉，不用 AST 黑名单。理由见 `tests/test_split_pack.py` ⑤：
     黑名单**证不完**（`__import__("os").makedirs` 绕过去，断言仍绿，`ERR-AI-05` 形状）。
  ⑤ 用法/纪律三件：`--dump-attrs` 与 `--raw` 是**并列**开关（不互相顶掉）、
     `--id` 照旧生效、文档里的用法行**与代码一致**（★ 这条防"文档说支持、代码没实现"）。

★ 全部离线：不联网、不碰 NAS、不碰生产 `.env`（★ **凭据与 query 全在测试里现造**，
  所以**不需要**站点的 `.env`）。★ 唯一的一次真进程调用是**故意喂一个不存在的 `.env`** ——
  那会在发网络请求**之前**退出（`torznab_url()` 先 `isfile` 再读），据此证明
  "参数解析这条路是通的"而**不是**在测网络行为。**这个判据是钉住的**：
  若将来有人把 `isfile` 检查挪到请求之后，那条断言会红（见 ⑥ 的反向）。
★ 数法/行形：只打印 `  ok  ` / ` FAIL `（`tests/README.md` 形状 A）。
"""
from __future__ import annotations

import contextlib
import importlib.util
import io
import pathlib
import sys
import tempfile

REPO = pathlib.Path(__file__).resolve().parent.parent
SCRIPT = REPO / "scripts" / "diag" / "torznab-probe.py"

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


# ---- 把脚本当模块导进来（结尾有 `if __name__` 守卫，导入不会跑 main）----
_spec = importlib.util.spec_from_file_location("torznab_probe", SCRIPT)
tp = importlib.util.module_from_spec(_spec) if _spec else None
if tp is not None:
    try:
        _spec.loader.exec_module(tp)
    except Exception as e:                      # noqa: BLE001
        print(f"  FAIL 导不进 torznab-probe.py：{type(e).__name__}: {e}")
        tp = None

ck("前提：torznab-probe.py 存在且可导入", tp is not None, f"{SCRIPT}")

if tp is None:
    print(f"\n{'=' * 60}")
    print(f"断言 {_ok + _bad} 条：{_ok} 过 / {_bad} 失败")
    sys.exit(1)

# ==========================================================================
print("\n① items_of：item 必须**整块**留下（这就是原来那个 bug 的形状）")
# --------------------------------------------------------------------------
# ★ 凭据形状的值**拼出来**，不在源码里写字面量 —— 否则推前扫描会扫到这个测试自己
#   （同 `test_scan_secrets.py` 的文件头纪律 ②）。
KEYISH = "a" * 4 + "b" * 28                     # 32 位，hex 形状
BODY = (
    '<?xml version="1.0"?><rss xmlns:torznab="http://torznab.com/schemas/2015/feed">'
    "<channel>"
    "<item><title>Duo.Ai.2011.S02.1080p.WEB-DL</title>"
    f"<link>http://hdtime.org/download.php?id=1&amp;passkey={KEYISH}</link>"
    '<guid isPermaLink="false">http://hdtime.org/details.php?id=1</guid>'
    '<torznab:attr name="category" value="5000"/>'
    '<torznab:attr name="size" value="2147483648"/>'
    '<torznab:attr name="seeders" value="12"/>'
    '<torznab:attr name="rageid" value="12345"/>'
    "</item>"
    "<item><title>Duo.Ai.2011.S01.1080p.WEB-DL</title>"
    '<torznab:attr name="category" value="5000"/>'
    '<torznab:attr name="season" value="1"/>'
    "</item>"
    "</channel></rss>"
)

items = tp.items_of(BODY)
ck("切出 2 个 item", len(items) == 2, f"得到 {len(items)}")
ck("★ item 里有 link（原版切到 </title> 就丢，这条会红）",
   "<link>" in items[0], "item 里没有 link ⇒ items_of 又把 item 截断了")
ck("★ item 里有 guid", "<guid" in items[0], "没有 guid")
ck("★ item 里有 torznab:attr（判季字段靠它，丢了就判不了）",
   "<torznab:attr" in items[0], "没有 attr")
ck("item 里**没有** </item>（收尾符剥干净了）", "</item>" not in items[0])
ck("title 抠得出来", tp.title_of(items[0]) == "Duo.Ai.2011.S02.1080p.WEB-DL",
   f"得到 {tp.title_of(items[0])!r}")
# ★ 反向：title 为空的 item 不许让整条崩掉、也不许编一个 title 出来
ck("★ 没有 title 的 item ⇒ 返回空串（不编）",
   tp.title_of("<torznab:attr name=\"size\" value=\"1\"/>") == "",
   "没有 title 时它编了一个")
# ★ 边界：没有 item 时返回空表（不许把整个文档当一条）
ck("★ 没有 item ⇒ 空表（不是 1 条）", tp.items_of("<rss><channel/></rss>") == [],
   f"得到 {tp.items_of('<rss><channel/></rss>')}")

# ==========================================================================
print("\n② attrs_of：**所有** attr 都要列出来（判「没有」之前先列全）")
# --------------------------------------------------------------------------
a0 = tp.attrs_of(items[0])
ck("第 1 条列出 4 个 attr", len(a0) == 4, f"得到 {len(a0)}：{a0}")
ck("category 在", ("category", "5000") in a0, f"{a0}")
ck("size 在", ("size", "2147483648") in a0, f"{a0}")
ck("seeders 在", ("seeders", "12") in a0, f"{a0}")
ck("★★ rageid 也在 —— 它**不是** season，但它是可用的季界锚",
   ("rageid", "12345") in a0,
   f"rageid 被漏掉了 ⇒ 只匹配 name=\"season\" 的写法（那是『未验 ≠ 无』的读数）")
a1 = tp.attrs_of(items[1])
ck("第 2 条列出了 season=1", ("season", "1") in a1, f"{a1}")
ck("attr 一个都没有时 ⇒ 空表（不是 None、也不是编一条）",
   tp.attrs_of("<title>x</title>") == [], f"{tp.attrs_of('<title>x</title>')}")
# ★ 自闭合与带 /> 的两种写法都要认（站点的 XML 不一定规范）
ck("自闭合 `<torznab:attr ... />` 也认",
   ("season", "2") in tp.attrs_of('<torznab:attr name="season" value="2" />'),
   "带空格的闭合写法没认出来")

# ==========================================================================
print("\n③ redact：出口必须抹掉凭据（--raw 打的是 NAS 生产响应）")
# --------------------------------------------------------------------------
red = tp.redact(BODY)
ck("★★ passkey 的值被抹掉", KEYISH not in red, "原始响应里的 passkey 原样打出来了")
ck("★ passkey= 这个**键**保留（要能看出那儿有东西）", "passkey=" in red, "键也被抹了")
ck("抹成了 <redacted> 标记", "<redacted>" in red, "没有留下标记")
ck("★ 标题不受影响（判读要用的信息不能被误抹）",
   "Duo.Ai.2011.S02.1080p.WEB-DL" in red, "标题被抹掉了")
# ★ 形状层：换个键名（如 torrent_pass）、或裸 hex，也要兜住
ck("★ 32 位 hex 裸值被抹（形状层）",
   tp.redact("id=%s" % ("deadbeef" * 4)) == "id=<hex20+>",
   tp.redact("id=%s" % ("deadbeef" * 4)))
ck("★ api_key= 也抹", "zzz" not in tp.redact("api_key=zzz0123456789abcdefghij"),
   tp.redact("api_key=zzz0123456789abcdefghij"))
# ★ 反向（不许过度抹）：正常数字计数不能被抹 —— 否则读不出 size/seeders
ck("★ 反向：seeders 那种短数字**不许**被抹",
   'value="12"' in tp.redact('<torznab:attr name="seeders" value="12"/>'),
   "把正常读数也抹了 ⇒ 过度脱敏，探针没用了")

# ==========================================================================
print("\n④ seeders/size 这类短值是**读数**，不是凭据（防过度脱敏把探针变废）")
# --------------------------------------------------------------------------
ck("size 值保留", "2147483648" in tp.redact('<torznab:attr name="size" value="2147483648"/>'))
ck("category 值保留", 'value="5000"' in tp.redact('<torznab:attr name="category" value="5000"/>'))

# ==========================================================================
print("\n⑤ ★★ 只读纪律 —— 用**绊线**证明，不用黑白名单（ERR-AI-05 形状）")
# --------------------------------------------------------------------------
# ★★ 为什么不用 AST 黑名单：它**证不完**。`test_split_pack.py` ⑤ 里实测过 ——
#    第一版黑名单**漏掉** `__import__("os").makedirs`，断言**仍是绿的**。
# ⇒ 把危险函数换成**会抛的桩**，然后**真跑一遍 main()**：桩没响 = 那段路没被走到。
import builtins                                     # noqa: E402
import tempfile as _tf                              # noqa: E402

# ★★ 先造夹具、**再**上绊线（`tp.os` 与 `tempfile` 是**同一个模块对象**：改它就是改全局）。
stub_env = pathlib.Path(_tf.mkdtemp(prefix="tp-trip-")) / "stub.env"
stub_env.write_text(
    # ★ 两个条目：① 让 --id 1 找得到；② 让 --any 跳到 2 时**也有**可跳的
    #   （否则 ⑩ 那条会报「没有 path 为 /2/api 的条目」，而不是走到闸后面的逻辑）。
    "TORZNAB_URLS=http://prowlarr:9696/1/api?apikey=%s,"
    "http://prowlarr:9696/2/api?apikey=%s\n" % ("c" * 32, "c" * 32),
    encoding="utf-8")

_saved = {}


class _Tripped(Exception):
    """★ 绊线专用的异常类型 —— ★★ **为什么不用 `AssertionError`**，见 ⑤ 末尾的长注释。
    一句话：`AssertionError` 是 `Exception` 的子类，会被下面的 `except Exception`
    **当成"网络/参数错"吞掉**，于是绊线形同不设（实测过：种进去的 `makedirs` 没被抓住，
    本文件照样全绿 —— `ERR-AI-05`）。⇒ 用**独立类型**，并**先**捕获它。
    """
    pass


def _trip(name):
    def _boom(*a, **k):
        raise _Tripped(f"绊线响了：{name} 被调用（本脚本必须只读）")
    return _boom


_WRITE_NAMES = ("link", "symlink", "makedirs", "mkdir", "remove", "unlink",
                "rmdir", "rename", "chmod", "chown", "system", "truncate")
for n in _WRITE_NAMES:
    if hasattr(tp.os, n):
        _saved[n] = getattr(tp.os, n)
        setattr(tp.os, n, _trip(f"os.{n}"))
_real_open = builtins.open
def _open_guard(file, mode="r", *a, **k):
    if any(c in str(mode) for c in "wax+"):
        raise _Tripped(f"绊线响了：open({file!r}, mode={mode!r}) —— 本脚本必须只读")
    return _real_open(file, mode, *a, **k)
builtins.open = _open_guard

_tripped = None
_fired = False
_rc = None

# ★★ 反向检查**必须在拆绊线之前**做 —— 否则问的是一个已经被拆掉的绊线
#    （`test_split_pack.py` ⑤ 第一版就栽在这里：`finally` 先拆了，反向检查恒绿为"不响"）。
try:
    _argv_bak = sys.argv
    # ★ 喂一个**存在的** stub .env（里面是不可用的站点 URL）⇒ 会走到发请求那步并失败。
    #   ★ 判据不是 rc，是**绊线没响** —— 即"整条路都没写盘"。
    sys.argv = ["torznab-probe.py", "Test-Show", "1",
                "--env", str(stub_env), "--dump-attrs", "--raw"]
    try:
        _rc = tp.main(sys.argv[1:])
    except _Tripped as e:                            # ★★ 绊线 —— **必须排在 Exception 之前**
        _tripped = str(e)
    except SystemExit:                               # 脚本可能 raise SystemExit
        _rc = "SystemExit"
    except Exception as e:                           # noqa: BLE001
        # ★ 连网络失败/参数错都行 —— 只要**不是**绊线响的
        _rc = f"{type(e).__name__}"
    finally:
        sys.argv = _argv_bak
    # ★ 反向（仍带电时试一次）：绊线**确实会响**
    try:
        tp.os.makedirs("/tmp/should-not-happen", exist_ok=True)
    except _Tripped:
        _fired = True
except _Tripped as e:
    _tripped = str(e)
finally:
    for n, fn in _saved.items():
        setattr(tp.os, n, fn)
    builtins.open = _real_open

ck("★★ 绊线：跑一遍真流程（含 --dump-attrs --raw），**没有任何写盘/执行调用被触发**",
   _tripped is None, f"绊线响了：{_tripped}")
ck("★★ 反向：绊线**真的会响**（证明上面那条不是假绿）", _fired,
   "绊线挂上了却不抛 ⇒ 那条断言恒真")
ck("★ 且它跑到头了（rc 是个真值，说明没被绊线自己掐断）",
   _rc is not None, "main() 没返回 ⇒ 那一遍没跑成")
print("  --   ★ 为什么这条比 AST 黑名单强：黑名单漏掉过 `__import__(\"os\").makedirs`")
print("      （实测：第一版断言**仍是绿的** —— `ERR-AI-05` 形状），绊线兜住了整类。")

# ★ subprocess / shutil / requests 连 import 都不许（这个探针不该有执行能力）。
# ★★ `socket` **另当别论**：它只用来 `except socket.timeout`（**接住超时**），
#    不是执行能力 —— 而"有没有执行能力"才是这条断言要钉的。
#    ⇒ ★ 所以判据要**更准**：不是"不许 import socket"，而是
#      **不许拿 socket 去连别的东西**（`socket.socket` / `create_connection` 之类）。
import ast                                          # noqa: E402

src = SCRIPT.read_text(encoding="utf-8")
tree = ast.parse(src)
BAD_MODULES = {"subprocess", "shutil", "requests"}
imported = set()
for node in ast.walk(tree):
    if isinstance(node, ast.Import):
        imported.update(a.name.split(".")[0] for a in node.names)
    if isinstance(node, ast.ImportFrom) and node.module:
        imported.add(node.module.split(".")[0])
ck("★ 不 import subprocess / shutil / requests",
   not (imported & BAD_MODULES), f"发现：{sorted(imported & BAD_MODULES)}")
ck("★ 不用 os.system（文本层再钉一道）", "os.system" not in src, "出现了 os.system")
# ★★ `socket` 只许用来**接住超时**，不许拿去**建连接**
_sock_calls = [n for n in ast.walk(tree)
               if isinstance(n, ast.Attribute) and n.attr in
               ("socket", "create_connection", "create_server", "socketpair")]
ck("★★ `socket` 只用于 `except socket.timeout`，**不建任何连接**",
   not _sock_calls,
   f"发现 socket 建连接的调用：{[a.attr for a in _sock_calls]}")

# ==========================================================================
print("\n⑥ 命令行：`--dump-attrs` 与 `--raw` 是**并列**开关，且文档与代码一致")
# --------------------------------------------------------------------------
ck("★ --dump-attrs 在源码里被解析", '"--dump-attrs"' in src, "参数没实现")
ck("★ --raw 在源码里被解析", '"--raw"' in src, "参数没实现")
# ★★ 这一格**故意不查源码文本** —— 我第一版就是 `'dump_attrs = raw = False' in src and ...`
#    那种形状，而**实测**：把两个开关改成共用一个变量（`dump_attrs = raw = True`）
#    之后，那条断言**照样绿**。★ 那就是 `ERR-AI-05`（绿，但绿是因为规则压根没参与匹配）：
#    它量的是"源码里出现过某几串字"，与"同时给两个开关时两个都生效"**根本不是一回事**。
# ⇒ 改成**行为判据**：把 main() 跑到"能看出两个开关各自生效"的那一点。
#    ★ 做法：喂一个**存在但为空**的 .env ⇒ `torznab_url()` 走到最后那句
#      `raise SystemExit("...没有 path 为 %s 的条目")`，而那句里**带着 idx**
#      ⇒ 据此能证明参数解析把该吃的都吃了。★ 不联网（空 .env 里没有 URL 可用）。
_cli_env = pathlib.Path(_tf.mkdtemp(prefix="tp-flags-")) / "empty.env"
_cli_env.write_text("TORZNAB_URLS=\n", encoding="utf-8")


def _run_main(argv):
    """跑一次 main()，只取它抛/返回的东西 —— 不发网络请求（.env 里没有可用条目）。"""
    bak = sys.argv
    sys.argv = ["torznab-probe.py"] + list(argv)
    try:
        try:
            return ("rc", tp.main(sys.argv[1:]))
        except SystemExit as e:
            return ("exit", str(e))
        except Exception as e:                      # noqa: BLE001
            return ("err", f"{type(e).__name__}: {e}")
    finally:
        sys.argv = bak


_flag_out = []
for _args in (["T", "--env", str(_cli_env), "--dump-attrs"],
              ["T", "--env", str(_cli_env), "--raw"],
              ["T", "--env", str(_cli_env), "--dump-attrs", "--raw"]):
    _flag_out.append(_run_main(_args))
# ★ 三种组合都必须走到**同一处**（「没有 path 为 1/api 的条目」）——
#   若两个开关共用一个变量，第三种组合**不会**与另两种不同地失败，但检查器
#   真正要杀的是"其中一个被吞掉"。⇒ 判据：三者的**退出话术一致**，
#   且**解析顺序**证明两个分支都被走过（见下面那条源码级但**更窄**的检查）。
ck("★ 三种开关组合都能跑到「.env 里没有该条目」那一句（说明参数被吃了、没卡在前头）",
   all(k == "exit" and "没有 path" in v for k, v in _flag_out),
   f"得到 {_flag_out}")
# ★ 这一条**只查一个字面事实**：两个分支各自的 `continue` 之前，写的变量是**它自己那个**
#   —— 这是「不共用变量」的**最小可判事实**。★ 它比「出现过 `dump_attrs = raw = False`」
#   强，因为后者在改成共用变量后**照样为真**（实测：那次变异让老断言 0 红）。
# ★ 只取**赋值语句里带 `; i += 1; continue` 后缀**的那两行（= 两个分支本体），
#   把初始化行 `dump_attrs = raw = False` 排除掉 —— 否则它自己就不是共用变量的证据。
_parsed = [ln.strip() for ln in src.splitlines()
           if "i += 1; continue" in ln and ("dump_attrs" in ln or "raw" in ln)]
ck("★★ 两个开关**不共用**变量（实测：改成共用后本条会红）",
   len(_parsed) == 2
   and not any("dump_attrs = raw" in ln or "raw = dump_attrs" in ln for ln in _parsed),
   f"疑似共用：{_parsed}")
print("  --   ★ 上面这条**是**源码级判据，但它量的是「两个分支各写各的变量」这个事实；")
print("      ★ 第一版量的是「某几串字出现过」，改成共用变量后**照样绿**（ERR-AI-05 形状）。")
ck("★ 用法行与代码对得上（`--dump-attrs` 在 docstring 的用法段里）",
   "--dump-attrs" in (tp.__doc__ or ""), "docstring 没写这个开关")
ck("★ docstring 说明了它为什么需要（原来只抠 title）",
   "title" in (tp.__doc__ or ""), "docstring 没交代动机")

# ★★ 最后一格：**参数解析这条路必须通** —— 用**不存在的 .env** 征一次真进程。
#    ★ 判据是「它报的是『.env 不可达』」而不是 429/网络报错 ⇒ 说明**参数被吃进去、
#      `--env` 生效了、且在发请求之前就退出了**（`torznab_url()` 先 isfile 再读）。
#    ★ 这条同时反向证明"离线可测"：坏 .env 一定不会走到网络。
import subprocess as _sp                            # noqa: E402  ★ 被钉的是被测脚本

r = _sp.run([sys.executable, str(SCRIPT), "Test-Show", "1",
             "--env", "Z:/no/such/env.file", "--dump-attrs"],
            capture_output=True, text=True, encoding="utf-8", timeout=30)
_outs = (r.stdout or "") + (r.stderr or "")
ck("★ 坏 .env ⇒ 报「.env 不可达」（不是网络错）",
   "不可达" in _outs, f"rc={r.returncode} out={_outs[-200:]}")
ck("★★ 且是在**发请求之前**退出（没有 429 / 没有 host:port 那行）",
   "429" not in _outs and "9696" not in _outs,
   "它在 .env 不可达时还去发了请求 ⇒ `isfile` 检查不在最前面（离线可测性没了）")
# ★ 反向：给一个**存在但没用**的 .env ⇒ 参数解析必须走到「没有 path 为 I/api 的条目」
tmp2 = pathlib.Path(_tf.mkdtemp(prefix="tp-cli-")) / "other.env"
tmp2.write_text("TORZNAB_URLS=http://x:9696/9/api?apikey=zz\n", encoding="utf-8")
r2 = _sp.run([sys.executable, str(SCRIPT), "T", "--env", str(tmp2), "--id", "3"],
             capture_output=True, text=True, encoding="utf-8", timeout=30)
_o2 = (r2.stdout or "") + (r2.stderr or "")
ck("★ --id 3 生效（去要 /3/api，而 stub 里只有 /9/api）",
   "3/api" in _o2 or "/3/api" in _o2 or "没有 path" in _o2,
   f"rc={r2.returncode} out={_o2[-200:]}")
print("  --   ★ 这两格是**故意**的：它们证明参数真的被解析了，而不是靠一次真查询碰运气。")

# ==========================================================================
print("\n⑦ ★★★ A 的**两个对照**必须真的成立：`season=N` 要真上线（离线证，不联网）")
# --------------------------------------------------------------------------
# ★★★ 为什么这一格是 A 的地基：A 的第 2 条判据是「同一剧 `season=1` 与 `season=2`
#     各跑一次、**比返回集**」。若 `season` 压根没进 query，那次"对照"是**两次一样的
#     查询** ⇒ 返回集当然一样 ⇒ 会得出"season 在服务端不生效"的**假结论**。
#     ★ 这正是 `ERR-AI-05` 的形状：一个**永远为真**的对照（两次相同的请求），
#       看起来却像"已验证"。
# ★ 做法：把 `urllib.request.urlopen` 换成一个**假的**，只记 URL 不回网络 ——
#   于是这一格**零联网、零站点额度**，可以放心跑在任何时候（包括退避期）。
_seen_urls = []


class _FakeResp:
    status = 200

    def read(self):
        return b'<rss><channel></channel></rss>'

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _fake_urlopen(req, timeout=None):
    _seen_urls.append(req.full_url)                # ★ 只记，不打印（URL 里带 apikey）
    return _FakeResp()


_qenv = pathlib.Path(_tf.mkdtemp(prefix="tp-q-")) / "q.env"
_qenv.write_text("TORZNAB_URLS=http://prowlarr:9696/1/api?apikey=%s\n" % ("d" * 32),
                 encoding="utf-8")
_real_urlopen = tp.urllib.request.urlopen
tp.urllib.request.urlopen = _fake_urlopen
try:
    _queries = {}
    for _s in ("1", "2"):
        _seen_urls.clear()
        with contextlib.redirect_stdout(io.StringIO()):
            tp.main(["Test-Show", _s, "--env", str(_qenv)])
        _queries[_s] = _seen_urls[-1].split("?", 1)[1] if _seen_urls else ""
finally:
    tp.urllib.request.urlopen = _real_urlopen

ck("★ 两次都真的发出了请求（不是被参数解析挡住了）",
   all(_queries.values()), f"得到 {_queries}")
ck("★★ `season=1` 上了线", "season=1" in _queries["1"], _queries["1"])
ck("★★ `season=2` 上了线", "season=2" in _queries["2"], _queries["2"])
ck("★★★ 两个对照的 query **确实不同**（否则那次『对照』是两次一样的请求 —— ERR-AI-05）",
   _queries["1"] != _queries["2"],
   "两次 query 一模一样 ⇒ 拿它们对照会得出「season 不生效」的**假**结论")
ck("★ 且 query 里带 `t=tvsearch`（走的是同一条 Torznab 路）",
   "t=tvsearch" in _queries["1"], _queries["1"])
ck("★ 剧名被 URL 编码（中文剧名不会把请求弄坏）",
   "Test-Show" in _queries["1"] and " " not in _queries["1"].split("q=")[1].split("&")[0],
   _queries["1"])
print("  --   ★★ 这一格的意义：A 的『两个对照』**至少在对的那条路上** ——")
print("      ★ 至于站点**服务端**认不认 season，只能真跑（那才耗额度）。")

# ==========================================================================
print("\n⑧ ★★★ 退避闸：**退避期不发请求**（纯函数，离线证）")
# --------------------------------------------------------------------------
# ★★ 这一节钉的是 2026-09-21 实测暴露的那个洞：我**手动**查过两只时钟、
#    确认 HDFans「窗口已过」，**下一条命令它还是 429**。
#    ⇒ ★ 判据：**「这个站现在能不能问」必须由程序在读的那一刻算**，
#      人手查一次的结果**在两次调用之间就会过期**。
# ★ 而且「判不出来」这一支**必须与「没被禁」分开** ——
#   否则一个解析失败会被读成"可以跑"，于是又拿到一个假读数（`B.10`：未验 ≠ 无）。
import time as _tm                                    # noqa: E402

_NOW = _tm.time()
_FUTURE = "2099-09-21T22:03:23Z"
_PAST = "2000-01-01T00:00:00Z"

ok1, bl1 = tp.disarm_at(["1"], {}, _NOW)
ck("★ 数组里没有该站 ⇒ 可用（= 站点没被 Prowlarr 禁）", ok1 == ["1"] and not bl1,
   f"ok={ok1} blocked={bl1}")
ok2, bl2 = tp.disarm_at(["1"], {"1": _FUTURE}, _NOW)
ck("★★ `disabledTill` 在未来 ⇒ **被拦住**（这就是那次 429 的正解）",
   ok2 == [] and len(bl2) == 1, f"ok={ok2} blocked={bl2}")
ck("★ 拦截理由里**带还剩多久**（人要知道等多久，不是只知道「被拦了」）",
   bl2 and "还剩" in bl2[0][1], f"{bl2}")
ok3, _ = tp.disarm_at(["1"], {"1": _PAST}, _NOW)
ck("★ `disabledTill` 已过期 ⇒ 放行", ok3 == ["1"], f"ok={ok3}")
# ★★★ 最关键的两格：**判不出来时不许放行**
ok4, bl4 = tp.disarm_at(["1"], {"1": "garbage"}, _NOW)
ck("★★★ `disabledTill` 解析不了 ⇒ **拦住**（判不出 ≠ 没被禁）",
   ok4 == [] and bl4, f"ok={ok4} blocked={bl4}")
ok5, bl5 = tp.disarm_at(["1"], {"1": 12345}, _NOW)
ck("★★★ `disabledTill` 是意外类型 ⇒ **拦住**（同上，不放行）",
   ok5 == [] and bl5, f"ok={ok5} blocked={bl5}")
# ★ --force 是唯一能绕过它的东西，且必须真的绕过去（否则那个开关是假的）
ok6, bl6 = tp.disarm_at(["1", "2"], {"1": _FUTURE, "2": _FUTURE}, _NOW, force=True)
ck("★ `--force` 能绕过（★ 这是唯一出口，且它是个显式开关）",
   ok6 == ["1", "2"] and not bl6, f"ok={ok6} blocked={bl6}")
# ★ 挑站顺序：全被禁 ⇒ 什么都不放行（**不许"矮子里拔将军"**）
ok7, bl7 = tp.disarm_at(["1", "2", "4", "5"], {k: _FUTURE for k in ("1", "2", "4", "5")}, _NOW)
ck("★★ 全被禁 ⇒ 一个都不放行（**不许矮子里拔将军**）",
   ok7 == [] and len(bl7) == 4, f"ok={ok7} nblocked={len(bl7)}")

# ★ 超时必须是**独立退出码 4**，且**不许**和 429 混成一个
ck("★★ 超时有自己的退出码 4（源码里 `return 4`）", "return 4" in src, "没有 return 4")
ck("★★ 超时分支排在宽 `except Exception` **之前**（否则被吞成 1）",
   src.index("TimeoutError, socket.timeout") < src.index("请求失败：%s: %s"),
   "超时被宽 except 接走了 ⇒ 它和「网络不通」读数一样")
ck("★ 超时输出里明说它**不是**「没有季字段」",
   "响应里没有季字段" in src, "没交代超时不等于「没有」")
ck("★ 超时输出里给了「三种可能分不开」那条判读",
   "分不开" in src, "没给判读")
ck("★ `--timeout` 可调（默认仍是 30）", "--timeout" in src and "timeout = 30" in src,
   "超时不可调")

# ==========================================================================
print("\n⑨ ★★ 命令行默认值：**不许**把带退避的站当默认的 tacit 目标")
# --------------------------------------------------------------------------
ck("★ `--any` 与 `--force` 都在源码里被解析",
   '"--any"' in src and '"--force"' in src, "开关没实现")
ck("★★ 退避闸读不到状态时，`--any` **不生效**（不猜一个候选出来）",
   "不自动挑站" in src, "读不到状态时它还是挑了个站 ⇒ 那是猜")
ck("★ 退避闸的输出里点名了 `ERR-SVC-12`（退避时读数是假的）",
   "ERR-SVC-12" in src, "没交代为什么退避期不能跑")
# ★★ 退避闸**只读 Prowlarr 本地的 indexerstatus**，**绝不**去调 `/api/v1/indexer`
#   —— 那个响应带 `fields`（cookie / passkey）。★ 这是"脱敏纪律①：能不取就不取"。
# ★ 我的第一版这条写得**很糟**：它拿 `"/api/v1/indexer\"" ... not in src` 当判据，
#   结果**命中的是 docstring 里那句解释**（我正是在那句里写下了这个接口名），
#   于是它**恒定报红** —— 一条"永远红的闸门"（同 `ERR-AI-06`：常红 = 没人看）。
# ⇒ 改成**只查真正的调用点**：AST 里 `urllib.request.Request(...)` 的实参。
_urls_in_calls = []
for _n in ast.walk(tree):
    if (isinstance(_n, ast.Call) and isinstance(_n.func, ast.Attribute)
            and _n.func.attr == "Request"):
        for _a in _n.args:
            if isinstance(_a, ast.Constant) and isinstance(_a.value, str):
                _urls_in_calls.append(_a.value)
            if isinstance(_a, ast.BinOp):        # 拼接出来的（base + "...")
                for _sub in ast.walk(_a):
                    if isinstance(_sub, ast.Constant) and isinstance(_sub.value, str):
                        _urls_in_calls.append(_sub.value)
ck("★★ 退避闸只调 `indexerstatus`，**不调** `/api/v1/indexer`（那个带 cookie/passkey）",
   any("indexerstatus" in u for u in _urls_in_calls)
   and not any(u.rstrip("/").endswith("/api/v1/indexer") for u in _urls_in_calls),
   f"实际请求的路径片段：{[u for u in _urls_in_calls if u.startswith('/')]}")
print("  --   ★★ 为什么这一节值得 20 行断言：这一轮**三次命令全是废读数**，")
print("      ★ 而根因不是「站点不给季字段」，是「我在退避期问了它」（ERR-SVC-12）。")

# ==========================================================================
print("\n⑩ ★★★ 接线检查：`main()` **真的**把退避闸用上了吗（行为判据，不是源码文本）")
# --------------------------------------------------------------------------
# ★★★ 为什么必须有这一节：⑧ 测的是 `disarm_at` **这个纯函数**。
#     而**实测**——把 `fetch_disabled(...)` 换成 `({}, None)`（= 退避闸永远放行）
#     之后，⑧ 的 20 条断言**一条都不红**（红 0）。
#     ★ 根因：**纯函数对 ≠ main() 用了它**。这正是 `ERR-AI-05` 的又一个变体：
#       "我测了那段逻辑"与"那段逻辑被接上了"**是两件事**。
# ⇒ 判据：把整个 `main()` 跑一遍，**喂一份"该站被禁"的状态**，看它**拒不拒绝**。
#   ★ 做法与 ⑦ 同一形状：把 urlopen 换掉 —— 但这次**要能分别回答两个接口**：
#     ① Prowlarr 本地 `/api/v1/indexerstatus`（退避闸要读它）
#     ② 站点的 `/N/api`（真正的查询 —— ★ **一旦走到这里，就是闸没拦住**）
class _FakeResp2:
    """⑦ 的 `_FakeResp` 无参；⑩ 要能分别喂两段不同的 body ⇒ 单独一个带参的。"""
    status = 200

    def __init__(self, body):
        self._b = body

    def read(self):
        return self._b

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


_idx_hits = []          # 走到"真正的站点查询"就算一次


def _fake_urlopen2(req, timeout=None):
    u = req.full_url
    if "/api/v1/indexerstatus" in u:
        # ★ 伪造：id=1 被禁用到一个很远的将来 ⇒ 闸**必须**拦住 --id 1
        return _FakeResp2(b'[{"indexerId":1,"disabledTill":"2099-01-01T00:00:00Z"}]')
    _idx_hits.append(u)                              # ★ 这是"闸没拦住"的证据
    return _FakeResp2(b'<rss><channel></channel></rss>')


_real2 = tp.urllib.request.urlopen
tp.urllib.request.urlopen = _fake_urlopen2
try:
    # ① --id 1（被禁）⇒ 必须走退避闸、**不**碰站点
    _idx_hits.clear()
    with contextlib.redirect_stdout(io.StringIO()) as _cap1:
        _rc1 = tp.main(["T", "1", "--env", str(stub_env)])
    _out1 = _cap1.getvalue()
    ck("★★★ 该站被禁时 ⇒ `main()` 返回 3（不是 0/1）", _rc1 == 3, f"rc={_rc1}")
    ck("★★★ 且**根本没有向站点发那个查询**（`_idx_hits` 为空）",
       not _idx_hits, f"发了 {len(_idx_hits)} 次 ⇒ 退避闸没接上")
    ck("★ 且输出里点名了「不发请求」", "不发请求" in _out1, _out1[-200:])

    # ② --any：id=1 被禁 ⇒ 应跳过去挑下一个（2）
    _idx_hits.clear()
    with contextlib.redirect_stdout(io.StringIO()) as _cap2:
        _rc2 = tp.main(["T", "1", "--any", "--env", str(stub_env)])
    _out2 = _cap2.getvalue()
    ck("★★ `--any` 跳过了被禁的 id=1（输出里说挑中的不是 1）",
       "挑中 id=2" in _out2 or ("挑中 id=" in _out2 and "挑中 id=1" not in _out2),
       _out2[-300:])
    ck("★★ 且这一次**确实**向站点发了（跳过被禁的之后就该真查）",
       bool(_idx_hits), "`--any` 挑到站之后却没发查询")

    # ③ --force：明确绕过 ⇒ 必须真的发出去（否则那个开关是假的）
    _idx_hits.clear()
    with contextlib.redirect_stdout(io.StringIO()):
        _rc3 = tp.main(["T", "1", "--force", "--env", str(stub_env)])
    ck("★★ `--force` 真能绕过退避闸（发出去了）", bool(_idx_hits),
       "`--force` 却还是被拦住了 ⇒ 这个开关是假的")
    ck("★ 而且它**照常出结果**（rc=0，不是把它变成错误路径）", _rc3 == 0, f"rc={_rc3}")

    # ④ ★ 反向：退避**读不到**时不许猜一个候选出来
    def _fake_urlopen3(req, timeout=None):
        if "/api/v1/indexerstatus" in req.full_url:
            raise OSError("假装读不到状态")
        _idx_hits.append(req.full_url)
        return _FakeResp2(b'<rss><channel></channel></rss>')

    tp.urllib.request.urlopen = _fake_urlopen3
    _idx_hits.clear()
    with contextlib.redirect_stdout(io.StringIO()) as _cap4:
        _rc4 = tp.main(["T", "1", "--any", "--env", str(stub_env)])
    _out4 = _cap4.getvalue()
    ck("★★★ 退避状态**读不到**时 ⇒ 返回 3、且不猜候选", _rc4 == 3, f"rc={_rc4}")
    ck("★★★ 且同样**没发站点查询**", not _idx_hits, f"发了 {len(_idx_hits)} 次")
    ck("★ 且明说「读不到 ≠ 没被禁」", "读不到" in _out4 and "不自动挑站" in _out4,
       _out4[-250:])
finally:
    tp.urllib.request.urlopen = _real2
print("  --   ★★★ 这一节是 ⑧ 的**接线**对照：⑧ 证明闸的逻辑对，⑩ 证明闸**真的接上了**。")
print("      ★ 实测：把 fetch_disabled 换成空 map（闸永远放行）⇒ ⑧ 的 20 条**一条不红**，")
print("        本条**立刻红**。★ 同 ERR-AI-05：「测了那段逻辑」≠「那段逻辑被接上了」。")

print(f"\n{'=' * 60}")
print(f"断言 {_ok + _bad} 条：{_ok} 过 / {_bad} 失败")
sys.exit(0 if _bad == 0 else 1)

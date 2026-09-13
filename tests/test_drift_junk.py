# -*- coding: utf-8 -*-
"""回归：漂移哨兵对 `.env` 备份/变体的分类 —— **别再靠猜文件名**。

钉住的现场（2026-09-13）
-----------------------
`check-deploy-drift.py` 的 `KNOWN_NAS` 里那条杂物规则原本写作：

    (r"^\\.env\\.bak\\..*", "杂物·.env 备份")

`.` 后面那个 `\\..*` 要求**必须**跟一个点 + 后缀，于是**裸名 `.env.bak`**
（不带时间戳）**不匹配** —— 而它恰恰是 `rm-staging.sh` 那条窄口
（8 个凭据副本只有 7 个匹配）里的第 8 个。
不匹配的后果：它掉进 `unknown` ⇒ 哨兵**误报**「NAS 上有没登记过的文件」。

★ 同一类坑（"保证取决于我们猜没猜对文件名"）当天咬了**三处**：
  `rm-staging.sh`（删除口径）、`.gitignore`（忽略口径）、本哨兵（分类口径）。
  所以这里把**命名变体整个钉住**，而不是只钉当时那一例。

判据：`classify()` 是**先匹配先赢**（`re.search` 逐条扫 `KNOWN_NAS`）。
  · `.env`           —— 本体，必须落在上一条「真实凭据」，**不许**被杂物吃掉；
  · `.env.example`   —— 模板，压根不部署，**不许**归进杂物；
  · 其余 `.env.` / `.env_` 前缀的，**都**该归进杂物。
"""
import importlib.util
import pathlib
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

REPO = pathlib.Path(__file__).resolve().parent.parent
SRC = REPO / "scripts" / "check-deploy-drift.py"


def _load():
    name = "check_deploy_drift_mod"
    spec = importlib.util.spec_from_file_location(name, SRC)
    mod = importlib.util.module_from_spec(spec)
    # ★ 必须先 `sys.modules[name] = mod` 再 exec_module —— 见 tests/README
    #   「importlib 载进来的模块…」（带上这个文件后照样得这么写）。
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


M = _load()


def kind_of(rel: str) -> str:
    """→ 'managed' / 'known' / 'clutter'（known 里那类"杂物"）/ 'unknown'。"""
    k, rule = M.classify(rel, set(), M.KNOWN_NAS)
    if k == "managed":
        return "managed"
    if k == "known":
        return "clutter" if (rule and M.CLUTTER.search(rule[1])) else "known"
    return "unknown"


fails = []


def check(n, label, rel, want):
    got = kind_of(rel)
    ok = got == want
    print("[%d] %-28s %-40s: %s" % (n, label, rel, "PASS" if ok else "FAIL"))
    if not ok:
        print("      want=%s  got=%s" % (want, got))
        fails.append(n)


print("== 漂移哨兵：`.env*` 分类（先匹配先赢）==")

# 1) 本体：必须仍是「真实凭据」，不能被放宽后的杂物规则吃掉
check(1, "本体凭据不被杂物吃", ".env", "known")

# 2) 模板：不许归进杂物（新版规则里的负向前瞻 `(?!example$)` 钉的就是这格）
check(2, "模板不归杂物", ".env.example", "unknown")

# 3) ★ 现场那一例：裸名 `.env.bak`（无时间戳）—— 旧规则漏的就是它
check(3, "裸名备份", ".env.bak", "clutter")

# 4) 旧规则**唯一**认得的那一形，放宽后当然还得认得
check(4, "带时间戳备份", ".env.bak.20260911-204109", "clutter")

# 5) 下划线变体（`.gitignore` 那条窄口实测漏过它）
check(5, "下划线变体", ".env_bak", "clutter")

# 6) 另一个常见写法
check(6, "backup 变体", ".env.backup", "clutter")

# 7) 误伤检查：不相关的东西不该被判成杂物
check(7, "无关文件不误伤", "hlink/.reseed_farm.manifest.tsv", "known")

print()
if fails:
    print("FAIL：第 %s 项不过（测试自己也可能错，先看 want/got）" % fails)
    sys.exit(1)
print("ok：7/7 通过")
sys.exit(0)

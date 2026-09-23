# -*- coding: utf-8 -*-
"""门禁 —— 钉住「名字挡板」（`scripts/diag/check-datadirs-names.py`）。

## 为什么这个文件必须存在

`①′` 要挡的是一条**实测过的**静默失败（`§26.58` 三 / `§10.2`）：

> `TV/` 里混着 `儿童` / `欧美剧` 两个**分类目录**（不是发布名）。
> `DATA_DIRS` 是**逐条手写在 `.env` 里**的（`.env:22`），而生成片段的
> `scripts/diag/gen-datadirs.py` 按 `--level N` **递归取第 N 层所有子目录**，
> ★ **它只跳 `.` 开头和 `@eaDir`，不认"分类目录"**。
> ⇒ 一旦 `--level` 给错（或人手工粘），分类目录名会被当成发布名进 `DATA_DIRS`：
>   **搜不到任何东西**（浪费查询额度），而且**日志一切正常**（`§19.1`）。

★ **只读文档挡不住它** —— 文档里的规矩是**恒绿**的（`ERR-AI-09`）。
  所以挡板必须是**代码**，而代码必须有**门禁**，否则它自己也会腐（清单里混进
  一条死规则、或者判据被写宽到杀真发布名，都没人会发现）。

## 本文件钉什么（五段）

| 段 | 钉什么 | 为什么 |
|---|---|---|
| ① | **前提控制** | `DATA_DIRS` 解析得出 + 清单非空。★ 少了这条，下面「都干净」可以**空集通过**（`ERR-AI-03`：`n/a ≠ 0 ≠ 没事`） |
| ② | **清单里没有死规则** | 每条必须是"**真的会出现在 `TV/` 里**"的名字（同 `tests/test_drift_lists.py` ② 段）。死规则比缺规则更坏：它**看起来**已经登记了 |
| ③ | **反面哨兵**（真发布名必须放过） | `儿童医院.S01.2026…` 这种含"儿童"二字的**真发布名**不许被杀 —— 那是本仓最忌的"量错对象"（`A.11`） |
| ④ | **正例：跑校验器本体** | `rc` 必须**分别**是 `0`（真 `.env`）/ `1`（含 `儿童` 的候选）。★ 只断言"清单里有 `儿童`"是不够的 —— 那证明不了**挡板真的会红** |
| ⑤ | **空清单 ⇒ `rc=2`** | 清单被清空 ⇒ 这道门**恒绿**。必须**当场拒跑**，不许静默通过 |

## ★ 三条容易写错的地方（都写在代码注释里了）

1. **④ 段必须跑子进程**，不能 `import` 后调 `check_paths()` ——
   要钉的是**退出码**（那是调用方唯一看得见的东西）。`check_paths()` 返回列表，
   `main()` 才把"有命中"翻译成 `rc=1`；★ 变异 ③（让 `main()` 永远 `return 0`）
   在 `check_paths()` 层面**完全看不见** ⇒ 只调函数会把那条变异**放过去**。
2. **⑤ 段必须用 `runpy` 跑一个临时副本**（把清单字面量替空），
   不能在测试里改模块全局 —— 那样改的是**同一个进程里的 `M._NAMES`**，
   而 `main()` 读的就是它 ⇒ 被测的根本不是"空清单"这个场景（`A.11`）。
3. **子进程一律带 `MSYS_NO_PATHCONV=1`**（本仓 2026-09-24 实测）：Git Bash 会把
   **以 `/` 开头的参数**改写成 Windows 路径（`/volume1/…` → `C:/Program Files/Git/volume1/…`），
   ⇒ 校验器打印的**不是输入路径**。判据（`rc`）不受影响，但会让变异诊断**看错对象**。

★ 行形只用 `  ok  ` / ` FAIL `（`tests/README.md` 那个重数器只认这三种）。
★ 全部离线：只读仓库里的 2 个文本文件 + 跑本仓脚本，不碰 NAS、不碰网络。
"""
from __future__ import annotations

import importlib.util
import json
import os
import pathlib
import subprocess
import sys
import tempfile

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

VALIDATOR = REPO / "scripts" / "diag" / "check-datadirs-names.py"
ENV = REPO / ".env"

_ok = 0
_n = 0


def check(name: str, cond: bool, detail: str = "") -> None:
    global _ok, _n
    _n += 1
    _ok += 1 if cond else 0
    print(("  ok  " if cond else " FAIL ") + "%s" % name)
    if not cond and detail:
        print("        ← " + detail)


# --------------------------------------------------------------------------- #
# 载入校验器本体（★ 必须先 `sys.modules[name] = mod` 再 exec_module ——
#   见 `tests/README.md`「importlib 载进来的模块…」）。
# --------------------------------------------------------------------------- #
_NAME = "check_datadirs_names_for_gate"
_spec = importlib.util.spec_from_file_location(_NAME, VALIDATOR)
M = importlib.util.module_from_spec(_spec)
sys.modules[_NAME] = M
_spec.loader.exec_module(M)


def run_validator(*extra: str, msys: bool = True) -> tuple[int, str]:
    """跑校验器**本体**（子进程），返回 `(rc, stdout+stderr)`。

    ★★ 为什么是子进程而不是 `M.main([...])`：要钉的是**退出码**，
      而 `check_paths()` 只返回列表 —— 变异「让 `main()` 永远 return 0」
      在函数层面看不见（见模块头注 1）。
    """
    env = dict(os.environ)
    if msys:
        # ★ Git Bash 的 MSYS 路径重写：不加这个，`--dirs /volume1/…`
        #   会被改写成 `C:/Program Files/Git/volume1/…`（打印的不是输入）。
        env["MSYS_NO_PATHCONV"] = "1"
    r = subprocess.run([sys.executable, str(VALIDATOR), *extra],
                       cwd=str(REPO), capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=120, env=env)
    return r.returncode, (r.stdout or "") + (r.stderr or "")


# --------------------------------------------------------------------------- #
print("== ① ★ 前提控制（防空集通过 —— `ERR-AI-03`：`n/a ≠ 0 ≠ 没事`）==")

check("前提：校验器脚本在", VALIDATOR.is_file(), str(VALIDATOR))
check("前提：分类目录名清单**非空**（空清单不是『没命中』，是『什么也挡不住』）",
      len(M.CATEGORY_DIR_NAMES) > 0,
      "清单空 ⇒ 下面 ③④ 的『都干净』全部退化成空集通过")
check("前提：反面哨兵清单**非空**（没有它，③ 段什么也不证明）",
      len(M.NOT_CATEGORY_SAMPLES) > 0,
      "空 ⇒ ③ 段的『真发布名被放过』是空集通过")

_RAW_DIRS, _WHY = M.read_datadirs(ENV)
check("前提：.env 里解析出了 DATA_DIRS（否则 ④ 段的正例是假的）",
      _RAW_DIRS is not None, "read_datadirs 说：%s" % _WHY)
check("前提：DATA_DIRS 切出了路径条目",
      len(M.split_dirs(_RAW_DIRS or "")) > 0,
      "切出 0 条 ⇒ 校验器会打印『干净：0 条』—— 那是**真空**，不是干净（`ERR-AI-03`）")

# --------------------------------------------------------------------------- #
print("\n== ② ★★ 清单里**不许有死规则**（死规则比缺规则更坏：它看起来已经登记了）==")
#   死规则 = 那条名字**不会出现在 `TV/` 里**。
#   ★ 本机读不到 NAS（2026-09-24 实测 `//iSunker-DS423/...` 不可达）
#     ⇒ **不能**去盘上核，只能核"它在 `summary/26` 里被**实测记过一笔**"。
#     这与 `tests/test_drift_lists.py` ② 段同形，只是把"盘上有没有"换成
#     "文档里有没有实证"（读不到的东西不许冒充"没有"，`ERR-AI-03`）。
_SUMMARY = REPO / "summary" / "26-跨会话任务盘面与旧会话清场.md"
check("前提：summary/26 在（② 段的实证来源）", _SUMMARY.is_file(), str(_SUMMARY))

if _SUMMARY.is_file():
    _SUM_TEXT = _SUMMARY.read_text(encoding="utf-8", errors="replace")
    _dead = [(n, why) for n, why in M.CATEGORY_DIR_NAMES if n not in _SUM_TEXT]
    check("★ 清单每条都在 summary/26 里有**实证记录**（没有死规则）",
          not _dead,
          "以下 %d 条在 summary/26 里查不到 —— 无法证明它真的会在 TV/ 里出现：\n"
          "        ← %s" % (len(_dead), "\n        ← ".join(n for n, _ in _dead)))

# --------------------------------------------------------------------------- #
print("\n== ③ ★★ 反面哨兵：**真发布名必须放过**（否则挡板会杀真包 —— `A.11`）==")
#   ★ 这一段的判据是「**整名比对**」而不是「子串包含」：
#     `儿童医院.S01.2026…` 含"儿童"二字，但它是真发布名。
#   ★★ 变异 ② 把 `b in _NAMES` 改成 `any(n in b for n in _NAMES)` 时，
#      下面这条必须**红透**（否则这条判据是摆设）。
_SENTINEL = ",".join("/volume1/video/download/TV/" + n for n, _ in M.NOT_CATEGORY_SAMPLES)
_rc_s, _out_s = run_validator("--dirs", _SENTINEL, "--quiet")
check("★ 反面哨兵全过（%d 条真发布名一条都没被命中）" % len(M.NOT_CATEGORY_SAMPLES),
      _rc_s == 0,
      "rc=%d（期望 0）\n        ← 判据写宽了（子串包含会把真发布名误杀）：\n%s"
      % (_rc_s, _out_s.strip()[:600]))

# --------------------------------------------------------------------------- #
print("\n== ④ ★★ 正例：跑**校验器本体**，退出码必须分别对 ==")
#   ★ 一段测两个方向：**该绿的绿、该红的红**。只测一边都不成立 ——
#     只测"真 .env 干净" ⇒ 一个永远 `return 0` 的脚本也能过。

_rc_a, _out_a = run_validator("--quiet")
check("★ 真 `.env` ⇒ rc=0（当前 DATA_DIRS 不含分类目录名）", _rc_a == 0,
      "rc=%d（期望 0）:\n%s" % (_rc_a, _out_a.strip()[:600]))

_rc_b, _out_b = run_validator("--dirs", "/volume1/video/download/TV/儿童", "--quiet")
check("★★ 候选含 `儿童` ⇒ rc=1（**这才证明挡板真的会红 —— `ERR-AI-09`**）",
      _rc_b == 1,
      "rc=%d（期望 1）:\n%s" % (_rc_b, _out_b.strip()[:600]))
check("★ 报红时**要点名那个基名**（不然人不知道改哪一条）", "儿童" in _out_b,
      "输出里没有 `儿童`：\n%s" % _out_b.strip()[:400])

# ★ 路径必须**原样**打印 —— Git Bash 会把 `/volume1/…` 改写成
#   `C:/Program Files/Git/volume1/…`，那样打印的不是输入（`ERR-CMD-04` 同族：
#   "我量到的对象 ≠ 我以为在量的对象"）。子进程一律带 `MSYS_NO_PATHCONV=1`。
check("★ 报红时打印的**就是输入的那条路径**（没被 MSYS 改写）",
      "/volume1/video/download/TV/儿童" in _out_b,
      "打印的路径不是输入 ⇒ 命中时会对着一个**不存在的路径**去改：\n%s"
      % _out_b.strip()[:400])

# --------------------------------------------------------------------------- #
print("\n== ⑤ ★ 空清单 ⇒ rc=2（**恒绿闸门必须当场拒跑**）==")
#   ★★ 为什么用 `runpy` 跑**临时副本**：在测试进程里改 `M._NAMES` 改的是
#      **同一个对象**，而 `main()` 读的就是它 —— 那样"空清单"与"清单非空"
#      两种场景会在**同一个进程里**互相污染（本文件 ⑤ 段会假红/假绿）。
#      于是把源码里的清单字面量替空，落一个临时文件，**另起进程**跑它。
_SRC = VALIDATOR.read_text(encoding="utf-8")
_MARK_A = "CATEGORY_DIR_NAMES: list[tuple[str, str]] = ["
_MUTATED = _SRC.replace(_MARK_A, _MARK_A + "\n    # ★ 门禁 ⑤ 段临时替空（仅内存，不落仓库）\n")
_i = _MUTATED.index(_MARK_A) + len(_MARK_A)
_j = _MUTATED.index("\n]", _i)
_MUTATED = _MUTATED[:_i] + "\n] # ★ 替空占位" + _MUTATED[_j + 2:]

check("前提：变异体真的把清单替空了（否则 ⑤ 段是假测试）",
      _MUTATED != _SRC and "_NAMES" in _MUTATED, "替换没生效 ⇒ 别在这儿报绿")

with tempfile.TemporaryDirectory() as _td:
    _tmp = pathlib.Path(_td) / "check-datadirs-names-emptied.py"
    _tmp.write_text(_MUTATED, encoding="utf-8")
    r = subprocess.run([sys.executable, str(_tmp)], cwd=str(REPO),
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=120)
    _rc_c = r.returncode
    _out_c = (r.stdout or "") + (r.stderr or "")

check("★ 空清单 ⇒ rc=2（不许静默通过 —— 那样这道门恒绿）", _rc_c == 2,
      "rc=%d（期望 2）:\n%s" % (_rc_c, _out_c.strip()[:600]))

# --------------------------------------------------------------------------- #
print("\n== ⑥ ★★ 本文件自己也得在 `COUNTS.json` 里（它是今天第 N 个 q2.py 的候选）==")
#   ★ 同 `tests/test_drift_lists.py` ⑤ 段：新测试忘了登记 ⇒ 计数闸门
#     （`test_readme_counts.py`）看不见它 ⇒ 它会成为下一个"提交了三天没人知道"的文件。
_counts = REPO / "tests" / "COUNTS.json"
check("前提：tests/COUNTS.json 在", _counts.is_file(), str(_counts))
if _counts.is_file():
    _c = json.loads(_counts.read_text(encoding="utf-8"))
    check("★★ test_datadirs_names.py 在 COUNTS.json 的 notes 里",
          "test_datadirs_names.py" in (_c.get("notes") or {}),
          "不在 ⇒ 它是**未登记**的测试，与 `q2.py` 同一个形状")

# --------------------------------------------------------------------------- #
print()
if _ok != _n:
    print("!!! %d/%d 失败" % (_n - _ok, _n))
    sys.exit(1)
print("全部通过（%d 条）" % _n)

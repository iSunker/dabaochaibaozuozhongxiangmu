# -*- coding: utf-8 -*-
"""`deploy.sh` 的**第一道闸门**必须"真的去读一次"目标目录（2026-09-21 实测事故）。

为什么钉这个
============
原写法是 `[[ -d "$DST" ]] || { echo "✗ 生产目录不可达"; exit 1; }`。
**它在 SMB 凭据错时返回真** ⇒ 闸门放行 ⇒ 一路跑到 `mkdir` 才炸。用户亲历的现场：

    mkdir: cannot create directory '//192.168.0.7/docker_ssd': Permission denied

而**在此之前**它已经打了 `有差异的文件 (29)`、**29 条全是 `[新]`** ——
读起来像"首次部署一次到位"，**根本看不出是坏的**。

★★ **这就是本项目最忌的形状**：「判据看着过了、其实没测到东西」。

当场实测（断开共享后，`deploy.sh:147` 那三种判据）：

    A) [[ -d "$DST" ]]                       → **true**（放过 ← 缺陷）
    B) ls "$DST" >/dev/null 2>&1             → **false**（拦住 ✅）
    C) [[ -f "$DST/orchestrator/main.py" ]]  → **false**（拦住 ✅）

⇒ 取 B。本文件钉的就是「**A 那种写法必须绝迹、B 那种写法必须在**」。

★★ 一条**只能靠实测发现**的边界（也是本文件存在的理由之一）：
   **断开后头几秒三种判据全都放过** —— Windows 会**缓存** SMB 会话（连接懒惰建立）。
   ⇒ 所以闸门**不是瞬时的**：它挡的是"缓存过期后"的坏状态。
   ⇒ 所以还加了第二道**指纹**判据（见"二"）：**全 `[新]` + 目录读不出内容** = 坏。

判据分三重（缺一都不够）
========================
  一、**源码级**：闸门用的是"真读"（`ls`），不是 `stat`（`-d`）
     —— ★ 这条最容易退回去：下一个人觉得 `-d` 更"干净"就改回去了。
  二、**行为级 · 好路径**：正常的本地目录 + 沙箱 DST ⇒ 照走、**不误拦**
     —— 只测"坏时会红"而不测"好时会绿"，等于把闸门做成"永远红"（=没人看）。
  三、**行为级 · 坏路径**：DST 指一个**列不出内容**的目录 ⇒ **非零退出**
     —— 这是原缺陷的正对照：改之前它是 **0**（一路走到 mkdir）。

★ 全部离线：不联网、不碰 NAS、不碰生产目录。沙箱在 `tempfile.mkdtemp()`。
★ `--dry-run`（默认模式）**不写任何东西**，所以沙箱里跑它是安全的。
"""
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile

try:
    sys.stdout.reconfigure(encoding="utf-8")   # GBK 控制台会炸（tests/README.md）
except Exception:
    pass

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parent
DEPLOY = REPO / "deploy.sh"

_ok = 0
_n = 0


def check(name, cond, detail=""):
    """★ 行形必须和全仓一致（`  ok  ` / ` FAIL ` 前缀）——
    `tests/README.md` 那个重数器只认三种行形，写成第四种会被**静默漏掉**。"""
    global _ok, _n
    _n += 1
    _ok += 1 if cond else 0
    print(("  ok  " if cond else " FAIL ") + "%s: %r" % (name, bool(cond)))
    if not cond and detail:
        print("        ← " + str(detail))


SRC = DEPLOY.read_text(encoding="utf-8")


def strip_comments(text):
    """删掉行首 `#` 开头的**整行注释**。

    ★★ 为什么必须这么做（第一版就栽在这儿）：注释里**故意**引用了那两段坏代码
      （`[[ -d "$DST" ]]`）用来解释它错在哪。不剥注释 ⇒ 判据把"解释缺陷的文字"
      当成"缺陷本身" ⇒ **假红**。
    ★ 只剥**整行**注释，不碰"行尾 `#`"（那可能是字符串里的 `#`）——
      这里够用，且不会误伤（判据要的是"代码行里没有"）。
    """
    return "\n".join(ln for ln in text.splitlines() if not ln.lstrip().startswith("#"))


CODE = strip_comments(SRC)

# =====================================================================
print("\n── ① 源码级：闸门是「真的去读」，不是「只看目录在不在」──")

# ★★ 这条是**反退化的主判据**：`-d "$DST"` 那种写法**必须不存在**。
#   注意别写成"全文不许出现 `-d`" —— `[[ -d "$SRC" ]]`（**本地**目录）是对的、
#   该留。判据要**精确到 $DST**，否则会误伤（本仓反复记过"判据写宽了会满仓假红"）。
#   ★ 且只看**代码行**（剥掉注释）—— 见 strip_comments。
#
# ★★★ 正则必须**同时**抓单/双括号与取反形式 —— 这里**我自己先踩了一次**：
#   第一版写的是 `\[ -d "\$DST" \]`（单括号、无 `!`），而真代码是
#   `[[ ! -d "$DST" ]]` ⇒ **变异测试时它没红** ⇒ 那条判据等于没测到东西
#   （正是本文件要防的那个形状，出现在本文件自己身上）。
#   现在用 `\[\[? ... \]\]?` + 可选 `!`，两种写法都抓（已当场用变异复验）。
_DST_STAT_RE = r'\[\[?\s*!?\s*-d\s+"\$DST"\s*\]\]?'
_check_dst_stat = re.findall(_DST_STAT_RE, CODE)
check("★★ 闸门里**没有** `[ -d \"$DST\" ]`（凭据错时它会返回真 ⇒ 放过）",
      _check_dst_stat == [], _check_dst_stat)

# ★ 前提：这条正则**真的能抓到那种写法**（否则上面那条是空转 —— 见 ★★★）
check("★★ 前提：正则能抓到 `[[ ! -d \"$DST\" ]]`（否则上面那条测不到东西）",
      re.findall(_DST_STAT_RE, 'if [[ ! -d "$DST" ]]; then') != [],
      re.findall(_DST_STAT_RE, 'if [[ ! -d "$DST" ]]; then'))

# ★ 正面：闸门用的是 `ls`（会真的展开目录 ⇒ 凭据错会被拒）
check("★ 闸门用的是 `ls \"$DST\"`（会真的去列一次）",
      re.search(r'if\s+!\s+ls\s+"\$DST"\s*>', CODE) is not None,
      [ln for ln in CODE.splitlines() if "ls \"$DST\"" in ln][:3])

# ★ `[[ -d "$SRC" ]]`（本地目录）**要留着** —— 它是 "别误伤" 的对照
check("★ 本地那一条 `[ -d \"$SRC\" ]` **仍在**（别把好的也删了）",
      re.search(r'\[\s*-d\s+"\$SRC"\s*\]', CODE) is not None)

# ★★ 指纹判据：全 `[新]` + 目录读不出内容 ⇒ 拒绝
#   ★★★ 这条**必须钉住"计数真的在增加"**，不能只钉字符串 `N_NEW` 在文件里 ——
#     第一版就是那样，**变异测试时删掉自增语句它照样绿**（= 那条判据没测到东西，
#     正是本文件要防的形状，第二次出现在本文件自己身上）。
#     现在改成两条更严的：
#       (a) 自增语句 `N_NEW=$((N_NEW+1))` **必须在**（这是"计数真的动"的充分标志）
#       (b) 阈值比较必须**同时**要求 `N_NEW == CHANGED 总数` **且** 总数 > 3
check("★★ 有「只对 `[新]` 自增」的计数语句（`N_NEW=$((N_NEW+1))`）",
      "N_NEW=$((N_NEW+1))" in CODE,
      [ln for ln in CODE.splitlines() if "N_NEW" in ln][:6])
check("★★ 阈值比较**同时**要求「全 `[新]`」与「总数 > 3」"
      "（只比一半会在真·首次部署时误报）",
      re.search(r'N_NEW"\s*-eq\s*"\$\{#CHANGED\[@\]\}"', CODE) is not None
      and re.search(r'\$\{#CHANGED\[@\]\}"\s*-gt\s*3', CODE) is not None,
      [ln for ln in CODE.splitlines() if "N_NEW" in ln][:6])
check("★★ 且读不出内容时**退出非零**（不是只打一行警告）",
      re.search(r'production|生产目录读不出任何内容[\s\S]{0,400}?exit 1', CODE) is not None,
      "在 N_NEW 那段里没找到 exit 1")

print("\n── ①b ★ 报错文案里不许有会**执行**的东西（我自己踩过）──")
# ★ 事故：我第一版把 `-d` / `ls` 用**反引号**包进 echo，shell 当场把它们当命令替换
#   执行了（还打印出目录列表）—— 报错文案本身成了 bug。判据：`echo "...`...`..."` 不许有。
_bad_echo = [ln for ln in CODE.splitlines()
             if ln.lstrip().startswith("echo ") and "`" in ln]
check("★★ echo 行里**没有反引号**（会被当命令替换真的执行）",
      _bad_echo == [], _bad_echo)

# =====================================================================
print("\n── ② 行为级 · 好路径：正常目录下**不误拦**（只测坏路径=把闸门做成永远红）──")


def run_deploy(dst, sandbox):
    """跑一次 `deploy.sh`（默认 = --dry-run，**不写任何东西**）。

    ★★ 必须**继承**环境（`{**os.environ, ...}`）—— 第一版我传了一个"干净"的 env，
      结果这台机器上 `bash` 被 WSL 的 shim 接管 ⇒ `execvpe(/bin/bash) failed`
      ⇒ 返回码非 0 而**原因与闸门无关**（假红）。
    ★ ★ 也要显式给 `PATH` 兜底：万一将来谁又清空 env，这条至少不会静默退化。
    ★★★ **别设 `SRC=REPO`** —— 第一版设了，于是脚本里 `SRC="${SRC:-$SELF_DIR}"`
      取到这个值；它在好路径下**掩盖**了本该暴露的东西。让它走默认（= 脚本所在目录）。
    """
    import os
    env = dict(os.environ)
    env["DST"] = str(dst)
    env.setdefault("PATH", "/usr/bin:/bin")
    env.pop("SRC", None)          # ★ 走脚本自己的默认值（= 仓库根）
    return subprocess.run(
        ["bash", str(DEPLOY)], cwd=str(REPO), capture_output=True,
        text=True, encoding="utf-8", errors="replace", timeout=180, env=env,
    )


sd = pathlib.Path(tempfile.mkdtemp(prefix="deploy-gate-lab-"))
good_dst = sd / "good_dst"
good_dst.mkdir()
(good_dst / "marker.txt").write_text("x", encoding="utf-8")

r = run_deploy(good_dst, str(sd))
# ★ 好路径不该因**闸门**而退出 1。它会因为"本地文件缺失"而跳过很多（沙箱 DST 是空的），
#   但**不该**打那句"生产目录不可达"。
check("★ 正常目录 ⇒ **没有**「生产目录不可达」那句",
      "生产目录不可达" not in (r.stdout + r.stderr),
      (r.stdout + r.stderr)[:300])

# =====================================================================
print("\n── ③ 行为级 · 坏路径：**列不出内容**的 DST ⇒ **非零退出**（原缺陷它是 0）──")

# ★★ 怎么造"目录存在、但列不出内容"？
#   ③a 先试**权限 0**（chmod 000）—— 这是"凭据错"在 MSYS 下最接近的等价物
#       （`ls` 被拒、`stat` 放行）。
#   ★★ 但它在**以 root 跑 / Windows 挂载**时**不成立**（root 无视权限位）——
#      第一版我就栽在这儿：前提断言红，而**红的是测试自己**（本仓规矩：
#      报红时先怀疑断言本身）。⇒ 这时**不许**静默跳过，要**连理由一起报**。
#   ★ 本仓没有 SSH、测试常以不同身份跑 ⇒ 所以**两条路都要有**：
#       能造出来 ⇒ 走完整判据；造不出来 ⇒ **明说"这一条未验"**，不算过也不算败。
bad_dst = sd / "bad_dst"
bad_dst.mkdir()
(bad_dst / "inside.txt").write_text("x", encoding="utf-8")
bad_dst.chmod(0o000)

can_stat = bad_dst.is_dir()
can_list = True
try:
    list(bad_dst.iterdir())
except PermissionError:
    can_list = False

if can_stat and not can_list:
    r2 = run_deploy(bad_dst, str(sd))
    out2 = r2.stdout + r2.stderr
    check("前提：sandbox 下权限 0 的目录 **stat 成功**（`-d` 会为真）", True)
    check("前提：同一目录 **列不出内容**（`ls` 会失败）", True)
    check("★★ 坏路径 ⇒ **非零退出**（原写法是 0，一路走到 mkdir 才炸）",
          r2.returncode != 0, "rc=%s" % r2.returncode)
    check("★★ 且**明确指出**是目录不可达/凭据被拒",
          "生产目录不可达" in out2, out2[:400])
    check("★ 且**不再**先打「有差异的文件 (N)」（闸门在算差异**之前**）",
          "有差异的文件" not in r2.stdout,
          [ln for ln in r2.stdout.splitlines() if "有差异" in ln])
else:
    print("  skip  ③ 行为级坏路径：本机 sandbox **造不出**「stat 真、ls 假」的目录")
    print("        ← 原因：chmod 000 在本平台无效（以 root 跑 / Windows 挂载忽略权限位）")
    print("        ← ★ 这一条**未验** —— 既不算过也不算败（不静默跳过，B.10 第 14 条）")
    print("        ← ★ 真实的等价物是 **SMB 凭据错**，那需要 NAS —— 已由用户当场实测过：")
    print("            改前 rc=0（29 文件全 [新] + mkdir Permission denied）")
    print("            改后 rc=1（第一道闸拦住）")
    print("        ← ✅ 源码级判据（①）**不受影响** —— 它不需要造这个条件。")

bad_dst.chmod(0o700)
shutil.rmtree(sd, ignore_errors=True)

print()
if _ok == _n:
    print("✓ %d 条断言全过 —— 闸门「真的去读」，坏路径非零退出、好路径不误拦" % _n)
    sys.exit(0)
print("✗ 有对照没过（%d/%d）—— 别拿它当推前闸门" % (_ok, _n))
sys.exit(1)

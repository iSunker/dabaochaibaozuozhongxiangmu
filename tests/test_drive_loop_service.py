# -*- coding: utf-8 -*-
"""`#58` drive-loop 迁容器 —— **本机离线**能钉住的那一半。

它钉的不是「迁容器做完了」。恰恰相反，本文件里**没有一条**断言能证明
「容器里真跑得起来」—— 那要 NAS、要 `docker`、要一次真批次（见文末「本机验不了的」）。
它钉的是**这次改动的三样东西，每一样都有一个"悄悄退化回原样"的失效模式**：

  ① `compose.yaml` 里的 `drive-loop` 服务（新增）
     ★★ 最要命的一条是 `profiles`：它是**安全锁**，不是分类标签。
        删掉它 ⇒ 该服务被 `docker compose up -d` **默认拉起来** ⇒
        在 DSM 任务那份 `run.sh` 还活着的时候把第二条 webhook 路点亮 ⇒
        一次 429 可能废掉几百条（README 坑 4）。
        **反向也要钉**：其余四个服务**都不许**带 profile —— 那会把它们一起锁住，
        是另一种事故（prowlarr 起不来 ⇒ cross-seed 全站搜不到）。
     ★ 另一条是「不写 `build:`」：本仓 build 上下文是**仓库根**、NAS 上是
        **compose 目录**，写了会在 NAS 上 build 失败。

  ② `scripts/drive-loop-resident.sh`（新增）
     钉住它**没有**把 `--once` 带上命令行 —— 常驻与 `--once` 就差这一个开关，
     而带错的后果不是报错、是「跑一批就退出 + 被 `restart: unless-stopped`
     反复拉起来」，看着像在跑。
     ★ 注释里**允许**出现 `--once`（要解释为什么不要它）⇒ 判据必须
       **只看命令行的参数区段**，不能用「grep 全文有没有 `--once`」那种写法。
     ★ 另钉 `--indexers` 名单与 `drive-loop-nas.sh` **逐字相同**：
       那个名单有**两个声明点**（本文件是第二个），而"加了站却漏改一处"
       正是 2026-09-12 卡住 224 部片子的形状。这条是本文件里**唯一**能抓住
       那种漂移的判据。

  ③ `scripts/drive-loop.py` 的**常驻分支真的写心跳**（15.a 的回归测试）
     ★★ 这是**唯一一条真能变红**的断言：把那段改回原样它就红。
        原缺陷的形状是「不报错、只是不动」—— `write_state()` 全在
        `once_round()` 里 ⇒ 常驻模式没有 `heartbeat_ts` ⇒
        `batch_alive()` 的容器分支**保守返回 True** ⇒ 「卡死被接管」永不发生。

★ 数法/行形：本文件只打印 `  ok  ` / ` FAIL `（`tests/README.md` 的形状 A）。
  **不许**自创行形 —— 新行形会让整份断言一条都不进账、而退出码仍是 0
  （`test_notify_drain.py` 实测过一次）。
★ 本文件**不碰任何状态文件**，所以不需要 `tempfile.mkdtemp()` 重定向；
  它只读仓库里的三个文件 + 做一次 AST 解析。
"""
from __future__ import annotations

import ast
import pathlib
import re
import subprocess
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

try:
    sys.stdout.reconfigure(encoding="utf-8")   # GBK 控制台会炸（tests/README.md）
except Exception:
    pass

try:
    import yaml                                  # orchestrator 的依赖，本仓必有
except Exception:                                # noqa: BLE001
    yaml = None

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


COMPOSE = REPO / "docker-compose.yml"
RESIDENT = REPO / "scripts" / "drive-loop-resident.sh"
DOCKER_PY = REPO / "scripts" / "drive-loop.py"
NAS_SH = REPO / "scripts" / "drive-loop-nas.sh"
DEPLOY = REPO / "deploy.sh"

# ★★ 整份测试的**前提**：文件在不在。缺了就直接红，别让后面十几条
#    全部"因为读不到而跳过"——那是把「没验」伪装成「通过」（B.10 第 14 条）。
ck("前提：docker-compose.yml 存在", COMPOSE.is_file(), str(COMPOSE))
ck("前提：scripts/drive-loop-resident.sh 存在", RESIDENT.is_file(), str(RESIDENT))
ck("前提：scripts/drive-loop.py 存在", DOCKER_PY.is_file(), str(DOCKER_PY))

# ==========================================================================
print("\n=== ① compose：drive-loop 服务的形状 ===")
# ==========================================================================
YML = None
if yaml is not None and COMPOSE.is_file():
    YML = yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))
ck("前提：本机有 PyYAML（没有就该红，而不是静默跳过）", YML is not None,
   "缺 PyYAML ⇒ ① 整段无法判")

if YML:
    svcs = YML.get("services") or {}
    dl = svcs.get("drive-loop")
    ck("①a compose 里有 drive-loop 服务", isinstance(dl, dict), repr(sorted(svcs)))

if YML and isinstance(svcs.get("drive-loop"), dict):
    dl = svcs["drive-loop"]

    # ---- ①b profiles 锁（★ 这是本文件最重要的一条）------------------------
    ck("★★ ①b drive-loop 有 profiles（安全锁：删掉它就会被 up -d 默认拉起来）",
       dl.get("profiles") == ["drive-loop"], repr(dl.get("profiles")))
    #   ★ 反向：别的服务**不许**带 profile。少了这条，一个手滑把 profile
    #     加到 prowlarr 上就会把它锁住，而表现是"cross-seed 搜不到任何站"。
    _others = {n: s.get("profiles") for n, s in svcs.items()
               if n != "drive-loop" and s.get("profiles")}
    ck("★★ ①c 其余服务**都不带** profiles（带 = 被一起锁住，另一种事故）",
       _others == {}, repr(_others))

    # ---- ①d 不写 build:（NAS 上 build 上下文不同）-------------------------
    ck("★ ①d drive-loop 不写 build:（NAS 的构建上下文是 compose 目录，写了会炸）",
       "build" not in dl, repr(dl.get("build")))

    # ---- ①e image 已 load 的那个 tag --------------------------------------
    ck("①e image = reseed-drive-loop:0.1.0（已 build + 已 load 到 NAS 的那个标）",
       dl.get("image") == "reseed-drive-loop:0.1.0", repr(dl.get("image")))

    # ---- ①f logging 锚点没漏（漏了 = 无上限日志，/volume1 只剩约 20 GB）----
    _lg = dl.get("logging")
    ck("①f 有 logging（走 `*logging-limits` 锚点，且已被解析成 json-file+上限）",
       isinstance(_lg, dict) and _lg.get("driver") == "json-file"
       and _lg.get("options", {}).get("max-size") == "10m", repr(_lg))

    # ---- ①g 常驻语义：restart 要对，且 command 不是"跑一批就退出"---------
    ck("①g restart = unless-stopped（常驻服务）",
       dl.get("restart") == "unless-stopped", repr(dl.get("restart")))
    _cmd = dl.get("command")
    _cmd_s = " ".join(_cmd) if isinstance(_cmd, list) else str(_cmd)
    ck("①h command 指向 run-resident.sh", "run-resident.sh" in _cmd_s, _cmd_s)
    #   ★★ 这一条就是常驻与 `--once` 的分界。command 上带了它 ⇒ 跑一批就退出。
    ck("★★ ①i command **不带** --once（带了 = 跑一批就退出，被 restart 反复拉起）",
       "--once" not in _cmd_s, _cmd_s)

    # ---- ①j 两条网络都要（缺一条就有一半服务名解析不了）-------------------
    _nets = dl.get("networks") or []
    if isinstance(_nets, dict):                  # compose config 渲染后的形态
        _nets = list(_nets)
    ck("★ ①j networks 同时含 reseed-net 与 qbit-net（缺一条就连不上另一个服务）",
       "reseed-net" in _nets and "qbit-net" in _nets, repr(_nets))

    # ---- ①k 两条挂载都是 1:1（左右逐字相等）-------------------------------
    _vols = dl.get("volumes") or []
    _bad_mounts = []
    for v in _vols:
        if isinstance(v, dict):                  # 渲染后：{type,source,target}
            src, tgt = v.get("source"), v.get("target")
        else:
            parts = str(v).split(":")
            src, tgt = (parts[0], parts[1]) if len(parts) >= 2 else ("", "")
        if src != tgt or not src:
            _bad_mounts.append(str(v))
    ck("★ ①k 两条挂载都是 1:1 同名同路径（代码里的路径全是绝对的，挑挂会静默退化）",
       _vols and not _bad_mounts, repr(_bad_mounts or _vols))
    #   ★ 顺带钉住**必须是整目录/整卷**：挂成子目录会静默退化
    #   （`first_existing()` 返回 None + 一行 warning），而不是报错。
    _vol_s = " ".join(str(v) for v in _vols)
    ck("★ ①l 挂的是整个 compose 目录 + 整个媒体卷（不是挑子目录）",
       "/volume2/docker_ssd/prowlarr_cross-seed_autohardlink" in _vol_s
       and "/volume1/video" in _vol_s, _vol_s)

    # ---- ①m 容器方言：PY / SUDO ----------------------------------------
    _env = dl.get("environment") or []
    if isinstance(_env, dict):
        _env = [f"{k}={v}" for k, v in _env.items()]
    _env_s = " ".join(str(e) for e in _env)
    ck("★ ①m environment 给了容器方言 PY / SUDO（并把 TZ 透进去）",
       "PY=python" in _env_s and "SUDO=" in _env_s and "TZ=" in _env_s, _env_s)

    # ---- ①n ★ 不加 user:（与另三个服务不同，这是刻意的）------------------
    #   宿主那份由 DSM 以 root 跑 ⇒ 状态文件属主是 root。容器若切成
    #   ${PUID}:${PGID}，同一个文件两个属主换来换去，必然有一边写不进去。
    ck("★ ①n drive-loop **不加** user:（与宿主那份同为 root，否则属主来回换）",
       "user" not in dl, repr(dl.get("user")))

# ==========================================================================
print("\n=== ② compose：profiles 的**真语义**（有 docker 就真跑）===")
# ==========================================================================
# ★ ①b 只断言「YAML 里有那个键」。它**证明不了** compose 真会把它排除在默认之外 ——
#   而"这条锁到底锁没锁上"恰恰是本改动最要紧的问题。
#   ⇒ 有 docker 时**真跑一遍** `config --services` 两个方向都看。
#   ★ 没有 docker 时**必须是"未验"，不是"通过"**（B.10 第 14 条：
#     空集/拿不到 都不许读成"没事"）—— 所以这里打印的是一条 `--` 行，
#     它**不计入断言数**，但把"这条没验"写在脸上。
_DOCKER = None
try:
    _r = subprocess.run(["docker", "compose", "version"],
                        capture_output=True, text=True, timeout=30)
    if _r.returncode == 0:
        _DOCKER = True
except Exception:                                # noqa: BLE001
    _DOCKER = False

if _DOCKER:
    def _svc_names(*extra):
        r = subprocess.run(["docker", "compose", "-f", str(COMPOSE), *extra,
                            "config", "--services"],
                           capture_output=True, text=True, timeout=120)
        return r.returncode, set((r.stdout or "").split())

    _rc0, _default = _svc_names()
    _rc1, _profiled = _svc_names("--profile", "drive-loop")
    ck("②a docker compose 解析得动这份 compose", _rc0 == 0 and _rc1 == 0,
       repr((_rc0, _rc1)))
    #   ★★ 这条是 profiles 锁的**真判据**：默认集里**必须没有** drive-loop。
    ck("★★ ②b 默认（不加 --profile）**不含** drive-loop —— 这就是那把锁",
       "drive-loop" not in _default, repr(sorted(_default)))
    ck("★★ ②c 加 --profile drive-loop 后**才**出现（显式启用才生效）",
       "drive-loop" in _profiled, repr(sorted(_profiled)))
    ck("★ ②d 默认集仍含其余四个（锁只锁住了 drive-loop，没误伤）",
       {"prowlarr", "flaresolverr", "cross-seed", "reseed-orchestrator"}
       <= _default, repr(sorted(_default)))
else:
    print("  --   本机没有可用的 docker ⇒ ② 段未验（**不是通过**）。")
    print("  --   要补验：在有 docker 的机器上跑 "
          "`docker compose config --services`，默认集里应当**没有** drive-loop。")

# ==========================================================================
print("\n=== ③ 常驻入口脚本：命令行区段 ===")
# ==========================================================================
# ★★ 判据的取法很要紧：`--once` **必须**在注释里出现（要解释为什么不要它），
#    所以「grep 全文」那种写法**恒红**、改一改就会退化成一个被删掉的断言。
#    ⇒ 只看**参数区段**：从 `RC=0` 那一行到 `exit "$RC"`。
_SH = RESIDENT.read_text(encoding="utf-8") if RESIDENT.is_file() else ""
#   ★★★ 取「参数区段」**故意不用正则** —— 我在这一处**连错三次**，
#      三次都是同一个原因：模式里要匹配的是 shell 的 `$RC`（一个**字面美元号**），
#      而它在正则里有第二种含义（行尾锚），得写 `\$` 才是字面量；
#      我写的却是裸 `$` ⇒ **恒不匹配** ⇒ 区段取不到 ⇒ ③ 段全假红。
#      ★ 而"红"的位置在 ③bcd（说 --url 不见了），与真因（正则写错）**隔着两层**。
#      ⇒ 教训与 `tests/README.md` 那条同族：**报红时先怀疑断言本身**。
#        而更实用的一步是：**别让判据需要转义** —— 按**行**取，不做模式匹配。
#      ⇒ 于是这里用最笨也最不会错的办法：找 `RC=0` 那一行的下标，
#        再找它之后第一个 `exit ` 开头的行。
_lines_sh = _SH.splitlines()
_i_start = next((i for i, l in enumerate(_lines_sh) if l.rstrip() == "RC=0"), None)
#   ★★ 边界取「**第一条空行**」——不是 `exit` 那一行。
#      我在这里又错了一次：区段取到 `exit "$RC"` 那行会**顺带收进**
#      `echo "... exit=$RC" >> "$ATTEMPTS"`（207 行）⇒ ③e 判"最后一行参数是不是
#      `"$@"`"时，读到的是那行 echo ⇒ **假红**，而脚本是对的。
#      ⇒ 参数块的结构是「`RC=0` / 若干续行 / 空行 / 收尾」。**空行就是边界。**
#      这条比"找 exit 行"稳：它不依赖后面有多少注释、注释里写了什么。
_i_blank = next((i for i, l in enumerate(_lines_sh)
                 if i > (_i_start or 0) and not l.strip()), None)
_ARGV = ("\n".join(_lines_sh[_i_start + 1:_i_blank])
         if _i_start is not None and _i_blank is not None else "")

ck("前提：找得到参数区段（`RC=0` 行 … 其后第一条空行）—— 找不到就该红",
   _i_start is not None and _i_blank is not None,
   f"start={_i_start} blank={_i_blank}（取不到 ⇒ ③ 段会变成空转）")
if _i_start is None or _i_blank is None:
    print("  FAIL 参数区段取不到 ⇒ ③ 段无法继续（下面几条**不是**代码的问题）")
    sys.exit(1)

ck("★★ ③a 参数区段里**没有** --once（带上 = 跑一批就退出，常驻变轮询）",
   "--once" not in _ARGV, _ARGV.strip())
ck("★★ ③b 参数区段里有 --url 与 --qbit-url（容器内必须服务名直连；"
   "群晖上『容器→宿主 LAN IP→DNAT』timeout）",
   "--url" in _ARGV and "--qbit-url" in _ARGV, _ARGV.strip())
ck("③c 两个 URL 是**服务名**，不是 ${NAS_IP} / 局域网 IP",
   "http://cross-seed:2468" in _ARGV and "http://qbittorrent-reseed:3060" in _ARGV,
   _ARGV.strip())
ck("③d 带 --env \"$COMPOSE_DIR/.env\"（TORZNAB 那几个 apikey 的来源）",
   '--env "$COMPOSE_DIR/.env"' in _ARGV, _ARGV.strip())
#   ★ 同样别用正则抠 `"$@"`（`$` 在正则里有含义，写成 `\$` 又会变字面反斜杠）。
#     ✓ 和 ✗ 的差别就在**最后一行参数**上，用字符串尾判最直白也最难写错。
_ARGV_LAST = [l for l in _ARGV.splitlines() if l.strip() and not l.strip().startswith("#")]
ck('③e "$@" 放最后（用户给的参数覆盖脚本里定的）—— 判据是**最后一行参数**',
   bool(_ARGV_LAST) and _ARGV_LAST[-1].strip().startswith('"$@"'),
   repr(_ARGV_LAST[-1].strip() if _ARGV_LAST else None))

# ---- ③f ★★ 名单两个声明点必须逐字一致 -------------------------------------
#   本文件是 `--indexers` 的**第二个**声明点。加了站却漏改一处 ⇒ 新站永远搜不到，
#   而 Prowlarr / cross-seed 那边一切正常（2026-09-12 就是这么卡住 224 部的）。
#   ⇒ 这是本文件里**唯一**能抓住那种漂移的断言。
#   ★★ 取名单必须**按行**取脚本里**真正的那个参数行**，不能全文搜 ——
#      两个文件里都有**注释**在讲 `--indexers`（本文件的注释里还引用了这句话），
#      全文搜会**抓到注释里的字**，于是这条断言永远绿、什么也没钉住。
#      （第一次跑就是这么绿的：resident 侧抓到了注释里的「手工维护」。）
def _argline(path: pathlib.Path, flag: str):
    if not path.is_file():
        return None
    for ln in path.read_text(encoding="utf-8").splitlines():
        s = ln.strip()
        if s.startswith("#"):
            continue
        if s.startswith(flag + " "):
            return s[len(flag):].strip().rstrip(" \\").strip()
    return None


_rd_s = _argline(RESIDENT, "--indexers")
_nd_s = _argline(NAS_SH, "--indexers")
ck("前提：两份入口都找得到 --indexers 名单", _rd_s is not None and _nd_s is not None,
   repr((_rd_s, _nd_s)))
ck("★★ ③f --indexers 与 drive-loop-nas.sh（生产在跑的那份）**逐字相同**"
   "（两个声明点，漏改一处 = 新站永远搜不到）",
   _rd_s is not None and _rd_s == _nd_s,
   f"resident={_rd_s!r} nas={_nd_s!r}")

_rl_s = _argline(RESIDENT, "--limit")
_nl_s = _argline(NAS_SH, "--limit")
ck("③g --limit 与 run.sh 一致（两个入口的批量口径不许分叉）",
   _rl_s is not None and _rl_s == _nl_s,
   f"resident={_rl_s!r} nas={_nl_s!r}")

# ---- ③h 留痕与前置闸门 ----------------------------------------------------
ck("③h attempts.log 的行带 [resident] 标记（两条路共用这个文件，"
   "标记是唯一能分清谁写的办法）",
   "[resident]" in _SH, "没有 [resident]")
ck("★ ③i 有前置闸门：读 .drive-loop.state 并能在「另一条路在跑」时退出"
   "（§26.5 前提 ② 的兜底）",
   ".drive-loop.state" in _SH and re.search(r"exit\s+3\b", _SH) is not None,
   "没有读状态 / 没有非零退出")
ck("★ ③j 闸门**不读 pid**，读的是 mode（跨 pid 命名空间判 pid 是假信号）",
   '"mode"' in _SH or "'mode'" in _SH, "没引用 mode")

# ==========================================================================
print("\n=== ④ 宿主入口那份**没被改**（生产在跑，不该动）===")
# ==========================================================================
#   ★ 为什么值得单独钉：常驻入口是**照抄**它的形状。以后有人回头"顺手统一一下"
#     就会把 `--once` 从 run.sh 删掉 —— 而 DSM 任务调的就是它，
#     删了之后那条任务会变成"每次唤醒起一个永不退出的进程"。
_NSH = NAS_SH.read_text(encoding="utf-8") if NAS_SH.is_file() else ""
ck("★★ ④a drive-loop-nas.sh（生产那份）**仍然带 --once** —— 它是 DSM 一次性调用",
   re.search(r"^\s+--once\s*\\?$", _NSH, re.M) is not None,
   "run.sh 的 --once 不见了")
#   ★ 同样只看**参数行**：`run.sh` 的注释里**必须**能有 `--url`（它要解释
#     "刻意不写这两个参数"）⇒ 全文搜恒红。
ck("★ ④b drive-loop-nas.sh **仍然不传** --url / --qbit-url（宿主上默认值就对，"
   "重复写一份只会多一个漂移点）",
   _argline(NAS_SH, "--url") is None and _argline(NAS_SH, "--qbit-url") is None
   and "--url" in _NSH,
   "run.sh 的参数行上出现了 --url，或注释里那句解释被删掉了")

# ==========================================================================
print("\n=== ⑤ drive-loop.py：常驻分支真的写心跳（15.a 回归）===")
# ==========================================================================
#   ★★ 这是**唯一一条真能变红**的断言：把常驻分支改回去（把 `_resident_state`
#      的调用与 `with Heartbeat()` 删掉）当场红。
#   ★ 用 AST 而不是 grep：grep 会被注释里的字样骗到（本改动**就是**一大段注释）。
#     但 AST 也给不出"在循环里"这件事 ⇒ 两条都要：
#       ⑤a/⑤b：AST 断言 `main()` 里**存在**这些调用（真判据，能红）
#       ⑤c   ：AST 断言含 `while` 循环（否则整段搬出循环也没人发现）
_SRC = DOCKER_PY.read_text(encoding="utf-8") if DOCKER_PY.is_file() else ""
_TREE = None
try:
    _TREE = ast.parse(_SRC)
except SyntaxError as e:
    ck("前提：drive-loop.py 能被 AST 解析", False, str(e))

_main = None
if _TREE is not None:
    for _n in ast.walk(_TREE):
        if isinstance(_n, ast.FunctionDef) and _n.name == "main":
            _main = _n
            break
ck("前提：找得到 `def main()`", _main is not None, "没找到 main()")

if _main is not None:
    #   ★★ 第一版这里写错过：`main.body` 里嵌套的调用被 `ast.Expr` **包着**，
    #      只扫 `isinstance(node, ast.Call)` 会一条都扫不到 ⇒ **假红** ——
    #      它报"前导段没写状态"，而代码是对的。
    #      ⇒ 用 `ast.walk` 递归，别自己写遍历。
    _calls, _withs = [], []
    for _node in ast.walk(_main):
        if isinstance(_node, ast.Call):
            _f = _node.func
            _nm = getattr(_f, "id", None) or getattr(_f, "attr", None)
            if _nm:
                _calls.append(_nm)
        if isinstance(_node, ast.With):
            for _it in _node.items:
                _f = _it.context_expr
                #   ★★ 又一次同样的错，这次在 ⑤b：`with Heartbeat():` 的
                #      `context_expr` 是一个 **`ast.Call`**，名字在 **`Call.func`** 上，
                #      不在 Call 自己身上 ⇒ `getattr(call, "id")` 恒为 None
                #      ⇒ `_withs` 恒为空 ⇒ **假红**（报"没有 with Heartbeat()"，
                #      而代码第 2587 行就是它）。
                #      ⇒ 与前面两次同族：**判据写错的样子和代码写错长得一样**。
                #        统一走"先解 Call.func"这一条路。
                if isinstance(_f, ast.Call):
                    _f = _f.func
                _nm = getattr(_f, "id", None) or getattr(_f, "attr", None)
                if _nm:
                    _withs.append(_nm)

    ck("★★ ⑤a 常驻分支调了写状态的东西（`write_state` 或 `_resident_state`）"
       "—— 这是 15.a 的**回归判据**：原缺陷是这一整段不存在",
       "write_state" in _calls or "_resident_state" in _calls,
       repr(sorted(set(_calls))[:12]))
    ck("★★ ⑤b 常驻分支有 `with Heartbeat()` 包着跑批 —— 批次里有长时间不发请求的"
       "阶段（等日志静默/回灌），靠「每发一条 webhook 刷一次」会漏",
       "Heartbeat" in _withs, repr(_withs))
    #   ★ 只断言"存在 while"**不够**（两个 Helper 都可能被搬出循环），
    #     但它能挡住"整段搬走"。真正的"在循环里"靠 ⑤a 的调用点分布兜 ——
    #     那需要在嵌套层级上判，而那种断言一改缩进就红（噪声 > 价值）。
    ck("★ ⑤c 常驻分支仍有 while 循环（判据是「常驻」，不是「跑一遍」）",
       any(isinstance(_n, ast.While) for _n in ast.walk(_main)), "main() 里没有 while")
    #   ★★ 心跳的**收尾**也必须有：只写不清 ⇒ 残留心跳会让下一轮误判
    #      「上一批还在跑」。判据是"存在把 running_pid 置 None 的那次写"。
    _none_writes = 0
    for _n in ast.walk(_main):
        if isinstance(_n, ast.Call) and (
                getattr(_n.func, "id", None) or getattr(_n.func, "attr", None)
        ) == "write_state":
            for _a in _n.args:
                if isinstance(_a, ast.Dict):
                    for _k, _v in zip(_a.keys, _a.values):
                        if (isinstance(_k, ast.Constant) and _k.value == "running_pid"
                                and isinstance(_v, ast.Constant) and _v.value is None):
                            _none_writes += 1
    ck("★★ ⑤d 收尾把 running_pid 置 None（残留心跳会让下一轮误判「上一批还在跑」）",
       _none_writes >= 1, f"找到 {_none_writes} 处")

# ==========================================================================
print("\n=== ⑥ deploy.sh：新脚本收进白名单 ===")
# ==========================================================================
_DEP = DEPLOY.read_text(encoding="utf-8") if DEPLOY.is_file() else ""
ck("⑥a deploy.sh 的 FILES 里有 drive-loop-resident.sh → drive-loop/run-resident.sh",
   '"scripts/drive-loop-resident.sh::drive-loop/run-resident.sh"' in _DEP,
   "白名单里没有它 ⇒ 部署后容器找不到入口脚本")
ck("⑥b drive-loop-nas.sh 仍在白名单里（生产那份不能被顶掉）",
   '"scripts/drive-loop-nas.sh::drive-loop/run.sh"' in _DEP, "run.sh 掉出白名单了")

# ==========================================================================
print(f"\n{'=' * 60}")
print(f"断言 {_ok + _bad} 条：{_ok} 过 / {_bad} 失败")
if not _DOCKER:
    print("★ ② 段（profiles 的真语义）**本机未验** —— 上面打的是 `--` 行，"
          "不是通过。别把本文件的绿读成「那把锁真的锁上了」。")
sys.exit(0 if _bad == 0 else 1)

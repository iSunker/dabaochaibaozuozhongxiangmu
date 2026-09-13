#!/bin/sh
# =====================================================================
# 删「暂存区」目录（**NAS 侧**，手动跑，不进计划任务）
#
# 为什么单独一个脚本
# ------------------
# 漂移哨兵的 `--cleanup` 会把杂物 `mv` 进 `<compose>/_cleanup-YYYYMMDD/`，
# 它的说明写的就是「确认后在 NAS 上整个删掉」。于是每清一次杂物就有一个
# 暂存区要人删，而删法有两条硬约束：
#   ① **只能在 NAS 上删**（原生路径）；对 UNC 跑 `rm` 是禁止的
#      —— SMB 上删是不走回收站的真删，且路径解析在 Windows 侧，容易打偏。
#   ② **不能走 DSM File Station**。File Station 的删除只是把文件挪进
#      `#recycle`，**文件仍在盘上**。而暂存区里最要紧的东西恰恰是
#      `.env*` —— 生产 `.env` 的**明文副本，带全部凭据**。
#      2026-09-13 实测：`//iSunker-DS423/docker_ssd/#recycle/env-bak-20260912/`
#      里就躺着 **8 个**凭据副本，全是之前几次「File Station 删除」留下的。
#      ★ 这 8 个里只有 **7 个**是 `.env.bak.<时间戳>` 形态，第 8 个是**不带后缀**
#        的 `.env.bak` —— 闸 ⑤ 的删除口径就是被它撑宽的，详见下面闸 ⑤ 那段。
#      ⇒ 走 File Station 删 = **凭据原地不动，还多 6 个**。
#
# 所以本脚本干的就是「在 NAS 上、绕开回收站、先把凭据删掉再删目录」这一件事，
# 并且把这件事写进版本库 —— 下次哨兵再攒出暂存区，参数一换就能用，
# 不用再往 DSM 的网页框里粘一遍代码。
#
# 用法
# ----
#   sh rm-staging.sh <绝对路径>            # 只列清单（默认，什么都不删）
#   sh rm-staging.sh <绝对路径> --apply    # 真删
#   sh rm-staging.sh --dir <绝对路径> --apply   # 同上，--dir 只是好读一点
#   sh rm-staging.sh --help
#
#   DSM → 控制面板 → 任务计划 → 新增 → **用户定义的脚本**，用户选 `root`，
#   脚本框里就一句（**手动运行**，不要设计划）：
#     sh /volume2/docker_ssd/prowlarr_cross-seed_autohardlink/rm-staging.sh \
#        /volume2/docker_ssd/prowlarr_cross-seed_autohardlink/_cleanup-20260912 --apply
#   ★ 这条**不要**勾「发送运行详情」的意义不大（一次性、手动），但勾了也无害。
#
#   —— 旧根残留（一次性，见闸 ③）：
#     sh /volume2/docker_ssd/prowlarr_cross-seed_autohardlink/rm-staging.sh \
#        /volume1/video/download/reseed_singles --apply
#   ★ 注意这里是 **`/volume1/...`**（真实数据路径），不是 `/volume2/...`
#     —— compose 在 volume2，数据在 volume1，两者本来就不在同一个卷上。
#   ★ 跑完请把闸 ③ 里那条 case 撤掉再 deploy 一次：它是残余清理，不是常态。
#
# 安全闸（五条，缺一不可）
# -----------------------
#   ① 必须是**绝对路径** —— 相对路径会被解读成「相对于任务计划的工作目录」，
#      而那个目录不是你能预先知道的。
#   ② 必须**存在、是目录、不是软链接**。软链接要单独拒：`rm -rf` 一个指向
#      `/volume1/video` 的链接会顺着删过去。
#   ③ ★ **只认三类路径**（这是本脚本存在的核心理由）：
#        · `_cleanup-*`               —— 哨兵的暂存区
#        · `#recycle/` 下的 `env-bak-*` —— 早先误删进回收站的明文 .env 副本
#        · `/volume1/video/download/reseed_singles` —— **旧根残留（一次性）**
#      其余一律拒绝。**生产上不许存在一个「给什么删什么」的脚本**，
#      哪怕它只由 root 手动跑 —— 手滑一次就是不可逆的。
#      ★ 第三类和前两类**判据不同**：它是**完整路径字面量**，不是 basename。
#        若按 basename 放行 `reseed_singles`，任何同名目录都跟着放行了；
#        写全路径 = 只放行这一处。**删完就该把这条撤掉**（它是残余清理，
#        不是常态；留着等于在生产上永久留一个能删视频目录的口子）。
#      ★ 放行它的依据 —— 2026-09-13 **全部实测，没有一条是推理**：
#        · 9 个文件 / 48.20 GiB；其中 8 个是**独立副本**（按 SMB 传回的
#          server inode/fid 判，可释放 44.60 GiB；剩下 1 个是硬链接，删了不释放）
#        · qB `:3060` 927 条 → 旧根 **0** 条；qB `:3020`(opencd) 1234 条 → 旧根 **0** 条
#          （opencd 的 API 回 403、免密不通，改读它自己的 `BT_backup`；
#           判据仍是 save_path 前缀，与读 API 时同一个判据）
#        · NAS `.env` 的 `LINK_DIR` 已指向**新根** ⇒ 没有任何配置再引用旧根
#        · 旧根不在任何 qB 的 save_path 下 ⇒ 删掉的不会是「正在做种的活文件」
#   ④ `--apply` 才动手；不加就是纯列清单。
#   ⑤ 先单独删凭据副本并复核归零，**再**删目录。
#      顺序是有意的：哪怕中途断电/报错，凭据也已经先走了。
#      ★ 删除口径是 **`.env*`（任何 `.env` 副本）**，不是 `.env.bak.*`
#        —— 2026-09-13 实测（README「漂移哨兵 / 已知窄口」）那个暂存区里
#        8 个凭据副本**只有 7 个**匹配 `.env.bak.*`，第 8 个是不带时间戳的
#        `.env.bak`。**口径宽松，闸 ⑤ 这句承诺才真的成立**；窄口径下它对
#        那个命名变体是假的 —— 而它恰恰是这条闸唯一的卖点。
#
# 本脚本**不做**的事
# ------------------
#   * 不删 `__pycache__`。它会自己长回来（下界 ≈ 正在跑的模块数），
#     为一个会自动复现的东西做脚本没有意义 —— 见 README「漂移哨兵」一节。
#   * 不碰 `state.db` / `.env` / 容器 / qB。它是纯文件系统操作，
#     和跑批完全正交，**不需要等批次间隙**。
# =====================================================================
set -eu

usage() {
  # ★ 锚点式，不写死行号：以前是 `sed -n '2,60p'`，而头部注释只加几行
  #   就会把最后几行截掉（**静默**——用法说明少几行没人会发现）。
  #   跟 build-farm.sh 用同一个写法：从第 2 行打到 `set -eu` 之前。
  awk 'NR>1 && /^set -eu/{exit} NR>1{print}' "$0" | sed 's/^# \{0,1\}//'
}

APPLY=0
P=""
while [ $# -gt 0 ]; do
  case "$1" in
    --apply) APPLY=1 ;;
    --dir)
      shift
      if [ $# -eq 0 ]; then
        echo "[!!] --dir 后面缺路径" >&2
        exit 2
      fi
      P="$1"
      ;;
    -h|--help) usage; exit 0 ;;
    -*)
      echo "[!!] 不认识的参数：$1（--help 看用法）" >&2
      exit 2
      ;;
    *)
      if [ -n "$P" ]; then
        echo "[!!] 给了不止一个路径（'$P' 和 '$1'）—— 一次只删一个，别蒙" >&2
        exit 2
      fi
      P="$1"
      ;;
  esac
  shift
done

if [ -z "$P" ]; then
  echo "[!!] 没给路径。用法见： sh $0 --help" >&2
  exit 2
fi

# 去掉结尾斜杠，否则 basename 会是空串、安全闸 ③ 形同虚设
P="${P%/}"

# ---- 闸 ① 绝对路径 ----
case "$P" in
  /*) : ;;
  *)
    echo "[!!] 必须是绝对路径（NAS 上的 /volumeX/...）。你给的是：$P" >&2
    exit 1
    ;;
esac
# 剥完斜杠后不能变空（原本是 "/" 或 "///" 这类）
if [ -z "$P" ]; then
  echo "[!!] 路径归一化后是空的 —— 拒绝" >&2
  exit 1
fi

# ---- 闸 ② 存在 / 是目录 / 不是软链接 ----
if [ ! -e "$P" ]; then
  echo "[!!] 不存在：$P" >&2
  exit 1
fi
if [ -L "$P" ]; then
  echo "[!!] 是软链接，拒绝（要删的是真实目录，不是你指向的地方）：$P" >&2
  exit 1
fi
if [ ! -d "$P" ]; then
  echo "[!!] 不是目录：$P" >&2
  exit 1
fi

# ---- 闸 ③ 只认三类路径 ----
# ★ 第一类按 **basename** 放行（`_cleanup-*` 带日期后缀，写不成字面量）；
#   第三类按 **完整路径字面量** 放行 —— 见头部闸 ③ 那段：
#   拿 basename 当通行证会把「任何叫这名字的目录」一起放行。
base=$(basename "$P")
parent=$(basename "$(dirname "$P")")
allowed=0
case "$P" in
  /volume1/video/download/reseed_singles) allowed=1 ;;   # 旧根残留（一次性，见头部闸 ③）
esac
if [ "$allowed" -eq 0 ]; then
  case "$base" in
    _cleanup-*) allowed=1 ;;
  esac
fi
if [ "$allowed" -eq 0 ] && [ "$parent" = "#recycle" ]; then
  case "$base" in
    env-bak-*) allowed=1 ;;
  esac
fi
if [ "$allowed" -eq 0 ]; then
  echo "[!!] 拒绝：本脚本只删三类路径，其余一律不碰 ——" >&2
  echo "       ① basename 形如 _cleanup-YYYYMMDD" >&2
  echo "       ② #recycle/ 下的 env-bak-*" >&2
  echo "       ③ /volume1/video/download/reseed_singles（旧根残留，一次性）" >&2
  echo "     你给的是：$P" >&2
  echo "     （basename=$base  parent=$parent）" >&2
  exit 1
fi

# ---- 清单 ----
# ★★ 凭据口径（2026-09-13 修）—— 这里有两个模式，**别混用**：
#     ENV_PAT  = `.env.bak*`  —— 只是「我们**预期**的备份命名」，用来**报数**；
#     ENV_SEAL = `.env*`      —— **真正拿来删**的口径（闸 ⑤ 用的就是它）。
#   为什么不一件事两个名字：上面那个窄口（`.env.bak.*` 只匹配 7/8）的教训
#   不是「再猜一次命名」，而是**别让「凭据删没删净」取决于我们猜得对不对**。
#   所以：删除口径放宽到「任何 `.env` 副本」，同时把**超出 ENV_PAT 的那些名字
#   点名打出来** —— 下一次命名再变，它是「报了一条你没见过的名字」，
#   而不是「计数悄悄少了一个」。（少一个数是**静默**的，静默的少算比报错坏得多。）
ENV_PAT='.env.bak*'
ENV_SEAL='.env*'
n_all=$(find "$P" -type f | wc -l)
n_env=$(find "$P" -type f -name "$ENV_PAT" | wc -l)
n_seal=$(find "$P" -type f -name "$ENV_SEAL" | wc -l)
n_odd=$((n_seal - n_env))
n_pyc=$(find "$P" -type f -name '*.pyc' | wc -l)

echo "目标          : $P"
echo "文件总数      : $n_all"
echo "  $ENV_PAT : $n_env   ← ★ 生产 .env 的**明文副本**（带全部凭据）"
echo "  *.pyc       : $n_pyc"
if [ "$n_odd" -gt 0 ]; then
  echo
  # ★ 字符串里**别用反引号**：双引号里的 `` 会被 shell 当命令替换（实测报
  #   `line NNN: .env*: command not found`，且**只是把那截文本吃掉**，
  #   不报错、不中断 —— 跟 Python 串里嵌 ASCII 引号是同一类坑）。中文引号「」安全。
  echo "★ 另外 $n_odd 个「.env*」**不在上面那个口径里** —— 名字没见过，"
  echo "  但同样是 .env 的副本、同样带凭据。**它们照样会先被删**（删除口径是 $ENV_SEAL）："
  find "$P" -type f -name "$ENV_SEAL" ! -name "$ENV_PAT" | sed 's/^/     /'
  echo "  ⇒ 这里出现陌生名字就是在提醒：备份命名又变了，回头把 ENV_PAT 跟上。"
fi

if [ "$APPLY" -eq 0 ]; then
  echo
  echo "（只读预检，**什么都没删**。清单如下）"
  find "$P" -type f | sed 's/^/   /'
  echo
  echo "确认无误后，加 --apply 再跑一次。"
  exit 0
fi

# ---- 闸 ⑤ 先删凭据，再删目录 ----
echo
echo "===== --apply ====="

echo "[1/2] 先删明文凭据"
# ★ 删的是 $ENV_SEAL（`.env*`，任何 .env 副本），不是 $ENV_PAT ——
#   理由见上面「两个模式」那段：**保证必须不依赖我们猜对命名**。
find "$P" -type f -name "$ENV_SEAL" -exec rm -f {} \;
n_seal_left=$(find "$P" -type f -name "$ENV_SEAL" | wc -l)
echo "      剩余 $ENV_SEAL = $n_seal_left"
if [ "$n_seal_left" -ne 0 ]; then
  echo "[!!] 有删不掉的（权限？文件被占用？）—— 目录就不动了，先查这个" >&2
  exit 1
fi

echo "[2/2] 再删目录"
rm -rf -- "$P"
if [ -d "$P" ]; then
  echo "[!!] 目录还在，删失败：$P" >&2
  exit 1
fi

echo
echo "OK：已删 $P"
echo "复核（Windows 侧，只读）： python scripts/check-deploy-drift.py"

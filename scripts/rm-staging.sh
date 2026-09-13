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
#      `.env.bak.*` —— 生产 `.env` 的**明文副本，带全部凭据**。
#      2026-09-13 实测：`//iSunker-DS423/docker_ssd/#recycle/env-bak-20260912/`
#      里就躺着 8 个 `.env.bak*`，全是之前几次「File Station 删除」留下的。
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
# 安全闸（五条，缺一不可）
# -----------------------
#   ① 必须是**绝对路径** —— 相对路径会被解读成「相对于任务计划的工作目录」，
#      而那个目录不是你能预先知道的。
#   ② 必须**存在、是目录、不是软链接**。软链接要单独拒：`rm -rf` 一个指向
#      `/volume1/video` 的链接会顺着删过去。
#   ③ ★ **只认两类 basename**（这是本脚本存在的核心理由）：
#        · `_cleanup-*`               —— 哨兵的暂存区
#        · `#recycle/` 下的 `env-bak-*` —— 早先误删进回收站的明文 .env 副本
#      其余一律拒绝。**生产上不许存在一个「给什么删什么」的脚本**，
#      哪怕它只由 root 手动跑 —— 手滑一次就是不可逆的。
#   ④ `--apply` 才动手；不加就是纯列清单。
#   ⑤ 先单独删 `.env.bak.*` 并复核归零，**再**删目录。
#      顺序是有意的：哪怕中途断电/报错，凭据也已经先走了。
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
  sed -n '2,60p' "$0" | sed 's/^# \{0,1\}//'
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

# ---- 闸 ③ 只认两类 basename ----
base=$(basename "$P")
parent=$(basename "$(dirname "$P")")
allowed=0
case "$base" in
  _cleanup-*) allowed=1 ;;
esac
if [ "$allowed" -eq 0 ] && [ "$parent" = "#recycle" ]; then
  case "$base" in
    env-bak-*) allowed=1 ;;
  esac
fi
if [ "$allowed" -eq 0 ]; then
  echo "[!!] 拒绝：本脚本只删两类路径，其余一律不碰 ——" >&2
  echo "       ① basename 形如 _cleanup-YYYYMMDD" >&2
  echo "       ② #recycle/ 下的 env-bak-*" >&2
  echo "     你给的是：$P" >&2
  echo "     （basename=$base  parent=$parent）" >&2
  exit 1
fi

# ---- 清单 ----
n_all=$(find "$P" -type f | wc -l)
n_env=$(find "$P" -type f -name '.env.bak.*' | wc -l)
n_pyc=$(find "$P" -type f -name '*.pyc' | wc -l)

echo "目标          : $P"
echo "文件总数      : $n_all"
echo "  .env.bak.*  : $n_env   ← ★ 生产 .env 的**明文副本**（带全部凭据）"
echo "  *.pyc       : $n_pyc"

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
find "$P" -type f -name '.env.bak.*' -exec rm -f {} \;
n_env_left=$(find "$P" -type f -name '.env.bak.*' | wc -l)
echo "      剩余 .env.bak.* = $n_env_left"
if [ "$n_env_left" -ne 0 ]; then
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

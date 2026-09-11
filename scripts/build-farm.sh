#!/bin/sh
# =====================================================================
# NAS 侧：构建 / 增量更新「硬链接农场」（v3 方案 B，见 SUMMARY §10.5）
#
# 农场是什么
# ----------
# 一个**扁平**目录，里面每个子项 = 一个大包里的「单片」，用硬链接指向真实数据
# （不占数据块，只多 inode + 目录项）。之后 cross-seed 的 `dataDirs` 就
# **只指向农场这一条**，不再需要 49 条、也不需要调大 maxDataDepth。
#
# 为什么是「每个 dataDir 的直接子项」——这条规则保证等价
# ------------------------------------------------------
# cross-seed 枚举 searchee 的规则是：
#     dataDirs.flatMap(dd => readdir(dd).flatMap(c => findNestedRoots(c, maxDataDepth)))
# 农场的子项恰好 = 原来那 49 个 dataDir 的直接子项之并集，
# 于是「农场 + depth=2」与「49 个 dataDir + depth=2」**逐条产出完全相同的 searchee**。
# ★ 注意：这是**构造上**的等价，不依赖我们对 depth 规则的建模是否精确
#   —— 同一个函数作用在同一批首层条目上，结果必然一样。
#   镜像源目录结构（硬链接正好做到这点）是它成立的前提。
#
# 用法（NAS 上，SSH 或 Container Manager「终端」均可）
# ---------------------------------------------------
#   sh build-farm.sh                  # 默认 dry-run：只统计和预演，一个文件都不建
#   sh build-farm.sh --apply          # 真建（增量：已存在的跳过）
#   sh build-farm.sh --apply --prune  # 顺带删掉"源已经没了"的农场条目
#   sh build-farm.sh --verify         # 只校验农场 vs 源，不建不删
#
# 环境变量
#   COMPOSE_DIR  含 .env 的目录（默认 /volume2/docker_ssd/prowlarr_cross-seed_autohardlink）
#   FARM         农场路径（默认 /volume1/video/download/reseed_farm）
#   SUDO         root 提权前缀（默认 sudo；已经是 root 就设 SUDO=）
#
# 为什么必须上 NAS 跑
# -------------------
# SMB/Windows **建不了硬链接**（这是协议限制，不是权限问题），只有 NAS 本机
# 或容器内能建。所以本脚本由用户在 NAS 上执行，本地只负责审阅和事后校验。
#
# 安全边界（本脚本**只增不删**，除 --prune）
#   * 绝不写源目录（只读源、只在 $FARM 下建）
#   * ★ 绝不 `chown -R`：硬链接文件与源文件是**同一个 inode**，
#     对链接文件 chown 会**改掉源文件的属主**。只对目录 chown（目录是新造的，不在 inode 上共享）
#   * 跨卷会失败 → 先 stat -c %d 比设备号，给出人话报错
#   * 幂等：重复跑不会重复建，也不会改已存在的东西
# =====================================================================
set -eu

COMPOSE_DIR="${COMPOSE_DIR:-/volume2/docker_ssd/prowlarr_cross-seed_autohardlink}"
FARM="${FARM:-/volume1/video/download/reseed_farm}"
SUDO="${SUDO-sudo}"

DRY=1
PRUNE=0
VERIFY_ONLY=0
for a in "$@"; do
  case "$a" in
    --apply)       DRY=0 ;;
    --dry-run)     DRY=1 ;;
    --prune)       PRUNE=1 ;;
    --verify)      VERIFY_ONLY=1; DRY=1 ;;
    -h|--help)     sed -n '2,45p' "$0"; exit 0 ;;
    *) echo "未知参数: $a  (可用: --apply | --dry-run | --prune | --verify | -h)" >&2; exit 2 ;;
  esac
done

say() { echo "$@"; }
die() { echo "[!!] $*" >&2; exit 1; }

cd "$COMPOSE_DIR" 2>/dev/null || die "目录不存在: $COMPOSE_DIR"
[ -f .env ] || die "$COMPOSE_DIR/.env 不存在"
[ -d "$FARM" ] || {
  if [ "$DRY" = 1 ]; then
    say "[dry-run] 农场还不存在，--apply 时会创建：$FARM"
  else
    mkdir -p "$FARM" || die "建不了农场目录: $FARM"
  fi
}

# ---------- 1) 源清单：直接从 .env 的 DATA_DIRS 读，不另存一份，永不漂移 ----------
DATA_DIRS=$(sed -n 's/^[[:space:]]*DATA_DIRS[[:space:]]*=[[:space:]]*//p' .env | head -1)
[ -n "$DATA_DIRS" ] || die "从 $COMPOSE_DIR/.env 读不到 DATA_DIRS"

# 清单文件放在农场**外面**（农场内任何文件都会被 cross-seed 枚举到，
# 虽然 .tsv 扩展名会被它的 shouldIgnore 过滤掉，但没必要冒险）
MANIFEST="$(dirname "$FARM")/.$(basename "$FARM").manifest.tsv"

# 农场还不存在时（第一次跑），退到**最近的已存在祖先目录**取设备号 ——
# mkdir -p 造出来的新目录必然落在那个祖先所在的文件系统上。
DEV_PROBE="$FARM"
while [ ! -d "$DEV_PROBE" ] && [ "$DEV_PROBE" != "/" ] && [ -n "$(dirname "$DEV_PROBE")" ]; do
  DEV_PROBE=$(dirname "$DEV_PROBE")
done
DEV_FARM=$(stat -c %d "$DEV_PROBE" 2>/dev/null || echo "")
[ -n "$DEV_FARM" ] || die "stat 不可用，无法校验同卷（本脚本依赖 coreutils）"

# 能力自检：cp -al 是整套方案的关键（-a 保结构、-l 建硬链接而非复制）
if ! cp -al "$COMPOSE_DIR/.env" "$COMPOSE_DIR/.env.hlprobe" 2>/dev/null; then
  die "本机的 cp 不支持 -al（硬链接复制），无法构建农场"
fi
rm -f "$COMPOSE_DIR/.env.hlprobe"

say "===================== 硬链接农场构建 ====================="
say "  .env       : $COMPOSE_DIR/.env"
say "  农场       : $FARM"
say "  清单       : $MANIFEST"
say "  模式       : $( [ "$VERIFY_ONLY" = 1 ] && echo '仅校验' || { [ "$DRY" = 1 ] && echo 'DRY-RUN（不建）' || echo 'APPLY'; } )$([ "$PRUNE" = 1 ] && echo ' + prune')"
say "========================================================="

# ---------- 2) 逐 dataDir、逐直接子项处理 ----------
# set -f：关掉通配符展开。DC 的路径里有全角括号和点，虽然不含 * 或 ?，
# 但把 DATA_DIRS 按逗号拆开时让 shell 别去 glob 更稳妥。
set -f
OLDIFS=$IFS
IFS=,
N_NEW=0; N_HAVE=0; N_MISS=0; N_SRC=0; N_SKIP_DEV=0
# 本次的「期望集」：名字列表（给 prune 做精确比对）+ 名字→源（给人看）
NAMES_TMP="$MANIFEST.names.tmp"
: > "$NAMES_TMP"
: > "$MANIFEST.tmp"

for dd in $DATA_DIRS; do
  [ -n "$dd" ] || continue
  set +f
  if [ ! -d "$dd" ]; then
    say "  [!!] 源目录不存在，跳过: $dd"
    N_MISS=$((N_MISS + 1))
    continue
  fi
  DEV_SRC=$(stat -c %d "$dd")
  if [ "$DEV_SRC" != "$DEV_FARM" ]; then
    say "  [!!] 与农场不在同一物理卷，跳过: $dd"
    say "       （硬链接只能同卷；农场的 FARM 要落在同一卷上）"
    N_SKIP_DEV=$((N_SKIP_DEV + 1))
    continue
  fi
  OWNER=$(stat -c '%u:%g' "$dd")

  # 直接子项 = 农场条目。这就是全部"规则"，没有深度计算。
  for src in "$dd"/*; do
    [ -e "$src" ] || continue
    name=$(basename "$src")
    dst="$FARM/$name"
    N_SRC=$((N_SRC + 1))

    # ★ 无论新建还是已存在，都要记进**期望集** —— prune 靠它判断"哪些该留"。
    #   （早期版本只记新建的，结果 prune 把已存在的一律当成过期删光。）
    printf '%s\n' "$name" >> "$NAMES_TMP"
    printf '%s\t%s\n' "$name" "$src" >> "$MANIFEST.tmp"

    if [ -e "$dst" ]; then
      N_HAVE=$((N_HAVE + 1))
      set -f; continue
    fi

    if [ "$DRY" = 1 ]; then
      N_NEW=$((N_NEW + 1))
      set -f; continue
    fi

    # ★ cp -al：建目录结构 + 对每个文件建**硬链接**（不复制数据）
    if ! cp -al "$src" "$dst" 2>/dev/null; then
      # 退一步：低版本 cp 不认 -al 的组合时，走 find + ln
      mkdir -p "$dst" && find "$src" -type d -exec mkdir -p "$dst"/{} \; 2>/dev/null || true
      if ! ( cd "$src" && find . -type f -exec sh -c '
             d="$2"; mkdir -p "$(dirname "$d")"; ln "$1" "$d"' _ {} "$dst"/{} \; ) 2>/dev/null; then
        say "  [!!] 建链接失败: $name"
        set -f; continue
      fi
    fi
    # 只给**目录**改属主：目录是新造的；文件是硬链接 = 同一个 inode，
    # 对其 chown 会连带改掉源文件属主（灾难）。所以这里绝不能加 -R。
    find "$dst" -type d -exec chown "$OWNER" {} + 2>/dev/null || true

    N_NEW=$((N_NEW + 1))
    set -f
  done
  set -f
done
IFS=$OLDIFS
set +f

N_EXPECT=$(wc -l < "$NAMES_TMP" 2>/dev/null | tr -d ' \t' || echo 0)
N_FARM=0
for dst in "$FARM"/*; do [ -e "$dst" ] && N_FARM=$((N_FARM + 1)); done

# ---------- 3) prune：农场里有、期望集里没有 → 源已经没了（或改名了）----------
N_PRUNE=0
if [ "$PRUNE" = 1 ] && [ "$N_FARM" -gt 0 ]; then
  # ★ 安全闸：期望集为空却要 prune = 几乎一定是 DATA_DIRS 读错/全都没了，
  #   真删下去会把**整个农场删光**。宁可停下让人看一眼。
  if [ "$N_EXPECT" -eq 0 ]; then
    say ""
    say "  [!!] 期望集为 0，但农场里有 $N_FARM 条 —— 拒绝 prune。"
    say "       多半是 $COMPOSE_DIR/.env 的 DATA_DIRS 读不到，或所有源目录都不存在。"
    say "       先跑一次不带 --prune 的 --apply 看清楚，再决定。"
  else
    for dst in "$FARM"/*; do
      [ -e "$dst" ] || continue
      name=$(basename "$dst")
      if ! grep -qxF "$name" "$NAMES_TMP" 2>/dev/null; then
        if [ "$DRY" = 1 ]; then
          say "  [prune·预演] 将删除: $name"
        else
          say "  [prune] 源已不存在，删除农场条目: $name"
          rm -rf "$dst"
        fi
        N_PRUNE=$((N_PRUNE + 1))
      fi
    done
  fi
fi

# ---------- 3b) 期望集落盘（apply 时；dry-run 不留任何东西）----------
if [ "$DRY" = 0 ]; then
  mv -f "$NAMES_TMP" "$MANIFEST.names" 2>/dev/null || cp -f "$NAMES_TMP" "$MANIFEST.names"
  mv -f "$MANIFEST.tmp" "$MANIFEST" 2>/dev/null || cp -f "$MANIFEST.tmp" "$MANIFEST"
fi
rm -f "$NAMES_TMP" "$MANIFEST.tmp" 2>/dev/null || true
# ---------- 4) 汇总 ----------
say ""
say "源直接子项合计 : $N_SRC   （= 本次期望集 $N_EXPECT 条）"
if [ "$VERIFY_ONLY" = 1 ]; then
  say "农场现有条目   : $N_FARM"
  say "源有但农场没有 : $((N_EXPECT - N_HAVE))"
  say "农场有但源没有 : $((N_FARM - N_HAVE))   （加 --prune 的预演可看明细）"
elif [ "$DRY" = 1 ]; then
  say "★ 将要新建     : $N_NEW   （dry-run，什么都没建）"
  say "  已存在(跳过) : $N_HAVE"
  say "  源目录缺失   : $N_MISS"
  say "  跨卷跳过     : $N_SKIP_DEV"
  [ "$PRUNE" = 1 ] && say "  将要删除     : $N_PRUNE   （--prune 预演）"
  say ""
  say "看清楚了就加 --apply 真建。"
else
  say "★ 新建         : $N_NEW"
  say "  已存在(跳过) : $N_HAVE"
  say "  源目录缺失   : $N_MISS"
  say "  跨卷跳过     : $N_SKIP_DEV"
  [ "$PRUNE" = 1 ] && say "  已删除       : $N_PRUNE"
  say ""
  say "下一步（人工确认无误后）——把 cross-seed 的 dataDirs 从 49 条切成农场这一条："
  say "  1) 本地 .env 里把 DATA_DIRS 改成：$FARM"
  say "  2) python scripts/gen-nas-env-update.py   （生成新的 nas-update-env.sh）"
  say "  3) 在 NAS 上跑 sh nas-update-env.sh       （改 .env + --force-recreate 容器）"
  say "  4) 验证：drive-loop 日志里「索引器自检」与 searchee 数应与切换前一致"
fi

#!/usr/bin/env bash
# =====================================================================
# 本地 → NAS 生产 的白名单同步
#   本地: 本仓库根目录（默认 = 脚本所在目录，可用 SRC 覆盖）
#   生产: NAS 上的 compose 目录（必须用 DST 指定）
#
# 原则：
#   1. 白名单 —— 只覆盖 FILES 里列出的文件，其余一律不碰。
#   2. 绝不覆盖生产独有/含密钥的内容：
#      .env(真实 apikey) / prowlarr/(站点 cookie+db) / cross-seed 的 db 与
#      cross-seeds 输出 / hlink 日志。它们不在白名单里，动不到。
#   3. 覆盖前备份到本地 .deploy-backup/<时间戳>/（放本地，避免污染 NAS 上的
#      docker build 上下文），可一键回滚。
#   4. 默认 dry-run 只打 diff；--apply 才写入。
#
# 用法:
#   DST=//my-nas/docker_ssd/prowlarr_cross-seed_autohardlink bash deploy.sh             预览差异
#   DST=//my-nas/docker_ssd/prowlarr_cross-seed_autohardlink bash deploy.sh --apply     写入（先自动备份）
#   DST=//my-nas/docker_ssd/prowlarr_cross-seed_autohardlink bash deploy.sh --rollback  回滚到最近一次备份
#
#   DST 也可写进 scripts/.nasrc（已 gitignore），避免每次输入。
# =====================================================================
set -euo pipefail

SELF_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
[[ -f "$SELF_DIR/scripts/.nasrc" ]] && source "$SELF_DIR/scripts/.nasrc"

SRC="${SRC:-$SELF_DIR}"
DST="${DST:?请设置 DST（NAS 上的 compose 目录），例如 DST=//my-nas/docker_ssd/prowlarr_cross-seed_autohardlink}"
BACKUP_ROOT="$SRC/.deploy-backup"

# <本地相对路径>::<生产相对路径>
# 注意 compose 文件两边命名不同: 本地 docker-compose.yml → 生产 compose.yaml
FILES=(
  "docker-compose.yml::compose.yaml"
  "cross-seed/config.js::cross-seed/config.js"
  "hlink/config.yml::hlink/config.yml"
  ".dockerignore::.dockerignore"
  "orchestrator/Dockerfile::orchestrator/Dockerfile"
  "orchestrator/requirements.txt::orchestrator/requirements.txt"
  "orchestrator/__init__.py::orchestrator/__init__.py"
  "orchestrator/config.py::orchestrator/config.py"
  "orchestrator/crossseed_client.py::orchestrator/crossseed_client.py"
  "orchestrator/hardlink.py::orchestrator/hardlink.py"
  "orchestrator/http.py::orchestrator/http.py"
  "orchestrator/main.py::orchestrator/main.py"
  "orchestrator/matcher.py::orchestrator/matcher.py"
  "orchestrator/qbit_client.py::orchestrator/qbit_client.py"
  "orchestrator/safety.py::orchestrator/safety.py"
)

MODE="${1:---dry-run}"
case "$MODE" in
  --apply|--rollback|--dry-run) ;;
  *) echo "未知参数: $MODE  (可用: --apply | --rollback | --dry-run)" >&2; exit 2 ;;
esac

[[ -d "$SRC" ]] || { echo "✗ 本地目录不存在: $SRC" >&2; exit 1; }
[[ -d "$DST" ]] || { echo "✗ 生产目录不可达（检查 SMB 连接）: $DST" >&2; exit 1; }

# ---------- 回滚 ----------
if [[ "$MODE" == "--rollback" ]]; then
  LATEST="$(ls -1 "$BACKUP_ROOT" 2>/dev/null | sort | tail -1 || true)"
  [[ -n "${LATEST:-}" ]] || { echo "✗ 没有任何备份: $BACKUP_ROOT" >&2; exit 1; }
  echo "→ 从备份回滚: $LATEST"
  ( cd "$BACKUP_ROOT/$LATEST"
    find . -type f | while read -r f; do
      f="${f#./}"
      echo "  恢复 $f"
      mkdir -p "$DST/$(dirname "$f")"
      cp -p "$f" "$DST/$f"
    done )
  echo "✓ 回滚完成。NAS 上记得: sudo docker compose up -d --force-recreate cross-seed"
  exit 0
fi

# ---------- 算差异 ----------
CHANGED=()
for p in "${FILES[@]}"; do
  s="${p%%::*}"; d="${p##*::}"
  if [[ ! -f "$SRC/$s" ]]; then
    echo "⚠ 本地缺失，跳过: $s" >&2
    continue
  fi
  if [[ ! -f "$DST/$d" ]] || ! cmp -s "$SRC/$s" "$DST/$d"; then
    CHANGED+=("$p")
  fi
done

if [[ ${#CHANGED[@]} -eq 0 ]]; then
  echo "✓ 生产与本地一致，无需同步。"
  exit 0
fi

echo "有差异的文件 (${#CHANGED[@]}):"
for p in "${CHANGED[@]}"; do
  s="${p%%::*}"; d="${p##*::}"
  if [[ -f "$DST/$d" ]]; then echo "  [改] $s → $d"; else echo "  [新] $s → $d"; fi
done

# ---------- dry-run ----------
if [[ "$MODE" != "--apply" ]]; then
  echo
  echo "──────── diff（生产 → 本地）────────"
  for p in "${CHANGED[@]}"; do
    s="${p%%::*}"; d="${p##*::}"
    echo "=== $d ==="
    diff -u "$DST/$d" "$SRC/$s" || true
  done
  echo
  echo "以上仅为预览。确认无误后执行： bash deploy.sh --apply"
  exit 0
fi

# ---------- 备份 + 写入 ----------
STAMP="$(date +%Y%m%d-%H%M%S)"
BDIR="$BACKUP_ROOT/$STAMP"
mkdir -p "$BDIR"
echo "→ 备份到 $BDIR"
for p in "${CHANGED[@]}"; do
  d="${p##*::}"
  if [[ -f "$DST/$d" ]]; then
    mkdir -p "$BDIR/$(dirname "$d")"
    cp -p "$DST/$d" "$BDIR/$d"
  fi
done

echo "→ 同步"
for p in "${CHANGED[@]}"; do
  s="${p%%::*}"; d="${p##*::}"
  mkdir -p "$DST/$(dirname "$d")"
  cp -p "$SRC/$s" "$DST/$d"
  echo "  ✓ $d"
done

cat <<MSG

✓ 同步完成。备份: .deploy-backup/$STAMP  （回滚: bash deploy.sh --rollback）

下一步在 NAS 上执行：
  cd /volume2/docker_ssd/prowlarr_cross-seed_autohardlink
  sudo docker compose config --quiet && echo 'YAML OK'
  sudo docker compose up -d --force-recreate cross-seed
  sudo docker compose logs --tail=60 cross-seed
MSG

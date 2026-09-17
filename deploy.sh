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

# ★ 命令行/环境变量必须**优先于** .nasrc —— 2026-09-12 实测踩过：
#   `DST=/tmp/sandbox bash deploy.sh --apply` 原本会被 .nasrc 里的 DST **覆盖掉**，
#   于是"在沙箱里试一下"实际打到了**生产 NAS**（`DST=` 赋值在 source 之后）。
#   想拿临时目录做演练却误伤生产，这个口子必须堵上：先存下外部给的值，source 完再恢复。
#   （`.nasrc` 的定位是**默认值**，不是**强制值**。）
_DST_FROM_ENV="${DST:-}"
# shellcheck source=/dev/null
[[ -f "$SELF_DIR/scripts/.nasrc" ]] && source "$SELF_DIR/scripts/.nasrc"

SRC="${SRC:-$SELF_DIR}"
DST="${_DST_FROM_ENV:-${DST:-}}"
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
  # ★ 2026-09-12 下午补：state.py **必须也进构建上下文**（<compose>/orchestrator/）。
  #   原先白名单只把它同步到 drive-loop/orchestrator/（第 76 行），漏了上面这个 ——
  #   而 Dockerfile 是 `COPY orchestrator/ /app/orchestrator/`（拷整个目录），
  #   于是容器里**没有** orchestrator/state.py。
  #   平时看不出来（main.py 以前不导入它），但 `state` 子命令一加就是
  #   **模块级 ImportError** —— 连默认的 `preflight` 都会一起打挂。
  #   ★ 教训：**"这个文件在哪几个地方需要"要按"谁拷它"分别数**，
  #     同一份代码在 <compose>/ 下有两个不同用途的副本（构建上下文 / drive-loop 运行时），
  #     漏一个不会报错，只会在某条路径上炸。
  "orchestrator/state.py::orchestrator/state.py"
  # 驱动层：2026-09-11 起 drive-loop 跑在 **NAS 上**（DSM 计划任务每 15 分钟），
  # 不再从 Windows 经 SMB 执行。Windows 侧有两个独立的坑（详见 SUMMARY §14）：
  #   ① <StopOnIdleEnd>true —— 一动键鼠就 TerminateProcess 整个批次；
  #   ② drive-loop-once.cmd 曾是 LF 行尾，cmd.exe 解析错位 → exit=9009。
  # 这 6 个文件自成一体地放进 <compose>/drive-loop/，因为它们靠
  # `ROOT = HERE.parent` 定位 hlink/、日志和状态文件 —— 目录结构必须与仓库一致：
  #     drive-loop/scripts/drive-loop.py     → ROOT = drive-loop/
  #     drive-loop/scripts/notify.py
  #     drive-loop/scripts/reseed-state.py
  #     drive-loop/orchestrator/{__init__,state}.py
  #     drive-loop/run.sh                    ← DSM 任务计划实际调的就是它
  # ★ drive-loop/hlink/state.db 是**生产独有**的运行时状态库，和白名单原则第 2 条
  #   一样**动不到** —— 它是从本地 hlink/state.db 一次性迁移过去的（见 SUMMARY）。
  "scripts/drive-loop.py::drive-loop/scripts/drive-loop.py"
  "scripts/notify.py::drive-loop/scripts/notify.py"
  "scripts/reseed-state.py::drive-loop/scripts/reseed-state.py"
  "scripts/drive-loop-nas.sh::drive-loop/run.sh"
  # ★ 2026-09-17（`#58` C 方案）：容器内**常驻**入口。与上面那份是**两条路**，
  #   不是替代关系 —— `run.sh` 带 `--once`（DSM 每 15 分钟唤醒一次，容器外跑），
  #   本文件**不带** `--once`（容器内 `while` 循环，`restart: unless-stopped` 兜底）。
  #   ⇒ 两份都要在，谁也不能顶掉谁（tests/test_drive_loop_service.py ④a 钉 run.sh 仍在、
  #     ⑥a 钉本文件已在）。★ 它由 compose 里 `drive-loop` 服务的 command 调用，
  #     而那个服务带 `profiles: ["drive-loop"]` ⇒ **不会**被 `up -d` 默认拉起来。
  "scripts/drive-loop-resident.sh::drive-loop/run-resident.sh"
  "orchestrator/state.py::drive-loop/orchestrator/state.py"
  "orchestrator/__init__.py::drive-loop/orchestrator/__init__.py"
  # 通知：NAS 侧脚本 + 配置模板（跑在 NAS 宿主机上，不在容器里，但放 compose 目录下）。
  # ★ 只同步 .example 模板 —— 真正的 notify.conf（含收件人邮箱）是生产独有的，
  #   和白名单原则第 2 条一样，**动不到**，需要时在 NAS 上从模板拷一份。
  "scripts/notify-spool.sh::notify/notify-spool.sh"
  "scripts/notify.conf.example::notify/notify.conf.example"
  # 农场清单维护脚本。★ 2026-09-12 才进的这份白名单 —— 在那之前它是**手工拷上去的**
  #   （仓库里在 scripts/，生产在 compose 根目录，两边靠人记得同步）。
  #   代价实测过：09-11 那次改完 --verify 的期望集，生产副本是另外手工放的，
  #   中间有一段时间两边内容不一致，而且手工放的没有备份。
  #   进白名单后：改完 deploy.sh --apply 就同步，且自动进 .deploy-backup/ 可回滚。
  #   路径映射注意：仓库 scripts/build-farm.sh → 生产 **compose 根目录**（不是 scripts/），
  #   因为它要跟 .env 同目录才找得到配置。
  "scripts/build-farm.sh::build-farm.sh"
  # ★ 2026-09-12 晚补：这两个原先**靠手工拷**，是同一族问题的最后两个。
  #   查"git 提交是不是一半 NAS 一半本地"时量出来的 —— 白名单之外的文件
  #   **没有任何机制保证两边一致**（build-farm.sh 就是前车之鉴，见上）。
  #   实测收进来时两边已一致，所以这次是**零风险**地把"靠记性"换成"靠 cmp"。
  #
  #   fix-statedb-farm-root.py —— 仓库里是 scripts/ 下的**已跟踪源码**，
  #     生产副本却放在 compose **根目录**（和数据修复时手边方便有关）。
  #   nas-update-env.sh —— 是**生成物**（scripts/gen-nas-env-update.py 产出，
  #     故在仓库里被 gitignore）。★ 之所以能同步：它只装载 DATA_DIRS + LINK_DIR
  #     两个**路径**键，不含任何凭据；且实测本地 .env 与生产 .env 的 DATA_DIRS
  #     **逐字节相同**（指纹 420afc99339a）。若哪天它开始携带别的键，先回看这里。
  #     本地没生成过这个文件时（如全新 clone），deploy.sh 会打
  #     「⚠ 本地缺失，跳过」并继续 —— 不会因为少了它而中断。
  "scripts/fix-statedb-farm-root.py::fix-statedb-farm-root.py"
  "scripts/nas-update-env.sh::nas-update-env.sh"
  # ★ 2026-09-13 补：删「暂存区」目录 —— 哨兵 `--cleanup` 攒出来的
  #   `_cleanup-YYYYMMDD/`，以及早先误删进回收站的 `#recycle/env-bak-*`。
  #   为什么落成文件、不往 DSM 任务框里粘：
  #     ① 这类目录**会反复出现**（每清一次杂物就攒一个），粘一次只能用一次；
  #     ② 它必须**绕开 File Station** —— File Station 的删除只是挪进 `#recycle`，
  #        文件仍在盘上；而暂存区里最要紧的恰恰是 `.env` 的**明文副本**（带全部凭据）。
  #        2026-09-13 实测 `docker_ssd/#recycle/env-bak-20260912/`
  #        里就躺着 8 个，全是之前几次「File Station 删除」留下的。
  #        ★ 这 8 个里只有 7 个是 `.env.bak.<时间戳>`，第 8 个是裸名 `.env.bak` ——
  #          脚本原先的删除口径 `.env.bak.*` 就漏了它，现已放宽成 `.env*`
  #          （详见 README 该节「窄口已修」）。
  #   放在 compose **根目录**（不是 scripts/），理由同 build-farm.sh —— 和它要
  #   清理的目标在同一层，命令行里路径短、不容易打错。
  #   ★ 它**不进任何计划任务**：只在 DSM 任务计划里手动运行一次，
  #     手动跑 → 用户选 root → 脚本框一句 `sh <路径>/rm-staging.sh <目标> --apply`。
  "scripts/rm-staging.sh::rm-staging.sh"
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
      # ★ 原子替换，同下面的说明 —— 回滚同样可能落在批次运行中。
      cp -p "$f" "$DST/$f.new.$$"
      mv -f "$DST/$f.new.$$" "$DST/$f"
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

# ---------- 批次运行中告警（见 SUMMARY §17.2）----------
# 覆盖一个**正在被 sh 读取**的脚本，会让它从旧偏移读到新文件的字节、执行到错位的代码。
# 实测症状：attempts.log 里冒出一条**假的** exit=127（"no python"，其实 python 好得很），
# 而那批真正的 exit=0 永远不写。改成下面的原子替换后不再有这个问题，
# 但**正在跑的那一批会继续用旧脚本**，所以还是提示一句更稳。
# 判据用**心跳新鲜度**（NAS 侧批次运行期间每 60s 刷一次 .drive-loop.state）。
# 读不到就闭嘴 —— 宁可不提示，也不要误报。
STATE="$DST/drive-loop/scripts/.drive-loop.state"
if [[ -f "$STATE" ]]; then
  HB="$(sed -n 's/.*"heartbeat_ts"[[:space:]]*:[[:space:]]*\([0-9.]*\).*/\1/p' "$STATE" 2>/dev/null | head -1 || true)"
  now_ts="$(date +%s)"
  if [[ -n "${HB:-}" ]] && [[ "$HB" =~ ^[0-9.]+$ ]]; then
    AGE="$(awk -v a="$now_ts" -v b="$HB" 'BEGIN{printf "%d", a-b}')"
    if [[ "${AGE:-99999}" -ge 0 && "${AGE:-99999}" -lt 600 ]]; then
      echo "⚠ NAS 上**有批次正在跑**（心跳 ${AGE}s 前刚刷过）。"
      echo "  本次同步不影响它（原子替换，它继续读旧脚本），但它跑完前你看到的是旧行为。"
      echo "  急着看新行为的话，等心跳停止刷新（~10 分钟）再重新触发一次。"
      echo
    fi
  fi
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

# ★ 必须是「写临时文件 + mv」，**不能**直接 cp 覆盖 —— 见 SUMMARY §17.2。
#   sh 是边读边执行的：直接 cp 会**原地截断重写同一个 inode**，正在运行的那份脚本
#   （例：跑批中的 drive-loop/run.sh）会拿着旧偏移去读新文件 → 执行到错位的代码。
#   实测症状就是 attempts.log 里那条假的 `exit=127 (no python: /usr/bin/python3)`。
#   mv 是同文件系统的 rename()，**换 inode** —— 老进程继续读它自己那份旧的，
#   新进程看到新内容。（python 不受影响：CPython 启动时一次性读完源码。）
#   cp -p 先保住权限位，再 mv 带过去，所以 755 这类可执行位不会丢。
trap 'rm -f "$DST"/*.new.$$ 2>/dev/null || true' EXIT
echo "→ 同步（原子替换）"
for p in "${CHANGED[@]}"; do
  s="${p%%::*}"; d="${p##*::}"
  mkdir -p "$DST/$(dirname "$d")"
  cp -p "$SRC/$s" "$DST/$d.new.$$"
  mv -f "$DST/$d.new.$$" "$DST/$d"
  echo "  ✓ $d"
done
trap - EXIT

cat <<MSG

✓ 同步完成。备份: .deploy-backup/$STAMP  （回滚: bash deploy.sh --rollback）

下一步在 NAS 上执行：
  cd /volume2/docker_ssd/prowlarr_cross-seed_autohardlink
  sudo docker compose config --quiet && echo 'YAML OK'
  sudo docker compose up -d --force-recreate cross-seed
  sudo docker compose logs --tail=60 cross-seed
MSG

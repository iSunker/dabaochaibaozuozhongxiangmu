#!/bin/sh
# =====================================================================
# 通知投递（**NAS 侧**）—— 排空 spool 目录，用 NAS 自己的邮件配置发信
#
# 为什么在 NAS 侧发
# -----------------
# 用户选择不把 SMTP 凭据放到 Windows 上。所以分工是：
#   Windows（notify.py）只往共享目录丢**纯文本事件文件**，零凭据；
#   本脚本在 NAS 上跑，发信**读 DSM 自己的** /etc/ssmtp/ssmtp.conf。
#   也就是说 —— 凭据一直在 DSM 里，本脚本只读不打印，从没离开过 NAS。
#
# ★ 代价（务必知道）：告警链路**依赖 NAS**。NAS 挂了就发不出去，
#   而这恰恰是最该被告知的时刻之一。所以 **每日摘要同时是心跳**：
#   「该来的日报没来」本身就是 NAS / 任务计划故障的信号。
#   摘要里还会写明「最近一次批次是几小时前」，用来区分「NAS 挂了」和「主机没开机」。
#
# 发信怎么发（本脚本自动探测，`--selftest` 可打印探测结果）
# ---------------------------------------------------------
#   ① 有现成的 sendmail/ssmtp/msmtp/mail → 走它（最省事）
#   ② 没有，但有 python3            → 用 smtplib 直接说 SMTP，读同一个
#                                      /etc/ssmtp/ssmtp.conf
#
# ★ 实测（2026-09-11，DSM 7.2 / geminilake_423+）：
#   这台 NAS 上**一个发信程序都没有**，但 /usr/bin/python3 (3.8.15) 在
#   —— 所以走的是 ②。这是探针逼出来的结论，不是猜的。
#
# ★ 前提：DSM 控制面板 → 通知 → 电子邮件 必须已配好
#   （「自定义 SMTP 服务器 + 应用专用密码」；Gmail 的「登录(OAuth)」方式
#     拿不到可用凭据，脚本这条路不通）。
#   ★ 任务计划里**用户要选 root** —— /etc/ssmtp/ssmtp.conf 通常只有 root 能读。
#
# 配置
# ----
#   同目录下的 notify.conf（模板见 notify.conf.example），或同名环境变量：
#     MAIL_TO          收件人（**必需**，否则本脚本只归档不发信）
#     MAIL_FROM        发件人（建议填，有些 SMTP 会校验）
#     SUBJECT_PREFIX   主题前缀，便于邮箱里过滤
#     NOTIFY_ROOT      spool/archive/log 的根目录
#     MAX_MAILS_PER_RUN 单次最多发几封（默认 5，防止一次性喷一屏）
#     MAILER_CMD       手工指定发信程序（一般不用填 —— 自动探测 ssmtp/sendmail/
#                      msmtp/mail，都没有就退到 python3 + smtplib）
#
# 用法
# ----
#   sh notify-spool.sh              # 排空 spool：告警立刻发，其余归档（每 5 分钟跑）
#   sh notify-spool.sh --digest     # 发每日摘要（每天固定时间跑一条）
#   sh notify-spool.sh --test-mail  # 发一封测试信，验证通路
#   sh notify-spool.sh --selftest   # 只打印诊断（不发信）；配合任务计划的
#                                   # 「发送运行详情」把结果寄回来看 —— SSH 关着时
#                                   # **这是我们唯一能看见 NAS 上报错的通道**
#   sh notify-spool.sh --dry-run    # 只打印会做什么，不动任何文件
#
# DSM 任务计划怎么建（两个任务，都用「用户定义的脚本」，用户选 root）
# ------------------------------------------------------------------
#   ① 排空：计划「每 5 分钟」，脚本 sh <路径>/notify-spool.sh
#   ② 摘要：计划「每天 21:00」，脚本 sh <路径>/notify-spool.sh --digest
#   ★ 都勾上「发送运行详情」——平时它就是个免费的诊断通道。
# =====================================================================
set -eu

SELF_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)

# ---------- 配置 ----------
NOTIFY_ROOT="${NOTIFY_ROOT:-/volume2/docker_ssd/prowlarr_cross-seed_autohardlink/notify}"
MAIL_TO="${MAIL_TO:-}"
MAIL_FROM="${MAIL_FROM:-}"
SUBJECT_PREFIX="${SUBJECT_PREFIX:-[reseed]}"
MAX_MAILS_PER_RUN="${MAX_MAILS_PER_RUN:-5}"
#: DSM 自己的邮件配置。脚本只读它，**从不打印其中的值**。
SSMTP_CONF="${SSMTP_CONF:-/etc/ssmtp/ssmtp.conf}"

# notify.conf 用 `KEY=value`，忽略空行与 `#` 注释。★ 它**不含密码**（见上面说明）。
CONF="$SELF_DIR/notify.conf"
if [ -f "$CONF" ]; then
  while IFS= read -r _line; do
    case "$_line" in
      ''|\#*) continue ;;
    esac
    _k=${_line%%=*}; _v=${_line#*=}
    case "$_k" in
      MAIL_TO|MAIL_FROM|SUBJECT_PREFIX|NOTIFY_ROOT|MAX_MAILS_PER_RUN|SSMTP_CONF|MAILER_CMD)
        # 只在环境变量**没给**时才用配置文件的值（env 优先，便于临时覆盖）
        eval "_cur=\${$_k-}"
        [ -n "$_cur" ] || eval "$_k=\$_v"
        ;;
    esac
  done < "$CONF"
fi

SPOOL="$NOTIFY_ROOT/spool"
ARCHIVE="$NOTIFY_ROOT/archive"
LOGDIR="$NOTIFY_ROOT/log"

MODE=drain
DRY=0
while [ $# -gt 0 ]; do
  case "$1" in
    --digest)    MODE=digest ;;
    --test-mail) MODE=test ;;
    --selftest)  MODE=selftest ;;
    --dry-run)   DRY=1 ;;
    -h|--help)   awk 'NR>1 && /^set -eu/{exit} NR>1{print}' "$0"; exit 0 ;;
    *) echo "未知参数: $1  (可用: --digest | --test-mail | --selftest | --dry-run | -h)" >&2; exit 2 ;;
  esac
  shift
done

say()  { echo "$@"; }
warn() { echo "[!] $*" >&2; }

# ---------- 占位符防线 ----------
# ★ notify.conf.example 里的 `MAIL_TO=you@example.com` 是**非空**的。
#   照抄忘改的话，保留闸（下面按"MAIL_TO 是否为空"判断）**不会触发** ——
#   告警被"成功"发往一个不存在的地址，然后归档。结果正是保留闸要防的那种
#   **静默丢告警**：日志显示已发、spool 是空的、而邮箱里什么都没有。
#   所以这里显式把明显的占位符当成"未配置"（宁可留在 spool，也不能假装发出去）。
case "$MAIL_TO" in
  *@example.com|*@example.org|*@example.net|*@example.cn|you@*|your@*|test@*|changeme*)
    warn "MAIL_TO='$MAIL_TO' 看起来还是 notify.conf.example 里的占位符。"
    warn "  → 当成**未配置**处理：告警会留在 spool，不会丢。请改成真实收件人。"
    MAIL_TO=""
    ;;
esac

# ---------- 探测发信方式 ----------
# 按偏好排序：现成的 CLI 程序最省事；没有就退到 python3 + smtplib。
detect_cli_mailer() {
  for c in /usr/sbin/ssmtp /usr/bin/ssmtp /usr/sbin/sendmail /usr/bin/sendmail \
           /usr/sbin/msmtp /usr/bin/msmtp /bin/mail /usr/bin/mail; do
    [ -x "$c" ] && { printf '%s' "$c"; return 0; }
  done
  return 1
}
detect_python() {
  for p in /usr/bin/python3 /usr/local/bin/python3 /usr/bin/python; do
    [ -x "$p" ] && { printf '%s' "$p"; return 0; }
  done
  return 1
}

MAILER=$(detect_cli_mailer || true)
PY=$(detect_python || true)
# 手工覆盖发信程序（可选）：NAS 上发信程序不在默认路径时用得上。
# ★ 也让「发信成功」这条路能在没有 SMTP 的机器上被验证到（见 --selftest 的输出）。
if [ -n "${MAILER_CMD:-}" ]; then
  if [ -x "$MAILER_CMD" ]; then
    MAILER="$MAILER_CMD"
  else
    warn "MAILER_CMD 不可执行，忽略：$MAILER_CMD"
  fi
fi
# 最终用哪条路
if [ -n "$MAILER" ]; then METHOD="cli"; elif [ -n "$PY" ]; then METHOD="python"; else METHOD=""; fi

# ---------- 用 python3 + smtplib 发信 ----------
# 读 DSM 自己的 ssmtp.conf，直接和 SMTP 服务器对话。
# ★ 凭据只在本进程内存里过一遍，**绝不打印、绝不写入任何文件**。
py_send() {
  # $1=主题正文文件由调用方拼好；这里收：$1=subject  $2=body_file
  "$PY" - "$MAIL_TO" "$MAIL_FROM" "$1" "$2" "$SSMTP_CONF" <<'PY'
import sys, ssl, smtplib
from email.message import EmailMessage

try:
    to, frm, subject, bodyfile, conf = sys.argv[1:6]
except ValueError:
    print("参数错误", file=sys.stderr); sys.exit(2)


def load_conf(path):
    """读 ssmtp.conf。值只在内存里用，**不回显**。"""
    cfg = {}
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            cfg[k.strip().lower()] = v.strip()
    return cfg


try:
    cfg = load_conf(conf)
except OSError as e:
    print("读不到 %s: %s（任务计划的用户要选 root）" % (conf, e), file=sys.stderr)
    sys.exit(3)

mailhub = cfg.get("mailhub", "")
if not mailhub:
    print("%s 里没有 mailhub —— DSM 的邮件通知还没配好？" % conf, file=sys.stderr)
    sys.exit(4)

host, port = mailhub, 587
if ":" in mailhub:
    h, _, p = mailhub.rpartition(":")
    try:
        port = int(p); host = h
    except ValueError:
        host = mailhub

user = cfg.get("authuser", "")
pwd = cfg.get("authpass", "")
frm = frm or cfg.get("root") or user
if not frm:
    print("没有发件人：notify.conf 里填 MAIL_FROM，或在 ssmtp.conf 里有 root=",
          file=sys.stderr)
    sys.exit(5)

msg = EmailMessage()
msg["From"] = frm
msg["To"] = to
msg["Subject"] = subject
with open(bodyfile, "r", encoding="utf-8", errors="replace") as fh:
    msg.set_content(fh.read())

ctx = ssl.create_default_context()
try:
    if port == 465:
        with smtplib.SMTP_SSL(host, port, timeout=30, context=ctx) as s:
            if user:
                s.login(user, pwd)
            s.send_message(msg)
    else:
        with smtplib.SMTP(host, port, timeout=30) as s:
            s.ehlo()
            try:
                s.starttls(context=ctx)
                s.ehlo()
            except smtplib.SMTPException:
                pass        # 服务器不支持 STARTTLS 就明文（内网中继常见）
            if user:
                s.login(user, pwd)
            s.send_message(msg)
except smtplib.SMTPAuthenticationError:
    # ★ 只说"认证失败"，不回显用户名/口令
    print("SMTP 认证失败 —— 检查 DSM 里的 SMTP 账号/应用专用密码", file=sys.stderr)
    sys.exit(6)
except Exception as e:  # noqa: BLE001
    print("发信失败: %s: %s" % (type(e).__name__, e), file=sys.stderr)
    sys.exit(7)

print("OK: %s:%s -> %s" % (host, port, to))
PY
}

# ---------- 发一封信 ----------
# send_mail <主题> <正文文件>
send_mail() {
  _subj="$1"; _body="$2"
  [ -n "$METHOD" ] || { warn "没有可用的发信方式（既无 sendmail/ssmtp，也无 python3）"; return 1; }
  [ -n "$MAIL_TO" ] || { warn "MAIL_TO 未配置 —— 只在归档，不发信"; return 1; }

  case "$METHOD" in
    python)
      py_send "$_subj" "$_body"
      ;;
    cli)
      case "$MAILER" in
        */mail)
          "$MAILER" -s "$_subj" "$MAIL_TO" < "$_body"
          ;;
        *)
          # 通用：自己拼信头走 -t。-t 会从 To: 头取收件人。
          {
            printf 'To: %s\n' "$MAIL_TO"
            [ -n "$MAIL_FROM" ] && printf 'From: %s\n' "$MAIL_FROM"
            printf 'Subject: %s\n' "$_subj"
            printf 'MIME-Version: 1.0\n'
            printf 'Content-Type: text/plain; charset=UTF-8\n'
            printf '\n'
            cat "$_body"
          } | "$MAILER" -t
          ;;
      esac
      ;;
  esac
}

# 取事件文件里的一个字段：field_of <文件> <字段名>
field_of() {
  sed -n "s/^$2: //p" "$1" 2>/dev/null | head -1
}

# 正文 = `---` 之后的部分
body_of() {
  sed -n '/^---$/,$p' "$1" 2>/dev/null | sed '1d'
}

# 追加一行到当天的事件流水（摘要靠它）
log_event() {
  _f="$1"
  _d=$(date '+%Y-%m-%d')
  [ "$DRY" = 1 ] && return 0
  mkdir -p "$LOGDIR"
  {
    printf '%s\t' "$(field_of "$_f" ts)"
    printf '%s\t' "$(field_of "$_f" kind)"
    printf '%s\t' "$(field_of "$_f" title)"
    printf '%s\n' "$(field_of "$_f" metrics)"
  } >> "$LOGDIR/$_d.tsv"
}

# 信封抬头：时间 + 主机，附在正文前
with_header() {
  _f="$1"
  printf '时间: %s\n主机: %s\n\n' "$(field_of "$_f" ts)" "$(field_of "$_f" host)"
  body_of "$_f"
}

# ---------- selftest ----------
do_selftest() {
  say "=== reseed-notify 自检 $(date '+%F %T') ==="
  say "身份     : $(id 2>/dev/null || echo '?')"
  say "脚本位置 : $SELF_DIR"
  say "配置文件 : $CONF $( [ -f "$CONF" ] && echo '（存在）' || echo '（不存在 —— 见 notify.conf.example）')"
  say "NOTIFY_ROOT : $NOTIFY_ROOT"
  say "MAIL_TO  : ${MAIL_TO:-<未配置>}"
  say "MAIL_FROM: ${MAIL_FROM:-<空，将退回 ssmtp.conf 的 root=>}"
  say ""
  say "--- 发信方式 ---"
  for c in /usr/sbin/ssmtp /usr/bin/ssmtp /usr/sbin/sendmail /usr/bin/sendmail \
           /usr/sbin/msmtp /usr/bin/msmtp /bin/mail /usr/bin/mail; do
    [ -x "$c" ] && say "  [有] $c"
  done
  [ -n "$MAILER" ] || say "  （上面一个都没有 —— 这台 NAS 没有现成的发信程序）"
  say "  python3 : ${PY:-<找不到>}"
  case "$METHOD" in
    cli)    say "  → 将使用: $MAILER" ;;
    python) say "  → 将使用: $PY + smtplib（读 $SSMTP_CONF）" ;;
    "")     say "  → ✗ 无可用发信方式" ;;
  esac
  [ -n "${MAILER_CMD:-}" ] && say "  （MAILER_CMD 覆盖: $MAILER_CMD）"
  say ""
  say "--- DSM 邮件配置 $SSMTP_CONF ---"
  if [ ! -f "$SSMTP_CONF" ]; then
    say "  [无] 文件不存在 —— DSM 的邮件通知还没配？"
  elif [ ! -r "$SSMTP_CONF" ]; then
    say "  [不可读] 当前 uid=$(id -u) 读不了 ——"
    say "           ★ 去任务计划里把这个任务的「用户」改成 root"
  else
    say "  [可读] 以下只列**键名**，值不会打印："
    sed -n 's/^[[:space:]]*\([A-Za-z_][A-Za-z0-9_]*\)[[:space:]]*=.*/    \1/p' "$SSMTP_CONF"
    _hub=$(sed -n 's/^[[:space:]]*[Mm]ailhub[[:space:]]*=[[:space:]]*//p' "$SSMTP_CONF" | head -1)
    # 只显示 host:port（服务器地址，不是凭据）
    [ -n "$_hub" ] && say "  mailhub = $_hub"
    if grep -qiE '^[[:space:]]*AuthUser[[:space:]]*=' "$SSMTP_CONF"; then
      say "  ✓ 有 AuthUser/AuthPass（说明是「自定义 SMTP + 密码」方式 —— 脚本能直接用）"
    else
      say "  ⚠ 没有 AuthUser —— 可能是 Gmail「登录(OAuth)」方式配的，"
      say "     那样脚本拿不到可用凭据。请改用「自定义 SMTP 服务器 + 应用专用密码」。"
    fi
  fi
  say ""
  say "--- 目录与待办 ---"
  for d in "$NOTIFY_ROOT" "$SPOOL" "$ARCHIVE" "$LOGDIR"; do
    if [ -d "$d" ]; then
      say "  [有] $d"
    else
      say "  [无] $d   ← 跑一次不带 --selftest 的会自建"
    fi
  done
  if [ -d "$SPOOL" ]; then
    say "  待发事件: $(find "$SPOOL" -maxdepth 1 -name '*.txt' 2>/dev/null | wc -l | tr -d ' ') 个"
    say "  .tmp（写了一半，会被忽略）: $(find "$SPOOL" -maxdepth 1 -name '*.tmp' 2>/dev/null | wc -l | tr -d ' ') 个"
  fi
  say ""
  say "--- 结论 ---"
  if [ -z "$METHOD" ]; then
    say "  ✗ 无可用发信方式。"
  elif [ -z "$MAIL_TO" ]; then
    say "  ⚠ 有发信方式，但 MAIL_TO 没配 → 现在只会归档，不发信。"
    say "    去改 $CONF"
  else
    say "  ✓ 看起来可行：$METHOD → $MAIL_TO"
    say "    真正确认请跑： sh $0 --test-mail"
  fi
  say "=== 自检结束 ==="
}

# ---------- 排空 spool ----------
do_drain() {
  [ -d "$SPOOL" ] || { [ "$DRY" = 1 ] || mkdir -p "$SPOOL" "$ARCHIVE" "$LOGDIR"; say "spool 不存在，已建：$SPOOL"; return 0; }
  mkdir -p "$ARCHIVE" "$LOGDIR"

  LIST=$(mktemp); ALERTS=$(mktemp)
  n_alert=0; n_info=0; n_sent=0; n_failed=0

  for f in "$SPOOL"/*.txt; do
    [ -e "$f" ] || continue
    printf '%s\n' "$f" >> "$LIST"
    if [ "$(field_of "$f" kind)" = "alert" ]; then
      n_alert=$((n_alert + 1))
      printf '%s\n' "$f" >> "$ALERTS"
    else
      n_info=$((n_info + 1))
    fi
  done

  # ★ log_event **只在事件真的投递出去（归档）时**才调用。
  #   若在这里无脑先记一遍，发不出去的告警会**每 5 分钟重记一条** ——
  #   一天 576 行，摘要里的「告警 N 条」直接变成垃圾数字。
  #   积压没送出去的情况由摘要单独报（见 do_digest 的「通知链路」）。
  if [ "$n_alert" -gt 0 ] && [ "$DRY" = 0 ] && { [ -z "$METHOD" ] || [ -z "$MAIL_TO" ]; }; then
    # ★ 发不出去时**不归档、不记账** —— 归档=丢弃。
    #   宁可让文件堆在 spool 里等人来修，也不要"看起来处理过了"却没人收到。
    #   只警告**一次**，否则每条告警都会打一行，刷屏。
    warn "发不了信（METHOD='${METHOD:-无}' MAIL_TO='${MAIL_TO:-未配置}'）——"
    warn "  $n_alert 条告警**保留在 spool**，不归档。修好后下轮自动补发。"
    warn "  先跑 --selftest 看缺什么。"
  elif [ "$n_alert" -gt 0 ]; then
    if [ "$DRY" = 1 ]; then
      say "[dry-run] 会发 $n_alert 条告警："
      while IFS= read -r f; do
        [ -n "$f" ] || continue
        say "  - $(field_of "$f" title)"
      done < "$ALERTS"
    elif [ "$n_alert" -le "$MAX_MAILS_PER_RUN" ]; then
      # ★ 用 `< file` 重定向而不是管道：管道会让 while 体跑在**子 shell** 里，
      #   里面的 n_sent / n_failed 改了也传不出来（下面的汇总行就靠它俩）。
      while IFS= read -r f; do
        [ -n "$f" ] || continue
        ti=$(field_of "$f" title)
        tmp=$(mktemp)
        with_header "$f" > "$tmp"
        if send_mail "$SUBJECT_PREFIX 告警：$ti" "$tmp"; then
          say "  [已发] $ti"
          n_sent=$((n_sent + 1))
          log_event "$f"
          mv -f "$f" "$ARCHIVE/$(basename "$f")"
        else
          warn "  [失败] 发信失败，保留在 spool（下轮重试）: $ti"
          n_failed=$((n_failed + 1))
          rm -f "$tmp"
          continue          # 不归档 → 下轮重试
        fi
        rm -f "$tmp"
      done < "$ALERTS"
    else
      tmp=$(mktemp)
      { printf '共 %s 条告警（超过单次上限 %s，合并成一封）。\n\n' "$n_alert" "$MAX_MAILS_PER_RUN"
        while IFS= read -r f; do
          [ -n "$f" ] || continue
          printf '── %s  %s\n' "$(field_of "$f" ts)" "$(field_of "$f" title)"
        done < "$ALERTS"
        printf '\n—— 明细 ——\n'
        while IFS= read -r f; do
          [ -n "$f" ] || continue
          printf '\n### %s\n' "$(field_of "$f" title)"
          with_header "$f"
        done < "$ALERTS"; } > "$tmp"
      if send_mail "$SUBJECT_PREFIX $n_alert 条告警" "$tmp"; then
        say "  [已发] 汇总告警（$n_alert 条）"
        n_sent=$((n_sent + 1))
        while IFS= read -r f; do
          [ -n "$f" ] || continue
          log_event "$f"
          mv -f "$f" "$ARCHIVE/$(basename "$f")"
        done < "$ALERTS"
      else
        warn "  [失败] 汇总发信失败，全部保留在 spool"
        n_failed=$((n_failed + 1))
      fi
      rm -f "$tmp"
    fi
  fi

  # 非告警（batch/info）：不发信，只归档 —— 它们进每日摘要
  while IFS= read -r f; do
    [ -e "$f" ] || continue
    if [ "$(field_of "$f" kind)" != "alert" ]; then
      if [ "$DRY" = 1 ]; then
        say "[dry-run] 会归档（进摘要）: $(field_of "$f" title)"
      else
        log_event "$f"
        mv -f "$f" "$ARCHIVE/$(basename "$f")"
      fi
    fi
  done < "$LIST"

  rm -f "$LIST" "$ALERTS"
  say "排空完成：告警 $n_alert 条（已发 $n_sent / 失败 $n_failed），归档 $n_info 条"
  [ -n "$METHOD" ] || warn "⚠ 无可用发信方式 —— 只归档了，没人会收到通知"
  [ -n "$MAIL_TO" ] || warn "⚠ MAIL_TO 未配置 —— 只归档了，没人会收到通知"
}

# ---------- 每日摘要 ----------
do_digest() {
  [ "$DRY" = 1 ] || mkdir -p "$LOGDIR"
  tmp=$(mktemp)

  {
    printf 'reseed 每日摘要 — %s\n' "$(date '+%Y-%m-%d %H:%M')"
    printf '主机: %s\n\n' "$(hostname 2>/dev/null || echo '?')"

    # 取**最近两个**日志文件（今天 + 昨天），不依赖 date -d
    # （DSM 的 date 未必支持 GNU 的 -d，别拿它做日期运算）
    _files=$(ls -1 "$LOGDIR"/*.tsv 2>/dev/null | sort | tail -2 || true)
    _lines=""
    for f in $_files; do
      [ -f "$f" ] && _lines="$_lines$(cat "$f")
"
    done

    _batches=$(printf '%s\n' "$_lines" | grep -c '	batch	' || true)
    _alerts=$(printf '%s\n' "$_lines" | grep -c '	alert	' || true)
    printf '最近两次运行窗口\n'
    printf '  批次 : %s\n' "${_batches:-0}"
    printf '  告警 : %s\n\n' "${_alerts:-0}"

    printf '批次明细（时间 / 包 / 指标）\n'
    printf '%s\n' "$_lines" | grep '	batch	' | awk -F'\t' '{printf "  %s  %s\n      %s\n", $1,$3,$4}' || true
    [ "${_batches:-0}" = "0" ] && printf '  （无）\n'

    if [ "${_alerts:-0}" != "0" ]; then
      printf '\n告警明细\n'
      printf '%s\n' "$_lines" | grep '	alert	' | awk -F'\t' '{printf "  %s  %s\n", $1,$3}' || true
    fi

    printf '\n── 心跳 ──\n'
    printf '★ 这封信本身就是心跳：**该来而没来 = NAS 或任务计划出事**。\n'
    _last=$(printf '%s\n' "$_lines" | grep '	batch	' | tail -1 | cut -f1 || true)
    if [ -n "$_last" ]; then
      printf '最近一次批次记录: %s\n' "$_last"
    else
      printf '最近没有任何批次记录 —— 主机可能没开机，或 Windows 计划任务停了。\n'
    fi

    # ★ 通知链路自己的健康状况。正常情况下 spool 排空后这里应该是 0。
    #   持续 >0 = 发信链路坏了（没配 METHOD/MAIL_TO，或 SMTP 认证失败）——
    #   这是「**通知系统自己出故障**」的信号，比任何单条告警都更该被看到：
    #   因为在这种情况下，你收不到告警邮件，只能靠**这封摘要**告诉你。
    _backlog=$(find "$SPOOL" -maxdepth 1 -name '*.txt' 2>/dev/null | wc -l | tr -d ' ')
    _backlog=${_backlog:-0}
    printf '\n── 通知链路 ──\n'
    printf '发信方式  : %s\n' "${METHOD:-无}"
    printf 'spool 积压: %s 条告警\n' "$_backlog"
    if [ "$_backlog" != "0" ]; then
      printf '  ⚠ 有告警**发不出去**，一直堆在 spool 里 —— 那些告警你没有收到。\n'
      printf '    跑 sh notify-spool.sh --selftest 看缺什么（多半是 MAIL_TO 没配，\n'
      printf '    或任务计划的用户不是 root —— /etc/ssmtp/ssmtp.conf 读不了）。\n'
    fi
  } > "$tmp"

  if [ "$DRY" = 1 ]; then
    say "[dry-run] 摘要内容："
    cat "$tmp"
  elif send_mail "$SUBJECT_PREFIX 每日摘要 $(date '+%m-%d')" "$tmp"; then
    say "[已发] 每日摘要"
  else
    warn "[失败] 摘要发送失败"
    rm -f "$tmp"; return 1
  fi
  rm -f "$tmp"
}

# ---------- 分发 ----------
case "$MODE" in
  selftest)  do_selftest ;;
  test)
    if [ "$DRY" = 1 ]; then
      say "[dry-run] 会发测试信 → ${MAIL_TO:-<未配置>}"
    else
      tmp=$(mktemp)
      { printf '这是一封测试信，来自 %s\n\n' "$(hostname 2>/dev/null || echo '?')"
        printf '发信方式: %s\n' "${METHOD:-<无>}"
        printf '时间    : %s\n\n' "$(date '+%F %T')"
        printf '收到它 = NAS 侧发信通路已经打通。\n'; } > "$tmp"
      if send_mail "$SUBJECT_PREFIX 测试信 $(date '+%H:%M')" "$tmp"; then
        say "[已发] 测试信，请查收（含垃圾箱）"
      else
        warn "[失败] 测试信发送失败 —— 先跑 --selftest 看探测结果"
        rm -f "$tmp"; exit 1
      fi
      rm -f "$tmp"
    fi ;;
  digest)    do_digest ;;
  drain)     do_drain ;;
esac

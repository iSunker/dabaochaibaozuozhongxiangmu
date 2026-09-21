#!/usr/bin/env bash
# 变异检验：每个变异都该**红**（且是"红"，不是"崩"）。
# ★ 判据（ERR-AI-09 固定动作）：新写的每条闸门，先种一个它该抓的变异，看它红不红。
# ★ 这里同时打印 FAIL 数与"有没有 MAIN_OK"——后者是"崩 vs 红"的区分信号。
# ★★ 计数只数**行首**的 `  FAIL `（`ck()` 打的那个形状）—— 别拿 `grep -c FAIL`，
#    它会把收尾那句「上面**有 FAIL**」的判读**也算进去**（实测：干净时数出 1）。
set -u
cd "$(dirname "$0")/.."

PROBE=scripts/diag/torznab-probe.py
BAK=/tmp/probe-mut.bak
cp "$PROBE" "$BAK"

apply() { python - "$1" <<'PY'
import pathlib, sys
which = sys.argv[1]
p = pathlib.Path("scripts/diag/torznab-probe.py"); s = p.read_text(encoding="utf-8")
M = {
 "A_unknown_allow": (
  '            blocked.append((i, "Prowlarr 状态**读不到** ⇒ ★ 判不出，不放行（读不到 ≠ 没被禁）"))\n            continue',
  '            ok.append(i)\n            continue'),
 "B_timeout_wide": (
  "    except (TimeoutError, socket.timeout) as e:",
  "    except Exception as e:  # 变异B"),
 "C_gate_always_ok": (
  "        cs_map, cs_err = fetch_cs_retry(NAS_CROSSSEED_DB, timeout=8)",
  "        cs_map, cs_err = ({}, None); cs_err = None  # 变异C：第二只时钟恒清"),
 "D_any_hardcoded": (
  "            idx = ok[0]",
  '            idx = "1"  # 变异D：候选里硬编码'),
 "E_timeout_code1": (
  "        return 4",
  "        return 1  # 变异E"),
 "F_gate_not_wired": (
  "cs_map=None if cs_err else cs_map",
  "None"),
 "G_no_second_clock": (
  "cs_map=None if cs_err else cs_map",
  "None"),
 "H_a_unreadable_ok": (
  '            blocked.append((i, "Prowlarr 状态**读不到** ⇒ ★ 判不出，不放行（读不到 ≠ 没被禁）"))\n            continue',
  '            ok.append(i)\n            continue'),
 "I_cs_missing_ok": (
  '                blocked.append((i, "cross-seed 库里**没有这个站的记录** ⇒ ★ 分不清"\n                                   "「从没搜过」还是「没登记」，不放行"))\n                continue',
  '                ok.append(i)\n                continue'),
 "K_select_creds": (
  "'SELECT id, status, retry_after FROM \"indexer\"'",
  "'SELECT id, status, retry_after, url, apikey FROM \"indexer\"'"),
 "L_cs_err_ignored": (
  "        if cs_err:",
  "        if False:  # 变异L"),
}
if which not in M:
    print("SKIP unknown:", which); sys.exit(3)
old, new = M[which]
if s.count(old) == 0:
    print("NOMATCH"); sys.exit(4)
p.write_text(s.replace(old, new), encoding="utf-8")
PY
}

for v in A_unknown_allow B_timeout_wide C_gate_always_ok D_any_hardcoded E_timeout_code1 \
         F_gate_not_wired G_no_second_clock H_a_unreadable_ok I_cs_missing_ok \
         K_select_creds L_cs_err_ignored; do
  printf '%-20s ' "$v"
  if ! apply "$v"; then
    rc=$?
    echo "  (NOMATCH/NOSKIP rc=$rc)"; cp "$BAK" "$PROBE"; continue
  fi
  python tests/test_torznab_probe.py > /tmp/mut.out 2>&1
  rc=$?
  red=$(grep -c 'FAIL' /tmp/mut.out)
  ok=$(grep -c 'MAIN_OK' /tmp/mut.out)
  if [ "$red" -gt 0 ]; then
    printf '红=%-3s %s\n' "$red" "✅"
  elif [ "$ok" -eq 0 ]; then
    printf '红=0    ❌ **崩了**（不是红！—— `ERR-AI-09` 同族）\n'
    grep -m1 '★★★ 本测试' /tmp/mut.out | sed 's/^/         /'
  else
    printf '红=0    ❌ **漏了**（变异没被抓到）\n'
  fi
  cp "$BAK" "$PROBE"
done
cp "$BAK" "$PROBE"
echo "--- 复原后：$(python tests/test_torznab_probe.py 2>&1 | grep -c '^  FAIL ') FAIL（应为 0）---"

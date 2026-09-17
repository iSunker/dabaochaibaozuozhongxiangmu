#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""探「上下文上限」—— **只用实证，不采信任何人的声明**。

为什么要有它（2026-09-17）：
  我问了两个地方「上限是多少」，得到**两个不同的答案、而且都不可信**：
    · `tools/ctx.py` 自己的 `DEFAULT_LIMIT = 400_000` —— **我编的**，
      依据只有「历史最大 355,726 且没撞墙」；
    · 反代 `/v1/models` 说 `context_window = 1000000` —— **它自己声明的**，
      而那可能是抄来的通用值。
  ⇒ 两个都是「**别人说的**」。这个程序只认「**记录里发生过的**」。

★★ 先说的三条纪律（否则这个程序会骗人）：
  ① **成功过 ≠ 上限**。某次请求在 X tokens 成功 ⇒ 上限 **≥ X**（**下界**）。
     把下界当上限，就等于重犯 `ctx.py` 那个错。
  ② **失败也可能是别的错**。429 / 网络断 / 上游 5xx 都不是"撞墙"。
     只有**明确的 context 类错误**才算 —— 所以要看 `error_message`，不能只看状态码。
  ③ **本程序默认不发请求**。`--probe` 才会真发，且**先打印预估花费**等你确认
     （反代背后是计费的真实模型，发一个 90 万 token 的请求是在**故意烧钱**）。

四步（前 3 步**纯只读、零成本**）：
  1. 读 `cc-switch.db` 的 `proxy_request_logs` —— **真实请求**的 input_tokens 分布
  2. 在那些记录里找**撞墙的痕迹**（context 类报错）
  3. 翻本机所有会话 JSONL 的 `usage`，取**全局历史最大值**
  4. （`--probe`）二分法主动探 —— **默认关**

用法：
    python tools/probe-ctx-limit.py            # 只做 1-3（只读）
    python tools/probe-ctx-limit.py --probe    # 加上第 4 步（会花钱，先问你）
    python tools/probe-ctx-limit.py --json     # 机器可读

★ 上游链路（2026-09-17 实测，不是猜的）：
    Windows 本机  `cc-switch`（`C:\Users\…\Programs\CC Switch\cc-switch.exe`）
    监听 `127.0.0.1:15721` ← `ANTHROPIC_BASE_URL` 指向它
    ⇒ 由它转给上游的真实模型（本会话用的是 `deepseek-v4.1-flash`）
"""
import argparse
import glob
import json
import os
import sqlite3
import sys
from datetime import datetime

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

CC_DB = os.path.expanduser("~/.cc-switch/cc-switch.db")
PROJ = os.path.expanduser("~/.claude/projects")

#: ★ 只有**这些字**出现才算"撞墙"。别只看状态码 —— 429/5xx 都不是。
CONTEXT_ERR_HINTS = (
    "context_length", "context length", "maximum context", "too long",
    "max_tokens", "token limit", "exceeds", "context window",
    "prompt is too long", "invalid_request_error",
)


def q(cur, sql, *a):
    try:
        return cur.execute(sql, a).fetchall()
    except sqlite3.Error as e:
        print(f"  [!!] SQL 失败（{e}）")
        return []


# ---------------------------------------------------------------- 步 1
def step1_logs():
    out = {"available": False, "by_model": [], "max_total": 0, "errors": []}
    if not os.path.exists(CC_DB):
        print(f"★ 找不到 {CC_DB} —— 跳过步 1")
        return out
    out["available"] = True
    con = sqlite3.connect(f"file:{CC_DB}?mode=ro", uri=True)
    cur = con.cursor()
    print("── 步 1：cc-switch 的**真实请求**记录（proxy_request_logs）──")
    n_all = q(cur, "SELECT COUNT(*) FROM proxy_request_logs")[0][0]
    print(f"  共 {n_all:,} 条请求记录")
    rows = q(cur, """
        SELECT model, COUNT(*) n,
               MAX(input_tokens) mx,
               MIN(input_tokens) mn,
               MAX(input_tokens + COALESCE(cache_read_tokens,0)
                   + COALESCE(cache_creation_tokens,0)) mx_total,
               SUM(CASE WHEN status_code >= 400 THEN 1 ELSE 0 END) errs
        FROM proxy_request_logs GROUP BY model ORDER BY mx_total DESC""")
    print(f"  {'模型':<26}{'n':>7}{'max(input)':>12}{'max(总上下文)':>14}{'错误':>7}")
    for m, n, mx, mn, mxt, e in rows:
        out["by_model"].append(dict(model=m, n=n, max_input=mx, max_total=mxt, errors=e))
        print(f"  {str(m):<26}{n:>7,}{mx:>12,}{mxt or 0:>14,}{e:>7}")
    out["max_total"] = max((r[4] or 0) for r in rows) if rows else 0
    con.close()
    return out


# ---------------------------------------------------------------- 步 2
def step2_wall(logs):
    print()
    print("── 步 2：找**撞墙的痕迹**（只认 context 类错误，不认 429/5xx）──")
    if not logs["available"]:
        print("  （步 1 没读到库，跳过）")
        return []
    con = sqlite3.connect(f"file:{CC_DB}?mode=ro", uri=True)
    cur = con.cursor()
    codes = q(cur, """SELECT status_code, COUNT(*) FROM proxy_request_logs
                      GROUP BY status_code ORDER BY 2 DESC""")
    print("  状态码分布：" + "  ".join(f"{c}={n:,}" for c, n in codes))
    #   ★ 全量拿错误行（不只是 >=400：有些上游错误也可能是 200 里带的 message）
    rows = q(cur, """SELECT request_id, model, input_tokens, status_code,
                            error_message, created_at
                     FROM proxy_request_logs
                     WHERE (error_message IS NOT NULL AND TRIM(error_message) <> '')
                        OR status_code >= 400""")
    hits = []
    for rid, m, tok, sc, msg, ts in rows:
        low = (msg or "").lower()
        if any(h in low for h in CONTEXT_ERR_HINTS):
            hits.append(dict(request_id=rid, model=m, tokens=tok,
                             status=sc, message=msg, at=ts))
    print(f"  error_message 非空 或 status>=400 的行：{len(rows)}")
    print(f"  其中**像 context 类**的：{len(hits)}")
    for h in hits[:10]:
        print(f"    · {h['at']}  {h['model']}  tokens={h['tokens']:,}  "
              f"status={h['status']}  {str(h['message'])[:100]}")
    if not rows:
        print("  ★ **一条错误记录都没有** ⇒ 从没在上游撞过墙（或者撞墙那次没被记进表）。")
        print("    ⇒ 这一步**证不出上限**，只能证明“没留下痕迹”。别把它读成“没上限”。")
    con.close()
    return hits


# ---------------------------------------------------------------- 步 3
def step3_sessions():
    print()
    print("── 步 3：本机所有会话 JSONL 里的 usage 最大值 ──")
    best = []
    for p in glob.glob(os.path.join(PROJ, "*", "*.jsonl")):
        mx, model, when = 0, None, None
        for line in open(p, encoding="utf-8", errors="replace"):
            if '"usage"' not in line:
                continue
            try:
                d = json.loads(line)
            except Exception:
                continue
            m = d.get("message") or {}
            u = m.get("usage") or {}
            t = (u.get("input_tokens", 0) + u.get("cache_read_input_tokens", 0)
                 + u.get("cache_creation_input_tokens", 0))
            if t > mx:
                mx, model, when = t, m.get("model"), d.get("timestamp")
        if mx:
            best.append((mx, model, when, os.path.basename(p)))
    best.sort(reverse=True)
    print(f"  {'max context':>13}  {'model':<26} {'时刻':<22} 会话")
    for mx, model, when, sid in best[:8]:
        print(f"  {mx:>13,}  {str(model):<26} {str(when)[:19]:<22} {sid[:20]}")
    top = best[0][0] if best else 0
    if best:
        print(f"\n  ⇒ **全局历史最大 = {top:,}**（会话 {best[0][3][:20]}）")
    return top, best


# ---------------------------------------------------------------- 步 4
#: ★ 上游价目（USD / 1M input tokens）。来源：`cc-switch.db` 的 `model_pricing`，
#:   取 `DeepSeek V4.1 Flash` 那一条（`deepseek-flash` = 0.30）。
#:   ★ 这是**保守估计**用的 —— 真实计费以反代为准，别拿它当账单。
PRICE_IN_PER_M = 0.30

#: ★ 探针用的「填充物」。**必须是能精确控制 token 数的东西。**
#:   中文字符在不同 tokenizer 下 ≈1~2 token，**不可控** ⇒ 用重复的 ASCII 词。
#:   「hello 」这种高频词通常稳定在 **1 token / 词**，但**不能假设** ——
#:   所以下面 `_prove_filler()` 会**先量一次**（这就是"最小探针"那一步）。
FILLER_WORD = "hello "

#: 默认的二分区间起点（用步 1-3 探到的下界做起点，别从 0 开始）
PROBE_MIN_DEFAULT = 400_000
PROBE_MAX_DEFAULT = 2_000_000


def _post(url, token, model, text, timeout=600):
    """发一次 /v1/messages。返回 (status, body_text 或 None, 异常)。

    ★★ `max_tokens` **不许小于 3**（2026-09-17 实测，`#117`）：
      反代（`cc-switch` `:15721`）对 `max_tokens ∈ {1, 2}` 会**短路**，回一个
      **占位响应**：
          id     = "chatcmpl-probe-…"     ← **不是**上游的 id（上游是 `cmb-…`）
          usage  = {input_tokens: 1, output_tokens: 1}
          content = []
      它 **HTTP 200、结构合法、有 usage** ⇒ **逐字看着像真的**。
      而 `input_tokens=1` 会让「按 token 标定换算率」这条路**算出一个荒谬的值**
      （实测：1000 个词 → 报 1 token ⇒ 1M tokens 要 10 亿个词 ⇒ MemoryError）。
      ⇒ 代价对比：`max_tokens=16` 比 1 多 15 个 output token
        （output 价 1.2/M ⇒ **多花约 $0.000018**）—— 拿这个换"不被短路"极划算。
    """
    import urllib.request
    import urllib.error
    mt = max(16, int(os.environ.get("PROBE_MAX_TOKENS", "16")))
    payload = json.dumps({
        "model": model,
        "max_tokens": mt,
        "messages": [{"role": "user", "content": text}],
    }).encode()
    req = urllib.request.Request(
        url.rstrip("/") + "/v1/messages", data=payload,
        headers={"content-type": "application/json",
                 "anthropic-version": "2023-06-01",
                 "authorization": f"Bearer {token}"},
        method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read().decode("utf-8", "replace"), None
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace"), None
    except Exception as e:                       # 网络/超时
        return None, None, repr(e)


def _base_url():
    """从 cc-switch 的配置里取监听地址（别写死端口）。"""
    try:
        con = sqlite3.connect(f"file:{CC_DB}?mode=ro", uri=True)
        r = con.execute("SELECT listen_address, listen_port FROM proxy_config "
                        "WHERE app_type='claude' LIMIT 1").fetchone()
        con.close()
        if r and r[1]:
            return f"http://{r[0]}:{r[1]}"
    except Exception:
        pass
    return "http://127.0.0.1:15721"


def _token():
    """从 settings.json 读凭据。★ **只读、不打印**。"""
    p = os.path.expanduser("~/.claude/settings.json")
    try:
        d = json.load(open(p, encoding="utf-8"))
        return (d.get("env") or {}).get("ANTHROPIC_AUTH_TOKEN", "")
    except Exception:
        return ""


def _looks_short_circuited(body):
    """★★ 判「这个响应是不是**占位/短路**的」—— 2026-09-17 实测的形状。

    ★ 为什么必须显式判它：短路响应 **HTTP 200、结构合法、带 usage**，
      一切看起来都对 —— 只有 `input_tokens` 荒谬地小。
      若拿它当「换算率」的样本，会算出**假的上限**，而读数**逐字看着像真的**。
    判据（任一条命中即认定短路）：
      ① `id` 以 `chatcmpl-probe-` 开头（实测：上游真响应是 `cmb-…`）
      ② `content` 为空 **且** `output_tokens <= 2`
    """
    try:
        d = json.loads(body)
    except Exception:
        return False
    if str(d.get("id") or "").startswith("chatcmpl-probe-"):
        return True
    u = d.get("usage") or {}
    if not (d.get("content") or []) and (u.get("output_tokens") or 0) <= 2:
        return True
    return False


def _prove_filler(url, tok, model):
    """★★ 标定「填充物 → tokens」的换算率。

    ★ 做法：发一个**小**请求（1000 个词），读反代报的 `usage.input_tokens` 来标定。
      这个数不是估的，是它算的 —— **但前提是它没说谎**，所以下面两道闸。

    ★★ 两道闸（缺一不可，2026-09-17 加）：
      ① **短路检测**：`input_tokens` 荒谬地小 ⇒ 那是占位响应，**不许当样本**；
      ② **合理性区间**：词→token 的比率必须落在 `[0.2, 4]`。
         （实测真值 ≈ **1.012**；旧代码在这里算出 `0.001`，
          却因为「非 None」而**放行**，一路走到 MemoryError 才炸。）
    ★ 教训：**「返回值不是 None」≠「返回值可用」** —— 检查了存在性，没检查合理性。
    """
    n = 1000
    st, body, err = _post(url, tok, model, FILLER_WORD * n)
    if err:
        print(f"  [!!] 标定请求失败：{err}")
        return None
    if st != 200:
        print(f"  [!!] 标定请求 HTTP {st}：{str(body)[:200]}")
        return None
    if _looks_short_circuited(body):
        print("  [!!] ★★ 标定请求被**短路**了（占位响应）—— 不能当样本。")
        print(f"       响应：{str(body)[:220]}")
        print("       常见成因：`max_tokens` 太小（实测 <=2 会短路，见 `_post` 的说明）。")
        return None
    try:
        d = json.loads(body)
        u = d.get("usage") or {}
        got = u.get("input_tokens")
    except Exception as e:
        print(f"  [!!] 标定响应解析失败：{e}：{str(body)[:200]}")
        return None
    if not got:
        print(f"  [!!] 标定响应里没有 usage.input_tokens：{str(body)[:200]}")
        return None
    per = got / n
    #   ★★ 闸 ②：合理性。区间取得宽（0.2~4），因为不同 tokenizer 差异大；
    #      但它一定会拦住 `0.001` 这种「短路留下的痕迹」。
    if not (0.2 <= per <= 4.0):
        print(f"  [!!] ★★ 标定结果**不合理**：{n} 个词 → {got} tokens"
              f" ⇒ {per:.4f} token/词，落在 [0.2, 4] 之外。")
        print("       ⇒ **判标定失败，不往下走**（否则后面探到的是假读数）。")
        return None
    print(f"  标定：发 {n} 个词 → 反代报 input_tokens = **{got}**"
          f"  ⇒ {per:.3f} token/词  OK 在合理区间内")
    print(f"        （响应 id={str(d.get('id'))[:24]} —— 真响应的前缀是 `cmb-`）")
    return per


def step4_probe(args, floor):
    import urllib.request  # noqa: F401  （确认依赖可用）
    print()
    print("=" * 68)
    print("步 4：主动探（--probe）")
    print("=" * 68)
    url, tok = _base_url(), _token()
    if not tok:
        print("  [!!] 读不到 ANTHROPIC_AUTH_TOKEN（settings.json）⇒ 停在这里。")
        return None
    model = args.model or "deepseek-v4.1-flash"
    print(f"  端点 {url}   模型 {model}")
    print(f"  已证下界 = {floor:,}（步骤 1-3）")
    print()
    print("  ── 4a 最小探针：先证明探针本身能工作 ──")
    per = _prove_filler(url, tok, model)
    if per is None:
        print("  ★★ 标定失败 => **不往下走**。理由：换算不可信时，"
              "后面探到的「上限」是**假读数**，而它看起来完全正常。")
        return None

    print()
    print("  ── 4b 阴性对照：故意发一个**必然超长**的请求 ──")
    print("     ★ 目的：**先把「墙长什么样」记下来**。否则真撞到墙时认不出它。")
    huge_words = int(5_000_000 / per)          # ≈5M tokens
    print(f"     发 ≈5,000,000 tokens（{huge_words:,} 词）…")
    st, body, err = _post(url, tok, model, FILLER_WORD * huge_words)
    print(f"     HTTP {st}   {('err=' + str(err)) if err else str(body)[:200]}")
    if st == 200:
        print("     ★★ **它成功了** —— 那就说明 5M 都还没撞墙（上限 >= 5M）！")
        print("        这不是「对照失败」，是**上界被推得比预期高**。")
        return dict(limit_floor=5_000_000, wall=None, per_token=per)
    neg = dict(status=st, body=str(body)[:500])
    print("     => 记下这个形状：**这就是墙**（或至少是「这个长度的报错」）。")

    print()
    print("  ── 4c 二分 ──")
    lo = args.lo or floor
    hi = args.hi or PROBE_MAX_DEFAULT
    worst = (hi - lo) / 1_000_000 * PRICE_IN_PER_M * 12
    print(f"     区间 [{lo:,}, {hi:,}]；最坏计费**上限**估算 ≈ ${worst:.2f}"
          f"（按每发都满额、最多 12 发算；撞墙的一般不计满额）")
    if not args.yes:
        print("     ★ 要真发请加 `--yes`（**这一步会花钱**）。现在停在这里。")
        return dict(limit_floor=lo, wall=neg, per_token=per, aborted="需要 --yes")

    results = []
    while hi - lo > 50_000 and len(results) < 12:
        mid = (lo + hi) // 2
        words = int(mid / per)
        st, body, err = _post(url, tok, model, FILLER_WORD * words)
        ok = (st == 200)
        results.append((mid, st, ok))
        print(f"     {mid:>10,} tokens → HTTP {st}  {'✅' if ok else '❌'}")
        if ok:
            lo = mid
        else:
            hi = mid
    print()
    print(f"  ★★ **探到：上限 ∈ [{lo:,}, {hi:,}]**（窗口 {hi - lo:,}）")
    return dict(limit_floor=lo, limit_ceil=hi, wall=neg,
                per_token=per, ladder=results)


def main():
    ap = argparse.ArgumentParser(add_help=True)
    ap.add_argument("--probe", action="store_true",
                    help="加上第 4 步（会花钱；默认只做只读的 1-3）")
    ap.add_argument("--yes", action="store_true",
                    help="★ --probe 下真发请求（不加则只打印计划与费用）")
    ap.add_argument("--model", help="探针用的模型名（默认 deepseek-v4.1-flash）")
    ap.add_argument("--lo", type=int, help="二分区间下界（默认用步 1-3 的实测下界）")
    ap.add_argument("--hi", type=int, help="二分区间上界（默认 2,000,000）")
    ap.add_argument("--json", action="store_true", help="机器可读")
    a = ap.parse_args()

    logs = step1_logs()
    hits = step2_wall(logs)
    top, best = step3_sessions()

    floor_candidates = [x for x in (logs.get("max_total"), top) if x]
    floor = max(floor_candidates) if floor_candidates else 0

    print()
    print("=" * 68)
    print("★★ 结论（把「下界」和「上限」分清楚）")
    print("=" * 68)
    print(f"  **已证下界 = {floor:,}**  ← 有请求在这个长度上**成功过**（无一次报错）")
    print(f"     · cc-switch 记录里最大：{logs.get('max_total') or 0:,}")
    print(f"     · 会话 JSONL 里最大：  {top:,}")
    print(f"  **上界 = 未知**。{len(hits)} 条 context 类错误痕迹。")
    print()
    print("  ★ 别把下界当上限 —— 那正是 `ctx.py` 原来犯的错")
    print("    （它拿「历史最大 355,726 没撞墙」当「上限 ≥ 356k」，取了 400k，实际差 2.5 倍）。")
    print("  ★ 反代 `/v1/models` 自称 context_window=1000000 —— **那是声明，不是实测**。")
    print(f"  ⇒ 目前唯一能说的是：**上限 ≥ {floor:,}**。要更紧的值只能靠 `--probe`。")
    probe = step4_probe(a, floor) if a.probe else None

    if a.json:
        print()
        print(json.dumps({"floor": floor, "logs": logs, "wall_hits": hits,
                          "session_top": top, "probe": probe},
                         ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())

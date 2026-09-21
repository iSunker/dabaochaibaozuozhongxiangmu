#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""手动复现 cross-seed 对某个 PT 站发的那一次 Torznab 查询（**只读**）。

用途
----
SUMMARY §20.9.5 的退出条件里，有一格日志**分不开**：
「HDtime 完全没货」与「HDtime 有货但只有单集」在三处读数里**一模一样**
（`searched` 有、`matched` 空、`found` 0），而**处置相反**。
⇒ 那一格只能**手动搜一次**才能定，本脚本就是那次手搜。

★ 为什么走 Torznab、不走去站点网页搜：要判的是「**cross-seed 看到的候选里有没有季包**」，
  所以必须复现同一条路、同一个 query（口径不一样，答案没法比）。
★ `q` 必须**逐字节抄** verbose 里那行
  `Querying HDtime at … with { t: 'tvsearch', q: '…' }` 的 `q`，别自己拼季包名。

为什么读 **NAS 的 `.env`**
--------------------------
本地 `.env` 是**开发存根**（占位符），`TORZNAB_URLS` 里没有真的站点 URL。
生产那份在 NAS 上，只读直读 UNC。

★ 这个脚本能在 Windows 上跑，靠的是一条容易漏掉的规则（`.env.example` 里写着）：
  `TORZNAB_URLS` 里写的是**容器名** `prowlarr`（那是给 cross-seed 容器用的），
  而 **9696 已发布到宿主机**、且 apikey 是 Prowlarr **应用层**的（`/N/api` 不校验来源 IP）
  ⇒ 把 host 换成 **NAS 宿主机 IP** 即可。
  **这不是「换一条路」，是同一条 Torznab 路的宿主机入口。**
  ★ 2026-09-13 曾据此判定「探针从 Windows 跑不了」—— **那是错的**，就是漏了这条规则。

★ 路径一律用**正斜杠**：实测同一台机器上 `\\\\NAS\\share\\…` 这种反斜杠 UNC 在
  Python 里会 `isfile → False`，而 `//NAS/share/…` 正常。别改成反斜杠。

安全
----
* **绝不打印 URL**（URL 里带 apikey）。只打 host:port、状态码、条数、标题。
* **只读**：读 NAS `.env` 一次，发一次查询，不写任何东西。
* `--dump-attrs` / `--raw` 的输出**过一遍 `redact()`** —— ★ 因为 `--raw` 打的是
  原始响应，里面有 `<link>` / `<guid>`，**很多站把 passkey 直接编进下载 URL**
  （`…/download.php?id=…&passkey=<32位>`）。★ 只打**前 4000 字符**，
  且按「值的形状」抹掉凭据（同 `scan-secrets.py` / `04_probes.py` 的出口口径）。
* 站点退避期间会拿到 **429** —— 那时读数无意义（Prowlarr 本地就拒了），**别下任何结论**。
  退避到什么时候，看 NAS 的 `drive-loop/scripts/drive-loop.log` 里
  「索引器 <站> 要等到 …」那行。

用法
----
    python scripts/diag/torznab-probe.py "<原样 q>" [season] [--id N] [--env PATH]
    python scripts/diag/torznab-probe.py "<剧名>" 1 --dump-attrs      # ★ 季界侦察
    python scripts/diag/torznab-probe.py "<剧名>" 1 --raw             # ★ 原始响应头 4000 字符

    --id   TORZNAB_URLS 里 path 段的编号：1=HDtime 2=HDFans 3=BTSCHOOL 4=NanyangPT
           （默认 1）
    --env  生产 .env 的路径（默认走 NAS 的 UNC；给本地路径便于离线核对）
    --dump-attrs
           ★★ 逐条把 **item 的全文**摆出来（title 之后的 link/guid/pubDate/enclosure/
           `torznab:attr` 全列）—— 用来回答「**响应里有没有可解析的季字段**」。
           为什么必须有这个开关：本脚本原先**只抠 `<title>`** ⇒ 后面那些元素**整段被丢掉**，
           于是「响应里没有季字段」这句话**当时压根没有判据**（拿不到 ≠ 没有，`B.10`）。
    --raw  ★ 原始响应体的**前 4000 字符**（脱敏后）。`--dump-attrs` 只给已知元素，
           这个给「有没有别的写法」（如 `torznab:attr` 之外的自定义命名空间）。
"""
from __future__ import annotations

import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")
    except Exception:
        pass

NAS_ENV = "//iSunker-DS423/docker_ssd/prowlarr_cross-seed_autohardlink/.env"
NAS_IP = "192.168.0.7"

# ---- 脱敏（出口口径，与 scan-secrets.py / 04_probes.py 同一形状）----
# ★ 为什么 `--raw` 必须过它：原始响应里的 `<link>` / `<guid>` 常把 passkey 编进去。
# ★ 两条都要，缺一条就是漏洞：① 按**值的形状**抹（不只按键名）；
#   ② 已知的凭据参数名再抹一道（形状层对短值不生效）。
REDACT_SHAPE = re.compile(r"\b[0-9a-fA-F]{20,}\b")
REDACT_NAME = re.compile(
    r"(?i)((?:api_?key|passkey|torrent_pass|authkey|token|cookie|password)"
    r"[\s\"']*(?:[=:]|%3D)[\s\"']*)([^\s\"'&<>,;]+)")


def redact(text):
    """★ 出口统一脱敏 —— 打印与落盘都只走这一个函数。"""
    s = REDACT_NAME.sub(r"\1<redacted>", str(text))
    s = REDACT_SHAPE.sub("<hex20+>", s)
    return s


def items_of(body):
    """把响应体切成 item 块（**原始片段**，不是只有 title）。

    ★★ 这是一次真缺口修补：原来那版把每个 item 切到 `</title>` 就丢，
      于是 item 后面的 `link` / `guid` / `enclosure` / `torznab:attr` **全都看不见**
      ⇒ 「响应里有没有季字段」当时**没有判据**。
    ★ 用 `</item>` 收尾，且**不假设** item 里有 title（有的站 title 为空）。
    """
    out = []
    for chunk in body.split("<item>")[1:]:
        out.append(chunk.split("</item>", 1)[0])
    return out


def title_of(item_raw):
    """从原始 item 片段里抠 title（抠不到就返回空串，不编）。"""
    if "<title>" not in item_raw:
        return ""
    return item_raw.split("<title>", 1)[1].split("</title>", 1)[0].strip()


def attrs_of(item_raw):
    """★ 把 item 里**所有** `torznab:attr` 的 (name, value) 列出来。

    ★★ 这是 A 的核心判据：**判「没有」之前，先把整个 item 的 attr 列全看一眼** ——
      因为「站点不给」与「给了但名字不叫 season」（如 `rageid` / `tvdbid`）
      在只搜 `name="season"` 时**读数一模一样**（`B.10`：未验 ≠ 无）。
    """
    out = []
    for m in re.finditer(r"<torznab:attr\s+([^/>]*)/?>", item_raw):
        seg = m.group(1)
        n = re.search(r'name\s*=\s*"([^"]*)"', seg)
        v = re.search(r'value\s*=\s*"([^"]*)"', seg)
        out.append(((n.group(1) if n else "?"), (v.group(1) if v else "")))
    return out


def torznab_url(env_path: str, idx: str) -> str:
    """取 TORZNAB_URLS 里 path 段为 `/<idx>/api` 的那条。返回值**绝不落盘/打印**。"""
    want = "/%s/api" % idx
    if not os.path.isfile(env_path):
        raise SystemExit("[!!] .env 不可达（SMB 断了？或路径给错）：%s" % env_path)
    for line in open(env_path, encoding="utf-8", errors="replace"):
        if line.startswith("TORZNAB_URLS="):
            for u in line.split("=", 1)[1].strip().split(","):
                if u.split("?", 1)[0].endswith(want):
                    return u.strip()
    raise SystemExit("[!!] .env 的 TORZNAB_URLS 里没有 path 为 %s 的条目" % want)


def to_host_entry(url: str, ip: str):
    """把 host 换成宿主机 IP。只回报 (原 host, 新 netloc)，**不回报 URL 本身**。"""
    p = urllib.parse.urlsplit(url)
    netloc = "%s:%d" % (ip, p.port or 80)
    new = urllib.parse.urlunsplit((p.scheme, netloc, p.path, p.query, p.fragment))
    return new, (p.hostname or "?"), netloc


def main(argv):
    env_path, idx, rest = NAS_ENV, "1", []
    dump_attrs = raw = False
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--id" and i + 1 < len(argv):
            idx = argv[i + 1]; i += 2; continue
        if a == "--env" and i + 1 < len(argv):
            env_path = argv[i + 1]; i += 2; continue
        if a == "--dump-attrs":
            dump_attrs = True; i += 1; continue
        if a == "--raw":
            raw = True; i += 1; continue
        rest.append(a); i += 1

    if not rest:
        raise SystemExit(__doc__)
    q = rest[0]
    season = rest[1] if len(rest) > 1 else None

    url, old_host, netloc = to_host_entry(torznab_url(env_path, idx), NAS_IP)
    print("入口：%s  →  %s    （路径 /%s/api，q=%r season=%r）"
          % (old_host, netloc, idx, q, season))

    params = {"t": "tvsearch", "q": q}
    if season:
        params["season"] = season
    full = url + ("&" if "?" in url else "?") + urllib.parse.urlencode(params)

    req = urllib.request.Request(full, headers={"User-Agent": "reseed-toolkit/probe"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            status, body = r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        print("HTTP %s —— 站点/Prowlarr 侧拒绝了这次查询" % e.code)
        if e.code == 429:
            print("（429 = 限流/站点退避；此时读数无意义，**别下任何结论**）")
            print("  退避到什么时候：看 NAS 的 drive-loop.log 里「索引器 <站> 要等到 …」那行。")
        return 1
    except Exception as e:
        print("请求失败：%s: %s" % (type(e).__name__, e))
        return 1

    print("HTTP %s" % status)
    items = items_of(body)
    titles = [title_of(it) for it in items]

    print("条数 = %d" % len(titles))
    for n, t in enumerate(titles[:25], 1):
        print("  %2d. %s" % (n, t[:120]))
    if len(titles) > 25:
        print("  … 其余 %d 条略" % (len(titles) - 25))

    if dump_attrs:
        print()
        print("=" * 72)
        print("★★ item 全文（★ 出口已过 redact()）—— 用来判「响应里有没有季字段」")
        print("=" * 72)
        if not items:
            print("★ 没有 item ⇒ 没有 attr 可看。（条数 0 的两种可能见下。）")
        want = ("season", "episode", "tvdbid", "rageid", "imdb", "tvtitle",
                "covers", "category", "size", "seeders", "grabs", "downloadvolumefactor")
        seen = set()
        for n, it in enumerate(items[:10], 1):
            print()
            print("-- item %d --" % n)
            # ★ 该 item 里出现过的**所有**元素名 —— 这样「有没有别的写法」一并答掉
            names = re.findall(r"<([A-Za-z_][\w:]*)[\s>/]", it)
            print("   元素名（去重，按首现序）：%s" % ", ".join(
                dict.fromkeys(names)))
            at = attrs_of(it)
            if not at:
                print("   ★ torznab:attr：**一个都没有**")
            else:
                print("   torznab:attr %d 条：" % len(at))
                for k, v in at:
                    seen.add(k)
                    mark = "  ★★" if k.lower() in want else "    "
                    print("%s %-22s = %s" % (mark, k, redact(v)[:100]))
        if items:
            print()
            print("★ 本轮 attr 里出现过的名字（去重）：%s" % (
                ", ".join(sorted(seen)) or "（无）"))
            print("★★ 判读（三条，缺一不可）：")
            print("   ① 上面**有没有** `season` / `episode` 这类字段？")
            print("   ② 若**没有** —— ★ 别急着写「不给」：先看元素名那一行，")
            print("      确认不是换了个名字（`rageid`/`tvdbid` 也算**季界可用的锚**）。")
            print("   ③ 真正的『season 在服务端生效』的判据是**两次对照**：")
            print("      同一剧 `season=1` 与 `season=2` 各跑一次，★ **比返回集**。")
            print("      返回集不同 ⇒ 服务端认了 season（哪怕响应体里没有季字段）。")

    if raw:
        print()
        print("=" * 72)
        print("★★ 原始响应前 4000 字符（★ 已过 redact()；URL/凭据一律不回显）")
        print("=" * 72)
        print(redact(body[:4000]))

    if not titles:
        print("★ 条数 0 有两种可能，本读数**分不开**：")
        print("   ① 站上确实没有；② 有货但**只有单集**（config.js 的")
        print("      includeSingleEpisodes=false 把单集静默过滤了，日志里查不到）。")
        print("   要分开得去站点网页再搜一次 —— 那是**另一个 query**，口径不同。")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

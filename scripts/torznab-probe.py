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
* 站点退避期间会拿到 **429** —— 那时读数无意义（Prowlarr 本地就拒了），**别下任何结论**。
  退避到什么时候，看 NAS 的 `drive-loop/scripts/drive-loop.log` 里
  「索引器 <站> 要等到 …」那行。

用法
----
    python scripts/torznab-probe.py "<原样 q>" [season] [--id N] [--env PATH]

    --id   TORZNAB_URLS 里 path 段的编号：1=HDtime 2=HDFans 3=BTSCHOOL 4=NanyangPT
           （默认 1）
    --env  生产 .env 的路径（默认走 NAS 的 UNC；给本地路径便于离线核对）
"""
from __future__ import annotations

import os
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
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--id" and i + 1 < len(argv):
            idx = argv[i + 1]; i += 2; continue
        if a == "--env" and i + 1 < len(argv):
            env_path = argv[i + 1]; i += 2; continue
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
    titles = []
    for chunk in body.split("<item>")[1:]:
        seg = chunk.split("</title>", 1)[0]
        titles.append(seg.split("<title>", 1)[-1].strip())

    print("条数 = %d" % len(titles))
    for n, t in enumerate(titles[:25], 1):
        print("  %2d. %s" % (n, t[:120]))
    if len(titles) > 25:
        print("  … 其余 %d 条略" % (len(titles) - 25))

    if not titles:
        print("★ 条数 0 有两种可能，本读数**分不开**：")
        print("   ① 站上确实没有；② 有货但**只有单集**（config.js 的")
        print("      includeSingleEpisodes=false 把单集静默过滤了，日志里查不到）。")
        print("   要分开得去站点网页再搜一次 —— 那是**另一个 query**，口径不同。")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

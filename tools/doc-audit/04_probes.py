#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""只读探针：把文档声称的事实，从生产上真读一遍。

★★ 安全（改自原稿，原稿有泄露）：
   原稿 `SELECT id, url, name, status FROM indexer` 并**把结果整行打印** ——
   `cross-seed.db` 的 `indexer.url` 列里每条都带 `apikey=<Prowlarr 应用级 key>`，
   那个 key 能开 Prowlarr 上的所有 PT 站。本稿：
     ① 不选 `url` 列（判「有哪些站、状态如何」根本不需要那个值）；
     ② 所有输出过一遍 `redact()` —— 按**值的形状**兜底，不只按键名；
     ③ 落地到 out/probes.tsv 的也同样是脱敏后的文本。

用法：python 04_probes.py
输出：<脚本目录>/out/probes.tsv
"""
import re
import shutil
import sqlite3
import sys
import threading
import time
import urllib.request
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

TOOLS = Path(__file__).resolve().parent
OUT = TOOLS / "out"

NAS = "//iSunker-DS423"
COMPOSE_UNC = "%s/docker_ssd/prowlarr_cross-seed_autohardlink" % NAS

# ---- 脱敏纪律（**两条都必须有，缺一条就是漏洞**）----
#   ① **不选可能含凭据的列**。判「哪个站、什么状态」靠 id / name / status 就够，
#      `url` 对判读零价值，而它每条都带 `apikey=<Prowlarr 应用级 key>`。
#      —— 能不取就不取，这是第一道，也是最有效的一道。
#   ② **出口统一过 redact()**。万一某个探针**必须**碰这类列（或异常信息里带出来），
#      在打印和落盘之前把它按**值的形状**抹掉。这是兜底，不是主防线。
#   判据是「只读 + 不回显凭据 + 只打聚合」，与 check-deploy-drift.py 里
#   qb-census / linkguard 那两条是同一个形状。
REDACT = re.compile(r"(apikey=)[^,&]+")
# 再按**值长什么样**兜一层（不只按键名叫什么）—— 键名匹配会漏掉嵌套在
# options / fields / 异常信息里的凭据。
REDACT_MORE = [
    (re.compile(r"(?i)(passkey|password|passwd|token|cookie)(\s*[=:]\s*)([^\s,;&\"']+)"),
     r"\1\2<redacted>"),
    (re.compile(r"\b[0-9a-fA-F]{32,64}\b"), "<hex32+>"),
    (re.compile(r"(?i)Bearer\s+\S+"), "Bearer <redacted>"),
]


def redact(text):
    s = REDACT.sub(r"\1<redacted>", str(text))
    for rx, rep in REDACT_MORE:
        s = rx.sub(rep, s)
    return s


# ---- 探针 ----
def qb_version():
    with urllib.request.urlopen("http://192.168.0.7:3060/api/v2/app/version", timeout=5) as r:
        return r.read().decode().strip()


def _ro(db):
    """只读打开生产库。

    ★ 踩过的坑：不能写 `sqlite3.connect("file:%s?mode=ro" % unc, uri=True)` ——
      UNC 的 `//iSunker-DS423` 会被当成 URI 的 authority，
      报 `invalid uri authority: iSunker-DS423`。要么 `file://` + 路径（多两个斜杠），
      要么退回「普通连接 + `PRAGMA query_only=1`」（**原始方案**）。
      两条路都真只读；URI 那条更硬（连接层就拒绝写 / 不走 WAL 恢复）。
    """
    p = db.replace("\\", "/")
    try:
        con = sqlite3.connect("file://" + p + "?mode=ro", uri=True, timeout=5)
    except sqlite3.OperationalError:
        con = sqlite3.connect(p, timeout=5)
    con.execute("PRAGMA query_only=1")
    return con


def active_indexers():
    """等价于 docker inspect 的 TORZNAB_URLS（Windows 侧读不到容器）。

    ★ 不选 `url` 列 —— 它每条都带 apikey，对判读零价值（见文件头「脱敏纪律 ①」）。
    ★ 同时读 `retry_after`：`status` 是**残留标签**，限流窗口过去后不会被擦掉，
      只看它会把「曾经被限流」误判成「现在还在被限流」（SUMMARY §18.11.2）。
      真判据是 `retry_after` 有没有到点。
    """
    now_ms = int(time.time() * 1000)
    con = _ro(COMPOSE_UNC + "/cross-seed/cross-seed.db")
    try:
        rows = con.execute(
            "SELECT id, name, status, retry_after FROM indexer ORDER BY id").fetchall()
    finally:
        con.close()
    out = []
    for i, name, status, retry in rows:
        if retry and retry > now_ms:
            out.append((i, name, status, "退避中，剩 %d 分钟" % ((retry - now_ms) // 60000)))
        elif retry:
            out.append((i, name, status, "限流窗口已过"))
        else:
            out.append((i, name, status, "—"))
    return out


def stages():
    con = _ro(COMPOSE_UNC + "/drive-loop/hlink/state.db")
    try:
        return dict(con.execute("SELECT stage, COUNT(*) FROM movie GROUP BY stage").fetchall())
    finally:
        con.close()


def indexer_timestamps():
    """各索引器真的搜出去过几行 —— 判「闸门开了没」。"""
    con = _ro(COMPOSE_UNC + "/cross-seed/cross-seed.db")
    try:
        return con.execute(
            "SELECT i.name, COUNT(t.searchee_id) FROM indexer i "
            "LEFT JOIN timestamp t ON t.indexer_id = i.id GROUP BY i.id ORDER BY i.id"
        ).fetchall()
    finally:
        con.close()


def volume_usage():
    """磁盘水位 —— 三份文档里 /volume1 可用空间记了三个不同的值，这条是判据。
    只碰已知共享名；不存在的共享会抛错，由上层记下。"""
    out = {}
    for label, unc in (("/volume2 (docker_ssd)", NAS + "/docker_ssd"),
                       ("/volume1 (video)", NAS + "/video")):
        try:
            u = shutil.disk_usage(unc)
            out[label] = "总 %.2f TiB / 已用 %.2f TiB / 可用 %.2f GiB" % (
                u.total / 2**40, u.used / 2**40, u.free / 2**30)
        except Exception as e:
            out[label] = "%s: %s" % (type(e).__name__, redact(e))
    return out


def _timed(fn, secs=20):
    box = {}

    def run():
        try:
            box["v"] = fn()
        except Exception as e:                     # noqa: BLE001
            box["e"] = "%s: %s" % (type(e).__name__, e)

    t = threading.Thread(target=run, daemon=True)
    t.start()
    t.join(secs)
    if t.is_alive():
        return None, "TIMEOUT after %ds（SMB 可能卡住，别重试太多次）" % secs
    if "e" in box:
        return None, box["e"]
    return box.get("v"), None


PROBES = [
    ("qB :3060 版本", qb_version),
    ("active 索引器（id/name/status/retry_after，无 url）", active_indexers),
    ("状态机 stage 分布", stages),
    ("索引器时间戳", indexer_timestamps),
    ("卷水位", volume_usage),
]


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    lines = ["probe\tactual\terror"]
    for name, fn in PROBES:
        v, err = _timed(fn)
        if err:
            print("[!!] %s: %s" % (name, redact(err)))
            lines.append("%s\t\t%s" % (name, redact(err)))
        else:
            print("[ok] %s: %s" % (name, redact(v)))
            lines.append("%s\t%s\t" % (name, redact(v).replace("\n", " ")))
    (OUT / "probes.tsv").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n→ %s" % (OUT / "probes.tsv"))


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""只读 Storage Analyzer（存储空间分析器）的报告：**里面有没有「可对照的可用空间」**。

它在回答什么
------------
原打算做「两条独立来源互校」：**我们的探针**（读 `statvfs` / `df`，每批）vs
**群晖自己的周期报告**（Storage Analyzer，每周）。对不上 ⇒ 有一方读数错了，
而我们**一直不知道**（同 `§16.1` 的 A/B 来源互校、`§18.11.1` 的 `timestamp` 表同一形状）。

**2026-09-14 的结论是否定的**：报告里**没有可用空间**这一列 ——
`volume_usage.csv` 只有 `Volume / Size / Used / Days to Full`，`Used` 是**百分数**
且只到 **0.1%**。落在 61.4 TB 的 Volume 1 上：**一格 = 61 GB**、
舍入意味着 **±30 GB** ⇒ 原打算的「差 < 1 GiB 算互校通过」**比不出来**。
（要算只能反推：`Size × (1 − Used)` —— 而那个不确定度就是上面这个数。）
所以这一步卡在「换对照量还是换报告」，**等拍**，没往下做。

★ 报告节奏实测：**每周一次，周三 04:07:02**（不是每天）。

用法
----
    python scripts/sa-volume-usage.py            # 最新那份报告的三个 csv 各打前 12 行 + 最近 6 份的周节奏
    python scripts/sa-volume-usage.py --all      # 多打几行（看全每一列）

★ 只读：zip 在**内存里**解（`io` + `zipfile`），**不落盘、不写任何文件**；
  它读的是**群晖的报告目录**，不是 web 路径（web 路径 `/dar/...` 不是磁盘路径 —— 别按它猜）。
"""

from __future__ import annotations

import argparse
import datetime as dt
import io
import pathlib
import sys
import zipfile

try:  # GBK 控制台下不 reconfigure 会在中途炸掉
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

#: 群晖 Storage Analyzer 的报告目录（Windows 侧走 SMB；**不是** web 路径）。
DEFAULT_DIR = pathlib.Path(r"//iSunker-DS423/home/存储空间分析器/synoreport/StorageAnalysisReport")

#: 报告里带的三个 csv（zip 包内名字，可能带前缀、大小写不一）。
NAMES = ["volume_usage.csv", "share_list.csv", "quota_usage.share.csv"]


def _decode(raw: bytes) -> str:
    """★ 群晖这几个 csv 是 **UTF-16**（带 BOM），不是 UTF-8 —— 按 UTF-8 解会得到
    `V o l u m e` 这种**每字符夹空格**的乱码（看着"能读"，其实**列名全废**）。
    先看 BOM 再解；没有 BOM 才退回 UTF-8。"""
    if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return raw.decode("utf-16")
    return raw.decode("utf-8-sig", "replace")


def read_csv_zip(d: pathlib.Path, name: str) -> str:
    """在 zip 里找 `name`（大小写不敏感、可能带前缀）—— **内存**解压，不落盘。"""
    with zipfile.ZipFile(io.BytesIO((d / "csv" / (name[:-4] + ".csv.zip")).read_bytes())) as z:
        for info in z.infolist():
            if pathlib.Path(info.filename).name.lower() == name.lower():
                return _decode(z.read(info))
    return ""


def main() -> int:
    ap = argparse.ArgumentParser(description="只读 Storage Analyzer 报告（找有没有可对照的可用空间）")
    ap.add_argument("--dir", default=str(DEFAULT_DIR), help="报告根目录；默认群晖那份")
    ap.add_argument("--all", action="store_true", help="每个 csv 打全部行（默认只打前 12 行）")
    args = ap.parse_args()

    root = pathlib.Path(args.dir)
    if not root.is_dir():
        raise SystemExit("[!!] 报告目录读不到：%s" % root)

    dirs = sorted(p.name for p in root.iterdir() if p.is_dir())
    if not dirs:
        raise SystemExit("[!!] 报告目录下没有任何报告子目录")
    latest = dirs[-1]
    print("最新报告：%s\n" % latest)

    for nm in NAMES:
        try:
            txt = read_csv_zip(root / latest, nm)
        except Exception as e:  # noqa: BLE001 —— 少一份 csv 不带走整趟
            print("--- %s：读不了 %r" % (nm, e))
            continue
        print("--- %s ---" % nm)
        lines = txt.splitlines()
        for ln in (lines if args.all else lines[:12]):
            print("   " + ln[:160])
        print()

    print("=== 最近 6 份报告的时间戳（看周节奏，决定「保留几份 / 找不到本周的怎么办」）===")
    for s in dirs[-6:]:
        try:
            d = dt.datetime.strptime(s.split("_")[0], "%Y-%m-%d")
            print("   %s   %s" % (s, "周" + "一二三四五六日"[d.weekday()]))
        except Exception:  # noqa: BLE001
            print("   %s" % s)

    print("\n★ 找什么：`volume_usage` 里有没有 `/volume1` `/volume2` 的**可用空间**（能跟我们探针对照的那个数）。"
          "\n   2026-09-14 的读数：**没有** —— 只有 `Size` 与 `Used(%)`。反推 `Size × (1 − Used)` 的话，"
          "\n   Volume 1 上 0.1% 一格 = **61 GB**、舍入 ±30 GB ⇒ 比不过「差 < 1 GiB」那条判据。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""check-datadirs-names —— **只读**校验 `DATA_DIRS` 里没有"分类目录名"。

为什么需要它（`summary/26` §26.63 那件事的一般化）
--------------------------------------------------
`cross-seed` 把 `dataDirs` 的**直接子目录**当作 searchee，并**拿子目录名**去站点搜索
（`cross-seed/config.js:92` 注释原文：「其『子目录』被当作 searchee」）。

而 `DATA_DIRS` 是**逐条手写在 `.env` 里**的（`.env:22`）。生成片段的工具是
`scripts/diag/gen-datadirs.py`，它按 `--level N` **递归取第 N 层的所有子目录**
（`dirs_at_level()`）—— ★ **它只跳 `.` 开头和 `@eaDir`，不认"分类目录"**
⇒ 一旦 `--level` 给错（或人手工粘），**中间那层中文分类目录会被当成发布名**。

那就是实测过的坑（`§26.58` 三 / `§10.2`）：`TV/` 里混着 `儿童` / `欧美剧`
两个**空分类目录**。它们**不是发布名**，拿它们去搜:
  - **搜不到任何东西**（浪费查询额度），而且
  - ★★ **静默失败** —— 日志一切正常，只是那个"包"永远不被搜（`§19.1`）。

⇒ 本脚本就是 `①′` 要的那道**名字挡板**：把「**哪些名字是分类目录、不许进
`DATA_DIRS`**」写成一份**带理由的手写清单**，然后逐条校验。

★★ 为什么这必须是**代码**、不能只是文档里的一句话
--------------------------------------------------
写进文档 = **恒绿**（没人会去读）。写进代码 + 门禁 = **能被变异打红**
（`ERR-AI-09`）。本仓的 `check-deploy-drift.py` 已经把「两份手写清单」这个
形状踩过一遍了（`§26.60` 三：「**常红的闸门 = 没有闸门**」），这里是同一族。

★★ 清单在 `datadirs_rules.py`（**唯一出处**，`§26.64` 起）
------------------------------------------------------------
生成侧 `gen-datadirs.py` 和本脚本 `import` **同一份**清单 ⇒ **没有第二份可漂**
（`§26.60` 三 那一族）。★ 而且生成侧**在吐出来之前**就拒绝（`rc=3`），
不必等到事后跑本脚本 —— 这才是"护栏"而不是"事后验尸"（`§26.63` A 格①）。

★★ 它**故意不读 NAS**（2026-09-24 实测 `//iSunker-DS423/...` 本机不可达）
---------------------------------------------------------------
要挡的东西是「**有人把一个分类目录名写进了 `DATA_DIRS`**」——
那是**一个字符串问题**，**不需要读磁盘就能判**。
⇒ 本脚本**零网络、零 UNC、零 sqlite**，只读一个文本文件。
★ 判不出就**明说判不出**（`ERR-AI-03`：`n/a ≠ 0 ≠ 没事`），绝不拿"我现在看不到"
  去冒充"没有分类目录"。

用法
----
    # 默认：读仓库根 .env 的 DATA_DIRS（只读）
    python scripts/diag/check-datadirs-names.py

    # 指定别的 env 文件
    python scripts/diag/check-datadirs-names.py --env .env.example

    # ★ 拿候选值当场验证（最重要的一种用法 —— 否则清单永远不会被触发）
    python scripts/diag/check-datadirs-names.py --dirs "/volume1/video/download/TV/儿童"
    python scripts/diag/check-datadirs-names.py --dirs "a/b/儿童,c/d"   # 逗号分隔

    # 只看清单（人读用）
    python scripts/diag/check-datadirs-names.py --list

退出码：`0` = 干净；`1` = **命中分类目录名**（不许进 DATA_DIRS）；`2` = 用法/文件错误。
★ **本脚本永不写任何东西。**
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# ★★ 清单本身在 `datadirs-rules.py`（**唯一出处**）—— 生成侧 `gen-datadirs.py`
#   引用同一份 ⇒ 不存在"两份清单漂移"这个形状（`§26.60` 三 那一族）。
sys.path.insert(0, str(Path(__file__).resolve().parent))
from datadirs_rules import (  # noqa: E402
    CATEGORY_DIR_NAMES,
    NOT_CATEGORY_SAMPLES,
    basename,
    check_paths,
    split_dirs,
)

# ★★ 强制 stdout/stderr 用 UTF-8 —— Windows 控制台默认 GBK，
#   一旦打印非 GBK 字符（`…`/`→`/`✗`）就 UnicodeEncodeError。
#   ★ 那个异常**会污染退出码**（崩成 rc≠0），而本脚本的 rc **是有语义的**
#     ⇒ 会把"崩溃"误读成"命中分类目录名"（`ERR-AI-03` 的形状）。
#   ★ 同时：**正文一律只用 ASCII 分隔符**（`ok`/`!!`/`---`），
#     理由同 `tests/README.md` 的重数器只认 `  ok  ` / ` FAIL `。
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

# --------------------------------------------------------------------------- #
def read_datadirs(env_path: Path) -> tuple[str | None, str]:
    """从 env 文件里读 `DATA_DIRS=` 那一行。

    返回 `(值, 说明)` —— 值是 `None` 时**说明里写清为什么**（别用空串冒充"没有"）。
    """
    if not env_path.is_file():
        return None, "文件不存在：%s" % env_path
    for ln in env_path.read_text(encoding="utf-8", errors="replace").splitlines():
        if ln.startswith("DATA_DIRS="):
            return ln[len("DATA_DIRS="):].strip(), "%s 的 DATA_DIRS 行" % env_path.name
    return None, "%s 里没有 DATA_DIRS= 行" % env_path.name


# ★ 清单的**基名集合**（整名比对用）—— 从共享模块取，**不在本文件里**（唯一出处）
_NAMES = {n for n, _why in CATEGORY_DIR_NAMES}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="只读校验 DATA_DIRS 里没有『分类目录名』")
    ap.add_argument("--env", default=".env",
                    help="要读的 env 文件（默认 .env；只读）")
    ap.add_argument("--dirs", default=None,
                    help="★ 直接给候选（逗号分隔），不读 --env —— 用来当场验证挡板真的会响")
    ap.add_argument("--list", action="store_true", help="只打印清单，不校验")
    ap.add_argument("--quiet", action="store_true", help="只打结论行")
    args = ap.parse_args(argv)

    if args.list:
        print("分类目录名清单（%d 条）—— 这些名字**不许**进 DATA_DIRS：" % len(_NAMES))
        for n, why in CATEGORY_DIR_NAMES:
            print("  · %s\n      %s" % (n, why))
        print("\n反面哨兵（看着像、其实是真发布名，**必须放过**）：")
        for n, why in NOT_CATEGORY_SAMPLES:
            print("  · %s\n      %s" % (n, why))
        return 0

    if not _NAMES:
        # ★ 空清单 = 这道闸门**恒绿**（`ERR-AI-03` 的形状）⇒ 当场报错，不许静默通过。
        print("!! 分类目录名清单是**空的** —— 那这道闸门什么也挡不住", file=sys.stderr)
        return 2

    if args.dirs is not None:
        paths = split_dirs(args.dirs)
        src = "--dirs（候选，共 %d 条）" % len(paths)
    else:
        raw, why = read_datadirs(Path(args.env))
        if raw is None:
            print("!! 读不到 DATA_DIRS：%s" % why, file=sys.stderr)
            return 2
        paths = split_dirs(raw)
        src = why

    hits = check_paths(paths)

    if not args.quiet:
        print("检查对象：%s" % src)
        print("清单：%s" % ("、".join(sorted(_NAMES))))

    if hits:
        print("\n!! 命中 %d 条**分类目录名** —— 它们不是发布名，进 DATA_DIRS 会："
              % len(hits))
        print("   ① 拿这个名字去所有站点搜（浪费查询额度）")
        print("   ② ★★ 搜不到时**静默失败**：日志正常，只是那个『包』永远不被搜")
        for p, b, why in hits:
            print("\n   FAIL %s" % p)
            print("        basename=`%s`" % b)
            print("        %s" % why)
        return 1

    print("\n  ok  干净：%d 条里没有分类目录名" % len(paths))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

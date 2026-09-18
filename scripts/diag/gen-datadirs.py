#!/usr/bin/env python3
"""生成 .env 的 DATA_DIRS 片段。

为什么需要它：cross-seed 把 dataDir 的**直接子目录**当作 searchee，
并用子目录名去站点搜索。如果大包根目录下还有一层"分类/标签"目录
（例如 `DC相关剧集全系列大合集/DC系列电影/01.蝙蝠侠1：侠影之谜 (2005)/…`），
那层中文标签就会被当成 searchee 名 —— 搜不到任何东西，却照样消耗查询额度。

解法：把 dataDir 指到**标签层的每个目录**（`--level 2`），
这样它的直接子目录才是真正的发布名。

用法：
    # 看某层有哪些目录（先确认层数对不对）
    python scripts/gen-datadirs.py "//YOUR-NAS/video/download/movies/DC相关剧集全系列大合集" --level 2 --list

    # 直接输出可粘进 .env 的 DATA_DIRS 片段（NAS 视角的 /volume1/...）
    python scripts/gen-datadirs.py "//YOUR-NAS/video/download/movies/DC相关剧集全系列大合集" \
        --level 2 --nas-prefix /volume1/video

    # 追加到现有 DATA_DIRS（不覆盖已有内容）
    python scripts/gen-datadirs.py "..." --level 2 --append-to .env

--level 含义：1 = 根目录的直接子目录（默认），2 = 再下一层，以此类推。
"""
from __future__ import annotations

import argparse
import os
import sys


def dirs_at_level(root: str, level: int) -> list[str]:
    """返回 root 下第 level 层子目录的**相对路径**（相对 root），已排序。"""
    if level < 1:
        raise ValueError("--level 至少为 1")
    out: list[str] = []

    def rec(path: str, rel: str, depth: int) -> None:
        try:
            entries = sorted(os.scandir(path), key=lambda e: e.name)
        except OSError as e:
            print(f"  !! 无法读取 {path}: {e}", file=sys.stderr)
            return
        for e in entries:
            if not e.is_dir(follow_symlinks=False):
                continue
            if e.name.startswith(".") or e.name == "@eaDir":
                continue
            cur = f"{rel}/{e.name}" if rel else e.name
            if depth == level:
                out.append(cur)
            elif depth < level:
                rec(e.path, cur, depth + 1)

    rec(root, "", 1)
    return out


def to_nas_path(local_root: str, rel: str, nas_prefix: str | None) -> str:
    """把本地/UNC 路径 + 相对路径 转成 NAS 视角路径。

    UNC 形如 //HOST/share/a/b；NAS 视角是 /volumeN/share/a/b。
    --nas-prefix 给的是 share 对应的卷路径（如 /volume1/video）。
    """
    if not nas_prefix:
        return f"{local_root.rstrip('/')}/{rel}"
    norm = local_root.replace("\\", "/").rstrip("/")
    # 去掉 //HOST/<share> 前缀，只留 share 之后的部分
    parts = [p for p in norm.split("/") if p]
    if len(parts) >= 2:
        tail = "/".join(parts[2:])
    else:
        tail = ""
    return "/".join(p for p in [nas_prefix.rstrip("/"), tail, rel] if p)


def main() -> int:
    ap = argparse.ArgumentParser(description="生成 .env 的 DATA_DIRS 片段")
    ap.add_argument("root", help="大包根目录（本地路径或 //NAS/share/... 的 UNC）")
    ap.add_argument("--level", type=int, default=1,
                    help="取第几层子目录，1=直接子目录（默认）")
    ap.add_argument("--nas-prefix",
                    help="NAS 视角的卷路径，如 /volume1/video（用于把 UNC 转成 webhook 路径）")
    ap.add_argument("--list", action="store_true", help="逐行列出，便于先核对")
    ap.add_argument("--append-to", metavar="ENV",
                    help="把结果追加到该 .env 文件的 DATA_DIRS 行末尾")
    args = ap.parse_args()

    if not os.path.isdir(args.root):
        print(f"!! 路径不可达: {args.root}", file=sys.stderr)
        return 2

    rels = dirs_at_level(args.root, args.level)
    if not rels:
        print(f"!! 第 {args.level} 层没有子目录（层数是不是选大了？）", file=sys.stderr)
        return 2

    paths = [to_nas_path(args.root, r, args.nas_prefix) for r in rels]

    if args.list:
        print(f"第 {args.level} 层共 {len(rels)} 个目录：")
        for p in paths:
            print(f"  {p}")
        return 0

    if not args.append_to:
        print(",".join(paths))
        return 0

    # 追加到 .env 的 DATA_DIRS
    env = args.append_to
    with open(env, encoding="utf-8") as f:
        lines = f.read().splitlines()
    hit = False
    for i, ln in enumerate(lines):
        if ln.startswith("DATA_DIRS="):
            cur = ln[len("DATA_DIRS="):].rstrip(",")
            existing = [p for p in cur.split(",") if p]
            new = [p for p in paths if p not in existing]
            if not new:
                print(f"✓ DATA_DIRS 已包含全部 {len(paths)} 条，无需改动")
                return 0
            lines[i] = "DATA_DIRS=" + ",".join(existing + new)
            hit = True
            print(f"✓ 追加 {len(new)} 条（原有 {len(existing)} 条）→ {env}")
            break
    if not hit:
        print(f"!! {env} 里没有 DATA_DIRS= 行", file=sys.stderr)
        return 2
    with open(env, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

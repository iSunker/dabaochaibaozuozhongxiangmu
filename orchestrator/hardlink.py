"""可选的"预拆"模块——参考 hardlink_collection.py 的加固版。

主链路里硬链接由 cross-seed 负责（只对匹配到的单片按发布名建链接）。
本模块保留"把大包所有单片先整体硬链接到某目录"的能力，供以下场景：
  - 你想手动往 :3060 加种（数据已就位）；
  - 将来接非 cross-seed 的匹配器；
  - 只是想在同卷内摆出一份可浏览的单集副本。

相比参考脚本，增加了：同卷校验、统计返回、更清晰的日志、dry-run。
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path

from . import safety

log = logging.getLogger("reseed.hardlink")


@dataclass
class LinkStats:
    linked: int = 0
    skipped: int = 0
    failed: int = 0
    dirs_created: int = 0


def prestage(source_dir: str, target_dir: str, *, dry_run: bool = False) -> LinkStats:
    """把 source_dir 的目录树硬链接到 target_dir（保持相对结构），已存在则跳过。"""
    src = Path(source_dir)
    dst = Path(target_dir)
    if not src.is_dir():
        raise FileNotFoundError(f"源目录不存在或不是目录: {src}")

    # 同卷校验（对尚未创建的 dst 用最近已存在祖先判断）
    if not safety.same_volume(src, dst):
        raise OSError(f"源与目标不在同一物理卷，无法硬链接：{src} <-> {dst}")

    stats = LinkStats()
    if not dry_run:
        dst.mkdir(parents=True, exist_ok=True)

    for root, _dirs, files in os.walk(src):
        rel = os.path.relpath(root, src)
        target_root = dst / rel if rel != "." else dst
        if not target_root.exists():
            if dry_run:
                log.info("[dry-run] 将创建目录: %s", target_root)
            else:
                target_root.mkdir(parents=True, exist_ok=True)
            stats.dirs_created += 1

        for fn in files:
            s = Path(root) / fn
            d = target_root / fn
            if d.exists():
                stats.skipped += 1
                continue
            if dry_run:
                log.info("[dry-run] 将硬链接: %s -> %s", s, d)
                stats.linked += 1
                continue
            try:
                os.link(s, d)
                stats.linked += 1
            except OSError as e:
                log.error("硬链接失败 %s: %s", fn, e)
                stats.failed += 1

    log.info("预拆完成 [%s -> %s]：链接 %d / 跳过 %d / 失败 %d / 新建目录 %d",
             src, dst, stats.linked, stats.skipped, stats.failed, stats.dirs_created)
    return stats

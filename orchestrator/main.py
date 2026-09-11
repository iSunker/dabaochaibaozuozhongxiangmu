"""命令行入口。

子命令：
  preflight  只读预检：配置合法性、各任务同卷/单片枚举、qB 与 cross-seed 连通性。
  run        对启用的任务执行匹配→注入→等待→汇报（--job 只跑一个，--dry-run 不触发）。
  status     连 :3060，按分类列出当前单种的做种状态汇总。
  prestage   可选：把某任务的大包整体硬链接到 linkDir（参考脚本的加固版）。

用法（容器内默认读 /config/config.yml，可用 --config 或环境变量 RESEED_CONFIG 覆盖）：
  python -m orchestrator.main preflight
  python -m orchestrator.main run --job frds-top250-2024
  python -m orchestrator.main status
  python -m orchestrator.main prestage --job frds-top250-2024 --dry-run
"""
from __future__ import annotations

import argparse
import logging
import os
import sys

from . import hardlink, safety
from .config import AppConfig, ConfigError, JobConfig, load_config
from .crossseed_client import CrossSeedClient, CrossSeedError
from .matcher import MatchRun, build_matcher
from .qbit_client import QbitClient, QbitError, classify

DEFAULT_CONFIG = os.environ.get("RESEED_CONFIG", "/config/config.yml")
log = logging.getLogger("reseed")


def setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


# --------------------------------------------------------------------------- #
# 子命令
# --------------------------------------------------------------------------- #
def cmd_preflight(cfg: AppConfig) -> int:
    print("=== 预检 ===")
    all_ok = True

    # 各任务：同卷/单片枚举
    for job in cfg.enabled_jobs():
        pf = safety.preflight_job(job.name, job.source_dir, cfg.matcher.link_dir,
                                  job.include, job.exclude)
        mark = "OK " if pf.ok else "!! "
        print(f"[{mark}] 任务 {job.name}")
        print(f"       源目录: {pf.source_dir}  (存在={pf.source_exists}, 同卷={pf.same_volume_as_link})")
        print(f"       识别到单片子目录: {pf.single_count} 个")
        if pf.single_count:
            preview = ", ".join(pf.singles[:5]) + (" ..." if pf.single_count > 5 else "")
            print(f"       示例: {preview}")
        for p in pf.problems:
            all_ok = False
            print(f"       - 问题: {p}")

    # 连通性：qBittorrent（硬性）
    print("--- 连通性 ---")
    qbit = QbitClient(cfg.qbittorrent.url, auth_mode=cfg.qbittorrent.auth_mode,
                      username=cfg.qbittorrent.username, password=cfg.qbittorrent.password)
    try:
        ver = qbit.connect()
        print(f"[OK ] qBittorrent {ver} @ {cfg.qbittorrent.url}")
    except QbitError as e:
        all_ok = False
        print(f"[!! ] qBittorrent 连接失败: {e}")

    # 连通性：cross-seed（软性，仅提示）
    if cfg.matcher.engine == "cross-seed":
        cs = CrossSeedClient(cfg.matcher.crossseed_url, api_key=cfg.matcher.crossseed_api_key)
        if cs.ping():
            print(f"[OK ] cross-seed 可达 @ {cfg.matcher.crossseed_url}")
        else:
            print(f"[?? ] cross-seed 暂不可达 @ {cfg.matcher.crossseed_url}（部署后再确认）")

    print("=== 预检结果:", "通过" if all_ok else "有问题需处理", "===")
    return 0 if all_ok else 2


def _print_run(run: MatchRun) -> None:
    print(f"--- 任务 {run.job_name} [{run.engine}] ---")
    print(f"    单片总数: {run.singles_total}  触发搜索: {run.searches_triggered}")
    print(f"    分类内: 基线 {run.baseline_count} → 新增 {run.new_count} "
          f"(做种 {run.seeding} / 校验中 {run.checking} / 报错 {run.errors})")
    if run.note:
        print(f"    备注: {run.note}")
    for sr in run.results:
        state = sr.state or "-"
        prog = f"{sr.progress*100:.0f}%" if isinstance(sr.progress, (int, float)) else "-"
        tag = "✓" if sr.matched_torrent else ("→" if sr.search_triggered else "·")
        matched = sr.matched_torrent or "(未对应到新种)"
        print(f"      {tag} {sr.single_name}  [{state} {prog}]  {matched}")


def cmd_run(cfg: AppConfig, job_name: str | None, dry_run: bool) -> int:
    matcher = build_matcher(cfg)
    jobs = [cfg.job(job_name)] if job_name else cfg.enabled_jobs()
    if not jobs:
        print("没有可运行的任务（检查 enabled）")
        return 2

    # 运行前做一次预检，任一硬问题则中止
    for job in jobs:
        pf = safety.preflight_job(job.name, job.source_dir, cfg.matcher.link_dir,
                                  job.include, job.exclude)
        if not pf.ok:
            print(f"[中止] 任务 {job.name} 预检未通过：")
            for p in pf.problems:
                print(f"   - {p}")
            return 2

    print(f"=== 运行{'（dry-run）' if dry_run else ''} ===")
    rc = 0
    for job in jobs:
        try:
            run = matcher.find_and_seed(job, dry_run=dry_run)
            _print_run(run)
            if job.iyuu_handoff:  # ★预留：本版本不触发 IYUU 扩散
                print("    (预留) iyuu_handoff=true，本版本不触发 IYUU 扩散")
        except (QbitError, CrossSeedError, NotImplementedError) as e:
            rc = 3
            print(f"[错误] 任务 {job.name}: {e}")
    return rc


def cmd_status(cfg: AppConfig, category: str | None) -> int:
    qbit = QbitClient(cfg.qbittorrent.url, auth_mode=cfg.qbittorrent.auth_mode,
                      username=cfg.qbittorrent.username, password=cfg.qbittorrent.password)
    try:
        qbit.connect()
        cat = category or cfg.qbittorrent.category
        torrents = qbit.torrents(category=cat)
    except QbitError as e:
        print(f"[错误] {e}")
        return 3

    buckets: dict[str, int] = {}
    for t in torrents:
        buckets[classify(t.get("state", ""))] = buckets.get(classify(t.get("state", "")), 0) + 1
    print(f"=== 分类 {cat!r} 状态汇总（共 {len(torrents)} 个种）===")
    for k in ("seeding", "checking", "downloading", "paused", "error"):
        if buckets.get(k):
            print(f"    {k}: {buckets[k]}")
    for t in torrents:
        prog = t.get("progress", 0) or 0
        print(f"    [{classify(t.get('state',''))} {prog*100:.0f}%] {t.get('name','?')}")
    return 0


def cmd_prestage(cfg: AppConfig, job_name: str | None, dry_run: bool) -> int:
    jobs = [cfg.job(job_name)] if job_name else cfg.enabled_jobs()
    rc = 0
    for job in jobs:
        try:
            hardlink.prestage(job.source_dir, cfg.matcher.link_dir, dry_run=dry_run)
        except OSError as e:
            rc = 3
            print(f"[错误] 任务 {job.name} 预拆失败: {e}")
    return rc


# --------------------------------------------------------------------------- #
# 参数解析
# --------------------------------------------------------------------------- #
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="reseed-orchestrator", description="大包拆包·单种保种编排器")
    p.add_argument("--config", default=DEFAULT_CONFIG, help=f"配置文件路径（默认 {DEFAULT_CONFIG}）")
    p.add_argument("-v", "--verbose", action="store_true", help="调试日志")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("preflight", help="只读预检")

    pr = sub.add_parser("run", help="匹配→注入→等待→汇报")
    pr.add_argument("--job", help="只运行指定任务（默认全部启用的）")
    pr.add_argument("--dry-run", action="store_true", help="只枚举/汇报，不触发搜索与注入")

    ps = sub.add_parser("status", help="按分类汇总做种状态")
    ps.add_argument("--category", help="覆盖默认分类")

    pp = sub.add_parser("prestage", help="可选：把大包整体硬链接到 linkDir")
    pp.add_argument("--job", help="只处理指定任务")
    pp.add_argument("--dry-run", action="store_true", help="只打印将做的操作")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    setup_logging(args.verbose)
    try:
        cfg = load_config(args.config)
    except ConfigError as e:
        print(f"[配置错误] {e}")
        return 1

    if args.cmd == "preflight":
        return cmd_preflight(cfg)
    if args.cmd == "run":
        return cmd_run(cfg, args.job, args.dry_run)
    if args.cmd == "status":
        return cmd_status(cfg, args.category)
    if args.cmd == "prestage":
        return cmd_prestage(cfg, args.job, args.dry_run)
    return 1


if __name__ == "__main__":
    sys.exit(main())

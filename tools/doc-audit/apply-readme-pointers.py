#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""把 `README.md` 里**已经搬进 `ENVIRONMENT.md` 的运维正文段**换成「撤节指针」。

为什么需要脚本而不是手改：
  本次要删的正文有 **~1060 行 / 10 段**，而其中**每一行都必须先被证明过
  「在 `ENVIRONMENT.md` 里逐字节存在」**（见 `verify-move.py`）。
  手改会把「我看起来搬对了」当判据 —— 那正是本项目最贵的那条教训。

做法（**只删不写**）：
  1. 从**旧版**（搬迁前的 rev）里按行号区间取要删的块 —— 保证删的与搬的是同一批字节；
  2. 在每个区间的位置插入 2–5 行「撤节指针」（指向 `ENVIRONMENT.md` 的 `A.NN`）；
  3. **保留** `## 扩展` 下没搬的小节（`#### 生产 .env 怎么更新` / `#### 其它要点`）
     与 `## 常见问题` 里那两处通用段落 —— 它们不在删除区间里。

★ 安全性：脚本**先备份**原 `README.md` 到同目录 `.README.md.presplit`，
  并在结束时打印「删了多少行、留了多少行」，便于与预期核对。
  用法：`python tools/doc-audit/apply-readme-pointers.py [--apply]`（默认 dry-run）
"""
import argparse
import pathlib
import subprocess
import sys

CHR_LF = chr(10)   # ★ LF 的换行符（写成 chr(10) 免得被行尾策略改写）

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

REPO = pathlib.Path(__file__).resolve().parent.parent.parent
README = REPO / "README.md"
PRE_SPLIT = "94a3d0f"          # ★ README 搬迁前的最后一个 commit（见提交信息）

# (区间起行, 区间止行) —— 1-based、闭区间，按**旧版**行号；来自实地核对（不是估算）
CUTS = [
    (443, 528),    # ### 单片状态机
    (529, 612),    # ### 多包支持 + #### 嵌套结构  ← ★ 保留 566-612（生产 .env 怎么更新 / 其它要点）
    (613, 691),    # ### 硬链接农场
    (692, 702),    # ### IYUU 扩散 + ### 别的匹配器
    (703, 837),    # ## 原理技术和风险须知（4 小节）
    (838, 991),    # ### 源文件被写穿 + #### 附：硬链接 vs reflink
    (992, 1039),   # ## 漂移哨兵
    (1040, 1097),  # ## 推前凭据扫描
    (1098, 1362),  # ## 通知 / 告警（5 小节）
    (1373, 1788),  # ## 当前状态（全节）
]

# ★ 特例：多包支持那一段里，**566–612 两小节没搬**（通用做法），必须保留。
KEEP_WITHIN = [(566, 612)]

POINTER = {
    443: (["### 单片状态机 / 多包支持（部分）/ IYUU / 别的匹配器"],
          "**单片状态机的阶段语义、`--depth` 的硬约束、三个真实包的结构** —— 已搬。",
          "★ 真相源：`ENVIRONMENT.md` 的 **`A.13` 运行语义（真实值）**。"),
    566: ([], None, None),   # 保留：生产 .env 怎么更新 / 其它要点
    613: (["### 硬链接农场（v3）"],
          "**农场怎么建、怎么验、怎么切换**（`FARM_SOURCES` 自指闸 / `--map` / 安全边界）—— 已搬。",
          "★ 真相源：`ENVIRONMENT.md` 的 **`A.14` 存储与农场**（与 `A.3` 卷水位是**一对**）。"),
    692: (["### IYUU 扩散 / 别的匹配器（本次不实现）"],
          "这两个**预留位**已搬。",
          "★ 真相源：`ENVIRONMENT.md` 的 **`A.13.3`**。"),
    703: (["## 原理技术和风险须知（原理 A / B / C · 风险清单）"],
          "**「包是声明的不是识别的」· 搜索压力来自分母 · BT 只校验 piece · 风险清单** —— 已搬。",
          "★ 真相源：`ENVIRONMENT.md` 的 **`A.15` 原理与风险（真实值）**；",
          "★ 完整论证与四条对策仍只在 **`SUMMARY §19`**。"),
    838: (["## 源文件被写穿 —— partial 匹配 × 硬链接农场（2026-09-13 发现）"],
          "**那次事故的完整现场记录**（关闸门 · 链接守护 · 硬链接 vs reflink 怎么判）—— 已搬。",
          "★ 真相源：`ENVIRONMENT.md` 的 **`A.16` 写穿事件与链接类型**。"),
    992: (["## 漂移哨兵 / 推前凭据扫描"],
          "**`check-deploy-drift.py`（NAS 与仓库一不一致）· `scan-secrets.py`（推前按值形状扫凭据）** —— 已搬。",
          "★ 真相源：`ENVIRONMENT.md` 的 **`A.17` 部署、漂移与凭据**。"),
    1098: (["## 通知 / 告警（NAS 侧发信）"],
           "**spool 分工 · 两条通道 · 每日摘要=心跳 · DSM 任务配置（含 `21:20` 勘误）· 通知开关** —— 已搬。",
           "★ 真相源：`ENVIRONMENT.md` 的 **`A.18` 通知链路与 DSM 任务**。"),
    1373: (["## 当前状态 / 日常看板 / 怎么继续跑 / 电脑端已不参与 / 交接必读的坑"],
           "**状态快照、日报 `metrics` 八格基线、「三种读不到」的区分、调度与台账** —— 已搬。",
           "★ 真相源：`ENVIRONMENT.md` 的 **`A.19` 观测口径与状态快照**。"),
}



def _write_lf(path, text):
    """以 LF 写文件 —— 本仓 `.gitattributes` 是 `* text=auto eol=lf`。

    2026-09-20 实测踩到：本机 Python 的 `Path.write_text()` 会把换行写成 CRLF，
    而 README 原文是 LF-only ⇒ 改完后 `git diff` 会把**整份文件**显示成改动。
    ★ 同 `SUMMARY §28` 与 `.gitattributes` 注释里那条：**行尾会咬人**。
    """
    with open(path, "w", encoding="utf-8", newline=CHR_LF) as fp:
        fp.write(text)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()

    old = subprocess.run(["git", "show", f"{PRE_SPLIT}:README.md"],
                         capture_output=True).stdout.decode("utf-8").split("\n")
    if not old or len(old) < 100:
        raise SystemExit(f"★ git show {PRE_SPLIT}:README.md 没拿到东西 —— 先回读你实际拿到了什么")

    keep = [False] * len(old)          # True = 这行保留
    for i in range(len(old)):
        keep[i] = True
    removed = 0
    for s, e in CUTS:
        for ln in range(s, e + 1):
            keep[ln - 1] = False
            removed += 1
    for s, e in KEEP_WITHIN:           # 撤销保留区
        for ln in range(s, e + 1):
            keep[ln - 1] = True
            removed -= 1

    out = []
    for i, line in enumerate(old):
        ln = i + 1
        if ln in POINTER and not keep[i]:
            heads, why, *rest = POINTER[ln]
            for h in heads:
                out.append(h)
                out.append("")
            if why:
                out.append("> **本节已搬（2026-09-20，README 瘦身成 GitHub 门面）** —— " + why)
                for r in rest:
                    out.append("> " + r)
                out.append("> ")
                out.append(f"> 原文可从 git 历史取回：`git show {PRE_SPLIT}:README.md`。")
                out.append("")
        if keep[i]:
            out.append(line)

    while out and not out[-1].strip():
        out.pop()

    nptr = sum(1 for ln in POINTER if ln in [s for s, _ in CUTS])
    print(f"旧 README {len(old)} 行 → 新 README {len(out)} 行（删 {removed} 行正文，"
          f"插 {sum(len(v[0]) + 3 for v in POINTER.values())} 行指针，共 {nptr} 处）")
    if not a.apply:
        print("（dry-run —— 加 --apply 才写）")
        # 自证：把保留区与预期逐段列出来
        print("\n保留的非指针区（应包含：三份文档分工/占位符约定/目录结构/两道门/部署/验证/常见问题/安全）:")
        for i, line in enumerate(old):
            if keep[i] and line.startswith("## "):
                print("   ", i + 1, line[:60])
        return 0

    bak = REPO / ".README.md.presplit"
    if not bak.exists():
        _write_lf(bak, "\n".join(old))
        print(f"→ 备份旧版到 {bak.name}")
    _write_lf(README, "\n".join(out) + "\n")
    print(f"→ 写入 {README}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

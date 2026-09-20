#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""把撤节指针里**被引用的子标题**补回去（README 拆分，2026-09-20）。

为什么需要这一步（**这是"另一侧"**）：
  撤节指针保留了**顶层**标题名，但 `ENVIRONMENT.md` 里那批 `ERR-*` 条目的
  「怎么发现的」格还引着**更细的子标题**（`README「链接守护」` / `README「🔴 下一步」`
  / `README「NAS 侧一次性配置」` / `README「两条通道」` …）。
  这些引用**在搬迁前是命中的**（`out.baseline-20260916/refs.tsv` 里状态 OK），
  所以它们是**真丢**、不是"本来就没有" —— 不许当噪音忽略。

做法：在对应指针块里补一行 `#### <原标题>`（**下标仅用于让读者看出它是"已搬的锚"**），
  空块即可 —— 我们要的是**锚点存在**，不是把正文抄回来。

★ 判据：改完 `02_refs.py` 的「锚点无命中」必须回到 **0**（搬迁前是 2，本次顺手清掉）。
★ 反面：不要为了让它变绿而放宽 `mdwalk`/`02_refs` 的匹配口径 ——
  那是「改判据去迁就数据」，正是 `B.10` 第 14 条那个形状。
"""
import argparse
import pathlib
import sys

CHR_LF = chr(10)   # ★ LF 的换行符（写成 chr(10) 免得被行尾策略改写）

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

REPO = pathlib.Path(__file__).resolve().parent.parent.parent
README = REPO / "README.md"

# (锚点文字, 该补的标题行, 该插在哪个已有行**之后**)
# 顺序按文件中出现位置排列，逐条都对着 `02_refs` 的输出核过。
INSERTS = [
    ("### 硬链接农场（v3）",
     "#### 残留风险 / 边界 —— 只留锚（原文见 ENVIRONMENT.md `A.16.1.2`）", None),
    ("## 源文件被写穿 —— partial 匹配 × 硬链接农场（2026-09-13 发现）",
     "#### 链接守护（the 628 条仍是硬链接）—— 只留锚（原文见 ENVIRONMENT.md `A.16.1.2`）", None),
    ("## 推前凭据扫描 —— 别把密钥推上去", None, None),
    ("## 通知 / 告警（NAS 侧发信）",
     "#### 两条通道：坏消息立刻发，好消息进日报 —— 只留锚（原文见 ENVIRONMENT.md `A.18.1.2`）", None),
    ("## 通知 / 告警（NAS 侧发信）",
     "#### NAS 侧一次性配置 —— 只留锚（原文见 ENVIRONMENT.md `A.18.1.4`）", None),
    ("## 当前状态（「下一步」已撤 —— 见 `§26.2`）（2026-09-14 更新）",
     "### 系统现状（一句话）—— 只留锚（原文见 ENVIRONMENT.md `A.19.1.1`）", None),
    ("## 当前状态（「下一步」已撤 —— 见 `§26.2`）（2026-09-14 更新）",
     "### 🔴 下一步（按优先级）—— 只留锚（原文见 ENVIRONMENT.md `A.19.1.2`）", None),
    ("## 当前状态（「下一步」已撤 —— 见 `§26.2`）（2026-09-14 更新）",
     "### 日常看板 —— 只留锚（原文见 ENVIRONMENT.md `A.19.1.4`）", None),
    ("## 当前状态（「下一步」已撤 —— 见 `§26.2`）（2026-09-14 更新）",
     "### 怎么继续跑 —— 只留锚（原文见 ENVIRONMENT.md `A.19.1.6`）", None),
    ("## 当前状态（「下一步」已撤 —— 见 `§26.2`）（2026-09-14 更新）",
     "### 把调度挂到 NAS 上（✅ 已完成 —— 2026-09-12 凌晨）—— 只留锚（原文见 ENVIRONMENT.md `A.19.1.7`）", None),
    ("## 当前状态（「下一步」已撤 —— 见 `§26.2`）（2026-09-14 更新）",
     "### ⛔ 电脑端已不参与（2026-09-12 退役）—— 只留锚（原文见 ENVIRONMENT.md `A.19.1.8`）", None),
    ("## 当前状态（「下一步」已撤 —— 见 `§26.2`）（2026-09-14 更新）",
     "### ⚠ 交接必读的坑 —— 只留锚（原文见 ENVIRONMENT.md `A.19.1.9`）", None),
    ("## 当前状态（「下一步」已撤 —— 见 `§26.2`）（2026-09-14 更新）",
     "### 还没做（已撤 —— 见状态指针）—— 只留锚（原文见 ENVIRONMENT.md `A.19.1.10`）", None),
    ("## 当前状态（「下一步」已撤 —— 见 `§26.2`）（2026-09-14 更新）",
     "#### 收尾命令（一次重建同时办完两件事）—— 只留锚（原文见 ENVIRONMENT.md `A.19.1.10.1`）", None),
    ("### 单片状态机（已实现）—— 记录每部片子走到哪一步了",
     "#### 多包支持（已接入 3 个包）—— 只留锚（原文见 ENVIRONMENT.md `A.13.2`）", None),
]



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
    t = README.read_text(encoding="utf-8")

    # 每条按「插在该指针块的 `> 原文可从 git 历史取回…` 之前」处理
    for anchor, heading, _ in INSERTS:
        if heading is None:
            continue
        # 找到该锚点段的结束（即那一行的 `git show …` 引用行），把 heading 插到它前面
        i = t.index(anchor)
        j = t.index(f"中", i) if False else i
        k = t.index("> 原文可从 git 历史取回", i)
        block = t[i:k]
        if heading.split("（")[0] in block:
            print(f"  · 已有，跳过：{heading}")
            continue
        print(f"  + 在 {anchor[:24]}… 里补 {heading[:40]}…")
        t = t[:k] + heading + "\n\n" + t[k:]

    if a.apply:
        _write_lf(README, t)
        print("→ 已写入")
    else:
        print("（dry-run —— 加 --apply 才写）")
    return 0


if __name__ == "__main__":
    sys.exit(main())

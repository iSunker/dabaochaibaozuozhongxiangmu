#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""datadirs-rules —— `DATA_DIRS` 的「分类目录名」清单（**唯一出处**）。

★★ 为什么单独一个模块（2026-09-24 `§26.64`）
--------------------------------------------------
这份清单原本长在 `check-datadirs-names.py` 里。但**写 `DATA_DIRS` 的入口有两个**：

| 入口 | 干什么 |
|---|---|
| `gen-datadirs.py` | ★ **生成**片段（按 `--level N` 递归取子目录）|
| `gen-nas-env-update.py` | ★ 把本地 `.env` 的 `DATA_DIRS` **搬上 NAS** |

而**校验器 `check-datadirs-names.py` 是事后跑**的 —— 即：
**先生成错的、再靠校验器抓**。★ 那是「一半的护栏」：**没跑校验器就没人拦**
（`§26.63` A 格①的原话）。

⇒ 把清单抽到这里，**生成侧和校验侧引用同一份**：
  · 生成侧（`gen-datadirs.py`）能**在吐出来之前**就报错（事前）；
  · 校验侧（`check-datadirs-names.py`）照旧兜底（事后）。
★ **两份清单漂移**这个形状本仓踩过（`§26.60` 三 / `check-deploy-drift.py` 的两份手写清单）
—— 所以这里**只留一份**，两边 `import`，没有第二份可漂。

判据（一个名字凭什么进这份清单）
--------------------------------
它**进 `DATA_DIRS` 会导致 cross-seed 拿它去搜站点**，而它**不是发布名**
（是分类习惯 / 语言标签 / 占位目录）。
⇒ **整名比对**（`basename == 清单项`），**不是子串包含** —— 后者会把
`儿童医院.S01.2026…` 这种**真发布名**误杀（`A.11`「量错了对象」）。

★ **每条都必须"真的会在目录树里出现"**（死规则比缺规则更坏）——
  `tests/test_datadirs_names.py` ② 段会核这一条（每条须在 `summary/26` 有实证记录）。

本模块**零依赖、零副作用**（只放常量，不读文件、不打印）。
"""
from __future__ import annotations

# --------------------------------------------------------------------------- #
# ★★★ 分类目录名清单（**手写** —— 加一条必须写清"它为什么不是发布名"）
# --------------------------------------------------------------------------- #
CATEGORY_DIR_NAMES: list[tuple[str, str]] = [
    ("儿童", "★ 分类习惯（不是发布名）。实测真空（2026-05-05）；`§26.58` 三 标为『真·分类目录』。"
             "拿它去搜站点 ⇒ 搜不到 + 静默失败"),
    ("欧美剧", "★ 同上（真空，2026-05-08）。`§26.58` 三 同一条"),
]

# ★ 反面哨兵：这些名字**看着像**分类目录，但**其实是真发布名**，不许加进清单。
#   闸门会拿它们跑一遍，**若被命中 ⇒ 说明判据写宽了**（把真发布名杀了）。
NOT_CATEGORY_SAMPLES: list[tuple[str, str]] = [
    ("儿童医院.S01.2026.1080p.WEB-DL.H.264", "真发布名里含『儿童』二字 —— 整名比对必须放过它"),
    ("The.First.Jasmine.2026.S01.1080p.Disney+.WEB-DL.AVC-QHstudIo", "`[莫离]` 那种（§26.61）"),
    ("Outlast.The.Jungle.2026.S01.2160p.NF.WEB-DL.DDP5.1.H.265-DepWeb", "同一部剧的三个版本之一（§26.62）"),
]

# ★ 清单的**基名集合**（整名比对用）—— 生成侧与校验侧共用。
CATEGORY_BASENAMES: frozenset[str] = frozenset(n for n, _why in CATEGORY_DIR_NAMES)


def basename(p: str) -> str:
    """取路径的**基名**（去掉尾斜杠）。

    ★ 不用 `os.path.basename`：它按**宿主机**的分隔符走，而这里的路径是
      **NAS 视角的 POSIX 路径**（`/volume1/video/...`），在 Windows 上
      `ntpath.basename("/a/b/儿童")` 也能对，但一旦有人写成 `//NAS/share/…`
      就会多出歧义 ⇒ **自己按 `/` 切**，语义单一。
    """
    return p.replace("\\", "/").rstrip("/").rsplit("/", 1)[-1]


def split_dirs(raw: str) -> list[str]:
    """把 `DATA_DIRS` 的值切成**逐条路径**（逗号分隔；忽略空项、去空白）。"""
    return [p.strip() for p in (raw or "").split(",") if p.strip()]


def is_category_dir(path: str) -> str | None:
    """路径的基名若是分类目录名 ⇒ 返回**理由**；否则 `None`。"""
    b = basename(path)
    if b in CATEGORY_BASENAMES:
        return {n: why for n, why in CATEGORY_DIR_NAMES}[b]
    return None


def check_paths(paths: list[str]) -> list[tuple[str, str, str]]:
    """逐条检查；返回 `[(原路径, 基名, 理由)]`（**命中的**）。"""
    hits: list[tuple[str, str, str]] = []
    for p in paths:
        why = is_category_dir(p)
        if why is not None:
            hits.append((p, basename(p), why))
    return hits

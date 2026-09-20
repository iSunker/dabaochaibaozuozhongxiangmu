#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""一次性：把 `tests/README.md` 的**读数历史段**搬进 `summary/31`，并包上生成区。

★ 第一版**做错了**（2026-09-20 实测，记在这里免得重犯）：
  它只按日期行**逐行**删，于是那些日期行的**续行段落全被留下、且被截断**
  （「43 条 —— `#58` drive-loop 迁容器…」这种**没有主句的残段**）。
  屏幕上 `git diff` **看着像正常删减** —— 只有逐段读才发现主句没了。
  ⇒ 正解：**整段搬**（从第一条日期行到 `## 各测什么` 之前，92 行一起走）。
  ★ 同 `INDEX-USAGE` 第七节「搬迁的验证法」：判据是**字节**，不是"看着对"。

做三件事（默认 dry-run）：

1. **整段搬** L15–L107（92 行）→ `summary/31-测试计数的口径与历史.md`；
   ★ 其中**最后一条**日期行（当前读数）**不搬** —— 它由生成器渲染。
2. 把那条当前日期行**换成生成区标记**（数字由 `gen-counts.py` 填）。
3. 表格外包一对生成区标记（同一个生成区：表格 + 当前读数行）。

★ 区外的字**一个不动**（「钉住什么」注解、`## 怎么跑`、`## 写测试时踩过的坑`…）。
"""
import argparse
import pathlib
import re
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

REPO = pathlib.Path(__file__).resolve().parent.parent.parent
README = REPO / "tests" / "README.md"
HISTORY = REPO / "summary" / "31-测试计数的口径与历史.md"

DATE = re.compile(r"^\d{4}-\d{2}-\d{2} 实测：\*\*\d+ 个脚本、\d+ 条断言")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()

    lines = README.read_text(encoding="utf-8").split("\n")
    date_idx = [i for i, l in enumerate(lines) if DATE.match(l)]
    tbl_head = next(i for i, l in enumerate(lines) if l.startswith("## 各测什么"))
    if not date_idx:
        raise SystemExit("★ 找不到日期行")
    s, e, cur = date_idx[0], tbl_head, date_idx[-1]
    moved = [l for i, l in enumerate(lines[s:e]) if s + i != cur]
    print(f"历史段 L{s+1}–L{e}（{e-s} 行）")
    print(f"  → 搬走 {len(moved)} 行（含 {sum(1 for l in moved if DATE.match(l))} 条旧日期行）")
    print(f"  → 保留 L{cur+1} 那条当前读数，**由生成器重渲**")

    if not a.apply:
        print("\n（dry-run —— 加 --apply 才写）")
        return 0

    HISTORY.write_text(
        "# §31 测试计数的口径与历史\n\n"
        "> ★ **本文件是 2026-09-20 从 `tests/README.md` 整段搬来的**（原 L15–L107，92 行）。\n"
        "> 搬的理由：那是**追加式读数史**（每跑一轮往里加一段）+ **计数口径的说明**。\n"
        "> 数字已降级成**派生数据**（源 = 真跑；`tests/COUNTS.json`；`tests/gen-counts.py`），\n"
        "> ⇒ 历史挪到这里留档，`tests/README.md` 只留**当前那一条**（机器渲染）。\n"
        "> ★ **正文逐字搬，未改一字** —— 下面的读数都是**当时**的，别当现值。\n\n"
        "---\n\n" + "\n".join(moved).strip() + "\n",
        encoding="utf-8", newline=chr(10))
    print(f"→ {HISTORY.relative_to(REPO)}")

    # 删掉整段，在它原来的位置放生成区（生成器稍后重渲内容）
    lines[s:e] = ["<!-- counts:auto:begin（本节由 tests/gen-counts.py 生成，别手改）-->",
                  "<!-- counts:auto:end -->"]
    README.write_text("\n".join(lines), encoding="utf-8", newline=chr(10))
    print(f"→ {README.relative_to(REPO)}：历史段已换成生成区标记")
    print("★ 下一步：`python tests/gen-counts.py`")
    return 0


if __name__ == "__main__":
    sys.exit(main())

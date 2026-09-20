#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""README 拆分的**引用改指** —— 逐条、可复核、可回滚。

背景：2026-09-20 把 README 的运维正文搬进 `ENVIRONMENT.md`（新 `A.13`–`A.19`）后，
一批 `README「<标题>」` 的**锚点引用**指向了已经搬走的标题 ⇒ 会变成 `ANCHOR-MISS`。
本脚本把这批引用改指到新位置。

★ 设计原则（照 `INDEX-USAGE` 第七节那两条）：
  1. **逐条显式列出** —— 不批量正则替换。批量替换在「同一句话里有两种引用」时会改错。
  2. **只改指针，不改叙述** —— 替换串只动「文档名+标题引用」那一截，
     前后的中文原样保留（历史过程记录里的措辞不许动）。
  3. **历史审计记录不动** —— `INDEX-USAGE.md` L409–413 是**09-20 那次复检的记录**
     （它记录的正是"当时这两条是 ANCHOR-MISS"这个事实），改了它＝改坏现场。
     同 `f2c2af9` 对 `summary/12` 的处置。
  4. **`tests/README.md` 不在投影范围内**（`mdwalk.doc_files()` 只收仓库根 + `summary/`），
     所以那两处**手工改**，并在这里记一笔免得下次又被漏掉。

用法：`python tools/doc-audit/apply-readme-refs.py [--apply]`（默认 dry-run）
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

# (文件, 行号, 旧串, 新串) —— 行号按**当前**工作区（改指前）核对过
EDITS = [
    # ── summary/12：这一对是 `02_refs` 抓到的**真回归**（既有 ANCHOR-MISS），本次顺势归零 ──
    ("summary/12-收尾归档.md", 15,
     "README「当前状态与下一步」", "`ENVIRONMENT.md` `A.19`（原 README「当前状态与下一步」）"),
    ("summary/12-收尾归档.md", 100,
     "README「当前状态与下一步」", "`ENVIRONMENT.md` `A.19`（原 README「当前状态与下一步」）"),
    # ── 通知 / 告警 → A.18 ──
    ("summary/13-接手会话.md", 641, "README「通知 / 告警」一节", "`ENVIRONMENT.md` `A.18` 一节"),
    ("summary/20-观测层语义收敛.md", 290, "README「通知 / 告警」节", "`ENVIRONMENT.md` `A.18` 节"),
    ("summary/26-跨会话任务盘面与旧会话清场.md", 216,
     "README「通知 / 告警（NAS 侧发信）」节", "`ENVIRONMENT.md` `A.18` 节"),
    ("summary/26-跨会话任务盘面与旧会话清场.md", 224, "README「通知 / 告警」那节", "`ENVIRONMENT.md` `A.18` 那节"),
    ("summary/26-跨会话任务盘面与旧会话清场.md", 1793, "README「通知 / 告警」那段", "`ENVIRONMENT.md` `A.18` 那段"),
    # ── 原理 → A.15 ──
    ("summary/23-卷归属复核与SMB探针分辨力.md", 147,
     "README「原理 A：没有「识别」，只有「声明」」", "`ENVIRONMENT.md` `A.15.1`「原理 A」"),
    ("summary/27-装不出来的单种.md", 58, "README「原理 C」", "`ENVIRONMENT.md` `A.15.3`「原理 C」"),
    ("tests/README.md", 32, "（README「原理 C」）", "（`ENVIRONMENT.md` `A.15.3`「原理 C」）"),
    # ── 漂移哨兵 → A.17 ──
    ("summary/18-目录布局调整.md", 1065, "README「漂移哨兵」一节", "`ENVIRONMENT.md` `A.17.1`「漂移哨兵」一节"),
    # ── 调度 / NAS 配置 → A.18 ──
    ("summary/13-接手会话.md", 291, "README「把调度挂到 NAS 上」", "`ENVIRONMENT.md` `A.18`（原 README「把调度挂到 NAS 上」）"),
    ("summary/14-驱动层迁到NAS.md", 6, "README「把调度挂到 NAS 上」", "`ENVIRONMENT.md` `A.18`（原 README「把调度挂到 NAS 上」）"),
    ("summary/14-驱动层迁到NAS.md", 184, "README「把调度挂到 NAS 上」", "`ENVIRONMENT.md` `A.18`（原 README「把调度挂到 NAS 上」）"),
    ("summary/14-驱动层迁到NAS.md", 207, "README「NAS 侧一次性配置」", "`ENVIRONMENT.md` `A.18.1.4`「NAS 侧一次性配置」"),
    # ── 「还没做」→ 本来就已经 ANCHOR-MISS（`f2c2af9` 改了该节标题），本次一并修 ──
    ("summary/20-观测层语义收敛.md", 127, "README「还没做」第 14 条", "`summary/26` `§26.2`（原 README「还没做」第 14 条）"),
    ("summary/20-观测层语义收敛.md", 128, "README「还没做」第 14 条", "`summary/26` `§26.2`（原 README「还没做」第 14 条）"),
    ("summary/20-观测层语义收敛.md", 129, "README「还没做」第 14 条", "`summary/26` `§26.2`（原 README「还没做」第 14 条）"),
]

# ★ 明确**不动**的（写下来免得下次有人"顺手修"）：
SKIP = [
    ("tools/doc-audit/INDEX-USAGE.md", 103, "`README「…」` 的定义行 —— 这条语法**照旧有效**"),
    ("tools/doc-audit/INDEX-USAGE.md", 409, "09-20 复检的**历史记录**：它记的正是'当时是 ANCHOR-MISS'"),
    ("tools/doc-audit/INDEX-USAGE.md", 412, "同上"),
    ("tools/doc-audit/INDEX-USAGE.md", 413, "同上"),
    ("summary/16-待做的四个自动化.md", 612, "已自带「该节 2026-09-19 已移除」—— 措辞已自洽，不动"),
    ("summary/18-目录布局调整.md", 519, "同上"),
    ("summary/12-收尾归档.md", 59, "「多站点」那节**没搬**（仍在 README `## 扩展`）⇒ 引用仍然有效"),
    ("tests/test_linkguard.py", 4, "注释里的「源文件被写穿」—— ★ 该标题**仍在 README**（撤节指针保留了原名）"),
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

    print("═══ 要改的 ═══")
    ok = 0
    for path, lineno, old, new in EDITS:
        f = REPO / path
        lines = f.read_text(encoding="utf-8").split("\n")
        if lineno - 1 >= len(lines) or old not in lines[lineno - 1]:
            print(f"  ✗ {path}:{lineno} 没找到 {old!r}")
            continue
        # ★ 防止"同一行里有两种引用"时改错：断言这一行**只出现一次**
        if lines[lineno - 1].count(old) != 1:
            print(f"  ✗ {path}:{lineno} 该行出现 {lines[lineno - 1].count(old)} 次 —— 需人工")
            continue
        ok += 1
        print(f"  ok {path}:{lineno}")
        print(f"      - {old}")
        print(f"      + {new}")
        if a.apply:
            lines[lineno - 1] = lines[lineno - 1].replace(old, new)
            _write_lf(f, "\n".join(lines))

    print("\n═══ 明确不动的 ═══")
    for path, lineno, why in SKIP:
        print(f"  · {path}:{lineno} —— {why}")

    print(f"\n{'已写入' if a.apply else '（dry-run —— 加 --apply 才写）'}  {ok}/{len(EDITS)} 处")
    return 0 if ok == len(EDITS) else 1


if __name__ == "__main__":
    sys.exit(main())

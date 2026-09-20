#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""verify-move —— 证明「搬走的正文在新位置**逐字节**相同」。

为什么需要它（2026-09-20，README 拆分那次）：
  本仓最贵的一条教训是 `INDEX-USAGE` 第七节那句 ——
  「我以为我拿的是 A，其实拿到的是 B」。搬迁这种事**不能靠"我看起来搬对了"**：
  过程记录一旦被顺手改掉/精简/重排，**下一个读者看不出这里改过**（同 `A.11` 的反例）。

  所以：**搬迁前**先把它记住（`--save`），**搬迁后**逐段比对（`--check`）。

口径（★ 关键，别改）：
  · 比对**只到"符号级切片"**：从旧文档的某个起始行（含）到下一个标题行（不含）。
  · **标题行里的编号前缀被允许变**（`### 原理 A` → `### A.15.0 原理 A`）——
    那是**搬迁本身**必需的，不是内容改动。**除标题那一行以外，一个字都不许动。**
  · 归一化只做两件**明确且可解释**的事：① 去掉行尾 `\r`（本仓 CRLF/LF 混历史）；
    ② 切片的**首尾空白行**不计。此外一律逐字符比。

用法
----
    # 搬迁前：把每一段记进一个 manifest（存旧文档的 rev + 每段的起止锚）
    python tools/doc-audit/verify-move.py --save manifest.json \
        --from 94a3d0f:README.md --seg "单片状态机（已实现）" --seg "原理 A：没有"

    # 搬迁后：逐段证明它还在（在新文件里按标题搜到同名的段）
    python tools/doc-audit/verify-move.py --check manifest.json --into ENVIRONMENT.md

退出码：0 = 每一段正文都逐字节相同；1 = 有任何一段不同（**打印差异**，不静默）；2 = 用错。
"""
import argparse
import difflib
import hashlib
import json
import pathlib
import re
import subprocess
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HEAD_RE = re.compile(r"^#{1,6} ")
# 标题里的编号前缀：`### A.13.1 单片状态机` / `### 原理 A` ⇒ 剥掉「层级+编号」，只留正文标题
NUM_PREFIX = re.compile(r"^(#+)\s+(?:[A-Z]\.\d+(?:\.\d+)*\s+|§?\d+\.\d+(?:\.\d+)*\s+|〔[^〕]*〕\s*)?")


def read_rev(spec):
    """`<rev>:<path>` → 行列表。★ 先回读你实际拿到了什么（INDEX-USAGE 第七节）。"""
    if ":" not in spec:
        raise SystemExit("★ 需要 <rev>:<path> 形式，例如 94a3d0f:README.md")
    rev, path = spec.split(":", 1)
    p = subprocess.run(["git", "show", f"{rev}:{path}"], capture_output=True)
    if p.returncode != 0:
        raise SystemExit(f"★ git show {spec} 失败：{p.stderr.decode('utf-8','replace').strip()}")
    return p.stdout.decode("utf-8").split("\n")


def norm(lines):
    """两件明确且可解释的归一化 —— 见模块头注。"""
    out = [l.rstrip("\r") for l in lines]
    while out and not out[0].strip():
        out.pop(0)
    while out and not out[-1].strip():
        out.pop()
    return out


def seg_by_anchor(lines, anchor):
    """从含 `anchor` 的那个标题行（含）到下一个标题行（不含）。"""
    s = None
    for i, l in enumerate(lines):
        if HEAD_RE.match(l) and anchor in l:
            s = i
            break
    if s is None:
        return None
    e = len(lines)
    for j in range(s + 1, len(lines)):
        if HEAD_RE.match(lines[j]):
            e = j
            break
    return lines[s:e]


def strip_heading(lines):
    """返回 (标题行, 其余正文行)。"""
    return (lines[0], lines[1:]) if lines else ("", [])


def sha(lines):
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()[:16]


def cmd_save(args):
    src = read_rev(args.from_)
    man = {"from": args.from_, "segments": []}
    for anchor in args.seg:
        seg = seg_by_anchor(src, anchor)
        if seg is None:
            raise SystemExit(f"★ 在 {args.from_} 里找不到锚点：{anchor!r}")
        body = norm(seg[1:])
        man["segments"].append({
            "anchor": anchor, "in": body[0][:60] if body else "",
            "body_sha": sha(body), "lines": len(body),
        })
        print(f"  记住 {anchor!r}: {len(body)} 行正文  body_sha={sha(body)}")
    pathlib.Path(args.save).write_text(json.dumps(man, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"→ {args.save}（{len(man['segments'])} 段）")
    return 0


def cmd_check(args):
    man = json.loads(pathlib.Path(args.manifest).read_text(encoding="utf-8"))
    dst = norm(pathlib.Path(args.into).read_text(encoding="utf-8").split("\n"))
    bad = 0
    for seg in man["segments"]:
        got = seg_by_anchor(dst, seg["anchor"])
        if got is None:
            print(f"  ✗ 在新文件里找不到锚点：{seg['anchor']!r}")
            bad += 1
            continue
        body = norm(got[1:])
        ok = sha(body) == seg["body_sha"]
        print(f"  {'ok  ' if ok else '✗  '} {seg['anchor']!r}: {len(body)} 行  body_sha={sha(body)}"
              f"（期望 {seg['body_sha']}）")
        if not ok:
            bad += 1
            d = [l for l in difflib.unified_diff(
                seg.get("_old_preview", "").split("\n"), body, lineterm="")
                if l.startswith(("+", "-")) and not l.startswith(("+++", "---"))]
            for l in d[:12]:
                print("        ", l)
    if bad:
        print(f"\n★ {bad} 段**不逐字节相同** —— 这正是不许静默跳过的那一格。")
        return 1
    print(f"\n✓ {len(man['segments'])} 段正文**逐字节相同**（行号与标题编号前缀不计）")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--save"); ap.add_argument("--from", dest="from_")
    ap.add_argument("--check", dest="do_check")
    ap.add_argument("--into"); ap.add_argument("--manifest")
    ap.add_argument("--seg", action="append", default=[])
    a = ap.parse_args()
    if a.save:
        if not a.from_ or not a.seg:
            raise SystemExit("★ --save 需要 --from <rev>:<path> 与至少一个 --seg")
        return cmd_save(a)
    if a.do_check:
        return cmd_check(a)
    raise SystemExit("★ 用 --save 或 --check，见 --help")


if __name__ == "__main__":
    sys.exit(main())

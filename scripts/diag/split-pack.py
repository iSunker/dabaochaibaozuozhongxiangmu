#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""「大包按季拆分」—— **只读**看一个源大包，报出**可执行的拆分方案**。

★★ 定位（2026-09-21 立，用户问「每集里有 S01E1/S02E2 这种，能不能不查 TMDB 自动拆？」）

  它**只做三件事**：① 列目录 ② 判季界 ③ 把该跑的硬链接命令**拟好给人看**。
  ★★ **它绝不自己建农场条目、绝不移动源文件** —— 理由：
     · `A.10`：**AI 不写 NAS** ⇒ 真正执行的是人；
     · `A.16`：源是**硬链接的目标**，动它 = 可能写穿原本在做种的源文件；
     · `A.13.2`：**「要不要拆、拆成什么」是产品决定**，不是一行能自动消除的代码债。

★ 为什么要有它：现行农场（v3）的「一片 = 一个发布名目录」只对「一片即一季/一部」成立。
  发布者把**整部剧**打成一个发布名（`…Complete…`）、单集平铺在下面时，
  农场就只剩「整部剧一片」这一条路 —— 而站点上是**按季**发的 ⇒ 匹配不上。
  ⇒ 这个脚本负责**把那种包拆成一季一个条目**，且**取名字也一起拟好**。

★★★ 季界判据 —— **分档，可靠的自动、不可靠的明确拒绝**（本仓最贵的教训之一：不许猜）

  ★ 档 1（`--by-name`，默认）：文件名里有 `SxxExx` ⇒ **直接按它分组**，零外部依赖。
      正则只认**词边界**形态（`S01E05` / `s1e5` / `S01.E05` / `S01-E05`），
      ★★ **不认** `E05` 这种**裸集号**（那没有季信息，见档 2/3）。

  ★ 档 2（`--by-dir`）：目录里本来就有季层（`S01/`、`Season 2/`、`第1季/`）⇒ 用**季层名**。
      ★ 它的季号来自目录名，**不是从文件名推的**。

  ★ 档 3（`--season-hint`）：★★ **平铺流水号（`E01..E24`、无任何季痕迹）** ——
      ★★★ **本脚本拒绝猜**（见下）。

★★ **档 3 为什么拒绝猜**：`E01..E24` 里「前 12 集是 S01」这个信息
  **不在文件名里、也不在目录结构里**。用「文件大小聚类 / 时长聚类 / 平均分」去蒙，
  是**在编**——而编错的代价是**发出去一个错种**（`A.15.4`：本项目**只搬运、不保证**，
  但我们**不能主动制造错的划分**）。
  ⇒ 档 3 的正路是**外部季界**（后续实现，见下），不是启发式：
     ① **Prowlarr / Torznab**（★ 优先 —— 用已有的 Prowlarr，不引入新凭据）：
        Torznab 的 `tvsearch` 支持 `season=` 参数，且返回的 item 可能带季信息。
        ★ 但「返回里到底有没有可解析的季字段」**尚未实测** ⇒ 本脚本**不假装它有**。
     ② **TMDB / 豆瓣**（★ 外部凭据 + 联网 ⇒ 用户 2026-09-21 拍：**接口先留、实现后补**）。
  ⇒ 本脚本对档 3 的当前行为：**明确报「判不出」，并打印 ①/② 两条后续路线**，**不产出方案**。

用法：
    python scripts/diag/split-pack.py "<源包目录>"              # 默认：按文件名 SxxExx
    python scripts/diag/split-pack.py "<源包目录>" --by-dir     # 按季层目录名
    python scripts/diag/split-pack.py "<源包目录>" --emit-cmds  # 额外打印拟命令
    python scripts/diag/split-pack.py "<源包目录>" --root "//iSunker-DS423/..."  # 指定 NAS 侧前缀

退出码：0 = 出了方案（或明确报"只有一季 ⇒ 不用拆"）；3 = **判不出季界**（不猜）；2 = 读不到目录。

★ 安全（与 `find-packs.py` / `qb-census-savepath.py` 同一形状）：
  **只读**（只 `os.scandir`）、**不写任何东西**、**不改配置**、**不碰凭据**。
"""
import argparse
import os
import re
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

#: 档 1 的季集正则。★ 只认「季号 + 集号」成对出现的形态：
#:   S01E05 · s1e5 · S01.E05 · S01-E05 · S01 E05 · S01_E05
#: ★★ 刻意**不**匹配裸 `E05` —— 那没有季信息（档 3），匹配上就是"猜"。
#: ★ `\b` 在这里**不可靠**：`S01E05` 前面常是 `.` 或 `[`，而 `_` 也算词字符
#:   ⇒ 用"前面不是字母数字"的否定环视，比 `\b` 准（本仓踩过 `\b` 与 `_` 的坑：`ERR-ENC-05`）。
_SE_EP = re.compile(r"(?<![A-Za-z0-9])[Ss](\d{1,2})[\s._-]?[Ee](\d{1,3})(?![0-9])")

#: 档 1 的**兜底**：`S01.05` 这种"点分季集号"（没有字母 E）。
#: ★ 只在**没有** `_SE_EP` 命中时才用 —— 因为它更宽松，更容易误伤
#:   （如 `1080p.S01` 之后跟一个数字）。⇒ 保守使用。
_SE_DOT = re.compile(r"(?<![A-Za-z0-9])[Ss](\d{1,2})[\s._-](\d{1,3})(?![0-9])")

#: 档 2 的季层目录名。★ 覆盖常见写法：`S01` · `Season 1` · `第1季` · `S01.1080p`（前缀形态）。
_DIR_SEASON = re.compile(
    r"^(?:[Ss]eason[\s._-]*(\d{1,2})|[Ss](\d{1,2})(?![\dEe])|第\s*(\d{1,2})\s*季)"
)

#: 视频扩展名（与 `orchestrator/state.py` 的 `VIDEO_EXTENSIONS` 同一份口径，
#: ★ 这里只取常见的那批 —— 本脚本只用来"数入口"，不参与任何登记判断）。
VIDEO_EXT = frozenset({
    ".mkv", ".mp4", ".avi", ".ts", ".m4v", ".mov", ".wmv", ".rmvb", ".flv", ".mpg", ".mpeg",
})


def season_of(name):
    """从**文件名**里取季号（档 1）。返回 int 或 None。"""
    m = _SE_EP.search(name)
    if m:
        return int(m.group(1))
    m = _SE_DOT.search(name)
    if m:
        return int(m.group(1))
    return None


def episode_of(name):
    """从**文件名**里取集号（档 1）。返回 int 或 None。"""
    m = _SE_EP.search(name)
    if m:
        return int(m.group(2))
    m = _SE_DOT.search(name)
    if m:
        return int(m.group(2))
    return None


def season_of_dir(name):
    """从**目录名**里取季号（档 2）。返回 int 或 None。"""
    m = _DIR_SEASON.match(name)
    if not m:
        return None
    for g in m.groups():
        if g is not None:
            return int(g)
    return None


def walk_videos(root):
    """把 root 下**所有**视频文件找出来（递归，跳过 `@eaDir` 一类的系统目录）。"""
    out = []
    skip = ("@eaDir", "#recycle", "@tmp", ".DS_Store")
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in skip and not d.startswith(".")]
        for fn in filenames:
            if os.path.splitext(fn)[1].lower() in VIDEO_EXT:
                out.append(os.path.join(dirpath, fn))
    return out


def group_by_name(root, files):
    """档 1：按文件名里的 `SxxExx` 分组。返回 ({季号: [相对路径]}, 无季号的文件列表)。"""
    groups, unknown = {}, []
    for p in files:
        rel = os.path.relpath(p, root)
        # ★ 只拿**文件名的最后一段**去看季集号 —— 父目录名里也可能有 `S01`，
        #   那属于档 2 的信息，混进来会把档 1 的判据污染（本仓"两个判据量不同的东西"
        #   那个形状：`B.10` 第 20 条）。
        s = season_of(os.path.basename(rel))
        if s is None:
            unknown.append(rel)
        else:
            groups.setdefault(s, []).append(rel)
    return groups, unknown


def group_by_dir(root, files):
    """档 2：按**季层目录名**分组。返回 ({季号: [相对路径]}, 归不到季的文件列表)。"""
    groups, unknown = {}, []
    for p in files:
        rel = os.path.relpath(p, root)
        parts = rel.split(os.sep)
        hit = None
        for seg in parts[:-1]:                     # 只看目录段
            s = season_of_dir(seg)
            if s is not None:
                hit = s
                break
        if hit is None:
            unknown.append(rel)
        else:
            groups.setdefault(hit, []).append(rel)
    return groups, unknown


def derive_names(root_name, seasons):
    """★ 从**源发布名**机械派生每个季条目的名字。

    ★★ 判据（用户 2026-09-21 定）：**按 `.` 切词，把"季/完整性"那一格换成 `Sxx`，
       其余**原样保留**。★ 派生的名字就是"我们要发的那个种的名字" ⇒ 它**就是规范**。

    ★ 找不到可替换的那一格时**明确报出来**，不硬塞（否则会造出一个不存在的发布名）。
    返回 ({季号: 新名字}, 无法派生的原因 or None)。
    """
    parts = root_name.split(".")
    # ★ 候选格：含"完整性/季"语义的那些词（大小写不敏感）。
    keys = ("complete", "series", "season", "s0", "s1", "全集", "全季")
    idx = None
    for i, seg in enumerate(parts):
        low = seg.lower()
        if any(low == k or low.startswith(k) for k in keys):
            idx = i
            break
    if idx is None:
        # ★ 退而求其次：找**纯季号**那一格（`S01` 之类），但它可能不存在。
        for i, seg in enumerate(parts):
            if re.fullmatch(r"[Ss]\d{1,2}", seg):
                idx = i
                break
    if idx is None:
        return {}, ("源发布名里**找不到「季/完整性」那一格**（候选词：%s）"
                    "⇒ 不硬塞，请人工定名" % ", ".join(keys))
    out = {}
    for s in seasons:
        new = list(parts)
        new[idx] = "S%02d" % s
        out[s] = ".".join(new)
    return out, None


def main():
    ap = argparse.ArgumentParser(add_help=True)
    ap.add_argument("source", help="源大包目录（本地/UNC 路径都可）")
    ap.add_argument("--by-dir", action="store_true",
                    help="按季层目录名判季（默认按文件名 SxxExx）")
    ap.add_argument("--emit-cmds", action="store_true", help="打印拟好的命令草稿")
    ap.add_argument("--root", default="", help="NAS 侧前缀（拟命令里用）")
    args = ap.parse_args()

    src = args.source
    if not os.path.isdir(src):
        print("[!] 读不到目录：%s" % src)
        print("    ★ 「读不到」不是「没有」（B.10）：先确认路径、SMB 挂载、权限。")
        return 2

    root_name = os.path.basename(os.path.normpath(src))
    print("源包：%s" % root_name)
    print()

    files = walk_videos(src)
    print("视频文件 %d 个。" % len(files))
    if not files:
        print("★ 一个视频文件都没扫到 —— （a）它本来就是空的／（b）扩展名不在名单里／")
        print("  （c）路径打到了父目录而不是包本身。★ 本读数**分不开**这三种，先人工看一眼。")
        return 2
    print()

    if args.by_dir:
        groups, unknown = group_by_dir(src, files)
        mode = "档 2（季层目录名）"
    else:
        groups, unknown = group_by_name(src, files)
        mode = "档 1（文件名 SxxExx）"

    print("季界判据：%s" % mode)
    print()

    if not groups:
        print("★★ **判不出季界** —— 这个包**不猜**。")
        print("   归不到季的文件 %d 个（样例）：" % len(unknown))
        for r in unknown[:5]:
            print("     %s" % r)
        print()
        print("★ 为什么会判不出：`E01..E24` 这种**裸集号**里没有季信息，")
        print("  而「前 12 集是 S01」这个信息**不在文件名里、也不在目录结构里**。")
        print("  ⇒ 用文件大小/时长聚类去蒙 = **在编**，编错就发出去一个错种。")
        print()
        print("★ 正路是**外部季界**（两条，都还没实现）：")
        print("   ① **Prowlarr / Torznab**（优先：用已有 Prowlarr，不引新凭据）——")
        print("      Torznab 的 `tvsearch` 支持 `season=`；★ 返回里有没有可解析的季字段**尚未实测**。")
        print("   ② **TMDB / 豆瓣**（外部凭据 + 联网）—— 用户 2026-09-21 拍：**接口先留、实现后补**。")
        return 3

    seasons = sorted(groups)
    print("判到 **%d 季**：%s" % (len(seasons), ", ".join("S%02d" % s for s in seasons)))
    for s in seasons:
        print("  S%02d：%d 个文件" % (s, len(groups[s])))
    if unknown:
        print()
        print("⚠ 另有 **%d 个文件归不到任何季**（样例）：" % len(unknown))
        for r in unknown[:5]:
            print("     %s" % r)
        print("   ★ 它们**不在方案里** —— 拆的时候别漏，先人工判它们属于哪季（或本来就不该进农场）。")
    print()

    if len(seasons) < 2:
        print("★ 只有一季 ⇒ **按用户 2026-09-21 的判据，这不叫大包**：")
        print("  整包一片就行（农场条目名 = 源发布名），**不用拆**。")
        print("  ★ 除非它里面混着**别的季**却因为命名漏了季号 —— 那属于「判不出」，见上。")
        return 0

    names, why = derive_names(root_name, seasons)
    print("★ 拟用的农场条目名（从源发布名机械派生）：")
    if why:
        print("  [!] %s" % why)
    else:
        for s in seasons:
            print("  S%02d → %s" % (s, names[s]))
    print()

    if args.emit_cmds:
        print("★ 拟命令（**只打印，不执行**）—— 硬链接建到农场，**源不动**：")
        print()
        prefix = args.root or "//iSunker-DS423/video/download/reseed/reseed_farm"
        for s in seasons:
            if why:
                print("  # S%02d：名字待人工定（见上）" % s)
                continue
            print("  # ── S%02d" % s)
            print("  mkdir -p \"%s/%s\"" % (prefix, names[s]))
            for rel in sorted(groups[s])[:3]:
                print("  ln \"%s/%s\" \"%s/%s/\"   # … 其余同理" % (
                    src.rstrip("/\\"), rel.replace(os.sep, "/"),
                    prefix, names[s]))
            if len(groups[s]) > 3:
                print("  #   （本季共 %d 个文件，其余同理）" % len(groups[s]))
        print()
        print("★★ 硬链接前**先读** `A.16`（写穿）与 `A.13.2`（农场怎么建、怎么验）：")
        print("   源**绝不能**被移动/改名 —— 它是硬链接的目标，也是原本在做种的源文件。")
    print()
    print("★★ **本脚本只报方案、不动任何文件** —— 建条目、建链接都由人执行（`A.10`）。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

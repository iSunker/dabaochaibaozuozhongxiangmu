#!/bin/sh
# chk-volume1-free.sh —— /volume1 「可用空间」到底是多少：NAS 侧判据（只读）
#
# 它在回答什么
# ------------
# 本机探针（`shutil.disk_usage('//iSunker-DS423/video')`，走 SMB）2026-09-17 报
#   /volume1 可用 5457.79 GiB（= 5.33 TiB，Used 90.46%）
# 而群晖自己的 Storage Analyzer 周报（2026-09-16，04:07）报
#   Volume 1 Used = 99.9%（反推可用 ~57 GiB）
# 两者 **total 逐字节相等**（61401196064768 B）⇒ 同一个卷、同一个 Size，
# 却差了 **5.27 TiB**。这不是"路径指错了"，是**两个读数真对不上**。
#
# 为什么不能只靠 SMB 判
# ---------------------
# `ERR-FS-04`：BTRFS 的 reflink/CoW 副本 **inode 不同、`%h` 也是 1**，
# 删了**不一定**释放空间；`ENVIRONMENT.md` A.3 末 ★：SMB 侧 `stat -c %d` 零分辨力、
# `nlink` 恒读 1（假阴性）。⇒ 只有 NAS 侧能看见 extent 与快照。
#
# ★★ 代价（`ERR-CMD-02`，先读再跑）
# ---------------------------------
# `/volume1` = 56 TB、**碎片化** BTRFS，且 cross-seed / qB **还在写**。
#   - 全树 `du -shx` / `btrfs filesystem du <整卷>` 是 **分钟~小时级**，
#     2026-09-13 直接把用户界面**敲卡住**过。**本脚本不跑全树。**
#   - 本脚本只做：① 三条 `df`（秒级）② **几个小目录/单文件**的 `btrfs du`（秒级）
#     ③ 元数据计数（秒级）。
#   - `-d 1` 那种"按第一层汇总"**仍可能是分钟级**，所以它**不是默认**，
#     要用得显式加 --deep，并且**先想清楚要不要**。
#
# 用法（**在 NAS 上跑**，DSM 里开 Terminal / 或计划任务里手动执行一次）
# -------------------------------------------------------------------
#   sudo sh chk-volume1-free.sh              # 默认：轻量（秒级）
#   sudo sh chk-volume1-free.sh --deep       # 追加 btrfs du -d1（可能分钟级）
#   sudo sh chk-volume1-free.sh --path /volume1/video/download/reseed/reseed_farm
#                                            # 只对一个指定目录做 btrfs du -s
#
# ★ 输出别重定向到 /volume1（满卷 / ERR-FS-03）——
#   本脚本**不写任何文件**，全部打 stdout，你复制走就行。
#
# ★ 本脚本**只读**：没有 rm / mv / cp / chmod / chown / truncate。
#   `btrfs filesystem du` 是**统计**（只读 extent 表），不改数据。

set -u

DEEP=0
ONE_PATH=""
while [ $# -gt 0 ]; do
    case "$1" in
        --deep) DEEP=1 ;;
        --path) shift; ONE_PATH="${1:-}" ;;
        *) echo "未知参数: $1" >&2; exit 2 ;;
    esac
    shift
done

# 找 btrfs 工具（DSM 上通常在 /sbin，PATH 里可能没有）
BTRFS=""
for c in btrfs /sbin/btrfs /usr/sbin/btrfs /usr/bin/btrfs; do
    if command -v "$c" >/dev/null 2>&1; then BTRFS="$c"; break; fi
done

echo "=== chk-volume1-free.sh  $(date '+%Y-%m-%d %H:%M:%S')  ==="
echo

echo "--- [1] df：卷级可用空间（这是最权威的『当下』读数）---"
df -h /volume1 /volume2 2>&1
echo
# ★ 这一节要保证"要么给出数、要么明说给不出" —— 空着会**看起来像"没问题"**（B.10 第 14 条）
LINE=$(df -B1 /volume1 2>/dev/null | tail -n +2 | head -1)
if [ -n "$LINE" ]; then
    echo "$LINE" | awk '{printf "  /volume1 可用 = %s B = %.2f GiB = %.4f TiB\n", $4, $4/1073741824, $4/1099511627776}'
    echo "  对照 A：本机 SMB 探针 2026-09-17 13:10 报 5457.79 GiB（Used 90.46%）"
    echo "  对照 B：群晖 SA 周报 2026-09-16 04:07 报 Volume 1 Used 99.9%（~57 GiB）"
    echo "  ⇒ 看本节数字落在 A 附近还是 B 附近；若都不像，说明还有第三种口径。"
else
    echo "  !! df -B1 /volume1 没给出可解析的行 —— 本节的读数**缺失**，不是通过"
fi
echo

echo "--- [2] 文件系统与设备（确认真是 BTRFS / cachedev_1）---"
mount | grep -E '/volume1|/volume2' 2>&1
echo

echo "--- [3] BTRFS 空间账：df 与 usage 可能不是一回事 ---"
if [ -n "$BTRFS" ]; then
    echo "\$ $BTRFS filesystem df /volume1"
    $BTRFS filesystem df /volume1 2>&1
    echo
    echo "\$ $BTRFS filesystem usage -h /volume1   # 看 Free (estimated) / Unallocated"
    $BTRFS filesystem usage -h /volume1 2>&1
    echo
    echo "★ Data 行的 'used' 含 CoW/reflink 共享块；Unallocated 才是没分给任何 chunk 的裸空间。"
else
    echo "!! 找不到 btrfs 命令 —— 后面的 extent 判据跑不了（df 仍然有效）"
fi
echo

echo "--- [4] 快照：SMB 侧看不见 @ 前缀目录，只有这里能看 ---"
if [ -n "$BTRFS" ]; then
    # ★ 2026-09-17 实测：普通用户跑 `subvolume list` 报
    #   "ERROR: can't perform the search - Operation not permitted"
    #   而脚本当时把它记成 "(总条数: 0)" —— **那是假绿**：查不了 ≠ 没有。
    OUT4=$($BTRFS subvolume list /volume1 2>&1)
    if echo "$OUT4" | grep -qi 'Operation not permitted\|Permission denied'; then
        echo "  !! 权限不足 —— 本节的读数**拿不到**，不是『没有快照』"
        echo "     （普通用户跑 subvolume list 会 EPERM；这一条必须 sudo）"
        if [ "$(id -u)" = "0" ]; then
            echo "  ?? 已是 root 仍报权限不足 —— 换查 /proc/mounts 里的 subvol："
            grep -c 'subvol=/' /proc/mounts
        fi
    else
        echo "$OUT4" | head -30
        N4=$(printf '%s\n' "$OUT4" | grep -c 'ID ')
        echo "  (条数: $N4)"
        if [ "$N4" -gt 0 ]; then
            echo "★ 有 @snapshots / 大量 snap_* ⇒ 空间可能是被快照按着，删了原始文件也不释放。"
        else
            echo "★ 条数 0 且**没有**报权限错 ⇒ 才是『确实没有子卷/快照』。"
        fi
    fi
else
    echo "!! 跳过（无 btrfs 命令）"
fi
echo

echo "--- [5] 抽样：单文件的 Exclusive 列（ERR-FS-04 指定的判据，秒级）---"
if [ -n "$BTRFS" ]; then
    echo "★ ★ 2026-09-17 实测教训：对**目录**跑 btrfs du 会卡死（reseed_farm 里几万文件）。"
    echo "   ⇒ 本节**只挑单个文件**（ERR-FS-04 原文：单文件是秒级）。"
    echo "   取件方式：按大小挑几个**最大的**散文件，不做通配递归。"
    echo
    # 只对已知目录做**浅层**取样（maxdepth 1，不递归）—— find 比 btrfs du 快得多
    picked=0
    for d in /volume1/video/download/reseed/reseed_farm \
             /volume1/video/download/reseed/reseed_singles \
             /volume1/video/link; do
        [ -d "$d" ] || continue
        echo "$ $BTRFS filesystem du -s <单文件，取自 $d>"
        # 浅层、按大小排序取前 3 —— find 只走一层，秒级
        find "$d" -maxdepth 2 -type f -size +100M 2>/dev/null | head -3 | while read -r x; do
            echo "  --- $x"
            timeout 20 $BTRFS filesystem du -s "$x" 2>&1 | sed 's/^/      /'
        done
        picked=$((picked+1))
    done
    if [ "$picked" = "0" ]; then
        echo "  !! 没找到可抽样的目录 —— 本节读数**缺失**，不是通过"
    fi
    echo
    echo "★ 读法（ERR-FS-04）：Exclusive ≈ 0 ⇒ 与别处共享 extent、删了不释放；"
    echo "  Exclusive ≈ Total ⇒ 才真占着这卷的空间。"
    echo "★ 已知警告：intra-file reflink 时 Exclusive 可能被**高报**。"
else
    echo "!! 跳过（无 btrfs 命令）"
fi
echo

if [ -n "$ONE_PATH" ] && [ -e "$ONE_PATH" ] && [ -n "$BTRFS" ]; then
    echo "--- [6] 指定目标：$ONE_PATH ---"
    df -h "$ONE_PATH" 2>&1
    if [ -d "$ONE_PATH" ]; then
        # ★ 目录：**不**对目录跑 btrfs du（见 [5] 节实测教训）。只做浅层取样。
        echo "  ★ 这是目录 —— 按 2026-09-17 的教训**不**对它跑 btrfs du（会卡死）。"
        echo "     改为：浅层挑最大 5 个**单文件**，逐个跑（每个 20s 封顶）。"
        find "$ONE_PATH" -maxdepth 2 -type f -size +100M 2>/dev/null | head -5 \
            | while read -r x; do
                echo "  --- $x"
                timeout -s TERM 20 $BTRFS filesystem du -s "$x" 2>&1 | sed 's/^/      /' \
                    || echo "      (20s 超时/出错 —— 该文件读数缺失)"
                stat -c '      nlink=%h size=%s ino=%i' "$x" 2>&1
            done
    else
        # 单文件：秒级，安全
        echo "\$ $BTRFS filesystem du -s $ONE_PATH"
        timeout -s TERM 60 $BTRFS filesystem du -s "$ONE_PATH" 2>&1
        rc6=$?
        [ "$rc6" != "0" ] && echo "  !! rc=$rc6 —— **本节读数缺失**，不是通过"
        stat -c '    nlink=%h size=%s ino=%i %n' "$ONE_PATH" 2>&1
    fi
    echo "★ nlink(%h)==1 **判不出** CoW/reflink（ERR-FS-04），仅作对照。"
    echo
fi

if [ "$DEEP" = "1" ] && [ -n "$BTRFS" ]; then
    echo "--- [7] --deep：按第一层汇总（★ 可能分钟级，ERR-CMD-02）---"
    # ★ 2026-09-17：对目录跑 btrfs du 已实测会把终端卡住（reseed_farm 几万文件）。
    #   这一节保留，但要**倒计时可中断**，且明确告诉你卡住怎么办。
    echo "★★ 你明确要求了 --deep。这条在本卷上可能几分钟到几十分钟。"
    echo "   卡住的话按 Ctrl-C 中止（不是 Ctrl-Z —— 那只是挂起，进程还占着 I/O）。"
    echo
    echo "\$ $BTRFS filesystem du -d 1 /volume1/video"
    # 用 timeout 真杀：SIGTERM 后再补刀，避免它退化成僵尸占 I/O
    timeout -s TERM 180 $BTRFS filesystem du -d 1 /volume1/video 2>&1
    rc7=$?
    if [ "$rc7" = "124" ]; then
        echo "  !! 180s 超时，已强制终止（rc=124）—— **本节读数缺失**。"
        echo "     结论：这个卷上 -d 1 也不可行。用 [5] 的单文件抽样就够了。"
    elif [ "$rc7" != "0" ]; then
        echo "  !! 出错 rc=$rc7 —— **本节读数缺失**，不是通过。"
    fi
    echo
fi

echo "--- [8] 回收站与松散文件（A.2.1 收口用）---"
for p in /volume1/video /volume1/#recycle /volume1/video/#recycle; do
    if [ -d "$p" ]; then
        n=$(ls -1A "$p" 2>/dev/null | wc -l)
        echo "  $p : $n 项"
    fi
done
echo
echo "=== 完（本脚本未写任何文件）==="

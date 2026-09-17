#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""NAS 漂移哨兵 —— **只读**。回答两个「有没有我不知道的东西」：

  A. NAS 上  有没有**既不在部署白名单、也不在已知生产独有清单**里的文件？
  B. 仓库里  有没有**既没进部署白名单、也没被明确标为「不部署」**的已跟踪文件？

为什么需要它
------------
`deploy.sh` 是**白名单式、单向**（本地 → NAS）的：它保证白名单里那些文件两边
一致，**白名单之外的一律不碰、也不报告**。于是两个方向都会悄悄长东西：

  A 方向（NAS 上冒出来的）：手工拷上去的脚本、忘了删的一次性补丁、某次调试
     留下的产物。风险是它**不在任何同步机制里** —— 既不会被更新，也不会被
     发现，只会在某天以「NAS 上跑的行为和仓库里这份不一样」的形式咬人。
     前车之鉴：`build-farm.sh`、`fix-statedb-farm-root.py`、`nas-update-env.sh`
     这三个都是这么手工躺在 NAS 上的，2026-09-12 才逐个收进白名单。

  B 方向（仓库里没登记的）：新写了个脚本，忘了加进 `deploy.sh` 的 FILES，
     于是「git 提交里有它、NAS 上没有它」—— 而没有任何东西会提醒你。
     这正是「git 提交时是不是 NAS 拿一部分、电脑拿一部分」那个问题的答案。

★★ 受管集合**从 `deploy.sh` 的 FILES 数组解析出来，绝不在这里复制一份** ——
   复制就是又造一个漂移源，还会和 deploy.sh 各自漂到不同的地方去。
   解析一旦对不上（有 `::` 的行没解析出目的地）直接 exit 2：**宁可吵，也不误报**。
   因为解析悄悄失败会让受管集合变空，于是「全部文件都不认识」这场假警报
   会把真信号淹掉 —— 一个会误报的哨兵，两次之后就没人看了。

用法
----
    python scripts/check-deploy-drift.py              # DST 取自 --dst / 环境变量 / scripts/.nasrc
    python scripts/check-deploy-drift.py --all        # 连已知生产独有的一并列出（默认只报数）
    python scripts/check-deploy-drift.py --cleanup    # 额外打一份"整理杂物"的 mv 计划（**仍然只读**）
    python scripts/check-deploy-drift.py --no-nas     # 只做 B 方向（NAS 不可达时也有用）

★ `--cleanup` 只**打印**计划，自己不写任何东西：本脚本的契约是只读。
  计划里只有 `mv`、没有 `rm` —— 对 NAS 的 UNC 路径跑 `rm` 是禁止的（见禁止清单）。

★ 杂物里有**一类要单看**：`.env` 的备份/变体。它不是噪音，是**形似凭据泄漏** ——
  备份里装的是真凭据。所以它既单独列一行计数、又置 `fail=1`，不混进「杂物 N 个」
  那个数里（那个数本身也不可读：它是"活着的模块数"的代理量，涨了不代表出杂物——
  `drive-loop` 每 import 一个模块就多一个 `.pyc`）。严重度写在 `KNOWN_NAS` 规则的
  第三项（`ALERT`），**不另立正则表**。

退出码
------
    0 = 干净   1 = 有未登记的（需要人看一眼）   2 = 环境问题（NAS 不可达 / 解析失败）
"""
import datetime
import os
import pathlib
import re
import subprocess
import sys

# ★ 输出**无条件**强制 UTF-8。别试图做得更"聪明"—— 第一版写成
#   `if not _s.isatty(): _s.reconfigure(...)`，想"管道用 UTF-8、tty 交给控制台"，
#   结果在 Windows 上直接炸：**NUL 是字符设备，`isatty()` 对它返回 True**，
#   于是 `>/dev/null` 时反而跳过 reconfigure，按 GBK 编码 ✓★⚠ 抛
#   UnicodeEncodeError —— 而那是个**未捕获异常，退出码也是 1**，
#   和"发现漂移"的 1 长得一模一样；traceback 又跟正常输出去了同一个 /dev/null。
#   症状：40/40 次 `>/dev/null` 都"报漂移"，而所有测试跑法（管道/落文件）全绿。
#   → 判据自己要先被验证一遍（同 SUMMARY §18.10.1）；仓库另外 7 个脚本用的
#     就是这里这个无条件写法，别改。
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")
    except Exception:
        pass

REPO = pathlib.Path(__file__).resolve().parent.parent
DEPLOY = REPO / "deploy.sh"

# ★ 严重度：杂物里有一类**不是噪音**，是「形似凭据泄漏」—— NAS 上躺着一份 `.env`
#   的备份/变体。把它和 `__pycache__` 混在同一个计数里是错的：前者该有人立刻看一眼，
#   后者是字节码。（2026-09-13：起因是「杂物 3 个」这个数**本身不可读** ——
#   它是"当前活着的模块数"的代理量，下界随 import 而变化，涨了不代表出杂物。）
#   ★ 严重度用**同一份清单的第三项**表达，绝不另立一份正则表 —— 那会造出第二个
#     声明点，两份迟早漂开（本仓库反复吃过这个形状的亏，见 deploy.sh 的教训）。
#     `classify()` 只读 `rule[0]`、调用方只读 `rule[1]`，所以加这一项对既有代码
#     是**纯增量** —— 没有 alert 的规则仍是 2 元组，照旧工作。
#   ★ 定义必须**在 KNOWN_NAS 之前**：清单里那条 `.env` 规则在构造时就要用到 ALERT，
#     放后面会 NameError（本文件刚踩过，测试是当场抓到的 —— 这就是它有回归测试的价值）。
ALERT = "alert"


def is_alert(rule):
    """这条规则是不是「形似凭据泄漏」。规则是本清单里的 (正则, 说明[, 严重度])。"""
    return len(rule) > 2 and rule[2] == ALERT


# NAS 上**已知合理**的、不在白名单里的东西。每一条都要写清"为什么它该在 NAS 上"。
# 判据用正则匹配 **POSIX 相对路径**（不含开头的 ./），比 fnmatch 的 `**` 语义更可控。
KNOWN_NAS = [
    # ---- 生产独有：含凭据 / 运行时状态，**故意**不进白名单（deploy.sh 原则第 2 条）----
    (r"^\.env$",                                  "真实凭据"),
    (r"^prowlarr/",                               "站点 cookie + Prowlarr 库"),
    (r"^cross-seed/cross-seed\.db.*",             "cross-seed 库（含 -wal/-shm）"),
    (r"^cross-seed/cross-seeds/",                 "cross-seed 硬链接产物"),
    (r"^cross-seed/logs/",                        "cross-seed 日志"),
    (r"^cross-seed/torrent_cache/",               "cross-seed 种子缓存"),
    (r"^drive-loop/hlink/",                       "从本地一次性迁移过去的 state.db"),
    (r"^drive-loop/attempts\.log$",               "批次台账（NAS 上追加写）"),
    (r"^drive-loop/scripts/drive-loop\.log$",     "驱动日志"),
    (r"^drive-loop/scripts/\.[^/]+\.state$",      "心跳 / --once 闸门 / 巡检状态"),
    (r"^hlink/\.reseed_farm\.manifest\.tsv.*",    "农场清单及其名字侧写"),
    (r"^notify/notify\.conf$",                    "含收件人邮箱"),
    (r"^notify/archive/",                         "已发出的通知归档"),
    (r"^notify/log/",                             "通知日志"),
    # ★ 2026-09-13 补：原先漏登，于是**只要扫的那一刻 spool 里还有没被取走的告警，
    #   哨兵就报「未知文件」**（实测撞上 2 个），而它是**完全正当**的运行时目录 ——
    #   drive-loop.py 写纯文本事件、notify-spool.sh 每 5 分钟排空（README「通知」一节）。
    #   同 log/ 与 archive/ 一类，不是"该定期清"的杂物：它**自己会被排空**。
    #   ★ 注意别把它当杂物：spool 里有积压是**另一条**通道在报（日报里那句
    #     「spool 积压: N 条告警」），登记它不会把那个信号盖掉。
    (r"^notify/spool/",                           "待发的通知事件（每 5 分钟被 notify-spool.sh 排空）"),
    # ---- 杂物：已知、合理、但**该定期清**（哨兵只报数，不删）----
    # ★ 2026-09-13 放宽：原先写作 `^\.env\.bak\..*`，于是**裸名 `.env.bak`**
    #   （不带时间戳后缀 —— 正是 rm-staging.sh 那条窄口 8/7 里的第 8 个）不匹配，
    #   会掉进"没登记过的"把哨兵**误报**成有未知文件。同一类坑在 rm-staging.sh
    #   与 .gitignore 上各犯过一次，教训一致：**别靠猜文件名叫什么**。
    #   这里按 `.env.` / `.env_` 两种前缀全兜，只排掉 `.env.example`
    #   （它是模板、**压根不部署**，见下面 LOCAL_ONLY；排掉只为分类语义干净）。
    #   `.env` 本体不受影响 —— 它在上面那条 `^\.env$` 就命中了，**先匹配先赢**。
    (r"^\.env[._](?!example$)",                 "杂物·.env 备份/变体", ALERT),
    (r"^build-farm\.sh\.bak\..*",                 "杂物·旧脚本备份"),
    (r"^notify/probe-artifacts-[^/]*/",           "杂物·一次性探测产物"),
    (r"(^|/)__pycache__/",                        "杂物·python 字节码"),
    (r"^_cleanup-[0-9]{8}/",                      "杂物·本哨兵 --cleanup 暂存区（确认后在 NAS 上整个删掉）"),
]
CLUTTER = re.compile(r"^杂物·")

# 仓库里**已跟踪、但明确不该部署**的文件。同样每条都写清理由 ——
# 这是一份"公开声明"，不是"懒得管的兜底"：没登记的东西会被 B 方向报出来。
LOCAL_ONLY = [
    (r"^\.gitattributes$",                        "仓库元数据"),
    (r"^\.gitignore$",                            "仓库元数据"),
    (r"^\.env\.example$",                         "模板；生产用真实 .env，白名单**故意**不含它"),
    (r"^README\.md$",                             "文档"),
    (r"^SUMMARY\.md$",                            "文档"),
    (r"^ENVIRONMENT\.md$",                        "文档·环境前提与坑手册（检索层，不是事实源）"),
    (r"^patches/",                                "在 NAS 上**手工**应用的操作说明"),
    (r"^tests/",                                  "离线自测（在 Windows 上跑，不进容器）"),
    # ★ 2026-09-13：文档整理审计工具（标题树 / 引用对账 / 关键词倒排 / 只读探针）。
    #   判据与下面 qb-census / linkguard 那两条**同一形状**：
    #   **只读 + 不回显凭据 + 只打聚合**（不是「它碰没碰凭据」）。
    #   04_probes.py 读 cross-seed.db 的 indexer 表，但**不选 url 列** ——
    #   那条每行都带 apikey=<Prowlarr 应用级 key>，而判「哪个站、什么状态」
    #   靠 id/name/status 就够；出口再统一过一遍 redact() 兜底（**两条都要**）。
    #   另外三个只看三份 md，不碰网络。产物目录 out/ 已进 .gitignore。
    #   INDEX-USAGE.md 是这些投影的**用法 + 两周观察基线**（09-13 建 / 09-20 复跑 /
    #   09-27 决策）—— 给人和工具看的说明，**不是第三份事实源**。
    (r"^tools/doc-audit/",                        "文档审计工具 + 索引用法（在 Windows 上跑；只读 md + UNC 只读 + HTTP 只读；不选 indexer.url 列，出口统一 redact()）"),
    (r"^deploy\.sh$",                             "同步工具本身（在 Windows 上跑）"),
    # ★ 2026-09-17：/volume1 可用空间的 NAS 侧判据。它是**一次性诊断件**，但留下来
    #   可复用（下次再遇"读数对不上"直接拿它跑），所以**进版本库、不进白名单**。
    #   判据与上面 doc-audit / qb-census 那几条**同一形状**：
    #   **只读 + 不回显凭据 + 只打聚合**（它不是"碰没碰凭据"的问题 —— 它根本不碰凭据，
    #   只跑 df / btrfs filesystem usage / subvolume list）。
    #   ★ 脚本内部**零写操作**已成契约（无 rm/mv/cp/chmod/chown/truncate），
    #   且**刻意不写任何文件**（输出全走 stdout）—— 因为它的目标卷是满盘，
    #   往那里写东西会触发 ERR-FS-03 的 ENOSPC 级联。
    #   ★ 它读的是 NAS **原生路径**（/volume1），所以**只能在 NAS 上跑**；
    #   从 Windows 跑只会得到"路径不存在"（正是 §26.7 那条"SMB 视图 ≠ NAS 视图"）。
    (r"^scripts/chk-volume1-free\.sh$",           "卷水位判据（在 **NAS** 上跑；只读 df/btrfs，零写操作、不落盘、不碰凭据；一次性诊断件）"),
    (r"^scripts/check-deploy-drift\.py$",         "本哨兵（在 Windows 上跑）"),
    (r"^scripts/scan-secrets\.py$",               "推前凭据扫描（在 Windows 上跑；读本地 .env，但绝不打印命中到的值）"),
    (r"^scripts/audit-found-lines\.py$",          "对账 a−b（在 Windows 上跑；只读 NAS 的 info.current.log，不碰库）"),
    (r"^scripts/audit-found-resolve\.py$",        "对账 b−c（在 Windows 上跑；UNC 直读 state.db，query_only 硬闸，绝不写）"),
    (r"^scripts/torznab-probe\.py$",              "手搜探针（在 Windows 上跑；读 NAS .env 的 TORZNAB_URLS 但**绝不回显**，只发一次 Torznab 查询）"),
    # ★ 2026-09-13：qB 落点普查。它和上面那条是**同一形状** —— 都读本地 .env 的凭据
    #   去连 NAS 上的服务，且都**只打聚合**（这条打的是 count / tag 名 / 路径前 4 段，
    #   绝不打 torrent 名、tracker、content_path）。
    #   ⇒ 判据是「**只读 + 不回显凭据 + 不打印可识别内容**」这三条同时成立，
    #     不是「它碰没碰凭据」—— 后者会把所有有用的诊断工具都挡在门外。
    (r"^scripts/qb-census-savepath\.py$",         "qB 落点普查（在 Windows 上跑；读本地 .env 的账号口令登录，只打聚合计数与路径前 N 段）"),
    # ★ 2026-09-13：链接守护的诊断端。与上面 qb-census 那条是**同一形状**
    #   （只读 + 不回显凭据 + 只打聚合），判据也一样。它比那条更严一点：
    #   默**只出 hash 前 12 位**，发布名要 `--show-names` 才出（名字里有站点与
    #   发布名，不该随随便便进日志）。它读的是 NAS 上 drive-loop 写的
    #   `.linkguard.state`，**只读不写**。
    (r"^scripts/crossseed-linkguard\.py$",        "链接守护诊断（在 Windows 上跑；读 NAS 的 .linkguard.state + 只读问一次 qB，默认只出 hash）"),
    # ★ 2026-09-14：`ERR-SVC-17` 的 ② 机制探针。与上面两条是**同一形状**
    #   （只读 + 不回显凭据 + 只打白名单字段），判据也一样。它替换掉的是
    #   `ENVIRONMENT.md` 早先那条**把 key 摆在命令行上**的裸 curl ——
    #   那条除了漏凭据，返回的裸 JSON 还得人肉把 indexerId 对到站名。
    #   key 从生产 .env 读；**不调 `/api/v1/indexer`**（那个响应带 fields：cookie/passkey）；
    #   站名只从 cross-seed.db 取 id/name 两列（url/apikey 那两列带凭据）。
    (r"^scripts/prowlarr-indexerstatus\.py$",     "Prowlarr 本地禁用探针（在 Windows 上跑；读 NAS .env 的 key 但绝不打印、只打白名单字段）"),
    # ★ 2026-09-15：#109（Prowlarr key 轮换）的前置探针。与上面那条是**同一形状**
    #   （只读 + 不回显凭据 + 只打白名单字段）。
    #   它多守一条**阴性对照**：验 key 时同时发「假 key」与「不带 key」两组，
    #   否则端点要是压根不校验，那个 200 什么也证明不了。
    #   只用 `t=caps`（Prowlarr 本地定义回答，**不打 PT 站**）—— 所以站点退避时也能跑。
    (r"^scripts/torznab-keycheck\.py$",           "Torznab key 有效性探针（在 Windows 上跑；读 NAS .env 的 key 但绝不打印，带阴性对照，只发 t=caps）"),
    # ★ 2026-09-14：群晖 Storage Analyzer 报告的只读读者。只读、无凭据（走 SMB 读报告目录），
    #   而且 zip 是**内存里**解、不落盘。它存在的理由是**留一句否定结论的证据**：
    #   「报告里没有可用空间」这个结论决定了一条待办（见 README 的 #77）。
    (r"^scripts/sa-volume-usage\.py$",            "只读群晖 Storage Analyzer 报告（在 Windows 上跑；内存解 zip、不落盘、无凭据）"),
    # ★ 2026-09-13：#58「drive-loop 迁容器」的草案，**故意不进白名单**。
    #   它与 scripts/drive-loop-nas.sh 是同一层的东西（NAS 侧入口），差别只在
    #   后者**已经**在生产跑、前者还没有。白名单的语义是「两边必须一致」——
    #   现在收进去，下次谁跑一次 `deploy.sh --apply` 就会把它推到生产，
    #   而它没有任何东西调用它 ⇒ 制造一个**假一致**（生产上有个看着像"在用的那套"
    #   的文件，而 DSM 任务调的其实还是 `drive-loop/run.sh`）。
    #   **先验，后进白名单**。验通过后的正确做法不是删掉这一行、而是：
    #   把它加进 deploy.sh 的 FILES，**并从本清单里移除**（两处必须同时改，
    #   只改一处就会被 B 方向当场报出来 —— 这正是这份清单存在的意义）。
    (r"^scripts/drive-loop-docker\.sh$",          "**草案**，未部署（#58 迁容器方案 B）；验通过后应进白名单并删掉本行"),
    (r"^prowlarr/\.gitkeep$",                     "占位符；生产的 prowlarr/ 是**不许碰**的"),
    (r"^scripts/(add-indexers|add-torznab-indexer|check-indexer-timestamps"
     r"|gen-datadirs|gen-nas-env-update|migrate-reseed-dirs|run-batch|wait-for-checks)"
     r"\.(py|sh)$",                               "在 Windows 上跑的工具/生成器（对着 NAS 的端口或 UNC 干活）"),
    # ==========================================================================
    # ★ 2026-09-17 本会话新增（`#83` / `#109` / `#58`）—— 判据同上一节：
    #   「只读 + 不回显凭据 + 只打聚合/白名单字段」；写工具则比照
    #   `scan-secrets.py` 那条先例（本机→生产的一次性操作，只在 Windows 上跑）。
    # ==========================================================================
    # #83 的替代品：列 Prowlarr 全部索引器的 id/name/enable。在 Windows 上跑；
    #   读 NAS .env 的 key 但**绝不打印、绝不上命令行**。
    #   ★ 只取**白名单三字段**（id/name/enable）—— 那个响应每条都带 `fields`
    #     （cookie/passkey），所以「取白名单」而不是「排除 fields」才是它的全部理由：
    #     黑名单挡不住 Prowlarr 将来新加的字段。
    (r"^scripts/prowlarr-indexers\.py$",         "只读列 Prowlarr 索引器 id/name/enable（在 Windows 上跑；只取白名单三字段）"),
    # #109 的写工具：换 NAS .env 里那条 key（PROWLARR_API_KEY + TORZNAB_URLS）。
    #   ★ 它是**写**工具，与上面几条「只读」不同 —— 但**仍在 Windows 上对着生产干活**：
    #     NAS 没有 SSH，所以「改 NAS 文件」只能在 Windows 做（同 scan-secrets.py 的形状）。
    #   安全闸：默认 dry-run、只改那两行、其余逐字节不动、写前备份、原子写；
    #   key **从文件读**（不走命令行 —— 会进 shell 历史与进程表）。
    (r"^scripts/rotate-prowlarr-key\.py$",       "换 .env 的 Prowlarr key（在 Windows 上跑；写工具，默认 dry-run + 备份 + 原子写）"),
    # #109 的写工具：换 cross-seed.db 的 indexer.apikey 列（4 行）。
    #   安全闸：默认 dry-run、先 PRAGMA integrity_check、写前备份、事务写 + 回读核对；
    #   ★ 另有一道**容器闸**（container_state）—— 查 docker inspect 的 State.Status，
    #     **unknown 一律不放行**（宁可要人确认，也不在"不知道"时写生产库）。
    (r"^scripts/rotate-crossseed-key\.py$",      "换 cross-seed.db 的 apikey 列（在 Windows 上跑；写工具，含容器闸 unknown 不放行）"),
    # #58 的挂载自证：三查（硬编码目录 / state.db 里的绝对路径 / .env 前缀）。
    #   ★ **它属于 #58，沿用 `drive-loop-docker.sh` 那条先例**：迁容器的东西**故意不进白名单**。
    #     白名单的语义是「两边必须一致」，现在收进去 ⇒ 下次 deploy.sh --apply 就把它推到生产
    #     ⇒ 制造**假一致**。**先验，后进白名单**（本会话已在本机验过正例+两反例，
    #     但**还没在 NAS 的容器里真跑过** ⇒ 仍不算"验通过"）。
    (r"^scripts/drive-loop-mount-selfcheck\.sh$","#58 挂载自证（未部署，先验后进白名单；本机验过正例+两反例）"),
    # #58 的镜像定义。★ 同上面那条：属于**迁容器**的东西，**故意不进白名单**
    #   （进白名单 = 下次 deploy.sh --apply 就推到生产 = 假一致）。
    #   ★ 它还有个**只有它才有的**理由：本仓的 docker build 上下文是**仓库根**，
    #     而 NAS 上的构建上下文是 **compose 目录** —— 两边的相对路径不同，
    #     直接拷过去也 build 不起来（`COPY scripts/…` 在 NAS 上找不到 orchestrator/）。
    #     ⇒ 真要上 NAS，得连构建方式一起设计，不是"加进 FILES"就完事。
    (r"^scripts/drive-loop\.Dockerfile$",        "#58 镜像定义（未部署；且本仓/NAS 的 build 上下文不同，不能直接拷）"),
    # ==========================================================================
    # ★ 2026-09-17 补登记**本来就在库里、却一直没登记**的 —— 哨兵这些天一直红着。
    #   而**「常红」等于「没有哨兵」**：天天红的东西没人看，真报出来的新漂移会被淹掉。
    #   这一批是文档与仓库本地小工具，与已登记的 README/SUMMARY/ENVIRONMENT 同类。
    # ==========================================================================
    # SUMMARY 的分章正文（2026-09-16 从 SUMMARY.md 拆出，`split-summary.py` 自验逐字节不变）。
    #   ★ 它们与 SUMMARY.md 是**同一份内容的两种装法** ⇒ 登记理由也相同（文档，不上 NAS）。
    (r"^summary/",                                "SUMMARY 的分章正文（文档；与 SUMMARY.md 同类，不上 NAS）"),
    # #115 现场验收的**只读**观察器：把 drive-loop.log 按批次切开算四件事，
    #   给**三值结论**（PASS/FAIL/WAIT）。只读 NAS 日志，不碰生产文件。
    (r"^tools/check-115\.py$",                   "#115 只读观察器（在 Windows 上跑；切批次给三值结论）"),
    # 看一眼「这个会话用了多少 context」——只读本地会话文件。
    (r"^tools/ctx\.py$",                         "只读本地会话文件（看 context 用量）"),
    # 把 SUMMARY.md 拆成分章的**一次性**工具；产物就是上面那些 summary/*.md。
    (r"^tools/split-summary\.py$",               "一次性拆分工具（在 Windows 上跑；产物是 summary/*）"),
    # 探 context 上限的只读探针。
    (r"^tools/probe-ctx-limit\.py$",             "只读探针（探 context 上限，在 Windows 上跑）"),
    # ★ 兜底：tools/ 下若再加新脚本，不必每次都回来改这里 ——
    #   **前提是它满足本目录的既有性质**（只读、不碰生产、不回显凭据）。
    (r"^tools/",                                  "仓库本地运维/文档小工具（在 Windows 上跑，只读）"),

]

# 受管、但**不在 git 里**的本地源（正常情况只有生成物）。没列在这里的会被 B 方向报出来 ——
# 「deploy.sh 会把它拷到 NAS，可它没有版本历史」这件事必须有人明确认过。
GENERATED_OK = {
    "scripts/nas-update-env.sh":
        "生成物（scripts/gen-nas-env-update.py 产出，故被 gitignore）；只带 DATA_DIRS/LINK_DIR 两个路径键",
}


def parse_deploy_files(text):
    """从 deploy.sh 解析 FILES 数组。返回 (entries, unparsed, err)。"""
    lines = text.splitlines()
    start = None
    for i, ln in enumerate(lines):
        if re.match(r"^\s*FILES=\(", ln):
            start = i
            break
    if start is None:
        return None, None, "deploy.sh 里找不到 `FILES=(` 这一行"

    entries, unparsed = [], []
    for ln in lines[start + 1:]:
        s = ln.strip()
        if s == ")":
            break
        if not s or s.startswith("#"):
            continue
        v = s
        if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
            v = v[1:-1]
        if "::" not in v:
            unparsed.append(s)          # 形如 `::` 的行却没给目的地 → 解析器坏了
            continue
        src, dst = v.split("::", 1)
        entries.append((src.strip(), dst.strip()))
    return entries, unparsed, None


def walk_nas(root):
    """返回 NAS 上的相对 POSIX 路径集合。"""
    out = set()
    for dirpath, dirnames, filenames in os.walk(root):
        rel = os.path.relpath(dirpath, root)
        for fn in filenames:
            out.add(fn if rel == "." else f"{rel}/{fn}".replace("\\", "/"))
    return out


def split_missing(dst, missing):
    """把「走查说 NAS 上没有」的目的地分成 (确实没有, 其实在)。

    ★ 单独提出来是因为这条判据**必须能被直接测**：它是整个哨兵里唯一可能产生
      假警报的地方（枚举只会漏文件、不会凭空造文件）。抽成纯函数才能在对照里
      构造"走查漏了、stat 却在"的场景 —— 真实 SMB 抖动复现不了。
    """
    gone, phantom = [], []
    for d in missing:
        (phantom if os.path.isfile(os.path.join(dst, *d.split("/"))) else gone).append(d)
    return gone, phantom


def print_cleanup_plan(dst, clutter_items):
    """把"杂物"整理成一份可直接执行的 `mv` 计划。

    ★ 三条硬约束，都是环境逼出来的：
      ① **只用 `mv`，绝不用 `rm`** —— 对 NAS 的 UNC 路径跑 `rm` 是明确禁止的
         （SMB 上没有回收站，glob 打错一次不可逆）。mv 是同文件系统内的 rename，
         原子且可逆，东西一件不少地进暂存区。
      ② **一次只搬一个显式路径**，不用通配符 —— 通配符 + 变量展开是这类脚本
         出事的经典姿势。
      ③ 整理完不留常驻文件在 NAS 上：暂存区是个**目录**，用户确认后
         在 NAS 上（或 DSM File Station，那边有回收站）一次删掉即可。

    ★ 搬的**单位**要挑最大的那层：`notify/probe-artifacts-*/` 底下 12 个文件
      是一条 mv（搬目录），不是 12 条；`__pycache__/` 同理。
      判据是"命中的那条规则是否以 `/` 结尾"—— 以 `/` 结尾的规则描述的是**目录**，
      于是把路径截到那次匹配的末尾，就是该搬的目录。
    """
    stamp = datetime.date.today().strftime("%Y%m%d")
    stage = f"_cleanup-{stamp}"
    units = set()
    for rel, rule in clutter_items:
        rx = rule[0]
        m = re.search(rx, rel) if rx.endswith("/") else None
        units.add(rel[:m.end() - 1] if m else rel)   # 去掉匹配末尾那个 `/`

    print(f"\n       ── 清理计划（--cleanup）：{len(units)} 项，全部 **mv** 到暂存区 ──")
    if not units:
        print("         没有杂物需要搬。")
        return
    print(f"         暂存区: {dst}/{stage}/")
    print(f"         下面 {len(units)} 项各自都是同一文件系统内的 rename（可逆、原子）。")
    print(f"         跑完确认无碍后，在 NAS 上删掉整个 `{stage}/` 目录即可。")
    print("         正在跑批次时不必等 —— 搬走的都是日志/备份/字节码，不在运行路径上。")
    print()
    print(f'         DST="{dst}"')
    print(f'         STAGE="$DST/{stage}"')
    print('         mkdir -p "$STAGE" \\')
    # 只对**去重后**的上级目录 mkdir，根目录下的则不生成（dirname 会给 "."）
    parents = sorted({os.path.dirname(u) for u in units} - {""})
    for i, p in enumerate(parents):
        tail = " \\" if i < len(parents) - 1 else ""
        print(f'           "$STAGE/{p}"{tail}')
    for u in sorted(units):
        print(f'         mv -- "$DST/{u}" "$STAGE/{u}"')
    print()
    print("         ★ 不要把这个计划里的任何一条改成 rm；要删请在 NAS 上删暂存区那一个目录。")


def resolve_dst(argv):
    for i, a in enumerate(argv):
        if a == "--dst" and i + 1 < len(argv):
            return argv[i + 1]
        if a.startswith("--dst="):
            return a.split("=", 1)[1]
    if os.environ.get("DST"):
        return os.environ["DST"]
    nasrc = REPO / "scripts" / ".nasrc"
    if nasrc.is_file():
        for ln in nasrc.read_text(encoding="utf-8", errors="replace").splitlines():
            s = ln.strip()
            if s.startswith("#") or "=" not in s:
                continue
            k, v = s.split("=", 1)
            if k.strip() == "DST":
                return v.strip().strip('"').strip("'")
    return None


def classify(rel, managed, rules):
    """→ (kind, rule)。rule 是命中的那条 (正则, 说明)，方便调用方知道**为什么**命中。"""
    if rel in managed:
        return "managed", None
    for rule in rules:
        if re.search(rule[0], rel):
            return "known", rule
    return "unknown", None


def main():
    argv = sys.argv[1:]
    show_all = "--all" in argv
    no_nas = "--no-nas" in argv
    cleanup = "--cleanup" in argv
    fail = 0

    # ---------- 0) 解析 deploy.sh（受管集合的唯一来源）----------
    if not DEPLOY.is_file():
        print(f"✗ 找不到 {DEPLOY}", file=sys.stderr)
        return 2
    entries, unparsed, err = parse_deploy_files(
        DEPLOY.read_text(encoding="utf-8", errors="replace"))
    if err:
        print(f"✗ {err}", file=sys.stderr)
        return 2
    if unparsed:
        print(f"✗ FILES 里有 {len(unparsed)} 行没解析出目的地（口径变了？）：", file=sys.stderr)
        for s in unparsed[:10]:
            print(f"    {s}", file=sys.stderr)
        return 2
    if len(entries) < 5:
        print(f"✗ FILES 只解析出 {len(entries)} 条 —— 明显不对，拒绝据此判定"
              f"（受管集合变空会把所有文件误报成「未知」）", file=sys.stderr)
        return 2

    managed = {d for _, d in entries}          # 生产侧相对路径
    local_managed = {s for s, _ in entries}    # 本地侧相对路径
    print(f"NAS 漂移哨兵（只读）   受管集合解析自 deploy.sh：{len(entries)} 条")
    dup = len(entries) - len(local_managed)
    print(f"  生产目的地 {len(managed)} 个 / 本地源 {len(local_managed)} 个"
          + (f"（{dup} 条是同一源部署到多个目的地，如 orchestrator/__init__.py "
             f"既进构建上下文又进 drive-loop/）" if dup else ""))

    # ---------- A 方向：NAS ----------
    if not no_nas:
        dst = resolve_dst(argv)
        if not dst:
            print("✗ 没有 DST（--dst / 环境变量 / scripts/.nasrc 三处都没找到）", file=sys.stderr)
            return 2
        print(f"\n[ A ]  NAS: {dst}")
        if not os.path.isdir(dst):
            print(f"✗ NAS 目录不可达（SMB 断了？）: {dst}", file=sys.stderr)
            return 2

        nas = walk_nas(dst)
        groups = {"managed": [], "unknown": [], "known": []}
        known_why = {}
        clutter_items = []           # [(相对路径, 命中的规则)]，只收"杂物"那几条
        alert_items = []             # 上面那批里**形似凭据泄漏**的（规则带 ALERT）
        for rel in sorted(nas):
            kind, rule = classify(rel, managed, KNOWN_NAS)
            groups[kind].append(rel)
            if kind == "known":
                why = rule[1]
                known_why.setdefault(why, []).append(rel)
                if CLUTTER.match(why):
                    clutter_items.append((rel, rule))
                    if is_alert(rule):
                        alert_items.append((rel, rule))

        clutter = {w: v for w, v in known_why.items() if CLUTTER.match(w)}
        n_clutter = sum(len(v) for v in clutter.values())
        n_alert = len(alert_items)
        n_known = len(groups["known"])

        print(f"       NAS 上共 {len(nas)} 个文件：")
        print(f"         ✓ 受管（在白名单里）        {len(groups['managed']):>6}")
        print(f"         ✓ 已知生产独有              {n_known - n_clutter:>6}")
        print(f"         ✓ 杂物（已知，但该清）      {n_clutter - n_alert:>6}")
        print(f"         ★ 形似凭据泄漏              {n_alert:>6}")
        print(f"         ★ 未知                      {len(groups['unknown']):>6}")

        # ★ 单列的理由：这些**不是杂物**，是凭据。和 `__pycache__` 共用一行计数
        #   就等于让「3 个杂物」这个数把真信号和噪音一起吞掉 —— 而 `.env` 的备份里
        #   装的是**真凭据**（见上面「已知生产独有」的 `.env` 那条）。
        #   于是这里既单列、又置 fail=1：它该让人**看一眼**，不该沉默地混在计数里。
        if alert_items:
            print(f"\n       ★★ 形似凭据泄漏 {n_alert} 个 —— NAS 上躺着 `.env` 的备份/变体：")
            for rel in sorted(r for r, _ in alert_items)[:20]:
                print(f"           {rel}")
            if n_alert > 20:
                print(f"           …（还有 {n_alert - 20} 个）")
            print("         → 里面是真实凭据。处理：在 **NAS 上**删掉，或先 `mv` 进暂存区"
                  "（`--cleanup` 会给计划）。")
            print("         ★ 本脚本的契约是只读：**绝不对 NAS 的 UNC 路径跑 rm**。")
            fail = 1

        missing = sorted(managed - nas)
        if missing:
            # ★ 复核「NAS 上没有」这个结论：SMB 枚举**偶尔会漏**文件 ——
            #   实测碰到过一次 exit=1，随后复跑 15 次却次次干净，文件集基线也纹丝不动(1322)。
            #   枚举只会漏、不会凭空造，所以唯一可能的**假警报**就是这条"白名单文件不见了"。
            #   于是这里不认一次快照：直接 stat 复核，stat 说在 → 那是"看不清"，不是"漂移"。
            gone, phantom = split_missing(dst, missing)
            if phantom:
                print(f"\n       ⚠ NAS 枚举**不完整**：{len(phantom)} 个白名单文件第一次没列出来、"
                      f"直接 stat 却在（例：{phantom[0]}）。")
                print("         这是 SMB 读取抖动，不是漂移 —— 本次**不做**「文件不见了」的判断，请复跑一次。")
                return 2
            print(f"\n       ⚠ 白名单里有 {len(gone)} 个目的地 NAS 上**不存在**"
                  f"（deploy.sh 会把它们标成 [新]）：")
            for d in gone:
                print(f"           {d}")
            fail = 1

        if groups["unknown"]:
            print(f"\n       ★ 未知文件 {len(groups['unknown'])} 个 —— "
                  f"既不在 deploy.sh 白名单、也不在 KNOWN_NAS 清单里：")
            for rel in groups["unknown"][:60]:
                print(f"           {rel}")
            if len(groups["unknown"]) > 60:
                print(f"           …（还有 {len(groups['unknown']) - 60} 个）")
            print("         → 三种可能，逐个定性：① 该收进 deploy.sh 的 FILES；"
                  "② 该加进本脚本的 KNOWN_NAS（并写清理由）；③ 该删。")
            fail = 1

        if show_all:
            print("\n       ── 已知生产独有 / 杂物 明细（--all）──")
            for why in sorted(known_why):
                v = known_why[why]
                print(f"         [{why}] {len(v)} 个")
                for rel in v[:8]:
                    print(f"             {rel}")
                if len(v) > 8:
                    print(f"             …（还有 {len(v) - 8} 个）")
        elif clutter:
            print("\n       ── 杂物（--all 看明细，本脚本**只报不删**）──")
            for why, v in sorted(clutter.items()):
                print(f"         [{why}] {len(v)} 个")

        if cleanup:
            print_cleanup_plan(dst, clutter_items)

    # ---------- B 方向：本地仓库 ----------
    print("\n[ B ]  本地仓库：已跟踪、但没进白名单 / 也没声明「不部署」的")
    try:
        # ★ 必须 `-c core.quotepath=false`，且**不能用 text=True**：
        #   git 默认把非 ASCII 路径转义成 `"\350\265\260..."` —— 一整串**纯 ASCII**，
        #   于是任何中文名的登记模式都**永远匹配不上**它。
        #   表现恰好是本脚本最该防的那种坏法：**登记了，但静默失效**
        #   （2026-09-12 自查发现：`^走过的弯路\.md$` 那条一直是死代码；
        #    该文件已于 2026-09-13 并入 ENVIRONMENT.md 并删除，那条规则随之移除 ——
        #    可**这个坑本身还在**：只要还有非 ASCII 的登记模式，就必须留着这两行防护）。
        #   关掉转义后 git 直接吐原始字节，所以显式按 utf-8 解码 ——
        #   别图省事用 text=True：Windows 上 locale 是 GBK，会把 UTF-8 路径解成乱码，
        #   比报假阳性更难查。
        r = subprocess.run(
            ["git", "-C", str(REPO), "-c", "core.quotepath=false", "ls-files"],
            capture_output=True, check=True)
    except (OSError, subprocess.CalledProcessError) as e:
        print(f"✗ git ls-files 失败: {e}", file=sys.stderr)
        return 2
    tracked = [f for f in r.stdout.decode("utf-8", "surrogateescape").split("\n") if f.strip()]

    rows = []
    for rel in tracked:
        if rel in local_managed:
            rows.append(("managed", rel, None))
            continue
        why = next((w for rx, w in LOCAL_ONLY if re.search(rx, rel)), None)
        rows.append(("local", rel, why) if why else ("unknown", rel, None))

    n_m = sum(1 for k, _, _ in rows if k == "managed")
    n_l = sum(1 for k, _, _ in rows if k == "local")
    n_u = sum(1 for k, _, _ in rows if k == "unknown")
    print(f"       已跟踪 {len(tracked)} 个文件：")
    print(f"         ✓ 会部署（在 FILES 里）     {n_m:>6}")
    print(f"         ✓ 明确不部署                {n_l:>6}")
    print(f"         ★ 未登记                    {n_u:>6}")

    # 受管、但不在 git 里的本地源：deploy.sh 照样会把它拷上 NAS，可它没有版本历史。
    # 生成物属于这一类，但要**逐条认过**才放行（见 GENERATED_OK）。
    untracked_src = sorted(local_managed - set(tracked))
    if untracked_src:
        declared = [s for s in untracked_src if s in GENERATED_OK]
        undeclared = [s for s in untracked_src if s not in GENERATED_OK]
        print(f"\n       ── 受管、但不在 git 里的本地源：{len(untracked_src)} 个"
              f"（deploy.sh 仍会拷，但无版本历史）──")
        for s in declared:
            print(f"         ✓ {s}\n             {GENERATED_OK[s]}")
        for s in undeclared:
            print(f"         ★ {s}   ← 没登记过：它凭什么不在 git 里？")
            fail = 1

    if n_u:
        print(f"\n       ★ 未登记 {n_u} 个 —— "
              f"`git push` 会把它们带走，但它们**不会**上 NAS：")
        for k, rel, _ in rows:
            if k == "unknown":
                print(f"           {rel}")
        print("         → 二选一：① 该上 NAS 就加进 deploy.sh 的 FILES；"
              "② 不该上就加进本脚本的 LOCAL_ONLY（写明理由）。")
        fail = 1

    if show_all:
        print("\n       ── 明确不部署 明细（--all）──")
        for k, rel, why in rows:
            if k == "local":
                print(f"           {rel:<52} {why}")

    # ---------- 结论 ----------
    print()
    if fail == 0:
        print("✓ 两个方向都干净：NAS 上没有未知文件，仓库里没有未登记的已跟踪文件。")
    else:
        print("★ 有需要人看一眼的东西（上面 ★ 标出的）。")
    return fail


if __name__ == "__main__":
    sys.exit(main())

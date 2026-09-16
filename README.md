# 大包拆包 · 单种保种工具链（v1）

把一个正在做种的**多合一大包**（如 `DouBan_IMDB.TOP250.Movies.Mixed.Collection.20240501.FRDS`），
**零磁盘开销**地让其中每一部单片，也在隔离的第三实例 `qbittorrent-reseed`(:3060) 上以**单种**做种。

```
大包(主QB做种)                   ┌──────────── Prowlarr(把你的PT站→Torznab) ──[可选]FlareSolverr
 /volume1/video/...              │  ▲ 搜索
        │  dataDirs               │  │
        ▼                         │  │
   cross-seed ───按内容匹配单种(名称→搜索→文件名+大小校验)───┘
        │  命中：在 linkDir 里按"单种发布名"建硬链接(零磁盘)
        ▼  注入 + 触发校验(recheck)
   qbittorrent-reseed :3060  ──校验通过→ 单种做种 ✅
        │
        ▼ (本次不做，已预留)
   IYUU 读 :3060 的 InfoHash → 扩散到更多站点
```

> **为什么不用 IYUU 起步**：IYUU 按 InfoHash 匹配，而单片"藏在大包这个整种里"，大包 InfoHash ≠ 任何单种，**IYUU 无法从大包引导出单种**。必须先用**按内容匹配**的 cross-seed 拿到"第一个单种"，之后才轮到 IYUU 扩散。

本次范围 = 做到"**单种在 :3060 成功做种**"。IYUU 扩散、别的大包，均**已预留接口**、本次不实现。

---

## ⚠ 免责声明与使用边界

> **先读这一节再往下。** 这套工具链会**自动建立链接、向 qB 注入种子**，
> 因此**可能改写你磁盘上的文件**（见「源文件被写穿」），也会**以你的身份向 PT 站发搜索**。
> 用之前请确认你清楚下面每一条。

### 本工具链**只**做什么

| ✅ 会做 | ❌ 不做 |
|---|---|
| 按内容匹配，**建立链接**（硬链接 / reflink）指向你**已有的**文件 | **不下载、不生成、不修改、不伪造**任何媒体数据 |
| 向 qB 注入 `.torrent` 并**触发 recheck** | **不参与**「这份数据到底对不对」的判断 —— 那是 qB 的 piece 校验 |
| 按**你给的站点和节奏**发 Torznab 搜索 | **不绕过**站点规则，**不伪造**进度 / 上传量 / 分享率 |

★ **一句话**：本项目是**搬运工**，不是**生产者**。它把"你手上已经有的"数据**换个目录再做一份种**
（判据是**字节一致**，见「原理 C」）—— **它没有任何一条代码路径能造出、或掩盖一份不存在的数据**。

### 「不完整做种」不是「假种」—— 判据是「**有没有骗人**」

| 维度 | ✅ 真种（完整做种） | ⚠ 不完整做种（缺种） | ❌ **假种** |
|---|---|---|---|
| qB 显示进度 | **100%** | <100%（常见 99.9%） | ★ **也可能显示 100%** |
| piece 校验 | **全部通过** | 有 piece **失败** | 数据与种子描述**根本不符** |
| 数据 | 与种子**逐字节一致** | **大部分正确**，缺的是少数 piece | 用**完全不同的**数据冒充 |
| 有没有骗人 | —— | **没有**（给出的有效数据是真的） | ★ **有** —— 故意提供与描述不符的数据 |
| 性质 | 正常做种 | **合法但不完整** | **欺诈** |

★ **两者的判据完全不同，别混着用**：
- 判「是不是**完整**做种」→ 看 qB 的**进度列**（任何 <100% 就是）；
- 判「是不是**假种**」→ ★ **进度不是判据**（假种可以显示 100%）—— 要看**数据来源是否可信**。

> ★★ **本项目可能产生「不完整做种」，但永远不会产生「假种」** —— 这两个词在本项目里
> **必须分开用**。「不完整」是**上游 partial 匹配的已知副作用**（见下）；
> 「假种」是**人的行为**，本项目既不提供、也不容忍。

### 本项目的产物**确实**是「不完整做种」—— 这是已知且有实测的

cross-seed 的 `partial` 匹配会把「**名称+大小匹配、但 piece 哈希不一致**」的单种也注入 qB；
qB recheck **不通过时不报错**，而是**就地重下**那几个 piece。上游文档把这个现象写成正常行为：

> Nearly all partial matches recheck to **99.9%** rather than 100% *(expected due to piece hashing)*

★ **它的危害不是"假"，是"占位不产出"**：这类种子**不产生上传量**，
长期挂着会踩站点的 **HnR（做种时长 / 分享率不达标）** —— 那是**你**的账号风险。
**本项目已把闸门关上**（`matchMode` ⇄ `linkType` 结构性互锁：只有 reflink 才许 partial），
**但改动前已建的存量仍在**，见「源文件被写穿」第 2 步。

### 你**自负**的后果

| 事项 | 说明 |
|---|---|
| **站点规则** | 多站重复做种是否允许、HnR 怎么算、分享率怎么保 —— **各站规则不同，本项目不替你判断** |
| **搜索压力** | 每站 **14 天一轮**的机器人流量（见「原理 B」）—— 这是**设计时就知道的代价**，请用对方站点的规则去衡量它 |
| **磁盘占用** | reflink 重下分离出的块**要占真实空间**；本项目这块 `/volume1` **已用满 100%** |
| **数据不可逆** | 被写穿的文件**无备份可恢复**（本项目已实测：`net view` 无任何备份共享、4 处 `#snapshot` 全不存在）⇒ 只能**回站点重新下** |
| **凭据** | PT 站凭据**只进 Prowlarr**，不进本仓库；泄了是你自己的运维问题 |

> ★★ **若你打算用它做「假种」、刷流量、或拿别人的数据冒充 —— 请立刻停手。**
> 本项目**没有**、也**不会**提供这类能力。任何以此为目的的使用**与作者无关**，
> 后果**由行为人自负**；也请勿据此向作者追责。

---

## 我要做什么 → 看哪节

| 我想… | 看哪节 |
|---|---|
| **我要拿去用了 —— 先看责任边界** | **⚠ 免责声明与使用边界**（只搬运不生产 · 真种/不完整/假种的**分野** · 你自负的后果）|
| 搞清这东西干嘛的 | 上面这段 + **目录结构** |
| **搞清「包」是怎么被认出来的 / 搜索压力从哪来** | **原理技术和风险须知**（包是**声明**的不是识别的 · 压力来自**分母** · 风险清单）→ SUMMARY §19 |
| 从零部署一台 | **部署步骤**（Phase 0→3，每步可独立验证）+ **验证清单** |
| **动手前：这件事现在允许做吗 / 改动检查过了吗** | **开工前的两道门** ← 动作→允许条件表 + 9 格改动前自检 |
| 跑起来 / 继续跑 | **当前状态与下一步** ← 最常用，先看这个 |
| **新会话开局 / 不了解这台机器** | **`ENVIRONMENT.md`** ← 环境前提 + 按症状 grep 的 `ERR-*` 条目（含全部 20 项技术弯路）|
| 我卡住了（报错 / 搜不到 / 不动了） | **常见问题** + **交接必读的坑** → `ENVIRONMENT.md` 的 `ERR-*`（按症状检索）|
| **想从电脑上手动跑点什么** | **⛔ 电脑端已不参与** ← 电脑只剩诊断用途：`deploy.sh`（推代码）、`check-deploy-drift.py`（查漂移）、`scan-secrets.py`（推前扫凭据）、`audit-found-*.py`（对账 `Found` 行） |
| **想知道 NAS 上有没有我不知道的文件** | **漂移哨兵** ← `python scripts/check-deploy-drift.py` |
| **想推代码，但怕把密钥一起推上去** | **推前凭据扫描** ← `python scripts/scan-secrets.py`（绿了再 `git push`） |
| 加站 / 换站 | **多站点** → SUMMARY §13.3（完整流程，可复用） |
| 让它出事了主动通知我 | **通知 / 告警（NAS 侧发信）** |
| **下一步该做什么** | **当前状态与下一步** 的「🔴 下一步（按优先级）」 |
| 下一步还能自动化什么 | **还没做** 第 7 条 → **SUMMARY §16**（四条预案 + **两条前提被推翻**） |
| **判「能不能建硬链接」/ 某共享在哪个卷 / 某共享 SMB 里「看不见」** | **SUMMARY §23**（`docker_ssd ∈ /volume2` 的双来源复核 · ★★ **`stat -c %d` 只在 NAS 侧成立**，Windows/SMB 侧零分辨力 ⇒ 对照量用 `df` · **枚举 ≠ 全量**）· 判据本体在 `ENVIRONMENT.md` 的 `A.3` |
| 状态机说没做种、qB 里明明在做种 | **常见问题** → **SUMMARY §17.5.1**（已修） |
| 接手这个项目 | **当前状态与下一步** → **SUMMARY §13**（全过程 + 坑单）→ **§13.11**（最新进度与唯一待办） |

> **三份文档怎么分工**（照日志分级来）：
> **README = INFO 层**（操作手册：命令、步骤、症状→解法）；
> **SUMMARY = DEBUG 层**（完整过程、踩坑、决策理由）；
> **`ENVIRONMENT.md` = 检索层**（环境前提 + 每条坑一个 `ERR-*` 可检索 ID，**不承担事实源**）。
> 同一事实**只在一处维护**，跨层用「详见 SUMMARY §N」单向指路 —— 防止两边漂移。
> ★ `ENVIRONMENT.md` 是**索引**，不是第三个事实源：与 README / SUMMARY 冲突时，以那两份为准。
> ★ 原 `走过的弯路.md`（20 项技术弯路）已于 2026-09-13 **全部并入 `ENVIRONMENT.md` 并删除**，
> 文件名不再存在；要按历史编号找，用 `grep -n '弯路 #' ENVIRONMENT.md`。

---

> **占位符约定**：为便于公开分享，文档与脚本里的真实主机名 / 内网 IP / 私有站名
> 已替换为 `YOUR-NAS`、`NAS_IP`、`SiteA`、`SiteB`。照着做时请换成你自己的。
> 脚本没有硬编码这些值 —— `scripts/run-batch.sh` 与 `deploy.sh` 读环境变量，
> 或读 `scripts/.nasrc`（已 gitignore）。完整对照表见 SUMMARY.md §0。

---

## 目录结构

```
prowlarr_cross-seed_autohardlink/   # NAS 部署目录（compose 就放这里，./ 即指它）
├─ docker-compose.yml     # prowlarr + (flaresolverr可选) + cross-seed + reseed-orchestrator
├─ .env                   # 由 .env.example 复制而来；IP/密钥/路径/开关（单点维护）
├─ .env.example
├─ cross-seed/
│  └─ config.js           # cross-seed 配置（从 .env 取值；含版本免责说明）→ 挂进 /config
├─ prowlarr/              # Prowlarr 配置目录（首次启动自动写入）→ 挂进 /config
├─ hlink/
│  ├─ config.yml          # ★大包任务 + 全局设置（你主要编辑这个）→ 挂进 /config
│  └─ state.db            # ★状态机运行时库（自动生成，勿提交）
├─ orchestrator/          # 编排器(Python, 仅依赖 PyYAML) 源码 + Dockerfile：预检/驱动/汇报
│  └─ state.py            # ★单片状态机（sidecar 库，只读 cross-seed/qB，见「扩展」）
├─ patches/reseed-qbit.conf.md   # Phase 0：:3060 需改的配置项（参考文档）
├─ ENVIRONMENT.md         # ★环境前提与坑手册（检索层：A 部分前提 + B 部分 `ERR-*` 条目）
└─ README.md
```

> 开发仓库里另有 `scripts/`（`run-batch.sh` 抽样脚本、`reseed-state.py` 状态机 CLI、
> `drive-loop.py` 自动续跑、`add-indexers.py` 加站、`gen-datadirs.py` 生成嵌套包的 `DATA_DIRS` 片段、
> `build-farm.sh` 构建硬链接农场〔NAS 本机**或** Windows 经 SMB 都能跑，见「扩展 → 硬链接农场」〕、
> `migrate-reseed-dirs.py` 目录搬迁（qB `setLocation`）+ `wait-for-checks.py` 等它校完
> 〔2026-09-12 新增，见 SUMMARY §18〕、`add-torznab-indexer.py` 往生产 `.env` 加索引器
> 或摘索引器（`--remove`，换站用〔apikey 从同文件现有条目**原样抄**，不经过人眼〕）、
> `check-indexer-timestamps.py` **只读**查「哪个站真的搜出去过 + 到底有没有在被限流」
> 〔加站流程第 ③ 步的闸门，见 SUMMARY §18.11〕、
> `prowlarr-indexerstatus.py` **只读**查「Prowlarr 是不是**在本地禁用**某个站」
> 〔`ERR-SVC-17` 里三种限流机制的分辨器，与上一条是**一对**：一条看 Prowlarr 侧、
> 一条看 cross-seed 侧；key 从生产 `.env` 读、**绝不打印**，站名只取
> `cross-seed.db` 的 `id`/`name` 两列〕、
> `check-deploy-drift.py` **只读**的**漂移哨兵**（NAS 上有没有没登记的文件 / 仓库里有没有
> 该部署却没进白名单的文件，见「漂移哨兵」一节，SUMMARY §18.14）、
> `scan-secrets.py` **只读**的**推前凭据扫描**（按值的形状找漏进仓库的 cookie / apikey /
> passkey，见「推前凭据扫描」一节，SUMMARY §18.15）、
> `audit-found-lines.py` / `audit-found-resolve.py` **只读**的两道**对账**
> （`Found` 行：a−b 验「抓到的形状 = 正则认的形状」，b−c 验「抓到的行真的落到了某个单片」；
> 直读 NAS 的 `info.current.log` 与 `state.db`〔后者 `query_only` 硬闸〕，见 SUMMARY §18.18）、
> `sa-volume-usage.py` **只读**群晖 Storage Analyzer 的报告
> 〔内存里解 zip、不落盘、无凭据；它留着的是**一句否定结论的证据** ——
> 报告里**没有可用空间**，见 SUMMARY §22 与「🔴 下一步」第 14 条〕。
> 其余工具要么跑在 NAS 上，要么是**手动**用的（不必进容器）。
> ★ 2026-09-12 起电脑端只留 **`deploy.sh`**（推代码）、**`check-deploy-drift.py`**（查漂移）、
> **`scan-secrets.py`**（推前扫凭据）、**`audit-found-*.py`**（对账）、
> **`prowlarr-indexerstatus.py`** / **`check-indexer-timestamps.py`**（查限流是哪一种）几个用途，
> 见「⛔ 电脑端已不参与」。
> `tests/` 是**离线自测** —— ★ **脚本数与断言数只维护在 `tests/README.md`，别在这里抄第二份**
> （抄过一次就漂了：这里曾写「13 个脚本 / 431 条断言」，而 2026-09-14 实测已是 **21 / 757**）。
> 原先散在 `D:/tmp` 里**没有版本管理**，2026-09-12 搬进仓库。不联网、不碰生产、不碰真库，
> `python tests/<名字>.py` **任一 cwd** 都能跑（路径按 `__file__` 解析），全过退出码 0。
> 见 `tests/README.md`。
> 由状态机导出的 `unmatched.tsv` /
> `todo-paths.txt` 属运行时产物，已 gitignore。

三大服务的配置目录一一对应：`prowlarr/`→Prowlarr、`cross-seed/`→cross-seed、`hlink/`→编排器。
`.env` 是**唯一密钥/IP/路径来源**：`hlink/config.yml` 用 `${VAR}` 引用它，`cross-seed/config.js` 从环境变量读它。三处保持一致，只需改 `.env`。

> 注意区分：`hlink/` 只放编排器的**配置/日志**；真正的硬链接（做种数据）在 `.env` 的 `LINK_DIR`（须在 `/volume1/video` 下，与大包**同卷**，不是 `docker_ssd`）。

---

## 开工前的两道门（动手前必读）

> 这一节是**闸**，不是资料 —— 它只回答两个问题：**这件事现在允许做吗**、**这个改动检查过了吗**。
> 每条的判据本体在 `ENVIRONMENT.md`（动作边界 `A.2`、判据约定 `A.11`，与对应的 `ERR-*`；按症状 grep）—— 这里只是把它收成一张动手前扫一眼的表。

### ① 动作 → 允许条件

**`批次间隙`** = `.drive-loop.state` 的 `running_pid` 为 `null`。

| 动作 | 允许条件 |
|---|---|
| 只读 SMB / 只读 HTTP 端口 | 任何时刻 |
| `deploy.sh --apply` | 批次间隙（它会覆盖正被 `sh` 读的脚本）|
| `docker compose up -d --force-recreate` | 批次间隙 **+ 该重建确有必要** |
| 改 `.env` 的 `DATA_DIRS` / `LINK_DIR` | 用 `gen-nas-env-update.py` 生成脚本，**不手敲** |
| `build-farm.sh --apply` | 批次间隙（要写 NAS）|
| 手动 `rm` NAS 上的东西 | 只走 `rm-staging.sh`（有闸），**绝不 `rm` UNC 路径** |
| qB 的 `setLocation` | **一站一批**（按 `save_path` 分组、一批一次调用），且种子不在在途状态 |

**在途状态**（`migrate-reseed-dirs.py` 的 `IN_FLIGHT_STATES`）：`checkingDL` / `checkingUP` / `moving` / `allocating`。

> ★ **`running_pid` 是快照，不是窗口** —— 它 `null` 只说明**这一刻**没在跑，**不说明能安全多久**。
> 循环每 15 分钟醒一次（`last_sleep_sec` 常见 `10800`）⇒ **窗口长度要看它，不是看这一刻**。
> ★ 状态文件在 **NAS** 上（`<compose>/drive-loop/scripts/.drive-loop.state`），**不在本机仓库里** ——
> 本机看不到它，就别假装读过。

### ② 改动前自检（9 格，逐格填，不许"全绿了就算过"）

```
□ 这个改动落在哪一层？（构建上下文 / NAS 宿主机 / 容器内）
□ 需不需要 deploy / --build / --force-recreate？
□ 期望值的另一侧是谁？能指回哪条真实记录？
□ 阴性对照做了吗？打断代码测试会红吗？
□ 部署窗口对吗？批次在跑吗？
□ 回读证据准备好了吗？（md5 / 符号 grep / docker inspect）
□ 有没有把"没查到"写成"查到了没有"？
□ 有没有构造出"看着合理其实无意义"的数？（`.get() or 0`）
□ 这份输出会不会在别处被照抄？（措辞一旦成断言就成假事实）
```

★ 最后一格有**凭据版**：脱敏要按**值形状**兜底 —— `apikey=` 会出现在 URL 的**值**里，
按**键名**兜不住；`cut -c1-N` **不是**脱敏。

---

## 部署步骤（分阶段，每步可独立验证）

> 前置：把本目录内容整个放到 NAS 部署目录 `/volume2/docker_ssd/prowlarr_cross-seed_autohardlink`，`cd` 进去执行下述命令。
> `cp .env.example .env`，然后编辑 `.env`：至少填 `NAS_IP`、`CROSSSEED_API_KEY`、确认 `DATA_DIRS`/`LINK_DIR` 路径。
> 确保 `LINK_DIR` 与 `DATA_DIRS` **在同一物理卷**（都在 `/volume1/video` 下即可）。

### Phase 0 — 修 `:3060`
按 [`patches/reseed-qbit.conf.md`](patches/reseed-qbit.conf.md)：停容器→备份 conf→改 BT 端口 56883、开局域网免密白名单、关 DHT/PeX/LSD、关队列、注入不暂停→启容器。
验证：`curl http://<NAS_IP>:3060/api/v2/app/version` 免密返回版本号。

### Phase 1 — Prowlarr 加站
```bash
docker compose up -d prowlarr flaresolverr   # 不需要过CF可省略 flaresolverr
```
1. 打开 `http://<NAS_IP>:9696`，把目标 PT 站加进 Indexers（填各站 cookie/passkey/API；中文站若卡 Cloudflare，在 Settings→Indexers 里配 FlareSolverr = `http://flaresolverr:8191`）。
2. 每个站页面找 **Torznab Feed / API** 的地址与 apikey，拼进 `.env` 的 `TORZNAB_URLS`（逗号分隔），如
   `http://prowlarr:9696/1/api?apikey=xxxx,http://prowlarr:9696/2/api?apikey=yyyy`。
3. 在 Prowlarr 里对**一部电影名**手动搜一下，确认至少一个站能出结果（这步验证站点可搜性）。

### Phase 2 — cross-seed 试点（关键闸门）
```bash
docker compose up -d cross-seed
docker compose logs -f cross-seed        # 看有无 "unknown option" 等版本键名报错
```
先对**大包里 1~2 部电影**手动触发匹配（把 `<某电影目录>` 换成 `DATA_DIRS` 下真实子目录）：
```bash
curl -XPOST http://<NAS_IP>:2468/api/webhook \
  -H "X-Api-Key: <你的 CROSSSEED_API_KEY>" \
  --data-urlencode 'path=/volume1/video/download/movies/DouBan_IMDB.TOP250.Movies.Mixed.Collection.20240501.FRDS/<某电影目录>'
```
> webhook 路径/参数名随 cross-seed 版本略有差异；若 404/400，见 `cross-seed/config.js` 顶部说明与官方文档，并对照 `orchestrator/crossseed_client.py` 的注释调整。

验证（[验证清单](#验证清单)）：`linkDir` 下出现该电影的硬链接、且 `:3060` 里该单种在校验后做种。
**若中文站匹配率过低**，问题会在这里暴露 → 换站 / 加 FlareSolverr / 调 `MATCH_MODE`，再决定是否全量。

### Phase 3 — 编排器（我们的程序）
```bash
docker compose build reseed-orchestrator
docker compose run --rm reseed-orchestrator preflight                       # 只读预检
docker compose run --rm reseed-orchestrator run --job frds-top250-2024 --dry-run  # 只枚举不触发
docker compose run --rm reseed-orchestrator run --job frds-top250-2024      # 正式：逐单片触发→注入→等待
docker compose run --rm reseed-orchestrator status                          # 按分类汇总做种状态
```
编排器做：安全预检（源存在/同卷/单片枚举）→ 逐单片驱动 cross-seed → 轮询 `:3060` 汇报"哪些单片已做种 / 未匹配到"。

---

## 验证清单

1. **Phase 0**：`curl .../api/v2/app/version` 免密返回版本；`nc -vz <NAS_IP> 56883` 通。
2. **Phase 2/3**：硬链接生效（删单种不伤大包）——
   ```bash
   ls -l "<LINK_DIR>/<某电影>"/*.mkv   # 链接计数(第2列)应 ≥ 2
   ```
   且 `:3060` 该单种进度 100%、状态为做种（`status` 子命令里计入 `seeding`）。
3. **全量后**：编排器报告的做种数与 `:3060` 分类 `reseed-singles` 实际数量一致。

---

## 常见问题

- **中文站搜不到 / 结果为空**：Prowlarr 里该站是否需要 FlareSolverr？passkey/cookie 是否过期？先在 Prowlarr 手动搜确认；再考虑放宽 `MATCH_MODE`。
- **命中率低、有些片子搜不到**：正常。**单站（sitea）已搜部分实测命中率约 50%**
  （87 部里 44 部；详见 SUMMARY §5.3）。想提高就**加索引器**，见下方「多站点」。
  当前匹配/未匹配的完整清单见 `scripts/unmatched.tsv`。
- **跑完一轮但感觉"漏了很多"**：先看进度条是不是 `(N/总数)` **一次性从某个数跳到总数** ——
  那不是跑完了，是**索引器被退避、剩下的条目被秒跳**了（cross-seed 跳过不排队）。
  去 Prowlarr 日志确认该站真实状态码：`500/502/520/522` = 站点侧故障，等它好了**重打一次根目录 webhook** 续跑；
  只有真 `429 + Retry-After` 才需要把 `delay` 往上调。详见 SUMMARY §5.3 / §6.5。
  **别靠肉眼判断漏了哪些** —— 用下面的状态机，它会精确列出"该搜但没搜"的清单。
- **某部片子确认没匹配上，怎么处理**：多半是**站点上还没有这个单种**（或只有别的分辨率/压制组），不是配置问题。
  **不要反复重打 webhook** —— cross-seed 有搜索缓存，短期内重复打基本是白打，还可能撞上 Prowlarr 的失败退避。
  正确做法：让它留在 `scripts/unmatched.tsv` 里，用 cross-seed 的 `searchCadence` + `excludeRecentSearch`
  做**低频自动重扫**（例如每周扫一轮、同一部 3 天内不重复搜）。等哪天有人发了对应单种，下一轮自然就命中了。
- **注入后一直"校验中"或校验失败**：单种发布名/文件大小与你的数据不完全一致属正常（换一个匹配结果）；确认 `LINK_DIR` 与源**同卷**、`/volume1/video` 已 1:1 挂进 cross-seed 与 `:3060` 两个容器。
- **cross-seed 启动报 `unknown option`/键名错误**：版本键名差异，按 `cross-seed/config.js` 顶部说明与官方文档改键名。
- **外网连不上 / 上传为 0**：路由器 56883 的 **TCP 和 UDP** 都要转发；确认 conf 三处端口都是 56883。
- **`drive-loop` 报「有 N 个 active 索引器拉不到名字（prowlarr#3）」**：
  这是**索引器拉的 caps 失败**（名字来自站点 caps，取不回来就没名字），
  `#N` 就是 `TORZNAB_URLS` / `/N/api` 那个号，**不是 Prowlarr 界面序号**。
  先去 Prowlarr 看这站还在不在、是否被禁用 —— 多半又是「`.env` 删了站但容器没重建」
  （见上面「交接必读的坑」），重建即可。SUMMARY §13.11 记了这个标签曾经写错的 bug。
- **`:3060` API 403**：白名单网段没覆盖来源 IP（改 `WebUI\AuthSubnetWhitelist`），或应改用 `QBIT_AUTH_MODE=password`。
- **`drive-loop` 回灌打出 `新增做种 -26`（负数）/ qB 里明明在做种，状态机却写 `MATCHED` 或 `UNMATCHED`**：
  状态机的 `SEEDING` 是**推导**出来的 —— `seeding_count = |matched_hashes ∩ qB 的 hash|`
  （`orchestrator/state.py:963`）。**`matched_hashes` 一空，stage 就必然降级**，跟 qB 通不通无关。
  **先别怀疑 qB**，直接两边数一下对照：
  ```bash
  curl -s "http://NAS_IP:3060/api/v2/torrents/info?category=reseed-singles" \
    | python -c "import sys,json;print('qB 在做种:',len(json.load(sys.stdin)))"
  python -c "
  import sqlite3;c=sqlite3.connect(r'//YOUR-NAS/.../drive-loop/hlink/state.db')
  print('状态机认的:', c.execute('SELECT COUNT(*) FROM movie WHERE seeding_count>0').fetchone()[0])"
  ```
  ★ **补救（幂等、不发任何站点请求）**：补跑一次带 `--qbit-url` 的 `sync`。
  ✅ **2026-09-12 上午已定位并修复**：真根因是 **v3 农场切换后 cross-seed 报的是农场路径**，
  而 `pack.roots` 还是原路径 → searchee 全被判成「别的包」**静默跳过** → `matched_hashes` 空。
  修法（`pack.farm_root` 列 + `reseed-state.py farm` 子命令）与验证（**`SEEDING` 21 → 201**）见 **SUMMARY §17.5.1**。
  ⚠ 光补跑 `sync` **治不了这个** —— 实测只从 13 回到 21。当时的误判过程见 §17.3。
- **`backoff_hits` 一直是 0，但索引器状态明明是 `RATE_LIMITED`**：
  检查间隔（`--check-every` × `--interval` = 10 × 30s = **300 秒**）**比实测的退避窗口（30~60 秒）还长**，
  窗口整段落在两次检查之间 → 既不等待也不计数。
  ✅ 已修：加 `--backoff-check-secs`（默认 60）**按秒**触发检查，并按 `retry_after` 变化认定「新发生了一次退避」。
  ★ 连带修掉一个更隐蔽的：`next_sleep()` 的在 `--once` 模式下**压根没接线**（结论只进日志），
  所以「站点在退避就缓一缓」这条策略**从来没生效过**。见 **SUMMARY §17.5.2~§17.5.4**。
- **`attempts.log` 里出现 `exit=127 (no python: /usr/bin/python3)`，但同一批的 python 明明跑完了**：
  **那是假象** —— `deploy.sh` 曾在脚本**运行中**覆盖它（`sh` 边读边执行，会从旧偏移读到新内容）。
  `deploy.sh` 已改成**原子替换**（写 `.new` 再 `mv`，换 inode），并在检测到批次在跑时给出告警。
  判据：**同一次 `start` 没有配对的 `exit`** 时，先怀疑"脚本被换过"，别急着信那个退出码。详见 **SUMMARY §17.2**。

---

## 扩展

### 多站点 —— 提高命中率的唯一手段

单站（sitea）已搜部分实测命中率约 **50%**，加站能把剩下那 50% 里的一部分也捞回来：

1. Prowlarr（`http://<NAS_IP>:9696`）→ Indexers → Add Indexer，把其它 PT 站加进来。
   > cookie / passkey / API **只在 Prowlarr 网页里填**，绝不写进任何文件、聊天或命令行。
2. 记下每个站的 **indexerId**（索引器详情页 URL 里的数字，如 `/indexer/3` → id=3）。
   > ⚠ **这个数字会变** —— 删站再重加，ID 往往就换了。**每次增删索引器后都要重新核对**：
   > ```bash
   > curl -s -H "X-Api-Key: <Prowlarr API key>" http://<NAS_IP>:9696/api/v1/indexer \
   >   | python -c "import sys,json;[print(i['id'], i['name']) for i in json.load(sys.stdin)]"
   > ```
   > 详见 SUMMARY §6.6。
3. 把它的 Torznab 地址追加进 `.env` 的 `TORZNAB_URLS`，**逗号分隔、单行**（`scripts/add-indexers.py` 已自动化这步，会自动补 `/api`、只改一行、自动备份）：
   ```
   TORZNAB_URLS=http://prowlarr:9696/2/api?apikey=<Prowlarr API key>,http://prowlarr:9696/3/api?apikey=<同一个 key>
   ```
   > 用的是 **Prowlarr 自己的 API key**（所有条目共用同一个），不是各站的 passkey。
4. 重建 cross-seed 让新 env 生效 —— **必须 `--force-recreate`，`restart` 不够**（见下）。
5. 在 Prowlarr 里对一部电影手动搜一下，确认新站能出结果。
6. **加完站要重跑一轮全量**：对 `DATA_DIRS` 的**根目录**打一次 webhook（见 SUMMARY §6.4），
   cross-seed 会把整包重新遍历一遍。已经命中的会被跳过，只有没命中的才有机会被新站捞到。

> ⚠ **`docker compose restart` 不重新注入环境变量** —— 改了 `TORZNAB_URLS` / `DATA_DIRS` 后
> 必须 `sudo docker compose up -d --no-deps --force-recreate cross-seed`
> （`--no-deps` 防连带重建 Prowlarr）。完整加站流程见 **SUMMARY §13.3**。
>
> ⚠ **只在 Prowlarr 里禁用索引器 ≠ cross-seed 不搜它** —— cross-seed 只认自己的
> `TORZNAB_URLS`，会继续请求已禁用的站，每搜一次吃一个 `HTTP 410` 并 snooze。
> **彻底停用某站必须把它从 `TORZNAB_URLS` 移除**再重建（SUMMARY §13.6 坑 5）。

**对站点友好**：`delay` 保持 30~45；Prowlarr 每个站的 **Query Limit 只当保险丝**（设成明显高于实际用量的值，如 1000/天），
不要拿它当节流阀。加站**不会**增加单个站的查询量 —— 一次搜索由 Prowlarr 分发到各站各一次。

> ★ 「定期人工看额度」这件事**能自动化到什么程度、哪里是天花板**（站点真实余额
> Prowlarr 根本不知道），见 **SUMMARY §16.1**。

> **怎么判断某个站要不要 FlareSolverr**：在 Prowlarr 里手动搜一下。
> 看到 `403` + 挑战页 HTML / 日志里出现 `Cloudflare` → 需要；
> 看到 `500/502/520/522/timeout`（站点后端挂了）或 `429`（限流）或能正常返回结果 → **不需要**。

> ⚠ **Cloudflare**：中文 NexusPHP 站常需要 FlareSolverr。真要给某个站启用，做法是
> **在 Prowlarr 里给那个站挂一个名为 `flaresolverr` 的 tag**（Prowlarr 按**索引器挂 tag**
> 启用，**没有全局开关** —— 「Settings → Indexers 里填个 URL」这个说法是错的）。
>
> ★ **「从 GHCR 拉镜像失败」那条已经过时**：SUMMARY §7 记的是**早期**的情况；2026-09-12
> 那次 `up -d` 已经把 `ghcr.io/flaresolverr/flaresolverr:latest` 成功拉了 12 层，
> 现在容器跑的就是它。`compose.yaml` 里的镜像名**不用**换成 Docker Hub 那个。
>
> ★ **现状（2026-09-12 17:15 实测）：FlareSolverr 装了、容器在跑（v3.5.2、健康），
> 但一次都没被用上** —— Prowlarr 的 tag 列表是**空的**，四个索引器**一个 tag 都没挂**。
> 而且现在**四个站都不需要它**。判定见 SUMMARY **§18.12**。

### 单片状态机（已实现）—— 记录每部片子走到哪一步了

cross-seed **不会排队、不会重试**：索引器被退避时，待搜索项直接跳过
（2026-09-11 有 295 条就这么消失了，见 SUMMARY §5.3）。
所以补了一个 sidecar 状态库，把每部片子的阶段记下来，**已完成的阶段不重复，被跳过的阶段必须补上**。

```bash
PACK=frds-top250-2024
N=//YOUR-NAS/docker_ssd/prowlarr_cross-seed_autohardlink

# ★推荐：根清单从 .env 派生（首选 FARM_SOURCES；缺席时退回 DATA_DIRS）
python scripts/reseed-state.py init --pack $PACK --depth 2 \
  --roots-from-env .env --match "DouBan_IMDB" --exclude "0观影清单*"
python scripts/reseed-state.py sync --pack $PACK \
  --db-path "$N/cross-seed/cross-seed.db" \
  --log "$N/cross-seed/logs/info.current.log" --log "$N/cross-seed/logs/verbose.current.log" \
  --qbit-url http://NAS_IP:3060 --indexer-alias "http://prowlarr:9696/1/api=SiteB"
python scripts/reseed-state.py report --pack $PACK
python scripts/reseed-state.py todo  --pack $PACK --indexers SiteA,SiteB --out scripts/todo-paths.txt
python scripts/reseed-state.py drive --pack $PACK --indexers SiteA,SiteB --limit 50 --apply \
  --url http://NAS_IP:2468 --api-key <CROSSSEED_API_KEY> --db-path "$N/cross-seed/cross-seed.db" \
  --qbit-url http://NAS_IP:3060
```

**`init` 的根怎么给** —— 推荐**从 `.env` 派生**（`--roots-from-env .env --match "<路径关键词>"`）：
它读的是 `.env` 的 **`FARM_SOURCES`**（v3 之后的**源清单**；切换前那份源目录写在 `DATA_DIRS` 里，
所以 `FARM_SOURCES` 缺席时会退回 `DATA_DIRS` —— 与 `build-farm.sh` 同一种顺序）。DC 那种
47 个根的包也一行搞定。另有显式 `--root/--local-root`（可重复、**必须按序一一对应**）用于单根包。
`--match` 可重复（OR），`--unc-host //YOUR-NAS` 把 NAS 路径翻成 UNC（不给则试着从
`scripts/.nasrc` 的 `NAS_NAME` 推断），`--nas-prefix` 默认 `/volume1`。
完整参数与多根用法见 SUMMARY §10.6。

> ⚠ **`--depth` 必须与 cross-seed 的 `maxDataDepth` 完全一致**（本项目未显式配置 ⇒ 默认 2）。
> 它是"从 dataDir 往下数几层"，第 1..N 层的**目录和视频文件**都算 searchee。
> 对不上就会出现"状态机有、cross-seed 没有"的幽灵条目，或漏掉真在搜的片子。详见 SUMMARY §10.6.1。

**分批**：`--limit N` 每批 N 条，`--batch K` 指定第几批，`--plan` 只打印计划不发请求。
因为待办清单**已排除已做种的片**、且按 `SKIPPED → ERROR → PENDING → UNMATCHED` 排序，
所以 **一批做完重跑同一条命令就自动推进**（不用记批次号）。
`todo` 的路径走 stdout、分批说明走 stderr，管道不会被打扰。

阶段（**由事实推导，不是手工填的**）：

| 阶段 | 含义 | 会重搜吗 |
|---|---|---|
| `SEEDING` | qB 里真有这个 info_hash | ❌ 永不 |
| `MATCHED` | 匹配到、已注入，等 qB 确认 | ❌ 不 |
| `UNMATCHED` | 真搜过、没匹配到 | ⏳ 仅当**出现没搜过的索引器**或过了重搜周期（默认 **14 天**） |
| `SKIPPED` | ★被退避秒跳 | ✅ **立刻** |
| `PENDING` / `ERROR` | 没搜过 / 异常 | ✅ 立刻 |

> **加一个站，所有 `UNMATCHED` 自动变成待搜** —— 不需要人工挑片子。
> 实测：只配 SiteA 时待搜 286 条；加上 SiteB 后那 48 个 `UNMATCHED` 全部解锁。

**重搜周期（每站按周期重搜，默认 14 天）**：粒度是 **(片 × 站)**，来自 cross-seed 自己的
`timestamp(searchee_id, indexer_id, last_searched)` 表。默认每站 14 天，可按站覆盖：
`--cadence "SiteA=14,NanyangPT=30"`；`todo --include-cooldown` 忽略周期强制全量重扫。
`report` 会打印按站周期表（搜过几部 / 到周期几部 / 下次最早可重搜是哪天）。详见 SUMMARY §11.6。

> **为什么是 14 天而不是 7 天**：无人值守下这个周期直接决定长期查询量 ——
> 约 1000 部单片，7 天 = 每天 ~150 次查询/站、一年 5 万+ 次，且是**永不停止**的机器人流量。
> `delay=30` 解决的是"快不快"，解决不了"像不像人"。翻倍到 14 天查询量减半，
> 代价只是未命中的片子多等一周。**账号比命中率重要** —— 站点查限额见 SUMMARY §11.6。

**`drive` 已经会控速、会等退避、会回灌**（SUMMARY §11.8）：
`--interval 30` 对齐 cross-seed 的 `delay`；读 cross-seed.db 的 `indexer` 表检查退避 ——
**双触发**：每 `--check-every 10` 条、以及每 `--backoff-check-secs 60` 秒
（★按秒那一路是 2026-09-12 加的：实测退避窗口只有 30~60 秒，只按条数 300 秒才看一眼会**整段错过**）。
撞上 `RATE_LIMITED` 就**睡到解禁**；若要等到**超过 `--max-wait 1800` 秒**，
★**先看是不是"全都在退避"**（2026-09-16 改）—— 还剩下健康站就**照发**
（cross-seed 会跳过被禁的站、用其余的搜，实测见 SUMMARY §11.13），
**全都落在退避里**才中止；没给 `--indexers` 时退回旧行为（照旧中止，宁可吵）；
打完自动 `sync` 回灌，直接告诉你 `newly_seeding`（这轮真赚到几部）和 `still_skipped`（又被退了几部）。
**默认 dry-run**，不加 `--apply` 不会发任何请求。

> 为什么退避只能读库、不能用 API：cross-seed v6.13 的 HTTP 接口只暴露
> `/api/ping` 与 `/api/status`，`/api/indexerstatus` 是 **404**（见 SUMMARY §11.9）。

- 状态库是 `hlink/state.db`（**运行时数据，已 gitignore**）。它**只读** cross-seed 的库/日志与 qB，
  唯一被写的就是自己。为什么不直接给 cross-seed 的库加字段？见 SUMMARY §11.1。
- 读 cross-seed.db 走**直读 UNC**（`PRAGMA query_only=1`，实测 0.17s 且能看到 WAL 数据），
  拷 `.db/-wal/-shm` 只是兜底。⚠ **诊断脚本一律直读，别 `cp`** —— `cp` 丢 WAL，会误判（SUMMARY §13.6 坑 2）。
- ⚠ `--root` 是 **cross-seed 视角的 NAS 路径**（webhook 要用它）；Windows 上列目录另外传 `--local-root`。
- 想跑"一次性批量作业"而不是长期增量维护，用 `python -m orchestrator.main`
  （`preflight` / `run` / `status` / `prestage`，见 SUMMARY §11.10）。

### 多包支持（已接入 3 个包）

| 包 | 单片单位 | 结构 |
|---|---|---|
| `frds-top250-2024` | 一部电影 | ✅ 根目录子目录即发布名 |
| `my-brilliant-friend-s01-s04` | 一季（S01~S04） | ✅ 根目录子目录即发布名 |
| DC 合集 | 一部电影 / 一季 | ⚠ 根下多一层中文标签，见下 |

#### ⚠ 嵌套结构：dataDir 要指到「发布名的那一层」

cross-seed 用**目录名**去站点搜索。若大包根下还有一层分类/标签目录，那层名字会被当成 searchee 名 ——
**搜不到任何东西，却照样消耗查询额度**。

```text
DC相关剧集全系列大合集/            ← ❌ 别把这里当 dataDir
├── DC系列电影/                   ← ❌ 也别
│   └── 01.蝙蝠侠1：侠影之谜 (2005)/ ← ❌ 更别（中文标签）
│       └── Batman Begins 2005 …-CHD/  ← ✅ 这里才是发布名
```

正确做法：把 `DATA_DIRS` 指到**标签层的每个目录**，这样它的直接子目录才是发布名。
用附带的生成器产出这段（幂等，加片后重跑即可）：

```bash
python scripts/gen-datadirs.py "//YOUR-NAS/video/download/movies/DC相关剧集全系列大合集" \
    --level 2 --nas-prefix /volume1/video --list           # 先核对
python scripts/gen-datadirs.py "//YOUR-NAS/video/download/movies/DC相关剧集全系列大合集" \
    --level 2 --nas-prefix /volume1/video --append-to .env  # 追加
```

**不要**改用调大 `maxDataDepth` 来省这 47 条 —— 它是**全局**的，其它包会跟着多出一批 searchee，
而中文标签照样进池子。实测两种接法的垃圾名数量：包根方案 **47 个**，本方案 **0 个**。
完整分析与 cross-seed 的 searchee 生成规则见 SUMMARY §10.2 / §10.6。

> 状态机**已支持嵌套包**：`init --root` / `--local-root` 可重复传、`--depth` 必须与
> `maxDataDepth` 一致。DC 47 根 → 115 单片已能正常登记（SUMMARY §10.4 / §10.6）。

#### 生产 `.env` 怎么更新（本地改完要同步到 NAS）

`deploy.sh` 的白名单**故意不含 `.env`**（怕覆盖生产上的真实密钥），所以 `DATA_DIRS` 得单独上 NAS 改。
这条值长约 3.5 KB、含中文与全角括号、还有带空格的路径 —— **别手敲**。用生成器：

```bash
python scripts/gen-nas-env-update.py          # 由本地 .env 生成 scripts/nas-update-env.sh
```

把生成的 `scripts/nas-update-env.sh` 传到 NAS（和 `compose.yaml` 同目录），然后：
```bash
sh nas-update-env.sh --dry-run       # 先看：备份 + 新旧条数 + 逐条校验 49 个路径是否存在
sh nas-update-env.sh                 # 改 .env + 重启 cross-seed + 回读容器内条数做闭环验证
sh nas-update-env.sh --no-restart    # 只改不重启
```

脚本会：① 备份 `.env` → `.env.bak.<时间戳>`；② 用 `awk` 就地替换 `DATA_DIRS=` / `LINK_DIR=`
两行（不走 `sed`，避开分隔符与 `&` 转义坑）；③ 逐条 `[ -d ]` 校验（缺失只告警）；
④ 重启后 `docker inspect` 回读容器内的 `DATA_DIRS` 条数并比对。回滚：`cp -p .env.bak.<时间戳> .env`。

**它只动这两行，其余键逐字节保留** —— 因为本地 `.env` 的 `TORZNAB_URLS` 是脱敏占位符
（`apikey=xxxx…`）、生产上是真实密钥，串了就是全线 401（写盘前有 `cmp -s` 硬闸把关）。
原理与实测见 SUMMARY §11.12。

> ⚠ **怎么确认它真的生效了**：`.env.new` 存在 ≠ `.env` 已更新。判断一律看这两处 ——
> ① `docker inspect reseed-cross-seed` 的 `DATA_DIRS` 条数 ② `cross-seed.db` 的 `data` 表
> 里有没有新包的路径。别看 `ls`。详见 SUMMARY §11.12。

#### 其它要点

1. **`hlink/config.yml` 的 `jobs`** 是数组 —— 复制一段、改 `name` / `source_dir`；
   注意 job 的 `source_dir` 语义是「**其子目录 = 各单片**」。
2. **`LINK_DIR` 必须与源大包同一个物理卷**（硬链接不能跨卷）。新大包若在**另一个卷**上，
   就要为新卷再配一个 linkDir —— cross-seed v6 的 `linkDirs` 是数组，它会按 searchee 所在设备挑同卷的那个。
   **不要**把 linkDir 指到 SSD 上图省事：跨卷建不了硬链接，会直接失败。
3. **分类与汇报**：`QBIT_CATEGORY` 目前是单一分类 `reseed-singles`。多包时靠
   `LINK_DIR/<包名>/<Tracker>/...` 的目录结构区分，或给每个包单独起一个 qB 分类。
4. **磁盘**：新大包本身要占真实空间 —— NAS 的 `/volume1` **已 0 可用 / 100%**。
   ★ 先看 **SUMMARY §9 的「卷归属表」**：`video` / `Download` / `docker` 在**满**的那块
   （56 T），`docker_ssd` / `qb_temp` / `技术文档` / `000 临时文件夹nas（内容可删除）`
   在**另一块 448 G 的盘上（304 G 可用）**。要临时落脚就放后者，**别往 `/volume1` 写真实文件**。
   但**硬链接侧依旧零开销** —— 这正是本项目能在满卷上跑起来的原因。
5. **站点压力**：接入 DC 后 searchee 总数从 ~405 涨到 **~1000+**，一轮全量搜索的耗时和 API 次数
   都会成倍增长。**按包分时段跑、务必带 `--limit`**，别同时开多个全量任务。
6. **日常重搜别打大包根的 webhook** —— 它不会排除已做种的片子。走
   `reseed-state.py drive`（已排除 `SEEDING`/`MATCHED`），详见 SUMMARY §11.11。

### 硬链接农场（v3，**农场已建好 / 配置待切换**）—— 把 49 条 `dataDirs` 收成 1 条

**它解决什么**：现在 `DATA_DIRS` 是 **49 条**（3 个大包 + DC 的 47 个标签目录），
每加一个包就要重算一遍路径、同步 `.env`、重建容器。农场把这些归一成**一条**。

**做法**：在源同一个物理卷上建一个**扁平**目录，每个子项 = 一个"单片"，用**硬链接**
指向真实数据（不占数据块，只多 inode + 目录项）：

```text
/volume1/video/download/reseed/reseed_farm/     ← 唯一的 dataDir
├── Arrow.S01-S08.2012-2020.Bluray.1080p.MNHD-FRDS/   ← 硬链接副本
├── 守望者S01.Watchmen…@FRDS/
└── …（实测 475 条）
```

`dataDirs` 从此只有这一条，`maxDataDepth` 保持默认 **2**（不用动全局开关 →
FRDS/MBF 行为完全不变）。

> **为什么"每个 dataDir 的直接子项"就是全部规则**：cross-seed 的枚举是
> `dataDirs → 每个直接子项 → 按 depth 展开`。农场的子项**恰好等于**原来那 49 个
> dataDir 的直接子项之并集，所以「农场 + depth=2」与「49 条 + depth=2」产出的
> searchee **逐条相同**。★ 这是**构造上**的等价 —— 同一个函数作用在同一批首层条目上，
> 不依赖我们对 depth 规则的建模是否精确（实测 475 条、**零重名**）。

**怎么用**。`deploy.sh` 只管容器文件，**不含** `scripts/`，所以先把它拷到 NAS 的
compose 目录（纯 LF，`sh` 可直接跑）：

```bash
# 本地：拷到 NAS 的 compose 目录
cp scripts/build-farm.sh "//iSunker-DS423/docker_ssd/prowlarr_cross-seed_autohardlink/"
```

然后**在 NAS 上跑**（最省事）：

```bash
cd /volume2/docker_ssd/prowlarr_cross-seed_autohardlink
sh build-farm.sh                    # 默认 dry-run：只统计预演，一个文件都不建
sh build-farm.sh --apply            # 真建（增量：已存在的跳过）
sh build-farm.sh --apply --prune    # 顺带删掉"源已经没了"的条目
sh build-farm.sh --verify           # 只校验农场 vs 源
```

> ⚠ ~~**`--verify` 在 `DATA_DIRS` 切到农场之后会失效**~~ ✅ **2026-09-12 已修，不再是问题**：
> 当时的毛病是它取「期望集」的方式**从 `.env` 的 `DATA_DIRS` 派生**（脚本第 108 行），
> 而 v3 的全部意义正是把 `DATA_DIRS` 改成农场这一条 —— 于是它**拿农场校验农场，永远 PASS**。
> 现在期望集改由独立的 `FARM_SOURCES` 给出，并加了一道**自指闸**（期望集里出现农场自身
> 就拒绝执行），`--verify` 也补齐了退出码与漂移明细（0=无漂移 / 1=有漂移 / 其它=没跑成）。
> 详见 **SUMMARY §16.2.1**。
> ✅ **它已经挂成定期巡检了**，且已在生产跑过一次 —— 见 **SUMMARY §16.2.2 / §16.2.2.1**。

> ★ **也能直接从 Windows 跑**（走 SMB）—— 2026-09-11 实测：这个 NAS 上
> `os.link()` / `cp -al` 经 SMB 过来是**服务端真硬链接**（同 inode、`nlink=2`、
> 删掉原文件后另一个还在）。原先"Windows 建不了硬链接"的说法**是错的**。
> 此时 `.env` 里的 `/volume1/...` 在本机不存在，用 `--map` 做前缀翻译即可：
>
> ```bash
> COMPOSE_DIR="//iSunker-DS423/docker_ssd/prowlarr_cross-seed_autohardlink" \
> FARM="//iSunker-DS423/video/download/reseed/reseed_farm" \
> sh scripts/build-farm.sh --map "/volume1=//iSunker-DS423"          # 先 dry-run
> # 确认 → 同一行末尾加 --apply
> ```
>
> 两种跑法结果完全一样（脚本每次都用探针**自证**硬链接真的建成了，见下）。
> Windows 跑的代价是逐文件 RPC，475 条用时数分钟。

确认无误后，切换（**与"移除 BTSCHOOL"合并成一次容器重建更省事**）：

1. 本地 `.env` 把 `DATA_DIRS` 改成农场那一条路径；
2. `python scripts/gen-nas-env-update.py` 生成新的 `nas-update-env.sh`；
3. NAS 上 `sh nas-update-env.sh`（改 `.env` + `--force-recreate` 容器）；
4. 验证：`drive-loop` 启动时的「索引器自检」与 searchee 数应与切换前**一致**。

**安全边界**：脚本**只增不删**（除 `--prune`）；`--prune` 带安全闸 ——
期望集为空时**拒绝**执行（否则 `.env` 一读错就会把整个农场删光）。
★ 脚本**绝不** `chown -R`：硬链接文件与源文件是**同一个 inode**，
对链接文件 chown 会改掉**源文件**的属主 —— 所以只对目录（新造的）改属主。

设计取舍与 A/B 方案对比见 SUMMARY §10.5。

### IYUU 扩散（本次不实现）

单种在 `:3060` 做种后，由 IYUU 读其 InfoHash 扩散到更多站点。`hlink/config.yml` 里 `jobs[].iyuu_handoff` 为其预留开关。

### 别的匹配器（本次不实现）

`orchestrator/matcher.py` 的 `Matcher(ABC)` 是接口落点；`hlink/config.yml` 的 `matcher.engine` / `jobs[].matcher_engine`
预留 `iyuu`/`custom`（当前会明确报"未实现"）。

---

## 原理技术和风险须知

> 两条「不知道就会踩」的原理。**完整论证、实测数据与四条对策见 SUMMARY §19。**
> 这里只放**要照做的部分**。

### 原理 A：没有「识别」，只有「声明」—— 系统不会告诉你哪个目录是包

系统只有两件**被动**能力，**两件都不判断「这个目录是不是包」**：

| 能力 | 输入 → 输出 |
|---|---|
| **枚举**（`scan_pack()` / `find_searchee_paths()`） | 一个根 + 一个 depth → 根下的单片清单 |
| **归属**（`_resolve_searchee_to_pack()`） | 一条 searchee 路径 → 它属于哪个包的哪个单片 |

> 「哪个是大包」这个判断**从来不发生在代码里，只发生在人手写下的配置里**。

**声明点清单 —— 分两档，因为「漏了会怎样」完全不同：**

**① 静默档：漏了没有任何人知道**（**只有这一档需要检测器**）

| 声明点 | 在哪 | 声明什么 | 漏了会怎样（两边看起来都正常） |
|---|---|---|---|
| **`FARM_SOURCES`** | NAS `.env` | 哪些目录是**源根** | `build-farm.sh --verify` 期望集里没有它 → **连漂移都不报**（两边一致地当它不存在） |
| **`pack` 表一行** | `<compose>/drive-loop/hlink/state.db` | 名字 + `roots` + `farm_root` + `max_depth` | 农场里的片**归不到任何包** → 静默 continue（只记进 `other_pack`） |
| **`--packs`** | `drive-loop.py` 的 **`PACKS_DEFAULT`**（`dc-collection,mbf,frds-top250-2024`；`run.sh` **没传**） | 哪个包**会被驱动** | 状态机有它、农场有它，**就是不排它** —— `mbf` 就是这么被落下很久的（2026-09-13 已排进去，见第 7 条） |
| **`--indexers`** | `run.sh` | 哪些**站**会被搜 | 站没进名单 = 对每部片子来说「那个站从没搜过」**根本不会被表达出来** → HDtime 就是这么卡住的（§18.11） |
| **文档里的 init 配方** | `SUMMARY §10.2` 与本节的示例 | 包名 + `--match` 关键词 | 照旧配方重跑 → 挑 0 条根；或**多建一个包行**（`mbf` 与 `my-brilliant-friend-s01-s04` 是同一包的两个名字） |

**② 会响档：漏了立刻报错**（不用盯，但**别和上面混成一张表**）

| 声明点 | 在哪 | 漏了会怎样 |
|---|---|---|
| `DATA_DIRS` | NAS `.env` | cross-seed 扫不到东西 —— 农场空转，日志当场不对 |
| `LINK_DIR` | NAS `.env` | 硬链接建不出来，cross-seed 报错 |
| `TORZNAB_URLS` | NAS `.env` | 那个站压根不在容器里，`check_env_applied()` 下一批就喊 |

> ★ **分档本身就是判据。** ② 漏了会自己喊；① 漏了**两边都正常** ——
> 所以「要不要给它配检测器」这个问题，答案完全由落在哪一档决定。
> 把两档并回一张"完整的声明点表"看起来更整齐，但会把这条判据抹掉。
>
> ★ ① 里的**每一处**都是「登记了却不在名单里」和「压根没登记」**长得一模一样**。
> 2026-09-12 的 HDtime 就是活例 —— 它早在 Prowlarr 和 `.env` 的 `TORZNAB_URLS` 里，
> 名单里没有它，**224 部 UNMATCHED 一部都没往新站重搜**，而 Prowlarr / cross-seed
> 那一侧看起来一切正常。

**看起来像识别、其实不是**：

```bash
python scripts/reseed-state.py init --roots-from-env .env --match "DouBan_IMDB"
```

它是「**从人给的清单里，按人给的关键词挑**」，不是「识别出哪些是大包」——
**关键词是人给的**，系统不生成关键词。所以新包没进**清单**，`--match` 也永远挑不到它。

⚠ **v3 之后它一度连"挑"都做不到**：农场切换把 `DATA_DIRS` 从 49 条源目录改成
**1 条**（农场本身），而它**只读 `DATA_DIRS`** → `--match "DouBan_IMDB"` 一条都匹配不上，
直接报「没挑到任何根」。源根清单搬到了 **`FARM_SOURCES`**，**工具没跟着搬**。

✅ **2026-09-12 已修**：`_roots_from_env()` 现在**首选 `FARM_SOURCES`、缺席时退回 `DATA_DIRS`**
—— 照的是 `build-farm.sh:132-155` 里**早就写好**的同一种优先顺序（连退回时的报错文案
`build-farm.sh:178-181` 都有），不是另立一套规矩。验收见 §19.1.3。

**农场之后，「包」只剩两个用途**（搜索那一侧已经不需要它了）：

* **webhook 发源路径** —— 发的是 `movie.path` = **源大包路径**，不是农场路径；
* **按包统计 / 轮流跑** —— `report` / `trend` / `--packs` 的分账。

> ★ 换句话说：**「包」现在是个纯账本概念** —— 决定怎么记账、发什么 webhook，**不决定搜什么**。

**盯着漏声明的两个计数器**（都在日报里，各配一条基线 —— 期望值都指回一条判据之外的真实记录）：

| 计数器 | 覆盖 ① 的哪一处 | 基线 | 涨了意味着 |
|---|---|---|---|
| **全场无人认领**（§18.19.2） | `pack` 表 | **1**（那条 `0观影清单chrlee整理` 的 xlsx） | 有人加了包、忘了登记 `pack` 表 |
| **声明点〔`--packs`〕**（§19.1.6） | `--packs` | **0**（2026-09-13 起 —— `mbf` 已排进 `PACKS_DEFAULT`；此前恒为 1） | 有人又落下一个包 —— 或被驱动名单里的名字写错了 |

⚠ 覆盖面仍要说清：① 里的 **`FARM_SOURCES`** 与 **文档里的 init 配方**今天**仍然没有检测器**
—— 它们没有一条能自动对账的"另一侧"（前者要 NAS 上真去 build 才看得出，后者是文档）。

### 原理 B：搜索压力来自「分母」，不是「频率」

* **不是「一直在搜」，是每站 14 天一轮** —— `DEFAULT_CADENCE_DAYS = 14`，
  注释原话就是「**永不停止的机器人流量**」。这是**设计时就知道的代价**（见「为什么是 14 天而不是 7 天」）。
* **当前那个「均摊」是「优先级插队」的副产品** —— 待搜清单按
  `SKIPPED → ERROR → PENDING → UNMATCHED` 排序、每批 `--limit 50`，
  于是 `UNMATCHED` **永远排在队尾**。它今天能被节流，只是因为 `SKIPPED`/`PENDING` 还多；
  **等它们被清空，`UNMATCHED` 的压力会突然全部释放。**
* **压力的真源**：`PENDING`/`SKIPPED` 都是**一次性**的（搜/重搜一轮就没了），
  只有**到期的 `UNMATCHED` 每 14 天重生一次** —— 这才是永久压力。

> **所以杠杆不在「均摊时间」，在「减少分母」** —— 而减少分母**唯一安全**的做法是
> **「按站历史表现降频」**，不是「按片预测会不会命中」。
>
> ★ 四条思路（抖动 / 按站自适应周期 / `EXHAUSTED` / 全局日预算）各自的成本、风险
> 与推荐排序，见 **SUMMARY §19.2.4**。**这四条都还没实现。**

### 原理 C：BT 只校验 **Piece**，不校验「整个文件」

`.torrent` 里**没有"文件哈希"这种东西** —— 只有 **`pieces`**：
文件被按**建种人选定的固定大小**（常见 1/2/4/8 MB）切成片，
**每片一个 SHA-1**，按顺序拼成一个长字符串。**校验只发生在这一层**：

| 层 | 校验什么 | 谁校验 |
|---|---|---|
| **Piece** | 每片的 SHA-1 是否与 `.torrent` 里记的一致 | **BT 客户端**（qB / Transmission） |
| **文件** | ★ **没有独立的文件级校验** | —— |

**由此推出的两条**：

* **piece 全过 = 做种完整**；**有一片不过 ⇒ 客户端会去重下那一片**（**不报错、不拒绝**）。
* ★ **「文件看起来一样」≠「piece 全部通过」** —— piece **会跨文件边界**
  （一个片 = 文件 A 的尾部 + 文件 B 的头部），且**片大小是建种人定的**。

★ **对本项目意味着什么**（两条，都很实用）：
1. **判「能不能跨站做种」的唯一判据是「字节是否一致」** —— 字节一样，
   qB 按新种子的 piece 表重算**照样 100%**，**片大小不同不影响命中**。
2. **真正咬人的是 `partial`** —— 它按"名称 + 大小"就放行，**piece 哈希压根没对过** ⇒
   qB 重下那几片 ⇒ **源文件被写穿**。见下节。

> ★ 本项目**只**做「搬运 + 触发 recheck」，**不**给任何"这是真种"的保证 ——
> **那是 qB 的 piece 校验说了算**，不是本项目说了算。责任边界见 **⚠ 免责声明与使用边界**。

### 风险清单

| 风险 | 现状 | 谁在看着 |
|---|---|---|
| 漏声明 → 包**静默不存在** | 3 个声明点**全是手工** | 只有第 2 处有（无人认领计数器，基线 1） |
| **搜索总量没有上限** | `delay` 控速、退避检测**被动等** —— 但「一天总共能发多少」**没有闸门** | 无 |
| `UNMATCHED` 的「软性节流」会**突然释放** | 靠 `SKIPPED`/`PENDING` 还多撑着 | 无 —— **不可观测** |
| 站上「后来才有人发种」的机会被漏掉 | 14 天周期是当前兜底 | 无 |
| 「按片预测会不会命中」这条路 | **没采用，也不该采用** —— 判据只有模型自己一个来源 | 见 SUMMARY §19.2.5 |
| **源文件被 qB 就地重下写穿**（partial 注入 × 硬链接） | 2026-09-13 起 `matchMode` ⇄ `linkType` **互锁**（只有 reflink 才许 partial）+ **链接守护**每日差分 | 存量 628 条仍是硬链接（**故意不重建**）—— 靠守护发现、按需重建，见下节 |
| **产物是「不完整做种」**（partial 注入的形状） | 同一轮已关闸；已注入的 **629 条里 551 条（88%）来自非完整匹配** | 链接守护只盯「文件被改没改」—— **不盯「这条种子产不产出」** |
| ★ **有人拿本工具链去做「假种」/ 刷流量 / 冒充** | 本项目**只建立链接 + 注入种子**，无任何生成或掩盖数据的路径 | **无 —— 这是责任边界，见「⚠ 免责声明与使用边界」** |

### 源文件被写穿 —— partial 匹配 × 硬链接农场（2026-09-13 发现）

**一句话**：cross-seed 以 `matchMode: partial` 把「名称+大小匹配、但 piece 哈希不一致」的
单种也注入 qB；qB 校验(recheck)不通过时**不报错**，而是**就地重下**那几个 piece；
而 `linkDirs` 是硬链接 —— 于是这次重下**直接写进源文件**，无声改写库里母本，
Farm 侧还显示 100%。

**三个前提各自都"合理"，叠在一起才致命**：
① partial 是官方推荐的高命中模式；
② `skipRecheck: false` **看起来**是安全网（实际上它不通过时 qB 只会重下，不会拒绝）；
③ 硬链接是为了零磁盘开销。
上游文档甚至把这个现象写成正常行为：

> Nearly all partial matches recheck to **99.9%** rather than 100% *(expected due to piece hashing)*

**实证**（两处时间**分秒吻合**）：

| 包 | 注入种 decision | 种子完成时刻 | 对应源文件 mtime |
|---|---|---|---|
| 哥谭.全5季 `04421b52` | `MATCH_PARTIAL` | 09-13 16:35 | 15:57 / 16:05 / 16:35 |
| 教父 1972 `db7be3ac` | `MATCH_PARTIAL` | 09-12 09:49 | 09-12 09:49 |

反证（天然对照）：同一份《致命魔术》被注入 **6 次** —— 5 条 `MATCH`（完成 09-12 19:22）
源**毫发无伤**，第 6 条 `MATCH_PARTIAL` 卡在 `99.9996%` 正在重下。

规模：已注入的 629 条里 **551 条（88%）来自非完整匹配**（`MATCH_PARTIAL` 472 +
`MATCH_SIZE_ONLY` 79 —— 后者只按大小匹配）。

**处置**：分两步走，**第一步关闸门，第二步给存量上锚**。

#### 第 1 步 · 关闸门：把 `matchMode` 和 `linkType` 做成**结构性互锁**

`cross-seed/config.js` 里 `resolveMatchMode()` 不再单独看 `MATCH_MODE`，而是先看链接类型：

| `linkType` | `matchMode` | 为什么 |
|---|---|---|
| `hardlink` / `symlink` | **强制 `strict`**（`.env` 的值被忽略并告警） | 同 inode / 同文件 ⇒ 重下 = 写穿源文件 |
| `reflink`（COW） | `.env` 的 `MATCH_MODE` 生效，可以 `partial` | 重下只改副本，源不受影响 |

这么耦合是**故意的**：把"放宽匹配"的前提写进代码，以后谁想调 partial，**必须先让
链接真的是 COW 的**，而不是在 `.env` 里改个值就绕过。`reflinkOrCopy` 会被**降级成
`reflink`** —— 它在 reflink 失败时**静默整份拷贝**（上游文档自己标了 Danger），
而本卷已近满，一次静默拷贝就能把注入卡死，且"静默"意味着你只看到跨站做种莫名停了。

`orchestrator/hardlink.py::prestage()` 是**另一条**建链接的路径，也一并接上了
`matcher.link_type`（此前 `config.py` 里那个键只被定义和校验、**全仓库无人引用**，
是个死键 —— 不接上它，config.yml 里写 reflink 也只是好看）。

#### 第 2 步 · 给存量上锚：链接守护（the 628 条仍是硬链接）

reflink 只保护**新建**的链接。改动前已建的 **628 条仍是硬链接**，且**故意不重建**
（重摆几十 TB 链接的风险大于收益）—— 但必须能发现"它正在被写穿"。

判据：给这 628 条 payload 的文件建一份 `(size, mtime_ns)` 指纹基线，**定期差分**。

- **判据本体**在 `orchestrator/state.py`（`linkguard_snapshot` / `linkguard_diff` /
  `linkguard_owner` / `linkguard_inflight`）—— 本进程跑在 NAS 宿主机上，
  判据只有一份才谈得上两侧一致。
- **基线**落在 `<compose>/drive-loop/scripts/.linkguard.state`（**单独一个文件**：
  几千~几万条快照不该让每个 watch 都搬一次 —— `.reconcile.state` 是几个 watch
  整文件读改写的）。
- **接线**在 `drive-loop.linkguard_watch()`，挂在**每日台账**里，只报数量：
  `被改写 N · 新增 N · 消失 N · 正在动 N`。**首读不响**（现状不是新闻，#47 的规矩）。
- **诊断端** `scripts/crossseed-linkguard.py`（Windows 上跑，**只读**）：告诉你
  具体是**哪几条**（默认只出 hash 12 位，`--show-names` 才出发布名）。
- ★★ **`_linkguard_detail.changed` 在首读那一轮必须是空的**。首读 `base={}` ⇒
  `linkguard_diff` 把**整库**算进 `added`，而 `linkguard_watch` 把 `changed + added`
  合并写进同一个键 ⇒ 诊断端吐出「★ 被改写 / 新增（4 条种子受影响，共 **2816** 个
  文件）」—— **而那天什么写穿都没发生**（2026-09-13 18:00 起锚时真的这样，已修、
  已钉回归）。注意**只看日报是发现不了的**：正文与 metrics 本来就对（`first` ⇒
  三个数全 0），错的恰恰是"出事后去查证时读的那份清单"。

★ **为什么不直接监控"是否被 recheck"**：qB 不提供逐种的 recheck 计数，
`checkingDL`/`checkingUP` 只是**瞬时**状态，事后查不到；而且 recheck 本身无害 ——
有害的是它**失败后那一次就地重下**。所以判据落在**结果**（文件到底变了没）上。
瞬时状态另记一格（`linkguard_inflight`），用来抓"此刻正在发生"。

★ **`uploading` 那个坑**：`uploading` **不以 `UP` 结尾**，只按 `endswith("UP")`
判会被当成"正在下载"⇒ 误暂停健康做种。这个判据写错了**不会报错**，只会把
628 条好种子一条条 pause 掉 —— 而"暂停"看起来完全正常。是 `tests/test_linkguard.py`
当场抓到的（生产上那把临时看门狗用的是同一个写错判据，只是那批种子恰好全是
`stalledUP` 才没误伤）。

**残留风险 / 边界**：
- `/volume1` 确认是 **BTRFS**（`/dev/mapper/cachedev_1 /volume1 btrfs …`）⇒
  **reflink（COW）可用**。★ 这块卷**已用满 100%**（仅剩 ~19 GiB）—— COW
  "不写不占空间"在这里尤其划算，但重下分离出来的块**要占真实空间**，留意容量。
- 这块卷上 **reflink 是真的在发生**：删掉旧根那 9 个文件时，`%h == 1`（不像硬链接）
  却**一分空间都没回来** —— 因为 COW 共享 extent。⇒ **判 inode 数判不出 COW**，
  要看 `btrfs filesystem du -s` 的 Exclusive 列。
- **写入面已实测（2026-09-13）**：qB 全部 931 条的 `save_path` **都**在
  `reseed_singles/<站点>/`（HDFans 488 / 南洋 258 / BTSCHOOL 143 / HDtime 42），
  **没有一条**落在 `reseed_farm` —— 面很窄，只有这一处要改。
- 已被改写的文件**无备份可恢复**：`net view` 没有任何备份共享，4 处 `#snapshot` 均不存在，
  `download/可删` 与 `download/temp` 为空。诊断出"被改写"之后，恢复要**回站点重新下**
  —— 那条数据**和源是同一份**，删种子只会少一份证据（见任务 #74）。
- inode 基线存档在 **`D:\tmp\reseed-inode-baseline\`**（**仓库外** —— 里面有完整文件名）。
  日后谁再被改写，拿这份比即可。

**损失清单与收尾（2026-09-13 定案，按 16:51 那份基线快照判）**

- 全库 **5654** 个 payload 文件里 mtime 异类 **18 条**，去重后是 **9 个文件**：
  **5 个确证被写穿**（源侧同时异常 —— 哥谭S01 ×2、教父1972 ×1、新蝙蝠侠2160p ×1、
  Arrow S01 ×1）；**1 个**哥谭S01 文件被改写但源侧没有对应硬链接（**只伤它自己**）；
  **3 个判不了**（源侧反而更旧 ⇒ 它本来就不是"同一份"）。
  ★ 其中**哥谭、教父**两组另有上文那张**分秒吻合**的实证表 —— 那是当场抓到的 **2 例**；
  这里说的 5 个是事后按基线快照扫出来的，两者口径不同、互不冲突。
- 改写时刻：哥谭 09-13 15:57–16:35、教父 09-12 09:49（**都在本周、当时正在进行**），
  另有 2026-06-13 ×3 与 2025-12-14 ×2 属历史改写。
- ★ **本条到此闭环，没有待办动作。** 当初记录里那句"待盯"——看 17:38 那轮 inject
  会不会把暂停的条目唤醒——**已经盯完**：17:38:48 那轮是 `No torrent files are
  awaiting injection`（**0 个文件**），`c802c614` 在日志里的最后一处提及是 16:39:21，
  qB 里现在 **0 条**，暂停连续 **8 轮**没被唤醒。
- 恢复路径**确认不存在**（见上一节最后一格）⇒ 剩下的只是"**回站点重新下**"这一个人的
  动作，**不是代码动作**，所以不挂在任务列表上。

#### 附：硬链接 vs reflink —— 差在哪、**怎么判**、以及本项目**判错过一次**

| 维度 | **hardlink（硬链接）** | **reflink（COW / 写时复制）** |
|---|---|---|
| 本质 | **同一个 inode** | 看起来像副本，实则**共享数据块**，**inode 不同** |
| 创建时占用 | **0 字节** | **0 字节** |
| ★ **有人写时** | ★ **改全部**（含源文件） | ★ **只改自己**（复制被写的那一块） |
| 写后占用 | 0（但**源被改**） | **被写的那一块** |
| 跨卷 | ❌ 不行 | ❌ 不行 |

**三条硬性警告**：

1. ★ **hardlink 下，qB 的任何"补下载"都直接改源文件，且不可逆** —— 没有快照就回不来
   （本项目实测：`net view` 无任何备份共享、4 处 `#snapshot` 全不存在）。
2. ★ **reflink 只保护"新建的"链接** —— 已存在的 hardlink **不会自动变**，要**重建**。
   本项目**故意不重建**那 628 条（重摆几十 TB 链接的风险大于收益），改用**链接守护**发现。
3. ★ **reflink 的代价是"重下的那块占真实空间"** —— 对本项目这块**已满 100%** 的卷是直接副作用。

**怎么判「是不是同一个 inode」—— 本项目在这上面判错过一次，务必照这条来**：

| 路 | 可用否 |
|---|---|
| Windows 经 SMB：`st_nlink` | ❌ **恒读成 0**（`orchestrator/state.py` 里写着这条注释） |
| Windows 经 SMB：`nNumberOfLinks` | ❌ **恒读成 1** —— ★ 拿一对**定义上同 inode** 的硬链接（农场条目 vs 它的源，`cp -al` 建的）做对照，**两边都报 1** |
| **Windows 经 SMB：`fid`** | ✅ **唯一可用** —— `GetFileInformationByHandle` 的 `nFileIndexHigh/Low` **就是服务端 inode**，跨 SMB 准确透传（同一路径连读两次结果一致） |

★★ **关键不是"读不到"，是"读得到一个假的"** —— `nlink = 1` 看起来完全正常，
于是「`nlink = 1` ⇒ 不是硬链接」这条推断**整套是错的**。
这是本项目反复栽的**假阴性**形状：**命令成功了、结论是空的**。判据一律用 **`fid`**。

★ **再进一步：`fid` 两两不同 ≠ 删了能释放空间。** 删旧根那 9 个文件时实测
`%h` **全部 = 1**、`fid` 也**两两不同**，删完**一分空间都没回来** ——
因为 **COW 共享 extent 时 inode 本来就是不同的**。
⇒ 判"删了省不省空间"要看 **`btrfs filesystem du -s` 的 Exclusive 列**（≈0 ⇒ 与别处共享）。
同一实测见本节末尾「残留风险 / 边界」第二条。

---

## 漂移哨兵 —— NAS 和仓库到底一不一致

`deploy.sh` 是**白名单式、单向**的：它保证**白名单里**那些文件两边逐字节一致，
**白名单之外的一律不碰、也不报告**。于是有两个方向会悄悄长东西：

| 方向 | 长出什么 | 后果 |
|---|---|---|
| **A（NAS 上冒出来的）** | 手工拷上去的脚本、忘了删的一次性补丁、调试产物 | **不在任何同步机制里** —— 既不会被更新也不会被发现，只会在某天以「NAS 上跑的行为和仓库里这份不一样」的形式咬人 |
| **B（仓库里没登记的）** | 新写了脚本，忘了加进 `deploy.sh` 的 FILES | `git push` 把它带走了，但**它永远上不了 NAS**，而且没有任何东西会提醒你 |

两个方向都有前车之鉴：`build-farm.sh`、`fix-statedb-farm-root.py`、`nas-update-env.sh`
三个文件都曾长期**靠手工拷**，2026-09-12 才逐个收进白名单。

```bash
python scripts/check-deploy-drift.py              # 两个方向都查（DST 取自 --dst / 环境变量 / scripts/.nasrc）
python scripts/check-deploy-drift.py --all        # 连已知生产独有的一并列出
python scripts/check-deploy-drift.py --cleanup    # 额外打一份「整理杂物」的 mv 计划（仍然只读）
python scripts/check-deploy-drift.py --no-nas     # 只查 B 方向（NAS 不通时也有用）
```

**退出码**：`0` 干净 · `1` 有需要人看一眼的 · `2` 环境问题（NAS 不可达 / `.env` 解析失败）。

> ★ **受管集合是从 `deploy.sh` 的 FILES 数组解析出来的，没有第二份拷贝** ——
> 复制一份就是又造一个漂移源。解析对不上（有 `::` 的行没解析出目的地）时**直接退出码 2**：
> 受管集合一旦悄悄变空，所有文件都会被误报成「未知」，那种假警报会把真信号淹掉。

**只有三种东西会出现在 NAS 上**：白名单里的（受管）、`KNOWN_NAS` 里逐条写明了理由的
（`.env`/`prowlarr/`/库/日志/缓存…）、以及**杂物**。第 4 种——没登记过的——才会报警，
提示二选一：**收进白名单**，或**加进 `KNOWN_NAS` 并写清它凭什么在那儿**。

> **杂物**（`.env.bak.*` / `.env_bak` 等任何 `.env` 备份变体、`build-farm.sh.bak.*`、
> `notify/probe-artifacts-*/`、`__pycache__/`）
> 只**报数**，不自动删。`--cleanup` 会打一份**只含 `mv`、不含 `rm`** 的计划 ——
> 搬进 `<compose>/_cleanup-<日期>/`（同文件系统内的 rename，原子且可逆），
> 确认无碍后在 NAS 上（或 DSM File Station，那边有回收站）删掉那一个目录即可。
> ⚠ **对 NAS 的 UNC 路径跑 `rm` 是禁止的** —— SMB 上没有回收站，glob 打错一次不可逆。
>
> ★ 杂物搬走**不等于**消失，哨兵的杂物计数**不会因此下降** —— 要等那一整个目录被删掉。
> 哨兵量的是「NAS 上有什么」，不是「看着乱不乱」。
>
> ★★ 而且 `__pycache__` **会自己长回来** —— NAS 上**真的在跑 Python**（`drive-loop`），
> 它 import 一次就写一次 `.pyc`。2026-09-12 晚实测：整理完计数 23，二十来分钟后复跑
> **变成 26**，多出来的 3 个正是 `drive-loop/…/__pycache__/` 下的。
> **所以杂物的下界不是 0，而是「正在跑的那几个模块」** —— 计数涨回去是**正常现象**，
> 既不是整理失败，也不是哨兵坏了。别把它当成"没清干净"去反复清理。

---

## 推前凭据扫描 —— 别把密钥推上去

`git push` 一旦把 cookie / passkey / apikey 推上去，**内容就已经在远端了** ——
删掉也只是多一个 commit，历史里还在。所以在 push **之前**拦一道。

```bash
python scripts/scan-secrets.py      # 0 = 可以推；1 = 有新引入的命中，别推
git push origin main                # 绿了再推
```

它**按值的形状**找，不按键名 —— 按键名匹配会漏掉嵌在结构里的凭据
（`TORZNAB_URLS` 里逗号分隔的多条 URL 各带一个 `apikey=`、Prowlarr 的
`indexer.fields` 里塞着 cookie/passkey、`options`/`fields` 里还嵌一层）。两道网：

| 网 | 怎么找 | 覆盖 |
|---|---|---|
| **① 值指纹** | 从本地 `.env` 提出凭据值，**只算 sha256**，再找仓库里哪一行出现了同样的值 | ⚠ **薄**，见下 |
| **② 形状正则** | 完全不依赖 `.env`：URL 里的 `apikey=`、`passkey=`、`KEY=` 赋值、`Bearer`、`Cookie` | ✅ **真防线** |

> ★★ **为什么①的"0 命中"几乎不算保证**：本地 `.env` 是**开发存根** —— 它的
> `TORZNAB_URLS` 用的就是 `.env.example` 里那两个 `xxxx…/yyyy…` 占位符（实测 sha256
> 相同），真实凭据只存在于 **NAS 的生产 `.env` 与 Prowlarr UI** 里，本地从来没见过。
> 所以拿本地 `.env` 去比，等于**拿一份占位符去查泄露**。
> **这道闸门挡住的东西，几乎全部来自②。** 详见 SUMMARY §18.15。

**它只报「命中/未命中」与 `文件:行号`，绝不打印命中到的那个值本身**（只打前 4 位 + 长度）。
所以它读生产 `.env` 也是安全的，输出可以直接贴给人看。

**退出码判的是「这次推新引入了什么」**，不是「仓库里有没有」：

* 命中所在的那一行**在 `HEAD` 里就有** ⇒ 早就推上去了，**不拦本次**（单列一句警告）；
* 只有**本次新引入**的才 `exit 1`。

★ 这条很要紧：本地 `.env` 是存根时，`.env.example` 里那两个占位符会和 `.env` 撞上 ——
按「仓库里有没有」判，**闸门会次次都红**，而次次都红的闸门等于没有闸门。

**三类"看着像、其实不是"的会被规则跳过，并连理由一起列出来**（不静默跳过 ——
静默跳过等于把闸门悄悄钻个洞）：

| 形态 | 例子 | 为什么不是凭据 |
|---|---|---|
| 读变量的代码 | `api_key=cfg.matcher.crossseed_api_key`、`process.env.X` | 是表达式，不是字面量 |
| 英文短语/占位符 | `please-change-me-to-a-long-random-string`、`yyyy…` | 随机凭据不会既无数字又无大写 |
| 同一字符重复 | `xxxxxxxxxxxxxxxx` | 占位符 |

> ⚠ **已知盲区**（写在代码注释里，不装作没有）：一个**真的**由小写字母和连字符组成、
> 每段都是纯字母的长密钥，这道闸门**抓不到**。真实凭据（hex / base64 / 混合字母数字）
> 几乎不长这样，所以这条换来的降噪远大于它带来的盲区 —— 但"几乎不可能"不是"不可能"。

回归在 `tests/test_scan_secrets.py`（**25 条断言**，8 组：阳性两条路 / 阴性 / 三类假阳性 /
形状层**单独**也要拦得住 / 输出接到 `NUL` 也一样 / 只拦本次新引入）。跑：

```bash
python tests/test_scan_secrets.py
```

---

## 通知 / 告警（NAS 侧发信）

无人值守最怕的不是出错，是**出错了没人知道**。这套东西负责在出问题时主动发邮件。

### 分工：跑批只写文件，发信才碰凭据

```
drive-loop.py ──写纯文本事件──▶ <compose>/notify/spool/*.txt ──▶ notify-spool.sh ──▶ 你的邮箱
   (NAS，零凭据)                    (NAS 上的普通目录)            (NAS，读 DSM 自己的 SMTP 配置)
```

**跑批那一侧一行凭据都没有**（不 import smtplib、不读密码）—— 邮件配置只在 DSM 里，
发信由 `notify-spool.sh` 在 NAS 上完成。代价是推送有延迟（NAS 侧定时轮询），
收益是**凭据从没离开过 DSM**。

> ★ 2026-09-12 电脑端退役前，这张图写的是「Windows 只写文件、NAS 才发信」，
> 中间那一跳走 SMB。现在跑批也在 NAS 上，spool 就是本机的一个目录（见上节）。

### 两条通道：坏消息立刻发，好消息进日报

| 事件 | 何时发 | 例子 |
|---|---|---|
| `alert` | **立刻发信** | `.env` 未生效（410/401/403）、索引器拉不到名字、连续 3 批失败、整批异常 |
| `batch` / `info` | **只进每日摘要** | 本批新增做种 11 部、全部包已无待搜项 |

同一个告警 key **12 小时冷却**（问题不修每天最多提醒 2 次，不会变成每 15 分钟一封骚扰）；
`batch` **不冷却** —— 每批都是新信息，冷却它只会让摘要数错。

> ⚠ **告警正文里的查证命令必须自带脱敏**（2026-09-13 起）。
> 告警是**给人照着敲的**，而人照着敲的时候正是最急的时候 —— 正文里那条命令
> **等于让程序替我们决定"这时候会把什么打到终端上"**。
> 具体栽过的：`索引器拉不到名字` 那条原本写 `docker inspect reseed-cross-seed | grep TORZNAB_URLS`，
> 而这个键的值是**逗号分隔的一串 URL、每条各带一个 `apikey=`**，那个 key 就是 Prowlarr 的
> 应用级 key —— 它**完全控制 Prowlarr**，Prowlarr 里存着所有 PT 站的 cookie。
> 现在的写法是 `… | sed -E 's/(apikey=)[^,&]+/\1<redacted>/g'`，并在正文里写明
> 「★ 先脱敏再看，**别把原样输出粘进聊天/命令行**」。
> ★ 拿掉那个值**不影响判读**：要判的是「容器里还剩哪个站」，靠 `apikey=` 这个键名和 `/N/api` 就够了。
> 规矩是**写在命令里**，不是写在"记得别看"里 —— 靠人记得的那种防护，这条链上已经漏过一次
> （见「推前凭据扫描」那节对①值指纹的批评：**覆盖薄的那道网，绿了也不代表安全**）。

### 每日摘要 = 心跳（死人来信开关）

**该来而没来的日报，本身就是 NAS / 任务计划出事的信号。**
摘要里写明「最近一次批次记录是几小时前」，用来区分「NAS 挂了」和「主机没开机」，
末尾还报告**通知链路自己的健康状况**：

```
── 通知链路 ──
发信方式  : python
spool 积压: 0 条告警
```

积压持续 >0 = 发信链路坏了（而那些告警你根本没收到）—— 这是唯一一个"只能靠摘要告诉你"的故障。

> ★★ **2026-09-13 更正：这句话原先的结论是「所以发不出去的告警**一直留在 spool 里重试、
> 绝不归档**（归档 = 静默丢弃）」—— 那个结论**正是那场邮件风暴的成因**。**
> 「归档 = 丢弃」在后半段是对的，错在把它当成了**绝对律**，于是漏掉了另一半：
> **「重试」本身没有上界**。一条永远发不出去的告警会随每 5 分钟一趟的排空任务
> **无限重发** —— 那天「站点退避中：HDtime」重发了约 6 次。
> 现在的口径是**两条都要**：
> - 发不出去 → 留在 spool 重试，**不丢**（这一半保留）；
> - 但连续失败到 `MAX_SEND_TRIES`（默认 3）→ **归档 + 记一条 `[未确认]` 告警**，
>   于是它会出现在日报的「告警明细」里 —— 「有一条告警你没收到」这件事
>   **既没被丢弃、也没被重发**，而是**变成了一条更响的告警**。
>
> 摘要里 `spool 积压: N 条告警` 旁边还会报「其中 M 条已经在重试」。
> 详见 SUMMARY §21.7 与 `tests/test_notify_drain.py`（28 条断言，**同一份测试
> 跑在修复前的代码上会精确复现「信发了、没记账、下轮再发」**）。

### NAS 侧一次性配置

1. **DSM → 控制面板 → 通知 → 电子邮件**：勾「**启用电子邮件通知**」，用
   「**自定义 SMTP 服务器 + 应用专用密码**」填好并存盘。
   ✅ **2026-09-12 实测已通** —— 配好之后脚本这边不需要再做任何事。
   ★★ **别去看 `/etc/ssmtp/ssmtp.conf`**：DSM **改过** ssmtp 的配置路径，它实际读的是
   `/usr/syno/etc/synosmtp.conf`。前者在本机是个 **0 字节空壳**，
   **邮件天天正常送达时它照样是 0 字节** —— 从它推断"邮件没配"必然出错
   （我这么错过一次，详见 SUMMARY §15）。那个文件里的密码还是**加密**存的
   （`eventpasscrypted`），所以「读 DSM 配置、自己发信」这条路也不存在。
2. 把 NAS 侧脚本同步过去 —— **已在 `deploy.sh` 白名单里**，一条命令：
   ```bash
   DST=//YOUR-NAS/docker_ssd/prowlarr_cross-seed_autohardlink bash deploy.sh          # 先看 diff
   DST=//YOUR-NAS/docker_ssd/prowlarr_cross-seed_autohardlink bash deploy.sh --apply   # 写入
   ```
   > ⚠ **别在批次运行中 `--apply`**（2026-09-12 踩过）：`sh` 是**边读边执行**脚本的，
   > 覆盖正在跑的 `run.sh` 会让它执行到错位的代码 —— `deploy.sh` 现在改成**原子替换**
   > （写 `.new` 再 `mv`，换 inode，老进程继续读旧内容），并会在**检测到心跳新鲜**时给出告警。
   > 但它不会拦你：那批会继续用旧脚本跑完。详见 **SUMMARY §17.2**。
   >
   > ⚠ 想拿临时目录演练（`DST=/tmp/x bash deploy.sh --apply`）之前请确认脚本是新的 ——
   > 旧版本的 `DST=` 会被 `scripts/.nasrc` **静默覆盖**，演练会**打到生产**。已修（§17.4.1）。
   > 现在规则是：**命令行 > `.nasrc`**。
   >
   > ⚠ ⚠ **`deploy.sh` 末尾那句「下一步 `--force-recreate`」不是每次都适用**。
   > 本轮同步的 4 个目的地里，只有 `<compose>/drive-loop/**` 那 3 个是**热路径** ——
   > 它们跑在 NAS 宿主机上（DSM 计划任务），**拷完即生效，下一次唤醒就用新的，不需要动容器**。
   > 第 4 个 `orchestrator/state.py` 是**构建上下文**副本：它进不了正在运行的容器，
   > 因为 `reseed-orchestrator` 是**一次性 CLI**（`ENTRYPOINT python -m orchestrator.main`，
   > 无 daemon），而 `cross-seed` 用的是官方镜像、**完全不吃我们的文件**。
   > **要更新它得 `docker compose build reseed-orchestrator`** —— `up -d --force-recreate`
   > 不带 `--build` 只会拿**旧镜像**重启，对一个一次性 CLI 等于什么也没做，
   > 代价却是白掀一次容器。**别照着那句话无脑跑。**

   然后在 NAS 上填配置：
   ```bash
   cd /volume2/docker_ssd/prowlarr_cross-seed_autohardlink/notify
   cp notify.conf.example notify.conf && vi notify.conf
   #   MAIL_TO   = 你的收件邮箱
   #   MAIL_FROM = ★ 必须与 DSM 里那个**认证账号完全相同**（逐字相同，包括域名）
   #               QQ/163/Gmail 都要求「信封发件人 == 认证账号」，不一致就会得到：
   #                 ssmtp: 501 Mail from address must be same as authorization user.
   #               ★ 这条 501 是**服务器回的**，说明连接和认证都成功了，只差发件人。
   #               留空也行（交给 ssmtp 用它自己配置里的默认发件人）。
   ```
   ★ `notify.conf`（含你的收件人邮箱）**不在白名单里**，`deploy.sh` 永远动不到它 ——
   和白名单"绝不覆盖生产独有内容"的原则一致（`.env` / `prowlarr/` 同理）。
   （不想用 `deploy.sh` 就手工拷这两个文件。）
3. **先验证，再挂任务**：
   ```bash
   sh notify-spool.sh --selftest     # 探测发信方式 / 配置 / 目录（**不判断**邮件配置对不对）
   sh notify-spool.sh --test-mail    # ★ 唯一的判据：真发一封
   ```
4. **DSM 任务计划**建**三个**任务，**用户都选 `root`**（要读 `.env` / spool，还要发信）：

   | 任务 | 计划 | 脚本 | 发送运行详情 |
   |---|---|---|---|
   | 排空 spool | 每 5 分钟 | `sh <路径>/notify-spool.sh` | **不要勾** |
   | 每日摘要 | 每天 21:00 | `sh <路径>/notify-spool.sh --digest` | **不要勾** |
   | 驱动跑批 | 每 15 分钟 | `sh <路径>/drive-loop/run.sh` | **不要勾** |

> ⚠ **三个都不要勾「发送运行详情」**：排空任务每 5 分钟一趟 = **一天 288 封**，
> 驱动任务一天 96 封 —— 那不是告警，是骚扰。结果一定是你去建一条
> 「来自 NAS 的邮件」过滤规则，**连真正的告警一起过滤掉**。
>
> 勾了的唯一好处是"能收到失败邮件"；但失败信号在下面这些文件里**更全**
> （还带退出码和时间线）。装上后想确认 DSM 失败时会不会发信，
> 把任务脚本临时改成 `sh /nonexistent` 手动跑一次就知道了。
>
> ★★ **更正（2026-09-13 晚）：这里原先写「任务脚本别把输出重定向到 `/volume1`」，
>    并说那正是邮件风暴的触发条件 —— 那句话是错的，而且错法和 §21.5 一模一样：
>    拿假设当结论写进了文档。**
>    晚上在 NAS 上回读了任务定义（`sudo /usr/syno/bin/synoschedtask --get`）：
>    排空任务的 `Command` 就是裸的 `sh /volume2/.../notify/notify-spool.sh`，
>    **一个重定向都没有**。所以"重定向到满卷"这件事，这条任务根本没做。
>
>    仍然成立、也仍然要守的是另一半（见 README 上文「磁盘」一节）：
>    `/volume1` **剩余 0 字节**是真的，**别往它写真实文件**。至于任务 stdout
>    落到哪儿 —— 那是 **DSM 自己**决定的，不在我们脚本里，所以这条任务
>    的 stdout 失败了我们也看不见。**别加 `> /volume1/xxx.out` 这类重定向**；
>    要看输出就看下面那些日志文件。
>
>    **还没判明的是**：风暴窗口（12:45–13:10，约 6 趟）里那条任务每趟的退出码。
>    这能把触发条件二选一定下来 ——
>    **退出码非 0** ⇒ 脚本是半途退出的（`say` 写 stdout 失败，`set -e` 带走整趟，
>    设置条件就是那个满卷）；**一路 Success** ⇒ 那就是 `send_mail` 假阴性
>    （脚本正常走完，只是信没出去，`continue` 后退出 0）。
>    取法：DSM 任务计划里那条任务的「运行结果」，或
>    `sudo find /var/log -iname '*sched*'` 后翻它。
>    ★ 两种触发条件的**可观测行为与修法完全相同**（都是"信发了、没记账、
>    下轮再发"），所以这个读数只影响"当年到底怎么坏的"，**不阻塞修复**。
>
> **运行详情不用靠邮件看**（SSH 关着也不再是障碍，这些文件经 SMB 直接可读）：
> - `<路径>/drive-loop/attempts.log` —— 每轮的起跑时间 + 退出码。四个信号分得很清：
>   没有 start 行 = 任务压根没被触发；**有 start 无 exit = 先别下结论**，
>   最常见的是**批次还在跑**（50 部 × `--interval 30s` ≈ 25 分钟起步，
>   再加回灌前的 `--settle 90s`），其次才是进程树被强杀；exit≠0 = 它自己出错了。
>   ★ 判活**别用** `ps | grep drive-loop.py` —— BusyBox 的 `ps` 只显示 `comm`
>   （也就是 `python3`），**看不到命令行参数**，怎么 grep 都是空的。
>   用 `pgrep -f drive-loop.py`，或看 `drive-loop/scripts/.drive-loop.state`
>   里的 `heartbeat_ts` 在不在涨（批次运行期间每 60s 刷一次）。
> - `<路径>/drive-loop/scripts/drive-loop.log` —— 完整日志（自轮转，5MB × 6）。
> - `<路径>/notify/log/` —— 发信记录。
>
> 真正**该**打扰你的东西（连续 3 批失败、`.env` 没生效、索引器拉不到名字）
> 由 notify 走**它自己的 SMTP 通道**发信 —— 那条路才是告警路径，
> 和 DSM 的任务邮件完全是两回事。

> ★ 实测这台 NAS（DSM 7.2 / 423+）发信走的是 **`/usr/bin/ssmtp`** —— 它存在，
> 而且**真的能把信发出去**（2026-09-12 实测收到）。脚本按
> `ssmtp → sendmail → msmtp → mail → python3+smtplib` 的顺序探测，本机命中第一个。
> （早先这里写着"一个发信程序都没有"，那是只查了 sendmail/msmtp 的误判，已纠正。）
>
> ★★ **同一个 `python3` 也是 drive-loop 的解释器** —— 于是它成了整条链路的
> 单点依赖：版本是 **3.8.15**（DSM 自带，Package Center 里没有更新的）。
> ✅ **2026-09-11 23:27 已在 NAS 上实测通过**（`sh drive-loop/run.sh --dry-run`
> → `attempts.log` 记到 `start py=/usr/bin/python3` + `exit=0`；
> 旁边生成了 `__pycache__/*.cpython-38.pyc`，版本由此坐实）。
> 这就是 `scripts/drive-loop.py` 顶部那行 `from __future__ import annotations`
> **不能删**的原因：本文件通篇用 `str | None` / `list[str]`，在 <3.10 上会在
> **函数定义时**当场求值并抛 `TypeError`（不是等到调用），而且崩在 `logging`
> 配置之前 —— **连一行日志都留不下**，表现就是「任务跑了，什么都没发生」。
> `state.py` / `notify.py` / `reseed-state.py` 早就带这行，drive-loop 是补的。
>
> 万一那台 NAS 的 python3 版本对不上（或 DS 升级后换了），症状同样会是「静默」，
> 所以 `run.sh` 在 shell 这一层另记了一份 `attempts.log`（见上）。
> 后备方案：把 `run.sh` 里的 `PY=` 指到一个 Docker 一次性容器
> （`docker run --rm -v ... python:3.12-slim python3 ...`），
> 或换 Entware 的 `python3`（`opkg install python3`，3.11+）。
> 你的 NAS 未必一样：`--selftest` 会打印实际探测结果。

### 通知开关（跑批那一侧）

```bash
python scripts/drive-loop.py --once --no-notify                  # 本次不发任何通知
python scripts/drive-loop.py --once --notify-cooldown-hours 1    # 临时缩短冷却（调试用）
python scripts/drive-loop.py --once --notify-spool "D:/tmp/x"    # 换个 spool
```

启动日志第四行会打 `通知: ✓ 启用 → <spool 路径>` / `✗ 已禁用` / `试运行（只打印，不写文件）`
—— 一眼看出通知通没通。环境变量 `NOTIFY_DISABLE=1` 等价于 `--no-notify`。

> ⚠ 电脑端退役后这些开关**主要是手动调试用**（正常路径是 DSM 计划任务跑 `run.sh`，
> 参数在 `run.sh` 里）。在 NAS 上直接跑就用 NAS 原生路径，没有 git-bash 那一层。

> 从 git-bash 传 `--notify-spool` 时**别用 POSIX 路径**（如 `/tmp/x`）：
> MINGW 会把它改写成 `\tmp\x`，Python 按当前盘解析成 `D:\tmp\x`。
> 用 `D:/tmp/x` 或 UNC。（退役前默认值就是 UNC 指向 NAS；现在默认值是 NAS 原生路径。）

> 通知坏了**不会拖垮跑批**：`notify.py` 吞掉所有异常，只是打一行
> `投递通知失败（忽略，不影响跑批）`。NAS 没挂上时批次照跑，只是没有通知。

---

## 安全

- `.env`、`cross-seed/`（含 cross-seed 自建的 db）、`prowlarr/`（Prowlarr 配置）**不要提交/外传**——含 cookie/passkey/apikey。
- PT 站凭据只进 **Prowlarr**；`:3060` 走局域网免密白名单（或 `.env` 里的密码），二选一。
- ★ **本项目从不生成、修改或伪造任何媒体数据** —— 只建立链接、注入种子、触发 recheck。
  是否"完整做种"由 **qB 的 piece 校验**决定，本项目不做保证、也不承担判断责任。
  完整边界见 **⚠ 免责声明与使用边界**。

---

## 当前状态与下一步（2026-09-14 更新）

> 本节是**操作入口**：怎么继续跑 / 卡住了看哪。
> 完整状态数据与逐项快照只维护在 **SUMMARY §13.7 / §15.6 / §17**，避免两处漂移。

### 系统现状（一句话）

**调度**：✅ **已完全迁到 NAS** —— DSM 三个任务已建，**2026-09-12 00:17 首次由计划任务自动跑完一批**
（23:51 那批，26 分钟，`成功 50 / 失败 0`），跨进程节流与 60s 心跳都正常。见下「把调度挂到 NAS 上」·
**通知**：✅ **端到端打通并实测收到邮件**（`--test-mail` → QQ 收件箱；批次通知也真的写进 spool 并被取走）·
**生产 NAS 磁盘上的 `.env`**：`DATA_DIRS` ✅ **1 条（已切农场）** · `LINK_DIR` ✅ **1 条** · `TORZNAB_URLS` ✅ **4 条**（HDtime `/1` + HDFans `/2` + BTSCHOOL `/3` + NanyangPT `/4`）·
**跑着的容器**：✅ **已重建过**（2026-09-12 上午实测改判）—— 容器内的 `DATA_DIRS` **就是农场那条**、
★ 但 `.env` 下午又改过（见 §18.9）：`/3`（BTSCHOOL）**又加回来了**，并且新加了 HDtime `/1` —— 所以容器**要再重建一次**才读得到 `/1`。
索引器 HDFans ✅ / NanyangPT ✅ / BTSCHOOL ✅ / **HDtime ⏳（cookie 已换、Prowlarr Test 通过，卡在重建容器）**。
状态机 `hlink/state.db` ✅ 605 部 ·
农场 `/volume1/video/download/reseed/reseed_farm` ✅ **475/475**（2026-09-12 15:50 复核，退出码 0）· qB :3060 的 **509/509 全部落在新根下** ✅（2026-09-12 16:25 复核：旧根 **0** 条、异常状态 **0** 条；新根下 BTSCHOOL 23 / HDFans 318 / NanyangPT 168，与站点侧种子数逐个吻合）。见 SUMMARY §18.9.2 / §18.10。

> ★ **改判（2026-09-12 上午）**：本节此前写的是「容器 `DATA_DIRS` 仍是 49 条、`/3` 还在 ——
> 只差一次 `--force-recreate`」。实际核对下来**那一步已经做过了**，三条独立证据：
> ① `.env` 的 `DATA_DIRS` 已是 **1 条**，而 cross-seed 日志里**实际出现**
>    `/volume1/video/download/reseed/reseed_farm` 路径 → 容器确实在扫农场；
> ② 近 3000 行 cross-seed 日志里 `410/401/403` **0 条**（此前 `/3/api` 会持续报 410）；
> ③ `drive-loop` 的「索引器自检」连续 **31 次通过**（若容器里还留着 `/3`，这里会警告）。
> 所以下面「收尾命令」**无需再执行** —— 保留仅作流程记录。
> 若与你的记忆不符，请优先复核 ①。
>
> ★ **2026-09-12 12:42 补：推断已变成直接证据。** 这一条原本靠日志**推断**（今天重搜日志里没有 410），
> 现在有了一次**主动的** `--force-recreate`，重建后新容器的启动日志里索引器**恰好两个**
> （`HDFans`、`NanyangPT (南洋)`），`/3/api` 在当日日志里 **0 次**，
> 且 `docker inspect` 回读到 `logging` 段生效。**再无疑点。**

> ★ **磁盘 vs 容器**是本项目头号复发坑：`.env` 改了不会自动生效，
> 必须 `up -d --force-recreate`（`restart` **不重新注入环境变量**）。
> `drive-loop.py` 的「索引器自检」（⑧）会在启动时扫日志自动喊出来，见 SUMMARY §13.10。

### 🔴 下一步（按优先级，2026-09-14 更新）

| 优先 | 做什么 | 为什么 | 详见 |
|---|---|---|---|
| — | ~~修「状态机把在做种的片子降级」~~ ✅ **已完成（2026-09-12 上午）** —— `SEEDING` 13 → 21（只补跑 sync）→ **201**（修掉真根因后 = 理论上限）；同批的退避检测、退避分级、`next_sleep` 接线一并修掉 | 原后果是过重搜周期会被**重复搜、白烧站点额度**（额度是本项目最高优先）—— 已消除 | §17.5 |
| — | ~~**容器日志上限**~~ ✅ **已完成（2026-09-12 12:42）** —— 批次间隙里跑了 `sudo docker compose up -d --force-recreate cross-seed prowlarr flaresolverr`，`docker inspect` 回读 = `{"Type":"json-file","Config":{"max-file":"3","max-size":"10m"}}`。★ 同一枪顺带清掉了 `/3/api` 的 410（当日日志 0 次）、新容器认得**恰好两个**索引器 | 原先全走默认 `json-file`，**没有任何上限**；`/volume1` 只剩 ~20 GB。★ 正因如此才只动容器日志 —— `drive-loop.log` 与 `cross-seed/logs/*` **都已在自我轮转** | §16.4.2 |
| — | ~~一次 `--force-recreate` 同时办完两件事（清 `/3/api`、`DATA_DIRS` 切农场）~~ ✅ **已完成** —— 2026-09-12 上午核对发现容器早已重建（证据见上「系统现状」的改判说明） | — | 本节的「收尾命令」（仅存流程） |
| — | ~~**目录搬迁收尾**~~ ✅ **已全部完成** —— 搬迁（**509/509 在新根**）✅ 容器已重建（4 个索引器全通）✅ drive-loop 已重新启用 ✅ 旧根已删 ✅ **最后一步也已推上去**：`drive-loop-nas.sh` 的 `--indexers` = `HDtime,HDFans,NanyangPT,BTSCHOOL`（+ `orchestrator/config.py` 的 `link_dir` 默认值修正）—— 2026-09-12 深夜核对 `check-deploy-drift.py` **两个方向都干净**，NAS 上就是这份 | 原后果：新站加进 Prowlarr 却漏在 `--indexers` 里 ⇒ **新站永远搜不到**（§13.10 那个坑的形状） | §18.10 / §18.11 |
| ~~**2**~~ | ~~**换一个站替换 BTSCHOOL**~~ ✅ **已关闭（2026-09-12 17:15）—— 是「当初的判据失效了」，不是「换好了」**：BTSCHOOL 现在**搜得出去、也匹配得到** —— `matched_indexers` = **23 部**，命中率 **23/46 = 50%**（四个站里最高），且这 23 部**全在 DC 包里、是那个包的最大贡献者**（压过 HDFans 的 21 部）；实时搜 `The Dark Knight 2008` 回 **24 条**、`Spider-Man No Way Home 2021` 回 **40 条**，Prowlarr 日志里它的 warn/error = **0**。要换它是因为 2026-09-11 它在 Prowlarr 出 CF 挑战页 → 后来重新启用、`/3/api` 加回 `.env`、容器重建，**那道坎过了，只是没人回来销账**。下站工具 `add-torznab-indexer.py --remove` 留着备用 | **真要换，按数据该换的是 `NanyangPT`（4/452 = 0.9%），不是它** —— 不过南洋可能只是片库对不上这批包，得先看目录 | §18.11.6 |
| ~~**3**~~ | ~~四个新功能~~ ✅ **四条全部实现并部署**（农场巡检的**前置**、额度感知、趋势、**把农场巡检挂成定期任务**）；★ 最后一条已于 **2026-09-12 14:30 在生产实跑验证**——见 **SUMMARY §16.2.2.1「已在生产验证」** | ~~⬜ 只写了设计，均未实现~~ | §16 |
| — | ~~**人工**：删掉 Windows 计划任务 `reseed-drive-loop`~~ ✅ **已确认根本不存在（2026-09-12 傍晚）** —— `schtasks /Query /TN "reseed-drive-loop"` 报「系统找不到指定的文件」，且全表 **375 个任务**里 `grep reseed` 命中 **0**。**不用删了** | ~~两边同时驱动会打出成片 429~~（风险已随退役消失） | §14.6 + §18.11.3 |
| **4** | **跑一次「农场那条防线」的对账** —— ✅ **前半已完（2026-09-12 晚）**：两个脚本已收进版本库并登记进漂移哨兵的「不部署」名单 —— `scripts/audit-found-lines.py`（对账 **a − b**）与 `scripts/audit-found-resolve.py`（对账 **b − c**，UNC 直读 `state.db`）。★ **判据本体已搬进 `orchestrator/state.py`**（见下一行），两个脚本现在是**薄壳**。**只剩后半**：等日志里出现 `[inject] … from dataDir (/volume1/video/download/reseed/reseed_farm/…)` 的 Found 行，重跑 `audit-found-resolve.py` 一次 | 2026-09-12 晚跑出的 a−b=0 / b−c=0 **只覆盖「原路径」这条制度**：1011 条 Found 行**全部**是 `[webhook]`、组5 **全部**是原路径 ⇒ `_RE_FOUND` 的 `[inject]` 分支、以及 `_resolve_searchee_to_pack()` 的**农场分支**流量为 **0**。**v3 农场那条防线至今没在生产里被走到过** —— 绿，但绿可能是因为规则压根没参与匹配。★ 脚本里那格 `组5 落在农场根下 0` 就是这道判据的自检：**它恒为 0 时，上面那个 0 覆盖不到农场** | §18.18.2 |
| — | **三条观测判据进生产（2026-09-12 夜）** ✅ —— ①口径改名 ②全场无人认领 ③a−b/b−c 进 metrics。判据本体全部落在 **`orchestrator/state.py`**（`count_found_lines` / `resolve_found_lines` / `unclaimed_searchees` / `pack_contexts`），接线在 `drive-loop.py` 的 `reconcile_watch()` → 每日台账 `metrics`，差不为 0 时立刻发 alert | **为什么判据必须住 state.py**：`drive-loop.py` 跑在 **NAS 宿主机**（`/usr/bin/python3`），而 `scripts/audit-found-*.py` 是 **LOCAL_ONLY**（`deploy.sh` 的 FILES 里没有它们）—— 那两个文件**根本不在 NAS 上**，且写死的 `//iSunker-DS423/...` 在 NAS 上不存在。`orchestrator/state.py` 被部署**两次**（构建上下文 + `drive-loop/orchestrator/`），是两侧**唯一都能到达**的地方 | §18.19 |
| ~~**5**~~ | ~~**决定要不要给 `SyncReport` 加一格 `other_pack`**~~ ✅ **已判：不加（2026-09-12 夜）—— 不是因为"设计洁癖"，是因为它算出来就是个常数**。实测（NAS 只读）：三包**共用一个 `farm_root`** ⇒ 〔生产口径〕下 `other_pack` = **dc 865 / frds 146 / mbf 1011**，恒非零、大体恒定，**没有信息量**。真正该加的判据是**「全场无人认领」**（三包 dpaths 并集 vs 库里 searchee 全集），它才恒为 0，且非零时每条都指得出名字 | ★ 同时更正一处分寸：`audit-found-resolve.py` 报的那个 `other_pack = 0` 是**它自己循环构造的产物**（所有包一起试、命中即停），**不是日志的性质** —— 全量口径的 0 与生产口径的 865 不可比。这跟 `NanyangPT` vs `NanyangPT (南洋)` 是**同一个形状**：一个名字盖了两种模型。两个脚本现在都把口径名印在数旁边 | §18.19.1 + `tests/test_reconcile.py` |
| — | **实测：全场恰好 1 条 searchee 无人认领** —— `/volume1/video/download/reseed/reseed_farm/0观影清单chrlee整理`，里面只有一个 `.xlsx` 清单、**三包都不认**、`searched`/`decisions` 里都没有它（所以今天不烧额度，是**潜伏**的）。这是新判据的对账基准：**报得出这个 1 才可信**，报 0 或 3 都说明判据自说自话 | 该计数器的期望值**指回了一条判据之外的真实记录** —— 这是三轮论证要的那个形状的第一个具体实例 | §18.19.2 |
| — | **观察：`title mismatch` 的量** —— **只记着，未处理**。`[inject] Skipping match … with /…/reseed/reseed_farm/… due to title mismatch`：07 时 **197** / 08 时 **311** / 12 时 **128** / 16 时 **202** / 17 时 **70**。摘要是中文名、候选是英文发行名，看着像同一类；cross-seed 给的口子是 `--ignore-titles` | 若确实在**整类地**否掉本该注入的候选，那是**注入量**的损失 —— 而注入量直接决定做种数。**先量、再决定要不要给口子**，所以只记不动 | — |

| **6** | **`packs` 差集改成「只报变化」+ 基线** ✅ **代码已部署**（NAS 上 md5 与本地**逐字节相同**）、`615b03d` 已推 main —— ★ **首读在 09-13 当天首批跑完时**：那天会打一次 `★ 首次读数 → 已记为基线，不告警`，此后**只有差集新增才响**。✅ **实测兑现（2026-09-13 00:38:28）**：`.reconcile.state` 里确实落了 `_packs_baseline = {"undriven": ["mbf"], "unreg": []}`，当批 TSV **只有** `unclaimed` 与 `streak` 两条 alert、**没有** `packs-mismatch` —— 首读静默采纳，与设计一致。★ 那个 `"undriven": ["mbf"]` 是 **#40 之前**的读数；09-14 那批会**缩回空集**，正好撞上 2026-09-13 新补的缩回分支（§20.9.8） | 原先 `mbf` 是**已接受**的现状，每天喊一次只会把告警喊成噪音 —— 而噪音的代价是**真出问题时没人看** | §20.1 / §20.2 |
| **7** | **决定 `mbf` 要不要排进 `--packs`** ✅ **已决：排进去（2026-09-13，#40）** —— `PACKS_DEFAULT` 已改为 `dc-collection,mbf,frds-top250-2024`。代价照旧：驱动名单与轮转集**同一份**，2 包 → 3 包把 dc/frds 的节奏从 1/2 压到 **1/3（−33%）**。★ 但这是**几轮，不是永远** —— 退出条件写在那个常量正上方：**HDtime 上也 0 匹配就把 `mbf` 移出名单**，频率立刻复原 1/2 | 理由**不是**"`mbf` 可能命中"（HDFans 实测 4 季包全 `Found 0 torrents`），是**不排它 = 一个不可观测的盲区**：它在 unclaimed / report / trend 上**全绿**，而"到底能不能搜到"永远没有读数。★ `HDtime` 2026-09-12 才进 `TORZNAB_URLS`，mbf 从没在它上面搜过（`UNMATCHED` 遇没搜过的索引器自动解锁）⇒ **驱动一轮**就能拿到那个此前拿不到的读数 | §20.9 |
| — | **HDtime 退避结束（~09-14 11:32）后验探针** —— 完整判据见 `tools/doc-audit/INDEX-USAGE.md`「⏱ 时间门控」 | 到点才发生、无其他落点；不挂会话 TaskList | `INDEX-USAGE.md` |

| **8** | **兑现 09-13 首读读出来的三条**（✅ 代码已改、测试已过、**已部署 2026-09-13 10:19**）—— ① `unclaimed` 也改成**只报新增**（不然那条 `.xlsx` 目录配 12h 冷却 = 每天响两次、永远）② `stats.aborted` 拆 `aborted_kind`：「站点退避超时」不再算「批失败」（09-13 的 TSV 里同一批既 `failed=0` 又「连续 3 批失败」，正文还指去 force-recreate）③ README 两处**期望值**修正（`fb_c_farm` 1→0；`1011` 是全天数、日报里应为不变式 `a == b`）。★ **部署必须等批次间隙**（覆盖正在跑的 `run.sh`/`drive-loop.py` 会打出假的 `exit=127`，见「还没做」第 8 条）—— 已于 **09-13 10:19** 在间隙里做掉 | 三条都是**名字/期望值指不回真实记录**：一条是噪音、一条是把良性念成故障、两条是把全天数当日初数 | §20.7 |

| **9** | **caps 告警的查证命令换成脱敏版** ✅ **代码已改、测试已过、已随第 8 条一起部署（2026-09-13 10:19）**：`索引器拉不到名字` 那条 alert 正文里原本写的是 `docker inspect reseed-cross-seed \| grep TORZNAB_URLS`，**原样会把凭据打出来**（那行里每条 URL 各带一个 `apikey=`，值就是 Prowlarr 的**应用级 key**，而 Prowlarr 里存着所有 PT 站的 cookie）。现在改成 `… \| sed -E 's/(apikey=)[^,&]+/\1<redacted>/g'`，并加一句「★ 先脱敏再看，**别把原样输出粘进聊天/命令行**」 | ★ 这是**告警正文在教人泄露凭据** —— 而且专挑人最着急的时候（索引器出问题、想赶紧查容器里还剩哪个站）。命令只换值、留 `apikey=` 与 `/N/api`，**判「哪个站」根本不需要那个值** | §20.8 |

| **10** | **IYUU 辅种的目录从哪来** ✅ **已溯源（源码三跳，无需改配置）** —— 辅种时 `savePath` = **qB 里同 infohash 那条已有种子自己的 `save_path`**（`Client.php:726` → `ReseedServices.php:379` → `ReseedDownloadServices.php:149`），**原样回灌**。⇒ IYUU 那三个路径框（监控文件夹/资源文件夹/种子文件夹）**在这条路上一次都没被读**，`cn_folder` 目录映射表也**零行** ⇒ **不需要手动配任何目录**。唯一参与路径决策的是「**创建多文件子目录**」→ qB 的 `root_folder`（已勾是对的：`HDFans` 下是 276 个子目录，内容就在 `<save_path>/<名>/`）；而 `autoTMM='false'` 硬关 ⇒ **分类的 savePath 不会覆盖**。「容器路径映射不一致」（IYUU 看 `/video`、qB 看 `/volume1/video`）**碰不到辅种目录** —— 它只对那两个空转的字段成立 | §21.2 / §21.3 |
| **11** | **收拢 `:3060` 上 22 条指向旧根的种子** ✅ **已完成** —— 902 条里 880 在新根 / **22 在旧根**（南洋 14 + HDFans 8，**全是 IYUU 的** tag，我们 599 条一条不漏已在新根）。`--all-tags` 收拢：预检 → `--limit 1` 试跑 → 全量，**902/902 全在新根，0 条指旧根**。★ 那 19 条 `error` 是**搬之前就 error 的**（试跑只对 2 个 hash 下过 setLocation）；error 总数 23→24（+1，未归因）。⬜ **剩两件收尾**：① 旧根盘上还留着残留 —— ★ **2026-09-13 11:36 复核：实测 8 条目**（HDFans 2 + 南洋 6），**8/8 在新根都有同名条目** ⇒ 原先记的「1 条 `149.V字仇杀队…` 只此一份」**不成立**：旧根那条叫 `V字仇杀队.…`（无序号前缀），而新根**两个名字都有**，拿 `149.` 那条去比当然「对不上」—— 又是「一个名字盖了两种模型」那个形状。★ 原记的「10 条目 / 8 同名 + 1 独有」本身**计数也自相矛盾**（HDFans 3 + 南洋 6 = 9 ≠ 10），一律以**实测**为准。现在**无任何种子引用**，★ **2026-09-13 实测：9 个文件 / 48.2031 GiB，9/9 全是独立副本**（旧根每个文件与新根同名文件逐个比 inode，**9/9 全不同**；且这 9 个 inode 在 `reseed/` 全树 5663 文件、`video/download` 全树**除旧根外 94 813 个文件**里**只出现在旧根自身**）⇒ **可释放 48.20 GiB**。⚠ 早先记的「可释放 44.60 GiB / 剩下 1 个是硬链接」**是错的**（把「清单里查不到源包」当成了「它是硬链接」，详见 §21.5）；且终究是 SMB 侧读数，**删前要在 NAS 上跑** `stat -c '%h %s %i %n'`（单行；输出别落 /volume1），`%h == 1` 才坐实。**只许在 NAS 上删**。★★ **2026-09-13 收尾：已删，但空间没回来 —— 上面那个「可释放 48.20 GiB」不成立。** 删前 `stat` 实测 9 个文件 `%h` **全部 = 1**，`--apply` 也报 `OK：已删`、目录确实消失；但 `/volume1` 可用空间 **31.91 → 31.76 GiB**（连量 4 次、值在动 ⇒ 不是 SMB 缓存），**48.20 GiB 一分没回来**。⇒ **「不是硬链接」与「删了能释放」是两件事**：**CoW / reflink 共享 extent 时 inode 不同、`%h` 也是 1**，行为却与硬链接一样 —— 正是 `rm-staging.sh` 头部自己警告过的那句，当时以为 `stat` 能兜住，**没兜住**。下次判据要换成能看见 extent 的：`sudo btrfs filesystem du -s <目录>` 看 **Exclusive** 列（≈0 ⇒ 与别处共享、删了不释放）。★ 另：SMB 侧**看不见** `@snapshots` 这类 `@` 前缀系统目录，所以"没有快照"不能靠 `ls` 排除。删除本身仍是对的（0 条种子引用旧根），只是**没换来空间** ② ✅ **已修（2026-09-13）**：`qbittorrent-reseed` 的 `/downloads` **没挂载**（只挂了 `/downloads/incomplete`）而默认保存路径是 `/downloads/` ⇒ 任何不带 savepath 的添加会落进**容器可写层**（宿主机看不见、重建即丢）。**走 qB API 改 `save_path` → `/volume1/video/download/temp`**（`app/setPreferences`，零停机、可逆，**没动 conf 也没动 compose**）。★ 验收判据是 qB 自己报的 `free_space_on_disk`：改前 **302.14 GiB**（= volume2，可写层所在卷）→ 改后 **0**（= volume1）⇒ 落点**真的**换了卷。落点只能选在 `/volume1/video` 下，因为**硬链接不能跨卷**。详见 §21.6.1 | §21.6.1 |

| **12** | **qB（:3060）校验队列疑似卡死，卡住 145 条** —— 偏好里 `max_active_checking_torrents = 1`，而 **145 条 IYUU 种子**挤在 `checkingDL` 排队、**8 小时一步没挪**（另有 `error` 24 / `stalledDL` 1，全部 added 09-13 02:35–03:17，`pieces_have=0`、共 170 条 0 字节）。已排除三种：497 个文件逐个 `stat` **全部大小相符**、`save_path` **无映射失败** ⇒ **不是「保存路径错 / 根目录差一层 / 缺文件」**。★ **待坐实的一步（写操作，1 条，可逆）：对任意一条卡住的种子手动「强制重新校验」** —— 几秒内跳 100% ⇒ 坐实是**校验队列/校验器**卡住，不是内容问题；**未坐实前这只是「最符合证据的解释」** | 卡住的不是 1 条而是 **145** 条；校验不完就不做种，而**做种数正是这条链的产出** | — |

| **13** | **`movie.matched_indexers` 全库恒空：查清 + 修（#73 / #75）** —— ✅ **代码已改、测试已过（2026-09-14），★ 未部署**。查下来**不是**「判据没被调用」：拿 09-12 的日志跑**现在**的解析函数**有值**（1011 行命中，归片后带站名 —— 南洋 285 / HDFans 448 / HDtime 44）。真根因是两段：**① 输入源易失** —— `facts.found` 的**唯一**输入是**当天**的 `info.current.log`（`searched` / `hashes` 都有 cross-seed.db 这第二条腿，**`found` 没有**）；**② 写入端不合并** —— `sync_movie` 对 `matched_indexers` 是**整行覆盖**，而同一个函数里 `indexer_seen` 是**合并**的、`searched_indexers` 是 union 的（**两列语义相同、写法相反 = 遗漏，不是设计**）。⇒ 日志跨天一滚动（`info.current.log` → `info.YYYY-MM-DD.log`），下一次 sync 就把整列抹成 `[]`；而 SEEDING 的行**不会再被搜** ⇒ **永不恢复**。生产见证：同一张 605 行的表 **09-12 非空 215 部 → 09-14 变 0 部**。修法：**与旧值取并集**（**不采用**「喂全部 `info.*.log`」—— 成本随保留天数涨，且仍不覆盖被轮换掉的），并在源头**不再造 `"A\|B"` 合体标签**（读侧 `_sites()` 按 JSON 数组**逐项**取，不认里面的 `\|`；老库残留的合体标签在写入端**拆开**再并）。回归 `tests/test_matched_indexers_union.py`（15 条，**红过再绿**：回退那两个 hunk ⇒ 红 4 条）| ★ 这一列是 `report` 的**站点归属**与 `trend` 的**按周 × 按站**换站决策表的输入 —— 它恒空等于**那些判据都在沙上建塔** | §22 |
| **14** | **两件等拍的** —— ① **17:40 观测**（Prowlarr 放行 HDtime 之后 cross-seed 动不动）：两个读数 `python scripts/prowlarr-indexerstatus.py`（② 机制）与 `python scripts/check-indexer-timestamps.py`（③ 机制）。★ **时刻到 ≠ 条件成立** —— 窗口本身已经变过一次（`disabledTill` 记的是 24 h，而 6 h 那个只是 14:27 的读数），**先读再判** ② **存储分析器互校**：三步探针已跑完，结论是**报告里没有可用空间**（`Used` 只有百分数，0.1% on 61.4 TB = 61 GB）⇒ **等拍**：换对照量还是换报告 | ① 这是唯一能把 `ERR-SVC-17` 里那处**剩余推断**（cross-seed 是原样转抄 `Retry-After`，还是按自己起算点重算）验掉的机会，**顺手答** `#60`（放行后动不动 ⇒ snooze 该怎么处置）；判据见那两条 | §22 · `INDEX-USAGE` §八 |

| **15** | **ENVIRONMENT 卷归属复核：结论对、一处路径错、一味药没标适用范围** ✅ **已完成并推送（2026-09-14，`ead756d`）** —— ① **修路径**：`A.3` 的 `/volume1/docker_ssd` → **`/volume2/docker_ssd`**（同文件 212 行与归属表本来就是 `/volume2` ⇒ 三处自相矛盾；★ 而这行犯的**正是它上文 `ERR-DSM-03`/`ERR-FS-02` 登记的那个错**）② **补两条 Windows 侧通路**：`df -h <UNC>`（按底层文件系统分组，实测 **8/8 正确**）与 Storage Analyzer 的 `share_list.csv` 的 **`Volume` 列**（SMB、无凭据、每周三 04:07）—— 原来的 `ContainerManager/all_shares` **只在 NAS 上**读得到，本机没有 SSH ③ **`stat -c %d` 补适用范围**：**只在 NAS 侧成立**；Windows/SMB 侧实测**十个共享十个互不相同的号**（含同卷的 `video`/`Download`/`homes`/`drive`/`web`/`docker`）⇒ **分辨力为零**，对照量用 `df`；并记下 `build-farm.sh` 自承可从 SMB 跑 ⇒ 真那么跑会把**每个源目录**判成「不同卷，跳过」 | 一份专门教人「别按路径前缀判同一块盘」的文档，**照着错法写了一行**；而那枚被开了 4 处药的探针，**只在一个机器上有效** | §23.1 · §23.2 · `ENVIRONMENT.md` `A.3` |
| **16** | **同族还剩三条（等拍：共享可见性 / 探针可用性）** —— ① **`/volume1/docker`「不是共享文件夹」×4 处**：实测 `//iSunker-DS423/docker` **UNC 可达**（负对照：不存在的共享名会报 `No such file or directory`，所以不是幻觉），DSM 自己的 `share_list.csv` 也把它列为 **Shared Folder / Volume 1**；而 `net view` 与本机 `ls` **都只列 5 个**（实际至少 11）⇒ **枚举里看不见 ≠ 不是共享文件夹** ② **`ERR-HW-03` 里承重的 `net view`**：本机 `net view '\\iSunker-DS423'` 报 **1702 绑定句柄无效**，换 `net view iSunker-DS423` 才通 ⇒「没有任何备份共享」有**探针跑不通被读成没有**的嫌疑 ③ **`SUMMARY` 的 ⬜② 可结案**：`//iSunker-DS423/docker` 根**没有** `.probe_done_*`，且**不需要 SSH** | ★ 三条是**同一个形状**：文档自己写着「看不见 ≠ 不存在」，却在 8 行之外用「看不见」断言了不存在 | §23.3 · §23.4 |
| **17** | **一份「日报加各包进度」的方案：审出 8 条，★ 全部未落笔**（`pack_progress`）—— 骨架可用、口径选对了（`movie` 表 =「声明」，**且 `register_dirs()` 生产里只有 `init` 一个调用点** ⇒ 确实稳定），但：**① 例文真假日数据混着**（三个总数 **486/115/4 全对**，做种数写 `201/52` 而实测 **323/68** —— `201` 其实是 **`trend()` 的量**）**②「metrics 加两列」是错的**（它是 notify 事件里的**一个 `k=v` 字段**，不是 TSV 的列）**③ 两处引用错锚**（`#62` → `ERR-AI-01`/`n/a` 约定；`§16.3` → `§16.1.3`）**④ 新鲜度那条反了**（日报是在**该批回灌之后**投的；真风险是「当天没跑过的包数停在上次 sync」⇒ 改用每包 `pack.scan_finished_at`）**⑤ 包名含空格**是隐患（`_clean_line` 不动键）**⑥ 新节要放进同一个 `with S.StateStore`**，否则读库失败会带走整份日报 **⑦ 落笔前先判能否复用** `sync_pack` 的计数 **⑧ 判据①的名字**（`pack.roots` 是路径数组不是数）| ★ 这套方案的形状很典型：**机制名全对、判据全可跑通**，错的都在「想当然」那一层 —— 把 dict 说成列、把回灌前的时刻说成回灌后、把一个趋势数当成每包数 | §23.5（TaskList #90–#97）|

#### ★ 09-13 首读实测：`unclaimed=1` 那条告警**不是修复失效**（2026-09-13 复核）

00:38:28 的 TSV 里有两条 alert：`unclaimed=1`（`农场里有 1 条 searchee 谁都不归`）和
`streak=3`。**第一条字面上正是 #47 要消掉的噪音**（每天响两次、永远），所以它很容易被读成
「修复没生效」。**它不是。** 物证来自 `.deploy-backup/` —— 备份存的是**被覆盖前**的内容，
所以每份备份恰好是**那一次部署之前、磁盘上正在跑的那份代码**：

| `.deploy-backup/` | `_unclaimed_baseline` | `_packs_baseline` | `aborted_kind` |
|---|---:|---:|---:|
| `20260912-231726` | 0 | 0 | 0 |
| `20260913-101900` ← **00:38 在跑的就是这份** | **0** | 2 | **0** |
| `20260913-105013` | 2 | 3 | 3 |

⇒ 00:38 那一刻，**packs 基线已在**（09-12 23:17 部署，所以首读静默、没有 `packs-mismatch`），
而 **`unclaimed` 基线还没上线**（09-13 10:19 才部署）⇒ 那条告警是**旧行为**，符合当时的代码。

★ 为什么非要把这段写下来：**这是一份"只凭 TSV 就能得出错误结论"的记录。**
不写的话，下次翻到 00:38 那行会以为 `unclaimed` 的修复白做了 —— 而真相是
**它到那时为止一次都还没在生产上执行过**（10:19 上线，11:30 之前没有任何批次跑完）。

> **另外两条不在这里重复登记**（各自已有唯一出处，免得两处漂移）：
> * 「搬迁后次日 01:45 之后复核 `IYUU自动辅种` 条数是否仍在增长、首读 **09-14 凌晨**」
>   —— 见下面 **「还没做」** 一节的「还剩三件」列表（已自动化，进每日台账，基线 100 条）。
> * 「暂存区 / 回收站清理」 —— **2026-09-13 已做完**：`_cleanup-20260912/` 与
>   `#recycle/env-bak-20260912/` 用 `rm-staging.sh` 真删，另手删 3 条回收站残骸。
>   详见 **「还没做」** 一节那条 ✅（含读数与「别放宽闸 ③」的理由）。
>   `__pycache__` **不清**——它会自己长回来。

### 🆕 日常看板（2026-09-12 新增，都在 NAS 上跑）

```bash
D="//iSunker-DS423/docker_ssd/prowlarr_cross-seed_autohardlink"

# 新增做种趋势：按 (周, 站) —— 换站决策看这个，别看某个瞬间的快照
python scripts/reseed-state.py --db "$D/drive-loop/hlink/state.db" trend --weeks 8 -v

# 站点额度台账：滚动 24h 的各站搜过多少「部」（★不是查询次数，也★不是站点余额）
python scripts/reseed-state.py --db "$D/drive-loop/hlink/state.db" \
  quota --db-path "$D/cross-seed/cross-seed.db"

# 农场漂移：有漂移会返回退出码 1（以前恒返回 0，等于永远不报警）
# ★ 环境变量必须写在命令**前面** —— 写在后面会被当成脚本的参数
COMPOSE_DIR="$D" FARM="//iSunker-DS423/video/download/reseed/reseed_farm" \
  sh "$D/build-farm.sh" --verify --map "/volume1=//iSunker-DS423"
```

回**电脑上**再跑两条（查的不是农场，是「NAS 与仓库」本身、以及「待推的东西里有没有凭据」）：

```bash
python scripts/check-deploy-drift.py      # 0 干净 / 1 有要看的 / 2 够不着 NAS
python scripts/scan-secrets.py            # 0 可以推 / 1 有新引入的凭据形状命中
```

日报里**自动**带「每日台账」（额度 + 趋势），每 24 小时最多一条；
「某站此刻正在退避」会**立刻**发告警（按站 12 小时冷却）。

> **★ 对账八格怎么读**（每份日报的 `metrics` 里，TSV 流水只记数字不记正文）：
>
> | 格 | 期望值 / 基线 | 它指回的真实记录 |
> |---|---|---|
> | `fa` / `fb` / `fd` | ★ **不变式：`a == b`、`fd = a − b = 0`**（**不是** 1011 —— 见下） | 当日 `info.current.log` 里的 `Found` 行 |
> | `fb_c_all` / `fb_c_farm` | `0` / `0`（全量口径 / 农场行计数） | `hlink/state.db` 的 `pack`+`movie` |
> | `unclaimed` | **基线 1**（`0观影清单chrlee整理`），**只报新增** | 农场里那个只有 `.xlsx` 的目录 |
> | `packs_undriven` / `packs_unreg` | **基线 0 / 0**（2026-09-13 起 —— `mbf` 已排进 `PACKS_DEFAULT`；此前恒为 1 / 0） | `--packs` 的实际取值 vs `pack` 表 |
>
> ★ **为什么 `fa` 不是 1011**：日报在**当天首批**跑，而它读的是**当日日志**
> （`info.current.log` 按天轮转）⇒ 天然是「**今天 00:00 到现在**」，会随一天推进而涨。
> 所以日报里 `fa` 总是个小数字（实测 09-13 首批 = **76**）。
> **1011 是 09-12 的「全天」数**（手工核时读的同一个文件、读得晚）—— 拿它当日报的期望值
> 是**把一条全天记录写在了日初的读法旁边**。要核全量用 `scripts/audit-found-lines.py`。
> ★ `fb_c_farm` 恒为 `0` 是**自检**：它一旦长期为 0，就说明**农场那条防线还没被走到**
> （`_RE_FOUND` 的 `[inject]` 分支 / `_resolve_searchee_to_pack()` 的农场分支流量为 0）
> —— 上面那个 `fb_c_all = 0` 此时**覆盖不到农场**。绿是真的绿，但它管不到那条路。
>
> **三种"读不到"必须分开看**，混起来就会把「判据坏了」念成「今天没事」：
>
> * **`n/a` = 这一路没输入**（没跑到），**不是**"没事"。括号里会跟上
>   `上次成功 X 前`；若**从未**读到过则写 `★ 从未成功读到过` ——
>   连续几天 n/a 是**判据长期失效**，昨天还好今天抖一下是**偶发抖动**，
>   两句话指向完全不同的处置，所以必须指得回时间。
> * **`0` = 跑了、确实没有**（判据是好的，只是今天真没发生）。
> * **`unclaimed` 报 `0`** —— 那是**跑了、且比基线少**（那条 `.xlsx` 被清掉了？）
>   ⇒ 静默采纳新基线，**但正文会把「比基线少 N 条」写出来**，所以不是无痕；
>   将来**再长回来会被抓住**（当新增报）。
> * **`unclaimed` / `packs_*` 都只报「变化」，不报「现状」**（2026-09-12 深夜 / 09-13 改）：
>   现状（农场里那条 `.xlsx` 谁都不归；`mbf` 登记了却一直没被驱动是 **2026-09-12 之前**的现状
>   —— 09-13 已排进 `--packs`）是**已接受**的，
>   非空就每天喊一次只会把告警喊成噪音 —— 而噪音的代价是真的出问题时没人看。规则：
>   **出现基线里没有的 → 发 alert**；与基线一致、或缩回基线之内 → 不发。
>   基线存在 `.reconcile.state` 的 `_packs_baseline` / `_unclaimed_baseline` 里
>   （**不进代码** —— 写进代码就分不清「回到基线」和「判据死了」），
>   缩也采纳新基线，所以它**再长回来会被抓住**。
>   ★ **不告警 ≠ 看不见**：日报正文每天照旧打印完整差集 / 完整清单。
>   ★★ **不告警也 ≠ 跑了** —— alert 沉默有**四个**来源：
>   ① 与基线一致 ② 缩回基线之内 ③ 状态库读不到（正文写「没跑成」）
>   ④ 调用方没给 `--packs`（正文写「跳过」）。**后两种同样不发 alert**。
>   所以「沉默 = 没事」**要多读一步**：看正文那一行**有没有值 / 是不是 `n/a`**。
>   反过来，**响铃不需要附加判断** —— 响 ⟺ 真的算了、且真有新增。
>   （`n/a` 的读法见上面那条：`n/a` = 没跑到，**不是**「差集是空的」。）
>
> 差不为 0 时**立刻发 alert**，`key` 就是排查入口：`log-parse-miss`（正则没吃下形状行）、
> `reconcile-controls`（判据压根没走到）、`reconcile-empty`（真没搜出去）、
> `unclaimed-searchee`（★ 只在**新增**时发）、`packs-mismatch`（★ 同上）。

> **★ 「连续 N 批失败」不一定是失败**（2026-09-13 改，两个 key）：
>
> | key | 什么时候发 | 是什么性质 |
> |---|---|---|
> | `consec-abort` | 连续 3 批**真失败**（webhook 400/401/403、或整批抛异常） | **真故障** —— 去查鉴权/路径/`.env` 是否 force-recreate |
> | `consec-backoff` | 连续 3 批**提前收工**（站点一直在退避，等到 `--max-wait` 就先收工） | **良性** —— 条目没失败，剩下的下轮重排；长期如此才考虑摘站 |
>
> ★ **2026-09-16 起「提前收工」只发生在"全都退避"时**：还剩健康站就照发，不算收工。
> 所以这个计数从此**只在真有事时才涨** —— 09-13~09-15 那种「一个站被禁 24 小时、
> 另外三个干等」的日子不会再刷它。依据与实测见 SUMMARY §11.13。
>
> 原先只有一个计数、只看 `stats.aborted` 的真假 ⇒ 实测 2026-09-13 的 TSV 里
> **同一批**既写 `ok=22 failed=0`、又写「连续 3 批失败（索引器 HDtime 要等到 …）」，
> 而它的正文还把人指去查 `force-recreate` —— **名字和指向都是错的**。
> 现在分开计数（`DriveStats.aborted_kind`），**两个计数互不干扰**，
> 只有**正常跑完**才一起清零 —— 所以「中间夹了几批退避」**掩盖不了**真故障。
> 两种混着出现时标题会补一句「共 N 批没跑成」，免得把 N 念成"连续"。

> **趋势里的两个口径别搞混**：`本周新增做种 N 部` 的 N 是**按片去重**的，
> 而下面按站列的数字之和**会比它大** —— 一部片同时在两个站做种时，两个站各记一次
> （渲染里会自动补一行说明，只在"和 > 总数"时出现）。

### 三个包（**数字会变，别信写死的**）

阶段分布**一律以状态库为准** —— 下面这张静态快照在 2026-09-12 已实测**过期**，不再维护：

| 包 | 单片 | 结构 |
|---|---|---|
| `frds-top250-2024` | 486 | ✅ 根目录子目录即发布名 |
| `dc-collection` | 115 | ⚠ 根下多一层中文标签，见「多包支持 → 嵌套结构」 |
| `mbf` | 4 | ⚠ HDFans 上 **0 匹配**（4 个季包全 `Found 0 torrents`）；**2026-09-13 起已排进 `--packs` 被驱动**（#40）—— 若 HDtime 上也 0 匹配就移出名单 |

```bash
DB="//YOUR-NAS/docker_ssd/prowlarr_cross-seed_autohardlink/drive-loop/hlink/state.db"
python -c "
import sqlite3; c=sqlite3.connect(r'$DB')
for r in c.execute('SELECT pack,stage,COUNT(*) FROM movie GROUP BY pack,stage ORDER BY pack,stage'): print(r)"
python scripts/reseed-state.py report --pack frds-top250-2024    # 带按站重搜周期表
```

> **⚠ MBF**：HDFans 上已实测 0 匹配。状态已是 `UNMATCHED`，加新站后会自动解锁、**不会重复浪费额度**。

### 怎么继续跑（两种方式）

**方式 A：自动续跑（推荐）**

```bash
# 真跑一轮（当前包下一批，约 24 分钟）
python scripts/drive-loop.py --once --indexers HDFans,NanyangPT --limit 50

# 循环跑：DC↔FRDS 自动轮流，间隔按站点反馈动态调整（45min~4h）
python scripts/drive-loop.py --indexers HDFans,NanyangPT
```

> `drive-loop` 已内置 `--db-path` / `--qbit-url` 的**候选探测**（`CROSSSEED_DIRS`），
> 所以**回灌不会漏参数**。
> ★ 2026-09-12 电脑端退役后 `CROSSSEED_DIRS` 只剩 NAS 原生路径一条 ——
> 原来还有一条 UNC 兜底（Windows 经 SMB 跑时用），现已注释。
>
> **★ 2026-09-11 起，调度跑在 NAS 上**：DSM 任务计划每 15 分钟执行
> `sh /volume2/docker_ssd/prowlarr_cross-seed_autohardlink/drive-loop/run.sh`。
> ★ **2026-09-12 电脑端彻底退役**（包装器与 PC 侧状态已删，见「⛔ 电脑端已不参与」）。
> 当初搬走的原因不是性能，是 Windows 侧**批次会静默消失**，
> 查下去是**两个独立的坑**（完整证据与复现见 SUMMARY §14）：
>
> * **`<StopOnIdleEnd>true`**（当场读任务定义确认）：你一动鼠标/键盘，
>   Windows 就 `TerminateProcess` 整个任务实例 —— 没有 traceback、没有
>   finally 收尾、状态文件里 `running_pid` 永远挂着，之后每轮都空转。
> * **包装器 `.cmd` 是 LF 行尾**（这一条是 2026-09-11 深夜改包装器时引入的）：
>   cmd.exe 按字节块读批处理文件，LF-only 会让它**从某行中间开始执行** ——
>   `REM` 注释里的英文单词被当成命令跑，前面的 `set` 全部丢失，于是留下
>   `exit=9009` + `'""' 不是内部或外部命令`，且**有 `exit=` 没有 `start=`**。
>   已修（转 CRLF）。`deploy.sh` / `run-batch.sh` 的 CRLF 行尾也一并归正成 LF。
>
> `--once` 的自我节流（有人在跑 / 距上批结束不足 30 分钟 → 直接退出）和
> **心跳超时接管**（卡死 10 分钟后下一轮自动接管）两边通用，
> 所以 15 分钟一次**不会**和 24 分钟一批重叠。这也是没有改用
> 「常驻容器跑自带循环」的原因 —— 常驻进程卡死就没人接管了。
> 真实进度一律以 `drive-loop.log` 为准，**别看终端**（输出会被块缓冲吞掉，SUMMARY §13.8）：
> `<compose>/drive-loop/scripts/drive-loop.log`。
> （退役前 Windows 侧那份是 `scripts/drive-loop.log`，**已删**。）
>
> ⚠ 万一要**回退到 Windows 跑** —— 包装器 `scripts/drive-loop-once.cmd` **已删**，
> 但它踩过的两个点必须守住，否则回退会原样再踩一遍（脚本本体在 git 历史里）：
> 1. **别把包装器换成直接指向 `python.exe`** —— python 路径里有中文用户名，
>    经 `schtasks` / MINGW 传递会被搞坏；包装器要用 `%USERPROFILE%` 让 cmd.exe
>    在**运行时**展开，任务定义本身保持纯 ASCII。
> 2. **包装器必须是 CRLF 行尾** —— LF-only 会让 cmd.exe 解析错位、整行命令失效
>    （现象：`exit=9009` 且 `attempts.log` 里没有 `start` 行）。改完包装器务必确认：
>    ```bash
>    python -c "b=open('scripts/drive-loop-once.cmd','rb').read(); print('CRLF',b.count(b'\r\n'),'LF',b.count(b'\n')-b.count(b'\r\n'))"
>    # 要 CRLF 59 / LF 0
>    ```
> 3. ★ 还有 `os.kill(pid, 0)` 那一支 —— 它在 POSIX 上是"探测存活"，
>    在 Windows 上**会真的把进程杀掉**，必须切回 `tasklist` 分支
>    （代码在 `pid_alive()` 里，连 `import subprocess` 一起打开）。

### 把调度挂到 NAS 上（✅ 已完成 —— 2026-09-12 凌晨）

代码、状态库、DSM 计划任务**都已就位**并实测跑通：

- `deploy.sh --apply` 已执行（`drive-loop/` 下 6 个文件）；
- `hlink/state.db` 的 605 部已迁到 `<路径>/drive-loop/hlink/state.db`，
  `local_roots` 已从 UNC 归一成 NAS 原生路径；
- DSM 三个任务已建（见「通知」那节的任务表）；Windows 侧任务已 `DISABLE`；
- ✅ **2026-09-11 23:51 / 2026-09-12 00:01 实测**：手动触发的那批正常跑起来
  （`attempts.log` 有 `start py=/usr/bin/python3`），下一次唤醒时正确地打出
  「上一批（pid …）仍在运行，跳过本轮」—— **跨进程节流工作正常**。

**★ 建任务时最容易踩的一脚：「最后运行时间」的小时位存错。**

`synoschedtask --get` 实测到的**错误**状态：

```
reseed-drive-loop    Run time: [2]:[0]    Repeat every [15] min until [2]:[45]
reseed-notify-drain  Run time: [0]:[0]    Repeat every [5]  min until [0]:[55]
```

—— 两条任务分别**只在 02:00–02:45 / 00:00–00:55 之间**才触发，于是表现成
「**手动点『运行』能跑，计划却永远不自动触发**」。

正确值：**小时位明确设成 `23`** —— `drive-loop` → 最后 `23:45`、每 15 分钟；
`drain` → 最后 `23:55`、每 5 分钟（`digest` 每天 21:20、无 repeat，不受影响）。
改完务必复核：

```bash
sudo /usr/syno/bin/synoschedtask --get | grep -A 12 'reseed-drive-loop'
#  期望看到： Repeat every [15] min (s) until [23]:[45]
```

**排错**：`attempts.log` 里 `exit=127` = `run.sh` 找不到 python3 或脚本；
`exit≠0` 且有 traceback = python 层出错（最可能是版本，见「通知」那节关于 3.8 的说明）；
**压根没有 `start` 行** = 任务没被触发（没启用 / **计划窗口不对** / 脚本路径错）；
**有 `start` 没 `exit`** = **先别下结论**，最常见的是**批次还在跑**（见上）。
完整排查表见 SUMMARY §14.5；计划窗口这个坑见 SUMMARY §15.5。

**方式 B：手动单批（原来的做法）**

```bash
URL=http://192.168.0.7:2468
KEY=<CROSSSEED_API_KEY>
DB="//iSunker-DS423/docker_ssd/prowlarr_cross-seed_autohardlink/cross-seed/cross-seed.db"
Q="http://192.168.0.7:3060"          # ★必须带 --qbit-url，否则 SEEDING 被误降级！

python scripts/reseed-state.py drive --pack dc-collection --indexers HDFans,NanyangPT --limit 50 \
  --url $URL --api-key $KEY --db-path "$DB" --qbit-url $Q --apply
```

**一批做完重跑同一条命令就自动推进**，不用记批次号。**先 `--plan` 确认再加 `--apply`**。

### ⛔ 电脑端已不参与（2026-09-12 退役）

**一句话**：跑批、发信、建农场全在 NAS 上；Windows 只剩 **`deploy.sh`**（把代码推上去）、
**`check-deploy-drift.py`**（查两边一不一致）、**`scan-secrets.py`**（推之前扫一遍凭据）、
**`audit-found-*.py`**（对账 `Found` 行：只读 NAS 的日志与库）四个用途。

为什么单独写一节：代码里**到处**都有"Windows 也能跑"的痕迹（UNC 路径兜底、
`tasklist` 判活、计划任务包装器、git-bash 路径转换的告警……），
不写清楚的话，下一个人会以为这条路还活着，然后照着它去配、去调、去踩已经踩过的坑。

**① 退役了什么**

| 东西 | 处置 |
|---|---|
| `scripts/drive-loop-once.cmd` | **已删**（原 Windows 计划任务的入口） |
| Windows 计划任务 `reseed-drive-loop` | 已 `/DISABLE`，**目标文件已删 → 现在是个悬空任务**。彻底删需要管理员权限，见下 |
| `scripts/drive-loop.{log,attempts.log,task.err}`、`.drive-loop.state`、`.notify.state` | **已删**（PC 侧运行时残留） |
| `drive-loop.py` 的 `CROSSSEED_DIRS` UNC 兜底 | **已注释**（标记 `[电脑端已退役 2026-09-12]`） |
| `drive-loop.py` 的 `pid_alive()` tasklist 分支 + `import subprocess` | **已注释**（同上标记） |
| `notify.py` 的 `SPOOL_CANDIDATES` UNC 兜底 | **已注释**（同上标记） |

> 注释保留而不是删除，是因为它们各记着一个**反直觉的坑**，值钱的不是代码是那句话：
> `os.kill(pid, 0)` 在 POSIX 上是"探测存活"，搬到 Windows 上就变成**"探测即击杀"**；
> 以及 UNC 兜底在 NAS 上不报错、只是**悄悄绕一圈 SMB 连自己**（慢，且难查）。
> 要回退就取消注释 —— **`subprocess` 那行要一起打开**，否则 tasklist 分支会 NameError。

**② 还剩两件要你手动做的**

```bash
# 1) 彻底删掉那个悬空计划任务（必须**管理员** PowerShell/cmd，普通权限会「拒绝访问」）
schtasks /Delete /TN "reseed-drive-loop" /F
#    不删也不影响 —— 它是"已禁用"状态，而且目标 .cmd 已经没了，永远不会跑。

# 2) scripts/run-batch.sh 仍然保留（它是一次性的**手动**命中率试跑，不是调度）
#    但它从 Git Bash 跑，照样要读 scripts/.nasrc。
```

**③ 明确保留的东西**

- ✅ **`deploy.sh`** —— Windows Git Bash 跑的，**唯一**还从电脑发起的**写**操作。别删。
- ✅ **`scripts/check-deploy-drift.py`** —— Windows Git Bash 跑的，**只读**。它回答
  「NAS 上有没有我不知道的文件 / 仓库里有没有该部署却没进白名单的文件」，见「漂移哨兵」一节。
- ✅ **`scripts/scan-secrets.py`** —— Windows Git Bash 跑的，**只读**。`git push` 前跑一遍，
  按值的形状找漏进仓库的凭据。★ 它**读**本地 `.env` 但**只算 sha256、从不打印命中到的值**，
  所以输出可以直接贴给人看。见「推前凭据扫描」一节。**只扫不改，也不是调度的一部分。**
- ✅ **`scripts/run-batch.sh`** —— 手动试跑工具，不是调度的一部分。
- ✅ **`scripts/nas-update-env.sh`** —— **2026-09-12 晚已进 `deploy.sh` 白名单**（映射到
  `<compose>/nas-update-env.sh`），跟着 `deploy.sh --apply` 走，**不用再单独拷**。
  它是**生成物**（`scripts/gen-nas-env-update.py` 产出，故本地被 gitignore）——
  之所以能进白名单，是因为它只装载 `DATA_DIRS` + `LINK_DIR` 两个**路径**键、不含任何凭据。
  ⚠ 若哪天它开始携带别的键，**先回看 `deploy.sh` 里那段注释**再同步。

### ⚠ 交接必读的坑

1. **`drive` 忘给 `--qbit-url` → `SEEDING` 被误降级成 `MATCHED`。**
   现象：回灌打出 `已在 qB 里: 0` / `本次新增做种: -51`（**负数**）。
   根因：`stage` 是推导的纯函数，缺 qB 数据就推不出"在做种"。
   补救：补跑一次带 `--qbit-url` 的 `sync` 即完全恢复（幂等）。详见 SUMMARY §13.6 坑 1。
2. **`drive` 忘给 `--db-path` → 回灌被跳过，状态不更新。**
   现象：webhook 全发成功（204），但结尾打
   `[!!] 回灌需要 --db-path（cross-seed.db 路径），已跳过`，退出码 3。
   补救：补上 `--db-path` 重跑，或单独跑 `sync` 回灌（都不发新请求，幂等）。
   ⚠ 附带的**假象**：重跑时终端可能返回**空输出**，看着像"没执行"，其实跑完了 ——
   **判断 drive 是否真跑，查 cross-seed 日志 / `drive-loop.log`，别看终端**（SUMMARY §12.5）。
3. **`.env.new` 存在 ≠ `.env` 已更新。** 判断是否生效一律看
   ① 容器内 `DATA_DIRS` 条数 ② `cross-seed.db` 的 `data` 表，别看 `ls`。
4. **别对大包根打 webhook。** cross-seed 的 webhook 是单线程顺序处理，
   中途撞一次 429 → 后面几百条全部 `Skipped searching (filtered by temporarily
   disabled indexers)`。已实测：一次 429 废掉 295 条。改用 `drive --limit N` 分批。
5. **`--depth` 必须等于 cross-seed 的 `maxDataDepth`**（本项目默认 2），
   对不上就会出现"状态机有、cross-seed 没有"的幽灵条目。

### 还没做

★ **下面第 1、4 条已合并成同一次容器重建，并于 2026-09-12 12:42 执行完毕** —— 见本节的「收尾命令」。

1. ~~从 `TORZNAB_URLS` 移除 BTSCHOOL `/3/api`~~ ✅ **已完成（2026-09-12 12:42）** ——
   文件侧早已完成：生产 `.env` 里**只有 2 条**（`/2`、`/4`），`/3/api` 早就不在文件里了；
   那些 410 **纯粹是容器没重建**（磁盘上的 `.env` 是对的，跑着的容器用的是旧环境变量）。
   所以不用跑 `add-indexers.py --remove`，**只差 `--force-recreate`** —— 这一步已在批次间隙做完：
   新容器启动日志认得**恰好两个**索引器（`HDFans`、`NanyangPT (南洋)`），
   当日日志里 `/3/api` **0 次**、`410/401/403` **0 条**。
   ⚠ 重建会打断正在跑的 drive，务必等当前批次跑完。
   ★ 重建后第一次启动会打两条 `HDFans/NanyangPT failed to respond ... fetch failed` ——
   **那是竞态常态**（cross-seed 比 Prowlarr 先起来），不是故障，判据见 SUMMARY §16.4.2。
2. ~~挂 Windows 计划任务~~ ✅ 已完成过一次，但 **2026-09-11 晚已迁到 NAS**。
   ★ **2026-09-12 电脑端彻底退役**：包装器 `.cmd` 与 PC 侧日志/状态**已删**，
   代码里的 Windows 分支**已注释**（`[电脑端已退役 2026-09-12]`），详见上面
   「**⛔ 电脑端已不参与**」那一节。
   ✅ **残留任务已删除（2026-09-12 中午）** —— `schtasks /Query /TN "reseed-drive-loop"`
   报「系统找不到指定的文件」、`Get-ScheduledTask` 也返回空，**两把工具独立确认**。
   ⚠️ 记一个方向容易看反的坑：**`拒绝访问`= 没提权**（要管理员），
   而 **`找不到指定的文件` / `ObjectNotFound` = 已经没有了**（是成功信号，不是失败）。
   删的时候如果先跑的是没提权的那条，会先吃一个 `拒绝访问` —— 别以为"删不掉"，
   换个管理员窗口重跑就好。
3. ~~**换一个站替换 BTSCHOOL**~~ ✅ **已定并已改 `.env`（2026-09-12 13:09）** ——
   第三个 cross-seed 源站选 **HDtime**。理由见 **SUMMARY §16.6.3**：它在 Prowlarr 里
   **已配好且启用**（`id=1`，零新凭据）、**IYUU 也管它**、而且 **IYUU 还没对它扩散成功**
   （qB 里那 8 个外来 tracker 没有 hdtime）—— 正好落在「cross-seed 先做上种、
   IYUU 再扩散」的位置上。
   `.env` 的 `TORZNAB_URLS` 已从 2 条改为 **3 条**（备份 `.env.bak.hdtime-20260912-130915`）。
   ✅ **已完成（2026-09-12 13:12）** —— 批次间隙里 `sudo docker compose up -d --no-deps
   --force-recreate cross-seed`，回读容器内 `TORZNAB_URLS` 条目数 = **3**；
   启动日志 `Your configuration is valid!`，**三个索引器一条错都没报**。
   ⚠ **首搜爆发**：新索引器对库里每部片子都是「从没搜过」，接下来几批会补搜积压 ——
   收到 `indexer-blocked:HDtime` 告警就说明它吃不住。加站流程见 SUMMARY §13.3。
4. v3 **硬链接农场**：**农场已建好（475/475）并通过独立复核**，
   切换前的**等价性也已在真实数据上验过**：按 cross-seed 真正用的指纹
   （名字 + 每个文件的相对路径与尺寸）比，49 条 dataDir 与农场**逐条完全相同**
   （1888 = 1888，双向 0 差异）。见 SUMMARY §10.5.7 / §10.5.9。
   ✅ **已在生产生效** —— NAS 磁盘上的 `.env` `DATA_DIRS` 已是农场那 **1 条**，
   容器里也是。★ 2026-09-12 12:42 那次 `--force-recreate` 把这件事**从"日志推断"变成了直接证据**。
5. ~~编排器 `status` 子命令~~ ✅ **2026-09-12 下午已做** —— 但**原待办的名字是错的**：
   缺的是 **`state`**，`status` **早就有了**。两者名字像、含义完全不同：
   `status` 看 **qB 快照**，`state` 看**我们自己的 sidecar 状态库**；
   它们对不上恰好是 §17.5.1 那类 bug 的症状。实现与四个决定见 **SUMMARY §11.10**，
   测试 `tests/test_orchestrator_state.py`（24 条）。
   ✅ 容器里要用的那一步也做完了：给 compose 补了 `./drive-loop/hlink:/state:ro`
   （+ `RESEED_STATE_DB=/state/state.db`）。挂 **`ro`** 是必须的 —— `StateStore`
   打开库时会跑 schema 迁移（`ALTER TABLE`），rw 等于让一个**只读语义**的子命令
   具备**写坏生产库**的能力。这一行**不用重建容器**，下次跑编排器就生效。
   IYUU（本范围外）—— 但它可能不只是在"扩散"，见第 9 条。
9. ~~⬜ ★ **查清是否有第二套系统在共用同一个 qB**~~ ✅ **已查清（2026-09-12 13:00）**——
   见 **SUMMARY §16.6**。`.env` 只配了 **2 个** Torznab 索引器，
   而 qB 里的 tracker 域名**明显更多**（keepfrds / btschool / m-team / hdarea / pterclub …），
   首要嫌疑是 **IYUU**。
   **不是故障**，但它动摇的是 §16.1 额度台账的**前提**（"只有我们在用这些站"）：
   那些数字可能**系统性偏低**，而站点那边看到的是**两边之和**。
   ★ 当天下午**已排除一条错路**：原本以为"点亮来源 B 就能发现它"，
   **是错的** —— 那些站**在 Prowlarr 里一个都没有**，说明第二套系统**绕开 Prowlarr 直连站点**，
   A/B 互校**看不见它**。（"视角 ≠ 全景"：B 只能看见**经过 B 的**东西。）
   ⬜ 仍未查：IYUU 在不在跑、注入到哪个分类/目录、查不查我们这两个站。
   ✅ **已查清（2026-09-12 13:00，全文见 SUMMARY §16.6.3）**：
   **是 IYUU Plus**（容器 `iyuuplus_ssd`，UI `:8787/app/admin`），就在这台 NAS 上；
   ★ **2026-09-11 21:08 起**它把**我们的 qB（`192.168.0.7:3060`）加为下载器**（`id=6`）；
   其任务 `QB-docker-reseed辅种`（**每天 02:34**）向我们这个 qB 辅种、
   并查询 **16 个站**（**含 HDFans 与南洋**）。
   ★★ **但它抓的是网页**（`details.php` / `download.php`），**不是 Torznab** ——
   所以 A/B 量的是「我们的 Torznab 搜索」、IYUU 走 HTML，**两条通道不同**，
   台账的分母**没有被污染**。⚠️ 唯一没闭环的：**站点是否把「API 查询额度」与
   「网页浏览」分开计** —— 那只能人去规则页看。
   ★ 副产物：**Prowlarr 里其实有 4 个索引器**（`1=HDtime`、`2=HDFans`、
   **`3=BTSCHOOL`（只是被停用，从未删除）**、`4=NanyangPT`）——
   §13.10 那句「410 = 索引器已被删除」**需要复核**。
   ★ 由此定下的**分工**（用户当天拍板，见 §16.6.3 与上面第 3 条）：
   **cross-seed 只在 3 个源站把种做上，其余十余站交给 IYUU 扩散。**
10. ✅ **来源 B 已点亮（2026-09-12 下午）** —— 用真响应核对过字段名
   （`{"indexers":[{"indexerName","numberOfQueries",...}]}`，与解析一致），
   并接进每日台账。**但它的用途和原先记的不一样**：
   它能发现的是**「有别的工具在用我们的 Prowlarr」**，而**发现不了**直连站点的 IYUU（见第 9 条）。
   ★ 真就抓到一个：**HDtime**（Prowlarr 里启用、被查 8 次含 4 次失败，而我们只用 `/2` `/4`）
   —— **这 8 次不是我们发的，是谁发的还没查**，见 SUMMARY §16.6.1。
   顺带修掉一个结构性盲点：台账原先**看不见"不是我们的站"**（§16.6.2）。
   `.env` 里补了 `PROWLARR_URL=http://<NAS_IP>:9696`（备份 `.env.bak.prowlarrurl-20260912-122140`）。
11. ✅ **`.dockerignore` 的 `.env` → `.env*`（2026-09-12 下午，顺手救火）** ——
   `.env` 是**精确匹配**，拦不住 `.env.bak.20260911-204109` 这类**含密钥的完整副本**，
   而仓库根目录**确实躺着一份**。只写 `.env` 的话 `docker build` 会把它打进镜像层，
   而**镜像层是删不掉的**（删了也还在历史层里）。`.gitignore` 当时还是两条窄规则
   （`.env` + `.env.bak.*`），**2026-09-13 已一并改成同款 `.env*` 前缀全兜** —— 见文末 ⚠。
12. ✅ **`[inject] Failed to parse ... ENOENT` 已查清（2026-09-12 13:30）—— 是虚惊，不是丢种。**
   原判断「每一条都等于一个跨种没注入成」**是错的**。真相是 cross-seed **自己的事后清理**
   与**它自己的并发**打架：

   * cross-seed 在注入成功、且该种在 qB 里**已完整**之后，会删掉 `/config/cross-seeds/` 里
     那份存档 `.torrent`。这行**只写在 verbose 级**（今天 info 里 `Deleting` **0** 条、
     verbose 里 **384** 条）—— 所以光看 info 根本看不见，才显得像"文件凭空消失"。
   * 而 webhook 会触发**并发的**新一轮 inject 阶段：它在**开头**就把目录扫成一个文件清单
     （`[inject] Found N torrent file(s) to inject`），之后**逐个**打开处理。
     清单里的某个文件若在这期间被另一路删掉 → `open()` → **ENOENT**。
   * 实测配对：未麻的部屋 `[787075f7]` 在 `09:40:07.016` 被删，
     ENOENT 出现在 `09:40:07.336` —— **相差 320 ms**，同一文件还被删了两次
     （09:40:07 与 09:40:11），正是两路并发各删一次。

  **结论：ENOENT 的种子早已注入且已完整，丢的只是一份已经没用的存档。**
  ★ 顺带纠正一个更早的猜测：**NanyangPT 的跨种一直在正常工作** ——
  09-12 单日 webhook 路径 `- injected`：HDFans **121** 次、NanyangPT **105** 次。
  「只有红豆饭拆包成功」**不是 cross-seed 这一层的问题**，是台账的问题 —— 见第 13 条。

  ★★ **同一套机制顺带解释了一条硬规矩（2026-09-13 补记）：删一条跨种时，
  先删 NAS 侧 `/config/cross-seeds/` 里的 `.torrent`，再删 qB 里的种子。**
  理由就是上面那条：cross-seed **只在种子已完整时**才肯删存档。不完整时它
  **每一轮都重新注入同一份**，实测 8 轮全都留下
  `ALREADY_EXISTS (incomplete)` + `Will not delete …: torrent is incomplete`
  （连 `Will not delete` 都是在说"我想删它但不敢"）。所以只要存档还在，
  它就一直在敲门；把门后的种子换掉，敲的就是另一扇门。

  ⚠ **上面这一步是「推断」，不是「观测」。** 日志里从头到尾**没有出现过一次
  「删了之后被重建」**——它看到的是**没删成**。"先删种子 ⇒ 下一轮把它重建出来"
  是从这两条机制**推出来的**，不是实测到的。**别把它当作有日志为证的记录去引用。**

  ★ 同批还有一条**实测**（2026-09-13）：**「暂停」确实挡得住 resume。** 同一条种子
  连续 8 轮（12:35→16:38），每一轮都留下 `Will not resume …: state is stalledDL`，
  **一次都没被唤醒** —— 8 次直接实测，不是推测。★ 但它挡的是 **cross-seed 的唤醒**；
  别的会 resume 的路径（手点、qB 自己的恢复逻辑）不在它管得着的范围里。

  ⬜ 唯一还值得做的：`Deleting` 只记 verbose，等于这条清理路径在 info 级是隐形的；
  可以在 `config.js` 里给它留个 info 级的汇总（低优先）。
13. ✅ **★ 台账「只有红豆饭」是解析 bug，不是事实（2026-09-12 13:25 定位并修复）** ——
  **这直接就是你看到的「只有红豆饭拆包成功」。**

  `orchestrator/state.py:264` 的 `_RE_FOUND` 用 `on (\S+) by (\w+)` 取站名。
  而 Prowlarr 里的站点显示名**可以带空格和括号** —— 我们的南洋就叫
  **`NanyangPT (南洋)`**。于是 `(\S+)` 只吃到 `NanyangPT`，紧跟着要求 ` by `、
  实际却是 ` (南洋) by `，**整行静默不匹配**。HDFans / HDtime 名字没空格，所以毫发无伤。

  | 日志 | Found 行总数 | 现有正则认出 | 漏掉 |
  |---|---|---|---|
  | `info.2026-09-11.log` | 399 | 308 | **91，全部是南洋** |
  | `info.2026-09-12.log` | 770 | 492 | **278，全部是南洋** |

  **后果链**：`parse_log` 丢掉这些行 → `facts.found` 里没有南洋 →
  `sync_pack` 组装 `matched` 的那一行拿不到南洋标签 → `movie.matched_indexers`
  **永远只有 HDFans**。
  > ★ **那一行后来被重写了**（2026-09-14，为另一件事：`matched_indexers` 跨天日志滚动后
  > 被抹空 —— 见上面「🔴 下一步」里 **#73/#75** 那一行，与 **SUMMARY §22**）。原文是
  > `matched = [(h, "|".join(found_idx)) for h in hashes]`，**现在仓库里已经没有这一行** ——
  > 别再拿它（或它的行号）当锚点。两者是**两个不同的毛病**：这条是**正则吃不下带空格的站名**，
  > 那条是**输入源易失 + 写入端不合并**，别把它们并成一件事。

  据库实测：605 部里 **215 部标着 HDFans，标着南洋的 0 部** —— 而
  `indexer_seen`（452）和 `attempt.indexers` 里南洋**都在**，因为那两处走的是
  cross-seed.db 和搜索记录，**不经过这个正则**。所以是"一个字段瞎了"，不是"南洋不行"。

  ★ **影响面**：只影响 `matched_indexers` 这一列 → `report` 的站点归属、
  `trend` 的**按周×按站**换站决策表。**不影响 `stage`**（`compute_stage` 只看计数），
  也**不影响重搜**（`next_retry_at` 走 `indexer_seen`）。也就是说：
  **做种一直在做，只是台账把它记成了红豆饭的。**
  ⚠️ 它还会**反向污染**：一部在南洋匹配到的片，因为 HDFans 那一行解析成功，
  整条 `matched_indexers` 会被写成 `["HDFans"]` —— **把南洋的功劳记到红豆饭头上**。

  修法：`on (\S+) by` → `on (.+?) by`（后面 ` by (\w+) from dataDir \(` 是硬锚点，
  非贪婪不会越界）。已过：
  * 复跑上表 → **漏 0 条**；
  * 用真实 `parse_log` 跑全天日志 → `found` 里 HDFans 399 / **NanyangPT (南洋) 255**，
    且同一目录能同时归到两个站（如「寻梦环游记」）；
  * `py_compile` 通过。
  ✅ **已 `deploy.sh --apply` 落 NAS**（备份 `.deploy-backup/20260912-132505`），
  `orchestrator/state.py` 与 `drive-loop/orchestrator/state.py` 两个目标都已回读一致。
  **drive-loop 下一批次 import 时即生效，不需要重建容器。**

6. ~~**通知：NAS 侧还没部署**~~ ✅ **已完成（2026-09-12 凌晨）** —— 三个任务计划已建，
   **实测收到邮件**（`--test-mail` → QQ 收件箱），spool→发信整条链路打通。
   踩坑全过程见 SUMMARY §15（DSM 的 ssmtp 读的是 `synosmtp.conf`、`MAIL_FROM` 必须等于认证账号、
   计划窗口小时位存错导致"手动能跑、计划不跑"）。
7. ⬜ **四个自动化的设计预案** —— 见 **SUMMARY §16**：
   站点额度感知 / 农场巡检自动化 / 命中率趋势 / 日志轮转。
   ✅ **"日志轮转"那条已实施（2026-09-12 上午）** —— 但**不是**按原假设做的：
   探完之后发现**两条前提被推翻**：`drive-loop.log` 与 `cross-seed/logs/*` **其实都已在自我轮转**，
   真正没有上限的是**容器的 docker 日志**。所以改的是 `docker-compose.yml` 的 `logging` 段
   （四个服务共用一份锚点），✅ **已于 2026-09-12 12:42 在 NAS 上 `--force-recreate` 生效**
   （`docker inspect` 回读 `max-file=3` / `max-size=10m`）。详见 §16.4.2。
   剩下三条里：
   * ✅ **"农场巡检"也已实施（2026-09-12 下午）** —— 先修掉了它的前置条件
     （`--verify` 在 `DATA_DIRS` 切到农场后会**自己和自己比、永远通过**，§16.2.1），
     再把巡检挂进 `drive-loop`（`check_farm()`：漂移发 `alert`、干净进日报、
     **绝不自动 `--prune`**）。见 §16.2.2。**代码待部署。**
   * ★ 而"挂上去"这一步**自己又长出两个 bug**，都是只在**自动跑起来之后**才暴露的：
     `.env` 行尾的 CR 让 `--verify` 报**假漂移**（§16.2.1.2），
     `--verify` 收尾漏删一个 115 KB 的 `.tmp`（§16.2.1.1）。
     **一个只在"自动跑"时才暴露的问题，只有真的自动跑起来才会暴露** ——
     所以"先挂上去"不是收尾动作，是**发现手段**。
     ✅ **已部署（2026-09-12 12:12，备份 `.deploy-backup/20260912-121218`）。**
     ★ 首次真正跑到 `check_farm()` 是**下一批跑完**（约 13:40）——
     被闸门跳过的 tick 只在跑闸门那几行，走不到它。
   * ⬜ 还剩**站点额度感知**（已实施，§16.1）与**命中率趋势**（已实施，§16.3）之外的
     两条**已知残留**，见 §16.5 优先级表。
   动之前**先读 §16**，里面还给了优先级。
8. ~~🔴 状态机把"其实在做种"的片子降级了（2026-09-12 凌晨实测，未修）~~ ✅ **2026-09-12 上午已修** ——
   首次 NAS 真跑后回灌打出 `新增做种 -26`（**负数**），当时全库只剩 **13** 部 `SEEDING` 而 qB 里**有 160 部在做种**。
   真根因**不是**回灌链路，是 **v3 农场切换后 cross-seed 报的是农场路径、`pack.roots` 还是原路径**
   → searchee 全被判成「别的包」**静默跳过**。`SEEDING` 13 → 21（只补跑 sync）→ **201**（= 理论上限）。
   同批的 `backoff_hits=0` 也一并修掉（真根因：**检查间隔 300s 比退避窗口 55s 还长**），
   并顺带发现 `next_sleep()` 在 `--once` 模式下**压根没接线**。
   根因、修法、三层验证见 **SUMMARY §17.5**；当时的误判过程见 §17.3。
   （另：`attempts.log` 里可能看到一行**假的** `exit=127 (no python)` —— 那是部署覆盖了
   正在运行的 `run.sh` 造成的，**不是真的没有 python**，见 §17.2。）

14. ⬜ **2026-09-12 晚：「漂移哨兵 + 推前扫描」这一轮的收尾与遗留**

   ✅ **已完成**：白名单补齐（25→27，最后两个手工文件，见 §18.14.2）、
   `scripts/check-deploy-drift.py`（漂移哨兵，§18.14.3）、`scripts/scan-secrets.py`
   （推前凭据扫描，§18.15）、`tests/test_scan_secrets.py`（25 条对照）、
   杂物整理（10 项 `mv` / 23 个文件进 `_cleanup-20260912/`）。

   > ★★ **杂物计数的三个数 —— 18 / 23 / 26 —— 口径不同，别互相"订正"**（2026-09-13 统一记在这）：
   >
   > | 数 | 它是什么口径 | 什么时候读的 |
   > |---:|---|---|
   > | **23** | `_cleanup-20260912/` 里**实际的文件总数**（含 5 个 `.pyc`） | 搬走**那一刻**的实数 |
   > | **18** | 漂移哨兵的口径 —— 它把 `__pycache__` **单列**，不并进杂物，所以少 5 个 | 与 23 同一次扫描 |
   > | **26** | `__pycache__` **自己长回来**之后的读数 | 次日复测 |
   >
   > ⇒ **23 ≠ 18 不是对不上**（差的正好是那 5 个 `.pyc`）；**26 ≠ 23 也不是整理失败**
   > （`__pycache__` 会自己长回来，下界 ≈ 正在跑的模块数）。**三个数都对。**
   > ★ 真正该记住的是：**这个计数永远回不到 0**（见本节末尾那段），别把它当告警阈值。
   > （此前这三个数散在 README 本节与 SUMMARY 三处，谁看谁重数一遍 —— 故此处合并成一张表。）

   **还剩三件**，都不是阻塞：

   * ✅ **暂存区已真删（2026-09-13）** —— `_cleanup-20260912/` 与
     `#recycle/env-bak-20260912/` 两处都清了。前者 **23** 个文件（含 5 个 `.pyc`；
     漂移哨兵按「非 pyc」口径报 **18**，**两个数都对**，别当成对不上），其中
     **6 个 `.env.bak.*` 是生产 `.env` 的明文副本（带全部凭据）**；后者 8 个文件。
     删后哨兵读数：暂存区 18 → **0**、`*.pyc` 8 → **3**、受管 27 → 28、**`rc=0`**。
     ★ 删完杂物计数**也不会到 0** —— `__pycache__` 会自己长回来（下界 ≈ 正在跑的模块数），
     见「漂移哨兵」一节那段。
     ★★ **2026-09-13 起用脚本删，别再手敲**：`sh <compose>/rm-staging.sh <目标> --apply`
     （仓库 `scripts/rm-staging.sh`，已在 `deploy.sh` 白名单里，**不进任何计划任务**，
     手动跑一次即可）。它默认只列清单、`--apply` 才删；**先删凭据副本（口径 `.env*`）再删目录**；
     并且**只认两类路径**：`_cleanup-*` 与 `#recycle/` 下的 `env-bak-*`（**都按 basename**），
     其余一律拒。
     ★★ **第三类已撤（2026-09-13，本条原先写的是「三类」）** —— 旧根残留
     `/volume1/video/download/reseed_singles` 曾经是第三类（按**完整路径字面量**放行），
     删完即撤。★ 撤掉的理由值得留着：它和前两类的**判据不同**（完整路径 vs basename），
     而**一次性口子不该常驻** —— 留着等于在生产上永久留一个「能删视频目录」的口子。
     那条留下的教训照旧成立：**拿 basename 当通行证，会把「任何叫这名字的目录」一起放行**；
     写成完整路径 = 只放行那一处（对照实测：同名、不同完整路径 → 被拒）。
     ⇒ 下次再有一次性的清理，照这个办：**加一条 case，删完立刻撤**。
     ★★ **别走 DSM File Station** —— 它的删除只是把文件挪进 `#recycle`，**文件仍在盘上**。
     2026-09-13 实测 `docker_ssd/#recycle/env-bak-20260912/` 里已经躺着 **8 个 `.env.bak*`**
     （其中 4 个是 7.0–7.3 KB，**与生产 `.env` 的 7750 B 同档**），全是之前几次
     「File Station 删除」留下的 ⇒ 走 File Station 删 = **凭据原地不动，还多 6 个**。
     ★ **窄口已修（2026-09-13）**：原先闸 ⑤ 第 1 步只匹配 `.env.bak.*`，而
     `#recycle/env-bak-20260912/` 那 8 个里**只有 7 个**匹配（第 8 个是**不带
     时间戳后缀**的 `.env.bak`）。当时没出事——第 2 步 `rm -rf` 整目录把它一起
     带走了——**但脚本头部那句「哪怕中途断电，凭据也已经先走了」对它不成立**，
     而那正是这条闸**唯一的卖点**。
     ★ 修法**不是把 glob 放宽一格**（那仍然是在猜命名）。现在：
       · 真正拿来**删**的口径是 `ENV_SEAL='.env*'`（任何 `.env` 副本都算）；
       · `.env.bak*` 只留着**报数**；凡被 `.env*` 捞到却没被它覆盖的，
         **点名打出来**（标注「名字没见过」）。
       ⇒ 下次命名再变，表现是**报一条陌生名字**，而不是**静默少一个数**。
     ★★ **教训（当天连犯三次，故单列一行）：别让「凭据会不会泄漏 / 会不会被删净」
        取决于我们猜没猜对文件名。** 三处同源，都改了：
        `rm-staging.sh`（删除口径）、`.gitignore`（忽略口径）、
        `check-deploy-drift.py` 的 `KNOWN_NAS`（分类口径，原先 `.env.bak` 裸名会
        掉进 unknown ⇒ 哨兵**误报**）。分类那处配了回归 `tests/test_drift_junk.py`。
     ⚠ **别对 UNC 路径跑 `rm`** —— 只在本机看不到的 NAS 原生路径上删。

   * ⬜ **`#recycle` 里的「旧项目残骸」不受脚本受理，只能一次性手动删。**
     `rm-staging.sh` 的闸 ③ 对 `#recycle` 只放行 `env-bak-*`，其余条目**一概被拒**
     —— **这是有意为之，别放宽**：一放宽它就变成
     「能清空整个回收站」的东西，而回收站里还有 `iyuuplus` 等你可能想留的条目。
     （2026-09-13 新增的那条例外是**旧根残留**，判据是**完整路径字面量**、与回收站无关，
      所以并没有松动这里的口径。）
     处置：在 NAS 上先 `du -sh` + `ls -a` 看过，再 `rm -rf /volume2/docker_ssd/#recycle/<条目名>`。
     ★ **判它是残骸还是活项目，靠穷尽统计后缀** —— 2026-09-13 就这样定性了
     `musopia_script2/`：718 个文件里 `.db-shm` 346 / `.db-wal` 346 / `.pyc` 6 /
     `.lock` 11 / 无后缀 5 / `.env` 1 / `.yml` 1 / `.json` 1，**`.py` 和 `.db` 各 0 个**
     ⇒ 是 09-08 一次「跑了飞的」留下的残骸（346 对 `data_HHMMSS_N.db-*` 说明当时
     每轮循环都新开一个库、`daemon_heartbeat_110920` 说明每次重启都新写一个心跳文件），
     **不是活项目**；它那对 `1.env` / `.env.yml` 是早于活项目的草稿，**密钥全是占位符**、
     无真凭据（活项目在 `docker_ssd/musopia_script2`，那份 `.env` 才有真凭据）。
     同批还删了 `reseed-cleanup-20260912/`（2 文件，09-12 搬家的残余）与
     `stray-state-db-20260912/state.db`（0 字节，`StateStore(create=)` 那次事故的物证）
     ⇒ `#recycle` 16 → **13** 条，`iyuuplus` / `iyuuplus.syno.txz` 原样未动。
   * ⬜ **搬迁后次日 01:45 之后复核**：`:3060` 上 `IYUU自动辅种` 的条数是否**仍在增长** ——
     这是「目录搬迁没有把 IYUU 辅种搞停」的**唯一生产级反证点**，见 SUMMARY §18.8。
     ★ **2026-09-12 已自动化，不用人盯**：挂进了 `drive-loop` 的**每日台账**
     （`report_daily()`，见 §18.16）—— 每天一行进 `notify` 的 TSV 流水，判据是
     **基线 100 条**（搬迁当天实测）。
     ⚠ **第一个有意义的读数是 09-14 凌晨**，不是 09-13：日报在**当天第一批**（约 `00:0x`）
     采样，而 IYUU 的 cron 是 **`45 1 * * *`（01:45）** —— 09-13 那次读到的还是它
     「搬迁后还没跑过」的状态。
   * ⬜ **`scan-secrets.py` 的已知盲区**（低优先，**建议不修**）：只由小写字母 + 连字符
     组成、每段都是纯字母的长密钥抓不到。要收口就得换成"熵 / 字符集"判据，而那会**同时**
     把文档里的英文短语重新变成假阳性 —— 换来的是一个"次次都红"的闸门。
     理由与取舍见 §18.15。

15. ⬜ **2026-09-13：#58「drive-loop 迁容器」的静态对账 —— 含一条代码缺陷**

   **a. ★ 缺陷（这条是新的，且是"不报错、只是不动"的形状）：常驻分支不写心跳、也不落盘状态。**
   `drive-loop.py` 的 `write_state()` **全文件只有两处调用，都在 `once_round()` 里**
   （批前写 `running_pid` + `heartbeat_ts`；收尾写 `{"running_pid": None, ...}`）。
   常驻分支（`if args.once and not args.dry_run` 为假时走的那条）调 `run_round()` 时
   **没有 `with Heartbeat()` 包着** ⇒ 常驻模式下：
     * `.drive-loop.state` 的 `heartbeat_ts` **这键根本不存在**；
     * 包轮换下标 `cur_pack_idx` 与连续失败计数 `consec` **都是局部变量**，进程/容器一重启就从头
       （`--once` 那边是靠 `consec_abort` 落盘跨进程累计的，见 §17.5.4）。
   ⇒ **后果**：若照「给常驻容器加 healthcheck，判据用心跳新鲜度」这条路做，
     那套判据在常驻模式下**永远不成立**（键都没有）。要这么走得**先改代码**。
   ⇒ ★ 这同时否掉了一份外部分析里「常驻模式代码已存在、不用改代码，只需改怎么跑」的结论 ——
     **跑起来**确实不用改；**要"卡死能接管"** 就得改。
   ⇒ 另记一条同源的：`restart: unless-stopped` 只对容器**退出**生效，
     **healthcheck 不健康并不会触发重启** —— 所以常驻路线的接管机制得再加一个
     `autoheal` 侧车（或 DSM 轮询 `docker inspect`），不是配一个 healthcheck 就完事。

   **b. 迁容器（方案 B）的草案已落盘：`scripts/drive-loop-docker.sh`**
   （`docker run` 包装 + 挂载清单 + 三处容器方言差异）。
   **未部署、未进 `deploy.sh` 白名单 —— 有意为之**：白名单的语义是「两边必须一致」，
   而这份还没在 NAS 上验过；现在就收进去，下次谁跑一次 `--apply` 就会造成假一致
   （生产上有了这个文件、看着像在用的那套，而 DSM 任务调的还是 `run.sh`）。
   ★ 若最终采用，**首选**其实不是这个包装，而是做成 `compose.yaml` 的一个服务
     （网络与卷由 compose 统一声明，不用 `create → network connect → start` 绕），
     届时本包装退化成一句 `docker compose run --rm drive-loop`。
     现在不直接改 `compose.yaml` 的理由只有一条：**它在白名单里，改它 = 改生产**。

   ★★ 一条值得单独记的结论 —— **「挂载 1:1」不是「挑几个子目录挂」，而是整个 compose
   目录按同名同路径挂。** 因为代码里的路径**全是绝对路径**：`CROSSSEED_DIRS[0]`（硬编码）、
   `build-farm.sh` 的 `COMPOSE_DIR`、`--env "$COMPOSE_DIR/.env"`、告警出栈口
   `notify/spool/`、以及 `ROOT = HERE.parent` 那条推导。挑着挂**不会报错**，
   只会**静默退化**（`first_existing()` 返回 `None`，然后只打一行 warning）。
   ★ 最容易漏的是 `drive-loop/scripts/` 下那五个 `.state` 文件 —— 它们**不在** `hlink/` 里，
   而漏了的后果是**静默**的：对账 / 无人认领的基线会被当成「首次读数」重新记一遍。
   ★ 代价也要写明：挂整个 compose 目录 = 把 `.env`、`prowlarr/`、`cross-seed/`、
   `notify/notify.conf` 一并交给这个容器 —— 这是**新扩大的爆炸半径**，躲不掉。

   ★ **边界（别把这份对账读成"已经跑通过了"）**：容器里**真跑一遍没做过**，
   闸门跨容器**连跑两轮没验过**，属主/权限**没验过** —— 以上全是静态对账
   （读 NAS 上的 `run.sh` / `compose.yaml` + 本地代码）。本机不能在 NAS 上执行命令
   （SSH 关着）。这三条也写在草案文件头部了。

   **c. 顺带修掉一条"自己造的陈旧描述"**：本节上面那段原写 `rm-staging.sh`「只认三类路径」，
   而它 2026-09-13 已撤成**两类**（旧根删完即撤）—— 已按现状更正。

#### 收尾命令（一次重建同时办完两件事）—— ✅ **已执行过，此节仅存流程**

> ★ **2026-09-12 上午改判**：核对发现**这一步已经做完了**（容器内的 `DATA_DIRS` 已是农场那条、
> `/3` 已不在 `TORZNAB_URLS` 里，三条独立证据见上文「系统现状」的改判说明）。
> **不需要再跑下面的命令** —— 保留是因为将来改 `DATA_DIRS`/`LINK_DIR` 还要走同一条路。

本地已把 `.env` 的 `DATA_DIRS` 切成农场那一条，并生成/拷好了更新脚本。
**在 NAS 上**（SSH 或 Container Manager「终端」）：

```bash
cd /volume2/docker_ssd/prowlarr_cross-seed_autohardlink
sh nas-update-env.sh --dry-run     # 先看会改什么：DATA_DIRS 49 条 → 1 条
sh nas-update-env.sh               # 改 + --force-recreate + 闭环回读校验
```

脚本自带：备份 `.env.bak.<时间戳>`、安全闸（**除 `DATA_DIRS`/`LINK_DIR` 外的行必须
逐字节不变** —— 防止本地脱敏占位符污染生产密钥）、改完回读容器内 `DATA_DIRS` 条数
做闭环验证。回滚：`cp -p .env.bak.<时间戳> .env` 后重建。

**重建后请确认**：`drive-loop` 日志里「索引器自检」变绿、`/3/api` 的 410 警告消失、
searchee 数与切换前**一致（1888）**。

> ⚠ **备份文件同样含密钥** —— `.gitignore` 里 `.env` 是**精确匹配**，
> 拦不住 `.env.bak.20260911-204109`。
> ★ **2026-09-13 再修：当时补的 `.env.bak.*` 仍然窄。** `git check-ignore -v` 逐个实测，
> `.env.bak`（无时间戳）/ `.env_bak` / `.env.backup` **全都不被忽略** ⇒ `git add -A`
> 能把一份带全部密钥的副本**直接提交进仓库**。现改成前缀全兜 `.env*` +
> 显式放行 `!.env.example`（纯占位符模板，本来就该提交）。
> 若你在 NAS 上另存备份，别把任何一份拷进仓库。

详细的过程记录、踩坑与决策都在 **SUMMARY.md**
（老会话见 §11.12 / §11.13 / §11.14 / §12；本轮见 **§20**（观测层「沉默 / 响铃」语义收敛）
与 **§22**（`matched_indexers` 恒空 · HDtime 的 429 到底是哪种限流 · `ERR-SVC-17` 改「有据」），
最近一轮见 **§23**（卷归属双来源复核 · ★★ `stat -c %d` 只在 NAS 侧成立 · 枚举 ≠ 全量 ·
一份「日报加各包进度」方案的 8 条审订），
观测对账的判据本体见 §18.18 / §18.19）。

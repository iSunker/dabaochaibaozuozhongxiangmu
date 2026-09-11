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

## 我要做什么 → 看哪节

| 我想… | 看哪节 |
|---|---|
| 搞清这东西干嘛的 | 上面这段 + **目录结构** |
| 从零部署一台 | **部署步骤**（Phase 0→3，每步可独立验证）+ **验证清单** |
| 跑起来 / 继续跑 | **当前状态与下一步** ← 最常用，先看这个 |
| 我卡住了（报错 / 搜不到 / 不动了） | **常见问题** + **交接必读的坑** |
| 加站 / 换站 | **多站点** → SUMMARY §13.3（完整流程，可复用） |
| 接手这个项目 | **当前状态与下一步** → **SUMMARY §13**（全过程 + 坑单）→ **§13.11**（最新进度与唯一待办） |

> **两份文档怎么分工**（照日志分级来）：
> **README = INFO 层**（操作手册：命令、步骤、症状→解法）；
> **SUMMARY = DEBUG 层**（完整过程、踩坑、决策理由）。
> 同一事实**只在一处维护**，跨层用「详见 SUMMARY §N」单向指路 —— 防止两边漂移。

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
└─ README.md
```

> 开发仓库里另有 `scripts/`（`run-batch.sh` 抽样脚本、`reseed-state.py` 状态机 CLI、
> `drive-loop.py` 自动续跑、`add-indexers.py` 加站、`gen-datadirs.py` 生成嵌套包的 `DATA_DIRS` 片段、
> `build-farm.sh` 构建硬链接农场〔NAS 本机**或** Windows 经 SMB 都能跑，见「扩展 → 硬链接农场」〕）。
> 其余都是**在 Windows 上跑**的工具，不必进容器。由状态机导出的 `unmatched.tsv` /
> `todo.txt` 属运行时产物，已 gitignore。

三大服务的配置目录一一对应：`prowlarr/`→Prowlarr、`cross-seed/`→cross-seed、`hlink/`→编排器。
`.env` 是**唯一密钥/IP/路径来源**：`hlink/config.yml` 用 `${VAR}` 引用它，`cross-seed/config.js` 从环境变量读它。三处保持一致，只需改 `.env`。

> 注意区分：`hlink/` 只放编排器的**配置/日志**；真正的硬链接（做种数据）在 `.env` 的 `LINK_DIR`（须在 `/volume1/video` 下，与大包**同卷**，不是 `docker_ssd`）。

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
- **`:3060` API 403**：白名单网段没覆盖来源 IP（改 `WebUI\AuthSubnetWhitelist`），或应改用 `QBIT_AUTH_MODE=password`。

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

> **怎么判断某个站要不要 FlareSolverr**：在 Prowlarr 里手动搜一下。
> 看到 `403` + 挑战页 HTML / 日志里出现 `Cloudflare` → 需要；
> 看到 `500/502/520/522/timeout`（站点后端挂了）或 `429`（限流）或能正常返回结果 → **不需要**。

> ⚠ **Cloudflare**：中文 NexusPHP 站常需要 FlareSolverr，但本项目从 GHCR 拉镜像失败（见 SUMMARY §7）。
> 解法：改用 Docker Hub 的官方镜像 —— 把 `compose.yaml` 里的
> `ghcr.io/flaresolverr/flaresolverr:latest` 换成 `flaresolverr/flaresolverr:latest`，
> 然后在 Prowlarr 的 Settings → Indexers 里把 FlareSolverr 指向 `http://flaresolverr:8191`。

### 单片状态机（已实现）—— 记录每部片子走到哪一步了

cross-seed **不会排队、不会重试**：索引器被退避时，待搜索项直接跳过
（2026-09-11 有 295 条就这么消失了，见 SUMMARY §5.3）。
所以补了一个 sidecar 状态库，把每部片子的阶段记下来，**已完成的阶段不重复，被跳过的阶段必须补上**。

```bash
PACK=frds-top250-2024
N=//YOUR-NAS/docker_ssd/prowlarr_cross-seed_autohardlink

# ★推荐：根清单直接从 cross-seed 的 .env 里派生 —— 永不与 cross-seed 漂移
python scripts/reseed-state.py init --pack $PACK --depth 2 \
  --roots-from-env .env --match "DouBan_IMDB" --exclude "0观影清单*"
python scripts/reseed-state.py sync --pack $PACK \
  --db-path "$N/cross-seed/cross-seed.db" \
  --log "$N/cross-seed/logs/info.current.log" --log "$N/cross-seed/logs/verbose.current.log" \
  --qbit-url http://NAS_IP:3060 --indexer-alias "http://prowlarr:9696/1/api=SiteB"
python scripts/reseed-state.py report --pack $PACK
python scripts/reseed-state.py todo  --pack $PACK --indexers SiteA,SiteB --out scripts/todo.txt
python scripts/reseed-state.py drive --pack $PACK --indexers SiteA,SiteB --limit 50 --apply \
  --url http://NAS_IP:2468 --api-key <CROSSSEED_API_KEY> --db-path "$N/cross-seed/cross-seed.db" \
  --qbit-url http://NAS_IP:3060
```

**`init` 的根怎么给** —— 推荐**从 `.env` 派生**（`--roots-from-env .env --match "<路径关键词>"`）：
`.env` 的 `DATA_DIRS` 就是 cross-seed 实际会扫的清单，从它派生 ⇒ 状态机与 cross-seed **永不漂移**，
DC 那种 47 个根的包也一行搞定。另有显式 `--root/--local-root`（可重复、**必须按序一一对应**）用于单根包。
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
`--interval 30` 对齐 cross-seed 的 `delay`；每 `--check-every 10` 条读一次 cross-seed.db 的
`indexer` 表，撞上 `RATE_LIMITED` 就**睡到解禁**（超过 `--max-wait 1800` 秒则中止，不硬刚）；
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
4. **磁盘**：新大包本身要占真实空间（NAS 的 `/volume1` 只剩约 20 GB，见 SUMMARY §9）；
   但**硬链接侧依旧零开销** —— 这正是本项目能在快满的卷上跑起来的原因。
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
/volume1/video/download/reseed_farm/          ← 唯一的 dataDir
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

> ★ **也能直接从 Windows 跑**（走 SMB）—— 2026-09-11 实测：这个 NAS 上
> `os.link()` / `cp -al` 经 SMB 过来是**服务端真硬链接**（同 inode、`nlink=2`、
> 删掉原文件后另一个还在）。原先"Windows 建不了硬链接"的说法**是错的**。
> 此时 `.env` 里的 `/volume1/...` 在本机不存在，用 `--map` 做前缀翻译即可：
>
> ```bash
> COMPOSE_DIR="//iSunker-DS423/docker_ssd/prowlarr_cross-seed_autohardlink" \
> FARM="//iSunker-DS423/video/download/reseed_farm" \
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

## 安全

- `.env`、`cross-seed/`（含 cross-seed 自建的 db）、`prowlarr/`（Prowlarr 配置）**不要提交/外传**——含 cookie/passkey/apikey。
- PT 站凭据只进 **Prowlarr**；`:3060` 走局域网免密白名单（或 `.env` 里的密码），二选一。

---

## 当前状态与下一步（2026-09-11 晚）

> 本节是**操作入口**：怎么继续跑 / 卡住了看哪。
> 完整状态数据与逐项快照只维护在 **SUMMARY §13.7**，避免两处漂移。

### 系统现状（一句话）

**生产 NAS 磁盘上的 `.env`**：`DATA_DIRS` ✅ 49 条 · `TORZNAB_URLS` ✅ **2 条**（HDFans `/2` + NanyangPT `/4`）·
**跑着的容器**：⚠ `DATA_DIRS` 仍是 49 条、`TORZNAB_URLS` 里还留着已删的 `/3`（BTSCHOOL）——
两者都只差**一次 `--force-recreate`**（见下面「收尾命令」）。
索引器 HDFans ✅ / NanyangPT ✅ · 状态机 `hlink/state.db` ✅ 605 部 ·
农场 `/volume1/video/download/reseed_farm` ✅ **已建好 475/475**（本地 `.env` 已切，生产未切）·
新脚本 `add-indexers.py`（加站）、`drive-loop.py`（自动续跑）、`build-farm.sh`（建农场）。

> ★ **磁盘 vs 容器**是本项目头号复发坑：`.env` 改了不会自动生效，
> 必须 `up -d --force-recreate`（`restart` **不重新注入环境变量**）。
> `drive-loop.py` 的「索引器自检」（⑧）会在启动时扫日志自动喊出来，见 SUMMARY §13.10。

### 三个包

| 包 | 单片 | 待搜 | 阶段分布 |
|---|---|---|---|
| FRDS | 486 | **~410** | PENDING 331 / UNMATCHED 79 / **SEEDING 76** |
| DC | 115 | **~96** | PENDING 45 / UNMATCHED 51 / **SEEDING 19** |
| MBF | 4 | 0 | ⚠ UNMATCHED 4 |

> **⚠ MBF 已实测：HDFans 上 0 匹配**（4 个季包全 `Found 0 torrents`）。
> 状态已是 `UNMATCHED`，加新站后会自动解锁、**不会重复浪费额度**。

### 怎么继续跑（两种方式）

**方式 A：自动续跑（推荐）**

```bash
# 真跑一轮（当前包下一批，约 24 分钟）
python scripts/drive-loop.py --once --indexers HDFans,NanyangPT --limit 50

# 循环跑：DC↔FRDS 自动轮流，间隔按站点反馈动态调整（45min~4h）
python scripts/drive-loop.py --indexers HDFans,NanyangPT
```

> `drive-loop` 已内置 `--db-path` / `--qbit-url` 默认值（指向 NAS），**回灌不会漏参数**。
> 挂 Windows 计划任务每 15 分钟 `--once` 即可无人值守推进 —— 计划任务指向的是包装器
> **`scripts/drive-loop-once.cmd`**，不是直接指向 `python.exe`：
> python 路径里有**非 ASCII 用户名**，经 `schtasks` / MINGW 传递会被搞坏；
> 包装器用 `%USERPROFILE%` 让 cmd.exe 在**运行时**展开，任务定义本身保持纯 ASCII。
> `--once` 靠 `scripts/.drive-loop.state` 自我节流（有人在跑 / 距上批结束不足 30 分钟 → 直接退出），
> 所以 15 分钟一次**不会**和 24 分钟一批重叠。
> 真实进度一律以 `scripts/drive-loop.log` 为准，**别看终端**（输出会被块缓冲吞掉，SUMMARY §13.8）。

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

★ **下面第 1、4 条现在合并成同一次容器重建** —— 已全部准备好，见本节的「收尾命令」。

1. ~~从 `TORZNAB_URLS` 移除 BTSCHOOL `/3/api`~~ ✅ **文件侧早已完成** ——
   查下来生产 `.env` 里**只有 2 条**（`/2`、`/4`），`/3/api` 早就不在文件里了。
   那些 410 **纯粹是容器没重建**（磁盘上的 `.env` 是对的，跑着的容器用的是旧环境变量）。
   所以不用跑 `add-indexers.py --remove`，**只差 `--force-recreate`**。
   ⚠ 重建会打断正在跑的 drive，务必等当前批次跑完。
2. ~~挂 Windows 计划任务~~ ✅ **已完成**（`reseed-drive-loop`，每 15 分钟 `drive-loop.py --once`）。
3. **换一个站替换 BTSCHOOL**（已在计划中）——加站流程见 SUMMARY §13.3。
4. v3 **硬链接农场**：**农场已建好（475/475）并通过独立复核**，
   切换前的**等价性也已在真实数据上验过**：按 cross-seed 真正用的指纹
   （名字 + 每个文件的相对路径与尺寸）比，49 条 dataDir 与农场**逐条完全相同**
   （1888 = 1888，双向 0 差异）。见 SUMMARY §10.5.7 / §10.5.9。
   ⬜ 只差把 `DATA_DIRS` 切过去 —— **与第 1 条同一次重建**。
5. 编排器 `status` 子命令（见 SUMMARY §11.9）；IYUU 扩散（本范围外）。

#### 收尾命令（一次重建同时办完两件事）

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
> 拦不住 `.env.bak.20260911-204109`。已补 `.env.bak.*` 规则；
> 若你在 NAS 上另存备份，别把任何一份拷进仓库。

详细的过程记录、踩坑与决策都在 **SUMMARY.md**
（老会话见 §11.12 / §11.13 / §11.14 / §12，**本会话见 §13**）。

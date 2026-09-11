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
> `gen-datadirs.py` 生成嵌套包的 `DATA_DIRS` 片段）。
> 它们是**在 Windows 上跑**的工具，不必进容器。由状态机导出的 `unmatched.tsv` /
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
  （87 部里 44 部；详见 SUMMARY §5.3）。想提高就**加索引器**，见下方[扩展 → 多站点](#多站点--提高命中率的唯一手段)。
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
3. 把它的 Torznab 地址追加进 `.env` 的 `TORZNAB_URLS`，**逗号分隔、单行**：
   ```
   TORZNAB_URLS=http://prowlarr:9696/2/api?apikey=<Prowlarr API key>,http://prowlarr:9696/3/api?apikey=<同一个 key>
   ```
   > 用的是 **Prowlarr 自己的 API key**（所有条目共用同一个），不是各站的 passkey。
4. `docker compose restart cross-seed`。**不要**用 `up -d --force-recreate`（见上文警告）。
5. 在 Prowlarr 里对一部电影手动搜一下，确认新站能出结果。
6. **加完站要重跑一轮全量**：对 `DATA_DIRS` 的**根目录**打一次 webhook（见 SUMMARY §6.4），
   cross-seed 会把整包重新遍历一遍。已经命中的会被跳过，只有没命中的才有机会被新站捞到。

> **现成的一个站：SiteB**。它 2026-09-11 上午一度 500/520/522（站点侧故障，与 FlareSolverr 无关），
> 当天中午已自行恢复（实测 matrix 50 条、Se7en 15 条）。
> 它的 Torznab 端点是 `http://prowlarr:9696/1/api`，**直接加回 `TORZNAB_URLS` 即可**。

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
  --url http://NAS_IP:2468 --api-key <CROSSSEED_API_KEY>
```

**`init` 的根怎么给**（两种方式，二选一）：

| 方式 | 写法 | 什么时候用 |
|---|---|---|
| ★从 `.env` 派生 | `--roots-from-env .env --match "<路径关键词>"` | **推荐**。`.env` 的 `DATA_DIRS` 就是 cross-seed 实际会扫的清单，从它派生 ⇒ 状态机与 cross-seed **永不漂移**。多根包（DC 47 根）就靠它一行搞定 |
| 显式列出 | `--root <NAS路径> --local-root <本机路径>`（均可重复传） | 单根包、或想手工挑根时。**多根必须按序一一对应**（第 i 个 `--local-root` 就是第 i 个 `--root` 的 UNC） |

- `--match` 可重复（OR 关系），只取路径里含关键词的 `DATA_DIRS` 条目；不给则全取。
- `--unc-host //YOUR-NAS` 用来把 NAS 路径翻成 UNC；不给则尝试从 `scripts/.nasrc` 的 `NAS_NAME` 推断。
- `--nas-prefix` 默认 `/volume1`，是 NAS 上的卷前缀。
- ⚠ **`--depth` 必须与 cross-seed 的 `maxDataDepth` 完全一致**（本项目未显式配置 ⇒ 用默认值 2）。
  它是"从 dataDir 往下数几层"，第 1..N 层的**目录和视频文件**都算一个 searchee ——
  详见 SUMMARY §10.6。对不上就会出现"状态机有、cross-seed 没有"的幽灵条目。

DC 那种 47 个根的包，一条命令就是全部参数：

```bash
python scripts/reseed-state.py init --pack dc-collection --depth 2 \
  --roots-from-env .env --match "DC相关剧集全系列大合集" --dry-run   # 先核对
```

**分批**：`--limit N` 每批 N 条，`--batch K` 指定第几批（默认第 1 批），
`--plan` 只打印计划不发请求。因为待办清单**已排除已做种的片**、且按
`SKIPPED → ERROR → PENDING → UNMATCHED` 排序，所以 **一批做完重跑同一条命令就自动推进**
（不用记批次号）。`todo` 的路径走 stdout、分批说明走 stderr，管道不会被打扰。

阶段（**由事实推导，不是手工填的**）：

| 阶段 | 含义 | 会重搜吗 |
|---|---|---|
| `SEEDING` | qB 里真有这个 info_hash | ❌ 永不 |
| `MATCHED` | 匹配到、已注入，等 qB 确认 | ❌ 不 |
| `UNMATCHED` | 真搜过、没匹配到 | ⏳ 仅当**出现没搜过的索引器**或过了重搜周期（默认 **7 天**） |
| `SKIPPED` | ★被退避秒跳 | ✅ **立刻** |
| `PENDING` / `ERROR` | 没搜过 / 异常 | ✅ 立刻 |

> **加一个站，所有 `UNMATCHED` 自动变成待搜** —— 不需要人工挑片子。
> 实测：只配 SiteA 时待搜 286 条；加上 SiteB 后那 48 个 `UNMATCHED` 全部解锁。

**重搜周期（每站一周一次）**：粒度是 **(片 × 站)**，来自 cross-seed 自己的
`timestamp(searchee_id, indexer_id, last_searched)` 表。默认每站 7 天，可按站覆盖：

```bash
python scripts/reseed-state.py report --pack $PACK --cadence "SiteA=7,SiteB=30"
python scripts/reseed-state.py todo   --pack $PACK --include-cooldown   # 忽略周期，强制全量重扫
```

`report` 会打印按站周期表（搜过几部 / 到周期几部 / 下次最早可重搜是哪天）。
详见 SUMMARY §11.6。

**`drive` 已经会控速、会等退避、会回灌**（SUMMARY §11.8）：

- `--interval 30` —— 两条 webhook 之间隔 30s，对齐 cross-seed 的 `delay`；
- 每 `--check-every 10` 条读一次 cross-seed.db 的 `indexer` 表，撞上 `RATE_LIMITED`
  就**睡到解禁**（超过 `--max-wait 1800` 秒则中止，不硬刚）；
- 打完自动 `sync` 回灌，直接告诉你 `newly_seeding`（这轮真赚到几部）和
  `still_skipped`（这轮又被退了几部）；
- **默认 dry-run**，不加 `--apply` 不会发任何请求。

> 为什么退避只能读库、不能用 API：cross-seed v6.13 的 HTTP 接口只暴露
> `/api/ping` 与 `/api/status`，`/api/indexerstatus` 是 **404**（见 SUMMARY §11.9）。

- 状态库是 `hlink/state.db`（**运行时数据，已 gitignore**）。它**只读** cross-seed 的库/日志与 qB，
  唯一被写的就是自己。为什么不直接给 cross-seed 的库加字段？见 SUMMARY §11.1。
- 读 cross-seed.db 走**直读 UNC**（`PRAGMA query_only=1`，实测 0.17s 且能看到 WAL 数据），
  拷 `.db/-wal/-shm` 只是兜底。
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

> ⚠ **`--depth` 必须与 cross-seed 的 `maxDataDepth` 完全一致**。两者不一致时，
> 状态机会登记出 cross-seed 根本不搜的**幽灵条目**（永远 PENDING），
> 或者漏掉 cross-seed 真在搜的片子。规则是**纯按深度**的（第 1..N 层的目录和视频文件
> 全是 searchee），不是"含视频才算"—— 详见 SUMMARY §10.6.1。

> 状态机**已支持嵌套包**（2026-09-11）：`init --root` / `--local-root` 可重复传、
> 新增 `--depth`（= cross-seed 的 `maxDataDepth`，**必须与它一致**）。
> DC 47 根 → 115 单片已能正常登记，详见 SUMMARY §10.4 / §10.6。

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

**它只动 `DATA_DIRS` / `LINK_DIR` 两行，其余键逐字节保留** —— 因为本地 `.env` 里的
`TORZNAB_URLS` 是脱敏占位符（`apikey=xxxx…`），生产上是真实密钥，串了就是全线 401。
写盘前有一道硬闸：把两边除这两键外的所有行各导一份做 `cmp -s`，不一致就打印 `diff` 并拒绝写入。
中间文件全放 compose 目录里（相对路径 + `trap` 兜底），跑完一个都不留。

> ⚠ **怎么确认它真的生效了**：`.env.new` 存在 ≠ `.env` 已更新。判断一律看这两处 ——
> `sudo docker inspect reseed-cross-seed --format '{{range .Config.Env}}{{println .}}{{end}}' | grep '^DATA_DIRS='`
> 的条数，或 `cross-seed.db` 的 `data` 表里有没有新包的路径。
> 详见 SUMMARY §11.12。

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

### IYUU 扩散（本次不实现）

单种在 `:3060` 做种后，由 IYUU 读其 InfoHash 扩散到更多站点。`hlink/config.yml` 里 `jobs[].iyuu_handoff` 为其预留开关。

### 别的匹配器（本次不实现）

`orchestrator/matcher.py` 的 `Matcher(ABC)` 是接口落点；`hlink/config.yml` 的 `matcher.engine` / `jobs[].matcher_engine`
预留 `iyuu`/`custom`（当前会明确报"未实现"）。

## 安全

- `.env`、`cross-seed/`（含 cross-seed 自建的 db）、`prowlarr/`（Prowlarr 配置）**不要提交/外传**——含 cookie/passkey/apikey。
- PT 站凭据只进 **Prowlarr**；`:3060` 走局域网免密白名单（或 `.env` 里的密码），二选一。

---

## 当前状态与下一步（2026-09-11 收尾归档）

> 本节点已停止所有自动动作（不再发 webhook、不再 drive）。下面是交接快照。

### 系统现状

| 项目 | 状态 |
|---|---|
| NAS `.env` | ✅ `DATA_DIRS` = **49 条**，真实密钥保留 |
| cross-seed 容器 | ✅ 已重启（16:00），`Validated 1888 entries from dataDirs` |
| cross-seed.db `data` 表 | ✅ **1963 行**（FRDS 932 / DC ~993 / MBF 38） |
| 状态机 `hlink/state.db` | ✅ **605 部**（gitignored，本地管理，勿提交） |
| cross-seed API / qBittorrent | ✅ 可达（`:2468` OK / qB v4.6.5） |

### 三个包

| 包 | 单片 | 待搜 | 阶段分布 |
|---|---|---|---|
| FRDS | 486 | **390** | PENDING 108 / SKIPPED 282 / UNMATCHED 48 / SEEDING 48 |
| MBF | 4 | **0** | ⚠ **UNMATCHED 4** —— 实测 HDFans 上 0 匹配，见下 |
| DC | 115 | **115** | PENDING 115 |

> **⚠ MBF 已实测：HDFans 上 0 匹配。**
> 4 个季包各搜一次，cross-seed 全部 `Found 0 torrents`，`searchee` 表里始终没有记录。
> 当前单站条件下**做不了种**。出路：给 Prowlarr 加别的站再搜，或暂时放弃把额度留给 DC/FRDS。
> 状态机已回灌为 `UNMATCHED`（不会重复浪费额度），加站后会自动解锁。详见 SUMMARY §12.3.1。

### 恢复执行时的命令（**先 `--plan`，确认后再加 `--apply`**）

完整命令必须带 `--db-path`，否则回灌会被跳过（这是个坑，见下）：

```bash
# 通用参数
URL=http://192.168.0.7:2468
KEY=<CROSSSEED_API_KEY>
DB="//iSunker-DS423/docker_ssd/prowlarr_cross-seed_autohardlink/cross-seed/cross-seed.db"

# ⚠ MBF 不用再跑了 —— 已实测 HDFans 0 匹配（UNMATCHED），见上文。
#    除非你已给 Prowlarr 加了新站；加站后它会自动解锁。

# 1) DC（115 部，3 批，每批约 24 分钟）—— 从这里开始
python scripts/reseed-state.py drive --pack dc-collection --indexers HDFans --limit 50 \
  --url $URL --api-key $KEY --db-path "$DB" --apply

# 2) FRDS（390 部，8 批，每批约 24 分钟）—— SKIPPED 优先，排在最前
python scripts/reseed-state.py drive --pack frds-top250-2024 --indexers HDFans --limit 50 \
  --url $URL --api-key $KEY --db-path "$DB" --apply
```

**一批做完重跑同一条命令就自动推进**，不用记批次号。

### ⚠ 本次踩到的坑（交接必读）

1. **`drive` 忘给 `--db-path` → 回灌被跳过，状态不更新。**
   现象：webhook 全发成功（204），但结尾打
   `[!!] 回灌需要 --db-path（cross-seed.db 路径），已跳过`，退出码 3。
   补救：补上 `--db-path` 重跑，或单独跑 `sync` 回灌（都不发新请求，幂等）。

   ⚠ 附带一个**假象**：补 `--db-path` 重跑时终端可能返回**空输出**，看着像"没执行"，
   但 cross-seed 日志里其实有 `Searching for` 记录 —— 它跑完了，只是输出被吞了。
   **判断 drive 是否真跑，查 cross-seed 日志，别看终端。**
2. **`.env.new` 存在 ≠ `.env` 已更新。** 判断是否生效一律看
   ① 容器内 `DATA_DIRS` 条数 ② `cross-seed.db` 的 `data` 表，别看 `ls`。
3. **别对大包根打 webhook。** cross-seed 的 webhook 是单线程顺序处理，
   中途撞一次 429 → 后面几百条全部 `Skipped searching (filtered by temporarily
   disabled indexers)`。已实测：一次 429 废掉 295 条。改用 `drive --limit N` 分批。
4. **`--depth` 必须等于 cross-seed 的 `maxDataDepth`**（本项目默认 2），
   对不上就会出现"状态机有、cross-seed 没有"的幽灵条目。

### 还没做

- v3 **硬链接农场**（1 条 dataDir 取代 49 条）—— 设计已完成，见 SUMMARY §10.5。
- Phase 2.6 重跑全量（等合适时机）。
- 编排器 `status` 子命令（见 SUMMARY §11.9）。

详细的过程记录、踩坑与决策都在 **SUMMARY.md**（尤其 §11.12 / §11.13 / §11.14）。

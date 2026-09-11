# 大包拆包 · 单种保种工具链 v1 —— 方案与进度总结

> 最后更新：2026-09-11（§5.3 已修正：全量**没跑完**，只搜了 87/382，真实命中率 ~50%；
> §6.1 SiteB 已恢复；§6.5 429 真因是站点 502；§6.6 indexerId 会变；
> **§11 单片状态机已实现**，含 **§11.6 按站重搜周期（默认每站 7 天）** 与
> **§11.8 `drive` 控速 + 退避闭环**；§11.10 说明 `orchestrator/main.py`；
> **§10 多包支持已落地**，含 **§10.2 嵌套结构陷阱（DC 案例）**）
> 本文件是给「下一次接手的人（或下一个会话）」看的。读完这一篇应当能直接接着干，
> 不需要回翻聊天记录。

---

## 0. 占位符约定（本文档已脱敏）

为便于公开分享，真实的主机名、内网 IP、私有站名已替换为占位符。**照着做时请自行替换**：

| 占位符 | 含义 | 怎么填 |
|---|---|---|
| `YOUR-NAS` | NAS 主机名 | DSM → 控制面板 → 网络 → 服务器名；SMB 路径里就是 `\\YOUR-NAS\...` |
| `NAS_IP` | NAS 的局域网 IP | 路由器里查，或 NAS 网络设置里看 |
| `SiteA` / `SiteB` | 两个 PT 站 | 你在 Prowlarr 里接入的索引器名，随便几个都行 |
| `sitea` / `siteb` | 上面两个站的小写形式 | 同上（出现在域名/文件名里） |
| `PUID` / `PGID` | 容器运行用户 | DSM 上 SSH 执行 `id 你的用户名` 取前两个数字 |

脚本里没有硬编码这些值：`scripts/run-batch.sh` 与 `deploy.sh` 会读环境变量，
也可写进 `scripts/.nasrc`（该文件已 gitignore，不会外传）：

```bash
NAS_HOST=192.168.1.10
NAS_NAME=my-nas
DST="//my-nas/docker_ssd/prowlarr_cross-seed_autohardlink"
```

---

## 1. 目标（v1 范围）

把一个**已经在做种的多片大包**，让其中**每一部单片也各自作为单种做种**，且**零磁盘开销**（硬链接）。

- 大包：`DouBan_IMDB.TOP250.Movies.Mixed.Collection.20240501.FRDS`
  （"TOP250" 是片单名，**实测根目录下有 383 个子目录**，剔除清单目录后 382 部）
- 单种落地在**隔离的第三个 qBittorrent 实例** `qbittorrent-reseed`（:3060），
  与现有的其它 qB 实例互不干扰
- 不动大包原文件，单种数据用 hardlink 指向大包内的同一批 inode

**明确不在 v1 范围**：IYUU 扩散、其它大包、其它匹配器。配置里这些字段标了「★预留」，
留了接口但不实现。

---

## 2. 拓扑

```
                         ┌─────────────────────────────────────┐
  PT 站 (sitea …) ──────│ prowlarr  :9696                     │
                         │   把各 PT 站包装成 Torznab 源        │
                         └───────────────┬─────────────────────┘
                                         │ Torznab 查询
                         ┌───────────────▼─────────────────────┐
                         │ cross-seed :2468  (daemon)          │
                         │  按「名称+大小」内容匹配，不看 infohash │
                         │  匹配中 → 在 LINK_DIR 建硬链接        │
                         │        → action:inject 推给 qB       │
                         └───────────────┬─────────────────────┘
                                         │ WebUI API v2
                         ┌───────────────▼─────────────────────┐
                         │ qbittorrent-reseed :3060            │
                         │  （独立 compose 栈，不在本栈内）      │
                         │  分类 reseed-singles                 │
                         └─────────────────────────────────────┘

  reseed-orchestrator（一次性 CLI）：preflight / run --job / status
```

**物理路径**

| 用途 | 路径 |
|---|---|
| 生产栈目录（NAS） | `/volume2/docker_ssd/prowlarr_cross-seed_autohardlink` |
| 同一目录的 SMB 视图 | `\\YOUR-NAS\docker_ssd\prowlarr_cross-seed_autohardlink` |
| 本地开发目录 | `D:\Projects\dabaochaibaozuozhongxiangmu\reseed-toolkit` |
| 大包源数据 | `/volume1/video/download/movies/DouBan_IMDB...FRDS` |
| 硬链接落地目录 | `/volume1/video/download/reseed_singles` |
| 实际链接位置 | `.../reseed_singles/<Tracker>/<发布名>`（`flatLinking:false` 会按站点分子目录） |

> ★ 源目录与 LINK_DIR **必须同一物理卷**（都在 `/volume1`，实测 device 均为 191），
> 否则硬链接建不了。compose 里对两个服务都是 `/volume1/video:/volume1/video` 1:1 挂载，
> 就是为了让容器内外路径完全一致，省掉路径映射这一层心智负担。

NAS：Synology NAS，主机名 `YOUR-NAS`，局域网 IP `NAS_IP`，PUID / PGID 按你 DSM 上的实际值填。
> 本文档为脱敏版：真实主机名、内网 IP、站点名已替换为占位符（见 §0 占位符约定）。

---

## 3. 关键决策与踩过的坑

### 3.1 群晖上的 Docker 回环（hairpin NAT）—— 已解决

**现象**：cross-seed 容器访问 `http://NAS_IP:3060` 一律 timeout。
**原因**：容器 A（bridge `172.30.x`）→ 宿主机 LAN IP → DNAT 回容器 B（bridge `172.29.x`），
群晖上这条回环路径不通。
**解法**：把本栈接入 qbittorrent-reseed 所在的 docker 网络，**用服务名直连**。

```yaml
networks:
  reseed-net:
    driver: bridge
  qbit-net:
    external: true
    name: qbittorrent-reseed_default   # 由 qbittorrent-reseed 自己的 compose 创建
```

`cross-seed` 和 `reseed-orchestrator` 都 `networks: [reseed-net, qbit-net]`，
地址写 `http://qbittorrent-reseed:3060`。

> **不要改回 `${NAS_IP}:3060`**。这一点在 `docker-compose.yml` 和 `hlink/config.yml`
> 里都写了行内注释，就是防止以后有人"顺手改回去"。

### 3.2 qBittorrent 免密白名单必须包含 `172.16.0.0/12`

容器过来的源 IP 是 `172.x.x.x`，不是 `192.168.x.x`。
`patches/reseed-qbit.conf.md` 里只推荐了 `192.168.0.0/16, 127.0.0.1/32`，**不够**。
最终 `qBittorrent.conf` 用的是：

```ini
WebUI\AuthSubnetWhitelistEnabled=true
WebUI\AuthSubnetWhitelist=192.168.1.0/24, 127.0.0.1/32, 172.16.0.0/12
WebUI\LocalHostAuth=false
WebUI\CSRFProtection=false
WebUI\ClickjackingProtection=false
WebUI\HostHeaderValidation=false
WebUI\Port=3060
```

### 3.3 :3060 实例的保种专用设置（Phase 0，已完成）

```ini
Session\AddTorrentPaused=true      # 文件里是 true，运行时经 API setPreferences 改成 false
Session\Port=56883                 # 与其它 qB 实例错开
Session\DHTEnabled=false
Session\LSDEnabled=false
Session\PeXEnabled=false
Session\QueueingSystemEnabled=false   # 250 个种，不能排队
```

（`Connection\PortRangeMin=6881` 在 qB 4.6.5 已是残留字段，无影响。）

### 3.4 Torznab URL 的写法

cross-seed 走的是 Prowlarr 的 **Torznab 代理端点**，用的是 **Prowlarr 自己的 API key**，
不是 PT 站的 passkey：

```
TORZNAB_URLS=http://prowlarr:9696/<indexerId>/api?apikey=<Prowlarr API key>
```

| indexerId | 站点 | 状态 |
|---|---|---|
| 1 | SiteB | ❌ **已从 TORZNAB_URLS 移除**，站点侧故障，见 §6.1 |
| 2 | sitea | ✅ 在用 |

主机名用 `prowlarr`（同栈服务名），不要用 NAS IP。

### 3.5 cross-seed 的注入在「客户端为空」时必定失败 —— 冷启动坑

**这是本项目踩得最深的一个坑，值得单独记一笔。**

**现象**：cross-seed 明确报 `Found ... by MATCH`、硬链接也建了，紧接着
`failed to inject, saving...`，然后把刚建的链接 `Unlinking` 删掉，
`.torrent` 落到 `cross-seeds/` 目录里当"未注入产物"。

**排查过程**：
- `LINK_DIR` 同卷？→ `stat` 两边 device 都是 191，✅
- 手工 `ln` 能不能建？→ 能，link count 变 2，✅
- qB 能不能连？→ 日志里 `Logged in to v4.6.5 successfully`，✅
- 抓 verbose 日志里整个注入窗口 → **全程没有出现过一次 `/torrents/add` 请求**

**根因**：cross-seed 在 `/torrents/add` 之前会先调 `/torrents/info {}`（列出全部种子）。
当客户端里**一个种子都没有**时，返回的空列表命中了它的失败分支，
于是**直接判定注入失败、根本没走到 `/torrents/add`**。

**解法**（一次性，之后永久有效）：
1. 先把分类建出来（当时 `/torrents/categories` 返回 `{}`，分类压根不存在）：
   ```bash
   curl -s -X POST "$Q/api/v2/torrents/createCategory" \
     -d "category=reseed-singles" --data-urlencode "savePath=$SP"
   ```
2. **手工往 :3060 里塞第一个种子**（用 cross-seed 之前存在 `cross-seeds/` 里的
   那个 `.torrent` 即可）：
   ```bash
   curl -s -X POST "$Q/api/v2/torrents/add" -F "torrents=@/tmp/t.torrent" \
     -F "savepath=$SP" -F "category=reseed-singles"
   # 返回 Ok.
   ```
3. 之后再打 webhook，注入就一路正常了（第二部 V for Vendetta 直接
   `injected` ×2 个版本）。

> 以后如果清空了 :3060 的所有种子，这个坑会**再次出现**。记住：保持客户端里
> 至少有一个种子。

### 3.6 搜索频率该设在哪：cross-seed 的 `delay`，不是 Prowlarr 的 Query Limit

两者性质完全不同：

| | 作用 | 超限时的行为 |
|---|---|---|
| cross-seed `delay`（config.js） | **节流**，搜索之间真的等那么久 | 不存在"超限"，只是慢 |
| Prowlarr per-indexer Query Limit | **硬上限 / 保险丝** | 直接回 429 拒绝查询 → 对 cross-seed 就是**一次失败的搜索**，那部片子这一轮就漏了 |

**结论：节奏控制放 cross-seed，Prowlarr 的限额只当保险丝，设成明显高于实际用量的值。**
用保险丝当油门，就会复现 §6.1 里 SiteB 那个局面：一堆 429、退避越滚越长、搜索白白丢掉。

- `cross-seed/config.js` → `delay: 30`（第 54 行）。全量时建议提到 `45`。
- Prowlarr → sitea → Settings → Query Limit 设 `1000` / Limits Unit `Day` 之类。

**注意每个大包子目录会触发两次搜索**（目录级 + 里面的 .mkv 文件级，日志里的
`(1/2)` / `(2/2)`）。实测大包里有 **382 个子目录**（不是 250——"TOP250"是片单名，
实际目录数更多），剔除清单目录后约 380 部 ≈ **760 次搜索**，
按 `delay:45` 算约 9.5 小时。挂着跑即可。

---

## 4. 各文件最终状态（要点）

### `docker-compose.yml`（本地名）→ `compose.yaml`（生产名）

四个服务：`prowlarr`(9696) / `flaresolverr`(8191，可选) / `cross-seed`(2468) / `reseed-orchestrator`(一次性)。

- `cross-seed` 以 `user: "${PUID}:${PGID}"` 运行 → 建出来的硬链接属主/权限与大包一致
- `cross-seed` 只 `depends_on: [prowlarr]`，所以 flaresolverr 拉不动镜像也不阻塞主链路
- `reseed-orchestrator` 的 `restart: "no"`，它是 `docker compose run --rm` 用的

> ⚠ **重启单个服务时用 `restart`，不要用 `up -d --force-recreate`**。
> 实测 `up -d --force-recreate cross-seed` 会连带重启 prowlarr，导致 cross-seed
> 在 Kestrel 起来之前就去拉 caps，报 `fetch failed` / `no working indexers`。
> 正确做法：先确认 prowlarr 返回 200，再 `docker compose restart cross-seed`。

### `.env`（**不进版本库**，生产上单独维护）

```
PUID=1026  PGID=100  TZ=Asia/Shanghai  NAS_IP=NAS_IP
TORZNAB_URLS=http://prowlarr:9696/2/api?apikey=<Prowlarr API key>   # 2 = sitea
QBIT_AUTH_MODE=subnet_whitelist
QBIT_CATEGORY=reseed-singles
LINK_DIR=/volume1/video/download/reseed_singles
LINK_TYPE=hardlink
MATCH_MODE=partial
SKIP_RECHECK=false
CROSSSEED_API_KEY=<建议用 openssl rand -hex 32 重新生成>
```

### `cross-seed/config.js`

cross-seed **v6.13.7**。v6 的字段名：`linkDirs`（数组，不是 v5 的 `linkDir`）、
`matchMode: "partial"`、`action: "inject"`、`dataDirs`（其子目录即"待匹配单片"）。
`linkCategory` 取自 `QBIT_CATEGORY`。`delay: 30` 在第 54 行，
第 63 行的注释列了 `rssCadence` / `searchCadence` / `excludeRecentSearch` / `snatchTimeout`
这几个进阶项。

> 待办：`qbittorrentUrl` 已被官方标记 deprecated，应迁移到 `torrentClients`。
> 管线跑通之后再动，现在不碰。

### `hlink/config.yml`（编排器主配置，日常主要编辑这个）

`qbittorrent.url` / `matcher.crossseed_url: http://cross-seed:2468` /
`wait_timeout_sec: 900` / `poll_interval_sec: 15` /
job `frds-top250-2024` 指向大包 `source_dir`。

`${XXX}` 会在加载时用环境变量展开；标「★预留」的字段本版本不生效。

> 待办：全量跑之前给 job 加上
> `exclude: ["0观影清单*", "@eaDir", "*sample*"]`。
> `0观影清单chrlee整理` 是一个文本清单目录，不是电影，不该参与匹配。

### `scripts/run-batch.sh` —— 小批量试跑与度量

在 **Windows 的 Git Bash 里直接跑**（三个端口都已发布到宿主机，不需要 SSH 上 NAS）。
从大包里等间隔抽样若干部，逐部打 webhook 并计时，产出命中率 / 单部耗时 / 限流信号。
详见 §5.2。

### `deploy.sh` —— 本地改完直接覆盖到生产

**白名单式**同步，15 个条目，`<本地路径>::<生产路径>` 语法（含
`docker-compose.yml::compose.yaml` 这个改名）。

```bash
bash deploy.sh              # 默认 dry-run，只打 diff -u
bash deploy.sh --apply      # 先备份到本地 .deploy-backup/<时间戳>/ 再覆盖
bash deploy.sh --rollback   # 回滚到最近一次备份
```

**安全性来自"白名单"本身**：`.env` / `prowlarr/` / cross-seed 的 db 与输出 / hlink 日志
**根本不在 FILES 数组里**，所以永远动不到。备份放本地而不是 NAS，避免污染 docker build 上下文。

---

## 5. 进度

| 阶段 | 内容 | 状态 |
|---|---|---|
| Phase 0 | 修 :3060 的 qBittorrent.conf（白名单/端口/DHT/队列） | ✅ 完成 |
| Phase 1 | Prowlarr 接入 PT 站 + 拿到 Torznab URL | ✅ 完成（sitea；SiteB 搁置） |
| Phase 2 | cross-seed 试点：匹配 → 硬链接 → 注入 :3060 | ✅ **完成**（见 §5.1） |
| Phase 2.5 | 10 部小批量：测命中率 / 单部耗时 / 限流 | ✅ 结论：**限流干净（delay:30 安全）**；命中率被 §6.4 污染，改由 §5.3 的全量数据替代 |
| Phase 2.5+ | 整包全量（一次根目录 webhook，见 §6.4） | ⚠ **未真正完成**：只搜了 87/382 就被站点 502→429 打断；已搜部分命中率 ~50%，见 §5.3 |
| Phase 2.6 | **重跑一次完整全量**（先把 SiteB 加回去，见 §6.1） | ⬜ **待做** —— 清单已生成（`scripts/todo.txt`，334 条），等一个合适的时机执行 |
| Phase 2.7 | **单片状态机**（sidecar `hlink/state.db`，见 §11） | ✅ **已实现并实测**：382 部 → SEEDING 48 / UNMATCHED 48 / SKIPPED 282 / PENDING 4 |
| Phase 2.8 | **按站重搜周期**（默认每站 7 天，可 `--cadence "SiteA=7,SiteB=30"`，见 §11.6） | ✅ **已实现并验证** |
| Phase 2.9 | **`drive` 控速 + 退避闭环**（`DriveSession`：`--interval` 节流、撞退避就等、打完自动 `sync` 回灌，见 §11.8） | ✅ **已实现**（默认 dry-run，`--apply` 才真发） |
| Phase 3 | 编排器 build / preflight / run --dry-run / run / status | ⬜ 未开始（`run` 已非必要，见 §6.4；`status` 仍值得做；`main.py` 说明见 §11.10） |
| v2-a | **多包接入**：MBF（剧集，每季）+ DC（嵌套，47 个 dataDir） | ✅ **配置已落地**，见 §10.1 / §10.2 |
| v2-b | 状态机支持嵌套包（多根 + 深度） | ⬜ **未做** —— DC 目前 cross-seed 会搜、但状态机看不到，见 §10.4 |
| v2-c | **`--limit` 分批 + 优先级排序**（`--batch` / `--plan`） | ✅ **已完成并实测**，见 §11.7.1 |

### 5.1 Phase 2 验收结果

试点 2 部，产出 3 个单种，全部做种中：

```
/torrents/info?category=reseed-singles  →  3 条，progress:1  state:stalledUP
  · 12th.Fail.2023.…-KHN
  · V.For.Vendetta.2005.…MNHD-FRDS   （ff3d9aa1 / f4c7ba3a 两个版本都命中）
```

`ls -lR /volume1/video/download/reseed_singles/SiteA` 中**每个文件的链接数都是 2**
（cover.jpg / .mkv / .nfo 全部），与大包内是同一批 inode ——
**零磁盘开销这条核心目标已实测成立**。

顺带验证到的两件事：

- **中文目录名不影响匹配**。`V字仇杀队…` 这种中文子目录照样匹配、照样注入成功。
  cross-seed 是按"内容（文件名+大小）"匹配的，外层目录叫什么无所谓。
- **硬链接就是大包里的那份数据本身**，不是拷贝。所以单种做种时上传的字节
  和大包做种时是同一批物理块，两个种子共用。

试点里没匹配上的（Se7en、Seven Samurai）是**正常结果**：sitea 上只有 2160p 版本，
我们大包里是 1080p，内容大小对不上，本来就不该匹配。

### 5.2 Phase 2.5：10 部小批量怎么跑

```bash
cd /d/Projects/dabaochaibaozuozhongxiangmu/reseed-toolkit
bash scripts/run-batch.sh
```

脚本做的事：

1. 从生产 `.env`（经 SMB 读，不回显）取 `CROSSSEED_API_KEY` 和 Prowlarr API key
2. 跑之前先查 Prowlarr `/api/v1/indexerstatus`，**必须是 `[]`**，否则直接退出
   （处在退避窗口里跑，测出来的命中率全是假的）；再确认 qB 里至少有 1 个种子
   （否则会撞上 §3.5 那个冷启动坑）
3. 列出大包所有子目录（实测 **382 个**），剔除 `0观影清单*` / `@eaDir` / `*sample*`，
   **再剔除已经注入过的**（重复打 webhook 只会得到 `ALREADY_EXISTS`、新增 0 个种子，
   会被误记成 MISS 把命中率压低），然后**等间隔抽 10 部**
   ——不是取前 10 部，前 10 部字母相邻，做不出有代表性的命中率
4. 逐部：打 webhook → 轮询 qB 分类 `reseed-singles` 的种子哈希集合 →
   有新增就记命中和耗时；连续 30 秒不再增加就提前进入下一部；最长等 180 秒
5. 跑完再查一次 `indexerstatus`
6. 产出 `scripts/batch-report.tsv` 和一段汇总（含全量墙钟时间估算）

先 `DRY=1 bash scripts/run-batch.sh` 看一眼抽中哪几部、体检过不过，再正式跑。

**跑之前不要调 `delay`**。这一轮就是要测 `delay:30` 到底会不会触发 sitea 的限流，
提前改成 45 就测不出来了。

> ⚠ **2026-09-11 这轮抽样跑了两次，两次都作废：**
>
> **第一次（10 部全 400）**：脚本把 NAS 路径写在 curl 的命令行参数上，被 MINGW 的路径转换
> 改写成 `C:/Program Files/Git/volume1/…`（中文还变成乱码），cross-seed 一律回 HTTP 400
> —— 请求根本没进匹配，却被记成 `MISS`。已按 §6.3 修好（路径改走 stdin），
> 并新增 `ERR` 状态防止 400 被误记成 MISS。单部冒烟测试通过（`HTTP 204` / 16s 出种）。
>
> **第二次（10 部全 HIT，但也是假的）**：脚本本身工作正常（10 部全部 `HTTP 204`，
> `indexerstatus` 前后都是 `[]` —— **delay:30 确实不会触发 sitea 限流，这个结论有效**），
> 但当时 cross-seed 里还有一个**整包后台任务在跑**（见 §6.4），它持续注入别的片子，
> 把每部的 `new_torrents` 都撑了起来 → 10 部全被判 HIT、共"新增 30 个"。
> 逐部对齐日志后，**真正自己匹配上的只有 3~4 部**（模仿游戏 / 猜火车 / 虎胆龙威，
> 外加 `X战警合集` 拆出的 X 战警系列）：
>
> | 抽中的片子 | 报告 | 实情 |
> |---|---|---|
> | X战警合集 / 模仿游戏 / 猜火车 / 虎胆龙威 | HIT | ✅ 真命中 |
> | 光荣之路 / 因父之名 / 小姐 / 我的父亲我的儿子 / 纽伦堡大审判 / 钢铁巨人 | HIT | ❌ 假阳性（命中时间早于自己的搜索） |
>
> **结论：真实命中率约 4/10，`new_torrents` 合计 30 是虚高的。**
> 脚本已加 60s 静置体检（§6.4），后台有任务时会直接拒绝开跑。
> 想要一个干净的数字，等后台任务结束（或重启 cross-seed 容器）后重跑本脚本。
> 当前待办子目录约 **366 个**。

三个指标怎么读：

| 指标 | 从哪看 | 怎么判断 |
|---|---|---|
| 实际命中率 | 汇总行 `命中 N/10` | ≥5/10 就值得直接全量；<3/10 说明该加索引器了 |
| 单部耗时 | `secs_to_first_hit` 列 + 汇总的小时估算 | 注意 MISS 的那几部会跑满 180s 超时，把平均拉高，全量估算偏保守 |
| 有没有限流 | 跑完的 `indexerstatus` | 必须仍是 `[]`；非空就是被退避了，`delay` 要往上提 |

> 抽样里出现已知会 MISS 的片子是正常的。比如**七武士**，sitea 上只有 2160p，
> 我们是 1080p，本来就不该匹配——这正是命中率要测出来的东西。

限流还有一个佐证，在 NAS 上看（脚本查不到容器内日志）：

```bash
sudo docker logs --tail=400 reseed-cross-seed 2>&1 | grep -iE '429|retry-after|rate.?limit'
```

无输出 = 干净。

### 5.3 整包扫描：**没跑完**，真实命中率也不是 12.6%

> ⚠ 本节 2026-09-11 当天被**重写过一次**。初版写的是「整包跑完、命中率 12.6%」，
> 后来把日志逐行对了一遍，发现那是**误读**。以下是修正后的版本。

**结论先行**：日志里的 `(384/384)` 是「**列表遍历结束**」，不是「**搜索完成**」。
真正被搜索的只有 **87 / 382**，其余 **295 条被 cross-seed 秒跳**。
12.6% 是把「根本没搜过的」也算成「没命中」除出来的，**严重低估**。

#### 时间线（2026-09-11）

| 时刻 | 事件 |
|---|---|
| 11:41:15 | 误打的根目录 webhook 被受理（见 §6.4），开始逐目录搜索，日志出现 `(N/384)` |
| 11:41:17 → 12:24:21 | 稳定 **2 条/分钟**（≈ `delay:30`），进度走到 `(89/384)`；**87 条真搜过** |
| 12:24:21 | sitea 开始返回 `BadGateway`，Prowlarr 重试 |
| 12:24:28.0 | `https://site-a.example/login.php` → **502 BadGateway** |
| 12:24:28.2 | Prowlarr 把 SiteA 标为不可用 → 回给 cross-seed **429**，`snoozing until 12:25:28` |
| 12:24:28 → 12:24:29 | 剩余 **295 条**全部 `Skipped searching on indexers`，**1.5 秒**推到 `(384/384)` |

> cross-seed 的行为是：索引器被退避时，**待搜索项直接跳过，不排队、不重试**。
> 所以进度条走完 ≠ 搜索做完。**这是本项目最容易误判的一个坑。**

#### 真实命中率（把 87 条真搜过的与 `unmatched.tsv` 求交集）

| 项 | 数值 |
|---|---|
| 大包可用子目录 | 382 |
| **真正搜过的** | **87**（`N = 3..89`） |
| 被跳过的 | **295**（`N = 90..384`） |
| 搜过 ∧ `HIT` | **44** |
| 搜过 ∧ `UNMATCHED` | 41 |
| 搜过但清单里找不到 | 2 |
| **已搜部分命中率** | **44 / 87 ≈ 50.6%** |
| 全部注入事件 | 72 次（**全部落在 `N ≤ 87` 区间内**） |

遍历顺序是 **readdir 顺序**（不是字典序 —— 实测尾部序列是 出租车司机 → 切腹 → 勇士 → 勇敢的心），
可以近似当成**随机抽样**。于是：

- **整包真实命中率 ≈ 50%**（n=87，95% 置信区间约 **40%~61%**）。
- 全量跑完预计能匹配 **≈ 190 部**，而不是 48 部。
- 被跳过的 295 条里，**大约还藏着 150 部没被发现的单种** —— 这才是本次最大的损失。

#### ETA 的算法

```
每条耗时 ≈ delay(30s) × 索引器数
单站：382 条 ÷ 2 条/分钟 ≈ 191 分钟 ≈ 3.2 小时
两站：约翻倍（每条要向两个站各发一次请求）
```

- 之前估的「至少 2 小时」偏乐观，**单站要按 3 小时以上排**。
- 实际只跑了 43 分钟（87 条）就被 502/429 打断 —— **远没到 2 小时，也远没跑完**。

#### 修正后的结论

- ❌ 旧说法「单站命中率 12.6%」→ ✅ 应改为「**单站已搜部分命中率 ~50%**」。
- 想拿到那 ~190 部，需要**重跑一次全量**，并且要**盯住中途有没有被退避打断**。
- 打断本次全量的 429，根因是**站点侧 502**，不是我们搜太快 —— 见 §6.5。
- 仍然成立的两条：
  - 没匹配上的绝大多数是「站点上压根没有这个单种（或只有别的分辨率/压制组）」，不是配置问题。
  - `X战警合集` / `教父合集` / `洛奇合集` 这种**合集目录会被拆成多个单种**分别匹配
    （合集本身不是单种，里面每部电影各自成种）。

---

## 6. 已了结的坑（保留记录，避免重走）

### 6.1 SiteB 的 Torznab 文本搜索返回 500 —— 站点侧故障，已放弃

**症状链**：webhook → `Found 0 torrents`；Prowlarr 日志里是
`SiteB → 500.InternalServerError (0 bytes)`，查询压根没到达站点；
连续 500 触发 Prowlarr 的失败退避 → HTTP 429 + `Retry-After` 从 300 涨到 492。

**隔离实验**：

| 测试 | 请求 | 结果 | 结论 |
|---|---|---|---|
| CAPS | `t=caps` | 200，完整 caps XML | Prowlarr / apikey / indexerId **全对**（纯本地，不碰站点） |
| A | `t=search`（**不带** `q=`） | 200，98462 字节真实条目 | **cookie 有效、站点可达**，排除 cookie 失效 |
| B | `t=search&q=V+For+Vendetta+2005`（纯 ASCII） | 空 / 连接被断 | 与语言无关，证伪"中文打挂 PHP"的假设 |
| C | `t=search&q=<中文>` | 429 | B 的连带退避 |
| D | `t=movie&imdbid=tt0434409` | 空 | 见下 |

**最终定性**：在容器里找到自定义 Cardigann 定义（真实路径是
`/config/Definitions/siteb.yml`，**不是** `/app/prowlarr/bin/Definitions`，那个目录在
linuxserver 的 Prowlarr 2.5.2 镜像里不存在）。读完 `search:` 段发现：
**IMDBID / DoubanID / Keywords 三种查询全都走同一个 `torrents.php`**，
只是 `search_area` 不同（4=imdb / 1=douban / 0=关键词）。
也就是说"用 IMDB ID 能绕过去"这个假设**被证伪了**——没有第二条路径。

再看 Prowlarr 日志，500 之后紧跟的是 **Cloudflare 520 / 522** 和
`Http request timed out`。520/522 是 Cloudflare 特有的"回源失败"码，
说明**挂掉的是站点自己的后端**，不是我们这边任何配置。

→ **当时定性：SiteB 站点侧故障，与 FlareSolverr 无关**，已从 `TORZNAB_URLS` 移除
（indexer 本身还留在 Prowlarr 里）。

#### ⚠ 补充（2026-09-11 12:49 复测）：**SiteB 已经自己恢复了**

```
GET /api/v1/search?query=matrix&indexerIds=1   → 50 条
GET /api/v1/search?query=Se7en&indexerIds=1    → 15 条
Prowlarr 日志 12:49 段：无任何 warn/error
```

→ 所以它是**间歇性站点故障**，不是永久报废。**可以（也应该）把 `/1/api` 加回 `TORZNAB_URLS`**，
立刻多一个索引器、命中率按 §5.3 的逻辑大概能再上一截。

#### 「要不要配 FlareSolverr」的判定表

| Prowlarr 手动搜该站，看到的是… | 说明 | 配 FlareSolverr 有用吗 |
|---|---|---|
| `403` + 一段 HTML 挑战页 / 日志出现 `Cloudflare`、`cf-mitigated` | 被 CF 挡在门外 | ✅ 有用 |
| `500` / `502` / `520` / `522` / `Http request timed out` | 请求**已穿过 CF**，站点后端挂了 | ❌ 没用 |
| `429` + `Retry-After` | 站点限流 | ❌ 没用（该降 `delay`） |
| 能返回条目 | 一切正常 | ❌ 不需要 |

SiteB 当时命中的是第 2、3 行，**所以不是 FlareSolverr 的问题**。

### 6.2 其它一次性坑

- 用 `until` 循环等退避解除时按了 Ctrl+Z，循环被挂起，打出来的 `✓ 已解禁` 是假的。
  → 用 `kill %1` 清掉，然后直接查 `indexerstatus`。
- 退避窗口还差 31 秒就发请求，照样 429。→ 看 `disabledTill` 的绝对时间，别估。
- 终端（MINGW64 / sh）会**折断过长或多行的命令**，症状五花八门：
  `curl: no URL specified!`、`option -F requires parameter`、
  `paused=true: command not found`。→ 一律用 shell 变量（`P=` `Q=` `SP=` `D=` `S=`）
  把长串拆短，命令写成**单行**。
- 重新登录后 cwd 会回到 `/volume2/docker_ssd`，导致 `docker compose ...`
  报 `no configuration file provided`。→ 先 `cd` 回栈目录，或直接用
  `docker logs <container>`。
- **通过 SMB 读 NAS 上的大日志文件会偶发返回「截断内容」** —— 不是空文件，是短了一截，
  所以"判空后重试"不够。要**按字节长度校验**再重试：
  ```python
  size = os.path.getsize(p); data = open(p, "rb").read()
  if len(data) == size: ...   # 否则 sleep 1.5s 重来
  ```
  2026-09-11 就被这个坑过：统计"匹配到几部"时连续三次拿到 0，实际日志里明明有 57 条 `injected`。
- **从日志路径里切包内目录名时，分隔符是 `.FRDS/` 不是 `/FRDS/`** ——
  包名结尾是 `...Mixed.Collection.20240501.FRDS`，前面是个**点**。写成 `/FRDS/` 会切不开，
  所有行都被归成同一个值（症状：去重计数恒为 1，或路径原样输出）。

### 6.3 `run-batch.sh` 首次跑出「全 400」—— MINGW 的 MSYS 参数路径转换

**症状**：`scripts/batch-report.tsv` 里连续多行 `MISS / http=400`，看着像"命中率极低"，
实际是**请求压根没被 cross-seed 受理**，匹配逻辑一次都没执行。
（顺带坑：那批数据里混进过一个 `HIT`，是诊断时手工打的 webhook 造成的误报。）

**根因**：Git Bash(MINGW) 把参数交给**原生 `curl.exe`** 时会做「路径转换」。
脚本原来写的是 `--data-urlencode "path=$p"`，而 `path=/volume1/…` 这种 KEY=VALUE
里的值只要长得像 POSIX 路径就会被改写，中文还会按 ANSI 代码页(GBK)重编码：

```
cross-seed/logs/error.2026-09-11.log:
  path: 'C:/Program Files/Git/volume1/video/download/movies/…FRDS/2001̫������…MNHD-FRDS'
```

`stat()` 找不到这个路径 → `A valid infoHash or an accessible path must be provided` → HTTP 400。

**修法（已改）**：让路径走 **stdin**，不出现在命令行上，转换就无从发生：

```bash
printf '%s' "$p" | curl -s -o /dev/null -w '%{http_code}' --max-time 30 -X POST \
  -H "X-Api-Key: $CSKEY" --data-urlencode "path@-" "$CS_URL/api/webhook"
```

**三个候选方案的实测**（用 `__probe_*__` 假路径打 webhook，再看日志里收到的字符串）：

| 方案 | cross-seed 收到的路径 | curl 退出码 |
|---|---|---|
| `MSYS2_ARG_CONV_EXCL='--data-urlencode'` | 仍被改写 ❌ | 0 |
| **路径走 stdin（采用）** | `/volume1/video/__probe_y__` ✅ | 0 |
| `export MSYS_NO_PATHCONV=1` | 干净 ✅ | **23** ❌ |

- `MSYS2_ARG_CONV_EXCL` 只匹配参数本身，**保护不到它后面那个值**，没用。
- `MSYS_NO_PATHCONV=1` 路径是干净的，但会让**同一条 curl 里的 `-o /dev/null` 失效**
  （`/dev/null` 不再被换成 `NUL`，curl 报 23 write error）。**所以别用它。**

**顺带加固**：脚本现在把 `400/000` 单独记成 `ERR`（不再混进 `MISS` 压低命中率），
汇总的命中率分母也剔除了 `ERR`，出现 400 时当场打印告警。

**验证**：`COUNT=1 bash scripts/run-batch.sh` → `HTTP 204`、16s 出第一个种、新增 2 个单种、
`indexerstatus` 仍为 `[]`（`delay:30` 没触发限流）。

> 通用教训：**这个项目里凡是把 NAS 内路径当参数交给原生 exe（curl 等）的地方，
> 都不能直接写在命令行上**——走 stdin / 临时文件，或先确认那个 exe 是 MSYS 程序。
> （注意区分：`find` / `sed` / `grep` 是 MSYS 程序，不受影响；`curl.exe` 是原生的，受影响。）

### 6.4 并发任务会污染抽样测量 —— 以及「对根目录打 webhook」会触发整包全量搜索

**事故经过**：诊断 §6.3 时为了确认"路径能通"，顺手对**大包根目录**打了一次 webhook：

```bash
curl -XPOST .../api/webhook --data-urlencode 'path=/volume1/video/download/movies/DouBan_IMDB...FRDS'
```

cross-seed 把这个 dataDir 整个展开了，日志里开始出现：

```
[webhook] (1/384)   Searching for .../xxx
[webhook] (80/384)  Searching for .../xxx
```

**它逐目录搜完 384 个目录**，一路匹配一路注入（每目录两次搜索：目录级 + 文件级）。
实测约 **2 目录/分钟**，整包约 **3 小时**。这就是 qB 里种子数一路涨的原因。

**两个后果：**

1. **好事**：这其实是"全量保种"最省事的做法 —— **一次 webhook 就够，不必逐部驱动**。
   Phase 3 编排器的 `run` 因此可以退化成"可选"，主要价值变成 `preflight` 和 `status`。
   （前提：路径要正好是 dataDir 的**根**；打在子目录上只搜那一个子目录。）
2. **坏事**：它和抽样脚本**同时**跑时，抽样的 `new_torrents` 会把后台任务的产物
   算到当前这部头上 → **假 HIT**。§5.2 那轮"10/10"就是这么来的。

**防呆（已加进脚本）**：开跑前静置 60s，比较 qB 分类里的哈希集合有没有变；
一变就说明有后台任务在注入，直接拒绝开跑并给出提示。
（`SKIP_QUIET_CHECK=1` 可强行跳过，不建议。）

**教训**：**"qB 分类里新增了几个种子"这个判据，只在"没有别的任务在写同一个分类"时才成立。**
诊断用的探针请打在**一个具体的片子目录**上，不要打根目录。

### 6.5 全量扫描被「429」打断 —— 但根因是站点 502，不是我们搜太快

**症状**：§5.3 那次全量扫描跑到 `(89/384)` 时，cross-seed 报

```
12:24:28.219 warn: [webhook] Failed to reach SiteA: request failed with code 429
                  due to rate limiting, snoozing until 2026-09-11 12:25:28
```

看着像「`delay:30` 还是太快、被 sitea 限流了」。**但这是误判。**

**真正的根因**（Prowlarr 日志）：

```
12:24:21.3 Warn|Cardigann|Request for SiteA failed with status BadGateway. Retrying…
12:24:28.0 Warn|IndexerHttpClient|HTTP/2.0 [GET] https://site-a.example/login.php: 502.BadGateway
```

→ **`site-a.example` 自己的 `login.php` 返回了 502**，站点后端当时挂了。
Prowlarr 按自己的规则把 SiteA 标记为「不可用」，再**回给 cross-seed 一个 429** ——
**这个 429 是 Prowlarr 生成的，不是 sitea 发的。**

**教训**：

- **不要只看 cross-seed 的 429 就调 `delay`。** 一定要去 Prowlarr 日志看该站真实的 HTTP 码：
  `500/502/520/522/timeout` = 站点侧；真限流才是 `429 + Retry-After` 且能对上站的限额。
- `delay:30` 到目前为止**从未被证明有问题**（本次 87 条里 `indexerstatus` 一直是 `[]`）。
- 站点抖动是**不可控**的，所以全量任务必须**可续跑**：被打断后重打一次根目录 webhook 即可，
  但要注意 cross-seed 的搜索缓存 / `excludeRecentSearch` 可能让刚搜过的条目被跳过（见 §10 末尾）。

### 6.6 Prowlarr 的 indexerId 会变 —— `TORZNAB_URLS` 里写死数字很脆

`TORZNAB_URLS` 里用的是 `http://prowlarr:9696/<indexerId>/api`。
**这个数字不是稳定标识**：在 Prowlarr 里删掉再重新添加同一个站，ID 很可能变成另一个数。

本次就撞上了：早期 `.env` 里是 `/1/api`，日志显示它当时指向 **SiteA**；
现在查 `GET /api/v1/indexer`，**id 1 = SiteB、id 2 = SiteA**，ID 已经错位过。

**每次增删索引器后，必须重新核对 ID**（用 Prowlarr 的 API，别靠网页 URL 猜）：

```bash
# <K> = prowlarr/config.xml 里的 <ApiKey>
curl -s -H "X-Api-Key: <K>" http://<NAS_IP>:9696/api/v1/indexer \
  | python -c "import sys,json;[print(i['id'], i['name'], i['enable']) for i in json.load(sys.stdin)]"
```

核对完再改 `.env` 的 `TORZNAB_URLS`，然后 `docker compose restart cross-seed`。

> 顺带一个查「某个 indexerId 到底是哪个站」的笨办法（不依赖名字）：
> `GET /api/v1/search?query=matrix&type=search&indexerIds=<id>`，
> 返回结果里每个 item 都带 `"indexer": "<站点名>"`。

---

## 7. 其它已知的非阻塞问题

- FlareSolverr 镜像从 GHCR 拉不动。可选组件，`cross-seed` 不 `depends_on` 它，不影响主链路。
- cross-seed 的 `qbittorrentUrl` 弃用警告 → 管线稳定后迁移到 `torrentClients`。
- Prowlarr 日志刷 `Missing translation/culture resource: .../Localization/Core/zh.json` → 纯外观问题。
- `.gitignore` 结尾有一行多余的缩进重复项 `  .deploy-backup/`，待清理。
- 本地 git 仓库**还没有任何 commit**，文件只是 staged 状态。
- 手工 `mkdir` 出来的 `12th.Fail...` 链接目录是 `drwx------`（跟着默认 umask 走），
  cross-seed 自己建的是 `drwxr-xr-x`。不影响做种，`chmod 755` 统一一下即可。

---

## 8. 安全约定（务必遵守）

- **PT 站凭据（cookie / passkey / API key / User-Agent）只在 Prowlarr 网页 UI 里填**，
  绝不出现在聊天、命令行、或版本库中。
- `.env`、`cross-seed/`（含 db）、`prowlarr/` 一律不提交、不外传——它们含 cookie/passkey/apikey。
  `.gitignore` 已覆盖。
- 需要回显 `TORZNAB_URLS` 做核对时，先脱敏：
  ```bash
  grep '^TORZNAB_URLS=' .env | sed -E 's/(apikey=)[^,&]+/\1<redacted>/g'
  ```
- **不要执行 `docker system prune -a`**，会删掉其它项目的镜像。
- 代理账号密码不要写进命令行。

### 待处理的凭据问题

| 项 | 状态 |
|---|---|
| NAS 账号密码在终端回显中泄露过 | ⬜ **待改**（DSM 控制面板 → 用户账号） |
| Prowlarr API key 在聊天中出现过 | ⬜ 建议管线跑通后轮换（它能完全控制 Prowlarr，而 Prowlarr 存着所有 PT 站 cookie）；轮换后要同步改 `.env` 的 `TORZNAB_URLS` |
| `CROSSSEED_API_KEY` 是模板预填的固定值 | ⬜ 建议 `openssl rand -hex 32` 重新生成 |
| qbittorrent-reseed 的 LSIO 临时密码在日志里回显过 | ⬜ 已走白名单免密，但建议在 WebUI 里设一个固定密码 |

---

## 9. 环境备忘

- 用户终端是 MINGW64（Git Bash），**括号粘贴模式（`^[[200~`）会破坏多行粘贴**。
  给 NAS 的命令一律写成**单行**，一次一条。超过一屏的逻辑写成脚本文件走 SMB 拷过去，
  不要靠粘贴。
- DSM 7 **没有 `nc`**，测端口用 `netstat`。也**没有 `jq`**，解析 JSON 用
  `grep -o` + `cut`。
- 三个 Web 端口都已发布到宿主机（9696 / 2468 / 3060），
  所以**很多诊断可以直接在 Windows 的 Git Bash 里跑**，不必 SSH 上 NAS。
- 上文所有 `<KEY>` 占位符，实际使用时替换为 `.env` 里的 Prowlarr API key。

### 磁盘布局（2026-09-11 实测）

| 卷 | 挂载 | 容量 | 剩余 | 放什么 |
|---|---|---|---|---|
| `/volume1` | `\\YOUR-NAS\video` | 56 TB | **~20 GB（100% 满）** | 大包源数据 + `LINK_DIR`（reseed_singles） |
| `/volume2/docker_ssd` | `\\YOUR-NAS\docker_ssd` | 448 GB | ~329 GB | compose/配置、qB 的 `/downloads` |

- qB 的 `save_path` 是 `/downloads`（在 SSD 上），但 reseed 种子的**实际数据在机械盘**
  （每个种的 `save_path` 都是 `/volume1/video/download/reseed_singles/SiteA`）。
- **`/volume1` 只剩 20 GB 完全不影响拆包挂种** —— 硬链接不占空间，这正是本项目能在快满的卷上跑起来的原因。
  （反过来说：如果哪天发现机械盘被大量占用，那一定是有人在**拷贝**而不是链接。）
- ⚠ 但**新增别的大包**需要真实空间，`/volume1` 这个水位得先处理（清空间或另开卷）。
- **`LINK_DIR` 不能挪到 SSD**：硬链接不能跨卷，挪过去会直接失败。

---

## 10. v2 多包支持（2026-09-11 部分落地）

需求：除了 `DouBan_IMDB.TOP250...FRDS`，**还有其它大包**也要拆包挂种。

### 10.1 已接入的包

| 包名（job） | 源目录 | 单片单位 | 结构 |
|---|---|---|---|
| `frds-top250-2024` | `/volume1/video/download/movies/DouBan_IMDB.TOP250…FRDS` | 一部电影 | ✅ 根目录子目录即发布名 |
| `my-brilliant-friend-s01-s04` | `/volume1/video/download/TV/My.Brilliant.Friend.S01-S04…ADWeb` | **一季**（S01~S04） | ✅ 根目录子目录即发布名 |
| `dc`（见 §10.2） | `/volume1/video/download/movies/DC相关剧集全系列大合集` | 一部电影 / 一季 | ⚠ **根下多一层中文标签，需特殊处理** |

### 10.2 ★ 嵌套结构的陷阱（DC 案例，2026-09-11）

**背景**：`DC相关剧集全系列大合集` 是**自己整理的合集**（不是单一 torrent），根目录下先分两类，
再往下才是单片。实测有**四种形状**：

```
DC相关剧集全系列大合集/                 ← 包根（0）
├── DC系列电影/                        ← 分类层（1）
│   ├── 01.蝙蝠侠1：侠影之谜 (2005)/      ← ★中文标签层（2）
│   │   └── Batman Begins 2005 …-CHD/  ← 发布名（3）→ 里面 1 个 .mkv
│   └── 04.超人：钢铁之躯(2013.6.14)/    ← ★标签层（2）
│       └── Superman…mkv               ← 裸文件，无发布名目录！
└── DC系列剧集/                        ← 分类层（1）
    ├── 01.绿箭侠（2012.10-2019.10）/    ← ★标签层（2）
    │   └── Arrow.S01-S08…-FRDS/       ← 整季包（3）
    │       └── Arrow.S01.Bluray…-FRDS/ ← 每季发布名（4）
    └── 04.闪电侠（2014.10-2023.2）/     ← ★标签层（2）
        └── 闪电侠 第一季.The.Flash.S01…-NTb/ ← 每季发布名（3）
```

**为什么不能直接把包根塞进 `DATA_DIRS`**：cross-seed 用**目录名**去站点搜索。
若 dataDir = 包根，那层中文标签（`01.蝙蝠侠1：侠影之谜 (2005)`）会被当成 searchee 名 →
**搜不到任何东西，却照样消耗查询额度**（正是 §5.3 里"白烧"的翻版）。

实测两种接法（用已入库的 `cross-seed.db` 反推规则后测算）：

| 接法 | 干净发布名 | 垃圾名 | 结论 |
|---|---|---|---|
| 包根作 dataDir + `maxDataDepth: 3` | 88 | **47**（全是中文标签） | 需配 `blockList: ["nameRegex:^\\d{2}\\."]` 兜底，属启发式 |
| **47 个标签目录分别作 dataDir** | **86~113** | **0** | ✅ **采用** |

**采用的接法**：把 `DATA_DIRS` 指到**标签层本身**（即每个 `DC系列电影/01.…` 目录），
这样每个 dataDir 的**直接子目录才是发布名** —— 与 FRDS 的成功模式（§10.1）同构。
`maxDataDepth` **保持默认 2**，不动全局，因此**不影响 FRDS 现有扫描行为**。

```bash
# 生成这 47 条路径（以后往 DC 里加片，重跑这条即可，幂等）
python scripts/gen-datadirs.py "//YOUR-NAS/video/download/movies/DC相关剧集全系列大合集" \
    --level 2 --nas-prefix /volume1/video --list          # 先核对
python scripts/gen-datadirs.py "//YOUR-NAS/video/download/movies/DC相关剧集全系列大合集" \
    --level 2 --nas-prefix /volume1/video --append-to .env # 追加（不覆盖已有）
```

**cross-seed 的 searchee 生成规则**（用 `cross-seed.db` 反推 + 官方文档校验）：

- **dataDir 的直接子目录**：一律是 searchee（这正是我们要的）；
- **更深层**：只有**直接含视频文件**的目录才是 searchee，容器目录会被**穿透**（不下钻的是"含视频"的那种）；
- 深度上限由 **`maxDataDepth`** 控制，**默认 2**；调大会产生更多 searchee 和更多 indexer 请求（官方明确警告）；
- 过滤器（`blockList` 的 `nameRegex:` / `folderRegex:`）在**每次搜索前**生效，可用来兜底拦名。

> ⚠ **不要**为了让 DC 少写 47 条而把 `maxDataDepth` 调到 3~4：那是**全局**的，
> FRDS 会跟着多出一批 searchee，且 DC 的中文标签照样进池子。

### 10.3 其它设计要点

1. **`hlink/config.yml` 的 `jobs[]`** 是数组 → 复制一段、改 `name` / `source_dir`。
   注意 job 的 `source_dir` 语义是"**其子目录 = 各单片**"，所以 DC 这种嵌套包
   不能只写一行 job（见 §10.4）。
2. **`LINK_DIR` 必须与源大包同卷**。新大包若落在**另一个物理卷**，就要为新卷再配一个 linkDir ——
   cross-seed v6 的 `linkDirs` 是数组，它会按 searchee 所在 device 挑同卷的那个。
   ⚠ 不要图省事把 linkDir 指到 SSD：跨卷硬链接直接失败。
3. **分类**：`QBIT_CATEGORY` 目前是单一分类 `reseed-singles`。多包时靠
   `LINK_DIR/<包名>/<Tracker>/...` 的目录结构区分，或给每个包单独起一个 qB 分类。
4. **磁盘**：新大包要占真实空间（§9）；硬链接侧依旧零开销。
5. **站点压力**：包越多、搜索次数越多 → **按包分时段跑**，别同时开多个全量任务；`delay` 保持 30~45。
   接入 DC 后 searchee 总数从 ~405 涨到 **~1000+**（49 个 dataDir × 各自子目录），
   一轮全量搜索的耗时和 API 次数都会成倍增长 —— **务必用 `--limit` 分批**（见 §11.7.1）。

### 10.4 已知缺口：状态机还不支持嵌套包

`scripts/reseed-state.py init` 目前是**单根、只扫一层**（`_list_dirs`），
而 DC 的"单片"分散在 47 个根里。所以：

- `sync --pack dc` 会把 DC 的 searchee 名**对不上任何目录**，报 `unresolved` 并跳过；
- 也就是说 **cross-seed 会正常搜 DC，但状态机暂时看不到 DC**。

两种修法（都还没做）：

- **A. 多根 + 深度**：`init` 支持重复 `--root`/`--local-root` + `--depth N`，
  枚举时套用 §10.2 那条 cross-seed 规则（含视频即叶子）。改动约 60 行，FRDS 流程不受影响。
- **B. 硬链接农场**：建 `/volume1/video/download/reseed_farm/`，
  里面按发布名建硬链接目录指向真实数据。这样 `dataDirs` 只 1 条、
  `maxDataDepth: 1`、状态机也只要 1 个根 —— 三者全部归一。零磁盘开销，但要动 NAS 上的目录。

> 附带的待定策略：**未匹配的片子怎么处置**。
> 现状是写进 `scripts/unmatched.tsv` 就不再管。建议用 cross-seed 的
> `searchCadence`（多久重扫一遍 dataDirs）+ `excludeRecentSearch`（多久内不重复搜同一部）
> 做**低频自动重扫**，靠"等站点有人上传"自然补上；
> 而不是手动反复重打 webhook —— cross-seed 有搜索缓存，短期重复打基本是白打，还可能撞上 Prowlarr 退避。

---

## 11. 单片状态机（2026-09-11 新增，已实现）

**起因**：§5.3 暴露了一个致命问题 —— **cross-seed 对被退避跳过的条目"什么都不记"**，
295 条就这么消失在 `(384/384)` 里。需要一套"每部片子现在到哪一步了"的记录，
做到**已完成的阶段不重复、被跳过的阶段必须补上**。

### 11.1 结论先行：**不用给 cross-seed 加字段，它已经有了**

翻 `cross-seed.db` 发现它自带三个我们想要的东西（v6.13.7 实测）：

| 表 | 作用 |
|---|---|
| `timestamp(searchee_id, indexer_id, last_searched)` | 「这部片在某个站**真的搜过**吗」——天然的"已完成"标记 |
| `decision(searchee_id, guid, decision, info_hash, …)` | 匹配结论：`MATCH` / `MATCH_PARTIAL` / `MATCH_SIZE_ONLY` |
| `indexer(id, url, name, active, status, retry_after)` | 索引器退避状态 + **解禁的绝对时间** |
| `searchee(id, name, first_searched, last_searched)` | ⚠ 这两列**全 NULL**（已被 `timestamp` 取代，别再用） |

实测：`searchee` 405 行，**只有 118 行有 `timestamp`**（= 真搜过），
另外 **287 行既无 `timestamp` 也无 `decision`** —— 那 295 条被 429 秒跳的，
在 cross-seed 眼里就是"从来没搜过"。而这 118 里 58 个有 match，
**58/118 = 49.2%**，独立复现了 §5.3 的 ~50% 结论。

**为什么不直接 `ALTER TABLE`**：那是 cross-seed 自己的库，schema 由它的 knex migration 管，
手工加列会在它升级/启动时被覆盖，甚至让它启动失败。

### 11.2 所以补的是"它记不了的那一格"

新增 sidecar 库（`orchestrator/state.py` + `scripts/reseed-state.py`）：

```
hlink/state.db            ← 唯一被我们写的库
  pack    一个大包一行（NAS 根路径 / local_root / link_dir / category）
  movie   一部片一行（stage / attempts / next_retry_at / searched_indexers /
                      skipped_indexers / matched_hashes / seeding_count）
  attempt append-only 流水（每次状态变化的证据）
```

**关键设计：`stage` 不是手工维护的字段，而是由事实推导的纯函数** ——

```python
def compute_stage(seeding_count, matched_count, searched_indexers, skipped_indexers):
    if seeding_count > 0:  return "SEEDING"      # qB 里真有这个 info_hash
    if matched_count > 0:  return "MATCHED"      # decision 里有 match，等 qB 确认
    if searched_indexers:  return "UNMATCHED"    # timestamp 证明搜过了
    if skipped_indexers:   return "SKIPPED"      # ★只有我们记这个
    return "PENDING"
```

因为它是**算出来的**，所以不存在"状态和现实不一致"，也不需要"手动同步一下状态"。

### 11.3 阶段与动作

```
PENDING ──搜索──▶ UNMATCHED ──(新增索引器 / 过冷却期)──▶ 重搜
   │                  │
   │                  └──匹配──▶ MATCHED ──qB 校验通过──▶ SEEDING（终点，永不重搜）
   │
   └──被退避──▶ SKIPPED ──(立刻可重搜，不消耗重试预算)──▶ 重搜
```

| 阶段 | 含义 | 会不会重搜 |
|---|---|---|
| `SEEDING` | qB 里真有这个 info_hash | ❌ 永不 |
| `MATCHED` | 匹配到、已注入，等 qB 确认 | ❌ 不 |
| `UNMATCHED` | 真搜过、没匹配到 | ⏳ 仅当 **出现没搜过的索引器** 或 **过了冷却期**（默认 7 天） |
| `SKIPPED` | ★被退避秒跳 | ✅ **立刻** |
| `PENDING` | 还没搜过 | ✅ 立刻 |
| `ERROR` | 异常 | ✅ 立刻 |

> 「已完成的阶段就不重复」这条规则的落地，就是 `todo()` 里那句
> `missing = 当前索引器集合 - 该片已搜过的索引器集合`。
> **加一个站，所有 `UNMATCHED` 自动变成待搜** —— 不需要人工挑。

### 11.4 三个数据来源的分工

| 来源 | 提供什么 |
|---|---|
| `cross-seed.db`（只读） | "搜过没有"（`timestamp`）+"匹配到什么"（`decision` 带 info_hash） |
| cross-seed 日志 | ★"被退避跳过"（**cross-seed 不记这个**）+ 具体是哪个索引器 |
| qB `:3060` | "有没有真的在做种"（按 info_hash 与 `decision` 求交） |

**读法（已优化）**：早期担心"NAS/SMB 上读正被写的 WAL 库会锁失败"，所以走
"复制 `.db / -wal / -shm` 三件套到临时目录再读"。**实测这条路是多余的** ——

```python
sqlite3.connect(str(unc_path), timeout=5)   # 直接开 UNC，0.17s
conn.execute("PRAGMA query_only=1")         # 只读，不写、不加锁
```

直接开 UNC 上的活库**能读到 WAL 里的未 checkpoint 数据**（实测 `timestamp`=118 行、
`searchee`=405 行、`decision`=66 行，与三件套拷贝法结果一致），耗时 0.17s。
所以 `_open_csdb()` 现在是：**先试直读快路径，失败才回退到三件套拷贝**。
`.tmp-db/` 只作为兜底，已 gitignore。

> 关键点：`PRAGMA query_only=1` + `timeout=5`。不加 `query_only` 时 sqlite 可能尝试
> 建 WAL/写锁，在 SMB 上就会 `database is locked`；加了之后纯读，互不干扰。

### 11.5 实测结果（2026-09-11，382 部）

```
$ python scripts/reseed-state.py sync --pack frds-top250-2024 ...
  cross-seed.db 认为搜过 : 95
  日志里出现 Searching   : 96
  日志里被退避跳过       : 283  ← 这些是「假完成」，必须重试
  匹配到单种             : 48
  已在 qB 里             : 48
  当前索引器             : SiteA
  阶段分布: PENDING=4  SKIPPED=282  UNMATCHED=48  MATCHED=0  SEEDING=48  ERROR=0
```

`report` 输出（加 `-v` 看逐部清单）：

```
=== 包 frds-top250-2024 ===
    源目录: /volume1/video/download/movies/DouBan_IMDB.TOP250.Movies.Mixed.Collection.20240501.FRDS
    登记 382 部

    阶段          数量   含义
    PENDING           4   还没搜过
    SKIPPED         282   ★被退避跳过 —— 必须重搜
    UNMATCHED        48   真搜过，但没匹配到
    MATCHED           0   匹配到单种，等 qB 确认
    SEEDING          48   已在 qB 里（终点）
    ERROR             0   异常

    → 待搜索: 286 部
       周期: 每站 7 天

  按站重搜周期：
    SiteA           搜过   95 部 · 到周期    0 部 · 下次最早可重搜 09-18 10:46
```

- **48 个 `SEEDING`** 与 `unmatched.tsv` 的 HIT 数完全对上。
- **286 = `SKIPPED` 282 + `PENDING` 4**，与 cross-seed.db 里"既无 timestamp 也无 decision"的那批独立吻合。
- `SiteA 搜过 95 部`：95 是 **cross-seed.db `timestamp` 的行数**（真搜过），
  与"日志里出现 Searching 96 次"差 1 —— 差的那 1 部落在日志轮转边界上，不影响结论。
- `到周期 0 部`：95 部全是今天（09-11）搜的，7 天周期未到 → 0 部到周期。
  09-18 之后这 95 部会自动重新进入待办。

### 11.6 按站重搜周期（2026-09-11 新增）

**需求**："没搜到的种子重复搜的频率是多少？我要能调到**每个站一周搜一次**。"

**结论：现在就是每站每周一次（默认 7 天），且可按站分别设。**

数据源不是我们自己的 `attempt` 表，而是 **cross-seed 自己的 `timestamp` 表**：

```sql
timestamp(searchee_id, indexer_id, first_searched, last_searched)
```

这张表是 **(片 × 站)** 粒度的，`last_searched` 是 **epoch 毫秒**。
它天然回答"这部片在**这个站**上次是什么时候搜的" —— 正是"按站算周期"需要的粒度。
sidecar 的 `movie.indexer_seen` 把它**快照**成
`{片名: {站名: "YYYY-MM-DD HH:MM:SS"}}`，用于在 Windows 上离线算周期。

**判定规则**（`orchestrator/state.py`）：

```python
def due_indexers(indexer_seen, indexers_now, *, cadence_days=7,
                 cadence_by_indexer=None, now=None) -> list[str]:
    # 1) 从没搜过这个站              → due（立刻搜）
    # 2) now - last_searched >= 周期 → due
    # 3) 否则                        → 不 due，等
```

- `cadence_for(indexer, cadence_days=7, cadence_by_indexer=None)`：站级覆盖，站名命中就用站级值。
- `next_due_at(...)`：算出"最早什么时候可以再搜"，写进 `movie.next_retry_at`。

**CLI**：

```bash
# 全站统一 7 天
python scripts/reseed-state.py todo --pack $PACK --indexers SiteA,SiteB --cadence-days 7

# 按站覆盖：SiteA 7 天、SiteB 30 天
python scripts/reseed-state.py report --pack $PACK --cadence "SiteA=7,SiteB=30"

# 忽略周期，强制全量重扫
python scripts/reseed-state.py todo --pack $PACK --include-cooldown
```

**隔离验证**（固定 `now`，不依赖 NAS）：

```
刚搜过 1 小时, 周期 7 天 -> []                    # 不到周期，不搜
刚搜过, 再加 SiteB     -> ['SiteB']             # ★新站自动解锁
7 天后                  -> ['SiteA']             # 过周期
从没搜过                -> ['SiteA']             # 首搜
下次最早可重搜          -> 2026-09-18 12:23:56
按站覆盖 SiteB=30 天   -> ['SiteB']             # 站级周期生效
```

> **和 cross-seed 自带旋钮的关系**：cross-seed 自己的 `searchCadence` / `excludeRecentSearch`
> 也能让**守护进程自己**定期重扫，但粒度是"全局 N 天"。我们这套的增量是
> **(片 × 站) 粒度 + 按站不同周期 + 能导出"到底哪几部该搜"的清单**。
> 两者不冲突：守护进程的旋钮当兜底，`drive` 做定向补搜。

### 11.7 用法（Windows Git Bash 即可，不必上 NAS）

```bash
PACK=frds-top250-2024
NAS=/volume1/video/download/movies/DouBan_IMDB.TOP250.Movies.Mixed.Collection.20240501.FRDS
UNC=//YOUR-NAS/video/download/movies/DouBan_IMDB.TOP250.Movies.Mixed.Collection.20240501.FRDS
N=//YOUR-NAS/docker_ssd/prowlarr_cross-seed_autohardlink

# 1) 登记（可反复跑，不会重置已有状态）
python scripts/reseed-state.py init --pack $PACK --root "$NAS" --local-root "$UNC" \
  --link-dir /volume1/video/download/reseed_singles --exclude "0观影清单*"

# 2) 同步事实 → 推导阶段
python scripts/reseed-state.py sync --pack $PACK \
  --db-path "$N/cross-seed/cross-seed.db" \
  --log "$N/cross-seed/logs/info.current.log" \
  --log "$N/cross-seed/logs/verbose.current.log" \
  --qbit-url http://NAS_IP:3060 \
  --indexer-alias "http://prowlarr:9696/1/api=SiteB"

# 3) 汇报 / 看待办 / 看单片
python scripts/reseed-state.py report --pack $PACK
python scripts/reseed-state.py todo  --pack $PACK --indexers SiteA,SiteB --out scripts/todo.txt
python scripts/reseed-state.py show  --pack $PACK --movie "十二怒汉.12.Angry.Men.1957.BluRay.1080p.x265.10bit.MNHD-FRDS"

# 4) 驱动重搜（默认 dry-run，加 --apply 才真发）
python scripts/reseed-state.py drive --pack $PACK --indexers SiteA,SiteB --limit 50 --apply \
  --url http://NAS_IP:2468 --api-key <CROSSSEED_API_KEY>
```

#### 11.7.1 分批：`--limit` / `--batch` / `--plan`（2026-09-11 新增）

接入 DC 大包后 searchee 从 ~405 涨到 **1000+**，一轮全量会烧掉大量查询额度，
所以 `todo` 与 `drive` 都支持分批。

```bash
# 先看计划（不发请求、不导出清单；计划文字走 stderr）
python scripts/reseed-state.py drive --pack $PACK --limit 50 --plan

# 第 1 批（不加 --batch 就是第 1 批）
python scripts/reseed-state.py drive --pack $PACK --limit 50 --apply \
  --url http://NAS_IP:2468 --api-key <KEY>

# 一批做完，重跑同一条命令 → 自动推进到下一批
python scripts/reseed-state.py drive --pack $PACK --limit 50 --apply \
  --url http://NAS_IP:2468 --api-key <KEY>

# 想显式指定批次（比如中断后跳着跑）
python scripts/reseed-state.py drive --pack $PACK --limit 50 --batch 3 --plan
```

**为什么不需要记"我跑到第几批了"**：

1. `todo()` 已经**排除 `DONE_STAGES`（`SEEDING`/`MATCHED`）** —— 搜中并做种的片不会再出现在清单里；
2. `todo()` 内部按 `TODO_PRIORITY` 排序：

   | 阶段 | 优先级 | 含义 |
   |---|---|---|
   | `SKIPPED` | 0 | 上次被退避秒跳，**根本没发出去**，重搜不消耗重试预算 |
   | `ERROR` | 1 | 上次异常，尽快补 |
   | `PENDING` | 2 | 从没搜过 |
   | `UNMATCHED` | 3 | 真搜过没命中，等周期 / 等新站 |

3. 因此"取前 N 条"永远先吃掉**最该搜**的；一批做完状态就变了（被搜过的离开待办），
   下一批自然从剩下的头部开始 —— **重跑同一条命令就是推进**。

实测（`frds-top250-2024`，待搜 286 = `SKIPPED` 282 + `PENDING` 4）：

```text
$ drive --limit 50 --plan
共 286 部待搜 → 每批 50，共 6 批；本批 = 第 1 批（第 1~50 部）
本批 50 部  SKIPPED=50
节流：每条间隔 30s → 本批约 24 分钟；全部 286 部约 142 分钟

$ drive --limit 50 --batch 6 --plan
共 286 部待搜 → 每批 50，共 6 批；本批 = 第 6 批（第 251~286 部）
本批 36 部  PENDING=4  SKIPPED=32      # ← PENDING 排在最后，符合优先级

$ drive --limit 50 --batch 99 --plan
[!!] --batch 99 超出范围：共 6 批（每批 50）   # 退出码 2
```

**`todo` 的输出约定**：路径清单走 **stdout**，分批说明走 **stderr** —— 所以
`todo --limit 50 | xargs ...` 这种管道不会被提示文字污染。`--plan` 时 stdout 为空。

**两个易踩的点**：
- `--root` 必须是 **cross-seed 视角的 NAS 路径**（`/volume1/...`，webhook 要用它）；
  Windows 上列目录另外传 `--local-root`（UNC）。两者别搞混。
- 索引器标签要归一：同一个站在日志里可能是 `SiteA`、`http://prowlarr:9696/2/api`、
  或 info 级日志里的空值。`normalize_indexer()` 会统一，必要时用
  `--indexer-alias "http://prowlarr:9696/1/api=SiteB"` 补名字
  （cross-seed.db 里 SiteB 的 `name` 是 NULL，因为它当年连 caps 都没抓下来）。

### 11.8 `drive` 的控速与退避闭环（2026-09-11 新增）

**起因**：老版 `drive` 有两个洞 ——
1. **串行、不控速**：它只负责"把 todo 逐个打 webhook"，节流全靠 cross-seed 的 `delay`。
   无 `--limit` 的 `--apply` 会一口气把几百条灌进去。
2. **退避是黑盒**：发完就返回，要等下一轮 `sync` 才知道哪些又被 429 打断了。

**现在**：`drive` 由 `DriveSession`（`orchestrator/state.py`）驱动，两个洞都堵上了。

```python
DriveSession(url, api_key, crossseed_db=..., interval=30.0,
             check_every=10, max_wait=1800.0, pause_on_backoff=True)
    .backoffs()             # 读 cross-seed.db 的 indexer 表 → [IndexerBackoff]
    .wait_out_backoff()     # 睡到退避解除；超过 max_wait 就放弃
    .run(paths) -> DriveStats
```

`cmd_drive` 的完整流程：

```
枚举待办 → 打印 ETA → (dry-run 提前返回) → DriveSession.run()
   ├─ 每条之间 sleep --interval（默认 30s，对齐 cross-seed 的 delay）
   ├─ 每 --check-every 条（默认 10）读一次 indexer 表
   │     └─ 有 RATE_LIMITED 且 retry_after 未到 → 睡到解禁（--max-wait 默认 1800s 上限）
   └─ 打完后 wait_for_log_quiet(--settle 90) 等 cross-seed 忙完
→ 自动 _sync_now() 回灌 → 打印 newly_seeding / still_skipped / 按站周期表
```

`DriveStats` 汇报：

| 字段 | 含义 |
|---|---|
| `total / sent / ok / failed` | 计划 / 实发 / 成功 / 失败 |
| `waited_sec` | 累计为退避睡掉的秒数 |
| `backoff_hits` | 撞上退避的次数 |
| `aborted` | 是否因 `> --max-wait` 中止 |
| `resync` | 打完自动回灌的 `SyncReport` |
| `still_skipped` | ★回灌后**仍**是 `SKIPPED` 的（说明这轮又被退了） |
| `newly_seeding` | ★这轮新变成 `SEEDING` 的（= 真赚到的） |

**新增/关键参数**：

```
--interval 30          两条 webhook 之间隔几秒（默认 30）
--check-every 10       每发几条检查一次退避（默认 10）
--max-wait 1800        单次退避最多等几秒，超了就中止（默认 30 分钟）
--no-pause-on-backoff  不理会退避，闷头发（不建议）
--settle 90            回灌前等日志静默几秒（默认 90）
--drain-max-wait 3600  等 cross-seed 忙完的上限
--no-auto-sync         打完不回灌
--apply                真发请求（默认 dry-run）
```

**两个实现细节**（都踩过坑）：

- **`post_webhook()` 把路径放在请求体里**，不放 URL/命令行。
  Git Bash（MINGW MSYS）会把命令行里长得像 POSIX 路径的值改写成
  `C:/Program Files/Git/...`，并把中文按 GBK 重编码后传给**原生** `curl.exe`。
  用 `urllib.parse.urlencode` 走 body 就绕开了。
- **`wait_for_log_quiet()` 用 `stat().st_size` 轮询**，不用 `docker logs`。
  cross-seed 的 stdout 是空的 —— 它写的是**文件**（经 docker json-file 驱动落到
  `logs/info.current.log`）。"日志文件不再增长"就是"忙完了"的信号。

### 11.9 还没做的

- **没接进编排器**：`orchestrator/main.py` 目前只有 `preflight/run/status/prestage`，
  还没加 `state` 子命令。CLI 脚本本身已可用（见 §11.10）。
- **`indexerstatus` 走不通，只能读库**：cross-seed v6.13 的 HTTP API 只暴露
  `/api/ping` 和 `/api/status`（都返回 `OK`），`/api/indexerstatus`、`/api/indexers`、
  `/api/health`、`/api/stats`、`/api/version` **全是 404**。
  所以退避状态只能读 `cross-seed.db` 的 `indexer` 表（`status='RATE_LIMITED'` +
  `retry_after` epoch ms）。`DriveSession.backoffs()` 就是这么做的。

### 11.10 `orchestrator/main.py` 是什么

> 回答"orchestrator/main.py是什么脚本？"

它是 **`reseed-orchestrator` 这个容器/服务的命令行入口**（不是状态机的一部分）。
职责是"跑一轮完整的拆包保种作业"，子命令四个：

| 子命令 | 作用 |
|---|---|
| `preflight` | 只读预检：配置合法性、各任务是否同卷、单片枚举、qB 与 cross-seed 连通性 |
| `run` | 对启用的任务执行 匹配→注入→等待→汇报（`--job` 只跑一个，`--dry-run` 不触发） |
| `status` | 连 `:3060`，按分类列出当前单种的做种状态汇总 |
| `prestage` | 可选：把某任务的大包整体硬链接到 `linkDir` |

```bash
python -m orchestrator.main preflight
python -m orchestrator.main run --job frds-top250-2024
python -m orchestrator.main status
python -m orchestrator.main prestage --job frds-top250-2024 --dry-run
```

配置默认读容器内 `/config/config.yml`，可用 `--config` 或环境变量 `RESEED_CONFIG` 覆盖：

```python
DEFAULT_CONFIG = os.environ.get("RESEED_CONFIG", "/config/config.yml")
```

**和状态机的关系**：两者目前是**平行的**。
`main.py` 走的是"一次性批量作业"路线（配好 job，一把梭），
`reseed-state.py` 走的是"长期增量维护"路线（记状态、算周期、定向补搜）。
`main.py` **还没有** `state` 子命令，所以想用状态机得直接跑 `scripts/reseed-state.py`。
未来要么给 `main.py` 加 `state` 子命令，要么把状态机逻辑收进 `orchestrator/state.py`
后被 `main.py` import —— 现在 `state.py` 已经是个独立模块，import 是现成的。

# 大包拆包 · 单种保种工具链 v1 —— 方案与进度总结

> 最后更新：2026-09-12（§15 通知发信打通；§5.3 已修正：全量**没跑完**，只搜了 87/382，真实命中率 ~50%；
> §6.1 SiteB 已恢复；§6.5 429 真因是站点 502；§6.6 indexerId 会变；
> **§11 单片状态机已实现**，含 **§11.6 按站重搜周期（默认每站 14 天，2026-09-11 由 7 天改）** 与
> **§11.8 `drive` 控速 + 退避闭环**；§11.10 说明 `orchestrator/main.py`；
> **§10 多包支持已落地**，含 **§10.2 嵌套结构陷阱（DC 案例）**、
> **§10.6 cross-seed 的 searchee 枚举规则（读源码定论）**；
> **§11.7.1 `--limit` 分批**、**§10.5 A/B 方案对比**、**§11.11 全量能否排除已做种**、
> **§11.12 生产 `.env` 一键更新（含"怎么确认真的落地了"）**、
> **§10.6.4 `init --roots-from-env`（DC 47 组参数 → 一条命令）**、
> **§11.13 429 退避与 SKIPPED 的真相**、
> **§11.14 三个包 init 完成与 drive 分批策略**、
> **§12 收尾归档（现状快照 / 下一步手册 / 踩坑清单）—— 接手先读这里**、
> **§14 驱动层从 Windows 迁到 NAS（2026-09-11 深夜，含两个已查实的坑）**、
> **§15 通知发信打通 + DSM 的 ssmtp 配置路径坑（2026-09-12 凌晨）**、
> **§16 待做的四个自动化（设计预案，未实现 —— 两条前提与实测不符）**、
> **§17 首次真跑的探针发现（假 `exit=127` 已修 · **§17.5 两个疑点已结案**：农场路径 / 退避检查节奏 / 退避分级 / 闸门接线）**）
> 本文件是给「下一次接手的人（或下一个会话）」看的。读完这一篇应当能直接接着干，
> 不需要回翻聊天记录。

---

## 导航（先读这里 30 秒）

> **两份文档的分工**（按日志分级）：
> **README = INFO 层** —— 操作手册（命令、步骤、症状→解法）；
> **SUMMARY = DEBUG 层** —— 完整的**过程、踩坑、决策理由**（就是本文件）。
> 想知道「**怎么做**」看 README；想知道「**为什么这么做 / 当时踩了什么**」看这里。
> 同一事实**只在一处维护**，跨层用「详见 SUMMARY §N」单向指路。

**按目的查：**

| 我想… | 直接跳 |
|---|---|
| **接手这个项目**，先读什么 | §12 收尾归档 → **§13 接手会话**（最新，含 7 条新坑）→ **§13.11 当前进度与唯一待办** → **§14 驱动迁到 NAS** |
| 现在系统什么状态 | **§13.7 状态快照**（唯一权威，别处不再重复） |
| 调度为什么从 Windows 搬到 NAS | **§14**（`<StopOnIdleEnd>` + 包装器行尾两个坑 · 排查表） |
| 出事了怎么让它通知我 | **§13.12 通知系统**（架构 · 探针推翻了什么 · 三个真缺陷）→ README「通知 / 告警」 |
| **邮件发不出去 / ssmtp 报 501** | **§15**（DSM 的 ssmtp 读 `synosmtp.conf`，不是 `/etc/ssmtp/ssmtp.conf`） |
| **下一步自动化做哪件** | **§16**（额度感知 / 农场巡检 / 趋势 / 日志轮转 —— 含**两条前提被探针推翻**） |
| **状态机说没做种、qB 里明明在做种** | **§17.5.1**（根因 = v3 农场路径认不出，**已修**）· 误判过程见 §17.3 |
| **`backoff_hits` 一直是 0 / 退避没被检测到** | **§17.5.2**（检查间隔 300s > 退避窗口 55s，**已修**）· 分级 §17.5.3 · 接线 §17.5.4 |
| 遇到报错 / 症状 | **§13.6 本会话的坑** · §12.5 上次的坑 · §6 已了结的坑 |
| 加站 / 换站 | **§13.3 完整流程**（可复用，含"必须 force-recreate"） |
| 状态机怎么用 / 参数 | §11.7 用法 · §11.6 重搜周期 · §11.8 控速与退避 |
| 嵌套包（DC 那种）怎么接 | §10.2 陷阱 · §10.6 枚举规则（读源码定论） |
| 硬链接农场（v3） | §10.5 B/A 对比 · §10.5.7 实测 · §10.5.9 等价性证明 |
| 为什么不用 XX 方案 | §3 关键决策 · §10.5 A/B 对比 |
| **「包」是怎么被系统认出来的 / 搜索压力到底从哪来** | **§19 原理技术与风险须知**（包是**声明**的不是识别的 · 压力来自**分母每 14 天重生** · 风险清单） |

**章节总览（按"日志级别"分层）：**

| § | 标题 | 级别 |
|---|---|---|
| 0 | 占位符约定 | 🟢 操作 |
| 1–2 | 目标 / 拓扑 | ⚪ 背景 |
| 3 | 关键决策与踩过的坑 | 🔵 决策 |
| 4 | 各文件最终状态 | 🟢 操作 |
| 5 | 进度（含 §5.3 命中率真相） | ⚪ 历史 |
| 6 | 已了结的坑（保留记录，避免重走） | 🔴 症状→解法 |
| 7–9 | 非阻塞问题 / 安全约定 / 环境备忘 | 🟢 操作 |
| 10 | v2 多包支持（§10.2 嵌套陷阱 · §10.5 A/B · §10.6 枚举规则） | 🔵 决策 |
| 11 | 单片状态机（§11.6 周期 · §11.7 用法 · §11.8 控速） | 🟢 操作 + 🔵 决策 |
| 12 | 收尾归档（**接手先读**：快照 / 手册 / 踩坑） | 🔴 + 🟢 |
| 13 | **接手会话 —— 本会话全过程**（§13.6 坑单 · §13.7 快照 · §13.8 验证 · §13.11 最新进度 · §13.12 通知系统） | 🔴 + 🔵 |
| 14 | **驱动层迁到 NAS**（两个坑：`<StopOnIdleEnd>` · `.cmd` 行尾 · 排查表 · 剩余人工步骤） | 🔴 + 🟢 |
| 15 | **通知发信打通 + DSM ssmtp 配置路径坑**（501 真因 · BusyBox `ps` 假阴性 · 计划窗口存错） | 🔴 + 🟢 |
| 16 | **待做的四个自动化（设计预案，未实现）**（额度感知 · 农场巡检前置修复 · 趋势数据已在库 · 日志轮转**前提被推翻**） | 🔵 决策 |
| 17 | **首次真跑的探针发现 + 结案**（假 `exit=127` = 部署覆盖了在跑的脚本 · **§17.5 两个疑点已修：农场路径 / 退避检查节奏 / 退避分级 / 闸门接线**） | 🔴 + 🔵 |
| 18 | **2026-09-12 当天全过程**（搬迁 · 加站 · 巡检 · 漂移哨兵 · 推前扫描 · 观测对账三条判据进生产） | 🔴 + 🔵 |
| 19 | **原理技术与风险须知**（§19.1 包是**声明**的不是识别的 · §19.2 搜索压力来自**分母**不是频率 · §19.3 风险清单） | ⚪ 原理 + 🔴 风险 |

> 图例：🔴 症状→解法（卡住时搜这里）· 🟢 操作（照着敲）· 🔵 设计与决策（为什么）· ⚪ 历史快照。

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
| Phase 2.6 | **重跑一次完整全量**（先把 SiteB 加回去，见 §6.1） | ⬜ **待做** —— 清单已生成（`scripts/todo-paths.txt`，334 条），等一个合适的时机执行 |
| Phase 2.7 | **单片状态机**（sidecar `hlink/state.db`，见 §11） | ✅ **已实现并实测**：382 部 → SEEDING 48 / UNMATCHED 48 / SKIPPED 282 / PENDING 4 |
| Phase 2.8 | **按站重搜周期**（默认每站 14 天，可 `--cadence "SiteA=14,NanyangPT=30"`，见 §11.6） | ✅ **已实现并验证** |
| Phase 2.9 | **`drive` 控速 + 退避闭环**（`DriveSession`：`--interval` 节流、撞退避就等、打完自动 `sync` 回灌，见 §11.8） | ✅ **已实现**（默认 dry-run，`--apply` 才真发） |
| Phase 3 | 编排器 build / preflight / run --dry-run / run / status | ⬜ 未开始（`run` 已非必要，见 §6.4；`status` 仍值得做；`main.py` 说明见 §11.10） |
| v2-a | **多包接入**：MBF（剧集，每季）+ DC（嵌套，47 个 dataDir） | ✅ **配置已落地**，见 §10.1 / §10.2 |
| v2-b | 状态机支持嵌套包（多根 + 深度） | ✅ **已完成并实测**（DC 47 根 → 115 单片），见 §10.4 / §10.6 |
| v2-c | **`--limit` 分批 + 优先级排序**（`--batch` / `--plan`） | ✅ **已完成并实测**，见 §11.7.1 |
| v2-d | **生产 `.env` 一键更新脚本**（`gen-nas-env-update.py` → `nas-update-env.sh`） | ✅ **已完成并实测**（备份 / 三道安全闸 / 重启 / 闭环回读 / 不留中间文件），见 §11.12 |
| v2-e | **`init --roots-from-env`**：根的清单直接从 cross-seed 的 `.env` 派生 | ✅ **已完成并实测**（DC 47 组参数 → 一条命令），见 §10.6.4 |
| v2-f | **429 退避与 SKIPPED 的真相** —— 文档化 cross-seed 的"退避后跳过"机制 | ✅ **已文档化**，见 §11.13 |
| v2-g | **三个包全部 init 完成**：FRDS 486 + MBF 4 + DC 115 = 605 部 | ✅ **已完成**（状态机数据库本地管理） |
| v3 | **硬链接农场**（1 条 dataDir 取代 49 条，顺带闭合状态机的嵌套包缺口） | 🟢 **农场已建好**（475/475，独立复核通过，见 §10.5.6/§10.5.7）—— 待切换 `DATA_DIRS` |

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

### 10.4 ~~已知缺口：状态机还不支持嵌套包~~ → **已解决（2026-09-11）**

`reseed-state.py init` 原本是**单根、只扫一层**，而 DC 的"单片"分散在 47 个根里。
**现在已支持多根 + 深度**，DC 可以正常登记了（见 §10.6 的实现与实测）。

改动：

- `init --root` / `--local-root` 改成**可重复**（多根包按序一一对应），新增 `--depth`；
- `pack` 表新增 `roots` / `local_roots` / `max_depth` 三列（老库自动迁移，`root` 保留 = `roots[0]`）；
- `dir_name_of()` 改成**对已登记路径做最长前缀匹配**，这样嵌套包的"季层"不会被塌回"容器层"；
- 枚举规则**逐字复刻** cross-seed v6.13.7 的 `src/dataFiles.ts`（见 §10.6.1）。

> 原先写的两种修法（A 多根+深度 / B 硬链接农场）里，**A 已落地**。
> B 仍然值得做（`dataDirs` 从 49 条归一成 1 条），见 §10.5。

> 附带的待定策略：**未匹配的片子怎么处置**。
> 现状是写进 `scripts/unmatched.tsv` 就不再管。建议用 cross-seed 的
> `searchCadence`（多久重扫一遍 dataDirs）+ `excludeRecentSearch`（多久内不重复搜同一部）
> 做**低频自动重扫**，靠"等站点有人上传"自然补上；
> 而不是手动反复重打 webhook —— cross-seed 有搜索缓存，短期重复打基本是白打，还可能撞上 Prowlarr 退避。

### 10.5 ★「多根 + 深度」(A) vs「硬链接农场」(B)（2026-09-11 决策记录）

两种做法都能让 cross-seed 看见嵌套包里的每一部单片，但代价完全不同。

#### 10.5.1 先看清 DC 的真实形状（实测，2026-09-11）

三层嵌套，而且**同一包里混着三种形状**：

```text
DC相关剧集全系列大合集/
├── DC系列剧集/01.绿箭侠（2012.10-2019.10）/
│   └── Arrow.S01-S08.2012-2020.Bluray.1080p.MNHD-FRDS/     ← ① 容器层（不含视频，会被穿透）
│       ├── Arrow.S01.Bluray.1080p.MNHD-FRDS/*.mkv          ← ② 季层（直接含视频 = 叶子）
│       └── … 到 S08
├── DC系列剧集/17.守望者（2019.10.20）/
│   └── 守望者S01.Watchmen…@FRDS/*.mkv                       ← ①=② 直接含视频，只有一层
├── DC系列电影/01.蝙蝠侠1：侠影之谜 (2005)/
│   └── Batman Begins 2005 …-CHD/Batman Begins ….mkv         ← ① 单体文件
└── …（共 22 部电影 + 26 部剧集 = 47 个标签目录）
```

**关键实测结论**：47 个"标签目录"（`01.绿箭侠…`）的**直接子目录恰好就是真·发布名**。
这就是方案 B（47 条 dataDir）能跑出"0 垃圾"的原因 —— 不是运气，是这条包的结构决定的。

#### 10.5.2 方案 A：多根 + 深度

```yaml
# cross-seed/config.js
dataDirs: [ …包根… ]            # 1 条
maxDataDepth: 3                 # ★ 必须调大，官方警告"会产生更多 searchee + 更多 indexer 请求"
```
状态机侧：`init` 要支持重复 `--root`/`--local-root` + `--depth N`，约 60 行改动。

| | |
|---|---|
| ✅ | **不动 NAS 上的目录**，纯配置 |
| ✅ | 配置是**声明式**的：包变了改一行路径即可，无中间状态要维护 |
| ❌ | **必须调大全局 `maxDataDepth`** —— 这是全局开关，会连带影响 FRDS/MBF 的枚举行为 |
| ❌ | 包根的直接子目录（`DC系列剧集`、`DC系列电影`）**无条件成为 searchee** → 2 条必然搜不到的垃圾 |
| ❌ | 中文标签目录（`01.绿箭侠…`）也会成为 searchee → 又一批垃圾（实测 47 条） |
| ❌ | 状态机要改代码，且"多根"是个持续维护的负担 |
| ❌ | 包结构一变（有人往包里塞新剧），路径配置和枚举规则都要重算 |

#### 10.5.3 方案 B：硬链接农场

建一个**扁平**的农场目录，里面每个子目录 = 一部单片（硬链接指向真实数据）：

```text
/volume1/video/download/reseed_farm/          ← 唯一的 dataDir
├── Arrow.S01-S08.2012-2020.Bluray.1080p.MNHD-FRDS/   ← 硬链接副本（含季层）
├── 守望者S01.Watchmen…@FRDS/
├── Batman Begins 2005 …-CHD/
└── …（≈1000 个）
```

```yaml
dataDirs: ["/volume1/video/download/reseed_farm"]
maxDataDepth: 2                 # 默认值，不动全局
```

| | |
|---|---|
| ✅ | `dataDirs` **永远只有 1 条**，包再多也不用改配置 |
| ✅ | **不动全局 `maxDataDepth`** → FRDS/MBF 行为完全不变 |
| ✅ | **0 垃圾 searchee**：农场子目录名 = 真·发布名，不会混进中文标签 |
| ✅ | **状态机零改动**：1 个根、1 层 → `reseed-state.py init --root /volume1/video/download/reseed_farm` 直接能用，§10.4 的缺口自动闭合 |
| ✅ | 硬链接**不占数据块**（同卷），只多 inode + 目录项 |
| ✅ | 农场是**统一命名空间**：跨包、跨类型（电影/剧集）一视同仁 |
| ❌ | **要新写一个"农场构建器"**，并负责增量同步（已实现：`scripts/build-farm.sh`；~~Windows SMB 建不了硬链接~~ ← **此说不成立**，见 §10.5.7） |
| ❌ | 多一层间接：农场坏了/没同步 → cross-seed 看不见片子（A 没有这个失效点） |
| ❌ | 必须与源同物理卷（`/volume1`）—— 和 `LINK_DIR` 同样的约束 |
| ❌ | **重名冲突**要定策略：两个包含同名发布时，农场里只能有一个（或加前缀，但前缀会破坏"目录名=发布名"的匹配） |
| ❌ | 多一次全量遍历（≈1000 目录）才能把农场建起来 |

#### 10.5.4 农场该放哪：**不要**放 `reseed_singles/` 里面

`/volume1/video/download/reseed_singles` 就是 `LINK_DIR`，cross-seed 往里写
`LINK_DIR/<Tracker>/<发布名>/…`，所以它的**直接子目录是"站点名"**（现在只有 `SiteA/`）。

把 `reseed_farm` 塞进去会变成"一个假站点名"，三个坏处：

1. **视觉污染**：`reseed_singles/` 里分不清哪些是站点、哪些是农场；
2. **随时会炸**：只要哪天把 `reseed_singles`（或其父目录）加进 `dataDirs`，
   `reseed_farm` 和 `SiteA` 会**双双变成 searchee**，白白烧查询额度；
3. **输入输出同树**：`reseed_singles` 是 cross-seed 的**输出**，农场是它的**输入** ——
   混在一起迟早出事故。

**放哪都行，唯一硬要求是"和源大包同一个物理卷"**（`/volume1`）。所以用**兄弟目录**：

```text
/volume1/video/download/reseed_singles/     ← 输出（LINK_DIR），不动
/volume1/video/download/reseed_farm/        ← 输入（dataDir），新建
```

> 注意：硬链接**不占数据块**，所以 `/volume1` 只剩 ~20 GB 不影响农场；
> 占的是 inode + 目录项（≈1000 个目录、几千个文件，可忽略）。

#### 10.5.5 结论

- **现在（已落地）**：方案 A 的变体 —— 49 条 `dataDir`（FRDS + MBF + 47 个 DC 标签目录），
  `maxDataDepth` 保持默认 2。**这是最短路径，已经能跑，且不产生垃圾 searchee**（因为标签目录的直接子目录就是真发布名）。
- **状态机侧的对应修法已实现**（§10.4 / §10.6）：`init` 支持多根 + 深度，
  DC 47 根 → 115 单片已能正常登记。**所以 §10.4 的缺口不再是阻塞项。**
- **建议下一步（v3）**：上方案 B。它的真正价值**不是省几条配置**，而是
  **把"N 个异构大包"归一成"一个扁平的、状态机原生支持的 searchee 集合"** ——
  每次加包都要改 `.env`、包内结构变化要重算枚举规则，这两个问题会一起消失。
- **两者不冲突**：A 可以继续跑着，农场构建器做好后，把 `dataDirs` 从 49 条切成 1 条即可。

#### 10.5.6 方案 B 实现记录（2026-09-11 晚）

**产物**：`scripts/build-farm.sh`（NAS 本机**或** Windows 都能跑，见 §10.5.7）。

> ⚠ 本节写于 2026-09-11 **当天早些时候**，当时以为"SMB 建不了硬链接"。
> 该假设**当晚就被实测推翻**，请以 §10.5.7 为准；本节其余内容（等价性论证、
> 安全设计、prune bug）仍然成立。

**核心洞见 —— 规则只有一条，而且是构造上等价的**

农场子项 = **每个 dataDir 的直接子项**。证据：cross-seed 的枚举是

```text
dataDirs.flatMap(dd => readdir(dd).flatMap(c => findNestedRoots(c, maxDataDepth)))
```

农场的子项恰好 = 原 49 个 dataDir 的直接子项之**并集**，
于是「农场 + depth=2」与「49 条 + depth=2」把**同一个函数作用在同一批首层条目上** →
逐条产出相同的 searchee。

> ★ 这一点比"我们把 depth 规则复刻对了"更可靠：**它不依赖复刻是否正确**。
> 前提只是农场条目必须**忠实镜像**源目录结构（同基名、同内部结构、同文件大小）——
> 硬链接正好做到。

**实测（真实 NAS，dry-run）**：

| 项 | 值 |
|---|---|
| dataDir 直接子项合计 | **475**（474 目录 + 1 个散文件） |
| 跨 dataDir 重名 | **0**（所以"重名策略"这个待定项实际不存在） |
| 源目录读不到 | 0 |
| 抽样外推文件数 | 约 2375 个文件 / 5.3 TB 数据 |
| 农场额外占用 | **0 字节数据**（硬链接），仅 475 个目录 + 2375 个目录项 |

> 475 这个数字由**两份独立实现**给出（Python 走 `os.listdir`、shell 走 `"$dd"/*`），
> 互相印证。

**安全设计（三条硬约束）**：

1. **绝不 `chown -R`** —— 硬链接文件与源文件是**同一个 inode**，对其 chown 会
   **改掉源文件的属主**。脚本只用 `find -type d -exec chown`（农场目录是新造的，不在 inode 上共享）。
2. **`--prune` 有安全闸** —— 期望集为空却要 prune 时**拒绝执行**。否则 `.env` 一旦读坏，
   就会把整个农场删光。这条是**测试中真踩到的**：见下。
3. **默认 dry-run**，`--apply` 才动手（与 `reseed-state.py drive` 的习惯一致）。

**一个被测试抓到的真 bug（值得记）**：初版清单只记录**新建**的条目，且只在
`--prune` 时才落盘 → 于是 prune 时 `grep` 一个都匹配不上 → **把 4 条全删了**（源文件无恙）。
修法：无论新建还是已存在都记入"期望集"，且每次 `--apply` 都落盘；prune 比对新期望集
（用 `grep -qxF` 精确匹配名字，避免前缀误匹配）。

**沙箱验证清单（本地 NTFS 上跑真脚本）**：硬链接同 inode（含嵌套目录与散文件）✓ /
幂等重跑 0 新建 ✓ / `--verify` 计数一致 ✓ / dry-run 不建任何东西 ✓ /
源删掉一条后 prune **只**删那一条 ✓ / prune 后再跑 0 删除 ✓ / 期望集为空时拒绝删除 ✓ /
prune 之后源文件内容毫发无损 ✓

**尚未启用**：还要在 NAS 上 `sh build-farm.sh --apply`，再把 `.env` 的 `DATA_DIRS`
切成农场那一条并重建容器。**建议与"移除 BTSCHOOL"合并成一次重建**。

#### 10.5.7 ★ 推翻一个假设：这个 NAS 经 SMB **能**建硬链接（2026-09-11 晚）

**背景**：§10.5.3 / §10.5.6 都写着"Windows SMB 建不了硬链接，必须 NAS 本机跑"。
这句话**从来没有验证过**，是从"SMB 协议不支持跨主机硬链接"的通用印象推出来的。

**实测结论：对这个 NAS 而言是错的。**

| 验证 | 结果 |
|---|---|
| 原生 Windows `os.link(a, b)` | ✅ 成功 |
| 两者 inode | **相同**（`562949953463929`） |
| `os.stat().st_nlink` | 2（两边都是） |
| 删掉 `a` 后 `b` | ✅ 内容仍在，`nlink` 降到 1 |
| MSYS `cp -al` | ✅ 同样产生真硬链接 |

也就是 SMB 客户端把 `link()` 当成创建**服务端**硬链接的请求下发了，服务端（Synology
btrfs/ext4）照做 —— **数据一个字节都没过网**（删源文件后副本仍在，就是铁证）。

> ⚠ 顺带记一个 MSYS 陷阱：`stat -c %h` 对 SMB 硬链接**谎报 `links=1`**，
> 但 `stat -c %i`（inode）和原生 `os.stat().st_nlink` 都准确。
> **别拿 `%h` 判断 SMB 上的硬链接**。

**因此给 `build-farm.sh` 加了 `--map FROM=TO`**（路径前缀翻译），让同一份脚本
两边都能跑：`.env` 里是 NAS 绝对路径（`/volume1/...`），从 Windows 跑时翻译成
UNC（`//iSunker-DS423/...`）。只做前缀匹配，不做任何猜测。

**真实构建结果（2026-09-11 晚，从 Windows 经 SMB 执行 `--apply`）**：

```text
源直接子项合计 : 475   （= 本次期望集 475 条）
★ 新建         : 475        已存在(跳过): 0
  源目录缺失   : 0          跨卷跳过    : 0
```

耗时数分钟（逐文件 RPC，约 70 条/分钟）。`--verify` 随后报：
`农场现有条目 475 / 源有但农场没有 0 / 农场有但源没有 0`。

**独立复核（不复用脚本自身输出，直接问文件系统）**：

- 475 / 475 个名字双向对齐，**零重名**
- 474 个目录条目 + 1 个散文件条目（与 §10.5.6 的实测一致）
- 散文件条目 inode **相同** ✅
- 均匀抽样 32 条目录条目（每 15 条取 1，覆盖整个农场）、共 **160 个文件**：
  **全部同 inode、同尺寸** ✅

> ★ 复核时踩了自己的坑，值得记：**顶层目录的 inode 必然不同** —— 硬链接目录是
> 非法操作，`cp -al` 只能新建目录。所以"顶层 inode 比对"对目录条目而言是
> **判据写错**，不是缺陷。文件级 inode 才是有效判据（目录的正确性由"结构 +
> 文件树逐条一致"来保证，cross-seed 也只读路径/文件名/尺寸，不读目录 inode）。

**仍未启用**：`.env` 的 `DATA_DIRS` 还没从 49 条切成农场这一条 ——
**农场建好 ≠ 已生效**，容器没重建之前 cross-seed 完全看不见它。
建议与"移除 BTSCHOOL"合并成一次 `--force-recreate`（见 §13.6/§13.10）。

#### 10.5.8 复现命令（两条路，结果完全一样）

```bash
# NAS 本机
cd /volume2/docker_ssd/prowlarr_cross-seed_autohardlink && sh build-farm.sh --apply

# Windows（经 SMB，--map 做前缀翻译）
COMPOSE_DIR="//iSunker-DS423/docker_ssd/prowlarr_cross-seed_autohardlink" \
FARM="//iSunker-DS423/video/download/reseed_farm" \
sh scripts/build-farm.sh --map "/volume1=//iSunker-DS423" --apply
```

> 脚本每次运行都**自证**：在农场所在文件系统上建一个临时文件、`cp -al` 它、
> 比对 inode，然后删掉。所以"这台机器能不能建硬链接"不靠文档断言，跑一次就知道。
> 探针**绝不用 `.env` 当试验品** —— 失败路径会留下含密钥的副本（这个 bug 在
> 写的时候就修掉了，见 §13.10）。

#### 10.5.9 ★ 切换前的等价性证明（真实数据，2026-09-11 晚）

§10.5.6 的等价性是**论证**（"同一个函数作用在同一批首层条目上"）。切换前又在
**真实 NAS 数据**上验了一遍，用的是编排器自己的 `find_searchee_paths`
（= cross-seed 枚举规则的复刻），而不是另写一套。

**判据怎么选的（这里踩过两次坑，值得记）**：

| 判据 | 结果 | 对不对 |
|---|---|---|
| 比 searchee 的**绝对路径** | 1888 vs 1888，但"双向 0 差异"变成"双向 1888 差异" | ❌ **判据写错** —— 农场就是为了换根才存在的，比绝对路径必然全不等 |
| 比顶层**目录 inode** | 474 条"不同" | ❌ **判据写错** —— 硬链接目录是非法操作，目录 inode 必然不同 |
| 比 cross-seed **真正用的指纹**：`(searchee 名字, [(相对路径, 尺寸), …])` | **1888 = 1888，双向 0 差异** | ✅ |

```text
maxDataDepth = 2
A) 生产 49 条 dataDir → 1888 条 / 1888 种指纹
B) 农场  1 条 dataDir → 1888 条 / 1888 种指纹
只有 A 有 : 0        只有 B 有 : 0
```

> ★ 结论：切换后 cross-seed 看到的 searchee（名字 + 每个文件的相对路径与尺寸）
> 与现在**逐条完全相同** —— 不会新增或丢失任何匹配机会。
> 这条比 §10.5.6 的论证更强：论证说明"应该一致"，这里说明"实际读出来就一致"。

#### 10.5.10 一个诊断结论：`.env` 早就改对了，**只有容器是旧的**

收尾时查生产 `.env`，发现 **`TORZNAB_URLS` 已经只有 2 条**（`/2`、`/4`），
**`/3/api` 早就不在文件里了**。

也就是说 —— 那些 `/3/api` 的 410 **完全不是配置错误，而是"改了 `.env` 没重建容器"**：
磁盘上的 `.env` 是对的，跑着的容器用的是启动时注入的旧环境变量。

> ★ 这正是 §13.10 那条自检（⑧ `check_env_applied`）要抓的东西，而它第一次触发
> 就命中了真问题：20:25 那次运行报出 `http://prowlarr:9696/3/api ← HTTP 410 ×49`，
> 打印出修复命令，然后按 `min_sleep` 正确跳过本轮。
>
> **所以原计划里的 `add-indexers.py --remove` 不用跑了** —— 文件侧早已完成，
> 剩下**只有** `--force-recreate` 这一步，而它本来就要为切农场做。两件事合并成一次重建。

### 10.6 ★ cross-seed 的 searchee 枚举规则（读源码定论）+ 多根已落地

#### 10.6.1 规则（逐字读 cross-seed v6.13.7 `src/dataFiles.ts`）

```js
findSearcheesFromAllDataDirs = dataDirs.flatMap(dd =>
    readdir(dd).flatMap(child => findPotentialNestedRoots(child, maxDataDepth)))

findPotentialNestedRoots(root, depth):
  if (depth <= 0 || shouldIgnore(root))  -> []
  else if (isDir)                        -> [...递归(子项, depth-1), root]   // 自己也算
  else /* 文件 */                        -> [root]

shouldIgnore: 目录名 ∈ {sample, proof, bdmv, bdrom, certificate, video_ts}
              文件扩展名 ∉ VIDEO_EXTENSIONS(.mkv/.mp4/.avi/.ts/… 共 35 个)
```

**⚠ 结论：规则是纯按深度，没有"目录里含视频才算 searchee、否则被穿透"这回事。**
`maxDataDepth` 就是**从 dataDir 往下数几层**；第 1..N 层的**目录和视频文件**全都是
searchee（非视频文件忽略，黑名单目录忽略且不再下钻）。

> 我之前那个"含视频即叶子"的模型是**错的** —— 它在 FRDS 上预测 485、实际 405，
> 差的那 80 个正是"第 2 层不含视频的目录"（比如 `X战警合集…/X战警1…`）。
> **教训：涉及别人的枚举/匹配规则，必须读源码，别靠反推。**
> 反推时"数据对不上"只会让你怀疑数据，读源码才会让你发现模型错了。

#### 10.6.2 实测校验（三个包，0 垃圾名）

| 包 | 根数 | `--depth 1` | `--depth 2` | 垃圾名 |
|---|---|---|---|---|
| FRDS | 1 | 382（含 `--exclude "0观影清单*"`） | **486** | 0 |
| MBF | 1 | — | **4** | 0 |
| DC 合集 | 47 | — | **115**（88 第 1 层 + 27 第 2 层） | 0 |

- FRDS 多出的 104 个 = `Rocky.I~VI`、`Saw.I~VII`、`Creed`、`Jigsaw` ——
  全是**合集里的单片真发布名**，104/104 都含年份/卷号。
- DC 的 27 个第 2 层 = `Arrow.S01…Arrow.S08`、`Preacher.S01~S04`、`Titans.2018.S01~S04` ——
  27/27 全是季级真发布名，**只有 5 个第 1 层目录有多季子项**。
- DC 47 根、115 单片，**0 重名**。

#### 10.6.3 回归实测：depth 从 1 提到 2，多捞回 3 个真匹配

在真实库副本上跑（`hlink/state.db` 的 copy）：

| | depth=1（原状） | depth=2 |
|---|---|---|
| 登记 | 382 部 | **486 部** |
| `cross-seed.db` 认为搜过 | 95 | **105**（+10） |
| 匹配到单种 | 48 | **51**（+3） |
| **对不上目录的 searchee 名** | **10 个** ⚠ | **0** ✅ |

那 10 个对不上的，正是 `X战警合集…/X战警1…` 这类第 2 层目录 ——
**depth=1 让状态机对它们完全失明**。提到 2 之后 unresolved 归零，还多认了 3 个真匹配。

#### 10.6.4 落地实现

- `orchestrator/state.py`
  - 新增 `VIDEO_EXTENSIONS` / `IGNORED_FOLDER_SUBSTRINGS` / `should_ignore_path()` /
    `find_nested_roots()` / `find_searchee_paths()` / `scan_pack()`（含源码出处与版本注释）
  - `dir_name_of(path, root, dir_paths=None)`：**最长前缀匹配**。DC 的
    `…/01.绿箭侠…/Arrow.S01-S08…/Arrow.S02.Bluray…/xxx.mkv` 会正确归到**季层**
    `Arrow.S02.Bluray…`，而不是塌回容器 `Arrow.S01-S08…`（后者是 DC 之前丢数据的根因）
  - `scan_pack()` 输出的路径**一律规范成 `/`** —— Windows 上 `os.path.join` 会给反斜杠，
    不归一的话做前缀替换会静默出错（这个是实测抓到的真 bug）
  - `pack` 表加 `roots` / `local_roots` / `max_depth`；`upsert_pack()` / `roots()` /
    `local_roots()` / `max_depth()`；`register_dirs()` 改成收 `[(名, 完整路径)]`；
    新增 `dir_paths()`
- `scripts/reseed-state.py`
  - `init --root` / `--local-root` 可重复、新增 `--depth`（默认 2，**必须与 cross-seed 一致**）
  - 新增 `_scan_pack()`：多根配对 + 本地路径→NAS 路径回写 + `--pattern`/`--exclude` 过滤；
    返回 `(条目, 重名, 问题)`，重名与列不了目录都会**明确报出来**（不静默丢）

**用法**（一条命令，不用手抄 47 条路径）：

```bash
# 先看（不写库）
python scripts/reseed-state.py init --pack dc-collection --depth 2 \
  --roots-from-env .env --match "DC相关剧集全系列大合集" --dry-run
#   → 从 .env 的 FARM_SOURCES（共 49 条）里挑了 47 条
#   → 根 47 个，深度 maxDataDepth=2
#   → 识别到 115 个单片

# 真写
python scripts/reseed-state.py init --pack dc-collection --depth 2 \
  --roots-from-env .env --match "DC相关剧集全系列大合集"
```

三个包各自的命令（都从同一个 `.env` 派生）：

```bash
# ★ 包名以 state.db 为准。`mbf` 在 hlink/config.yml 里的 job 名叫
#   `my-brilliant-friend-s01-s04` —— 两个名字指同一个包，**别照 job 名去 init**：
#   那样会**多建一个包行**（UNIQUE(pack, dir_name) 是按 pack 分的），
#   于是「登记 vs 驱动」的差集从 1 变 2，而多出来那条是文档自己造的。
python scripts/reseed-state.py init --pack frds-top250-2024 --depth 2 \
  --roots-from-env .env --match "DouBan_IMDB" --exclude "0观影清单*"     # → 486
python scripts/reseed-state.py init --pack mbf --depth 2 \
  --roots-from-env .env --match "My.Brilliant.Friend"                    # → 4
python scripts/reseed-state.py init --pack dc-collection --depth 2 \
  --roots-from-env .env --match "DC相关剧集全系列大合集"                  # → 115
```

**根从哪来 —— `FARM_SOURCES` 优先，退回 `DATA_DIRS`**（2026-09-12 改）：

| 时期 | `DATA_DIRS` 是什么 | `init` 该读谁 |
|---|---|---|
| v3 切换**前** | 那 49 条**源目录** | `DATA_DIRS`（读它就等于读源清单，正确） |
| v3 切换**后** | `/…/reseed_farm`（cross-seed 的**输入**，1 条） | **`FARM_SOURCES`**（那 49 条源目录） |

★ 切换之后还读 `DATA_DIRS` 的话，`--match <包关键词>` **一条都挑不到** ——
因为那条只是农场本身，不含任何源目录名。`_roots_from_env()` 现在**首选
`FARM_SOURCES`、缺席时退回 `DATA_DIRS`**，与 `build-farm.sh:132-155` 同一种优先顺序
（那不是新设计，是**补上同一个切换里漏改的那一个工具**）。详见 §19.1.3。

| 参数 | 作用 |
|---|---|
| `--roots-from-env ENVFILE` | 从该 `.env` 的 **`FARM_SOURCES`** 派生根（缺席时退回 `DATA_DIRS`；与 `--root` 二选一） |
| `--match KEYWORD` | 只取路径里含该关键词的条目（可重复，OR）。**多包共用一个 `.env` 时靠它分拣** |
| `--unc-host //HOST` | 本地根的主机前缀；不给则从 `scripts/.nasrc` 的 `NAS_NAME` 推断 |
| `--nas-prefix /volume1` | NAS 卷前缀，用于拼本地根，默认 `/volume1` |

> `--root` / `--local-root` 的显式写法仍然保留（适合单根包或临时试）。
> 两种方式**只能选一种**，同时给会直接报错。
>
> 已知限制：`--roots-from-env` 用**子串**匹配，所以两个包的关键词如果互相包含，
> 需要给更长的关键词。当前三个包（`DouBan_IMDB` / `My.Brilliant.Friend` /
> `DC相关剧集全系列大合集`）互不包含，无歧义。
>
> ★★ **这条配方本身就是一个声明点**（§19.1.2 的 ① 第 5 行）：包名和 `--match`
> 关键词都写在这里，改一个而忘了另一个，**两边都不会报**。已知的一处漂移：
> 本节原先把包名写成 `my-brilliant-friend-s01-s04`（那是 `hlink/config.yml` 的 job 名），
> 而 `state.db` 里叫 **`mbf`** —— 2026-09-12 已按 `state.db` 改正。
> 照错的那份重跑，会在库里**多出一个包行**。

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
| `UNMATCHED` | 真搜过、没匹配到 | ⏳ 仅当 **出现没搜过的索引器** 或 **过了冷却期**（默认 14 天） |
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

**结论：每站按周期重搜（默认 7 天，**2026-09-11 晚改为 14 天**），且可按站分别设。**

> **为什么从 7 天改成 14 天（账号安全，2026-09-11 晚）**
> `drive-loop` 挂上计划任务后系统进入**无人值守**，这个周期就从"调试参数"变成了
> **长期查询量的总闸门**：约 1000 部单片 × 7 天 = 每天 ~150 次查询/站、一年 5 万+ 次，
> 而且是**永不停止**的机器人流量。`delay=30` 只解决"快不快"，解决不了"像不像人" ——
> 长期稳定运行的自动化抓取**本身**就可能触发站点风控。
> 翻倍到 14 天，查询量直接减半；代价是未命中的片子多等一周，而"站上出现这个单种"
> 本来就不由我们控制。**账号 > 命中延迟。**
> 单个站想更保守：`--cadence "NanyangPT=30"`。
>
> 配套动作：定期看 Prowlarr 里各站的 **Query Limit 消耗**与账号状态（有无警告/降级），
> 这比看本地命中率更能提前发现风险。
>
> ★ 这条**人工动作**想自动化的话，设计与边界（尤其「站点真实余额拿不到」这个天花板）见 **§16.1**。

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
def due_indexers(indexer_seen, indexers_now, *, cadence_days=DEFAULT_CADENCE_DAYS,
                 cadence_by_indexer=None, now=None) -> list[str]:
    # 1) 从没搜过这个站              → due（立刻搜）
    # 2) now - last_searched >= 周期 → due
    # 3) 否则                        → 不 due，等
```

- `cadence_for(indexer, cadence_days=…, cadence_by_indexer=None)`：站级覆盖，站名命中就用站级值。
- `next_due_at(...)`：算出"最早什么时候可以再搜"，写进 `movie.next_retry_at`。
- **默认值只写在一处**：`orchestrator/state.py` 的 `DEFAULT_CADENCE_DAYS`（改 7↔14 改这一行）。

**CLI**：

```bash
# 全站统一（默认值，见 DEFAULT_CADENCE_DAYS）
python scripts/reseed-state.py todo --pack $PACK --indexers SiteA,SiteB

# 显式指定：全站 7 天
python scripts/reseed-state.py todo --pack $PACK --indexers SiteA,SiteB --cadence-days 7

# 按站覆盖：SiteA 14 天、SiteB 30 天
python scripts/reseed-state.py report --pack $PACK --cadence "SiteA=14,SiteB=30"

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
python scripts/reseed-state.py todo  --pack $PACK --indexers SiteA,SiteB --out scripts/todo-paths.txt
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
             check_every=10, check_secs=60.0, max_wait=1800.0, pause_on_backoff=True)
    .backoffs()             # 读 cross-seed.db 的 indexer 表 → [IndexerBackoff]
    .wait_out_backoff()     # 睡到退避解除；超过 max_wait 就放弃
    .run(paths) -> DriveStats
```

`cmd_drive` 的完整流程：

```
枚举待办 → 打印 ETA → (dry-run 提前返回) → DriveSession.run()
   ├─ 每条之间 sleep --interval（默认 30s，对齐 cross-seed 的 delay）
   ├─ 读 indexer 表检查退避 —— ★双触发（2026-09-12 加）：
   │     ├─ 每 --check-every 条（默认 10）
   │     └─ 每 --backoff-check-secs 秒（默认 60）★短退避靠它才看得见
   │     └─ 有 RATE_LIMITED 且 retry_after 未到 → 睡到解禁（--max-wait 默认 1800s 上限）
   │        已经过去但 retry_after 变了 → 记一笔命中，不等待（§17.5.2）
   └─ 打完后 wait_for_log_quiet(--settle 90) 等 cross-seed 忙完
→ 自动 _sync_now() 回灌 → 打印 newly_seeding / still_skipped / 按站周期表
```

> ★ 为什么检查要**双触发**（2026-09-12 修）：只按条数（10 × 30s = 300s）时，
> 实测 30~60 秒的退避窗口**整段落在两次检查之间**，`backoff_hits` 恒为 0。
> 详见 **§17.5.2**。

`DriveStats` 汇报：

| 字段 | 含义 |
|---|---|
| `total / sent / ok / failed` | 计划 / 实发 / 成功 / 失败 |
| `waited_sec` | 累计为退避睡掉的秒数 |
| `backoff_hits` | ★**见过**几次限流 —— 含"窗口已过去、我们并没等"的那种，所以它计数 ≠ 有等待 |
| `aborted` | 是否因 `> --max-wait` 中止 |
| `resync` | 打完自动回灌的 `SyncReport` |
| `still_skipped` | ★回灌后**仍**是 `SKIPPED` 的（说明这轮又被退了） |
| `newly_seeding` | ★这轮新变成 `SEEDING` 的（= 真赚到的） |

**新增/关键参数**：

```
--interval 30          两条 webhook 之间隔几秒（默认 30）
--check-every 10       每发几条检查一次退避（默认 10）
--backoff-check-secs 60  ★每几秒也检查一次退避（默认 60；0 = 关掉，退回只按条数）
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

- ~~**没接进编排器**：`orchestrator/main.py` 目前只有 `preflight/run/status/prestage`，
  还没加 `state` 子命令。~~ ✅ **2026-09-12 下午已加**，见下。
  ★ **原待办把名字写错了**：写的是 `status`，而 `status` **早就有了** ——
  缺的是 `state`。两者名字像、含义完全不同：
  **`status` 看 qB 的当下快照，`state` 看我们自己的 sidecar 状态库**；
  它们**对不上恰恰是 §17.5.1 那类 bug 的症状**，所以两个都得能单独跑。
  实现要点见 §11.10 末。
- **`indexerstatus` 走不通，只能读库**：cross-seed v6.13 的 HTTP API 只暴露
  `/api/ping` 和 `/api/status`（都返回 `OK`），`/api/indexerstatus`、`/api/indexers`、
  `/api/health`、`/api/stats`、`/api/version` **全是 404**。
  所以退避状态只能读 `cross-seed.db` 的 `indexer` 表（`status='RATE_LIMITED'` +
  `retry_after` epoch ms）。`DriveSession.backoffs()` 就是这么做的。

### 11.10 `orchestrator/main.py` 是什么

> 回答"orchestrator/main.py是什么脚本？"

它是 **`reseed-orchestrator` 这个容器/服务的命令行入口**（不是状态机的一部分）。
职责是"跑一轮完整的拆包保种作业"，子命令五个：

| 子命令 | 作用 |
|---|---|
| `preflight` | 只读预检：配置合法性、各任务是否同卷、单片枚举、qB 与 cross-seed 连通性 |
| `run` | 对启用的任务执行 匹配→注入→等待→汇报（`--job` 只跑一个，`--dry-run` 不触发） |
| `status` | 连 `:3060`，按分类列出当前单种的做种状态汇总 ← **看 qB 快照** |
| `state` | **只读** sidecar 状态库：登记的包 / 各阶段多少 / 还欠多少待搜（`--trend` 附趋势）← **看我们自己的账** |
| `prestage` | 可选：把某任务的大包整体硬链接到 `linkDir` |

```bash
python -m orchestrator.main preflight
python -m orchestrator.main run --job frds-top250-2024
python -m orchestrator.main status
python -m orchestrator.main state --pack frds-top250-2024 --trend
python -m orchestrator.main prestage --job frds-top250-2024 --dry-run
```

#### `state` 实现时的四个决定（2026-09-12 下午）

1. ★★ **先判文件在不在，再开库。** `StateStore.__init__` 会
   `mkdir(parents=True)` 再 `sqlite3.connect()`，而 sqlite 连一个**不存在的路径
   不会报错，会凭空建一个 0 字节的库** —— 实测踩过（打错一层路径，就在媒体目录里
   留下一个空 `state.db`，而命令**看起来是成功的**）。
   所以只读命令必须 `Path(db).is_file()` 先挡一道，并明确打印"我不会替你建空库"
   —— 空库会**伪装成"一部都没登记"**，比报错更坏。测试里钉死了"文件没被建出来"。
2. ★ **在 `load_config()` 之前分派。** `state` 不连网、不读 `config.yml`，
   没理由因为配置文件坏了/不在就跑不了 —— **出故障时恰恰最需要它还能用**。
3. **`--db` 默认给的是 `/config/state.db`，但特意在报错里写明它多半不存在**：
   compose 里 `./hlink:/config` 挂的是 `<compose>/hlink`（**编排器自己的配置目录**，
   只有 `config.yml`），而**真正在写的库在 `<compose>/drive-loop/hlink/state.db`**。
   → ✅ **已给 compose 补了一行 `./drive-loop/hlink:/state:ro`**（并设
   `RESEED_STATE_DB=/state/state.db`）。
   ★ 挂 **`ro`** 不是随手写的：`StateStore` 打开库时会跑一遍 schema 迁移（`ALTER TABLE`），
   所以 rw 挂载等于让一个**只读语义**的子命令**具备写坏生产库的能力** —— `ro` 直接掐掉这条。
   ★ 这一行**不需要重建容器**（`docker compose run` 每次重读 compose 文件）；
   生效的是**下一次跑编排器**的时候。
4. **子命令用 `--detail` 而不是 `-v/--verbose`**：顶层已经有一个 `-v` 了，
   子解析器再定义同名参数会把顶层那个**覆盖成默认值** —— `main -v state` 会静默丢掉 `-v`。
   这类"看起来能跑、偶尔不灵"的坑，直接换名绕开。

**验证**：`tests/test_orchestrator_state.py`，21 条断言全过（含上面第 1、2 条那两个"必须不"）。
另用**真库快照**（连 WAL 一起拷）跑过一遍：dc 115 / frds 486（161 待搜）/ mbf 4 —— 与基准一致。

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

### 11.11 「一轮全量能不能把已做种的排除在外？」

> 回答："一轮全量能不能做到已做种的不在这次全量范围内？"

**要分两条路看，结论相反。**

| 走哪条路 | 能排除已做种的吗 |
|---|---|
| **状态机 `reseed-state.py drive` / `todo`** | ✅ **能，而且这是它的默认行为** |
| **直接给大包根打 cross-seed webhook**（老做法） | ❌ **不能** —— cross-seed 不查我们的状态 |

**为什么状态机能**：`todo_detail()` 第一件事就是

```python
if r["stage"] in DONE_STAGES:      # DONE_STAGES = {SEEDING, MATCHED}
    continue
```

`SEEDING`（qB 里真有这个 info_hash）和 `MATCHED`（已注入、等 qB 确认）**永不进待办**，
连 `--include-cooldown` 都不放行（那个开关只影响"还没到重搜周期的 `UNMATCHED`"）。
所以 `drive --limit N` 每一批都只花在**还没做种**的片子上，已做种的一分钱额度都不占。

**为什么 cross-seed 原生不行**：`dataDirs` 的扫描是**无状态**的 —— 它每次把
所有 searchee 枚举出来，逐个 × 逐个索引器去搜。它确实有"已注入过就不重复注入"的记录，
但**搜索照发**。所以对大包根打一次 webhook，就是几百条查询一次性轰出去，
已做种的也在里面。

**实践建议**：

1. 日常重搜一律走 `reseed-state.py drive`（见 §11.7.1 分批），**不要**再对大包根打 webhook；
2. 若确实要让 cross-seed 自己跑一轮全量（比如刚加了新索引器、想全网重扫），
   那就接受"已做种的重搜一遍"，或者用 `blockList` 的 `folder:` 规则把已命中的目录名排除掉
   —— 但那是**静态清单**，每命中一部就要手工加一条，不划算，**不如直接用状态机**。
3. 需要"只补没搜过的站"时，`--indexers` 传当前生效的站名，`due_indexers()` 会算出
   `indexer_seen` 里缺的那些站，只对这些站发 —— 这比全量重搜精准得多。

---

### 11.12 生产 `.env` 一键更新（`gen-nas-env-update.py` → `nas-update-env.sh`）

> 回答："NAS 上的 .env 还得手动更新，把这个手动更新的代码发给我，我去 nas 一键完成。"

**为什么不能直接 `scp` 本地 `.env` 上去**：两个 `.env` 是**不同性质**的东西 ——

| | 本地仓库 `.env` | 生产 `.env`（NAS compose 目录） |
|---|---|---|
| 密钥 | **脱敏占位符**（`apikey=xxxxxxxx…`） | **真实密钥** |
| `DATA_DIRS` | 49 条（真相） | 1 条（老值，待更新） |

直接覆盖 = 把真实密钥换成占位符 = cross-seed 带着假 key 重启 = 全线 401。
所以做成"**只搬 `DATA_DIRS` / `LINK_DIR` 两键，其余键原样保留**"的补丁式更新。

**流水线**：本地 `.env`（事实源）→ `scripts/gen-nas-env-update.py` → `scripts/nas-update-env.sh`
（POSIX sh，gitignored）→ 拷到 NAS 的 compose 目录执行。生成物里 `DATA_DIRS` 用单引号
heredoc 定界，CJK / 全角括号 / 带空格的路径**一个字符都不会被转义**。

**用法**（NAS 上，SSH 或 Container Manager 均可）：

```sh
cd /volume2/docker_ssd/prowlarr_cross-seed_autohardlink
sh nas-update-env.sh --dry-run      # 只看会改什么（不写盘、不重启、不留文件）
sh nas-update-env.sh                # 改 + 备份 + 重启 cross-seed + 闭环回读
sh nas-update-env.sh --no-restart   # 只改不重启
```

**三道安全闸**（都在写盘之前）：

1. `.env.new` 里 `DATA_DIRS` 必须**恰好 1 行**（0 行=没替换上，2 行=替换逻辑炸了）；
2. 除 `DATA_DIRS` / `LINK_DIR` 之外的行必须**逐字节不变** —— ⚠ **只比行数是不够的**：
   行数一样但内容被换掉完全可能，而生产 `.env` 里是真实密钥、本地是占位符，
   串了就是全线 401。实现：`grep -vE '^(DATA_DIRS|LINK_DIR)='` 两边各出一份 → `cmp -s`；
   不一致就打印 `diff` 并拒绝写入；
3. `DATA_DIRS` 里每条路径逐个 `[ -d ]`，不存在的**只告警不拦**（可能是还没建好的新目录）。

**中间文件**（`.env.new.src` / `.env.new` / `.env.new.list` / `.env.other.old|new`）全部放在
`COMPOSE_DIR` 里用相对路径，跑前先 `rm -f`、`trap ... EXIT INT TERM` 兜底 —— 成功落地后
**一个都不留**，Ctrl-C 也不留。（最初用 `mktemp`，系统临时目录在某些环境不可写/会被清理，
改成相对路径后 `rm` 必定成功。）

**怎么确认它真的落地了** —— 只看脚本最后那行 `[4/4] [ok]` 不够，四处交叉验证：

```sh
# ① NAS 上的 .env 本身
awk '/^DATA_DIRS=/{n=split($0,a,","); print n}' .env
# ② 容器**实际**拿到的环境变量（最权威）
sudo docker inspect reseed-cross-seed --format '{{range .Config.Env}}{{println .}}{{end}}' \
  | grep '^DATA_DIRS=' | tr ',' '\n' | grep -c .
# ③ cross-seed 自己扫出来的枚举结果（新包的路径应该出现）
sqlite3 cross-seed/cross-seed.db "select count(*) from data where path like '%Brilliant%'"
# ④ 日志里最近一次重载
grep -n 'Validating your configuration\|entries from dataDirs' cross-seed/logs/info.current.log | tail -4
```

**回滚**：脚本每次都会先 `cp -p .env .env.bak.<时间戳>`，回滚就是

```sh
cp -p .env.bak.<时间戳> .env && sudo docker compose up -d --force-recreate cross-seed
```

> ⚠ **一个真实的坑**：`.env.new` 存在 ≠ `.env` 已更新。曾出现"备份和 `.env.new` 都生成了、
> 但 `.env` 还是老值"的状态（脚本在 `mv` 之前中断，旧版没有 trap 兜底）。
> 所以**判断成功与否一律以 ②（容器内环境变量）或 ③（DB 枚举结果）为准**，
> 不要只看 `ls` 有没有 `.env.new`。

---

### 11.13 429 退避与 SKIPPED 的真相（2026-09-11 新增）

> 回答："为什么状态机里有 282 条 SKIPPED？cross-seed 到底搜没搜过？"

**结论**：
- **cross-seed 确实没搜** —— 这 282 条在 `timestamp` 表里**没有记录**（`searched_indexers='[]'`）。
- **但这不是 bug，是 cross-seed 的"退避后跳过"机制**。

**时间线**（2026-09-11 上午）：

```
12:24:28  HDFans 返回 429 → cross-seed 标记"snoozing until 12:25:28"
12:24:28~  后续 295 条全部 "Skipped searching (filtered by temporarily disabled indexers)"
```

cross-seed 的 `webhook` 是**单线程顺序处理**的：
1. 收到大包根的 webhook → 开始枚举 searchee（384 个）
2. 逐个搜索 → 第 89 个（勇敢的心）时 HDFans 返回 429
3. **标记 HDFans 为"临时禁用"**（snooze 1 分钟）
4. 后续所有 searchee **直接跳过**，不再尝试搜索
5. 1 分钟后（12:25:28）HDFans 恢复，但**webhook 已经处理完了**

**所以**：
- 被跳过的 295 条 = **真的没搜过**，不是"搜了没匹配"
- 状态机的 `SKIPPED` 阶段 = **正确记录**了"被退避秒跳"这个事实
- 这些条目**应该被重搜** —— 这就是 `drive` 命令存在的意义

**状态机的处理逻辑**：

```python
# todo_detail() 里
if r["stage"] == "SKIPPED":
    # SKIPPED 的优先级最高（仅次于 ERROR），会立刻被重搜
    priority = TODO_PRIORITY["SKIPPED"]
```

**实践建议**：

1. **不要对大包根打 webhook** —— 384 条一次性轰出去，遇到 429 就全军覆没
2. **用 `drive --limit N` 分批** —— 每批只发 N 条，429 只影响当前批
3. **SKIPPED 的片子会优先被重搜** —— 跑 `drive` 时它们排在最前面
4. **加索引器可以解锁 UNMATCHED** —— 但 SKIPPED 不需要加站，只需要重跑

**验证方法**：

```bash
# 看 cross-seed.db 的 timestamp 表
sqlite3 cross-seed.db "select count(*) from timestamp"
# → 如果 < 382，说明有被跳过的（没搜过的没有记录）

# 看状态机的待办清单
python scripts/reseed-state.py todo --pack frds-top250-2024 --indexers SiteA,SiteB
# → SKIPPED 会排在最前面，且被计入待办
```

---

### 11.14 三个包 init 完成与 drive 分批策略（2026-09-11 新增）

> 回答："三个包都 init 完了，怎么分批 drive 最合理？"

**当前状态**（2026-09-11 16:24）：

| 包 | 单片数 | 待搜 | 阶段分布 |
|---|---|---|---|
| FRDS | 486 | 390 | PENDING 108 / SKIPPED 282 / UNMATCHED 48 / SEEDING 48 |
| MBF | 4 | 4 | PENDING 4 |
| DC | 115 | 115 | PENDING 115 |
| **总计** | **605** | **509** | |

**分批策略**：

```bash
# 1. MBF 先跑（4 部，2 分钟，快速验证通路）
python scripts/reseed-state.py drive --pack mbf --indexers HDFans --limit 50 \
  --url http://NAS_IP:2468 --api-key <CROSSSEED_API_KEY> --apply

# 2. DC 第 1 批（50 部，约 24 分钟）
python scripts/reseed-state.py drive --pack dc-collection --indexers HDFans --limit 50 \
  --url http://NAS_IP:2468 --api-key <CROSSSEED_API_KEY> --apply

# 3. FRDS 第 1 批（50 部 SKIPPED，约 24 分钟）
python scripts/reseed-state.py drive --pack frds-top250-2024 --indexers HDFans --limit 50 \
  --url http://NAS_IP:2468 --api-key <CROSSSEED_API_KEY> --apply
```

**一批做完重跑同一条命令就自动推进**（todo 按优先级排序，已完成的不会重复）。

**时间估算**：
- MBF：1 批 × 2 分钟 = 2 分钟
- DC：3 批 × 24 分钟 = 72 分钟
- FRDS：8 批 × 24 分钟 = 192 分钟
- **总计：约 4.5 小时**（纯发送时间，不含匹配等待）

**建议节奏**：
- 每批之间至少隔 1 小时（让 cross-seed 有时间匹配和注入）
- 不要连续猛发（容易触发 429）
- 每天跑 2~3 批比较安全

**关键参数**：

```bash
--interval 30          # 两条 webhook 之间隔 30s（对齐 cross-seed 的 delay）
--check-every 10       # 每发 10 条检查一次退避
--max-wait 1800        # 单次退避最多等 30 分钟
--apply                # 真发请求（默认 dry-run，一定要先 --plan 确认）
```

**注意事项**：
- `--plan` 先确认计划，再加 `--apply` 执行
- `drive` 默认 dry-run，**不加 `--apply` 不会发任何请求**
- 打完自动 `sync` 回灌，直接告诉你 `newly_seeding`（这轮真赚到几部）
- 状态机数据库 `hlink/state.db` 已 gitignore，**不要提交到 GitHub**

---

## 12. 收尾归档（2026-09-11 会话结束）

> 本章是**交接快照**。本节点已停止所有自动动作（不发 webhook、不 drive）。
> 下次接手从这里读起，再按需跳到 §10（多包）/§11（状态机）看细节。

### 12.1 本次会话产出（提交记录）

| 提交 | 内容 |
|---|---|
| `1273acb` | 状态机支持嵌套包：多根 init + 深度枚举 + 路径最长前缀匹配 |
| `40289d3` | `init --roots-from-env`：根的清单直接从 cross-seed 的 `.env` 派生（DC 47 组参数 → 一条命令） |
| `827231c` | NAS `.env` 一键更新脚本加固：三道安全闸 + 中间文件相对路径 + 验证指南（§11.12） |
| `c686669` | §11.13 429 退避与 SKIPPED 的真相 |
| `273e2db` | §11.14 三个包 init 完成与 drive 分批策略 |
| 本次 | §12 收尾归档 + README「当前状态与下一步」 |

更早（`82ababe` `--limit` 分批、`6e0ffea` 脚本生成器）见 §5 进度表。

### 12.2 系统现状快照

| 项目 | 状态 | 怎么验证 |
|---|---|---|
| NAS `.env` | ✅ `DATA_DIRS` = **49 条**，真实密钥保留 | `awk '/^DATA_DIRS=/{n=split($0,a,","); print n}' .env` |
| cross-seed 容器 | ✅ 已重启（16:00） | 日志 `Validated 1888 entries from dataDirs` |
| cross-seed.db `data` | ✅ **1963 行** | `select count(*) from data` |
| ├ FRDS | 932 | `path like '%DouBan_IMDB%'` |
| ├ DC | ~993 | `path like '%DC相关剧集全系列大合集%'` |
| └ MBF | 38 | `path like '%Brilliant%'` |
| 状态机 `hlink/state.db` | ✅ **605 部** | `report --pack <包>` |
| cross-seed API | ✅ 可达 | `curl http://192.168.0.7:2468/api/ping` → `OK` |
| qBittorrent | ✅ v4.6.5 | `curl .../api/v2/app/version` |
| 索引器 HDFans | ⚠ `RATE_LIMITED` 但 `retry_after` 已过期 → 实际可用 | 读 `indexer` 表 |

### 12.3 三个包的最终台账

| 包 | 单片 | 待搜 | 阶段分布 | 备注 |
|---|---|---|---|---|
| FRDS | 486 | **390** | PENDING 108 / SKIPPED 282 / UNMATCHED 48 / SEEDING 48 | `--depth 2` 后从 382→486（多认 104 个嵌套目录） |
| MBF | 4 | **0** | **UNMATCHED 4** | ⚠ **已实测：HDFans 上 0 匹配**，见 12.3.1 |
| DC | 115 | **115** | PENDING 115 | 47 个 dataDir，嵌套包 |
| **合计** | **605** | **505** | | |

- SEEDING 48 部 = HDFans 已匹配并注入成功（终点，永不重搜）
- UNMATCHED 52 部 = 真搜过、没匹配到（FRDS 48 + MBF 4），7 天后或加新站才重搜
- SKIPPED 282 部 = **被 429 退避秒跳，真的没搜过** → 优先级最高，见 §11.13

#### 12.3.1 ⚠ MBF 实测结论：HDFans 上 0 匹配

这是停止动作前跑出来的一条**真实业务结论**，值得单独记一笔。

- 现象：对 MBF 4 个季包各发一次 webhook，cross-seed 日志显示
  `Searching for ... | MediaType: PACK` → `Found 0 torrents for {...}`。
  4 部**全部 0 匹配**，`searchee` 表里也始终没有 Brilliant 相关记录。
- 附带现象：日志里大量
  `Did not search for ...S01E01....mkv | MediaType: EPISODE - it is a season pack episode`
  —— cross-seed 识别出这是季包，**自动跳过单集、只搜整季**（这是正确行为，不是问题）。
- 结论：**MBF（我的天才女友）这个资源在 HDFans 上没有对应种子，当前单站条件下做不了种。**
- 出路（二选一）：
  1. 给 Prowlarr **加别的站**再搜（多站是提高命中率的唯一手段，见 README「多站点」）；
  2. 接受 MBF 暂时放弃，把额度留给 DC / FRDS。
- 状态机已回灌为 `UNMATCHED`（不是 PENDING），所以**不会重复浪费额度**；
  7 天后或加新站时会自动重新进入待搜。

### 12.4 下一步操作手册

**顺序建议**：~~MBF（2 分钟，验证通路）~~ → **DC（3 批）→ FRDS（8 批）**。
> MBF 已经跑过了，结论是 HDFans 上 0 匹配（见 12.3.1），**不必再跑第二遍**；
> 除非你先给 Prowlarr 加了新站。加站后 MBF 的 4 部会自动从 UNMATCHED 解锁。

```bash
URL=http://192.168.0.7:2468
KEY=<CROSSSEED_API_KEY>
DB="//iSunker-DS423/docker_ssd/prowlarr_cross-seed_autohardlink/cross-seed/cross-seed.db"

# ★--db-path 必须给，否则回灌被跳过（见 12.5 坑 1）
python scripts/reseed-state.py drive --pack mbf --indexers HDFans --limit 50 \
  --url $URL --api-key $KEY --db-path "$DB" --apply

python scripts/reseed-state.py drive --pack dc-collection --indexers HDFans --limit 50 \
  --url $URL --api-key $KEY --db-path "$DB" --apply

python scripts/reseed-state.py drive --pack frds-top250-2024 --indexers HDFans --limit 50 \
  --url $URL --api-key $KEY --db-path "$DB" --apply
```

**节奏**：每批约 24 分钟（50 条 × 30s 间隔）；批间隔 ≥1 小时；每天 2~3 批较安全。
**推进**：一批做完**重跑同一条命令**即可自动进入下一批（待办按优先级排序，已完成的不会重复）。

**每轮结束后看这两个数**（`drive` 会自动打印）：
- `newly_seeding` —— 这轮真赚到几部
- `still_skipped` —— 这轮又被退了几部（>0 说明撞了 429，放慢节奏）

### 12.5 本次会话踩到的坑（按严重度）

1. 🔴 **`drive` 忘给 `--db-path` → 回灌被跳过、状态不更新。**
   现象：4 条 webhook 全发成功（HTTP 204），结尾却打
   `[!!] 回灌需要 --db-path（cross-seed.db 路径），已跳过`，退出码 **3**。
   后果：请求发出去了，但状态机不知道，`todo` 里还是 PENDING，重跑会重复发。
   补救：补上 `--db-path` 重跑，或单独跑 `sync` 回灌（都不发新请求，幂等）。
   → 已写进 README「当前状态与下一步」。

   本次实测还发现一个**假象**：补 `--db-path` 重跑时，终端返回了**空输出**，
   看起来像"没执行"，但 cross-seed 日志里 16:36 明明有搜索记录 ——
   它其实**跑完了**，只是输出被截断吞掉了。
   **判断 drive 有没有真跑，别看终端输出，去查 cross-seed 日志的 `Searching for`。**

2. 🔴 **`.env.new` 存在 ≠ `.env` 已更新。**
   实测出现过「备份和 `.env.new` 都生成了、但 `.env` 还是老值」（脚本在 `mv` 前中断，
   旧版无 trap 兜底）。判断生效与否**一律看** ① 容器内 `DATA_DIRS` 条数
   ② `cross-seed.db` 的 `data` 表。详见 §11.12。

3. 🟠 **一次 429 废掉 295 条。**
   webhook 是单线程顺序处理，中途撞 429 → 标记索引器临时禁用 → 后面全部
   `Skipped searching (filtered by temporarily disabled indexers)`。详见 §11.13。
   → 所以**绝不能对大包根打 webhook**，只能用 `drive --limit N` 分批。

4. 🟠 **`--depth` 必须等于 cross-seed 的 `maxDataDepth`**（默认 2）。
   它是"从 dataDir 往下数几层"，第 1..N 层的目录和视频文件都算 searchee。
   对不上 → 出现"状态机有、cross-seed 没有"的幽灵条目。详见 §10.6。

5. 🟡 **本地 `.env` 是脱敏占位符，生产 `.env` 是真实密钥。**
   `TORZNAB_URLS` 本地是 `apikey=xxxx…`，生产是 `da94d20a…`。
   直接 scp 覆盖 = cross-seed 带假 key 重启 = 全线 401。
   → `gen-nas-env-update.py` 只搬 `DATA_DIRS`/`LINK_DIR` 两键，且有逐字节安全闸。

6. 🟡 **Windows 侧别对 NAS（UNC 路径）跑 `rm`。**
   safe-delete 钩子会因 genie-trash 不支持 UNC 而 fail-closed。
   测试用 `D:/tmp/...` 本地路径；NAS 上的清理让 NAS 自己的脚本做。

### 12.6 还没做（留给下次）

> ★ 本节写于 §12 会话结束时。**其中第 1 条后来已完成** —— 进展见 §13.11。

- **v3 硬链接农场**：1 条 dataDir 取代 49 条，顺带闭合嵌套包缺口。设计已完成，见 §10.5。
  → ✅ **已建成 475/475 并证明等价**（§10.5.7 / §10.5.9 / §13.11），只剩 NAS 上切 `.env`。
- **Phase 2.6 重跑全量**：等合适时机。
- **编排器 `status` 子命令**：见 §11.9。
- **IYUU 扩散**：本次范围外，接口已预留，见 §1。

---

## 13. 接手会话（2026-09-11 晚）—— 加站 / 修 bug / 自动化

> 本章是 §12 交接快照之后**第二个会话**的记录。上一会话停在"所有自动动作已停止"，
> 本会话把它继续跑了起来，并补了三样东西：**加站脚本、跨包过滤修复、自动续跑循环**。

### 13.1 本会话做了什么（概览）

| # | 事项 | 结果 |
|---|---|---|
| 1 | 健康检查 | ✅ cross-seed `OK` / qB `v4.6.5` / Prowlarr `200` / `DATA_DIRS`=49 |
| 2 | **DC 批 1**（`drive --limit 50`） | ✅ +8 部做种（qB 48→65 中的 8 部属 DC） |
| 3 | **接入新站 BTSCHOOL + NanyangPT** | ✅ 见 §13.3；BTSCHOOL 卡 CF 已禁用 |
| 4 | **修跨包 searchee 误报 bug** | ✅ 122 对不上 → **0**，见 §13.4 |
| 5 | **FRDS 批 1**（`drive --limit 50`） | ✅ **+14 部做种**（51→65） |
| 6 | **写 `drive-loop.py`**（反馈驱动自动续跑） | ✅ 见 §13.5 |
| 7 | 文档归档（本章 + README） | ✅ |

### 13.2 新增文件与代码改动

| 文件 | 类型 | 说明 |
|---|---|---|
| `scripts/add-indexers.py` | 🆕 | 给 NAS `.env` 的 `TORZNAB_URLS` **追加索引器**。安全闸模式（仿 `nas-update-env.sh`）：只改 `TORZNAB_URLS` 一行、其余逐字节校验、自动备份；**自动补 `/api` 段**；幂等（按 `http://host:port/id` 前缀精确去重）。key 从现有 URL 提取、不落命令行。 |
| `scripts/drive-loop.py` | 🆕 | **反馈驱动循环**：跑一批 `drive` → 读 `newly_seeding` / `still_skipped` / `backoff_hits` → 动态定下次间隔 → DC↔FRDS 轮流。见 §13.5。 |
| `orchestrator/state.py` | ✏️ | ① `CrossSeedSnapshot` 加 `searchee_paths`（`searchee.name → data.path`）② 新增 `_resolve_searchee_to_pack()`（路径前缀判定包归属）③ `_sync` 改用它，跨包 searchee 静默跳过。见 §13.4。 |

### 13.3 接入新站的完整流程（可复用）

> **背景**：用户在 Prowlarr 网页里加了两个站（BTSCHOOL、NanyangPT），问"代码有没有自动检测新站"。
> **答案：没有全自动**。cross-seed **只认 `.env` 的 `TORZNAB_URLS`**，Prowlarr UI 加站不会自动同步过去。

```
Prowlarr UI 加站                        ← 用户手动
        ↓  ❌ cross-seed 看不见，断在这
改 .env 的 TORZNAB_URLS + 重建 cross-seed   ← 本流程
        ↓  ✅ cross-seed 启动拉 caps → indexer 表注册（active=1）
状态机 sync / drive --indexers <站名>        ← ✅ due_indexers() 自动解锁没搜过新站的片子
```

**实际操作**（2026-09-11 实测）：

```bash
# 1) 查 Prowlarr 里各站的 indexerId（★ID 会变，必须实时查，见 §6.6）
curl -s -H "X-Api-Key: <Prowlarr key>" http://<NAS_IP>:9696/api/v1/indexer \
  | python -c "import sys,json;[print(i['id'],i['name'],i['enable']) for i in json.load(sys.stdin)]"
#   1 HDtime / 2 HDFans / 3 BTSCHOOL / 4 NanyangPT (南洋)

# 2) 追加进 NAS .env（自动补 /api、只改一行、自动备份）
python scripts/add-indexers.py \
  --env "//YOUR-NAS/docker_ssd/prowlarr_cross-seed_autohardlink/.env" \
  --add "prowlarr:9696/3,prowlarr:9696/4"

# 3) 重建 cross-seed 让新 env 生效（★必须 force-recreate，restart 不行！）
#    在 NAS 上执行：
cd /volume2/docker_ssd/prowlarr_cross-seed_autohardlink \
  && sudo docker compose up -d --no-deps --force-recreate cross-seed
```

**三个必须知道的点**：

1. **`restart` 不够，必须 `--force-recreate`**。`docker compose restart` 只重启容器、**不重新注入环境变量**，新站的 `TORZNAB_URLS` 进不去。加 `--no-deps` 防止连带重建 Prowlarr（§4 的坑）。
2. **验证要看容器内 env 条数**（最权威）：
   ```bash
   sudo docker inspect reseed-cross-seed --format '{{range .Config.Env}}{{println .}}{{end}}' \
     | grep '^TORZNAB_URLS=' | tr ',' '\n' | grep -c '/api'      # 期望 = 站数
   ```
3. **cross-seed 的 indexer id ≠ Prowlarr 的 indexerId**。它是自己从 1 递增注册的（实测 NanyangPT=Prowlarr id4 → cross-seed id5），映射靠 URL 的 `/N/api` 保持。**别写死数字**。

**禁用某个站的正确姿势（⚠ 本会话踩到）**：

> 只在 Prowlarr 里 `enable=false` **不够** —— cross-seed 仍按 `TORZNAB_URLS` 去请求它，
> 每搜一次就吃一个 **HTTP 410（Gone）** 并触发 snooze，白白浪费一次请求。
> 见 §13.6 坑 5。**要彻底停用某站，必须把它从 `TORZNAB_URLS` 里移除**（或把 `enable`
> 之外的 URL 也删掉）再重建 cross-seed。

**判断某站要不要 FlareSolverr**（BTSCHOOL 就栽在这）：

| Prowlarr 手动搜该站看到… | 说明 | 配 FlareSolverr 有用吗 |
|---|---|---|
| `403` + HTML 挑战页 / 日志 `Cloudflare`、`cf-mitigated` | 被 CF 挡在门外 | ✅ 有用 |
| `500/502/520/522/timeout` | 请求**已穿过 CF**，站点后端挂了 | ❌ 没用 |
| `429 + Retry-After` | 站点限流 | ❌ 没用（该降 `delay`） |

BTSCHOOL 属第一行（Cloudflare）→ 用户决定**先禁用、后面换站**。

**换站 = 下站 + 上站，两半的顺序是反的**（2026-09-12 补，
下站工具已就绪：`scripts/add-torznab-indexer.py --remove`）：

| 阶段 | 做什么 | 为什么是这个顺序 |
|---|---|---|
| **下站 ①** | **先**改 `drive-loop/run.sh` 的 `--indexers` 去掉它 + `deploy.sh` | `--indexers` 是**状态机的排期依据**。`.env` 先摘、容器先重建的话，状态机还以为这个站在，于是「每部片都还没在新站搜过」这个判定**一直成立** → 白白重排、白烧额度 |
| **下站 ②** | `python scripts/add-torznab-indexer.py --remove <id> --apply` | 从生产 `.env` 的 `TORZNAB_URLS` 摘掉该条（**字节级保真**，自动备份） |
| **下站 ③** | 在 NAS 上 `sudo docker compose up -d --force-recreate cross-seed` | env_file 不重建不生效 |
| **上站** | 按上面「实际操作」那三步 —— 顺序**相反**：先 Prowlarr + `.env`，**最后**才动 `--indexers` | 站没通就写进 `--indexers` → 状态机记成「搜过了」并压 14 天冷却，而一次都没发出去 |

★ **为什么两半顺序相反**：`--indexers` 是**排期依据**，`TORZNAB_URLS` 是**实际会发出去的请求**。上站要保证「发得出去之后才排期」，下站要保证「不再排期之后才停发」—— 两边都是**让排期比请求保守**。搞反了就是白烧站点额度（本项目最高优先的资源）。

★ `--remove` 的安全闸：**摘到一条不剩会被拒绝** —— `TORZNAB_URLS=` 为空 = 一个站都不搜，而 cross-seed **不报错**，只表现成「这批没有匹配」（同 §16.2.1 / §18.9.1 那一族：**失败的形态是「看起来正常」**）。确实要清空加 `--allow-empty`。

★ `--remove` 与 `--id` **互斥**；幂等；除目标行外**逐字节不变**（含那份生产 `.env` 里混着的行尾与那个游离 `\n`）。8 项合成样本测试全过，见 §18.11.4。

### 13.4 ★ 修复：跨包 searchee 被误报「对不上目录」

**症状**：`sync --pack dc-collection` 一直报 `⚠ 有 118~122 个 searchee 名对不上目录（已跳过）`。

**误判排查**：一开始以为是 DC 嵌套路径的匹配逻辑（`dir_name_of` 最长前缀）有问题。
**查完发现不是** —— 那 122 个名字（`V字仇杀队…`、`2001太空漫游…`、`低俗小说…`）**全是 FRDS 包的片子**。

**根因**：`searchee` 表是 cross-seed **全库共享**的（FRDS+MBF+DC 都在这张表），
而 `_sync` 拿**当前包（DC）**的目录名去匹配**全库**的 searchee 名 —— 别的包的片子自然对不上，
却全被计进了当前包的 `unresolved`。**这是调用语义问题，不是匹配算法问题。**

**修法**（`orchestrator/state.py`，3 处改动）：

1. `CrossSeedSnapshot` 新增 `searchee_paths`（`searchee.name → data.path`）。
   **关键实测**：`data` 表的 `title` 与 `searchee.name` **100% 对齐**（471/471），
   于是每个 searchee 都能拿到**完整路径** —— 这是区分包的唯一可靠依据。
2. 新增 `_resolve_searchee_to_pack()`：按 **dataDir 路径前缀**判定包归属，返回
   `(单片名, 归属)`，`归属` ∈ `{"in_pack","other_pack","unresolved"}`。
3. `_sync` 用它替换原来的 `resolve_dir_name(name, dirs)`：**跨包（other_pack）静默跳过、
   不计数**；只有「路径在本包内、但归不到具体单片」才算 `unresolved`。

**实测验证**（三个包全部归零）：

| 包 | 修前 | 修后 | 搜过 / 匹配 / 做种 |
|---|---|---|---|
| DC | ⚠ 122 对不上 | ✅ **0** | 50 / 8 / 8 |
| FRDS | ⚠ 118 对不上 | ✅ **0** | 140 / 65 / 65 |
| MBF | — | ✅ **0** | 4 / 0 / 0（HDFans 0 匹配，正常） |

> 顺带：修好后 FRDS 的 `SEEDING` 数（65）与文档 §10.6.3 的实测吻合，
> 确认了「depth=2 多认 3 个真匹配」那条结论。

### 13.5 ★ `drive-loop.py`：反馈驱动自动续跑

**起因**：§12 交接时发现"种子停在 58 不动了"。查清真相是 ——
**cross-seed 不会自动重搜**（`searchCadence` 没启用），**`drive` 是一次性命令**（跑完一批退出，
不自动排下一批），所以 12:24 全量被打断后就没人再触发，直到本会话手动跑。

**做法**：把"重跑同一条命令推进下一批"自动化，且**间隔按站点反馈动态调整**（不是固定时间表）。

**反馈信号 → 下次间隔**：

| 上一批的信号 | 含义 | 下次间隔 |
|---|---|---|
| `aborted`（退避等到超 `--max-wait`） | 站点严重异常 | 3 小时 |
| `still_skipped > 0` | 这轮又被退避跳过 | 2 小时 |
| `backoff_hits > 0` 且**实际等了 ≥ 10 分钟** | 站点在压我们 | 2 小时 |
| `backoff_hits > 0` 且实际等了 **3 ~ 10 分钟** | 中等退避 | 90 分钟 |
| `backoff_hits > 0` 但**没等到 3 分钟**（含"窗口已过去、压根没等"） | 站点打了个喷嚏 | 45 分钟 |
| `newly_seeding > 0` 且无退避 | 站点健康 | 45 分钟 |
| 无退避、无新增 | 正常 | 45 分钟 |

上下限 30 分钟 ~ 4 小时（`MIN_SLEEP`/`MAX_SLEEP`），包间默认 **DC → FRDS 轮流**。

> ★ 2026-09-12 两处修正，**都指向同一件事：这张表以前是"死的"**。
> ① `backoff_hits > 0 → 2 小时` 那条原本是**布尔**判断（喷嚏与重感冒同罚），
> 现改为按**实际等待时长**分档（`BACKOFF_SHORT_SEC` / `BACKOFF_LONG_SEC`）。
> ② 更根本的是：在 `--once` 模式下 `next_sleep()` 的结论**只进日志、没人用** ——
> 真正的闸门是写死的 `min_sleep`（30 分钟）。**所以上面这张表从来没生效过。**
> 现在结论落盘到 `.drive-loop.state` 的 `last_sleep_sec`，闸门改成 `clamp(max(min_sleep, 上批结论))`。
> 两处的根因与验证见 **§17.5.3 / §17.5.4**。

**用法**：

```bash
# 真跑一轮（当前包下一批，约 24 分钟）
python scripts/drive-loop.py --once --indexers HDFans,NanyangPT --limit 50

# 循环跑（默认 DC↔FRDS 自动轮流，直到都没待搜）
python scripts/drive-loop.py --indexers HDFans,NanyangPT

# 看计划不发请求
python scripts/drive-loop.py --once --dry-run
```

**为什么不是固定 cron**：这套系统的关键不确定项是**站点状态**（会 502/限流，见 §6.5）。
固定时间表在站点抖动时照打不误（继续撞 429），在站点健康时又白白空等。
反馈驱动能"撞了自动放慢、顺了自动收紧"。

**`--once` 模式**：配合外部调度**每 15 分钟唤醒一次**
（2026-09-11 深夜起是 **NAS 的 DSM 任务计划**，之前是 Windows 计划任务 —— 为什么搬，见 §14），
脚本内部用 `min_sleep`（默认 30 分钟）保证连续唤醒时不会猛打。

> ⚠ **`drive-loop` 的回灌必须带 qB**（`--qbit-url`，默认已填 `:3060`）。
> 漏了会把 `SEEDING` 误降级 —— 见 §13.6 坑 1。

### 13.6 本会话踩到的坑（按严重度）

1. 🔴 **`drive` 忘带 `--qbit-url` → `SEEDING` 被误降级成 `MATCHED`。**
   现象：FRDS 批 1 的回灌打出 `已在 qB 里: 0` / `SEEDING=0` / `本次新增做种: -51`（负数！）。
   根因：`stage` 是**推导的纯函数**（§11.2），推导需要 qB 的做种哈希；漏 `--qbit-url`
   时 `seeding_hashes` 为空 → 已有的 51 个 `SEEDING` 全部降级为 `MATCHED`。
   **补救**：补跑一次带 `--qbit-url` 的 `sync` 即完全恢复（已是幂等的推导，不丢数据）。
   → **`drive` 的自动回灌必须带 `--qbit-url`**（和 §12.5 的"必须带 `--db-path`"是姊妹坑）。

2. 🔴 **`cp` 复制 cross-seed.db 会丢 WAL 数据 → 误判"新站没注册"。**
   现象：`cp` 出来的副本里 `indexer` 表只有 id 1、2，看着像新站没注册；
   **直读 UNC 的原库**（`PRAGMA query_only=1`）却能看到 id=4、5 —— 新站其实好着呢。
   根因：`cp` 只拷主文件，`.db-wal` 里未 checkpoint 的数据丢了（§11.4 早已记录此坑，
   这次是在**我们自己写的诊断脚本**里又踩了一遍）。
   → **诊断一律直读 UNC 原库**（`sqlite3.connect(unc_path)` + `PRAGMA query_only=1`），
   别 `cp`。`read_crossseed_db()` 已经是直读优先，但临时脚本要注意。

3. 🟠 **`add-indexers.py` 幂等检查用了裸数字 → 误匹配 apikey 里的字符。**
   现象：首次跑报 `[skip] 已存在: .../3`、`.../4`，实际 `.env` 里只有 `/2/api`。
   根因：`key = a.split("/")[-1]` 得到裸 `"3"`，而 `"3" in url` 会撞上 apikey 字符串里的 `3`。
   → 改成按 `u.split("?", 1)[0] == prefix`（`http://host:port/id` 前缀）精确比较。

4. 🟠 **Torznab URL 必须带 `/api` 段。** 第一次写成 `http://prowlarr:9696/3?apikey=…`
   （少了 `/api`），cross-seed 拉 caps 会 404。正确形式见 §3.4：
   `http://prowlarr:9696/<indexerId>/api?apikey=<Prowlarr key>`。`add-indexers.py` 已自动补。

5. 🟠 **只在 Prowlarr 禁用索引器 ≠ cross-seed 不搜它。**
   现象：BTSCHOOL 在 Prowlarr `enable=false` 后，cross-seed 日志仍刷
   `Failed to reach http://prowlarr:9696/3/api: code 410, snoozing`。
   根因：cross-seed 只认自己的 `TORZNAB_URLS`，与 Prowlarr 的 enable 状态无关。
   → 彻底停用某站必须**从 `TORZNAB_URLS` 移除**，光改 Prowlarr 不够。

6. 🟡 **`drive --indexers` 只影响状态机记账，不限制 cross-seed 搜索范围。**
   cross-seed 按 `TORZNAB_URLS` **全站搜索**；`--indexers` 只决定状态机把
   "搜过"记到哪个站名下（`indexer_seen` / 周期计算）。两者别混。

7. 🟡 **Prowlarr 的 indexerId 会变**（§6.6 老坑，本会话再次验证）：
   文档快照里 id=1 是 SiteB，现在 id=1 是 **HDtime**。拼 `TORZNAB_URLS` 前**必须实时查 API**。

### 13.7 本会话结束时的状态快照

> ★ 本节是**唯一权威**状态表。下列为 2026-09-11 深夜（§13.11 收尾后）的最新值；
> 早于本次收尾的中间态见 §12.2。

| 项目 | 状态 |
|---|---|
| **磁盘** `.env` `DATA_DIRS` | ✅ **本地已切成 1 条**（农场）；**生产仍是 49 条**（待重建） |
| **磁盘** `.env` `TORZNAB_URLS` | ✅ **2 条**（HDFans `/2/api`、NanyangPT `/4/api`）——`/3` 早已移除，见 §10.5.10 |
| **容器内**环境变量 | ⚠ **旧** —— `DATA_DIRS` 49 条、`TORZNAB_URLS` 仍含已删的 `/3` → 请求吃 410 |
| cross-seed 索引器 | HDFans(active) / NanyangPT(active) / BTSCHOOL(已禁用，仍被请求→410) |
| 硬链接农场 | ✅ **已建成 475/475** 并独立复核（§10.5.7）；等价性已证（1888=1888，§10.5.9） |
| DC 包 | SEEDING **19** / PENDING 45 / UNMATCHED 51（待搜 ~96） |
| FRDS 包 | SEEDING **76** / PENDING 331 / UNMATCHED 79（待搜 ~410） |
| MBF 包 | UNMATCHED 4（HDFans 0 匹配，等换站） |
| `drive-loop.py` | ✅ 已写、语法通过、dry-run 通过、**真跑验证通过**（§13.8）；**调度已迁到 NAS**（DSM 任务计划，§14），⬜ 只差人工建任务 |
| ⑧ `.env` 生效自检 | ✅ **首次触发即命中真问题**（20:25 报 `/3/api` 410 ×49，见 §10.5.10） |
| 通知 / 告警 | Windows 侧 ✅ 已接好（`notify.py` + drive-loop 5 个钩子）；NAS 侧脚本 ✅ 已写并**全路径验证通过**，⬜ **还没部署**（§13.12.7）——在此之前一封邮件都发不出去 |

> ★ 表里「磁盘 ✅ / 容器 ⚠」这一对是本项目**头号复发坑**：`.env` 改了不会自动生效，
> `docker compose restart` **不重新注入环境变量**，必须 `up -d --force-recreate`。
> 消除它只需在 NAS 上跑一次 `sh nas-update-env.sh`（§13.11 末，**同时**办完切农场 + 清 `/3`）。

### 13.8 `drive-loop.py` 首次真跑验证（✅ 通过）

```bash
python scripts/drive-loop.py --once --indexers HDFans,NanyangPT --limit 50
```

**实测结果**（`scripts/drive-loop.log`）：

```
18:44:05  === drive-loop 启动：packs=['dc-collection','frds-top250-2024'] indexers=HDFans,NanyangPT limit=50
18:44:05  [第 1 轮] 跑包 dc-collection ...
19:08:37  [dc-collection] 发送完毕：成功 50 / 失败 0，退避等待 0.0 分钟（0 次）
19:14:35  [dc-collection] 回灌：搜过 158 / 匹配 19 / 新增做种 11 / 仍 SKIPPED 0
19:14:35  [第 1 轮] 计划 50 条，发出 50 条 | 原因：新增做种 11 部，站点健康 | 下次间隔 45 分钟
19:14:35  --once 模式：本轮完成，退出
```

**结论**：
- ✅ 一批 50 条发送正常，0 失败、0 退避
- ✅ **回灌带 qB 正确**：`新增做种 11` / `仍 SKIPPED 0` 算得准（这正是 §13.6 坑 1 的修复点）
- ✅ **反馈落到了决策**：`站点健康 → 下次间隔 45 分钟`（`next_sleep()` 正确）
- ✅ **DC 批 2 实际新增 11 部做种**

> ⚠ **另一个"别看终端"的实例**：后台运行时，任务输出文件只捕获到前 2 行
> （Python 的 stdout 被块缓冲），但 `scripts/drive-loop.log` 是**完整**的。
> 与 §12.5 那条"判断 drive 是否真跑，查日志别看终端"是同一类坑 ——
> **`drive-loop` 的真实进度一律以 `scripts/drive-loop.log` 为准。**

### 13.9 下一步（按优先级）

1. ~~从 `TORZNAB_URLS` 移除 BTSCHOOL `/3/api`~~ ✅ **不用做了 —— 文件侧早已正确**。
   生产 `.env` 里**只有 2 条**（`/2` HDFans、`/4` NanyangPT），`/3/api` 早就不在文件里。
   那些 410 是**容器陈旧**（磁盘对、容器里是启动时注入的旧 env），见 §10.5.10。
   于是 `add-indexers.py --remove` 不必写、不必跑，**只剩 `--force-recreate` 一步**。
2. ~~挂 Windows 计划任务~~ ✅ 已完成（`reseed-drive-loop`），但 **2026-09-11 深夜已迁到 NAS** ——
   Windows 侧批次会**静默消失**（`<StopOnIdleEnd>` 一动键鼠就 `TerminateProcess`，
   见 §14.2），且包装器行尾又踩了一次坑（§14.3）。现在跑在 DSM 任务计划上，
   ⬜ 只差人工建任务（§14.6 / README「把调度挂到 NAS 上」）。
   **Windows 任务请停用** —— 顺序上要先停，否则两边同时驱动 cross-seed 会撞 429。
3. **换一个站替换 BTSCHOOL**（用户计划中）——加站流程见 §13.3。
4. v3 硬链接农场：✅ **已建好并通过独立复核**（475/475，§10.5.7）+ ✅ **等价性已在
   真实数据上证明**（1888 = 1888，双向 0 差异，§10.5.9）。
   ⬜ 只差把 `.env` 的 `DATA_DIRS` 从 49 条切成 1 条 —— **与第 1 条同一次重建**，
   命令见 §13.11 末。
5. 编排器 `status` 子命令（§11.9）；IYUU 扩散（本范围外）。
6. **通知系统：NAS 侧部署**（§13.12）—— Windows 侧已接好，NAS 侧脚本已写并验证通过，
   剩三步人工操作（配 DSM SMTP → 拷脚本 → 建**三个** root 任务计划：
   排空 5 分钟 / 摘要 21:00 / **驱动跑批 15 分钟**，见 §14.6）。
   ⬜ 在此之前一封邮件都发不出去；事件会堆在 spool 里**不会丢**。

### 13.10 本会话末尾追加的三项改动（2026-09-11 深夜）

用户提出 ⑥⑦⑧ 三件事，全部落地：

**⑥ 账号安全：重搜周期 7 天 → 14 天**（`orchestrator/state.py` 的 `DEFAULT_CADENCE_DAYS`）

无人值守 = **每 7 天对每站重搜一轮**；约 1000 部单片 ≈ 每天 150 次查询/站、一年 5 万+ 次，
而且是**永不停止**的机器人流量。`delay=30` 只解决"快不快"，解决不了"像不像人"。
翻倍到 14 天查询量减半，代价只是未命中的多等一周。**账号 > 命中延迟。**
单个站想更保守：`--cadence "NanyangPT=30"`。详见 §11.6。

> 配套的人工动作：**定期看 Prowlarr 里各站的 Query Limit 消耗与账号状态** ——
> 这比看本地命中率更能提前发现风险。（**能不能自动化、以及自动化到哪一步为止**：见 §16.1）

**⑦ 硬链接农场**：见 §10.5.6（脚本 + 度量 + 安全设计 + 沙箱验证清单）。

**⑧ `.env` 生效自检**（`scripts/drive-loop.py` 的 `check_env_applied()`）

"改了 `.env` 忘了 `--force-recreate`"是本项目**头号复发坑**。现改为**由程序自己喊**：
`drive-loop` 启动时扫 cross-seed 日志**最近 2 小时**，命中下面两种句式就报警并打出修复命令：

```text
warn:  [webhook] Failed to reach <url>: request failed with code 410, snoozing until …
error: <url> returned 401 Unauthorized when fetching caps, check your apikey
```

- 410 = 该索引器在 Prowlarr 已删、容器里 `TORZNAB_URLS` 还留着；401 = apikey 不对；403 = 被禁用。
  三者多半是同一件事。
- ★ **必须卡时间窗**：容器重建成功后，历史 410 还躺在日志里，不卡窗口就会**永远报警**
  （狼来了），反而把真问题淹掉。窗口 2 小时 = 约 2~3 个批次。
- 只读日志**尾部 512 KB**（`info.current.log` 会长到几百 MB，全读不可接受）。

> ★ **同时修掉一个自己埋的隐患**：`batch_alive()` 原先把"状态文件没有心跳字段"
> 一律当成**残留**。但升级窗口里（旧进程在跑、新代码已在盘上）这会让计划任务
> **接管并并发再跑一批** → 双份 webhook → 撞 429 → 一次废掉几百条（§13.6 坑 4）。
> 改成区分「字段不存在」（保守当在跑，只影响升级那一批）与「字段过期」（判残留）。
> 这是**推理出来的、不是测出来的** —— 正好当时有个旧进程在跑，属于踩在线上修。

### 13.11 v3 农场落地 + 收尾（本会话）

§13.10 之后，本会话把 v3 从"脚本写好、沙箱验过"推进到**真实 NAS 上建成并复核**。

**做了什么**

| 步骤 | 结果 |
|---|---|
| ② NAS 上 `sh build-farm.sh`（dry-run） | `源直接子项合计 475（= 期望集 475）/ ★ 将要新建 475` —— 与预期**逐字一致** |
| ③ `sh build-farm.sh --apply` | `新建 475 / 已存在 0 / 源缺失 0 / 跨卷 0`，`EXIT=0`，耗时数分钟（~70 条/分） |
| 幂等复跑 | `将要新建 0 / 已存在 475` ✅ |
| 独立复核 | 475/475 名字双向对齐、零重名、**474 目录 + 1 散文件**、抽样 32 条共 **160 个文件全部同 inode 同尺寸** → 服务端真硬链接，**零数据复制** |

细节与实测表格见 **§10.5.7**（SMB 能建硬链接）、**§10.5.9**（等价性证明）。

**顺手修掉的两个 `build-farm.sh` 真缺陷**（都是"写了但没生效"型，不看跑不出来的）

1. **`SUDO` 是死配置** —— 头部有文档（第 32 行）、有赋值（第 61 行）、**从未被使用**。
   于是 chown 那步实际上从来没提权过。已接上：
   ```sh
   find "$dst" -type d -exec $SUDO chown "$OWNER" {} + 2>/dev/null || true
   ```
   ★ `$SUDO` **必须不加引号** —— 要让它按词拆分成多个参数交给 `find -exec`。
   从 Windows/SMB 跑时 `sudo` 不存在 → 失败被 `|| true` 吞掉，
   结果是"沿用服务端按登录用户给的属主"，不影响正确性。

2. **`-h` 硬编码行号** —— 原来是 `sed -n '2,55p' "$0"`：会**漏掉头部收尾行**，
   且任何一次头部编辑都会让它静默腐化（没有报错，只是少印几行）。
   改成自维护、不依赖行号：
   ```sh
   -h|--help) awk 'NR>1 && /^set -eu/{exit} NR>1{print}' "$0"; exit 0 ;;
   ```
   （`NR>1` 跳过 shebang；遇到 `set -eu` 即止 —— 正好是头部的边界。）

**发现并堵上一个密钥泄漏风险**

收尾时发现 `.env.bak.20260911-204109`（**含真实密钥的完整 `.env` 副本**）
在 `git status` 里是 `??` **未跟踪裸文件**。根因：`.gitignore` 里的 `.env`
是**精确匹配**，拦不住带后缀的备份。已加规则并验证：

```
.env.bak.*
```

```console
$ git check-ignore -v .env.bak.20260911-204109
.gitignore:8:.env.bak.*	.env.bak.20260911-204109
```

> ★ 教训是通用的：**任何"把密钥文件复制一份"的备份流程，都要单独加 gitignore 规则。**
> 备份不是"同一个文件"，精确匹配的规则不会管它。

**发现并堵上一个会误导人的标签 bug（`prowlarr#N` 里 N 不是表行号）**

`drive-loop` 启动自检报了一句：

```text
⚠ cross-seed 有 1 个 active 索引器**拉不到名字**（prowlarr#4）—— 多半是该站返回错误（410/403/CF）
```

按 `TORZNAB_URLS` 的写法（`/4/api` = NanyangPT）读，这句话像是说 **NanyangPT 挂了**。
但查 `error.current.log` —— **`/4/api` 一次都没出现过**，最近的 caps 失败是 `/2/api`（10:27）
和 HDFans（15:59）。直接查 cross-seed 的 `indexer` 表才看清：

| 表 `id` | `url` | `name` | `status` |
|---|---|---|---|
| 1 | `/1/api` | *(空)* | RATE_LIMITED |
| 2 | `/2/api` | HDFans | RATE_LIMITED |
| **4** | **`/3/api`** | ***(空)*** ← 真正拉不到名字的是它 | UNKNOWN_ERROR |
| **5** | **`/4/api`** | **NanyangPT (南洋)** ✅ | *(空，健康)* |

**`indexer.id` 是 cross-seed 的自增行号，不是 Prowlarr 的索引器号。**
`read_crossseed_db` 用 `f"prowlarr#{iid}"` 拼标签，于是**行号 4** 被打成 `prowlarr#4` ——
恰好与"Prowlarr 的 #4"撞名，指向了完全无辜的 NanyangPT。

> ★ 这个 bug 藏了很久，因为**行 id=1 恰好对应 `/1/api`**，偶然是对的。
> 真正拉不到名字的是 `/3/api`（BTSCHOOL）—— 和那 49 次 410 是同一件事（§10.5.10）。

**更糟的是它和既有契约冲突**：`state.py` 里早就有一个 `normalize_indexer()`，
把 URL `.../N/api` 映射成 `prowlarr#N`（**用的是 URL 里的 N**）。
而 `read_crossseed_db` 同时在写 `snap.alias[url] = label` ——
于是 `alias[".../3/api"]` 给的是行号版 `prowlarr#4`，正则回退却给 `prowlarr#3`。
**同一个索引器两条路两个标签**，正是 `normalize_indexer()` 文档里警告的那种"一个站变成多个成员"。

**修法**：新增 `_fallback_indexer_label(row_id, url)` —— 优先从 **URL** 取号
（复用既有的 `_INDEXER_URL_ID`），取不到才退化成 `prowlarr#row<id>`，
**明确标成行号、不冒充 Prowlarr 号**。三处调用点统一：

- `read_crossseed_db` 的 `indexers` / `indexer_status` / `indexer_label`
- `read_indexer_backoff`（顺带把查询加上 `url` 列，原来没取）
- `idx_names.get(iid, ...)` 的兜底也改成 `prowlarr#row{iid}`

**修完实测（拿生产 DB 跑）**：

```text
active 索引器标签: ['HDFans', 'prowlarr#3', 'NanyangPT (南洋)']
alias:  .../3/api -> 'prowlarr#3'     ← 与 normalize_indexer 一致了
        .../4/api -> 'NanyangPT (南洋)'
```

自检现在报 `prowlarr#3` —— 指对了站，也指对了人。

**顺带修掉一个 `DeprecationWarning`**：`drive-loop.py:149` 的
`re.split(r"[(（]", n, 1)` 把 `maxsplit` 按位置传了。改成 `maxsplit=1`
（用 `python -W error::DeprecationWarning` 验证已消除）。

> 教训：**日志里带 `#数字` 的标签，一定要写清是"哪套编号"。**
> 这个项目同时存在三套编号 —— Prowlarr 界面序号、`TORZNAB_URLS` 的 `/N/api`、
> cross-seed 的 `indexer.id` —— 打印时用一个、脑子里想另一个，就会去查错的站。

**提交**

| 提交 | 内容 |
|---|---|
| `c1e3f9e` | `build-farm.sh` 加 `--map` 路径翻译 + 实测推翻「SMB 建不了硬链接」；农场已建成 475/475 |
| `9252411` | 切换前准备：`DATA_DIRS` 49→1 + 真实数据上的等价性证明 + 两个判据踩坑记录 |

**留下的唯一人工动作**（SSH 端口 closed，必须由用户在 NAS 上跑）

```bash
cd /volume2/docker_ssd/prowlarr_cross-seed_autohardlink
sh nas-update-env.sh --dry-run     # 先看：DATA_DIRS 49 条 → 1 条
sh nas-update-env.sh               # 改 + --force-recreate + 闭环回读校验
```

⚠ 会中断 cross-seed，**务必等当前批次跑完**。
重建后确认三件事：`drive-loop` 索引器自检变绿、`/3/api` 的 410 消失、searchee 数仍是 **1888**。
回滚：`cp -p .env.bak.<时间戳> .env` 后重建。

> **本会话没有再踩新坑** —— 因为踩过的都记在 §10.5.7 / §10.5.9 里了：
> 顶层目录 inode 必然不同（硬链接目录非法）、农场就是为了换根所以不能比绝对路径。
> 这两条都是**判据写错**而不是系统缺陷，记下来是为了别下次又写一遍。

---

### 13.12 通知 / 告警系统（本会话）

**背景**：整个系统原先只会写日志。⑧ `.env` 生效自检抓到 410 时的动作是
"打印修复命令然后继续"—— 没有人会看到。同理"本批新增做种 11 部"这种好消息也只有翻日志才知道。
**没有通知的"无人值守"，实际是"无人知道"。**

用户选定：**通道 = NAS 侧发（DSM 任务计划）**，**范围 = 坏消息 + 每日摘要**。

#### 13.12.1 架构：为什么凭据必须留在 NAS

```
drive-loop.py ──写纯文本事件──▶ //NAS/…/notify/spool/*.txt ──▶ notify-spool.sh ──▶ 邮箱
   (Windows，零凭据)                 (SMB 共享目录)                (NAS，读 DSM 自己的 SMTP)
```

用户不想在 Windows 上存邮件凭据。所以 `notify.py` **一行凭据都没有** ——
不 import smtplib、不读密码、不碰 SMTP，只往共享目录丢文件；
`notify-spool.sh` 在 NAS 上跑，读 **DSM 自己的** `/etc/ssmtp/ssmtp.conf`。
凭据从没离开过 DSM，也就没必要出现在仓库、命令行或聊天里。

**★ 代价必须说清：告警链路依赖 NAS。NAS 挂了就发不出去 ——
而这恰恰是最该被告知的时刻之一。**
这是"发信方不能是被监控对象本身"的一般性问题的具体表现。
本方案的缓解不是加一条链路（那会引入第二份凭据，正是用户不想干的），
而是**把每日摘要同时设计成心跳**：

* 「该来的日报没来」本身就是 NAS / 任务计划故障的信号；
* 摘要里写明「最近一次批次记录是几小时前」，用来区分「NAS 挂了」和「主机没开机」；
* 摘要末尾报告**通知链路自己的健康状况**（发信方式 + spool 积压条数）——
  积压持续 >0 是唯一一个"只能靠摘要告诉你"的故障（那些告警你根本没收到）。

#### 13.12.2 探针推翻了原设计（实测 > 假设）

写第一版时按常规做法调现成的 `sendmail`/`ssmtp`。**探针结果否定了它**：

| 探测项 | 结果 |
|---|---|
| `/usr/sbin/ssmtp`、`/usr/sbin/sendmail`、`/usr/bin/sendmail`、`/usr/sbin/msmtp`、`/usr/bin/mail` | **全部 MISS** —— 这台 NAS 上一个发信程序都没有 |
| `/etc/ssmtp/ssmtp.conf` | **OK 存在** |
| `/usr/bin/python3` | **OK 3.8.15** |
| 探针身份 | `uid=1026(iSunker)`，**不是 root** |

于是发信层重写成 **`python3 + smtplib`** 直接和 SMTP 服务器对话，配置仍从同一个
`/etc/ssmtp/ssmtp.conf` 读（`mailhub` / `AuthUser` / `AuthPass` / `root`），
按端口决定 `SMTP_SSL`（465）还是 `SMTP + starttls`。
ssl/smtplib/email 都是标准库，NAS 上现成的 python3 够用。

> ★ 探针身份那条还牵出一个**必须写进文档的前提**：探针以 uid 1026 跑，
> 而 `ssmtp.conf` 的检查用的是 `[ -f ]`（**只测存在，不测可读**）。
> 所以**任务计划的用户必须选 root** —— 否则脚本连配置文件都打不开。
> 这条已写进脚本头部注释、README 和 `--selftest` 的报错文案里。

#### 13.12.3 验证时抓到的三个真缺陷

**(a) 🔴 429 被误判成「.env 未生效」——会把人骗去白重建一次容器**

`check_env_applied` 的正则在真实日志上匹配**两种完全不同的消息**：

```
warn: Failed to reach http://prowlarr:9696/3/api: request failed with code 410, snoozing until …
warn: Failed to reach HDFans: request failed with code 429 due to rate limiting, snoozing until …
```

第一种是**配置没生效**（该重建容器）；第二种是**限流**，是周期性的正常现象，
退避逻辑自己会处理，跟 `.env` 毫无关系。
`(?P<url>\S+?)` 连站名一起匹配，所以 429 也被捞了进来 ——
推出去就是一封标题写着「**.env 未生效：HDFans 返回 429**」的邮件。

在只有日志的年代这只是条误导性警告（没人看）；**一旦接上邮件就成了真骚扰**。
修法：加 `STALE_ENV_CODES = {410, 401, 403}` 白名单，429 直接跳过（记 debug）。

> 这个缺陷是**接线之后第一次拿真实数据跑**才暴露的 —— 单测用合成日志不会发现，
> 因为合成日志里只有你想到的那种形状。

**(b) 🔴 摘要把告警数了两遍 —— 发信坏掉时一天 576 行垃圾**

`do_drain` 在第一个循环里对**每个**文件调 `log_event`，包括那些
因为发不出去而要**留在 spool** 的告警。下一轮排空（5 分钟后）再来一遍又记一次。
实测摘要打出 `告警 : 4`（实际只有 2 条）。

发信链路正常时看不出来（告警发完就归档了，只记一次）；
**一旦发信坏掉，每条告警每 5 分钟重记一行，一天 576 行**，摘要里的告警数直接变垃圾数字。

修法：`log_event` **只在事件真的投递出去（归档）时**才调用。
没送出去的积压由摘要的「通知链路」一节单独报 —— 而且那个数字更该被看到。

**(c) 🔴 batch 事件的冷却会让摘要少算**

`Notifier._cooled` 原本对所有事件生效。但 batch 事件的 key 是 `batch:<包名>`，
同一个包在 12 小时内会跑好几批 —— **冷却会把它们全吃掉**，
而摘要正是靠 log 里的 batch 行数统计"最近两次运行窗口的批次"。

修法：**冷却只对 alert 生效**。语义也更对 ——
冷却要解决的是「同一个**未修复的**问题反复吵你」（如"容器 env 陈旧"），
而「本批新增做种 11 部」每批都是**新信息**，冷却它没有意义。
冷却状态文件也相应只记 alert 的 key（否则会白长）。

#### 13.12.4 其它已处理的可移植性/工程问题

| 问题 | 处理 |
|---|---|
| DSM 的 `date` 未必支持 GNU `-d`（日期运算） | 摘要取"最近两个日志文件"改用 `ls -1 *.tsv \| sort \| tail -2` |
| 管道里的 `while` 跑在**子 shell**，计数器传不出来 | 告警发送循环改用 `< file` 重定向 —— `n_sent` / `n_failed` 才能进汇总行 |
| `-h` 硬编码行号会静默腐化 | 改用 `awk 'NR>1 && /^set -eu/{exit} NR>1{print}'`（与 `build-farm.sh` 同一手法，§13.11） |
| 通知失败绝不能拖垮跑批 | `Notifier.emit` 吞掉**所有**异常，只打一行 `投递通知失败（忽略，不影响跑批）` |
| `prowlarr#N` 的 N 是哪一套编号 | 告警正文里显式写明"是 `TORZNAB_URLS` 里的那个，**不是** Prowlarr 界面序号"（§13.11 的标签 bug 教训） |
| git-bash 会把 POSIX 路径参数改写成 `\tmp\x` | 记进 README；测试里改用 `D:/tmp/...` |

#### 13.12.5 验证证据（全部在真实数据/真实脚本上跑过）

| 验证 | 结果 |
|---|---|
| 单测（26 项断言，临时脚本已删） | 全通过：格式、冷却、`--no-notify`、写失败不抛异常 |
| **跨边界端到端**：真实 `check_indexers` + `check_env_applied` 写文件 → NAS 侧脚本解析 | 事件格式互认，标题/正文/metrics 全部正确解析 |
| **真发信路径**（用假 mailer 顶替 SMTP） | 2 封告警真发出去（`To:` / `Subject:` 正确），batch 归档 |
| 重复排空 ×2 | `告警 0 条`，流水账**仍是 3 行**（不重复记账）✅ |
| 摘要数字 | `批次 : 1 / 告警 : 2`（修复前是 4） |
| 发信链路坏掉时 | 2 条告警**留在 spool**（不归档=不丢），摘要报 `spool 积压: 2 条告警` + 修复指引 |

> 测试脚本只存在于临时目录并已删除；测试用假 mailer（`MAILER_CMD` 覆盖项）——
> 这个覆盖项本身也是有用的功能（NAS 上发信程序不在默认路径时用得上）。
> **★ 测试期间发现测试自己会污染真实的 `scripts/.notify.state`** ——
> 残留一个 `consec-abort` 进去，真告警会被静默冷却 12 小时。已改成重定向到临时目录，
> 并在收尾时清理。

#### 13.12.6 几个刻意的设计取舍

* **事件文件用纯文本而非 JSON** —— NAS 侧是 POSIX sh，解析 JSON 要么依赖 python3、
  要么塞个解析器进去。改成一文件一事件的文本头，`sed`/`grep` 就能读，零依赖。
* **写入用 `tmp` + `os.replace`（同目录内原子 rename）** —— 否则 NAS 侧轮询
  可能读到写了一半的文件。
* **告警逐 `(url, code)` 一条，不合并** —— 每个都是独立可修的问题，
  分开去重才能在"修好一个、还剩一个"时继续提醒。
* **`MAX_PER_RUN`（12）与 `MAX_MAILS_PER_RUN`（5）双层限流** —— 超过就把告警合并成一封，
  避免一次喷一屏。
* **告警冷却 12 小时** —— 一个持续存在的问题每天最多提醒 2 次。
  "每 15 分钟一封"不是告警，是骚扰，结果是被无视。

#### 13.12.7 剩下的（必须人在 NAS 上做）

Windows 侧已接好；NAS 侧脚本已写好并在**真发信路径上验证通过**，但还没部署。
⬜ 在此之前一封邮件都不会发出去（事件会一直堆在 spool 里，**不会丢**）。

1. DSM → 控制面板 → 通知 → 电子邮件：配成「**自定义 SMTP 服务器 + 应用专用密码**」
   （Gmail 的「登录(OAuth)」方式拿不到可用凭据，这条路不通）。
2. 把 NAS 侧脚本同步过去 —— ✅ **已加进 `deploy.sh` 白名单**
   （`scripts/notify-spool.sh::notify/notify-spool.sh` 等两条），
   `deploy.sh --apply` 即可推送；`notify.conf`（含收件人邮箱）**不在白名单**，
   属生产独有内容，与 `.env` / `prowlarr/` 同样受白名单原则保护。
3. `sh notify-spool.sh --selftest` → `--test-mail` 确认真能收到。
4. DSM 任务计划建三个任务，**用户都选 root**：

   | 任务 | 频率 | 脚本 |
   |---|---|---|
   | 排空 spool | 每 5 分钟 | `sh notify/notify-spool.sh` |
   | 每日摘要 | 每天 21:00 | `sh notify/notify-spool.sh --digest` |
   | 驱动跑批 | 每 15 分钟 | `sh drive-loop/run.sh`（见 §14） |

   ★ **都不要勾「发送运行详情」**。原先这里写的是「都勾上」，那是错的：
   排空任务 5 分钟一次 = **288 封/天**，跑批 15 分钟一次 = **96 封/天**，
   一天近 400 封信会把真正的告警淹掉 —— 而「告警发得出来」正是这套通知
   存在的唯一理由。要看单次结果就 ssh 上去跑一次，或直接看
   `notify/notify.log` / `drive-loop/attempts.log`（都经 SMB 可读）。

详见 README「通知 / 告警」一节。

---

## 14. 驱动层从 Windows 迁到 NAS（2026-09-11 深夜）

> **一句话**：`drive-loop` 的调度从 Windows 计划任务搬到了 **NAS 的 DSM 任务计划**。
> 起因是 Windows 侧批次**静默消失**；查下去发现是**两个独立的原因**，
> 其中一个是本会话自己改出来的。代码与状态库已就位，
> **只剩「在 DSM 上建任务」这一件人工操作**（步骤见 README「把调度挂到 NAS 上」）。

### 14.1 症状：批次"跑了，但什么都没发生"

`drive-loop.log` 里存在**有启动、没收尾**的批次。最干净的一例：

```text
2026-09-11 19:41:11,932 [INFO] [--once] 跑包 dc-collection（第 1/2 个）
        ← 此后该进程再无任何输出
2026-09-11 19:50:44,606 [INFO] === drive-loop 启动 … ===      ← 下一轮
2026-09-11 19:50:44        （没有报"上一批仍在运行"）
```

判读要点：**如果 19:41 那个进程还活着，19:50 那一轮应当报"上一批（pid …）仍在运行，跳过本轮"**
（20:25 / 20:40 / 22:25 / 22:40 几轮都报了）。它没报 → 19:41 的进程**已经没了**。
而且它没有留下任何收尾：没有 traceback、没有 `异常`、没有 `finally` 写的状态收尾。

> **这是判据，不是猜测**：Python 里异常/崩溃**一定会**留下痕迹。
> 能造成"整棵进程树被抹掉、连日志缓冲都来不及刷"的，只有 `TerminateProcess`。

### 14.2 原因 A：`<StopOnIdleEnd>true</StopOnIdleEnd>`

实时查任务定义（不是回忆，是当场读出来的）：

```powershell
schtasks /Query /TN "reseed-drive-loop" /XML
```

```xml
<StopOnIdleEnd>true</StopOnIdleEnd>
<DisallowStartIfOnBatteries>true</DisallowStartIfOnBatteries>
<MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
<Command>D:\Projects\dabaochaibaozuozhongxiangmu\reseed-toolkit\scripts\drive-loop-once.cmd</Command>
```

`StopOnIdleEnd` 的含义是：**机器一旦"不再空闲"（你碰鼠标/键盘），Windows 直接
`TerminateProcess` 这个任务实例。** 这精确地解释了 14.1 的形态 —— 静默、无痕、
连 `finally` 都不执行、状态文件里 `running_pid` 永远挂着，于是之后每一轮都
"上一批仍在运行" 空转下去。

这是一个**设计上就与"无人值守长跑"互斥**的设置，而这个任务恰恰是 24 分钟一批的长跑。
换句话说：只要这台机器上有人，这个任务就永远跑不完一批。

> ★ 诚实标注：`StopOnIdleEnd=true` 是**读出来的事实**；把它与 14.1 那些
> 未收尾批次**因果关联**是**推断**（证据是时间点与"无痕"这一形态吻合）。
> 推论不影响结论 —— 下面 14.3 的迁移方案把这个问题整个绕开了。

### 14.3 原因 B：`.cmd` 包装器是 LF 行尾（★ 本会话自己弄坏的）

这才是 **22:55 之后任务彻底跑不起来**的直接原因，而且**是本会话 22:43 那次
"给包装器加留痕"的修改引入的**。必须原样记下来。

**观测到的证据**（`scripts/drive-loop.attempts.log` 全文只有两行）：

```text
[2026/09/11 周五 22:55:02.14] exit=9009
[2026/09/11 周五 23:10:02.11] exit=9009
```

`scripts/drive-loop.task.err` 尾部：

```text
'""' 不是内部或外部命令，也不是可运行的程序
或批处理文件。
'""' 不是内部或外部命令，也不是可运行的程序
或批处理文件。
```

**三个信号拼在一起，指向同一个解释：**

1. `9009` = cmd.exe 的**"命令找不到"**退出码；
2. `'""'` = 它试图执行的命令名**字面上是两个引号** —— 即 `%PY%` 和 `%SCRIPT%`
   **都展开成了空**，整行退化成 `"" "" --once …`；
3. `.cmd` 第 55 行 `echo … start >> attempts.log` 是**无条件执行**的，
   可 `attempts.log` 里**只有 `exit=` 没有 `start=`**。

**根因：批处理文件是 LF-only 行尾，cmd.exe 解析错位。**

cmd.exe 不是逐行读批处理文件，而是**按字节块读取并回退重定位**。
LF-only 会让它的字节偏移记账错位，结果是**从某一行中间开始执行** ——
于是 `REM` 注释里的普通英文单词被当成命令跑，而它前面那些 `set` 也就全丢了。

`scripts/drive-loop-once.cmd` 换行统计（`git HEAD` 版同样是 LF-only，
说明这个隐患**早就在**，只是那时文件短、偏移恰好没踩中）：

```text
修复前  工作区 CRLF=0   LF=59        ← 会坏
        git HEAD CRLF=0 LF=37        ← 这个长度下侥幸能跑
修复后  工作区 CRLF=59  LF=0         ← 正常
```

**受控 A/B（同一份内容，只差行尾）**：

| | attempts.log | stdout |
|---|---|---|
| CRLF | `start` + `exit=0` | 0 B |
| LF | **只有 `exit=0`，没有 `start`** | 511 B 乱码 |

LF 版的乱码正是注释文字被当命令执行：

```text
is:       cannot open `is' (No such file or directory)
expanded: cannot open `expanded' (No such file or directory)
by:       cannot open `by' (No such file or directory)
cmd.exe:  cannot open `cmd.exe' (No such file or directory)
at:       cannot open `at' (No such file or directory)
RUN:      cannot open `RUN' (No such file or directory)
time,:    cannot open `time,' (No such file or directory)
so:       cannot open `so' (No such file or directory)
the:      cannot open `the' (No such file or directory)
```

↑ 这九个词**按顺序**就是包装器注释里那句
"`%USERPROFILE%` **is expanded by cmd.exe at RUN time, so the** task definition itself stays pure ASCII."
—— 铁证。

**修复**：`scripts/drive-loop-once.cmd` 转成 CRLF。转换后桩测通过
（`attempts.log` 得到 `start` + `exit=0` 两行，被替换的那行也执行到了）。

> ★ **同一类问题一次清干净**：顺手体检了全仓库的脚本行尾，另外两个也要修 ——
> `deploy.sh`（CRLF=168）和 `scripts/run-batch.sh`（CRLF=298）都是 **CRLF 的 bash 脚本**。
> 在 Git Bash 里跑没事，但一旦拿到 WSL / NAS 上就是 `\r: command not found`。
> 两者都已归正成 LF。
>
> **教训**：早前用 `grep -c $'\r'` 查行尾，得到"CRLF=0，没有行尾问题"的结论 ——
> **方向反了**。CRLF=0 只说明"是 LF"，而 `.cmd` 要的恰恰是 CRLF。
> **按扩展名判定期望行尾**（`.cmd`/`.bat` → CRLF，`.sh`/`.py` → LF），
> 或用字节级 `b.count(b"\r\n")`，别用一句通用判断。

### 14.4 做了什么：迁移到 NAS

结论是**别再修 Windows 侧了** —— 这套东西的每一条依赖本来就都在 NAS 上
（cross-seed、qB、Prowlarr、媒体库），Windows 只提供一个调度器，
却为此引入 SMB 往返 + `<StopOnIdleEnd>` + 非 ASCII 用户名 + 行尾四个坑。

**代码侧（已完成）**

| 改动 | 文件 |
|---|---|
| 未来注解导入（NAS 系统 python 是 3.8.15，`str \| None` 语法否则在**定义期**就 `TypeError`，且那时 `logging` 还没配置 → **零日志输出**） | `scripts/drive-loop.py` |
| 路径探测 `CROSSSEED_DIRS`：**先 NAS 原生、再 UNC**（一份代码两边都能跑，不切参数） | `scripts/drive-loop.py` |
| spool 同样的候选探测 `SPOOL_CANDIDATES` | `scripts/notify.py` |
| **NAS 侧入口 `run.sh`**（DSM 任务调它）：钉死 `TZ`/`PYTHONIOENCODING`，写 `attempts.log` | `scripts/drive-loop-nas.sh` → `drive-loop/run.sh` |
| 白名单新增 6 条 | `deploy.sh` |

**为什么入口那层还要单独记一份 `attempts.log`**：`drive-loop.log` 只收 `logging` 的输出。
如果 python **自己起不来**（版本不对 → `SyntaxError`/注解 `TypeError`），`logging` 根本没配置，
`drive-loop.log` 一个字节都不会写 —— 表现就是"任务跑了但什么都没发生、也没有任何报错"。
**这正是 14.1 那个坑的形状**，所以 shell 这层必须自己留痕。三个信号分得很清楚：

| `attempts.log` | 含义 |
|---|---|
| 没有 `start` 行 | 任务压根没被触发（计划建错 / 没启用） |
| 有 `start` 无 `exit` | 进程树被强杀（`TerminateProcess`） |
| 有 `exit` 且 ≠ 0 | 它自己出错了（看 `drive-loop.log` 和退出码） |

**状态侧（已完成）**：`hlink/state.db` 的 605 部已迁到 `<compose>/drive-loop/hlink/state.db`，
`local_roots` 已从 UNC 归一成 NAS 原生路径（用 SQLite 快照 API 读，避免在 Windows 任务
可能正在跑批时读到撕裂状态）。回读校验 pack=3 / movie=605 / attempt=1350。

**为什么是 `--once` + 任务计划，而不是常驻容器**：`--once` 的跨进程节流带
**心跳超时接管**（`HEARTBEAT_STALE_SEC=600`）—— 上一批卡死 10 分钟后，
下一轮会自动接管。常驻进程卡死就没人接管了。见 §13.5。

### 14.5 排查表（NAS 侧）

| 症状 | 先看 | 多半是 |
|---|---|---|
| 完全没有 `start` 行 | DSM 任务是否启用、计划是否"每 15 分钟"、脚本路径 | 任务没被触发 |
| 有 `start` 无 `exit` | 是否有别的进程在抢 | 进程被强杀（NAS 上少见，多见于 Windows） |
| `exit=127` | `/usr/bin/python3` 在不在 | `run.sh` 找不到解释器或脚本 |
| `exit` ≠ 0 且有 traceback | `drive-loop/scripts/drive-loop.log` | python 层错误，**首先怀疑解释器版本** |
| `exit=9009`（Windows） | 包装器行尾 | `.cmd` 不是 CRLF —— 见 §14.3 |
| 每轮都"跳过" | `drive-loop.log` | 距上批不足 30 分钟 / 上一批的心跳还没过期 |
| 邮件里全是 `410` | Prowlarr 的 indexerId | **改了 `.env` 没 `--force-recreate`**（§13.10 ⑧） |

### 14.6 下一步（人工）

只剩三件必须你亲手做的事，详见 README「把调度挂到 NAS 上」：

1. **先停用 Windows 计划任务** `reseed-drive-loop`
   （`schtasks /Change /TN "reseed-drive-loop" /DISABLE`）——
   顺序很重要，两边同时驱动 cross-seed 会撞 429，一次能废掉几百条；
2. DSM 建任务，**第一次带 `--dry-run`**；
3. 手动跑一次，确认 `attempts.log` 有 `start` + `exit=0`，然后去掉 `--dry-run`。

> ✅ **已在 NAS 上实测通过（2026-09-11 23:27）**：`sh drive-loop/run.sh --dry-run`
> 在真机上跑通，`attempts.log` 得到

```
[2026-09-11 23:27:42] start  py=/usr/bin/python3
[2026-09-11 23:27:43] exit=0
```

> —— **`start` 行在了**（Windows 侧一直缺的正是这行），退出码 0，时间是本地时间
> （`TZ=Asia/Shanghai` 生效），`drive-loop.log` 落在 `drive-loop/scripts/` 下
> （`ROOT = HERE.parent` 的假设成立）。旁边生成了 `__pycache__/*.cpython-38.pyc`
> —— **解释器就是 CPython 3.8**，这条原先只是从文档抄来的假设，现在坐实了。
> `from __future__ import annotations` 确实是必需的（去掉会在 import 阶段静默崩）。
>
> 万一将来对不上（比如 DS 大版本升级换了 python），症状同样会是「静默」，
> 按 README「NAS 侧一次性配置」里列的后备方案换解释器即可。

### 14.7 ★ 电脑端退役（2026-09-12 下午）—— 从"停用"走到底

**为什么当初只 `DISABLE` 而没有删**：迁移当天（09-11 深夜）的目标是"先别两边同时跑"，
`DISABLE` 就够了；留着是**回退余地** —— 万一 NAS 侧跑不起来，还能一分钟内切回去。
所以 §14.6 第 1 条写的是"先停用"，措辞刻意留了余地。

**什么时候余地不再需要**：2026-09-12 上午，NAS 侧连续几批都正常
（`attempts.log` 有 `start` + `exit=0`、跨进程节流真的在拦、
「新增做种 36 部 🎉」这类业务输出也对）。**能回退的价值 < 半退役状态的代价**，
于是走到底。

**代价具体是什么**（这是决定删的理由，不是"清理癖"）：代码里到处是"Windows 也能跑"
的痕迹，留着会让下一个人以为那条路还活着 —— 然后照着去配、去调、去踩已经踩过的坑。
典型的就是 `CROSSSEED_DIRS`：它**看起来**只是个路径列表，
但它承载的语义是"同一份代码两边都能跑"，这个语义在只有 NAS 一个环境时**已经不存在了**。
路径列表本身没错，错的是它暗示的世界。

**① 删（真删）**

| 文件 | 为什么能删 |
|---|---|
| `scripts/drive-loop-once.cmd` | 计划任务的入口，任务本身已停用；代码在 git 历史里，回退拿得回来 |
| `scripts/drive-loop.{log,attempts.log,task.err}` | PC 侧运行时产物，跑批侧已经全搬到 NAS |
| `scripts/.drive-loop.state`、`.notify.state` | PC 侧的节流/冷却状态；NAS 侧各有一份自己的 |

★ 删之前**逐个看过内容**（都是 09-11 的、含着 `\\iSunker-DS423\…` 和 GBK 乱码的 PC 侧记录），
不是只看文件名就删 —— `attempts.log` 里那份 `exit=9009` 正是 §14.3 那个坑的物证。

**② 注释（不删代码）**

`drive-loop.py` 的 `CROSSSEED_DIRS` UNC 兜底、`pid_alive()` 的 `tasklist` 分支
（连 `import subprocess`）、`notify.py` 的 `SPOOL_CANDIDATES` UNC 兜底。
统一用可 grep 的标记 `[电脑端已退役 2026-09-12]`。

★ 注释掉的代码值钱的不是代码，是它旁边那句话 —— 两条都**反直觉**：
* `os.kill(pid, 0)` 在 POSIX 上是"发 0 号信号探测存活"（标准做法），
  搬到 Windows 上**会真的把进程杀掉**。所以 `pid_alive()` 必须留 `tasklist` 的那支。
* UNC 兜底在 NAS 上**不报错**：它会绕一圈 SMB 连回自己 —— 只是慢，而且难查。
  这正是"多一条候选路径 = 多一个静默降级点"的实例。

**③ 没删（明确保留）**

* **`deploy.sh`** —— 唯一还从电脑发起的操作（把代码推到 NAS）。
* **`scripts/run-batch.sh`** —— 手动命中率试跑工具，不是调度的一部分。
* ⚠ `scripts/nas-update-env.sh` 仍是**手工放在** `<compose>/nas-update-env.sh` 的，
  **不在 `deploy.sh` 白名单里**（和 `build-farm.sh` 退役前的情况一样）。
  这条**没修** —— 它是给一次性 `.env` 迁移用的，用完就不该再跑，进白名单反而危险。

**④ 验证**：`ast.parse` 三个改动文件全过；四个测试套件
（`test_quota_trend` / `test_next_sleep` / `test_backoff` / `test_once_gate`）全过；
`drive-loop.py --help` 能跑；`deploy.sh --apply` 同步后在 NAS 副本上复跑正常。

**⑤ ✅ 已结案（2026-09-12 中午）：计划任务已删除。** 记录一下过程里的坑。

我这边（普通权限）试删，返回「拒绝访问」：

```
schtasks /Delete /TN "reseed-drive-loop" /F     # → 错误: 拒绝访问。
```

**这个报错方向很容易看反**，值得写下来：

| 报错 | 含义 |
|---|---|
| `拒绝访问` | **没提权** —— 换管理员窗口重跑就行，任务还在 |
| `找不到指定的文件` / `ObjectNotFound` | **已经不存在了** —— 这是**成功信号** |

用户随后敲 `Unregister-ScheduledTask` 得到 `ObjectNotFound`，一度看着像"删不掉"，
实际是**之前那条 `schtasks /Delete` 已经生效了**。两把工具独立复核确认：

```
schtasks /Query /TN "reseed-drive-loop"        → 错误: 系统找不到指定的文件。
Get-ScheduledTask | ? TaskName -like '*reseed*' → （空）
```

对照：同日 **11:45** 同一条 `schtasks /Query` 还能查到（`模式: 已禁用`、
`下次运行时间: N/A`），全量 CSV 扫描确认**本机 reseed 相关任务只有这一条**。

★ 教训：**先 `Query` 再 `Delete`**。少了这一步，就得靠猜"这条报错到底是在说权限还是说存在"。

**⑥ `.probe_done_<pid>` 之谜（已结案）**：`//iSunker-DS423/docker_ssd` 根和
`//iSunker-DS423/video` 根各有 5 个 0 字节的 `.probe_done_<pid>`
（2026-09-11 21:20~21:30，两处**同名且 mtime 精确到纳秒一致**）。

**查了一整轮全是错的**：仓库搜不到、git 历史搜不到、`docker_ssd` 下所有脚本搜不到、
本地 `D:\Projects` + `D:\tmp` 全量搜（含被 gitignore 的）也搜不到；从 PID 反推
`21293` 是奇数（Windows 的 PID 恒为 4 的倍数）⇒ 判定「NAS 上的、非本项目的进程」。
**这个判定是错的** —— 错在只搜了**当前**的代码，而它来自一段**只存在于聊天记录里、
从未进过仓库**的一次性探针脚本。

真凶是我们自己：09-11 晚为查「notify 的 spool 到底能写哪个目录」，我给用户写了一段
DSM「用户定义的脚本」探针，用户挂在**任务计划**上跑（21:20 / 21:25 / 21:30 正是 5 分钟一档，
21:27、21:28 两次是手工点）：

```sh
for d in /volume1/docker /volume1/video /volume2/docker_ssd; do
  if touch "$d/.probe_$$" 2>/dev/null; then
    mv -f "$d/.probe_$$" "$d/.probe_done_$$"
    mv -f "$d/.probe_done_$$" /dev/null 2>/dev/null   # ★ 就是这行
    rm -f "$d/.probe_$$"
  fi
done
```

★★ **`mv -f 文件 /dev/null` 不是删除。** `mv` 是拿这个文件去**替换** `/dev/null`
这个字符设备节点 —— 非 root 必然失败，而 `2>/dev/null` 把错误吞得干干净净，
文件原地留下。紧跟着那句真正该干的 `rm -f` 删的却是**已经被 `mv` 走的名字**
（`.probe_$$`），是**空操作**。一行 bug 制造了 10 个垃圾文件，且**完全不报错**。

**教训（这条比文件本身值钱）**：① 「把东西丢进 `/dev/null`」只有**重定向**（`> /dev/null`）
才是丢弃，`mv ... /dev/null` 是误解；② 清理动作写错时**必须让错误可见** ——
这里 `2>/dev/null` 把一个注定失败的操作伪装成了成功，是整件事唯一的隐蔽点；
③ 排查「这东西谁写的」时，**只在仓库和历史里搜是不够的**，一次性脚本不在版本库里，
先查当事人最近手动做过什么。

**处置**：10 个文件（两处各 5）都移进
`<compose>/notify/probe-artifacts-20260911/{from-video-root,from-docker_ssd-root}/`，
同名分目录，附 `README.txt` 说明来历。**全程只 `mv` 不 `rm`** ——
项目约束明写「别对 NAS 的 UNC 路径跑 `rm`」。video 根与 `#recycle` 那处现均已干净。

**⬜ 顺带两件要你确认**：① DSM「任务计划」里那条探针任务**删掉了吗**
（最后一个文件停在 09-11 21:30，之后没再冒出来，看着是删了，但请核一眼）；
② 探针也扫过 `/volume1/docker`，那里**很可能同样躺着 5 个**，它不是共享文件夹、
SMB 看不到，SSH 上去 `ls -la /volume1/docker/.probe_done_*` 确认一下。

> **① 的核查记录（2026-09-12 11:3x）**：想从旧会话记录里翻一条**现成的删除命令**
> 给用户，结论是**没有** —— 三条 reseed 任务当年都是在 **DSM GUI 里建**的，
> `synoschedtask` 全程**只被用来查看**（就是上面 14.7 ② 那条 `--get`）。
> 记录里出现过 `--set` / `--del` 字样，但都是**当时的猜测，从未真的执行过**，
> 所以**不给用户任何猜出来的参数**。
>
> 另一个**差点成立的误判**：09-11 23:51 那份 `--get` 输出里只有
> `reseed-drive-loop` / `reseed-notify-drain` / `reseed-notify-digest` +
> 备份任务，**没有**探针任务 —— 看着能证明「早删了」。但那条命令原文是
> `synoschedtask --get | grep -n -B2 -A20 'reseed'`，**输出是按 `reseed` 过滤过的**，
> 名字里不含 `reseed` 的任务根本不会出现。**过滤后的"没看见"不等于不存在。**
>
> 可靠的两步（`--get` 的可用性与输出格式均已实测确认）：
> ```sh
> sudo /usr/syno/bin/synoschedtask --get | grep 'Name:'   # 先看它还在不在
> sudo /usr/syno/bin/synoschedtask --help                 # 要删再查删除参数
> ```
> 输出形如 `Name: [reseed-drive-loop]` / `ID: [10]` / `State: [enabled]` / `User: [root]`。
> 不想折腾 CLI 就直接走 GUI：控制面板 → 任务计划 → 「计划的任务」→ 选中 → 删除。
>
> **✅ 结案（2026-09-12 11:40，不过滤的全量清单）**：用户跑的是
> `sudo /usr/syno/bin/synoschedtask --get | grep 'Name:'` —— **没有 `reseed` 过滤，
> 是全量枚举**，共 12 条，reseed 相关只剩两条：
>
> ```
> Name: [reseed-notify-drain]     AppName: [#common:command_line#]
> Name: [reseed-drive-loop]       AppName: [#common:command_line#]
> ```
>
> **没有探针任务** ⇒ 已删除，待办 ① 关上。
>
> **顺带发现**：`reseed-notify-digest` 也**不在**列表里。这**不是缺陷** ——
> 每日台账现在由 drive-loop 自己在批次末尾发（2026-09-12 11:12:22 实测
> `已投递通知(batch) → 每日台账` + `已投递每日台账（额度 + 趋势）`），
> 独立 digest 任务属**多余**。防重复投递由 `.daily-report.state` 负责。
>
> 另外`Name:` 块里**没有** `Run time / until` 字段（在下面十几行），
> 但 §14.7 ② 那个「小时位存错」的坑**不必再复核**：该任务今天
> 10:00 / 10:15 / 10:30 / 11:15 / 11:30 **全天都在正常触发**，
> 若 `until` 还是 `[2]:[45]` 根本跳不了 —— 说明早已修正。

---

## 15. 通知怎么发出去：DSM 的 ssmtp 配置路径坑（2026-09-12 凌晨）

### 15.1 结论（一句话）

**邮件靠 `/usr/bin/ssmtp` 直连 QQ 发出；它读的是 `/usr/syno/etc/synosmtp.conf`
而不是 `/etc/ssmtp/ssmtp.conf`。** 后者在本机是 **0 字节的遗留空壳**，与邮件能不能
发出去**毫无关系** —— 邮件天天正常送达的时候，它照样是 0 字节。

### 15.2 症状与误判过程（★ 这段是留给未来的自己看的）

`notify-spool.sh --test-mail` 报：

```
ssmtp: 501 Mail from address must be same as authorization user.
```

当时的推理链（**错的**）：

1. `notify.conf` 里 `MAIL_FROM` 还是 `.example` 的占位符 `reseed@example.com`；
2. `--selftest` 说 `/etc/ssmtp/ssmtp.conf` 里"没有 AuthUser"；
3. 于是推断「DSM 的邮件通知压根没配，ssmtp 没有配置可用，退到了 `localhost:25`」。

**第 3 步错得最离谱。** 两条反证：

- 用户当时**每天**都在收 DSM 的邮件 → 通知是配好的；
- `netstat -tlnp | grep ':25'` **没有任何输出** → 本机 25 端口根本没人监听，
  ssmtp 不可能是在跟 localhost 说话。

正确地读那条 501：**它是 SMTP 服务器回的应答**，说明 ssmtp **已经连上了 QQ
并且认证通过**，只是在 `MAIL FROM` 那一步被拒 —— 因为信封发件人
（`-t` 模式下 ssmtp 取的就是 `From:` 头）与认证账号不一致。

**修法只有一步**：`MAIL_FROM=<你的邮箱>`（与认证账号**逐字相同**）。
2026-09-12 00:05 实测发出并收到。

> ★ 教训：**不要从"某个配置文件是空的"推断"某项功能没配"。**
> 先问一句「这台机器上有没有反证说明它是通的」——这个案例里就是用户天天在收信。

### 15.3 为什么「读 DSM 配置，自己发信」这条路不存在

- DSM **改过** ssmtp 的配置路径，它读 `/usr/syno/etc/synosmtp.conf`，内容形如：

  ```
  eventsmtp / eventport / eventusessl / eventuser / eventpasscrypted
  smtp_from_mail / eventsubjectprefix / smtp_verify_certificate / ...
  ```

- **密码是加密存的**（`eventpasscrypted`），用的是机器绑定密钥，脚本解不开。
- 格式虽是 `key=value`，但键名与 ssmtp 上游完全不同（`eventuser` ≠ `AuthUser`）。

→ 所以既不能"直接读来用"，也不能"照着它写一份 ssmtp.conf"。
**唯一可信的判据是真发一封**（`--test-mail`）。`notify-spool.sh` 的 selftest
已按此改写：**不再解析任何 DSM 配置文件**。

### 15.4 顺带纠正一个假阴性：BusyBox 的 `ps` 不显示命令行参数

排查当晚出现过"进程是不是被杀了"的误判：

```
sudo ps w | grep '[d]rive-loop.py'     → 空输出（看着像进程没了）
sudo cat /proc/31917/status            → 进程活得好好的
```

原因：**BusyBox 的 `ps` 只显示 `/proc/<pid>/stat` 里的 `comm`（截断到 15 字符，
也就是 `python3`），根本不显示命令行参数** —— 怎么 grep 都是空的。
而 `drive-loop.py:708` 判活用 `os.kill(pid, 0)`，那个是**真的**。

→ 以后按命令行查进程用 `pgrep -f drive-loop.py`，或者直接看状态文件心跳
（`scripts/.drive-loop.state` 里的 `heartbeat_ts`，批次运行期间每 60s 刷一次）。
`drive-loop-nas.sh` 的"四信号"排查表已把这条写进去。

> ★ 相关：`有 start 无 exit` **不等于**"被强杀"。最常见的原因是**批次还在跑**
> —— 50 部 × `--interval 30s` ≈ 25 分钟起步，再加回灌前的 `--settle 90s`，
> 跑上大半小时是常态。区分方法就是看心跳在不在涨。

### 15.5 另外两个当晚的发现

**① `synodsmnotify` 这条路放弃。**
它确实存在（`/usr/syno/bin/synodsmnotify`，`rwsr-xr-x` setuid root），但 title
必须是 "mail string key" 或 "i18n format"，而本该是 key 清单的
`/usr/syno/etc/notification/mails` 是个 **0 字节、2024-08-26 的空壳**；
`-c className` / `-l info` / 空 title 三种试法报错一字不差
（`title: '...' is neither mail string key nor i18n format.`），
二进制里也只有裸词 `i18n`，没有可发现的格式。**不值得再投入。**

**② 计划任务的「最后运行时间」存错过（这是"手动能跑、计划不跑"的真因）。**
`synoschedtask --get` 显示：

```
reseed-drive-loop    Run time: [2]:[0]    Repeat every [15] min until [2]:[45]
reseed-notify-drain  Run time: [0]:[0]    Repeat every [5]  min until [0]:[55]
```

即两条任务分别**只在 02:00–02:45 / 00:00–00:55 之间**才触发。

→ **小时位要明确设成 `23`**（`drive-loop` → 23:45，`drain` → 23:55），
改完用 `sudo /usr/syno/bin/synoschedtask --get | grep -A 12 '<任务名>'` 复核，
期望看到 `until [23]:[45]` / `until [23]:[55]`。
`reseed-notify-digest`（每天 21:20，无 repeat）本来就是对的。

### 15.6 当前状态（2026-09-12 00:05）

| 项 | 状态 |
|---|---|
| 发信通路 | ✅ 实测收到（`--test-mail` → QQ 收件箱） |
| `notify.conf` | `MAIL_TO` / `MAIL_FROM` 均为**同一个邮箱**（信封发件人必须 == 认证账号） |
| `notify-spool.sh` selftest | ✅ 已删掉"DSM 没配邮件"那段错误推断，重新部署（备份 `20260912-000508`） |
| `drive-loop` 计划窗口 | ✅ 已改成 00:00–23:45 / 每 15 分钟 |
| `drain` 计划窗口 | ✅ 已改成 00:00–23:55 / 每 5 分钟 |
| 三个任务的「发送运行详情」 | 都不勾（理由见 §13.12.7：288 + 96 封/天会把真告警淹掉） |
| 首次真跑 | 2026-09-11 23:51 手动触发的那批**仍在跑**（正常，见 §15.4） |

### 15.7 `drive-loop` 跑批阶段全程无日志（已修，2026-09-12 00:08）

**症状**：一次真跑的日志里，`[--once] 跑包 dc-collection（第 1/2 个）` 之后
**一个字都没有**，直到批次结束才蹦出 `发送完毕：…`。于是从日志上
**无法区分「在正常推进」和「卡死在第 3 部」** —— 当晚正是因此怀疑进程被杀了，
绕了一大圈才靠心跳时间戳反推出来它在正常跑。

**根因**：`orchestrator/state.py` 的 `DriveSession` 自己**不写任何日志**，
进度全靠 `on_event` 回调往外抛；不传回调时它默认是 `lambda *a, **k: None`
（`state.py:1517`）。

| 调用方 | 有没有接 `on_event` |
|---|---|
| `reseed-state.py drive`（手动跑） | ✅ 接了（`reseed-state.py:452`）→ 手工跑时看得到 `[12/50] OK 204 (+31s) 片名` |
| `drive-loop.py`（无人值守跑） | ❌ **漏传了** → 全程静默 |

**修法**：在 `drive-loop.py` 的 `run_round()` 里照 `reseed-state.py` 的同款形状
接上 `on_event=`，转发到 `LOG`（`sent`→INFO，`wait`→INFO，`warn`→WARNING，
`abort`→ERROR）。补上后新增的日志形如：

```
  [12/50] OK 204 (+31s) 电影名
  ⏸  索引器 HDFans 退避中，等到 03:12:05（420s）
```

> ★ 这条的价值不在"日志更好看"，而在于：**无人值守的系统，最长的那个阶段
> 必须能自证还在推进**。50 部 × `--interval 30s` ≈ 25 分钟起，撞上站点退避
> 还可能再等 `--max-wait` 的 30 分钟 —— 在这段时间里完全没有输出，
> 等于把"它是不是卡死了"变成了一个只能靠心跳臆测的问题。
>
> ★ 反面教训：**"日志里没有输出" 首先要怀疑的是"日志压根没接"，
> 而不是"进程卡住了"。** 排查顺序应该是：① 看代码有没有该事件源
> ② 再看心跳/进程 ③ 最后才怀疑卡死。

---

## 16. 待做的四个自动化（设计预案 —— 2026-09-12）

★ **进度（2026-09-12 更新）**：这四条里**三条已实施** ——
第 4 条（容器日志上限）、第 1 条（额度感知）、第 3 条（趋势）都写完了代码、测过、
也部署到了 NAS；第 2 条的**前置**（修期望集）也已修好。
**剩下的只有两件**：① 第 4 条在 NAS 上跑一次 `--force-recreate`（人工）；
② 第 2 条剩下的那一半 —— 把农场巡检挂成定期任务（§16.2.2）。

用户提的四条：**站点额度感知 / 农场巡检自动化 / 命中率趋势 / 日志轮转**。
本节只写**设计与探针结论**，**尚未实现**。四条同源：

> **无人值守的系统里，凡是"要人定期去看一眼"的动作，最后都会没人看。**

★ 但探完之后有两条的**前提是错的**（第 2、4 条）—— 这恰恰是"先写文档再动手"的价值：
**"想做的事"和"值得做的事"往往不是同一件。**

### 16.0 总览（含探针结论）

| # | 想法 | 现在靠什么 | 探针后的结论 |
|---|---|---|---|
| 1 | 站点额度感知 | 人工定期看 Prowlarr 的 Query Limit 消耗 | ✅ 可做，但**站点真实剩余额度拿不到**（见 16.1.1）；我方查询量可**精确算出** → ✅ **已实施（2026-09-12）**：来源 A+C 进日报；来源 B（Prowlarr）待 API key；按量阈值**故意未做**（16.1.5） |
| 2 | 农场巡检自动化 | 人工跑 `build-farm.sh --verify` | ⚠ 可做，但**前置条件是先修一个"校验永远通过"的坑**（见 16.2.1）→ ✅ **坑已修（2026-09-12）**，只剩"挂上去" |
| 3 | 命中率趋势 | `reseed-state.py report` 的当下快照 | ✅ 可做，**且原始数据已经在库里的 `attempt` 表**，不用另存 → ✅ **已实施（2026-09-12）**；实现时发现站点归属得换一列（16.3） |
| 4 | 日志轮转 | —— | ❌ **前提与实测不符**：两个日志**都已在自我轮转**；真正无上限的是**没人管过的容器 docker 日志**（见 16.4.1）→ ✅ **已完成（2026-09-12 12:42）**：`logging` 锚点已生效，`docker inspect` 回读 `max-file=3` / `max-size=10m`（16.4.2） |

### 16.1 站点额度感知

**要解决的问题**：§11.6 与 §13.10 里都写着一条**人工动作** ——
「定期看 Prowlarr 里各站的 Query Limit 消耗与账号状态」。
而**账号安全是本项目的最高优先**（14 天重搜周期就是为此从 7 天改的，§11.6）。
人工动作 + 最高优先 = **迟早出事**。所以这条与 14 天周期**同源**，值得做。

#### 16.1.1 ★ 先把「额度」拆成三件不同的事

混在一起谈必然做错 —— 它们的**可自动化程度完全不同**：

| 想知道的 | 谁能回答 | 能否自动化 |
|---|---|---|
| ① 我方今天对每个站发了多少次查询 | **我们自己**（cross-seed.db 的 `timestamp` 表；或 Prowlarr 的 `indexerstats`） | ✅ **两个独立来源可互校** |
| ② Prowlarr 的保险丝烧了没有 | Prowlarr `/api/v1/indexerstatus`（`DisabledTill` / `escalationLevel`） | ✅ |
| ③ **站点账号还剩多少额度** | **只有站点自己的网页** | ❌ **拿不到** |

★ ③ 是这件事的**天花板**，必须说在最前面：Prowlarr 的 Query Limit 是**你自己配的本地计数器**
（达到上限就把索引器临时禁用，日志里是 `API Request Limit reached for ... Disabled for 00:00:59`），
**它不是站点的真实计数**。站点网页上那句「今天还剩 N 次」，Prowlarr 从来就不知道。

→ 所以本功能的正确定位是 **「把『每天登站看 2 次』降到『出异常才登站』」，不是"取代人工"**。
把它当"能自动知道站点余额"来做，一定做成一个**自己骗自己**的假指标。

#### 16.1.2 数据从哪来（两条独立来源 + 一条已知不稳）

**来源 A —— 我们自己数（首选：零额外请求、零新增数据源）**

cross-seed 每对「某站 × 某部片」搜一次，就在 `cross-seed.db` 的
`timestamp(searchee_id, indexer_id, last_searched)` 留一行（**毫秒**时间戳）。
`orchestrator/state.py:593` **已经在读这张表了** ——「按站重搜周期」用的就是它。
所以「昨天/今天每个站各搜了多少部」就是一次 `GROUP BY`：

```sql
SELECT date(last_searched/1000,'unixepoch','+8 hours') AS d,
       indexer_id, COUNT(*)
  FROM timestamp GROUP BY d, indexer_id ORDER BY d DESC;
```

> ⚠ **时区**：表里是 **UTC 毫秒**，必须显式 `+8 hours`，否则"当天"会从早上 8 点算起。

**来源 B —— 问 Prowlarr（独立第二来源）**

`GET /api/v1/indexerstats` 返回各索引器**近 24 小时**窗口的
`numberOfQueries` / `numberOfGrabs` / `numberOfFailedQueries` 等。

> ★ 两个来源**互校**才是这条设计的核心价值，不是冗余：
> 只信 A → 看不见「**还有别的东西在吃你的额度**」（你手动在 Prowlarr 界面搜、或别的 `*arr` 应用
> 也接了同一个索引器）；只信 B → 不知道是谁在吃。**对不上就是信号。**

**来源 C —— 保险丝状态**：`GET /api/v1/indexerstatus`。
⚠ 社区有过「该接口返回空数组」的报告（Prowlarr issue #2253），**不能只靠它**，拿不到就退到 A。
另外我们**其实已经在读等价信号了**：cross-seed 自己的 `indexer` 表
（`read_indexer_backoff()`，`state.py:641`），记着 `status`（`RATE_LIMITED` 等）与 `retry_after` 解禁时间 ——
`drive` 现在就是靠它「睡到解禁」的。**这里要补的不是探测能力，是一行通知。**

#### 16.1.3 怎么接到通知系统（复用现成三档，不新造通道）

| 触发 | 用哪个 kind | 理由 |
|---|---|---|
| 滚动 24h 内某站查询量 ≥ 阈值（如 300） | `alert`（12h 冷却） | 这是「该看一眼了」，不是闲聊 |
| 某站被退避 / `DisabledTill` 在未来 | `alert` | 现在只是**默默睡到解禁**，补上通知 |
| 每日各站查询量 + 保险丝台账 | `batch` → 进**每日摘要** | 正好是"每天看一眼"的自动化替身 |

★ 关键取舍：**额度适合进日报，不适合即时告警。** 额度是**慢性**问题（超了不会当场炸），
而即时告警必须留给**急性**故障 —— 否则就变成 README 警告过的
「每 15 分钟一封骚扰 → 你去建过滤规则 → **连真告警一起过滤掉**」。

⚠ **计数必须落盘**（落状态库，如复用 `attempt` 表或新开一张 `quota_daily`），不能只存内存 ——
`--once` 每 15 分钟起一个**全新进程**，内存计数器每轮都从零开始，永远到不了阈值。

**实现前要定的两件事**：
1. **阈值按站配**，别写死全局（各站真实限额差一个数量级）。
2. ★ 窗口用**滚动 24 小时**，不要自然日 —— Prowlarr 的 limit 重置是 **UTC 0 点**
   （= 本地 **08:00**），自然日窗口和它**对不齐**，会出现"我们显示 200，Prowlarr 却已经烧了保险丝"。
   （reset 时点来自社区资料，**实现时要用真站/真 Prowlarr 复核一次**。）

#### ✅ 已实施（2026-09-12）—— 来源 A + C；来源 B 待 API key

**代码落点**：

| 东西 | 在哪 |
|---|---|
| `quota_snapshot()` 来源 A+C | `orchestrator/state.py`（`blocking_backoffs` 之后那一节） |
| `prowlarr_indexer_stats()` / `attach_prowlarr_quota()` 来源 B | 同上 |
| `render_quota()` 纯文本渲染 | 同上 |
| `quota` 子命令（人工随时看） | `scripts/reseed-state.py quota` |
| 每日台账（自动进日报） | `scripts/drive-loop.py` 的 `report_daily()` |
| 站点退避的即时告警 | 同上的 `alert_blocked_indexers()` |

**★ 四条设计取舍，每条都是为了不做错**：

1. **来源 A 顺带解决了"计数必须落盘"这条要求 —— 一行存储都不用加。**
   原设计怕的是"`--once` 每轮新进程，内存计数器归零"。但 `timestamp` 表是
   **cross-seed 自己的持久表**，本来就在盘上。**不维护计数器，就不存在"计数器会不会丢"的问题。**
2. **口径是"部数"，不是"查询次数"，而且这个区别写在函数 docstring 里、也印在输出里。**
   `timestamp` 每 (searchee, indexer) 只有一行、只留 `last_searched` 最后一次 ——
   同一部片在窗口内被重搜多次**只算 1**。真拿它去和 Prowlarr 的 Query Limit 比大小
   会得出荒唐结论，所以**输出里自带这句免责**，不靠读代码的人记得。
3. **`active()` 判据是"解禁时间还没到"，不是"状态列见过限流"。**
   实测 HDFans 的 `retry_after` 早就过期了、`status` 列**还挂着 `RATE_LIMITED`**
   （那一列 cross-seed 不会自动清回 OK）。只看"见过限流"的话，每个冷却期都会为
   **同一件早已过去的事**再喊一次 —— 喊到人不再看它，正好毁掉告警通道。
   ★ 于是 `snoozed`（见过）与 `active`（正在）在代码里是**两个不同的东西**，用途也不同：
   告警用 `active`，渲染里的「（见过限流）」用 `snoozed`。
4. **额度进日报、退避进告警**（§16.1.3 的取舍）：额度是**慢性**问题，急性的只有"此刻在退避"。

**★★ 来源 B（问 Prowlarr）现在是"未配置"，而且这是实测结论不是猜测**：

2026-09-12 从 Windows 探过 NAS 上的 Prowlarr：

```
http://192.168.0.7:9696/            → 200（服务活着）
  /api/v1/indexerstatus?apikey=<Torznab 里那个>  → 401
  /api/v1/indexerstatus（X-Api-Key 同上）        → 401
  /api/v1/openapi.json                            → 401（连文档都要鉴权）
```

→ **`.env` 里 `TORZNAB_URLS` 带的 apikey 不是 Prowlarr 的 API key**（两个索引器还各带
一个不同的 16 位串，全都 401）。要点亮来源 B，得从 Prowlarr 网页 UI
（Settings → General → API Key）取一把，写进 `.env` 的 `PROWLARR_API_KEY=`。

★ 因为**没验证过真实响应**，`prowlarr_indexer_stats()` 的策略是**宁可不报、绝不猜**：
没 key / 请求失败 / 结构不认识 → 一律返回空表 + 一句人话原因，
**永远不会返回一个自己编的数**。报错了顶多是这一列空着；猜错了会变成
"看着很合理、其实无意义"的数字，而它还要参与互校、把结论引向错误方向。
`.env` 里那个 `PROWLARR_API_KEY` 模板旁也写明了这一点。

★ 来源 B **原先没有接进 drive-loop 的无人值守路径** —— 只在
`reseed-state.py quota --with-prowlarr` 里按需调用。没验证过的东西不进每 45 分钟跑一次的循环。

**✅ 2026-09-12 下午：来源 B 已点亮并接进日报** ——
① key 已由用户填进 NAS 的 `.env`（32 字符）；
② 用真响应**核对了字段名**（`{"indexers":[{"indexerName","numberOfQueries",...}]}`，
与 `prowlarr_indexer_stats` 的解析一致）—— "没验证过"这个理由**不再成立**，于是接进
`report_daily()`（拿不到时只写一句原因，绝不编数）；
③ `.env` 补 `PROWLARR_URL=http://<NAS_IP>:9696`（**必须是宿主机 IP**，drive-loop 跑在
宿主机上、解析不了 `prowlarr` 这个服务名；备份 `.env.bak.prowlarrurl-20260912-122140`）。
★ 同时**修掉一个结构性盲点**：台账原先**看不见"Prowlarr 里有、我们没在用"的站** ——
而那正是"有别的工具在用这个 Prowlarr"唯一能露头的地方（§16.6.2）。
★ 但**用途和原先设想的不同**：它发现不了**绕开 Prowlarr 直连站点**的第二套系统
（IYUU）。详见 **§16.6.1** —— 那里记了一条推理错误。

**互校（`QuotaLine.disagrees`）只认"一边有、一边是 0"，不比大小**：
两边口径本来就不同（A 是部数、B 是 Prowlarr 记的查询数，一部片往往发好几个查询），
数值该有倍数差。有信息量的是"一边有、一边 0" —— 说明**有东西在吃额度而我们没算进去**
（手动在 Prowlarr 界面搜、别的 `*arr` 也接了同一个索引器），或者反过来我们以为搜了、
Prowlarr 根本没收到。

**首跑实测（NAS 生产库，滚动 24h）**：

```
HDFans              752 部  （见过限流：RATE_LIMITED）
NanyangPT (南洋)      714 部  （见过限流：RATE_LIMITED）
（另有 2 个已禁用的索引器窗口内无用量，未列出）
```

★ 渲染会把「**已禁用且窗口内 0 部**」的行藏掉（实测 `prowlarr#1` / `prowlarr#3`
是早就删掉的索引器，留着只是每天占两行），但**只藏零用量的** ——
已禁用却**有**用量的行必须留下，那正是"有东西在吃额度而我以为它已经关掉了"。

#### 16.1.4 ⚠ 超出 §16.1 原设计的三条（实现在代码里，也在这里留痕）

1. **幽灵用量**：`timestamp` 里还留着搜索记录、但 `indexer` 表已经没有这个 id 了
   （索引器被删过）。这些行**不丢弃**，作为 `prowlarr#N` 单列出来 ——
   "有东西在吃额度但看不见"正是本节最该报的那类信号。
2. **`render_quota` 的 `hide_idle`** 见上。
3. **没有 `--prowlarr-api-key` 命令行开关**（只从 `.env` 读）。项目的规则是
   PT/API 凭据不进命令行 —— 命令行会留在 shell 历史与进程列表里。

#### 16.1.5 ★ 没做的那一条：按量的阈值告警（**故意的**）

§16.1.3 的表里原有一条「滚动 24h 内某站查询量 ≥ 阈值（如 300）→ `alert`」。**没实现**，
理由不是没时间，而是**那个阈值现在给不出来**：

* 没有"站点真实限额"可参照（§16.1.1 的 ③ —— 那正是这个功能的天花板），
  阈值只能拍脑袋。拍出来的数字要么天天响、要么永远不响。
* 实测 HDFans 一天就是 **752 部**。按 300 设，等于**每天固定响一次** ——
  它就不再是告警，而是一条背景噪音，作用是把真正的告警一起拖进过滤规则。

→ 所以这一轮只做**"把数字按时摆到你面前"**（日报）+ **"此刻正在退避"**（真·急性，走 alert）。
等攒够几周的日报、看得见常态波动之后，阈值才有依据可配。**这跟 §16.0 那句
"能自动化的不是『看额度』，而是『把该看的数字按时摆到你面前』"是同一条原则。**

### 16.2 农场巡检自动化

**要解决的问题**：`build-farm.sh --verify` 已经能比对「农场 vs 源」，但靠人工跑。
不跑就不会发现**漂移**：源被删了/改名了，农场里那条硬链接还留着 ——
cross-seed 照样拿它去搜，**白烧额度，还可能匹配到错的东西**。

#### 16.2.1 ★ 前置条件：现在挂上去，它会「永远通过」（实测）

`build-farm.sh` 第 108 行是这么取「期望集」的：

```sh
# ---------- 1) 源清单：直接从 .env 的 DATA_DIRS 读，不另存一份，永不漂移 ----------
DATA_DIRS=$(sed -n 's/^[[:space:]]*DATA_DIRS[[:space:]]*=[[:space:]]*//p' .env | head -1)
```

「从 `.env` 派生 ⇒ 永不漂移」这个设计在**切换之前**完全正确 ——
那时 `DATA_DIRS` = 49 条源目录，**正是**农场的期望集。

**但 v3 的全部意义就是把 `DATA_DIRS` 改成农场那一条。** 切完之后：

```
DATA_DIRS=/volume1/video/download/reseed_farm     ← 源 == 农场
```

于是 `--verify` 拿**农场**当源去校验**农场** —— **自己和自己比，永远 PASS**。
这正是挂成定期任务最危险的地方：
**它会每天如期发一封「一切正常」，而它根本没有检查任何东西。**
（对照 §15.7 的教训：静默的失败比响亮的失败可怕得多。）

**修法（三选一，实现时定）**：

| 方案 | 做法 | 评价 |
|---|---|---|
| **A（推荐）** | `.env` 里另立 `FARM_SOURCES=`（49 条源目录；**切换后不再被 cross-seed 使用**，只给 build-farm 读）。脚本**优先读它，读不到才退回 `DATA_DIRS`** | 改动最小，"切换"这个动作本身没有歧义 |
| B | `--from <文件>`：把当前 49 条清单**冻结**成 `.reseed_farm.sources` | 期望集可人工审阅、可在 git 留痕 |
| C | 用清单文件 `.reseed_farm.manifest.tsv` 当期望集 | ★ **不推荐单独用** —— 清单是**农场自己写的**，源没了它不会自己变，等于**又退化一次** |

> ★ 一般原则：**校验的"期望值"绝不能来自被校验对象本身。**
> 这类退化**不报错、只静默变成永远通过** —— 比不做校验更坏，因为它还给你信心。

##### ✅ 已实施（2026-09-12 上午）—— 走的是 A + 一道自指闸

**先复现**（改之前，从 Windows 对 NAS 跑）：

```
源直接子项合计 : 475   （= 本次期望集 475 条）
农场现有条目   : 475
源有但农场没有 : 0
农场有但源没有 : 0            ← 475 vs 475，"源"就是农场，自己跟自己比
```

**改了三处**（`scripts/build-farm.sh`）：

1. **期望集改从 `FARM_SOURCES` 读**，读不到才退回 `DATA_DIRS`；
   并在开场打印 `期望集来自 : FARM_SOURCES / DATA_DIRS（退回）` —— 读的是哪一份，
   **必须一眼可见**，否则下次还是会有人以为它在校验。
2. ★ **自指闸**：源里出现农场自己（或农场内路径）→ **直接 `die`，退出码 1**。
   这是兜底：光靠"记得把清单挪过去"是挡不住的，而退化的两种后果都很重 ——
   `--verify` 永远通过、`--apply --prune` 若期望集退化到空会**把整个农场删光**。
   闸门在**探测硬链接能力之前**，所以它死的时候**没有任何副作用**。
3. **`--verify` 补上退出码与明细**（§16.2.2 第 1 条的前置）：
   * 有漂移（源有农场无 / 农场有源无 / 源目录缺失 / 跨卷）→ **退出码 1**；无漂移 → 0。
     以前**恒返回 0**，挂成计划任务也永远不会报警。
   * 两个方向的漂移**各列前 20 条**（缺失的连源路径一起打，孤儿只打名字）。
   * 三条漂移**不合成一个数**：`源有农场无` = 新内容没进农场（搜不到）；
     `农场有源无` = 源被删/改名但农场那条还在（**白烧额度，还可能匹配到错的东西**）；
     `源目录缺失/跨卷` = **期望集本身不完整，上面的数都不可信**（比有漂移更严重）。

**顺带改掉的两处陈述**（都已过期）：

* `--apply` 结尾的"下一步：把 dataDirs 从 49 条切成农场" —— 切换过之后再说这句
  等于教人**回退**。现在按 `SRC_FROM` 分流：已是 `FARM_SOURCES` 就只说"不用做别的，
  下次校验用 `--verify`；**别再动 DATA_DIRS**"。
* 环境变量表加了 `FARM_SOURCES`，并注明它**不在这里配**。

**验证**（四个测试，全过）：

| 测 | 做法 | 期望 | 实测 |
|---|---|---|---|
| ① 自指闸 | 用**当前** `.env`（`DATA_DIRS`=农场） | 硬停、退出码 1 | ✓ 打印理由 + 正确做法，**没跑探测** |
| ② 真校验 | `.env` 加 `FARM_SOURCES` | 475 = 475、退出码 0 | ✓ `期望集来自 : FARM_SOURCES` |
| ③ 假象检验 | 故意把 `FARM` 指向 `reseed_singles` | 报漂移、列明细、退出码 1 | ✓ 列出 475 条缺失（前 20 + "…还有 455 条"）与 2 条孤儿 |
| ④ 部署后复跑 | NAS 的 `.env` + NAS 的脚本 | 同 ② | ⚠ **记成「✓ 475 = 475、退出码 0」是错的 —— 被 MSYS 的 `sed` 骗了，见下** |

★ ③ 是关键：**② 那个"0 漂移"只有在能证明它会报错之后才有意义** ——
否则分不清"真的没漂移"和"还是没在检查"。这正是 §16.2 要防的那件事。

★★ **④ 更正（2026-09-12 中午）**：同一条命令、同一份 NAS `.env`，
**在 Windows 上跑通过（475 = 475、退出码 0），在 NAS 上跑就报 474 / 退出码 1**
（"源目录缺失 1"，而 `ls` 证明那个目录明明在）。差别既不在脚本也不在 `.env`，
而在**跑它的是哪个 `sed`** —— 详见 **§16.2.1.2**。

这条更正比它更正的那个结果更重要：④ 是四个验证里**唯一一个"在开发机上、隔着 SMB、对着生产的 `.env` 跑"**的，
而它恰好是唯一一个**不能这么验**的。判据：**验证 `.env` 解析对不对，必须在它真正运行的那台机器上做。**
（当时四个"全过"给了绿灯，而真的那一个从没被验过。）

**已部署**（2026-09-12 09:52，经 SMB 直写，无需 SSH）：

* `build-farm.sh` → `<compose>/build-farm.sh`（原子替换；备份 `build-farm.sh.bak.20260912-095225`）
* `.env` 加 `FARM_SOURCES=`（49 条，取自切换前的 `.env.bak.20260911-204109`；
  备份 `.env.bak.farmsources-20260912-095225`）—— **CRLF 行尾**，与该文件其余部分一致
* ★ **`build-farm.sh` 不在 `deploy.sh` 的白名单里** —— 它一直是手工放在 compose 目录下的。
  以后改它要记得单独拷，`deploy.sh` 不会带上。
* ★ 加 `FARM_SOURCES` **不影响容器**：compose 只透传 `DATA_DIRS`（`docker-compose.yml`
  的 `environment:` 里逐条列了），容器根本看不到这个变量，**不需要重建**。

**那时还没做**（属于 §16.2.2，任务 6）：把它挂成定期任务、漂移时发 `alert`、零漂移时进日报。
→ **当天下午已实施，见 §16.2.2「✅ 已实施」。** ★ 仍**绝不自动 `--prune`**。

★ 另一处要更正的是**备份**：上面写的 `.env.bak.farmsources-20260912-095225` 只有 **1818 字节**，
而其余 `.env.bak.*` 都是 7095+ 字节 —— 它**不是**一份完整 `.env` 副本，担不起"能回滚"这个说法。
（已随其余备份一起挪到 `<volume2>/#recycle/env-bak-20260912/`。）
`.env` 改动**必须留完整副本**才算备份：行尾、注释、无关行都可能是回滚时要用的信息。

#### 16.2.1.1 ★ 清单落点搬进 `hlink/`（2026-09-12 下午），顺带揪出一个 `.tmp` 泄漏

**缘起**：在 NAS 上核对农场时，看见 `/volume1/video/download/`（**媒体目录**）里躺着
`.reseed_farm.manifest.tsv`、`.names`，还有一个 115632 字节的 `.tsv.tmp` ——
跟 `movies/`、`reseed_farm/` 挤在一起，一眼分不清哪些是媒体、哪些是本项目的元数据。

**① 落点改了**：`$(dirname "$FARM")/.xxx.manifest.tsv` → **`<compose>/hlink/`**。
理由是 `hlink/` 本来就是本项目放元数据的地方（`config.yml` 在那儿，compose 里
`./hlink:/config` 也是这个意思）。**农场本身不动** —— 只是记账本换了个抽屉。
旧落点已有的清单会**自动搬一次**（新位置已存在则**不覆盖**，只 `mv` 不 `rm`：
搬不动时留在原处只是碍眼，删掉就真没了）。实测迁移后：

```
旧落点 /volume1/video/download/   →  无 .tsv/.names/.tmp
新落点 <compose>/hlink/           →  .reseed_farm.manifest.tsv (115632)
                                     .reseed_farm.manifest.tsv.names (34163)
                                     config.yml
```

**② ★ 那个 `.tmp` 是个真 bug，不是垃圾**：`$MANIFEST.tmp` 在 `--verify` 分支里
**没被删**（那条 `rm -f "$NAMES_TMP" "$MISSING_TMP"` 漏了第三个）。所以每跑一次
`--verify` 就往目录里留一个跟真清单一模一样大的 `.tmp`。
→ 改成 **`trap` 统一兜底**：`EXIT INT TERM` 一起收 `$PROBE_SRC $PROBE_DST
$NAMES_TMP $MISSING_TMP $MANIFEST.tmp`，无论从哪条路出去（正常 exit / `die` /
`set -e` 报错 / Ctrl-C）都干净。apply 成功后前两个已被 `mv` 走，`rm -f` 是空操作。
顺带把 `: > "$MANIFEST.tmp"` 和循环里的写入都收进 `[ "$DRY" = 0 ]` ——
verify/dry-run 根本不需要它，之前白写 115 KB 过一趟 SMB 最后再删掉。

★ 这条的教训是**"清理逻辑写在分支里"本身就是 bug 源**：这个脚本的出口不止一个
（verify / dry-run / apply / prune / die），清理写在其中一个分支里，
另一条路上就必然漏。**凡是"每条路都得做"的收尾，就该交给 trap，不该复制到各分支。**

**③ `build-farm.sh` 进 `deploy.sh` 白名单了**（原先不在，是手工拷上去的，见上）。
代价实测过：09-11 那次改完，仓库与生产副本之间有一段时间内容不一致，
而且手工放的没有备份。进白名单后 `deploy.sh --apply` 自动同步 + 自动进
`.deploy-backup/`。路径映射注意是 `scripts/build-farm.sh::build-farm.sh` ——
**生产在 compose 根目录**（要跟 `.env` 同目录），不是 `scripts/` 下。

**验证**：

| 测 | 做法 | 实测 |
|---|---|---|
| ① 迁移 | 本地新脚本 + NAS 路径跑 `--verify` | ✓ 打印 `[迁移]`，`.tsv`+`.names` 出现在 `hlink/`，旧落点空了 |
| ② 无漂移 | 同上（迁移后） | ✓ 475 = 475、退出码 0 |
| ③ **不泄漏** | 跑完立刻 `ls` 两处 | ✓ `hlink/` 只有 3 个文件、旧落点无 `.tmp` |
| ④ 漂移仍报错 | `FARM` 指向 `reseed_singles` | ✓ 退出码 1、列 475 缺失 + 2 孤儿，**且跑完无 `.tmp`** |
| ⑤ 部署副本 | 用 **NAS 上**那份再跑一次 | ✓ 退出码 0、无迁移行（已迁过） |

★ ③④ 是关键：改了清理逻辑就必须**验它跑完不留东西**，
而 ④ 保证"不留东西"不是靠"压根没干活"换来的。

#### 16.2.1.2 ★ 巡检第一次真跑，抓到的「漂移」是它自己造的：`.env` 行尾的 CR

> **一句话**：`.env` 是 CRLF，`sed` 不剥 `\r`，而这个 `\r` 落在**最后一条**源目录的末尾 ——
> 于是 `--verify` 报出一条根本不存在的漂移，退出码 1。
> **农场从头到尾都是健康的。** 挂上去之前没修的话，它会**每天如期报一次假警**。

**现象**（2026-09-12 中午，NAS 上跑 `sh build-farm.sh --verify`）：

```
源直接子项合计 : 474   （= 本次期望集 474 条）
农场现有条目   : 475
源有但农场没有 : 0
农场有但源没有 : 1
源目录缺失     : 1
[!!] 源目录不存在，跳过: /volume1/video/download/movies/DC相关剧集全系列大合集/DC系列电影/22.小丑2：双重妄想(2024-10-16)
★ 结论：有漂移（退出码 1）        退出码=1  耗时=4 秒
```

`ls` 直接看那个目录 —— **它明明在**。而且飘出来的「孤儿」恰好就是它的子项：
`小丑2：双重妄想.Joker.Folie.a.Deux.2024.2160p...-UBits`。**缺谁、谁就成了孤儿**，两条症状同源。

**根因**：`.env` 是 **CRLF**。脚本这么取期望集（当时还没有 `tr`）：

```sh
FARM_SOURCES=$(sed -n 's/^[[:space:]]*FARM_SOURCES[[:space:]]*=[[:space:]]*//p' .env | head -1)
```

`sed` 按 `\n` 断行，**行尾那个 `\r` 原样留在值里**；`$( )` 也不会去掉它（它只剥结尾的**换行**）。
按逗号切成 49 条之后，这个 `\r` 落在**最后一条**的末尾 —— 所以症状极具迷惑性：
**只有最后一条源目录"不存在"，其余 48 条全对。**

**实测确认**（就在写这段时查的 NAS `.env`，只打印结构、不打印内容）：

```
含 CR 的行数 : 40 / 总行数 42
DATA_DIRS      以CR结尾: False   条目数: 1
FARM_SOURCES   以CR结尾: True    条目数: 49
```

★ 注意 `DATA_DIRS` **不以 CR 结尾**。这一条正好解释了为什么这个坑**只在切换之后才出现**：
切换前读的是单值的 `DATA_DIRS`（`nas-update-env.sh` 写它时没带 CR），干净；
切换后改读 49 条的 `FARM_SOURCES`，**逗号分隔**才让 CR 有机会落在"一条"上。
**单值取值一直没事，一旦变成列表就出事** —— 同一个 CR，两种命运。

**两条后果，第二条更重**：

1. `--verify` 退出码 1 → 挂成定期任务后**每天一条假告警**。
   告警通道的容量是**信任**，假警会把它磨光 —— 真出事那天没人看了（§15.7 的同一个道理）。
2. ★ 那条源目录的子项因此进不了期望集，于是在农场里**反被当成孤儿**；
   脚本给的处理提示是 `--apply --prune`。谁照提示跑一次，就**删掉一个完全正常的农场条目**。
   `--prune` 是**不可逆**的（硬链接删了就是删了），而它的判据正是这份被打折的期望集。

**修法**：两处取值都过一遍 `tr -d '\r'`（`scripts/build-farm.sh` 第 142-143 行）：

```sh
DATA_DIRS=$(sed -n 's/.../p' .env | head -1 | tr -d '\r')
FARM_SOURCES=$(sed -n 's/.../p' .env | head -1 | tr -d '\r')
```

★ **修在读的一端，不在写的一端** —— 没去把 `.env` 改成 LF。理由：这个文件按约定就是 CRLF
（compose 读它没问题），为迁就一个脚本去改全文件行尾，是让**别的**读者承担风险；
而剥 CR 是幂等的，`.env` 以后是 LF 也不会有副作用。

**验证**（NAS 上复跑同一条命令）：

```
源直接子项合计 : 475   （= 本次期望集 475 条）
农场现有条目   : 475
源有但农场没有 : 0
农场有但源没有 : 0
★ 结论：无漂移（退出码 0）        退出码=0  耗时=1 秒
```

已部署（经 SMB 直写，备份 `build-farm.sh.bak.20260912-114923`，md5 一致）。

**★ 为什么这个 bug 在 Windows 上复现不出来**（重要，别再踩）：

| 环境 | `sed` 行为 | 结果 |
|---|---|---|
| NAS（Linux / busybox） | **不**剥 `\r` | 值末尾挂 CR → 报假漂移 |
| Windows（git bash / MSYS） | **自动**剥 `\r`（文本模式） | 值干净 → **通过** |

同一条命令、同一份 `.env`，**在 Windows 上跑通过、在 NAS 上跑报错**。
这也正是 §16.2.1 验证表 ④ 那条记录写错的原因（已更正）。
机制可以直接用一行证明（不需要跑脚本）：

```sh
printf '/a,/b\r\n' | tr ',' '\n' | tail -1 | od -c        # 末尾有 \r
printf '/a,/b\r\n' | tr ',' '\n' | tail -1 | tr -d '\r'   # 末尾没有
```

★ **教训**：读**逗号分隔**的行时，**行尾符是这个值的一部分**。
凡 shell 里从 `.env`（CRLF）取值，都该过一遍 `tr -d '\r'`。
Python 那边用 `splitlines()` 天然没这个问题 —— **出事的只会是 shell**，
所以这不是"两边都要改"的问题，是"shell 这一侧单独有个坑"。

★ 还有一条更一般的：**这个 bug 是被"把巡检挂成定期任务"这件事逼出来的**。
在那之前 `--verify` 靠人工跑，报错也只当"手滑了"；一旦挂上去，它就变成了**每天都会发生的事**。
**一个只在"自动跑"时才暴露的问题，只有真的自动跑起来才会暴露** ——
所以 §16.2.2 的"先挂上去"不是收尾，是**发现手段**。

#### 16.2.2 ✅ 已实施：把巡检挂进 `drive-loop`（2026-09-12 下午）

> 实现落在 `scripts/drive-loop.py` 的 `check_farm()`，**没有另起计划任务**。
> 理由见下「为什么挂在 drive-loop 里，而不是又一个 DSM 任务」。

原「挂法（实现时的约束）」四条，逐条落地情况：

| 原约束 | 落地 |
|---|---|
| 1. `--verify` 要有明确退出码，否则判不了成败 | ✅ **已在 §16.2.1 阶段做掉**（0=无漂移 / 1=有漂移 / 其它=没跑成） |
| 2. 有漂移 → `alert`（即时，不是日报） | ✅ `emit("alert", ..., key="farm-drift")` |
| 3. 零漂移 → 日报一行，兼当心跳 | ✅ `check_farm()` 返回一行摘要，作为 `farm_note` 塞进每日台账正文 |
| 4. ★★ 绝不自动 `--prune` | ✅ 代码里只有 `["sh", script, "--verify"]`；**测试断言 `"--prune" in argv == False`** |

**四个设计点**：

**① 三路判定，不是两路。** 退出码 0 = 无漂移；1 = 有漂移；
**其它（超时 124 / 起不来 127 / 参数错 2）单列一档**，`key="farm-check-broken"`：

> 「这**不是**『没有漂移』，而是『根本没查成』—— 修好之前，农场有没有漂移**无人知道**，
> 别把它当成『一切正常』。」

★ 这一档必须与漂移**分开告警**：合并的话，"脚本坏了"会被当成"有问题要处理"，
而"没问题"会被当成"脚本好着"。**三种状态压成两种，必然有一种被误读。**

**② 20 小时间隔标记 `.farm-check.state`。** 用**时间戳差值**判间隔，不用"今天发过没有"——
后者要处理跨天/时区，前者不用。文件原子写（`.tmp` + `os.replace`），坏/缺都当"还没查过"。

**③ 超时 120 秒 —— 按实测给余量，不是拍脑袋。** NAS 上 `--verify` 实测 **4 秒**
（475 条，全是本机 stat + 列 49 个目录，没有网络往返），120 秒 = 30 倍。
★ 注释里写死了这条理由：**这个值同时也是判据** —— 超时会被当成"巡检跑不起来"发 alert。
调太大 = 把一次真故障从告警变成静默等待。**"保险起见调大点"在这里是反向的。**

**④ 摘要必须进每日台账 —— 它不是装饰。** `alert` 有 12 小时冷却，
而 `batch`/`info` **每批都真投一条**。于是：
巡检哪天**静默不跑了**，从外面看与"一直没漂移"**完全一样**。
「巡检还活着」这个心跳，只能由日报带出来。

**为什么挂在 `drive-loop` 里，而不是又一个 DSM 任务**：不用多一个计划任务要维护、
不用再多一份日志要看，且天然复用已有的通知三档。代价是**它跟着 drive-loop 的节奏走** ——
所以有了下面这一条。

**⑤ ★ 两处调用点，第二处才是关键。**

```python
def after_batch_reports(args) -> None:
    alert_blocked_indexers(args)
    farm_note = check_farm()            # ★ 在日报**之前**跑，好把摘要塞进本次日报
    report_daily(args, farm_note=farm_note)
```

```python
if stats is None:                       # once_round：这个包没待搜
    alert_if_all_done(packs, args.db)
    check_farm()                        # ★ 见下
```

★ 只挂第一处会漏掉最该跑的时候：`run_round` 没待搜时**提前 `return None`**，
根本走不到 `after_batch_reports`。于是"所有包都搜完了"的那些天，**巡检跟着一起停** ——
而那恰恰是最该跑的：**没在搜索 ≠ 农场没漂移，只等于「没人看了」**。
等哪天真要搜了，漂移已经攒了几天。
（它自己有 20 小时间隔兜着，所以这里多调一次几乎总是空转，只读一个状态文件。）

**测试**（138 个断言，0 FAIL）：

| 文件 | 加了什么 |
|---|---|
| `test_quota_trend.py` §⑭ | 21 条：三路判定、`--prune` 绝不出现在 argv、20 小时内不再起子进程、两个 key 分开、摘要进台账正文 |
| `test_once_gate.py` §⑨ | 2 条：`stats=None` 时巡检**照样**被调用；真跑了批次则**不**重复调 |

★ 顺手修掉一处**测试污染**：`test_once_gate.py` §⑤（`stats=None`）会调到真 `check_farm()`，
而它的默认落点是**仓库里的** `scripts/.farm-check.state` —— 测试把产物写进了仓库（已清掉）。
凡是"生产会写文件"的路径，测试里都得改向临时目录。`.gitignore` 也补了
`.farm-check.state` / `.daily-report.state`（运行时产物，此前漏了）。

**部署状态**：✅ **已部署（2026-09-12 12:12，`deploy.sh --apply`，备份 `.deploy-backup/20260912-121218`）**。
本次一并发的是 6 个文件（都经 md5 核对）：`drive-loop/scripts/drive-loop.py`、
`orchestrator/{main,state}.py`（各两份，见下）、`compose.yaml`、`.dockerignore`。
★ **第一次真正跑到的时点是「下一批跑完」**（约 13:40），不是下一个 tick ——
被闸门跳过的那些 tick 只在跑闸门那几行，**走不到 `check_farm()`**。

★ 顺带修掉一个**会让这次部署直接炸掉**的问题：`orchestrator/state.py` 原先**不在
`deploy.sh` 白名单的构建上下文那一条上**（只同步到 `drive-loop/orchestrator/`）。
而 `Dockerfile` 是 `COPY orchestrator/ /app/orchestrator/` —— 于是容器里没有 `state.py`。
`state` 子命令给 `main.py` 加的是**模块级**导入，一旦缺文件，
**连默认的 `preflight` 都会 ImportError**。
→ 教训：**"这个文件在哪几个地方需要"要按"谁拷它"分别数**；
同一份代码在 `<compose>/` 下有两个用途不同的副本（镜像构建上下文 / drive-loop 运行时），
漏一个**不报错**，只在某条路径上炸。

**还没做**：给巡检本身加一条"上次检查时间"的**外部**可观测项 ——
目前只有日报里那一行。若日报那天恰好没发出（比如批次整天被闸门挡住），
巡检跑没跑同样看不出来。**这是已知的、接受了的残留风险**，不是遗漏。

#### 16.2.2.1 ✅ 已在生产验证（2026-09-12 14:30）

四项核实，全部通过：

| 查什么 | 结果 |
|---|---|
| `drive-loop/scripts/.farm-check.state` 是否出现 | ✅ **出现**（86 字节，mtime 14:30）。内容 `{"ts": 1789194608.0, "note": "农场巡检：无漂移"}` —— `ts` = **14:30:08**，即巡检真跑了并落了标记 |
| 日志里有没有 `农场巡检` 行 | ✅ `2026-09-12 14:30:10,208 [INFO] 农场巡检：无漂移`（`drive-loop.log:881`） |
| 有没有 `farm-drift` / `farm-check-broken` 告警 | ✅ **一条都没有**。日志里仅有的两条 `alert` 都与农场无关（`23:27` 的「`.env` 未生效：`/3/api` 410 ×11」、`13:15` 的「索引器拉不到名字：prowlarr#1」） |
| `.drive-loop.state` 的 `running_pid` | ✅ **`null`**（批次已结束）。`last_end_ts` = 14:30:10，`last_sleep_sec` = 7200（2 小时） |

**顺带第 4 项**（`cross-seed/logs/error.2026-09-12.log`）：`Failed to parse` 与 `ENOENT` **各 7 条**，
与 12:42 的读数**完全一致 —— 这批没有新增**。最后一条停在 `12:13:06`。

**为什么它只在 14:30 出现过一次 —— 三个原因叠加，都属正常**：

1. **代码 12:21 才部署到 NAS。** 12:40 结束的那批 **12:00:01 就启动了**，跑的是旧代码
   （`deploy.sh` 走原子替换，运行中的进程仍握着旧 inode，§17.2 —— 这正是 §17.2 想要的行为）。
   13:30:02 启动、14:30:07 结束的那批，才是**第一个**带 `check_farm()` 的批次。
2. **20 小时间隔**（`FARM_CHECK_MIN_GAP_SEC`）。首跑落标记之后，后续批次命中缓存，
   只读一个状态文件、既不起子进程也不打日志行 —— **"没打印"不等于"没跑"，这层区分是刻意设计的**。
3. **首跑比她预估的晚。** 本节正文预计"约 13:40"，实际是 **14:30:08** ——
   这批在第 4 部片子处撞上 `prowlarr#1` 限流，退避 **1770 秒**（13:32 → 14:01:33），
   把整批往后推了约 30 分钟。★ **这是闸门与退避的正常代价，不是巡检的问题** ——
   任何"挂在批次收尾"上的东西，都会继承这个抖动。

**结论**：任务 6「把巡检挂进 drive-loop」**已闭环** —— 从 §16.2.1 的「**有能力**报错」，
走到了「**真的在自动跑、且真的报了一次『无漂移』**」。当前农场处于**零漂移**状态。

★ **这次没有验证到的分支（如实记下）**：「有漂移 → `alert`」与「跑不起来 → `alert`」
这两条路**在真机上还没被触发过**，此前只在测试里断言过（§16.2.2 的 138 条）。
首次真触发时要留意告警文案是否如设计所愿 —— **测试通过 ≠ 首次真告警的文案可读**。

★ **顺带收掉了 §16.2.2 末尾那条"还没做"**：那里写「给巡检加一条外部可观测项 ——
目前只有日报里那一行」。**`.farm-check.state` 本身就是那个可观测项** ——
它是 NAS 上的一个普通文件，带 `ts` 与摘要，`cat` 一下就知道上次巡检是什么时候、
结论是什么，**不必等日报**。当初把它当"缓存标记"写，没意识到它同时也是外部探针。

### 16.3 命中率趋势

**要解决的问题**：`reseed-state.py report` 给的是**当下快照**。
「哪个站值不值得留 / 换站有没有效果」是**趋势**问题，快照答不了 ——
而**换站是眼下的待办**（用新站替 BTSCHOOL，§13.7 / README「还没做」第 3 条）。

#### 16.3.1 ★ 数据早就在库里了，不用另存一份（NAS 实测）

状态库的 `attempt` 表**本身就是一张事件流水**：

```
attempt(id, movie_id, at, kind, result, indexers, skipped_indexers, note)
```

`drive-loop/hlink/state.db` 实测：**1350 行**，`at` 从 `2026-09-11 13:40:53` 到 `22:44:34`；
`result` 分布 `skipped 514 / pending 312 / unmatched 301 / seeding 157 / matched 66`；
`kind` 目前**只有 `sync`**。

于是「趋势」= 对这张表按天聚合，**零新增存储**：

```sql
-- 每日各阶段的量
SELECT date(at) AS d, result, COUNT(*) FROM attempt GROUP BY d, result;
-- 按站看"这场换站赚了几部"
SELECT date(at) AS d, indexers, COUNT(*) FROM attempt
 WHERE result='seeding' GROUP BY d, indexers;
```

⚠ **两个必须先处理的点**：

1. `attempt` 表**没有 `at` 的单列索引**（现有的只有 `idx_attempt_movie(movie_id, at)`）。
   按 `at` 聚合会**全表扫**。现在 1350 行无所谓，但趋势是**长期**功能 ——
   实现时顺手 `CREATE INDEX idx_attempt_at ON attempt(at)`。
2. ★ **`seeding` 是"状态"，不是"增量"**。同一部片今天已经是 `SEEDING`，明天的 sync
   **不会再写一行**（好事，天然不重复计数）；但也意味着
   **「今天新增做种 N 部」不能直接 count 当天的行**，要按片取首次：
   `MIN(at) GROUP BY movie_id HAVING result='seeding'`。

#### 16.3.2 落成什么样

* 进**每日摘要**一小段：`本周新增做种 N 部（HDFans x / NanyangPT y）`。
* 换站决策要的是「**按站 × 按周**」的对比，所以聚合维度是 **(周, 站)**，
  不是全局一个数 —— 全局数会把"哪个站有用"平均掉。
* ⚠ **别做图/HTML**：邮件是纯文本，**一屏能看完**才有用。

#### ✅ 已实施（2026-09-12）—— 实现时改了两处口径

**代码落点**：`StateStore.trend()` + `TrendReport.render()`（`orchestrator/state.py`）、
`reseed-state.py trend` 子命令、`drive-loop.py` 的 `report_daily()` 进日报。

**① 索引已经加上了**：`CREATE INDEX IF NOT EXISTS idx_attempt_at ON attempt(at)`
（`SCHEMA` + `_migrate()` 两处都写了 —— 前者管新库，后者管已存在的老库；
重复 `CREATE INDEX IF NOT EXISTS` 是幂等的）。生产库已建上，实测
`sqlite_master` 里 `idx_attempt_movie` 与 `idx_attempt_at` 并存。

**② ★★ 站点归属**：原设计的 SQL 是按 `attempt.indexers` 归属，**那条路走不通**。
实测：

```
attempt 表里 kind='inject' 的行，indexers 写的是 '[]'
（sync_movie 里那三个 add_attempt 调用没传 indexers）
```

按它归属会**全部落到"未记站点"**。正确来源是 `movie.matched_indexers`。

**③ ★★ 但 `matched_indexers` 会缺 —— 而且是实测出来的 20%。**
实测 201 部 SEEDING 里：**161 部**有 `matched_indexers`（`["HDFans"]`）、
**40 部是 `[]`**（`matched_hashes` 却有值）。查下来那 40 部**恰好都是 08:55 那一批**
（farm_root 修复后的批次）变 SEEDING 的 —— 即 `matched_indexers` 的来源是
**解析 cross-seed 日志**，日志没覆盖到（或走的是 DB/qB 那条路）时它就是空的。

→ 于是加了**兜底**：`matched_indexers` 空时，退到**该片第一条 seeding 行**的
`attempt.indexers`（实测确实是准的，如 `["HDFans","NanyangPT (南洋)"]`）。
★ 两个都是**记下来的事实**，不是猜的 —— 所以这是补全，不是编造。
两边都没有才落到 `（未记站点）`，**并且会被单独点名**（`UNATTRIBUTED_SITE`，
不并进任何站 —— 它变多说明"匹配到了但没记下来"，那本身是个 bug 信号）。
`attempt` 里那个 `(未记录)` 占位（`UNKNOWN_INDEXER`）同样**不算一个站**。

修完实测（生产库）：

```
修之前：本周新增做种 201 部 /（未记站点）201      ← 全部丢失归属
修之后：本周新增做种 201 部 / HDFans 201 / NanyangPT (南洋) 25
```

★ 这一步的价值不只是数字好看：**它把"日志没覆盖到"这件事从静默变成了可见。**
若不修，趋势会一直显示"201 部没记到站点"，而人会以为那 40 部是没匹配上。

**④ ★ 日报的去重必须自己做，不能靠 notify。** `notify` 的冷却**只对 `alert` 生效**
（`batch` → `level=info` → `_cooled` 根本不查），也就是说同一个 batch 事件
**每一批都会真的写一个新文件进 spool** —— 45 分钟一批 = 一天 30 多条日报。
所以 `report_daily()` 自己记 `scripts/.daily-report.state`（`{"last_day": "..."}`，
原子替换写）。`emit` 失败时不标记，下一轮重试。

**⑤ 顺带修正了一处早已存在的静默 bug**（写在这里备查，不是本次引入）：
`drive-loop.py` 里 `emit("batch", ..., key="all-done")` 的注释写着「固定 key + 冷却：
不冷会刷屏」—— 但 `batch` 是 info 级、**不查冷却**，所以那个 key 是**失效的**。
全干完之后仍是每 15 分钟写一个 `all-done` 文件。**本次没动它**（改动通知语义要单独评估），
只把事实记下来。

**⑥ 首跑就撞上的读法陷阱：总数是「去重部数」，按站相加必然更大。**
2026-09-12 10:0x 在 NAS 用真库跑，输出是：

```
本周（2026-W37）新增做种 237 部（去重）
    HDFans  237
    NanyangPT (南洋)  30
```

`237 + 30 = 267 ≠ 237`。**这不是 bug**：总数按 `movie` 去重，而一部片同时在两个站做种时
**每个站各记一次**（那 30 部 NanyangPT 全都同时也在 HDFans 上）。
但这正是实测的第一反应 —— 数看着对不上。所以渲染里：
* 总数标成 `部（去重）`；
* 且**只在 `按站之和 > 总数` 时**补一行 `↑ 按站相加 267 > 237：同一部片在多个站做种时，每个站各记一次`。

★ 记住这条通用教训：**当一个数有两种都正确的口径时，光给数字等于埋雷** ——
必须把口径写在数字旁边，否则下一个人（包括三个月后的自己）会去查一个不存在的 bug。

### 16.4 日志轮转

#### 16.4.1 ❌ 前提与实测不符，先把账算清（NAS 真数据）

提这条时的假设是「`drive-loop.log` 和 cross-seed 的日志**都在无限长**」。**两条都不成立**：

| 日志 | 实际轮转情况 | 稳态上限 |
|---|---|---|
| `<路径>/drive-loop/scripts/drive-loop.log` | ✅ **已有** `RotatingFileHandler(maxBytes=5MB, backupCount=5)`（`drive-loop.py:896`） | ~**30 MB**（当前 + 5 份） |
| `<路径>/cross-seed/logs/*` | ✅ **已有按天轮转 + 保留 14 天** —— audit 文件里明写 `"keep": {"days": true, "amount": 14}` | ≈ 14 × 64 MB ≈ **0.9 GB** |
| `<路径>/notify/log/<日期>.tsv` | ❌ 不清理，但**一天 137 字节** | ~**50 KB/年**（可忽略） |

cross-seed 一天的量（2026-09-11 实测）：`verbose` **58.0 MB** + `info` 3.4 MB + `error` 17 KB ≈ **64 MB/天**。
→ 14 天保留 = **约 0.9 GB 稳态**。这确实不是"无限长"，但**是唯一有量的地方**。

> ★ 那 `verbose` 58 MB/天 值不值？**这是本题唯一值得动的地方**：
> verbose 是排错用的，平时没人看。可选动作（**实现前先确认你的 cross-seed 版本支持哪个键**）：
> ① 关掉 verbose；② 把 14 天降到 7 天（排错基本发生在前 3 天）。
> 任一都能把稳态从 ~0.9 GB 压到 **~0.3 GB 以下**。

#### 16.4.2 ★ 真正没有上限的是另一处：容器的 docker 日志

`docker-compose.yml` 里**四个服务全都没有 `logging:` 段** ——
`grep -n "logging\|max-size\|max-file" docker-compose.yml` **只命中 `driver: bridge`**（那是网络，不是日志）。
也就是说 `prowlarr` / `cross-seed` / `flaresolverr` / `reseed-orchestrator`
**全部走 Docker 默认的 `json-file` 驱动，默认没有任何上限**
（除非你另改过全局 `daemon.json`）。**这才是这一条里真会无限长的那个。**

**先在 NAS 上量一下**（只读，不改任何东西）：

```sh
sudo docker info --format '{{.LoggingDriver}}'
sudo du -sh /volume2/@docker/containers/*/*-json.log 2>/dev/null | sort -h | tail
sudo cat /var/packages/ContainerManager/etc/dockerd.json 2>/dev/null     # 看有没有全局 log-opts
```

**处理**（两条路，实现时选）：

* **A（推荐，改动最小、影响面最小）**：`docker-compose.yml` 给每个服务加
  ```yaml
  logging:
    driver: json-file
    options: { max-size: "10m", max-file: "3" }
  ```
  —— **必须 `--force-recreate` 才生效**（正好并进「收尾命令」那一次重建）。
* B：改全局 `dockerd.json` 的 `log-opts` 再重启 Container Manager。
  ⚠ 这会影响**这台 NAS 上所有容器**（你可能还有别的服务），**慎选**。

##### ✅ 已实施（2026-09-12 上午）—— 走的是 A

**改哪**：`docker-compose.yml`。四个服务共用一份 YAML **锚点**，而不是抄四遍 ——
以后调上限只改一处，不会漂移：

```yaml
x-logging: &logging-limits
  driver: json-file
  options:
    max-size: "10m"
    max-file: "3"
...
  prowlarr:
    logging: *logging-limits
```

`x-` 开头的顶层键是 compose 规范允许的**扩展字段**（会被忽略），所以它不会变成一个服务。

**为什么没选 B**：`dockerd.json` 的 `log-opts` 是**全局**的 —— 这台 NAS 上还有别的服务，
动它等于替所有项目做主。A 的影响面就锁在这四个容器里。

**为什么上限是 10m × 3**：每个容器封顶 30 MB，四个合计 ~120 MB。
对「无上限」来说是质变；真要看历史日志，`cross-seed/logs/*`（保留 14 天）才是权威，
docker 的 stdout 日志只是副本，转掉不可惜。

**验证（本地，已做）**：用 PyYAML 解一遍 —— `x-logging` 在**顶层**（`['x-logging','services','networks']`）、
四个服务各自 `logging = {'driver':'json-file','options':{'max-size':'10m','max-file':'3'}}`、
`'x-logging' in services` 为 **False**。

##### ✅ 已生效（2026-09-12 12:42，NAS 上执行完毕）

**等了什么**：`--force-recreate` 会掐断 `cross-seed`/`prowlarr` 几秒，
所以先等 `scripts/.drive-loop.state` 里 `running_pid` 变 `null`。
批次 12:40:15 收尾（`last_end_ts = 1789188015.13`、`last_sleep_sec = 2700`），
12:42 执行重建。**这一枪同时办完了另一件事**（清掉 `/3/api`，见 §13.10 ⑧）。

```bash
cd /volume2/docker_ssd/prowlarr_cross-seed_autohardlink
until grep -q '"running_pid": null' drive-loop/scripts/.drive-loop.state; do sleep 30; done
sudo docker compose config --quiet && echo 'YAML OK'
sudo docker compose up -d --force-recreate cross-seed prowlarr flaresolverr
```

**回读验证（逐条对过）**：

| 检查 | 结果 |
|---|---|
| `sudo docker inspect reseed-cross-seed --format '{{json .HostConfig.LogConfig}}'` | `{"Type":"json-file","Config":{"max-file":"3","max-size":"10m"}}` ✅ |
| 容器状态 | 三个全 `Up`（`reseed-cross-seed` / `reseed-prowlarr` / `reseed-flaresolverr`） |
| `/3/api` 的 410 | 当日日志 **0 次**（`grep -c "/3/api"` 也是 0） |
| 新容器认识的索引器 | **恰好两个**：`HDFans`、`NanyangPT (南洋)` —— 反证 `/3` 确实没了 |
| `Your configuration is valid!` | ✅ 12:42:18 |
| qB 登录 / 反向索引 | ✅ `Logged in to v4.6.5` / `Validated 1888 entries from dataDirs` |

> ★ **别把下面这两条当成故障**（重建后第一次启动就有，容易被误读）：
> ```
> 12:42:18.224 error: HDFans failed to respond, check verbose logs: fetch failed
> 12:42:18.231 error: NanyangPT (南洋) failed to respond, check verbose logs: fetch failed
> ```
> 这是**启动常态**：`cross-seed` 比 `Prowlarr` 先起来，配置校验那一瞬间 Torznab 还连不上。
> 09-11 的日志里同样形态出现 5 次（`21:53:49` 就是这两条），
> 且每次后面都跟着 `Your configuration is valid!`。
> **判据**：只要 `fetch failed` 后面紧跟 `Your configuration is valid!`，就是竞态、不是配置错。
> 真配置错的形态是 **`code 410/401/403`**（见 §13.10 ⑧）。
>
> ★ **2026-09-12 13:12 这条已被实证**（不再只是推测）：同一天、同一套配置、
> 同一台机器，唯一差别是那次重建**加了 `--no-deps`（Prowlarr 没被一起重启）** ——
> 启动日志里**一条 `failed to respond` 都没有**，直接就是
> `Logged in to v4.6.5 successfully` → `Your configuration is valid!`。
> **所以判据可以更硬地说**：`failed to respond` 是「我们自己重启时把 Prowlarr 一起拽下去了」
> 的副产品。**只重建 cross-seed 时请务必带 `--no-deps`，能省掉这两条假告警。**

> ★ 顺带一提：这次 `up -d` **把 `flaresolverr` 的镜像也拉新了**（12 层 Pulled）。
> 也就是说这一次重建不只换了配置，还换了一个版本。
> 它没影响本次结论，但**下次重建前后要留意 flaresolverr 的行为是否变化**。

★ **`reseed-orchestrator` 不用管**：它是 `restart: "no"` 的一次性 CLI，每次
`docker compose run --rm` 都会**新建容器**，自动带上新配置。
（也正因如此，上面的 `up -d` **只列三个常驻服务** —— 不列它就不会触发 `build:`。）

★ **务必挑批次间隙跑**：`--force-recreate` 会让 `cross-seed` / `prowlarr` 断几秒，
正在跑的 drive 会拿到连接错误。判据：`scripts/.drive-loop.state` 里 `running_pid` 为 `null`。


> ★ 结论先记住：**别去动那两个已经在自我轮转的日志**，力气花在**没人管过的容器日志**上。
> 这条的全部价值就在这个纠正里 —— 照原假设去写，会做出一个**已经存在的东西**。

### 16.5 优先级建议

| 优先 | 哪条 | 为什么 |
|---|---|---|
| ~~**1**~~ | ~~**16.4.2 容器日志上限**~~ ✅ **已完成（2026-09-12 12:42）** —— `logging` 段已写进 `docker-compose.yml` 并同步到 NAS 的 `compose.yaml`，批次间隙里 `--force-recreate` 跑完，`docker inspect` 回读 = `max-file=3 / max-size=10m` | 已从「一个配置段」推进到「一次命令」，再到**已生效** |
| ~~**2**~~ | ~~**16.2.1 修 build-farm 的期望集**~~ ✅ **已实施（2026-09-12 09:52）** —— `FARM_SOURCES` + 自指闸 + `--verify` 退出码/明细，已部署并复跑通过（§16.2.1「已实施」） | **前置条件已清除** —— 巡检现在**有能力**报错了 |
| ~~**3**~~ | ~~**16.2.2 把巡检挂进 `drive-loop`**~~ ✅ **已实施并部署（2026-09-12 12:12）** —— `check_farm()` + 三路判定 + 20h 间隔标记 + 摘要进每日台账；顺带在真跑中揪出两个 bug（`.env` 行尾 CR 的**假漂移**，§16.2.1.2；`--verify` 的 `.tmp` 泄漏，§16.2.1.1） | 前置条件确实是齐的，但**"挂上去"这个动作自己又长出两个 bug** —— 都是只在"自动跑"时才暴露的那类（§16.2.1.2 末） |
| ~~**4**~~ | ~~**16.1 额度感知**~~ ✅ **已实施（2026-09-12）** —— 来源 A+C 已在 `drive-loop` 每日台账里跑；来源 B 卡在 Prowlarr API key（§16.1「已实施」）；按量阈值告警**故意未做**（§16.1.5） | 直接服务「账号安全」这个最高优先，且**不增加任何站点请求** |
| ~~**5**~~ | ~~**16.3 趋势**~~ ✅ **已实施（2026-09-12）** —— `idx_attempt_at` + `StateStore.trend()` + `reseed-state.py trend` + 进日报；实测 201 部**全部**拿到站点归属（§16.3「已实施」） | 换站决策的直接依据 |
| ~~**6**~~ | ~~**16.6 查清是否有第二套系统在共用 qB**~~ ✅ **已查清（2026-09-12 13:00）** —— **是 IYUU Plus**，容器 `iyuuplus_ssd`，就在这台 NAS 上；**昨天 21:08 刚把我们的 qB（`:3060`）加为下载器**，其任务 2 每天 02:34 向我们这个 qB 辅种、并查询 16 个站（**含 HDFans 与南洋**）。**但它是抓网页（`details.php`），不是 Torznab** —— 所以**台账的分母没有被污染**（前提待站点规则页确认）。全文 §16.6.3 | ★ 结论与立案时的担忧**方向一致、程度更轻**：前提确实被打破了（"只有我们在用这些站"是错的），但**两套系统走的是不同的请求通道**，A/B 两个来源量的是 Torznab，IYUU 走 HTML |

> ★ 另：与 §16 强相关、已于 2026-09-12 下午顺手做掉的两条小项 ——
> `.dockerignore` 的 `.env` → **`.env*`**（`.env` 是精确匹配，拦不住 `.env.bak.*`
> 这类含密钥的完整副本，实测仓库根目录**就躺着一份**）；
> 编排器的 `state` 子命令（§11.9，**原先那条待办把名字写成了 `status`，而 `status` 早就有了**）。

> 一句话总结这几条：**能自动化的不是「看额度」，而是「把该看的数字按时摆到你面前」。**

### 16.6 ★ 新发现（2026-09-12）：**有第二套系统**在跟我们共用同一个 qB

> **状态：已立案；下午查了一半。**
> 已知的写「已知」，推测的写「推测」；下午推翻了自己上午的一条推测，**原文保留**（§16.6.1）。
> 这条**不是故障**，但它会让 §16.1 的额度台账**看起来安全、实际不安全**。

**已知的**（都是查过 qB 与 `.env` 的事实）：

| 事实 | 值 |
|---|---|
| `.env` 里配的 Torznab 索引器 | **2 个**（HDFans、NanyangPT 南洋） |
| qB 里的种子总数 | 434，seed 路径**全部**在 `reseed_singles/` 下 |
| qB 里实际出现的 tracker 域名 | **明显多于 2 个** —— 除 HDFans/南洋外还有 keepfrds、btschool、m-team、hdarea、pterclub、muxuege、hdsky、springsunday 等 |

**推测的**（未验证，别当成结论）：cross-seed 只会从**它自己的索引器**拿到种子，
所以上面那些站**不是本项目注入的** —— 另有东西在往同一个 qB 里注入，**首要嫌疑是 IYUU**
（NAS 上确实有 `iyuuplus` 的痕迹）。

**为什么这事值得单列一条**：§16.1 的额度台账统计的是**我们自己发出的搜索**
（`cross-seed.db` 的 `timestamp` 表，外加可选的 Prowlarr `numberOfQueries`）。
如果 IYUU 也在查同样的站，那么：

* 我们看到的"今日搜索数"**低于实际**；
* 站点那边看到的却是**两边之和** —— 触发限流/封的风险比台账显示的高。

#### 16.6.1 当天下午：来源 B 点亮了，结论**推翻了我上午的猜测**（2026-09-12）

**先把真响应拿到手**（这一步是解锁点，也是代码注释里明说"没核对过"的那一步）。
用 NAS `.env` 里的 `PROWLARR_API_KEY` 打 `/api/v1/indexerstats`，结构是：

```json
{"indexers":[{"indexerId":1,"indexerName":"HDtime","numberOfQueries":8,
              "numberOfGrabs":0,"numberOfRssQueries":2,"numberOfFailedQueries":4,...}],
 "userAgents":[...], "hosts":[...]}
```

与 `S.prowlarr_indexer_stats` 的解析**完全一致** —— 字段名核对通过。
（那 32 字符的 key 与 Torznab 的 apikey 确实不是同一个，`/api/v1/*` 用它才通。）

**Prowlarr 里到底配了什么**（`/api/v1/indexer` + `/api/v1/indexerstats`）：

| id | 名字 | 启用 | 查询数 | 备注 |
|---|---|---|---|---|
| 1 | **HDtime** | ✅ | **8**（rss 2 / 失败 4） | ★ **不在我们的 `TORZNAB_URLS` 里** |
| 2 | HDFans | ✅ | 1730 | 我们的 `/2/api` |
| 4 | NanyangPT (南洋) | ✅ | 1536 | 我们的 `/4/api` |
| 3 | BTSCHOOL | ❌ 已禁用 | — | 与 README 记的一致 |

我们的 `TORZNAB_URLS`：**2 条**（`/2`、`/4`）。

**★★ 结论：上午那个"点亮 B 就能发现 IYUU"的说法是错的，现在有反证。**
qB 里那些不属于我们的 tracker（keepfrds / btschool / m-team / hdarea / pterclub / muxuege /
hdsky / springsunday…）**在 Prowlarr 里一个都没有**。
而 A/B 互校比的是「我们的搜索数」vs「**Prowlarr 记的**查询数」——
**一个绕开 Prowlarr 直接打站点的工具，B 这一侧根本不会出现。**
所以 A/B **看不见 IYUU**。线索反而更强了：那些站连 Prowlarr 都没配，
说明第二套系统是**自带站点会话、直连 tracker** 的（IYUU 正是这种形态）。

> ★ 记一条**不要重犯**的推理错误：我当时把「B 是我们唯一的外部视角」
> 直接推成了「B 能看见所有外部活动」。
> **视角 != 全景** —— B 只能看见**经过 B 的**东西。
> 任何时候说"这是唯一能发现它的手段"，都该补问一句：**它会不会从这条路的旁边绕过去？**

**那点亮 B 还有什么用**：不是没用，是**用途变了**。它能发现的是
**「有别的工具在用我们的 Prowlarr」** —— 而这次真就抓到一个：**HDtime**。
它启用了、被查了 8 次（含 4 次失败），而我们的 cross-seed 只用 `/2` `/4`，
**这 8 次不是我们发的**。谁发的还没查（可能是 Prowlarr 自己的 RSS 同步，
也可能是谁在 UI 里点过）。**这是一个具体的、待查的问题，比上午那条模糊的怀疑强。**

#### 16.6.2 ★ 顺带修掉一个结构性盲点：台账**看不见"不是我们的站"**

`attach_prowlarr_quota` 原先**只遍历来源 A 的行**去 B 里查名字 ——
于是「Prowlarr 配了、我们不用的站」**一行都不会出现**，
而那恰恰是上面那个信号**唯一**的落点（不修的话，HDtime 永远看不见）。

已改为：把只存在于 B、且 `numberOfQueries > 0` 的索引器补成 `prowlarr_only=True` 的行
（`== 0` 的不补：那只是个没用到的配置，天天打是噪音）。
渲染上给了**专属旗标**（"不是本项目的索引器，却被 Prowlarr 记了 N 次查询"），
用量打 `-` 而不是 `0`（`0` 会被读成"我们搜了 0 次"，事实是"这行不属于我们"），
且**不参与 `limit` 截断**（`limit` 是给我们自己的站防日常噪音的，这一档罕见且重要）。

**同一次还修了一个误导**：`render_quota` 把
「**整体**拿不到 B」和「**某一行**名字对不上」混成一个 `prowlarr_note`，
渲染成同一句「来源 B 互校不可用」。实测现场就是：B 好得很（HDtime 的数就是它给的），
却仍印出"互校不可用"。→ 拆成两个字段（`prowlarr_note` 只管整体失败，
`prowlarr_mismatch` 管单行），单行的提示挪到那一行上去。

#### 16.6.3 ✅ 查清了：**IYUU Plus 就在这台 NAS 上，而且昨天刚接上我们的 qB**（2026-09-12 13:00）

用户授权**只读**翻阅 IYUU 的目录（`\\iSunker-DS423\docker_ssd\iyuuplus`）后查清的。
**全程只读，一个字节都没改。**

**它是什么**：容器 `iyuuplus_ssd`（`iyuucn/iyuuplus:latest`，`restart: unless-stopped`，
Web UI `:8787/app/admin`），PHP/Webman + 自带 MariaDB（`iyuu_data/`）。

##### ★ 只读的事实源：`iyuu/runtime/backup/` 的每日快照

这是本次最有价值的方法论发现 —— **不用进 UI、不用连数据库**，
`runtime/backup/` 每天落一份 JSON 快照，四份都是可读文本：

| 文件 | 内容 |
|---|---|
| `cn_client.json` | **下载器列表**（品牌 / 地址 / 启用 / 默认） |
| `cn_sites.json` | **站点列表**（`disabled` 开关 / `base_url` / 页面模板） |
| `cn_crontab.json` | **计划任务**（含解开后的 `parameter`） |
| `wa_options.json` | 全局选项 |

##### ★★ 下载器表：`id=6` 就是我们的 qB，**2026-09-11 21:08 才加进去的**

| id | 名称 | 地址 | 启用 |
|---|---|---|---|
| 1 | QB（DSM 套件版） | `:8085` | ✅ **默认** |
| 2 | TR | `:9091` | ✅ |
| 3 | QB docker | `:3003` | ❌ |
| 5 | QB-docker-opencd | `:3020` | ✅（音乐库） |
| **6** | **QB-docker-reseed** | **`:3060`** | ✅ ← **我们的 qB**，`created_at = 2026-09-11 21:08:17` |

##### ★★ 四个辅种任务（`task_type=10`）—— 站点与下载器都是明文的

| id | 名称 | 时间 | `clients` | 站点 |
|---|---|---|---|---|
| **2** | **`QB-docker-reseed辅种`** | **每天 02:34** | **`{"6": "on"}` → 我们的 :3060** | **16 个**：audiences, **btschool**, hdarea, **hdfans**, hdhome, hdsky, hdtime, keepfrds, m-team, muxuege, **nanyangpt**, nicept, opencd, ourbits, pter, ssd |
| 4 | `qb自动辅种` | 每天 01:45 | `{"1": "on"}` → :8085 套件版 | 17 个（同上 + hddolby） |
| 6 | `QB-docker-opencd` | 每天 03:45 | `{"5": "on"}` → :3020 | m-team, opencd |
| 1/3/5 | 三个 `iyuu:transfer` | — | qB↔TR 搬种，不查站 | —— |

**所以 §16.6.4 的第 1、2 条答案是**：它**在跑**（任务 2 今天 02:34 跑过，累计 290 次，
且当天日志里有 `辅种结束发送通知后的响应：{"errcode":0}`）；
注入到**我们的 qB**；**确实查 HDFans 和 NanyangPT**（就在那 16 个站里）。

##### ★★★ 但它走的是**另一条路** —— 这决定台账还算不算数

`cn_sites.json` 里每个站的模板暴露了它的请求方式：

```
details_page  = details.php?id={}
download_page = download.php?id={}&passkey={passkey}
options.limit = {"count": "20", "sleep": "5"}
```

**IYUU 抓的是网页（详情页 + 下载页），不是 Torznab 搜索接口**，而且自带节流（20 次 / sleep 5s）。

于是三个数据源各看各的：

| 来源 | 量的是什么 | 看得见 IYUU 吗 |
|---|---|---|
| A（cross-seed.db） | **我们**发出的 Torznab 搜索 | ❌ |
| B（Prowlarr） | 经过 **Prowlarr** 的一切 | ❌（IYUU **绕过 Prowlarr 直连站点**） |
| IYUU | 直接抓站点 HTML | —— 我们看不见 |

> ★ **结论：台账的分母没有被 IYUU 污染** —— 它量的是「我们的 Torznab 搜索量」，
> 而 IYUU 走网页。**但这是有条件的**：前提是**站点把「API 查询额度」和「网页浏览」
> 分开计**。这是**站点自己定的规则，尚未核实**，也是这一条唯一还没闭环的地方
> （只能人去 HDFans / 南洋的规则页看有没有两套限额）。

##### ★ 顺带查出来的三件事（都不在原问题范围内）

1. **Prowlarr 里其实有 4 个索引器**（不是 2 个）：
   `1=HDtime(enable)`、`2=HDFans`、**`3=BTSCHOOL(enable=False)`**、`4=NanyangPT`。
   * **BTSCHOOL 从来没有被删除** —— §13.10 把「410 Gone」解释成「该索引器在 Prowlarr 已删」，
     与这里的 `id=3` 存在相矛盾。**410 很可能就是「索引器被停用」的返回码**，
     这一条需要复核（目前只有 API 的这行事实，机制未证实）。
   * **HDtime 那 8 次查询大概率不是 IYUU 发的** —— IYUU 绕过 Prowlarr。
     那 `enable=True` 却没人用的 HDtime，最可能是 **Prowlarr 自身的检查/同步**。
     §16.6.1 那句「有别的工具在用我们的 Prowlarr」**很可能因此是错的**（待证实）。
2. **IYUU 自己也在报错**：每 4 小时（00/04/08/12/16/20 点整）
   `校验后做种 遍历异常：从下载器获取种子列表失败` —— 但它两个辅种任务（01:45 / 02:34）
   **都是成功的**，说明失败的是**另一个内置任务**，与辅种无关。今天 12:00:01 那两次
   正好撞在我们批次启动的同一秒。
3. **不要用 `cn_sites.json` 的 `cookie` 字段判断「IYUU 查不查某站」**：
   16 个启用站里只有 8 个 `cookie` 非空（`nanyangpt`、`hdarea`、`hdtime` 都是空）。
   要么 IYUU 有别的凭据来源，要么**快照会脱敏** —— 未核实，**别据此下结论**。

##### ⚠️ 本次犯的错，记下来当教训

侦察脚本为了看站点结构把 `options` 原样打了出来 —— **`options` 里装着明文 passkey**
（btschool / nanyangpt / hdfans 各一个），于是三个 passkey **被打印进了会话记录**。
**没有外传**（只落在本机会话文件），但违反了本项目「凭据绝不出现在聊天里」的规矩。
- **教训**：脱敏要按**「值长什么样」**兜底（如"32 位十六进制"），
  不能只按**「键名叫什么」**匹配 —— `options` 这个键名一点都不敏感。
- 脚本已改为只打 `options` 的键名和「有值/空」。

##### ★ 由此定下的策略（2026-09-12 13:00，用户拍板）

> 「拆包项目是小项目，不能耽误别的那么多站的做种。**原则是从少量站点把小包做上种，
> 然后再通过 IYUU 扩散。扩种压力集中在这三个站点就好了。**」

于是分工是：**cross-seed 只在 3 个「源站」做 Torznab 搜索把种子做上，
IYUU 负责向其余十余站扩散。**

**第三个源站选 HDtime**，理由是三个条件同时成立、且都不是猜的：
1. **Prowlarr 里已经配好且启用**（`id=1`）→ 不需要任何新凭据、不需要动 Prowlarr，
   只差把它写进 `.env` 的 `TORZNAB_URLS`（`/1/api` 用的是**同一个应用级 apikey**，
   已在 `.env` 里）；
2. **IYUU 也管它**（在那 16 个站里）→ 符合"扩散"分工；
3. ★ **IYUU 还没在对它扩散成功** —— qB 里出现的外来 tracker 是
   keepfrds / btschool / m-team / hdarea / pterclub / muxuege / hdsky / springsunday
   （**没有 hdtime**）。选一个 IYUU 已扩散的站（如 BTSCHOOL）等于让 cross-seed
   去干 IYUU 已经干完的活。

> ★ **「最后一个 410」的收尾**：`.env` 已改为 3 条目
> （备份 `.env.bak.hdtime-20260912-130915`，7684 字节，与原文逐字节相同）。
> ✅ **2026-09-12 13:12 已重建生效**：`up -d --no-deps --force-recreate cross-seed`
> → 回读容器内 `TORZNAB_URLS` 条目数 = **3**；启动日志 `Your configuration is valid!`
> 且**三个索引器一条错都没报**（HDtime 若 feed 有问题会像另两个那样被点名）。
> ⚠ **首搜爆发**：cross-seed 的搜索资格按 (种子, 索引器) 逐对记录，
> HDtime 是**新索引器 → 库里每部片子对它都"从没搜过"**，接下来几批会补搜积压。
> 这正是 `alert_blocked_indexers()` 该发挥作用的时候 —— **收到 `indexer-blocked:HDtime`
> 的告警就说明它吃不住**。

#### 16.6.4 还没查的（~~原样保留~~ → 1、2 已答，见 §16.6.3）

1. ~~IYUU 是否在跑、注入到 qB 的**哪个分类 / 哪个目录**~~ → **在跑；注入我们的 qB
   （`:3060`）；站点如 §16.6.3**。⬜ **仍未查**：用哪个**分类 / 保存路径**
   （`cn_client.json` 里 id=6 的 `save_path` 和 `torrent_path` **都是空**，
   这本身值得留意 —— 空 save_path 会不会让注入的种找不到文件？未验证）；
2. ~~若共用：它查不查我们这两个站~~ → **查，就在那 16 个站里**，见 §16.6.3；
3. ~~**HDtime 那 8 次查询是谁发的**~~ → **大概不是 IYUU**（它绕过 Prowlarr），
   最可能是 Prowlarr 自身，**待证实**（§16.6.3）。

★ 一条口径提醒（**别拿 B 的数字去比大小**）：`numberOfQueries` 是不是"近 24 小时"
**尚未核实**（Prowlarr 的统计窗口可能是自启动/自上次重置起算的累计值）。
`disagrees` 只判「一边有、一边是 0」，**正好对窗口口径不敏感** ——
这是那个设计少数几种"歪打正着"的健壮性，**别改成比大小**。

**可能的处置**（等查完再定，现在不预设）：给 IYUU 单独分类或单独 qB 实例；
或把它的查询量纳入台账口径；或至少在日报里注明"本台账不含第二来源"。

★ 记一条方法论：**这套系统的所有数字都建立在"只有我们在用这些站"这个隐含前提上。**
前提从没被写下来过，直到今天看到那几个不属于我们的 tracker 域名才想起来问。
**凡"我们自己的统计"，都该先问一句：还有谁在动同一个东西？**

#### 16.6.5 ★★ 两个「看着像事实、其实是观测工具坏了」的发现（2026-09-12 13:30）

用户的原话是 **「目前只有红豆饭拆包成功，iyuu 扩散的也都是红豆饭已有的种子」**。
顺着这句去查，先撞上 ENOENT，再撞上真正的根因。**两个都记在下面，因为它们的教训是同一类。**

##### 一、ENOENT 是虚惊 —— cross-seed 自己的善后清理 vs. 它自己的并发

`error.log` 里反复出现 inject 阶段读不到它**自己刚写下**的 `.torrent`。
先前的判断是「每一条都等于一个跨种没注入成」，**这是错的**。

事实链（全部可在日志里对齐时间戳）：

1. cross-seed 在**注入成功、且该种在 qB 里已完整**之后，会删掉 `/config/cross-seeds/`
   里的存档 `.torrent`。这行**只写在 verbose 级** ——
   09-12 的 info 日志里 `Deleting` **0 条**，verbose 里 **384 条**。
   只看 info 的话，文件就是"凭空消失"。
2. webhook 会触发**并发的**新 inject 阶段，而它在**开头**就把目录扫成一份清单
   （`[inject] Found N torrent file(s) to inject in /config/cross-seeds`），
   然后**逐个**打开。清单里的文件若在这期间被另一路删掉 → `open()` → ENOENT。
3. 配对的铁证：未麻的部屋 `[787075f7]` 在 `09:40:07.016` 被删，
   ENOENT 落在 `09:40:07.336` —— **相差 320 ms**；同一文件还被删了两次
   （09:40:07 与 09:40:11），正是两路并发各删一次。

**结论：ENOENT 的种早已注入、且已完整，丢的只是一份没用的存档。**
★ 更重要的副产品：**NanyangPT 的跨种一直在正常工作。**
09-12 单日 webhook 路径 `- injected` 统计：

| 站 | `- injected` | `- exists` |
|---|---|---|
| HDFans | **121** | 371 |
| NanyangPT (南洋) | **105** | 173 |
| HDtime | 0（13:12 才加进 `.env`，日志到 13:12 为止，正常） | 0 |

所以「只有红豆饭拆包成功」**不在 cross-seed 这一层**。

⬜ 低优先的收尾：`Deleting` 只记 verbose，等于这条清理路径在 info 级是隐形的；
可在 `cross-seed/config.js` 里让它出个 info 级汇总。

##### 二、★★ 真正的根因：`_RE_FOUND` 的站名正则，**吃不下带空格的站名**

`orchestrator/state.py:264`：

```python
r"\[(?:webhook|inject)\] Found (.+?) \[([0-9a-f]{8})\.\.\.\] on (\S+) by (\w+) from dataDir \((.+?)\) - (.*)$"
#                                                                          ^^^^^
```

`on (\S+)` 只吃到**非空白**为止。而 Prowlarr 里的站点显示名**可以带空格和括号** ——
我们的南洋就叫 **`NanyangPT (南洋)`**。于是它捕获到 `NanyangPT`，
紧接着正则要求 ` by `、实际却是 ` (南洋) by `，**整行静默不匹配**。
HDFans / HDtime 名字里没空格，毫发无伤 —— 这正是它一直没被发现的原因。

实测漏检率（对真实日志）：

| 日志 | Found 行总数 | 现有正则认出 | 漏掉 |
|---|---|---|---|
| `info.2026-09-11.log` | 399 | 308 | **91，100% 是南洋** |
| `info.2026-09-12.log` | 770 | 492 | **278，100% 是南洋** |

**后果链**：`parse_log` 丢行 → `facts.found` 里没有南洋 →
`state.py:1947` 的 `matched = [(h, "|".join(found_idx)) for h in hashes]` 取不到南洋标签 →
`movie.matched_indexers` **永远只有 HDFans**。

据库实测（605 部）：`matched_indexers` 里 **HDFans 215 部、南洋 0 部**；
但同一批片在 `indexer_seen`（南洋 452）和 `attempt.indexers`（南洋有 matched/seeding 行）里
**都在** —— 因为那两处走的是 cross-seed.db 与搜索记录，**不经过这个正则**。
所以是**一个字段瞎了**，不是南洋不行。

★ **影响面（想清楚再定优先级）**：

* 影响：`matched_indexers` 这一列 → `report` 的站点归属、`trend()` 的**按周 × 按站**换站决策表。
* **不影响 `stage`** —— `compute_stage` 只看计数，不碰站点标签；
* **不影响重搜** —— `next_retry_at` 走 `indexer_seen`，另有来源。
* 也就是说：**做种一直在做，只是台账把它记成了红豆饭的。** 这也解释了 §16.3 那个
  「`matched_indexers` 是空的、只能退到 `attempt.indexers`」的现象 —— 同一个根因的另一面。
* ⚠️ 它还会**反向污染**：一部其实在南洋匹配到的片，只要同目录还有一行 HDFans 解析成功，
  整条 `matched_indexers` 会被写成 `["HDFans"]` —— **把南洋的功劳记到红豆饭头上**。

**修法**：`on (\S+) by` → `on (.+?) by`。
后面 ` by (\w+) from dataDir \(` 是硬锚点，非贪婪的 `(.+?)` 不会越界吃到下一个 ` by `。
验证三步都过了：

1. 复跑上表 → **漏 0 条**（399/399、770/770）；
2. 用**真实 `parse_log`** 跑全天日志 → `found` 里 HDFans 399 / **NanyangPT (南洋) 255**，
   且同一目录能同时归到两个站（如「寻梦环游记」→ `['HDFans', 'NanyangPT (南洋)']`）；
3. `py_compile` 通过。

✅ **已 `deploy.sh --apply` 落到 NAS**（备份 `.deploy-backup/20260912-132505`），
`orchestrator/state.py` 与 `drive-loop/orchestrator/state.py` **两个目标都已回读一致**
（第 271 行）。**drive-loop 下一批次 import 时即生效，不需要重建容器。**

★ **教训（和 §17.5.1「农场路径认不出来」是同一个形状）**：
**解析器只在自己见过的样本上被验证过。** 站点名、路径、发布日期 —— 任何一个"当时以为
不会带空格/括号/特殊字符"的字段，都是一个**静默丢数据**的口子，而且**只在解析结果上看得出来，
在程序上不报错**。以后凡是"从日志里抠字段"，先拿**真实日志的全体样本**过一遍，
数一数"匹配上的 / 没匹配上的"，别只看匹配上的那些。

---

## 17. 首次真跑的探针发现（2026-09-12 凌晨）—— 两个疑点

首次由 **DSM 计划任务**驱动、在 NAS 上跑完的完整批次（23:51:28 → 00:17:47），
顺手把整条链路探了一遍。**跑通了，但探出两件必须记下来的事。**

### 17.1 先记好的：这批是成功的 ✓

| 事实 | 证据 |
|---|---|
| 批次跑完 | 23:51:28 → 00:17:47（**26 分钟** = 50 部 × `--interval 30s` ≈ 25 分钟 + 回灌） |
| 发送正常 | `发送完毕：成功 50 / 失败 0，退避等待 0.0 分钟（0 次）`（00:16:00） |
| **通知端到端打通** ✓ | `已投递通知(batch) → dc-collection 本批完成`，spool 里落了文件、被 drain 取走 |
| 心跳正常 | `heartbeat_ts` 全程每 60s 一跳（23:51:28 起算，15 分钟时正好第 15 跳） |
| 跨进程节流正常 ✓ | 00:01:57 / 00:17:53 两次唤醒都正确打出「跳过本轮」 |
| **计划任务真的自动触发了** ✓ | 这是第一次由 DSM 触发（不再是手动点"运行"） |

### 17.2 ★ 疑点一：`attempts.log` 里的 `exit=127 (no python)` 是**假象**

**现象**：23:51 那批**没有 `exit=` 行**（只有 `start`）；26 分钟后突然冒出一行

```
[2026-09-12 00:17:47] exit=127 (no python: /usr/bin/python3)
```

—— 而 **5 秒后**（00:17:52）同一个脚本又能正常找到 python 并跑起来。

**已验事实**：

- `run.sh` 的 mtime = **00:02:57**，**正落在这一批的运行窗口（23:51:28–00:17:47）之内**；
- `deploy.sh:157` 用的是 `cp -p "$SRC" "$DST"` —— **原地截断重写同一个 inode**，
  **不是**"写新文件再改名"；
- python 侧一切正常：状态文件里 `running_pid: null`、`last_end_ts` = 00:17:47、`consec_abort: 0`，
  且批次的 batch 通知**正常写进了 spool**。

→ **极可能**：`sh` 是**边读边执行**脚本的。脚本被 `cp` 原地换掉之后，
它接着从**旧偏移**去读**新文件**的字节 → 执行到一段错位的代码（正好是 `[ ! -x "$PY" ]` 那个守卫）
→ 于是写下一个**假的** `exit=127`，且**永远没写真正的 `exit=0`**。

★ 这与 **§14.3 的 `.cmd` 行尾坑是同一类**（"字节块读取"导致解析错位），
只是这次的触发源不是行尾，而是**部署覆盖了正在运行的脚本**。

★ 为什么 python 没事：**CPython 启动时一次性把源码读完**，之后文件怎么改都无影响 ——
**只有 shell 会中招**。这条不对称正好解释了"为什么只有一个假 exit 行"。

**动作**：
1. `deploy.sh` 改成"先写 `$DST/$f.new`，再 `mv -f`"（**原子替换 = 新 inode**，
   正在运行的进程继续读旧内容）；
2. 运行期别 deploy —— README 已有同类提醒（「重建会打断正在跑的 drive，务必等当前批次跑完」）。

⚠ **上述机制尚未复现**，先按最可能处理。但**判据本身已经够用**：
`attempts.log` 里**同一次 `start` 没有配对的 `exit`** 时，先怀疑"脚本被换过"，别急着信那个退出码。

### 17.3 ★ 疑点二：这批**一条搜索记录都没产生**，回灌却把 26 部降级了

> # ✅ 已结案（2026-09-12 上午）—— 两条都已修复并验证，见 **§17.5**
>
> 本节**保留原样**（DEBUG 层要留下"当时是怎么误判的"），但下面两处**待验假设已被推翻/补全**：
> - 降级那条的真根因**不是**回灌链路，是 **v3 农场路径认不出来** → §17.5.1
> - `backoff_hits=0` 的真根因**不是**（只是）`until > now` 的过期判定，是**检查间隔 300s 比退避窗口 55s 还长** → §17.5.2
>
> 本节末尾「下一步（未执行）」两条**都已执行完毕**，结论见 §17.5.1。

**已验事实**（全部**直读**，未 `cp` —— 见 §13.6 坑 2）：

| 探测 | 结果 |
|---|---|
| cross-seed `timestamp` 表 | **726 行，全部是 2026-09-11**；**09-12 一行都没有** |
| `decision` 表 | 267 行 / 163 个唯一 hash |
| `decision ∩ qB` | **160 = qB 里全部种子**（cross-seed 与 qB **完全一致** ✓） |
| qB `reseed-singles` | **160 条，全是 `stalledUP`** |
| 状态机 `matched_hashes` 非空 | 只有 **13** 部 |
| 状态机 `stage=SEEDING` | 只有 **13** 部（README 里记的曾是 FRDS 76 / DC 19） |
| 本轮通知 | `新增做种 -26`（**负数**），而 **`backoff_hits=0`** |
| `indexer` 表 | HDFans = **`RATE_LIMITED`**；另有两条 `name` 为 `NULL` |

**cross-seed 日志给出的答案**（verbose，**313 行同一句式**）：

```
[webhook] Did not search for …/Sweet.Tooth.S01E01.….mkv | MediaType: EPISODE - it is a season pack episode
```

→ 这是 cross-seed 的**正常行为**：**季包里的单集文件不单独搜**，只搜季包目录。
所以这些"没搜"**既不是故障、也没浪费额度** —— 不用去修。

**但仍然是问题**：33 次 `Found 0 torrents`（确实发出了搜索）之后，
**`timestamp` 依然一行没加**。**这一点没解释通。**

**两个已成立的后果**：

1. ★ **状态机把 26 部其实在做种的片子降级了**：现在全库只剩 13 部 `SEEDING`，
   而 qB 里明明有 **160** 部在做种。→ 这些片子过了重搜周期会被**重复搜**，
   **白烧站点额度** —— 而额度正是本项目最高优先要省的东西。
2. ★ **`backoff_hits=0` 但 HDFans 是 `RATE_LIMITED`** —— 退避检测没触发，
   与 §11.8 宣称的"每 `--check-every` 条读一次，撞上 `RATE_LIMITED` 就**睡到解禁**"不符。
   **待验假设**：`BlockingBackoff.active` 要求 `until > now`，
   若 `retry_after` 已过期就判为"不算退避"→ 直接放行 → 50 条请求打出去。

**下一步（当时按性价比排的）—— 两条都已在 §17.5 执行完毕**：

1. ~~先跑一次**带 `--qbit-url` 的回灌**~~ ✅ **已跑** —— `SEEDING` 从 13 回到 **21**（只回灌、没解决路径问题，所以只捞回一点点）。真正的修复见 §17.5.1，之后 **21 → 201**。
2. ~~再查 `blocking_backoffs` 为什么不认 HDFans~~ ✅ **已查清并修掉** —— 见 §17.5.2（根因不是 `until > now`，是**检查间隔比退避窗口还长**）。

> ★ 这两条**确实**是"真的会持续消耗额度"的问题（状态机认不出"在做种"→ 重复搜 → 额度白烧），
> 而不只是簿记问题 —— 现在两条都堵上了。§16 的四条新功能可以照常往后排。

### 17.4 已落地的代码改动：`deploy.sh` 改成**原子替换**（2026-09-12 00:3x）

**改哪**：`deploy.sh` 的两处写盘点 —— 主同步循环 + `--rollback` 的恢复循环。

| 之前 | 现在 |
|---|---|
| `cp -p "$SRC/$s" "$DST/$d"` | `cp -p "$SRC/$s" "$DST/$d.new.$$"` 然后 `mv -f "$DST/$d.new.$$" "$DST/$d"` |

`mv` 是同文件系统的 `rename()`，**换 inode** ——
正在运行的 `sh` 手里那个 fd 仍指向**旧 inode**，它会安安静静把自己那份读完；
新起的进程看到新内容。`cp -p` 先把权限位（`755` 这类）搬过去，`mv` 再整体带过去，所以可执行位不丢。
失败时用 `trap` 清掉残留的 `*.new.$$`。

**为什么必须这么改**（§17.2 的根因）：`sh` 是**边读边执行**脚本的。
`cp` 覆盖是**原地截断 + 重写同一个 inode**，正在跑的那份脚本下一次 `read()`
就会拿到**新文件的字节**，而它的偏移是**旧文件**的 → 从中间某处开始执行 → 执行到错位的代码。
实测症状：`attempts.log` 里一条**假的** `exit=127 (no python: /usr/bin/python3)`
（那批的 python 好得很，`last_end_ts` / `consec_abort=0` / batch 通知全都正常），
而真正的 `exit=0` **永远不写**。

> ★ 与 **§14.3 的 `.cmd` 行尾坑**同源：都是"**脚本被字节块读取**"。
> 差别的只是触发源 —— 一个是行尾，一个是**部署覆盖**。
>
> ★ **python 为什么没事**：CPython 启动时**一次性读完整份源码**再编译，之后文件怎么改都无影响。
> 所以"同一个目录、同一次部署"，只坏 shell 不坏 python —— 这条不对称本身就是佐证。

**顺带加的一道提示**：`deploy.sh` 在写入前会读 NAS 上的
`drive-loop/scripts/.drive-loop.state`，若 `heartbeat_ts` 在 **600s 以内**
就打印一行「**有批次正在跑**」的告警（不阻断）。
判据用的是**心跳新鲜度**（批次运行期间每 60s 刷一次），读不到就**不提示** ——
宁可不提示，也不要误报。原子替换之后本来就不会再打坏在跑的那批，
这道提示是为了让操作者知道「**你看到的仍是旧行为**」。

**验证**：`bash -n deploy.sh` 通过；行尾保持纯 LF（`CRLF=0`）。
本次改动**不需要部署到 NAS** —— `deploy.sh` 本身不在白名单里，它在本地跑。
`bash deploy.sh` 复查结果：`✓ 生产与本地一致，无需同步。`


#### 17.4.1 顺带堵上的一个口子：`DST` 被 `scripts/.nasrc` **静默覆盖**

**怎么发现的**：为了验证上面的原子替换，想拿个临时目录做演练 ——
`DST=$TMP bash deploy.sh --apply`。结果它打出 **「生产与本地一致」**（临时目录明明是空的）。

**原因**：脚本原先是

```bash
SELF_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
[[ -f "$SELF_DIR/scripts/.nasrc" ]] && source "$SELF_DIR/scripts/.nasrc"   # ← 这里把 DST 覆盖了
SRC="${SRC:-$SELF_DIR}"
DST="${DST:?...}"
```

`.nasrc` 里写着 `DST="//iSunker-DS423/..."`，而 `source` 是**直接赋值**，
赋值又排在环境变量之后 —— 于是**命令行给的值被配置文件吃掉**，
"在沙箱里试一下"实际是**对着生产 NAS 跑**。（本次没造成后果：CHANGED 为空，一个文件都没写。）

**修法**：`.nasrc` 的定位是**默认值**，不是**强制值**。先把外部给的值存下来，`source` 完再恢复：

```bash
_DST_FROM_ENV="${DST:-}"
[[ -f "$SELF_DIR/scripts/.nasrc" ]] && source "$SELF_DIR/scripts/.nasrc"
DST="${_DST_FROM_ENV:-${DST:-}}"
```

> ★ 同类口子在其它脚本里**没有排查过** —— `run-batch.sh` 也 source 同一个 `.nasrc`。
> 目前它的值（`NAS_HOST` / `NAS_NAME` / `DST`）都不是可覆盖的参数，**暂无实际影响**；
> 但以后要往 `.nasrc` 里加"也接受命令行覆盖"的键时，记得**先存后 source**。

#### 17.4.2 沙箱实测（三个分支都跑过）

用临时目录当 `DST`（**修好 17.4.1 之后**才可能这么做）：

| 场景 | 期望 | 实测 |
|---|---|---|
| 首次写入（目标不存在） | 23 个文件全部落地 | ✅ 23 个 |
| 目标已存在且有差异 | 走 `cp`+`mv`，内容与源一致 | ✅ `cmp` 一致 |
| 权限位 | `755` 不能丢 | ✅ `-rwxr-xr-x` |
| 残留临时文件 | 0 个 | ✅ 0 个（`trap` 兜底） |
| `heartbeat_ts` 很新鲜（模拟批次在跑） | 告警、**不阻断** | ✅ 打出「有批次正在跑」后继续 |
| `heartbeat_ts` 很旧（批次已结束） | 不告警 | ✅ 静默 |
| 没有 `.drive-loop.state` | 不告警 | ✅ 静默 |

> 演练产生的 4 个空/假备份目录已从 `.deploy-backup/` 删掉，**没留在部署历史里**。

> ⚠ 上面这条警告写的时点是 §17.4 完成时 —— **§17.3 的两个问题随后已修复**，
> 见下一节 §17.5。

### 17.5 ✅ §17.3 两个疑点的根因与修复（2026-09-12 上午）

两条**都已修复并验证**，且**互不相干** —— 一条在**路径匹配**，一条在**检查节奏**。
先把结论摆出来，再给证据。

| §17.3 的观察 | 真根因 | 修法 |
|---|---|---|
| 状态机 `SEEDING` 塌到 13，qB 里 160 在做种 | v3 农场切换后 cross-seed 报的是**农场路径**，而 `pack.roots` 还是原路径 → `_resolve_searchee_to_pack()` 把一切判成「别的包」**静默跳过** → `matched_hashes` 空 → 推导出的 `stage` 必然全部降级 | `pack` 表加 `farm_root` 列 + 农场路径解析分支 |
| `backoff_hits=0` 但 HDFans 是 `RATE_LIMITED` | 检查间隔 `check_every × interval` = 10 × 30s = **300 秒**，而实测退避窗口只有 **30~60 秒** → 窗口整段落在两次检查之间 | 加**按秒**触发（`--backoff-check-secs`，默认 60）+ 按 `retry_after` 变化认定「新退避」 |

---

#### 17.5.1 根因一：农场路径认不出来（`state.py`）

**为什么完全无声**：`SEEDING` 是**推导**出来的（`seeding_count = |matched_hashes ∩ qB|`）。
`matched_hashes` 来自 cross-seed 的 `decision` 表、按 **searchee 路径**索引；
路径对不上 → 查不到 → 归类成 `other_pack` → **跳过**。
**不报错、不告警**，只是数字变小 —— 正是无人值守最怕的坏法。

**改动**（全在 `orchestrator/state.py` + CLI）：

| 位置 | 改了什么 |
|---|---|
| `pack` DDL + `_migrate()` | 新增 `farm_root TEXT`（老库自动 `ALTER` 补列） |
| `_farm_mirror(path, roots, farm_root)` | 把登记的原路径换算成农场镜像：`<root>/<一级>/<其余>` → `<farm_root>/<一级>/<其余>` |
| `_resolve_searchee_to_pack(..., farm_root=)` | 农场路径按 `dir_paths` 的**镜像键**认领；根传 `[]` —— **不做单根回退猜测**，只认确实登记的 |
| `sync_pack()` | `dpaths.update(store.farm_dir_paths(pack))` |
| `scripts/reseed-state.py` | 新增 `farm` 子命令：`farm --pack X` 看现状 / `--farm-root Y` 设置 / `--clear` 清除 |

**三层验证**：

1. **离线断言** 15 条全过（`tests/test_farm_root.py`）
2. **只读模拟真库**：镜像覆盖 frds **486/486**、dc **115/115**、mbf **4/4**；
   **0 个 searchee 被两个包同时认领**；**0 个认不出**
3. **真跑 `sync`**：**`SEEDING` 21 → 201**，并证明 **201 就是理论上限** ——
   278 个 qB 种子 → 201 个唯一 `(pack, dir_name)` 对；与 DB 的 `SEEDING` 集合**双向差集都为 0**

阶段总数 **605 不变**：`PENDING` 277→213 · `UNMATCHED` 307→190 · `MATCHED` 0→1 · `SEEDING` 21→201。

> ★ `SEEDING 21` 是「补跑一次带 `--qbit-url` 的 sync」之后的**中间值** ——
> 那一步只把 qB 状态灌回来，没解决路径问题，所以只从 13 回到 21（=§17.3 下一步的第 1 条）。
> 真正的修复是 `farm_root`，之后才到 201。

**两条不是 bug 的观察**（记下来免得下次白查）：
农场里有 **1 条**（`0观影清单chrlee整理`）**不属于三个包中的任何一个**；
**9 行** `decision` 没有对应的 `searchee_paths` 条目，会退回**按名字匹配**。

---

#### 17.5.2 根因二：退避窗口比检查间隔还短（`state.py`）

§17.3 当时猜的是「`active` 要求 `until > now`，过期就放行」—— **猜对了一半**，
真正让它**永远看不见**的是**检查间隔**：

```
info.2026-09-12.log   08:16:19  Failed to reach NanyangPT (南洋): code 429 ...
                                snoozing until 2026-09-12 08:17:14
```

窗口 **55 秒**，而 `check_every(10) × interval(30s)` = **300 秒**才看一眼。于是：

- 每次看过去时 `until` **都已过期** → `active=False` → 既不等待、也不计数
- 2 天里 5 次限流**无一被记上** → `backoff_hits` 恒 0 → 下游 `next_sleep()` 永远收不到"站点在限流"

**改动**：

| 改了什么 | 为什么 |
|---|---|
| 检查**双触发**：条数（`--check-every`）+ **秒数**（`--backoff-check-secs`，默认 60） | 短退避才可能被撞上 |
| `retry_after` 与上次不同 → 认定「**新发生了一次退避**」，**哪怕窗口已过也记账** | 它确实发生过，是"站点在限流"的真信号 |
| **基线**：进程刚起第一眼**只建基线、不计数** | 库里常年躺着过期残值（`status=RATE_LIMITED` 但 `retry_after` 早过），当成"新发生"会让**每批开头都白记一笔** |
| `IndexerBackoff` 读 `indexer.active` 列 —— **被禁用的索引器不挡路** | 否则已从 `TORZNAB_URLS` 移除的站，留着一条未来的 `retry_after` 就能**卡死循环**（`active=1` 的两行恰好就是 `/2` `/4`） |
| 时钟可注入（`now` / `monotonic`） | 否则这条路径**根本没法测** |

**验证**：`tests/test_backoff.py` 15 条断言，含 **08:16 那次 55 秒窗口的完整复刻**。

---

#### 17.5.3 检出之后：`next_sleep()` 从「命中就罚 2 小时」改成**按时长分级**

修好检测暴露了一个**连带后果**：`next_sleep()` 里那条
`backoff_hits > 0 → 2 小时` **从死代码变成了会生效的策略**，而它是**布尔**判断 ——
站点打 55 秒喷嚏，和站点持续压 30 分钟，被**同等对待**。

改成按这批**实际等掉的时间**（`waited_sec`）分档：

| 等待时长 | 下批间隔 |
|---|---|
| < 3 分钟 | **45 分钟**（喷嚏，不惩罚） |
| 3 ~ 10 分钟 | **90 分钟** |
| ≥ 10 分钟 | **2 小时** |

`still_skipped > 0` **不参与分级**（它有片子真没推进，是**结果问题**，仍一律 2 小时）。
★「**等了 0 秒却记了一笔**」是**故意**的：那来自「窗口落在两次检查之间、我们压根没等」的限流 ——
记进 `backoff_hits` 供观测，但**不该改间隔**。

**验证**：`tests/test_next_sleep.py` 17 条断言（三档边界 + 单调性）。

---

#### 17.5.4 ★ 顺手发现：`next_sleep()` 在 `--once` 模式下**压根没接线**

这是复查时发现的**独立缺陷**，**比分级本身重要**。

**现象**：`next_sleep()` 的返回值**只进日志**，没有任何人用它。`--once` 模式下真正的闸门是
`once_round()` 里**写死**的常量：

```python
min_sleep = args.min_sleep or MIN_SLEEP        # → 1800 秒
...
if last_end and gap < min_sleep: 跳过本轮
```

而 `finally` 里写回状态文件的是 `{running_pid, last_end_ts, last_pack_idx, consec_abort}`
—— **没有间隔**。

**证据**（`drive-loop.log`）：每一批都打印「下次间隔 **45 分钟**」，实际间隔却是
`00:17 → 01:33 → 02:42 → 03:42 → 04:42 → 05:42 → 06:41 → 07:42 → 08:52`（**45~70 分钟**）——
由「DSM 每 15 分钟敲门 + 30 分钟闸门」算出来的，**跟那 45 分钟毫无关系**。
`09:00` / `09:15` 两次唤醒都被「距上次批次结束仅 7.6 / 22.6 分钟」挡回去。

→ 所以「**站点在退避就缓一缓**」这条策略**从来没生效过**；`next_sleep()` 在 NAS 上是**装饰性的**。
（它真正生效的只有常驻模式 `python drive-loop.py`——而 NAS 跑的是 `--once`。）

**改动**：把结论**落盘**到 `.drive-loop.state` 的 `last_sleep_sec`，闸门改成
`clamp(max(min_sleep, last_sleep_sec))`。

| 细节 | 为什么 |
|---|---|
| `log_result()` 从 `-> None` 改成**返回**间隔 | 原来算完就扔 |
| 本批**无动作 / 异常** → 写 `0`，退回下限 | **否则一笔旧退避会把系统永久卡在 2 小时** |
| `clamp()` 之前是**死代码**（定义了没人调用） | 现在真的用它兜住 4 小时上限 |
| `finally` 的 `write_state` **整体覆盖**、不合并 | 顺带清掉 `heartbeat_ts` —— 残留心跳会让下一轮误判「上一批还在跑」 |
| 过渡安全 | 老状态文件**没有这个键** → 读出 `0` → 闸门 = 30 分钟，与改动前**完全一致** |

**验证**：`tests/test_once_gate.py`。其中两条是**专门钉住无人值守失败模式**的：
①「无动作批会把旧退避清成 0」；②「`heartbeat_ts` 跑完必须被清掉」。
这两个都是"**不报错、只是不动**"的形状，专门钉死。

> ★ 这意味着**分级现在才真正生效**。按 2 天 5 次限流、且窗口只有 30~60 秒来看，
> 绝大多数会落在 **45 分钟档**（喷嚏）；只有站点确实压过 10 分钟以上才会等到 2 小时。
> 两个阈值是 `next_sleep()` 上面那两行常量（`BACKOFF_SHORT_SEC` / `BACKOFF_LONG_SEC`）。

---

#### 17.5.5 部署与回滚

三次 `deploy.sh --apply`，每次只动 1~2 个文件：

| 备份目录 | 内容 |
|---|---|
| `.deploy-backup/20260912-090628` | 退避**检测**（`state.py` / `reseed-state.py` / `drive-loop.py`） |
| `.deploy-backup/20260912-092254` | 退避**分级**（`drive-loop.py`） |
| `.deploy-backup/20260912-092447` | 闸门**接线**（`drive-loop.py` + `run.sh` 注释） |

回滚：`bash deploy.sh --rollback`。

> ★ 三次都挑在**批次间隙**执行（先确认状态文件 `running_pid=null`）——
> `run.sh` 是 **shell 脚本**，运行中被覆盖会**从旧偏移读到新内容**（§17.2 / §14.3 同源）。
> 原子替换只是让"换文件"这一步安全，**没让"换在什么时候"变安全**。

> ★ **新增的 CLI 参数**：`--backoff-check-secs`（默认 60，`drive` 与 `drive-loop` 都有）；
> `reseed-state.py farm` 子命令。`farm_root` 的用法见 §11.7 那类操作手册位置。

---

### 17.6 ✅ 跳过文案在**断言一个没有依据的原因**（2026-09-12 上午）

#### 17.6.1 症状：同一批的两行日志自相矛盾

11:12:22 那批跑完，紧接着 11:15:02 被闸门挡下。日志里相邻三行：

```
11:12:22  [dc-collection] 计划 50 条，发出 50 条 … | 原因：无退避、无新增（正常） | 下次间隔 45 分钟
11:15:02  距上次批次结束仅 2.7 分钟（< 45 分钟：上一批报告站点在退避），跳过本轮
```

上一行说**无退避**，下一行说**在退避**。**行为没错**（闸门确实该按 45 分钟挡住），
错的是**文案**。而这一行一天要出现很多次（09-12 的 10:00 / 10:15 / 10:30 / 11:15 四次全是），
往后真出限流时，它会把排查往错误方向带 —— 这是**比不打印更贵**的日志。

#### 17.6.2 根因：判据用的是「硬下限」，而健康档本来就高于硬下限

```python
wait = clamp(max(min_sleep, last_sleep))
if last_end and gap < wait:
    if wait > min_sleep:            # ← 就是这里
        LOG.info("…（< %.0f 分钟：上一批报告站点在退避），跳过本轮", …)
```

`next_sleep()` 的档位是：健康 `BASE_SLEEP`=**45 分钟**、`SNOOZE`=90、`BACKOFF`=120、`ABORT`=180；
而 `min_sleep` 的默认值是 `MIN_SLEEP`=**30 分钟**。于是判据
`wait > min_sleep` 在**完全正常的健康档也成立**（45 > 30）—— 健康档被一律打印成「在退避」。

★ **一句话**：它问的是「这次等待是不是**长过硬下限**」，而想表达的却是
「这次等待是不是**长过常态**」。两个问题在 `min_sleep < BASE_SLEEP` 时答案不同，
而默认配置**正好**是这个区间。

#### 17.6.3 修法：按 `last_sleep` 区分三档，让文案只说成立的话

```python
if last_sleep > BASE_SLEEP:      # 真退避档只可能是 90/120/180，都严格大于 45
    why = "上一批报告站点在退避"
elif min_sleep > last_sleep:     # last_sleep 还是 0（无记录）或被 --min-sleep 抬高了
    why = "按 --min-sleep 下限"
else:
    why = "按上一批算出的批间隔"
```

判据从「超过**硬下限**」改成「超过**常态**」—— 真退避档严格大于 `BASE_SLEEP`，所以这是
**只为退避成立**的条件。第三个分支是必要的：`--min-sleep` 被人为抬高时，
真正管事的是下限，既不是退避也不是上一批的间隔。

**自测**（`test_once_gate.py` 第 ⑧ 节，7 条）：健康档(45) **不许**出现「在退避」且必须说
「按上一批算出的批间隔」；`SNOOZE`/`BACKOFF`/`ABORT` 三档**必须**说「在退避」；
`--min-sleep` 抬高时归因下限。复现场景用的就是现场值：`last_sleep=2700`（健康档）
+ `gap=2.7 分钟`。

#### 17.6.4 ★ 顺带揪出：`test_quota_trend.py` 是**颗按钟点引爆的定时炸弹**

跑验证时 ⑬ 节挂了 —— `alert_blocked_indexers()` 返回 0 条告警。**跟本次改动无关**
（⑬ 走的是 `alert_blocked_indexers`，压根不经过 `once_round`），是自测自己的毛病：

| | |
|---|---|
| fixture | `NOW = datetime(2026, 9, 12, 10, 0, 0)` —— **写死**，NanyangPT 解禁 = `NOW + 1h` = **11:00** |
| 被测代码 | `alert_blocked_indexers()` 内部读的是**真实时钟** |
| 后果 | 真实时间一过 11:00，「正在退避」自愈成「已过期」→ 断言必挂。**上午还全过，11:00 整准时开始挂** |

★ 这类 bug 的特征：**改天跑、或者下午跑，结果就不同**。它平时不响，只在特定钟点响，
而且响的时候看起来像"真的是代码坏了"。

**修法（选了根因那一侧）**：`alert_blocked_indexers(args, *, now=None)` ——
把「此刻」变成入参，生产调用一律省略（默认真实时钟），自测传 `now=NOW` 把时间钉死。
另一条路（把 `NOW` 改成真实时间）只是**把炸弹换成慢引信**：依赖真实时钟的自测，
换个钟点跑还是会飘。

#### 17.6.5 部署

| 备份目录 | 内容 |
|---|---|
| `.deploy-backup/20260912-112306` | `drive-loop.py`（跳过文案判据 + `alert_blocked_indexers(now=)`） |

挑在批次间隙执行（先确认 `running_pid=null`；允许时刻 11:12:22+45min=11:57:22，
中间 35 分钟空窗）。生产副本与本地**字节一致**已 `cmp` 验证。

> ★ **不需要** `docker compose up` —— `deploy.sh` 结尾那段提示是**通用模板**，
> 但 drive-loop 跑在 **NAS 宿主机**上（`/usr/bin/python3`，DSM 计划任务），不在容器里。
> 改了 `drive-loop/` 下的东西，等下一次唤醒自然生效。

**验证**：四套自测全过 —— `test_quota_trend` 59 / `test_next_sleep` 17 /
`test_backoff` 17 / `test_once_gate` 22 = **115 条断言 0 失败**。
（`test_quota_trend` 恢复 59 条，之前显示 54 条是崩在 ⑬ **提前截断**了后面的断言。）

## 18. 目录布局调整：把 `reseed_farm` / `reseed_singles` 收进 `reseed/`

> 2026-09-12 下午讨论定案。**结论已定、命令已备，但尚未落地** —— 等一个没有批次在跑的时间窗。

### 18.1 先澄清一个误读：`reseed-farm` **从来不是**一个 qB 分类

起因是"为什么种子全在 `reseed-singles` 分类里，没有 `reseed-farm`"。答案是后者不存
在 —— 这两个名字只是"长得像"，扮演的角色正相反：

| 名字 | 是什么 | 配置项 | 直接子目录是 |
|---|---|---|---|
| `reseed_farm` | 目录（**输入**） | `DATA_DIRS` | 475 个发布名（`[路西法 第二季]…`） |
| `reseed_singles` | 目录（**输出**）**+ qB 分类** | `LINK_DIR` / `QBIT_CATEGORY` | `HDFans` / `NanyangPT (南洋)` / `BTSCHOOL` |

农场里**一条种子都没有**：它全是 `build-farm.sh` 建的硬链接，qB 里没有任何东西认识
它。所以不存在"落错了分类"，而是**农场没有分类可以落**；cross-seed 注入的种子，唯一
会打的标签就是 `QBIT_CATEGORY`。NAS 实测（2026-09-12）qB :3060 分类表只有一条：

| 分类 | savePath |
|---|---|
| `reseed-singles` | `/volume1/video/download/reseed_singles` |

★ ★★ **一处纠错（2026-09-12，动手前查 `tags` 才发现）**：这 500 条里 **100 条不是我们的** ——
它们的 tag 是 `IYUU自动辅种`，属于 **IYUU Plus**（见 §16.6.3）。按 `tags` 分开看：

| tags | `save_path` | 条数 |
|---|---|---|
| `cross-seed` | `…/reseed_singles/HDFans` | 249 |
| `cross-seed` | `…/reseed_singles/NanyangPT (南洋)` | 136 |
| `cross-seed` | `…/reseed_singles/BTSCHOOL` | 23 |
| `IYUU自动辅种` | `…/reseed_singles/HDFans` | **68** |
| `IYUU自动辅种` | `…/reseed_singles/NanyangPT (南洋)` | **32** |

> 本节初版在这里写的是"那 100 条是分类还没启用时早期试点注入的"—— **错的**。判据是
> "无分类"就猜成自己早期的运行，没有查 `tags`。**`reseed_singles/` 是 cross-seed 和
> IYUU 两套系统共用的目录**，后果见 §18.7 —— 这一条直接改变了迁移的可行性。

### 18.2 决定一：**加一层父目录**，不是**合并成一个目录**

最初提的是"两个文件夹合并成一个"。**否掉**，理由就是 §10.5.4 已经论证过的那三条，
它们在"合并"下会全部成立：

1. 农场自检把 cross-seed 建的链接当成孤儿 → `build-farm.sh --verify` **永久退出码 1**
   （§3568 / §3646 的假象检验实测过：报 475 条缺失 + 2 条孤儿）；
2. `dataDirs` 的直接子目录 = searchee → `HDFans/`、`NanyangPT (南洋)/`、`BTSCHOOL/`
   各变成一个**假 searchee**，每次全量白烧查询额度，且站越多垃圾越多；
3. 输入输出同树：`reseed_singles` 是 cross-seed 的**输出**，农场是它的**输入**。

改成**加一层父目录**：

```text
/volume1/video/download/
├── reseed/
│   ├── reseed_farm/       ← DATA_DIRS（输入）
│   └── reseed_singles/    ← LINK_DIR（输出）+ qB 分类
├── movies/  TV/  短剧/  ...
```

★ 关键：两者**仍然是兄弟** —— 农场依然不在 linkDir 里面，输入输出依然分离。所以
§10.5.4 那三条**一条都不适用**。这不是"合并"的折中，是另一个方案。

### 18.3 决定二：`reseed_singles` **不手动 `mv`**，交给 qB 的 `setLocation`

qB（:3060）实测有 **500 条种子，全部落在 `reseed_singles/` 下，只有 3 个不同的
`save_path`**：

| `save_path` | 条数 | 其中无分类 |
|---|---|---|
| `…/reseed_singles/HDFans` | 318 | 68（其中 68 是 **IYUU 的**）|
| `…/reseed_singles/NanyangPT (南洋)` | 168 | 32（其中 32 是 **IYUU 的**）|
| `…/reseed_singles/BTSCHOOL` | 14 | 0 |

★ 按 `save_path` 分组会**连 IYUU 那 100 条一起搬**。初版写的是"天然覆盖" —— 覆盖是
真的，但**覆盖到了别人的东西**。见 §18.7。

**为什么不让 NAS 上 `mv` 完再改 qB**：那会造出一个**中间态** —— 磁盘上文件已在新位
置、qB 还以为在旧位置，这期间 500 条全是"文件丢失"；而且这个态里到底谁去对账有两个
说法（源已不存在时的 `setLocation` 行为依版本而异）。**让 qB 自己搬，磁盘和它自己的
记账始终一致**，不存在对不上的窗口。

→ 所以：**`reseed_singles` 交给 qB**（`setLocation` ×3，因为只有 3 个 `save_path`）；
**`reseed_farm` 才在 NAS 上手动 `mv`**（它不在 qB 里）。

### 18.4 影响面（~~10 处全查过了~~ → **11 处**：漏了一处，见 §18.9.1）

**要改的 5 处：**（第 5 条是动手当天才撞上的，见 §18.9.1）

| # | 位置 | 改什么 |
|---|---|---|
| 1 | qB :3060 的 500 条种子 + 分类 savePath | `setLocation` ×3 + `editCategory` |
| 2 | `.env` 的 `DATA_DIRS` / `LINK_DIR` | 2 行（本地 `.env` 是事实源 → `gen-nas-env-update.py` 重新生成 `nas-update-env.sh` 再跑） |
| 3 | NAS `build-farm.sh` 的 `FARM` 默认值 | 1 行 |
| 4 | `drive-loop/hlink/state.db` 的 `pack.farm_root` | **3 行** UPDATE |
| 5 | **新父目录 `/volume1/video/download/reseed` 的属主 + 权限** | `sudo chown 1000:1000` + `sudo chmod 777`（理由见 §18.9.1）|

**不用改的 6 处（查过才算数）：**

| 位置 | 为什么不用改 |
|---|---|
| `compose.yaml` 挂载 | 是 `/volume1/video:/volume1/video` **整卷 1:1**，卷内挪目录不动挂载点 |
| `cross-seed/config.js` | 它从环境变量读 `DATA_DIRS`/`LINK_DIR`，不写死路径 |
| cross-seed 的历史记录 | `searchee` 表 951 行**只有 `name`/`first_searched`/`last_searched`，不存路径** → 重新扫一遍但**一次都不会重搜**，14 天冷却和历史全保住 |
| `build-farm` 的清单 | 清单名取自 `basename $FARM`（这层名字没变），内容是"发布名 + **源**路径"，不含农场路径 |
| `drive-loop` 的 webhook | 发的是 `movie.path` =**源大包**路径（`drive-loop.py:886`），根本不经过农场 |
| `state.db` 的 `movie.path` | 605 行存的也是**源**路径，不受影响（只有 `pack.farm_root` 3 行指向农场） |

### 18.5 遗留风险：一个**没实测过**的行为

qB 的 `setLocation` 在"内容已经在目标位置"时的行为，**没有实测过**，不同版本不一样。

★ 所以第一次**必须**先 `--limit 1` 只搬一条，确认那条 `state` 回到 `stalledUP`
（而不是 `missingFiles` / `error`）再上全量。这条不是保守，是因为这个行为没有依据可
查 —— 官网 `cross-seed.org` 被网络策略挡了，WebSearch 也没返回结果。

（相关的、同样没验证的一条：cross-seed 对"searchee 落在 linkDir 内部"有没有自动跳过。
这条只在"合并"方案下才要命（可能**静默全失效**），本方案下不触发。）

★ **2026-09-12 实跑**：本方案下 `setLocation` 的表现见 §18.9。§18.5 问的那个**具体情形**（内容**已经**在目标位置时）本方案不触发，**仍未实测**。

### 18.6 进度与待办

工具已备好：**`scripts/migrate-reseed-dirs.py`** —— 默认只读预检，`--apply` 落地，
`--limit` 支持试跑。已用 `--check` 实跑验证（500 条 / 3 个 save_path，退出码 0）。
文件顶部的注释就是完整 runbook。

执行顺序（**每一步都得在 NAS 上手动做，`22` 端口是拒的，没有远程 shell**）：

1. 挑时间窗：`heartbeat_ts` 不再跳 → DSM 任务计划里**临时禁用** drive-loop 任务；
2. `sudo docker compose stop cross-seed`（它正在往 `reseed_singles/BTSCHOOL/` 写新链接）；
3. `sudo mkdir -p /volume1/video/download/reseed`；
4. `sudo mv /volume1/video/download/reseed_farm /volume1/video/download/reseed/`
   （同卷 = rename，inode 不变，**硬链接关系完整保留**，瞬间完成）；
5. 改 §18.4 表里的 2/3/4 三处配置；
6. `sudo docker compose up -d --force-recreate cross-seed`；
7. `python scripts/migrate-reseed-dirs.py --limit 1 --all-tags --apply` → 验证 →
   `--all-tags --apply`（**全量 509 条，含 IYUU 的 100 条**；依据见 §18.8）；
8. 收尾：`build-farm.sh --verify` 退出码 0、`--check` 看 save_path 全落新根、抽查 state。

★ **实际执行记录、以及三个「只有真跑才会暴露」的坑，见 §18.9**（2026-09-12 下午）。

### 18.7 ⚠ 动手前发现：**`reseed_singles/` 是 cross-seed 和 IYUU 共用的**

停掉容器、准备 `mv` 之前，最后核对了一遍 qB 里的 `tags`，发现 500 条里有 **100 条不
是我们的**（`IYUU自动辅种`），而它们**就住在 `reseed_singles/` 里面**。

**这意味着迁移的代价变了**：搬这个目录不再只影响我们，还会让 IYUU 的 100 条种子
`save_path` 失效。当时留下两个待查问题，**已于 2026-09-12 14:50 全部查清（见 §18.8）**：
IYUU 侧**不需要改任何配置**，且搬迁范围应当**扩大到全部 509 条**。

> ~~因此 #1（qB setLocation）的正确范围从“500 条”缩小到“408 条”~~
> → **已推翻**：正确范围是**全部 509 条**（`--all-tags`）。依据见 §18.8。

**教训（值得记的通用一条）**：判断"这条种子是不是我们的"，**要看 `tags`**，不要看
`category` 空不空 —— cross-seed 会给它注入的每条打 `cross-seed` tag，IYUU 打
`IYUU自动辅种`，两个系统的产物混在同一个分类里（IYUU 那 100 条根本没有分类）。
按 `category` 判断会把别人的东西当成自己的。


### 18.8 ✅ 结论：`--all-tags` 全量搬 509 条，IYUU 侧零改动（2026-09-12 14:50）

**怎么查的**：没有远程 shell（NAS 的 22 端口拒绝连接），于是直接读 MariaDB 数据目录
`…/iyuuplus/iyuu_data/iyuu/` 下的 `.ibd` 文件（**只读**），从 InnoDB 页里的明文串
还原 `cn_crontab` 的任务定义。★ 这个取证手法本身很好用，
**但有个必须先设防的坑**：`cn_client` 这类“配置表”里存着**明文口令**，
直接 dump 原始串就会泄漏 —— **本次就踩了**（见本节末尾）。

**证据 1：`path_filter` 是空的。** 两个辅种任务的 `parameter` 原文（截去 sites 长列表）：

```json
qb自动辅种  45 1 * * *  {"clients":{"1":"on"},"master":"","path_filter":"",
                        "notify_channel":"notify_iyuu","marker":"category"}
TR自动辅种   3 2 * * *  {"clients":{"2":"on"},"master":"","path_filter":"",
                        "notify_channel":"notify_iyuu","marker":"tag"}
```

配合 `ReseedServices.php:438` 的 `if ($path_filter = $parameter['path_filter'] ?? [])` ——
空串为假，**整个分支跳过**，`$this->path_filter` 保持默认 `[]`；随后
`pathFilter()` 里的 `if (empty($this->path_filter)) return $hashArray;` **原样放行**。

**证据 2：`cn_folder` 零行。** 逐页扫 `cn_folder.ibd`（82 KB / 5 页），
只有 `infimum` / `supremum` 页边界，`folder_alias` / `folder_value` **一条数据都没有** ——
「目录管理」里从没建过条目，也就不存在“被引用的 folder_id”。

**两条合起来** → IYUU **没有任何排除目录** → 搬迁对它**完全透明**：
它下一天 01:45 跑 `qb自动辅种` 时从 qB 现读到的是新 `savePath`，照原样回填
（该机制见 §18.7 上半：**它不存目标目录，每次现读**）。

**顺带查清：NAS 上有两套 qB**，而 `IYUU自动辅种` 这个词在两边**含义不同** ——

| 端口 | 版本 | 角色 | `IYUU自动辅种` 在那边的形态 |
|---|---|---|---|
| **:3060** | qB v4.6.5 | **我们的 reseed qB**（docker）；509 条全在 `…/download/reseed_singles` 下 | **标签**（对应 `marker:"tag"`） |
| **:8085** | qB v5.2.3 | 主 qB（套件版）；2990 条，在 `…/download/movies`、`…/download/TV` 下 | **分类**（对应 `marker:"category"`） |
| :9091 | — | Transmission | — |
| :3003 | — | IYUU 里配着但连不上（疑似失效条目） | — |

**:3060 的 509 条精确构成**（实测，只取 `save_path` / `category` / `tags` 三个字段）：

```
408  …/reseed_singles  分类=[reseed-singles]  tags=[cross-seed]     ← 我们的
100  …/reseed_singles  分类=[(无分类)]       tags=[IYUU自动辅种]   ← IYUU 的
  1  …/reseed_singles  分类=[reseed-singles]  tags=[]               ← 无主（待认领）
```

**决定（用户 2026-09-12 14:52）：`--all-tags` 全量搬 509 条。**
理由：那 100 条的 `save_path` 与我们的**落在同一批站点子目录**里，物理上共享同一份硬链接
内容 —— “只搬 408”既做不到、也没意义；而 IYUU 侧零改动可以承受，所以没有理由不全搬。
★ 无主的那 1 条也随之进入新根。

**残留风险（如实记下）**：IYUU 是**次日 01:45** 才跑的那一批。
搬迁当天要留意 `IYUU自动辅种` 的条数**是否还在增长** —— 若搬迁后它不再新增，
才说明本节推断有误（届时去看 IYUU 日志，不要靠猜）。
★ 这是**唯一**能在生产中证伪本次结论的观测点。

★ **教训（凭据）**：读 InnoDB 页做取证时，**必须先按值形状脱敏**，
不能直接 dump 原始串。本次 dump `cn_client.ibd` 时把 qB 管理员口令、
TR / :8085 的 Web 口令打进了聊天。用户决定**不轮换**（2026-09-12），
但这是本项目第三次同类泄漏 —— 已并入记忆 `redact-by-value-shape`：
**“配置文件表”要在读之前就假定含密钥。**

### 18.9 ✅ 执行记录：三个「只有真跑才会暴露」的坑（2026-09-12 下午）

搬迁 2026-09-12 约 15:00 落地。**498 / 509 已迁**，剩 11 条等校验完再复跑带走。

本节只记**计划里没写、动手才撞上**的东西。三条是同一族：
**它们都不报错，只表现成「一切正常」或者「莫名其妙的等待」。**

#### 18.9.1 坑一：新父目录是 `root:root 700`，容器被锁在外面（已并入 §18.4）

`sudo mkdir -p /volume1/video/download/reseed` 造出来的是 **`700 root:root`**，
而容器按 `user: "${PUID}:${PGID}"` = **1026:100** 跑（`compose.yaml:81`）。两边后果：

| 谁 | 后果 |
|---|---|
| cross-seed 容器 | 读不到农场（`DATA_DIRS` 指向 `reseed/reseed_farm`）→ **看成空的**，一个 searchee 都没有 |
| qB 容器 | 建不出 `LINK_DIR`（`reseed/reseed_singles`）→ 新链接无处可写 |
| `iSunker` 用户 | `ls -ld` 直接 `Permission denied` |

★ **最坏的地方是它不报错**：cross-seed 不会说「目录读不到」，它会**静默地什么都搜不到**，
日志上看起来只是「这批没有匹配」。这和 §16.2.1 那个「校验跟自己比、永远通过」是同一族故障 ——
**失败的形态是「看起来正常」**。

**怎么发现的**：`nas-update-env.sh --dry-run` 自带的 `[ -d ]` 逐条校验报了
`[warn] 路径不存在: /volume1/video/download/reseed/reseed_farm`。
★ 那**不是它设计时的目标**（它本来只是想拦住打错的路径），**是副作用救的场** ——
所以「配置脚本顺手把落地路径校验一遍」这件事，价值比看上去大。

**修法**：让 `reseed/` 与它的父目录 `download/` 同级同权（`download/` 是 `777 1000:1000`）：

```sh
sudo chown 1000:1000 /volume1/video/download/reseed
sudo chmod 777       /volume1/video/download/reseed
```

★ **这一条本该在 §18.4 的表里。** 加一层父目录 = 多一个**由 `sudo` 造出来的**目录，
于是引入了一个「属主/权限」的影响面。原表只数了「路径字符串出现在哪儿」，
**没数「谁有权访问新路径」** —— 这是那张表的**方法论缺口**，不是漏看了一行。
（同族的还有：`[ -d ]` 只能证明「存在」，证明不了「容器能读」。本次是巧合才撞上。）

#### 18.9.2 坑二：试跑抽中了「正在校验」的种子 —— 并暴露脚本一个真缺陷

`--limit 1 --all-tags --apply`（每站取第一条，共 3 条）的结果：
HDFans / 南阳 各 1 条 → 干净回到 `stalledUP` 100%；
**BTSCHOOL 那条 `Superman.and.Lois.S01.REPACK` → `checkingDL` 0%，盘上文件没动。**

查下去发现它属于 **11 条 `checkingDL`**，而且：

- 这 11 条里 **10 条我们根本没碰过**（`save_path` 还在旧根）→ 这个状态**在动手之前就存在**；
- 它们的 `added_on` 挤在 **572 秒**内（`1789193889` → `1789194461`）→ 是**同一个 cross-seed
  批次**当天 14:27 注入的，qB 正在逐条做**初次校验**；
- `du -sh` 那份文件夹 = **29 G**，种子 size = 30.88 GB → **数据是齐的**，不是丢了；
- qB **一次只校验一条**：停手观察 90 秒，`Preacher`（201 GB）从 64.4% → 71.1%，
  其余 10 条一动不动停在 0%。

**为什么不能碰**：对**校验中**的种子调 `setLocation`，两个后果是**叠加**的 ——

1. qB 立刻改 `save_path`，但数据要等搬完才动；中间态里它的校验是按**新路径**跑的
   → 必然找不到任何文件 → 最后落到 `missingFiles`；
2. 那条正在跑的校验（201 GB，已到 71%）被整个作废。

★ **试跑的设计盲区（方法论，值得单独记）**：`--limit 1` 每站只取**一条**。
而 18.9.3 会看到，问题恰好只在「同一份内容被**多条**种子共用」时出现 ——
试跑**按构造就抽不到第二个成员**，所以它**不可能**发现 18.9.3；
但它**确实**发现了 18.9.2。一句话：**试跑能发现什么，取决于它抽到了什么**。
别把「试跑通过」当成「全量安全」的证明 —— 它们验证的是**不同的东西**。

**已修**：给 `migrate-reseed-dirs.py` 加了两道闸（都是**默认**行为，不是可选项）——

1. **已经在新根下的 → 跳过**。否则第二次跑会因为「它不在旧根下」而退出 1，
   把一次正常的**幂等复跑**变成假警报；
2. **`checking*` / `moving` → 跳过**，留给下一次复跑自动带上。
   `--include-checking` 才强搬，且 `--help` 里写明后果。

然后把这 3 条里误搬的那条 **`setLocation` 回旧根**，让 `save_path` 与数据重新一致
（否则它排到的校验会在新位置找不到东西）。

**收尾**：`--all-tags --apply` 搬 **496** 条（509 − 11 校验中 − 2 试跑已搬），
累计 **498 条在新根**；盘上核对 —— HDFans 新 234 / 旧 0、南阳 新 136 / 旧 0、
BTSCHOOL 新 12 / 旧 11。旧根下**只剩那 11 条**。

#### 18.9.3 坑三：共用内容的种子会被 qB 重校验（每组 N−1 条）

搬完立刻出现 **116 条 `checkingUP`**（搬之前是 0）。规律**非常干净**：

| 状态 | 条数 | 其中「内容被多条种子共用」 |
|---|---|---|
| `checkingUP` | 116 | **116 / 116** |
| `stalledUP` | 380 | 36 |

而站点层面的数字**精确吻合**：

```
HDFans     318 条种子 / 234 个不同内容项  →  差 84
NanyangPT  168 条种子 / 136 个不同内容项  →  差 32
BTSCHOOL    23 条种子 /  23 个不同内容项  →  差  0   （无重复）
                                 84 + 32 = 116  ← 与上面的 116 完全相同
```

再按「共用组」算：36 组、涉及 152 条种子 → **116 条重校验、36 条没有**，
即**每组恰好 1 条不重校验**（`152 − 36 = 116`，也等于 `Σ(N−1)`）。

**机制**：一个共用组的内容只发生**一次**真实的 rename（由组里第一条种子完成），
其余同组种子的 `save_path` 是被顺带改掉的、**自己没有 move** →
libtorrent 只能**重新校验**来确认。所以这不是故障，是 qB 在**自证同组数据也到位了**。

**代价与结论**：数据无风险，校验完自动回到做种。代价只有两项 ——
这 116 条在校验期间**不做种**，以及磁盘 I/O。qB 单线程校验，实测约 **4.5 分钟/条**，
队列 3–5 小时排空。
★ **这一条应该提前写进搬迁计划**：大规模 `setLocation` 之后出现一批 `checkingUP`
是**预期内**的，不是搬坏了。（本次是我先没预见到，用户看到 116 条重校验来问，
才回头查出来的。）

#### 18.9.4 顺带修掉的三处小问题

| 问题 | 症状 | 修法 |
|---|---|---|
| `editCategory` 拿返回值判成败 | 刚下发完几百条 `setLocation` 之后 qB 回 **409 Conflict**，而它要设的**本来就是同一个值**（试跑已设过）→ 照字面打「✗ 失败」，操作者会白查一轮 | 改成**回读 `/torrents/categories` 的实际值**再下结论。同 §16.2.2 的教训：**别信调用的返回值，信回读到的状态** |
| `build-farm.sh` 的 Windows 用法示例写错 | 文档把 `COMPOSE_DIR=` / `FARM=` 排在**脚本名之后** → 它们是**位置参数**，被判「未知参数」以退出码 2 结束 | 改为**命令前缀的环境变量**写法。2026-09-12 实测前缀写法 `--verify` 正常返回 0 |
| `add-torznab-indexer.py` 写回不保真 | 按 `\r\n` 切分再拼回，**把目标行里多出来的 `\n` 一起吃掉**（那行结尾原本是 `\n\r\n`）| 改成**切 `\n`**、给每行记住自己的尾 `\r` 再原样拼回；已用合成样本做**字节级**验证（游离 `\n` 保留、除目标行外逐字节相同）|

★ 第三条的通用教训：`.env` 的行分隔符是 **`\n`**，`\r` 只是某些行末尾**多带的一个字符** ——
而这一份生产 `.env` 就是**混的**（41 行带尾 CR、2 行不带）。
凡「读进来再写回去」的文件，**要么逐字节保真，要么明说改了什么**：
一个装着真密钥的文件，不该有未经说明的字节改动。
（同族坑本项目已踩三次：`build-farm.sh` 的 `tr -d '\r'`、`read_text` 的换行翻译、这一次。）

### 18.10 ★ 收尾判据：等的是 `checkingDL == 0`，**不是**「所有校验都停」（2026-09-12 傍晚）

#### 18.10.1 判据本身踩过一次坑

「等校验跑完再复跑迁移」这句话里的"校验跑完"，第一版写成了
`checkingDL == 0` **且** `checkingUP == 0` —— **错的**。实测数据（见 §18.9.3）：

| 状态 | 条数 | 排在队里的哪儿 | 大致耗时 |
|---|---|---|---|
| `checkingDL` | 11 → 0 | 队首 | ≈45 分钟 |
| `checkingUP` | 116 | **排在 `checkingDL` 之后**，实测进度一直停在 0 | ≈9 小时（~4.5 分钟/条） |

qB 的校验是**单线程**的，队列顺序决定一切。要等的只有 `checkingDL` 那批；
把 `checkingUP` 也写进条件 = **白等一整晚**。
★ 同族教训见 §16.2.1：**先想清楚"等到什么才算完"，再写循环条件。**

**已沉淀成工具**：`scripts/wait-for-checks.py`（只读轮询）
退出码 `0` = 队列空 / `2` = 超时 / `3` = 一次都没连上（用到网络就显式区分，别让抖动背锅）。
★ 它**只打印计数** —— 不打印种子名、`tracker`、`content_path`（`tracker` 带明文 announce passkey）。
★ 与 `migrate-reseed-dirs.py` / `add-torznab-indexer.py` 一样，它**不在 `deploy.sh` 的白名单里** ——
三个都是**电脑侧手动工具**（只通过 HTTP 打 qB / 改 `TORZNAB_URLS`），不像 `build-farm.sh` 那样需要在 NAS 上跑。
所以 NAS 上找不到它们**是正常的**，别当部署漏了。

#### 18.10.2 ★★ `checkingDL == 0` 是**瞬时**状态，不是"世界静止了"

实测撞到：看门狗**已经**以退出码 0 报过「队列空了」，几分钟后再看又是 `checkingDL = 1`。
原因很简单 —— cross-seed 仍在按批次注入新种子，**每注入一条就触发一条校验**。于是：

- 「队列空了」**会反复出现**，它**不是**"从此没人再校验"的保证；
- 因此它**不能**当成"可以动手"的**全局**前提。

**那复跑迁移到底安不安全？** 安全 —— 因为迁移脚本那道闸是**按种子**判的
（`IN_FLIGHT_STATES` 逐条看），不是全局开关。所以真正的判据是：
**「那 11 条自己不在途」，而不是「整个队列是空的」。**
这一条决定了收尾**不必挑时机**，随时可以复跑。

#### 18.10.3 ★ 观测量 ≠ 进度：「仍在旧根=11」这个数**不会自己变小**

看门狗打印的 `仍在旧根=N` 有迷惑性：**它一直是 11，但底下的状态一直在变。**

| 时刻 | 那 11 条的 `state` | 条数 |
|---|---|---|
| 16:08 前后 | **全在** `checkingDL`（我们谁都没碰过它们） | 11 |
| 16:20 | 逐条校完 → 一条条回落到 `stalledUP`，**但 `save_path` 仍在旧根** | 11 |

`save_path` 仍在旧根，是因为**当初闸门跳过的那批，没有任何人搬过它们** ——
条数因此恒为 11。★ **教训**：一个"不变量"式的观测量（这里的条数）**不能拿来读进度**；
进度要看**状态的分布**，不看**条数**。「11 条里校完了 10 条」在条数上**完全不可见**。

#### 18.10.4 现场快照（2026-09-12 16:15 / 16:20 两次一致）

```
总数 = 509
  stalledUP  = 384
  pausedUP   = 8
  checkingUP = 116    ← §18.9.3 那批共用内容的，**全在新根**，校完自动恢复做种
  checkingDL = 1      ← 瞬时值，会重新出现；**与旧根那 11 条无关**
仍在旧根 = 11（10 stalledUP + 1 pausedUP，合计 619.3 GB）
        ← ★ 全部**不在途** → 复跑条件**已满足**
```

#### 18.10.5 剩下的收尾（③ 完成**之前**列的计划 —— 实际执行结果见 §18.10.6）

| # | 谁 | 做什么 | 状态 |
|---|---|---|---|
| ① | **你** | `cd /volume2/docker_ssd/prowlarr_cross-seed_autohardlink && sudo docker compose up -d --force-recreate cross-seed` —— 让 `.env` 里 HDtime 的 `/1` 生效 | ⏳ 待做 |
| ② | **你** | DSM → 控制面板 → 任务计划：**重新启用** drive-loop | ⏳ 待做 |
| ③ | 我 | `python scripts/migrate-reseed-dirs.py --all-tags --apply` 带走最后那 11 条（闸门跳在途的，随时可跑） | ✅ **已完成** → §18.10.6 |
| ④ | **你** | 旧根空了之后，**在 NAS 上**（**不要**走 UNC）`sudo rm -rf /volume1/video/download/reseed_singles` | ⏳ 等 ③ |
| ⑤ | 我 | HDtime 的第 ③ 步：确认 `cross-seed.db` 的 `timestamp` 表里出现 HDtime 的行，**之后**才把 `drive-loop-nas.sh` 的 `--indexers` 改成 `HDtime,HDFans,NanyangPT,BTSCHOOL` 并 `deploy.sh` | ⏳ 等 ①② |

★ **① ② 与 ③ 之间没有依赖** —— ③ 只动 qB 侧的 `save_path`，跟容器重不重建无关。
想先把 ③ 跑掉完全可以。（顺序上唯一有硬依赖的是 **⑤ 必须在 ①② 之后**，理由见
`drive-loop-nas.sh` 里「加站的正确顺序」那段：站没通就写进 `--indexers` = 白烧一次
「来了新站」的一次性触发。）

#### 18.10.6 ✅ 收尾已落地（2026-09-12 16:25）

**① 最后那 11 条**：`--all-tags --apply` 一次带走（`setLocation` 11 条 → 新根 BTSCHOOL）。
qB 是**异步**搬的，落完立刻回读仍显示"11 条在旧路径"—— 等 ~75 秒再读：

```
总数 = 509
  stalledUP  = 391
  checkingUP = 110     ← 就是 §18.9.3 那批，从 116 逐条在收
  pausedUP   = 8
落新根    = 509 / 509
仍在旧根  = 0
异常状态  = 0          ← missingFiles / error / unknown 一条都没有

新根下：  BTSCHOOL 23  /  HDFans 318  /  NanyangPT (南洋) 168
          ← ★ 三个数与站点侧种子数**逐个吻合**（§18.9.3 那张表的"条数"列）
```

★ 同一枪里 `editCategory` **又报了一次 `409 Conflict`**，而回读确认**值本来就是对的** ——
这正是 §18.9.4 改掉的那条：**别信调用的返回值，信回读到的状态**。
改之前这里会打一个 ✗ 假失败，操作者得白查一轮。（这次一次都没误报。）

**② `deploy.sh --apply`**：推了 3 个文件，都是良性的 —— `reseed-state.py`（一行 docstring）、
`drive-loop/run.sh`（只有注释）、`build-farm.sh`（只有用法文档修正）。
备份 `.deploy-backup/20260912-162537`，原子替换。

★ 推之前先确认**没有批次在跑**（`attempts.log` 末条 = `14:30 exit=0`、
状态文件 `running_pid: null`）—— 这是 `deploy.sh` 那条「别在批次运行中推」的**硬前提**：
跑批中的 `drive-loop/run.sh` 会拿着旧偏移去读刚被换掉的文件 → 执行到错位的代码。

**③ 旧根（`/volume1/video/download/reseed_singles`）现在只剩 3 个空目录**
（BTSCHOOL / HDFans / NanyangPT，`total 0`）—— ④ 可以做了。

### 18.11 ✅ 收尾复核 + HDtime 第 ③ 步（2026-09-12 傍晚）

本节记录「搬迁收尾」之后、真正把项目推回稳态的那一轮。四件事：**闸门开了**、
**`RATE_LIMITED` 是个陈旧标记**、**一个待办其实不用做**、**下站工具备好了**。

#### 18.11.1 ★★ 闸门开了：HDtime 的 `timestamp` 有 60 行

第 ③ 步的判据（见 `drive-loop-nas.sh`「加站的正确顺序」）是
**`cross-seed.db` 的 `timestamp` 表里开始出现该站的行**。
17:00 实测：

```
id=1 HDtime                 60 行   status=RATE_LIMITED  retry_after=09-12 14:01:33 已过期
id=2 HDFans                908 行   status=RATE_LIMITED  retry_after=09-12 14:26:47 已过期
id=4 BTSCHOOL              115 行   status=OK            retry_after=09-11 21:40:37 已过期
id=5 NanyangPT (南洋)        870 行   status=RATE_LIMITED  retry_after=09-12 08:17:14 已过期
```

★ 为什么信这张表而不信日志：`timestamp` 主键是 (searchee_id, indexer_id)，
**失败的搜索不会留下行** —— 所以「有行」= 请求真的发出去并被应答了。
日志里 `POST /api` 的成败是混在一起的，这里是个纯计数。

→ 于是第 ④ 步（改 `--indexers`）解锁：`scripts/drive-loop-nas.sh` 已改为
`--indexers HDtime,HDFans,NanyangPT,BTSCHOOL`。★ **但 `deploy.sh` 要等当前批次跑完** ——
跑批中的 `drive-loop/run.sh` 拿着旧偏移在读自己，中途被换掉会执行到错位的代码（§18.10.6）。

**已沉淀成工具**：```
python scripts/check-indexer-timestamps.py --expect HDtime,HDFans,NanyangPT,BTSCHOOL
```
只读，退出码 0 = 闸门开。`--wait` 可先等下一批跑完再取数。
与 `migrate-reseed-dirs.py` / `add-torznab-indexer.py` / `wait-for-checks.py` 一样，
它**不在 `deploy.sh` 的白名单里** —— 是 Windows 侧手动诊断工具，不是容器要跑的。

★ **第一版就错在名字匹配上**，记一笔：`--expect` 里的 `NanyangPT` 与 cross-seed
自己注册进 `indexer.name` 的 `NanyangPT (南洋)` **不是同一个字符串**，严格 `==` 把一个
**已经搜了 870 行**的站报成「不在 indexer 表里」—— 一度看起来像"容器没见过它，要不要重建？"，
而真相是脚本自己的匹配太紧。修法：精确命中优先，否则去掉 ` (` 后缀再比一次，
且**要求唯一命中**。★ 结论仍然是 §18.10.1 那条：**判据本身要先被验证一次**。

#### 18.11.2 ★★ `status=RATE_LIMITED` 不代表还在被限流 —— 真判据是 `retry_after`

四个站里有三个标着 `RATE_LIMITED`，看起来像"站点在拦我们"。**不是。**
把 `retry_after`（epoch 毫秒）换算成本地时间，**四个全部已经过期**
（14:01 / 14:26 / 昨 21:40 / 08:17，而现在 17:00）；BTSCHOOL 的 `status` 更是**已经自己翻回 `OK`**。

★ **这个字段限流窗口过去后不会被擦掉** —— 只看 `status` 这个词会误判成
"站点还在拦我们"，进而做出错误决策（去降并发 / 去换 cookie / 去怀疑站点）。
**真判据是 `retry_after` 有没有到点**；`status` 只是个"最后一次见到限流"的残留标签。

这又是一次 §18.10.3「**观测量 ≠ 真相**」：`status` 是**状态**，`retry_after` 才是**时刻**，
而"还在不在限流"是个**关于时刻的问题**。用一个没有时间维度的量去回答它，必错。

#### 18.11.3 Windows 计划任务 `reseed-drive-loop`：**已经不存在，不用删**

这条待办在 README 上挂了好几轮（"仍需你动手 + 要管理员权限"）。实测**根本不用做**：

```
schtasks /Query /TN "reseed-drive-loop"   →  系统找不到指定的文件
全表 375 个任务里 grep "reseed"            →  0 个
```

★ 记一个**方向容易看反**的坑（README「还没做」第 2 条也写了同一族）：
`拒绝访问` = **没提权**（要管理员），而 `找不到指定的文件` / `ObjectNotFound` = **已经没有了**。
后者是**成功信号**，不是失败。先跑没提权的那条会先吃一个 `拒绝访问`，
容易让人以为"删不掉"。

★ 另一个 Git Bash 的坑：**`schtasks /TN` 的 `/TN` 会被 MSYS 当成路径翻译**
成 `C:/Program Files/Git/Query`，报「无效参数」—— 你看到的不是真实结论。
必须 `export MSYS_NO_PATHCONV=1`。本项目在 Windows 侧跑 `schtasks` / `sc` 这类命令时都会撞上。

#### 18.11.4 下站工具 `add-torznab-indexer.py --remove`

为「换站替换 BTSCHOOL」的下站那一半做的（§13.3 有那张顺序表）。

- `--remove <id>` 默认预检，`--apply` 才落地；**自动备份 + 临时文件 + 原子替换**
  （不能直接 `open(path,'w')`：那会先截断再写，中途断掉就是一个**空的 `.env`**，
  cross-seed 起来后全线没有密钥）。
- **安全闸**：摘到一条不剩会被拒绝，要 `--allow-empty`。
- `--remove` 与 `--id` **互斥**（一次只做一件事）。
- **字节保真**：除目标行外**逐字节不变** —— 连那份生产 `.env` 里混着的行尾
  和 TORZNAB_URLS 那行末尾多出来的那个**游离 LF** 都原样留着
  （做法：切 `\n` 而不是切 `\r\n`，给每行记住自己的尾 `\r` 再拼回）。

测试 `tests/test_remove_indexer.py`：8 项断言全过（预检不改文件 / 真摘 / 字节保真 / 游离 LF 保住 /
幂等 / 加回往返 / 摘空被拒且没写文件 / 参数互斥）。

★ **测试第 4 项第一次报 FAIL，是断言写错了，不是代码错了**：
我拿 `api\n\r\n` 去匹配，而那行的实际结尾是 `…apikey=FAKE`，
这个针在哪儿都匹配不到。改成 `FAKE + "\n\r\n"` 后通过。
★ 教训：**测试报红时，先怀疑断言本身** —— 尤其是"检查某个片段还在不在"这种断言，
针写错时**表现和真 bug 一模一样**。这与 §18.10.1 是同一件事的两面：
那边是"判据要验证"，这边是"**测试自己也是判据**"。

#### 18.11.5 本轮的下一步

| 谁 | 做什么 | 状态 |
|---|---|---|
| 我 | `deploy.sh --apply` 推 **2 个文件**：`drive-loop/run.sh`（`--indexers` 加 HDtime）、`orchestrator/config.py`（`link_dir` 默认值修正，见 §18.10.7） | ✅ **已完成（17:12）** → §18.11.6 |
| 用户 | **决定「换哪个站」替换 BTSCHOOL** | ✅ **这条待办已关闭 —— 判据失效，不是换好了** → §18.11.6 |
| 我 | 次日 01:45 后复核 IYUU 自动辅种条数是否仍增长（§18.8 的唯一生产证伪点） | ⏳ |

★ 批次于 **16:45:03** 起跑 —— 这是 drive-loop 任务**重新启用后第一次唤醒成功**
（14:30 那批之后断了两个小时，正是任务被禁用/旧根被删的那段窗口）。

#### 18.11.6 ✅ 部署完成 + 「换站替换 BTSCHOOL」这条待办**关闭**

**部署**：16:45 那批 `17:10:57 exit=0` 结束后推的（`deploy.sh --apply`，备份
`.deploy-backup/20260912-171213`），2 个文件：
`drive-loop/run.sh`（`--indexers` 加 HDtime）、`orchestrator/config.py`（`link_dir` 默认值）。

★ **这两个都不需要 `--force-recreate`** —— 别被 `deploy.sh` 结尾那段**通用**提示
（"在 NAS 上 up -d --force-recreate cross-seed"）带着去白重建一次容器：

- `drive-loop/run.sh` 是 **DSM 任务在宿主机上直接执行**的（不是容器里的东西），下次唤醒自动生效；
- `orchestrator/config.py` 是 `build:` 进镜像的，要 `docker compose build reseed-orchestrator`
  才生效 —— 但它本来就是**死代码**（§18.10.7），不必为它单独重建。
  （`deploy.sh` 的那段提示对**它自己**不知道的两个文件类型一视同仁，所以在这里是**噪音**。）

**关掉「换站」**：用户提问——「BTSCHOOL 现在不是能登录、能匹配到种子吗？」
查完**是对的**：

| 站 | 匹配到 | 搜过 | 命中率 |
|---|---|---|---|
| HDFans | 215 部 | 485 部 | 44% |
| **BTSCHOOL** | **23 部** | **46 部** | **50%（最高）** |
| NanyangPT (南洋) | 4 部 | 452 部 | **0.9%** |
| HDtime | 0 部 | 0 部 | 刚上路（16:45 才首搜） |

（数据源：`drive-loop/hlink/state.db` 的 `movie.matched_indexers` / `searched_indexers`。）

★★ **判据是有层次的，两个库各答一半**：

- `cross-seed.db` 的 `timestamp` 只能证明**搜得出去**（请求发出去了）；
- `state.db` 的 `matched_indexers` 才证明**匹配得到**（真换来了种子）。

**两个都要看** —— 一个站完全可以"每次请求都成功、但从来匹配不上"
（NanyangPT 就接近这个形状：搜了 452 部，只中 4 部）。

BTSCHOOL 那 23 部**全在 `dc-collection` 包里**，且在那个包里它是**最大贡献者**
（23 部，压过 HDFans 的 21 部）。17:15 实时搜 `The Dark Knight 2008` 回 **24 条**、
`Spider-Man No Way Home 2021` 回 **40 条**，带 `downloadUrl`、seeders 正常；
Prowlarr 日志里 BTSCHOOL 的 warn/error = **0**。

**所以这条待办不是"换好了"，是"当初的判据失效了"** —— 决定是 2026-09-11 做的，
当时它在 Prowlarr 出 CF 挑战页（§13.3 判定表第一行）；后来它被重新启用、
`/3/api` 加回 `.env`（§18.9）、容器重建。**那道坎过了，只是没人回来销账**，
于是一条**前提已经不存在**的待办在 README 上挂了一天多。

★ 教训：**待办有自己的生命周期。** 它的前提（"BTSCHOOL 不可用"）会被**别的工作顺手推翻**
（换 cookie、重建容器、重加索引器），但待办本身**不会因此自动消失**。
→ **每次要执行一条待办前，先验一遍它的前提还成不成立**；不成立就该**关闭**，
而不是"既然写着就做掉"。（同 §13.10 那次：`410 Gone` 的成因也被解释错过一回。）

★ 顺带的反问：**真要换站，按数据该换的是 `NanyangPT`（4/452 = 0.9%）**，不是 BTSCHOOL。
不过它可能只是片库对不上这批包的口味 —— 先看它的目录再下结论，**不是现在该做的事**。
下站工具 `add-torznab-indexer.py --remove` 留着备用（顺序表见 §13.3）。

### 18.12 ★★ FlareSolverr：装了、在跑、**一次都没用上**（2026-09-12 17:15 实测）

**问题**：本项目到底用没用 FlareSolverr？BTSCHOOL 的 CF 盾很厚，要不要跟它适配一下？

**答**：**至今零使用**；而且**现在四个站都不需要它**。

#### 18.12.1 证据

| 查什么 | 结果 |
|---|---|
| 容器在不在 | ✅ `reseed-flaresolverr` 在跑 —— `POST /v1 {"cmd":"sessions.list"}` → `{"status":"ok","sessions":[],"version":"3.5.2"}` |
| Prowlarr 认得它吗 | ❌ `GET /api/v1/tag` → **空列表**（一个 tag 都没有） |
| 有索引器挂它吗 | ❌ 四个索引器 `tags` **全是 `—`**（BTSCHOOL / HDFans / HDtime / NanyangPT） |

★ `sessions: []` 是**佐证**：真被用过会留下会话。
★ 也就是说它从 Phase 1 起就 `up -d` 起来了，然后**一直空转到现在**。

#### 18.12.2 怎么才算"接上"—— Prowlarr 是**按索引器挂 tag**，不是全局开关

★ 本仓库 README 里那句「在 Prowlarr 的 Settings → Indexers 里把 FlareSolverr
指向 `http://flaresolverr:8191`」**是错的**（Prowlarr **2.5.2** 实测）。
正确接法只有两步：

1. 在 Prowlarr 建一个 **label 恰好是 `flaresolverr`** 的 tag；
2. 把该 tag **挂到需要过 CF 的那个索引器上**。

旁证：`GET /api/v1/config/indexer` → **404**（这个端点不存在），
说明"索引器级配置页"里根本没有 FlareSolverr 这一项。

★ **`info_flaresolverr` 不是配置项** —— 它只出现在 **BTSCHOOL 的索引器定义**里
（另外三个站都没有），`type = "info"`、`label = "FlareSolverr Info"`、`help = None`，
只是个**提示用的说明字段**：这个站的定义**认为**它可能需要 FlareSolverr。
**看到它 ≠ 已经接上了。** 这是个很容易把"定义里的提示"读成"已经配置好"的地方。

#### 18.12.3 为什么现在不需要它 —— 判定表又被用了一次

回到 §13.3 / §13.6 那张判定表。它问的不是"这站凶不凶"，而是**卡在哪一层**：

| 症状 | 卡在哪 | FlareSolverr 有用吗 |
|---|---|---|
| `403` + 挑战页 / 日志出现 `Cloudflare` | **请求还没出去** | ✅ 有用 |
| `500/502/520/522/timeout` | 请求**已穿过 CF**，是站点后端挂了 | ❌ 没用 |
| `429 + Retry-After` | 站点限流 | ❌ 没用（该降 `delay`） |
| 正常返回结果 | 没卡 | ❌ 不需要 |

**BTSCHOOL 现在是第四行** —— 17:15 实时搜索正常返回 24 / 40 条，日志 0 报错。
它 2026-09-11 确实卡过**第一行**，但**那道坎已经过去了**
（重新启用 + 换 cookie + 重建容器，见 §18.11.6）。
→ **"BTSCHOOL 的 CF 盾很厚"是记忆，不是当前状态。**

#### 18.12.4 ★ 今天真正在报错的是 HDtime —— 而它恰好属于「FlareSolverr 帮不上」那一类

查日志时顺手发现的（**不是**本次要查的东西，是顺着 BTSCHOOL 的日志扫出来的）：

```
warn: Request for HDtime failed with status BadGateway. Retrying in 1.76s.
warn: Unable to connect to HDtime at [https://hdtime.org/torrents.php?search=...]
```

这批（16:45–17:10）里 HDtime 报 **502 BadGateway**，**17:04–17:11 共 17 条**；
而 16:45–17:04 它是正常的（`timestamp` 从 60 行涨到 88 行）。同期 HDFans 有 32 条 warn/error。

★ 502 是判定表的**第二行** —— 请求**已经穿过 CF** 到了 `hdtime.org` 的后端，
是**站点自己**在挂。**FlareSolverr 对这类完全无效，接了也是白接。**

★ 所以结论不是"要不要上 FlareSolverr"，而是 **HDtime 当前不稳定**。
这**不影响**第 ④ 步的结论（`--indexers` 已加 HDtime，它确实搜得出去、也有 88 行 timestamp），
但意味着 **HDtime 短期内的匹配产出会偏低**。

★ 而且这类失败**不会**被状态机记成"搜过了"：
cross-seed 搜索**报错时不写 `timestamp` 行** → 状态机看到"还没搜过" → 会退避重试。
**这是正确的行为，不需要干预** —— 也正是 §18.11.1 那个"失败不记行"特性的**另一个用途**：
它不只让人能确认"真的搜出去了"，也保证"没搜成的**不会**被记成搜成了"。

★ 通用结论：**下次再遇到"某站搜不到"，先按那张表定位到哪一层，再决定要不要动 FlareSolverr** ——
不要因为"这站 CF 很厚"这个**印象**，去接一个帮不上的东西。

### 18.13 ★ 把 7 个测试从 `D:/tmp` 搬进仓库 `tests/`（2026-09-12 傍晚）

**起因**：查「代码提交完整了么」时发现，**给仓库代码钉回归的那 7 个测试全住在 `D:/tmp`**，
既没有版本历史、也不进备份 —— 而 README / SUMMARY 有 6 处**按绝对路径引用它们**。
`D:/tmp` 是最容易被清掉的目录：**哪天清一次，护栏就没了，而且没有痕迹。**

#### 18.13.1 搬了什么

新增 `tests/`（7 个脚本 + 一个 `README.md` 索引），从 `D:/tmp` **移走**（原件已删）：

| 文件 | 断言 | 钉住什么 |
|---|---:|---|
| `test_backoff.py` | 17 | 55 秒短退避发生在批次中途也要记一笔；残值不误记 |
| `test_farm_root.py` | 18 | v3 农场路径归包（单根 / 多根嵌套 + 季层 / 老包不认领） |
| `test_next_sleep.py` | 17 | `next_sleep()` 三档分级 + 单调性 |
| `test_once_gate.py` | 24 | `--once` 闸门：间隔真落盘、真挡人；跳过文案说的是不是真原因 |
| `test_orchestrator_state.py` | 24 | `state` 子命令：库不存在时**绝不许建文件**；须在读 config 前分派 |
| `test_quota_trend.py` | 96 | 额度台账 A/B 双来源 + 互校 + 趋势 + 农场巡检判断 |
| `test_remove_indexer.py` | 8 | `add-torznab-indexer.py --remove` 的字节保真与安全闸 |

**合计 204 条断言，0 失败**；`python tests/<名>.py` 在**任一 cwd** 都能跑
（路径改成按 `__file__` 解析：`Path(__file__).resolve().parent.parent` = 仓库根），
全过退出码 0 —— 可以直接接 CI。

★ 唯一改名的是 `test-remove.py` → `test_remove_indexer.py`：连字符名**不可导入**，
和其余六个 `test_*.py` 不一致，顺手统一。

#### 18.13.2 ★★ 顺手修掉两个**本来就存在**、只是没人跑才没暴露的毛病

搬完**实跑**才发现 —— 这两个都不是搬运引入的：

**① 控制台是 GBK 时 `⑪`(U+246A) 编不出去。** `test_quota_trend.py` 打印到 §⑪ 时
`UnicodeEncodeError` 直接中断。★ 阴险之处在于：**已经过的断言打印全是 `ok`**，
只有最后一行是异常 —— 看起来像"代码坏了"，其实是**输出编码**问题。
成因：`①`..`⑩`(U+2460–U+2469) 在 GBK 里，**`⑪`(U+246A) 不在**。
修法：每个脚本开头强制 `sys.stdout.reconfigure(encoding="utf-8")` ——
**这个 guard 仓库里本来就有**（`test_remove_indexer.py` 自己带着），只是另外六个没跟上。

**② `sys.path` 里塞 `Path` 对象没用。** `test_orchestrator_state.py` / `test_quota_trend.py`
原先是 `REPO = Path(...)` 后 `sys.path.insert(0, REPO)` → `ModuleNotFoundError: No module named 'orchestrator'`
（而且 `test_quota_trend` 后面还有 `REPO + "/scripts/drive-loop.py"` 这种**字符串拼接**）。
修法：`REPO = str(Path(__file__).resolve().parent.parent)`。

★ 教训同 §18.10.1：**"测试没红"不等于"测试跑过"**。这两条都是**一跑就现形**，
而它们在此之前**从没在干净环境下被跑过** —— 上一次跑大概带着当时的环境（UTF-8 控制台 /
cwd 恰好在仓库里），**环境把缺陷盖住了**。搬进仓库、换 cwd 实跑，才把它们逼出来。
→ **搬家/迁移之后必须真跑一遍**，否则只是把"没人跑"换了个地方。

#### 18.13.3 另一笔：`grep -c $'\r'` 数行尾是**不可靠**的

判断这 7 个文件是 CRLF 还是 LF 时，`grep -c $'\r'` 在 Git Bash 里对**纯 LF** 的
`test_backoff.py` 报出「178 行含 CR」（总行数 178）—— 看起来"全是 CRLF"。
用 Python 数字节才是真相：`crlf=0, lf=178`，**纯 LF**。

★ 顺带纠正一条一直记错的印象：**仓库 Python 的主流行尾是 LF 不是 CRLF** ——
实测 `scripts/` 11 个里 10 个 LF、`orchestrator/` 11 个里 9 个 LF
（只有 `scripts/reseed-state.py`、`orchestrator/config.py`、`orchestrator/qbit_client.py` 是 CRLF），
与 `.gitattributes` 的 `* text=auto eol=lf` 一致。
→ **判断行尾用 Python 数 `b"\r\n"`，别用 grep。**

#### 18.13.4 引用同步

README 1 处、SUMMARY 5 处（本次共 6 处）绝对路径改成 `tests/...`。
★ 另外两处 `D:/tmp` 是**故意不动**的，别顺手改：README 里的
`--notify-spool "D:/tmp/x"` 是**举例子说 spool 目录可以改到哪儿**，与测试无关。

### 18.14 ★ 白名单补齐 + 漂移哨兵：「NAS 一部分、电脑一部分」这个问题本身

**起因（用户原话）**：
> 「git 提交的时候是不是 nas 里面拿一部分文件，电脑里面拿一部分文件？然后不能保证是不是最新的？这个问题怎么解决？」

问得对。而且答案是**比这更糟**：不是"拿一部分"，是**白名单之外完全没有机制**。
本节 = 把这件事量出来、把口子堵上、再留一个能持续回答它的哨兵。

#### 18.14.1 先把关系说清：提交只有一个来源，风险是反方向的

**git 提交只从 Windows 工作副本发生，NAS 从不是提交来源。** 关系是**单向**的：

```
   Windows 工作副本  ──(deploy.sh，白名单)──▶  NAS 生产
     唯一的版本历史                         部署目标，无版本历史
```

所以真正的问题不是"提交混了两个来源"，而是 **`deploy.sh` 的白名单之外，
两边没有任何机制保证一致**。这时文件分三类：

| 类 | 是什么 | 保证 |
|---|---|---|
| **A** | 在 `deploy.sh` 的 `FILES` 里 | ✅ **强**：`cmp -s` 逐字节，不一致就报 |
| **B** | 手工放在 NAS 上的 | ⚠ **无**，纯靠人记得同步 |
| **C** | 其余一切（NAS 上的运行时数据等） | ⚠ 无，且**不该**同步 |

★ 风险方向是 **NAS → 本地**：有人在 NAS 上直接改了文件，下一次 `deploy.sh --apply`
会**静默覆盖**它。而 B 类还有个更隐蔽的变体 —— **改的是哪一份**：

#### 18.14.2 白名单补齐：把最后两个「靠记性」的换成「靠 cmp」的

量下来，`FILES` 之外还躺着两个**手工拷上去**的脚本，同一个族：

| 文件 | 仓库里在哪 | 生产上在哪 | 为什么当初是手工的 |
|---|---|---|---|
| `fix-statedb-farm-root.py` | `scripts/`（**已跟踪源码**） | compose **根目录** | 数据修复时手边方便 |
| `nas-update-env.sh` | `scripts/`（**生成物**，被 gitignore） | compose **根目录** | 由 `gen-nas-env-update.py` 产出 |

`build-farm.sh` 是前车之鉴（见 §18.9 一带）：它当年也是手工的，代价是
**09-11 改完 `--verify` 的期望集后，生产副本是另外手工放的，中间有一段时间两边不一致，
而且手工放的那份没有备份**。

两者都**实测已一致**，所以收进来是**零风险**地把"靠记性"换成"靠 cmp"。
白名单条目 **25 → 27**（本地源 25 个，其中 2 个源各部署到 2 个目的地）。

★ `nas-update-env.sh` **凭什么能进白名单**：它只装载 `DATA_DIRS` + `LINK_DIR` 两个
**路径**键，不含任何凭据；且实测本地 `.env` 与生产 `.env` 的 `DATA_DIRS`
**逐字节相同**（42 字符，sha256 前缀 `420afc99339a`）。**若哪天它开始携带别的键，先回看这段。**
另外它是生成物 ⇒ 全新 clone 时本地没这个文件，`deploy.sh` 会打「⚠ 本地缺失，跳过」并继续，
**不会因为少了它而中断**。

#### 18.14.3 漂移哨兵 `scripts/check-deploy-drift.py`（只读）

它回答**两个方向**的同一个问题：

* **A 方向**：NAS 上有没有**既不在白名单、也不在已知生产独有清单**的文件？
* **B 方向**：仓库里有没有**既没进白名单、也没被声明「不部署」**的已跟踪文件？

```bash
python scripts/check-deploy-drift.py            # 0 干净 / 1 有要看的 / 2 环境问题
python scripts/check-deploy-drift.py --cleanup  # 额外打一份「整理杂物」的 mv 计划（仍只读）
python scripts/check-deploy-drift.py --no-nas   # 只查 B 方向
```

★★ **受管集合从 `deploy.sh` 的 FILES 数组解析，绝不复制一份** ——
复制就是又造一个漂移源，还会和 `deploy.sh` 各自漂到不同的地方去。
解析一旦对不上（有 `::` 的行没解析出目的地）**直接退出码 2**：
受管集合悄悄变空，所有文件都会被误报成「未知」，那种假警报会把真信号淹掉 ——
**一个会误报的哨兵，两次之后就没人看了。**

判据是**穷举 + 显式登记**：NAS 上只允许三种东西 —— 受管的、`KNOWN_NAS` 里逐条写明了
理由的（`.env`/`prowlarr/`/库/日志/缓存/杂物）、以及**没登记过的**（报警）。
报警文案会直接给出两条出路：**收进 `FILES`**，或**加进 `KNOWN_NAS` 并写清它凭什么在那儿**。

> ★ 另加一条只有 SMB 环境才需要的判据：**「NAS 上没有某个白名单文件」这个结论要两次确认**。
> 枚举**只会漏文件、不会凭空造文件**，所以这是整个哨兵里**唯一可能产生假警报**的地方。
> 走查说没有时，再 `stat` 一次复核；`stat` 说在 ⇒ 那是**「看不清」，不是「漂移」**，
> 报「枚举不完整，请复跑」并退出码 2。

#### 18.14.4 ★★ 哨兵自己的两个 bug —— 而且第二个是「防护代码」反噬

这段和 §18.10.1、§18.13.2 是同一个母题：**判据本身要先被验证一次**。

**① stderr 没护输出编码。** 脚本给 stdout 加了 `reconfigure(encoding="utf-8")`，
**漏了 stderr** —— 而它的错误信息全是 CJK + `✗`。Windows 上非 tty 的 stderr 走本地编码
（cp936），于是**读它输出的那个程序**（我自己的对照脚本）当场炸在
`UnicodeDecodeError: 'utf-8' codec can't decode byte 0xc0`。修法：stdout / stderr 一起护。

**② ★ `isatty()` 在 Windows 上对 `NUL` 返回 True。** 第一版写成：

```python
if not _s.isatty():          # ✗ 想「管道用 UTF-8、tty 交给控制台」
    _s.reconfigure(encoding="utf-8")
```

**NUL 是字符设备**，`isatty()` 对它返回 **True** ⇒ `>/dev/null` 时**反而跳过**
reconfigure ⇒ 按 GBK 编码 `✓★⚠` ⇒ `UnicodeEncodeError`。

★★ 阴险之处在三重叠加，**每一重单独看都不会怀疑到它**：

1. 那是**未捕获异常**，而**未捕获异常的退出码也是 1** —— 和「发现漂移」的 1 **一模一样**；
2. traceback 跟正常输出去了**同一个 `/dev/null`**，什么也看不见；
3. 现象是「**40/40 次全报漂移**」，看着像判据坏了，不像编码问题。

★ 而**我之前"验证过"它**：`--no-nas` / 管道 / 落文件三种跑法各跑了 15、30、40 次，
**全绿**。它们绿的真正原因是 —— **全都不是 `/dev/null`**。
**测试的"跑法"本身也是一个变量，而我恰好把所有跑法都选成了不触发它的那种。**

修法：**回到无条件 `reconfigure`**（仓库另外 7 个脚本用的就是这个写法），并把这段
连同"别改它"写进注释。**"更聪明"的版本是错的。**

#### 18.14.5 六组对照：证明它会响，再证明它不乱响

一个只报「✓ 干净」的检查器是最危险的 —— 它让人以为看过了。所以先在**隔离沙箱**
（`D:/tmp/ctl-drift*`，不碰真仓库、不碰 NAS）里跑六组：

| 组 | 场景 | 期望 |
|---|---|---|
| 阴性 | 沙箱完全干净 | rc 0 |
| 阳性① | NAS 多一个没人认识的文件 | rc 1，**点名那个文件** |
| 阳性② | 仓库多一个没登记的已跟踪文件 | rc 1，**点名那个文件** |
| 阳性③ | `deploy.sh` 的 FILES 被改坏（一行少 `::`） | **rc 2**（宁可吵不误报） |
| 对照⑥ | stdout/stderr 指向 **NUL** | rc 0（**不是异常伪装的 1**） |
| 阳性④ | 白名单目的地 NAS 上没有 | rc 1，报「NAS 上不存在」 |
| 阳性⑤ | `split_missing`：走查漏了、stat 却在 | 判成 **phantom**（不是「漂移」） |

**16 条断言全过。** 对照⑥ 是**事后补的回归项** —— 正是它抓出了 18.14.4 的 ②。

> ★ 顺带一条方法论：阳性⑤ 测不了真实 SMB 抖动（复现不了），所以把那条判据
> **抽成了纯函数 `split_missing`** 才测得到。**判据要能被直接测，才配叫判据。**

#### 18.14.6 杂物整理：只 `mv` 不 `rm`，且不留常驻文件在 NAS 上

`--cleanup` 打的计划**只用 `mv`**，把杂物搬进 `<compose>/_cleanup-<日期>/`：

* **对 NAS 的 UNC 路径跑 `rm` 是禁止的**（SMB 上没有回收站，glob 打错一次不可逆）；
  `mv` 是同文件系统内的 `rename`，**原子且可逆**，东西一件不少地进暂存区；
* 搬的**单位挑最大的那层**：`notify/probe-artifacts-*/` 底下 11 个文件是**一条 mv**（搬目录），
  `__pycache__/` 同理。判据：命中的规则**是否以 `/` 结尾**（以 `/` 结尾的描述的是目录）。
  23 个文件 ⇒ **10 项**；
* 命令**逐条显式路径，不用通配符**；`mkdir` 只对**去重后**的上级目录生成。

本次实搬 **10 项 / 23 个文件**，文件数守恒（源 23 → 暂存区 23），根目录从 20 项降到 8 项。
搬完 `find` 复核：10 个源**全部已走**、暂存区文件数**恰好 23**。

> ★ **杂物搬走 ≠ 消失**：哨兵的杂物计数**不会因此下降**（它量的是「NAS 上有什么」）。
> 要等那一整个目录在 NAS 上被删掉。**这次它故意没降** —— 那是正确行为，不是没生效。
>
> ★ 事后顺手做的一个判断：搬之前先看 `running_pid` / 心跳，确认**没有批次在跑**再动手。
> （`running_pid=None`、末次 `attempts.log` 是 `18:15:03 exit=0`。）
> 搬的都是备份/日志/字节码，本来就不在运行路径上，但**看一眼的成本是零**。

#### 18.14.7 文档同步

README 改了 **5 处**，其中**两处是它自己已经过期的说法** —— 正是哨兵要治的那类病：

1. 索引表新增「想知道 NAS 上有没有我不知道的文件」一行；
2. `scripts/` 清单补 `check-deploy-drift.py`；
3. 新增 **「漂移哨兵 —— NAS 和仓库到底一不一致」** 整节（两个方向 / 用法 / 退出码 / 杂物）；
4. 日常看板补一条；
5. ★ **纠正两处过期**：① 索引表与「电脑端已不参与」都写着
   「电脑只剩 `deploy.sh` **一个**用途」—— 现在是两个；
   ② `nas-update-env.sh` 那条⚠还写着「**不在 `deploy.sh` 白名单里**……改它记得单独拷」——
   **它 18.14.2 刚进白名单**。★ 这条过期说法本身就是「靠人记得同步」的产物。

### 18.15 ★ 推前凭据扫描：五个 bug、以及「闸门自己也要过闸门」

**起因**：`git push` 一旦把 cookie / passkey / apikey 推上去，**内容就已经在远端了** ——
删掉也只是多一个 commit，历史里还在。所以推之前要拦一道。
本节记这道闸门是怎么被**自己的对照**一个个 bug 修出来的，以及一条比 bug 更要紧的发现。

#### 18.15.1 两条网，和一件必须先说清楚的事

`scripts/scan-secrets.py`（**只读**）按**值的形状**找凭据，不按键名 ——
按键名匹配会漏掉嵌在结构里的：`TORZNAB_URLS` 是逗号分隔的一条长串、每条 URL 各带一个
`apikey=`；Prowlarr 的 `indexer.fields` 里塞着 cookie/passkey；`options`/`fields` 里还嵌一层。

| 网 | 怎么找 | 覆盖 |
|---|---|---|
| ① **值指纹** | 从本地 `.env` 提出凭据值，**只算 sha256**，再找仓库里哪一行出现同样的值 | ⚠ **很薄** |
| ② **形状正则** | 完全不依赖 `.env`：URL 里 `apikey=`、`passkey=`、`KEY=` 赋值、`Bearer`、`Cookie` | ✅ **真防线** |

#### 18.15.2 ★★ 最要紧的一条：本地 `.env` 是**开发存根**，①这张网几乎是空的

第一次实扫时 `.env.example:44` 被**值指纹层**命中两次。查下去才发现原因不在仓库，
在**本地 `.env` 自己**：

* 本地 `.env` 的 `TORZNAB_URLS` 用的**就是** `.env.example` 里那两个占位符
  （`apikey=xxxx…` / `apikey=yyyy…`）—— 实测两边 sha256 相同；
* 于是"本地 `.env` 的凭据值"里有两个其实是**模板占位符**，拿去全仓库找，只能找到模板本身；
* 扣掉它们，本地 `.env` 一共只提供了 **1 个**指纹（一个 hex 值），而**它自己也未必是真的**。

★ 真实凭据只存在于 **NAS 的生产 `.env` 与 Prowlarr UI** 里，本地从来没见过它们。
所以「值指纹 **0 命中**」**只证明仓库不含本地 `.env` 的值 —— 几乎不构成保证**。

★★ 这条推论直接决定了下面 bug ④ 的分量：**既然①几乎是空的，那么形状层就是唯一的防线；
而它当时根本不参与退出码。也就是说这道闸门在"大多数情况下"是纯装饰。**

#### 18.15.3 五个 bug —— 三个是这一轮的，全部由对照抓出

前两个更早由阳性对照抓到（其中一条在代码注释里：按"词元"算指纹时**没连 `=` `:` `&` 一起切**，
于是 `KEY=secret` 整行是一个词元，它的哈希永远不等于 `secret` 的哈希 ⇒
**泄露在 `KEY=值` 形态里的凭据一律漏报**）。下面三个是这一轮的：

**③ `\b` 锚点在 `PROWLARR_API_KEY=` 上不成立。**
形状正则原本写成 `\b(?:api[_-]?key|apikey)\s*[:=]`。可是 `_` **也是词字符**，
`PROWLARR_API_KEY` 里 `API` 前面是 `_` ⇒ **根本没有词边界** ⇒ 不匹配。
而 `PROWLARR_API_KEY` / `CROSSSEED_API_KEY` **正是本仓库最可能泄露的两个名字**。

> 抓它的方式：往阳性对照里塞 `PROWLARR_API_KEY=0123…`，结果报「**0 命中**」。
> 再用直接正则测试逐个试：`PROWLARR_API_KEY=` 漏报、`CROSSSEED_API_KEY=` 漏报、
> 裸 `API_KEY=` **命中** —— 三个里两个漏，恰好是最常见的那两个。
> 修法：前缀改成 `[A-Za-z0-9_]*`（不用 `\b`）。Cookie 那条同病同修。

**④ 形状层不参与退出码 —— 闸门是纯装饰。**
原来只有值指纹决定 `sys.exit`，形状层**打印完就退出 0**。
而形状层存在的**唯一理由**恰恰是兜住"值指纹抓不到的"（换个站 / 换了 key / 值被截断）——
结合 18.15.2，**它抓不到的正是全部**。它还为假阳性准备了两道逃生口
（`FAKE` 前缀、同行注释含 `FAKE`）—— 一个不拦东西的闸门配两个逃生口，说明本意就是要拦。

**⑤ 退出码用的是 `hits`，不是代码自己算出来的 `new_hits`。**
上方注释白纸黑字写着「这决定要不要拦推」，算出了 `new_hits` 却没用它。
而且 `line_in_head` 只长在 `if hits:` 里面 —— **形状层连"是不是本次引入"这个概念都没有**。
修的时候还连带发现：形状命中我传进去的是**行号**，而 `line_in_head` 是按**行内容**比的
（拿 HEAD 的行集合做成员判断），传行号**永远不匹配** ⇒ 每处形状命中都判成"本次新引入"
⇒ 闸门变成"次次都拦"。**同一处代码，两个方向各错一次。**

>`④` 与 `⑤` 的修法合起来是一条判据：**推前闸门判的是"这次推新引入了什么"**。
> `HEAD` 里本来就有的内容早就推上去了，拿它拦当前这次推，等于闸门永远关着
> —— 本地 `.env` 是存根时尤其如此（`.env.example` 的占位符会和 `.env` 撞上，**次次都报**）。
> ★ 但**不假装没看见**：`HEAD` 里就有的那些会单列一句警告，它们**已经在仓库里**了。

#### 18.15.4 假阳性不是"噪音"，是**闸门失效**的一种方式

首扫全仓库 5 处形状命中，逐个看完 —— **没有一处是凭据**：

| 形态 | 实例 | 为什么不是凭据 |
|---|---|---|
| 读变量的代码 | `api_key=cfg.matcher.crossseed_api_key`、`apiKey: process.env.CROSSSEED_API_KEY` | 是表达式，不是字面量 |
| 英文短语/占位符 | `please-change-me-to-a-long-random-string` | 随机凭据不会既无数字又无大写 |
| 同一字符重复 | `apikey=yyyyyyyyyyyyyyyy` | 占位符 |

不把它们认出来，闸门就**次次都红** —— 而**次次都红的闸门等于没有闸门**，
和 §18.14.3 那句「一个会误报的哨兵，两次之后就没人看了」是同一个病。
于是加了 `benign()` 三条规则，并且**每条跳过的都连理由列出来**：
静默跳过等于把闸门悄悄钻个洞。
> ★ **顺带的自我指涉**：把上面这三个假阳性例子**写进文档**，这件事本身又**制造**了同样的
> 假阳性 —— 补完本节后复扫，README 与本节各有一处 `api_key=cfg.matcher.crossseed_api_key`
> 的引用被扫到。但因为规则认得它，代价只是输出里多两行「跳过（读变量的代码表达式）」，
> **闸门不会被弄红**。这正是那三条规则的价值：它让**「讨论凭据」和「泄露凭据」不再同形**。
> 反过来说 —— 当初要是没加它们，**这一节根本没法写：一写文档闸门就红，一红就没人看了。**

（同一个道理也用在 `.env` 侧的取指纹上：占位符值不再被当成"真实凭据"，
否则模板永远自己告自己。只报**键名**与理由，不报值。）

**已知盲区，写在代码注释里而不是装作没有**：一个**真的**由小写字母 + 连字符组成、
每段都是纯字母的长密钥，`benign()` 会当成英文短语放过。
真实凭据（hex / base64 / 混合字母数字）几乎不长这样，所以这条换来的降噪远大于盲区
—— 但"几乎不可能"不是"不可能"。**要收口就得换成"熵 / 字符集"判据，而那会同时把
文档里的英文短语重新变成假阳性**：拿一个"次次都红"的闸门去换一个假想中的漏网密钥，
不划算。**这一条是权衡后决定不修的，不是没想到。**

#### 18.15.5 对照：8 组 25 条，两头都测

一个只报「✓ 0 命中」的闸门是最危险的 —— 它让人以为看过了。所以**两头都测**：
阳性能不能拦住、假阳性会不会把闸门憋成"次次都红"。回归在 `tests/test_scan_secrets.py`。

| 组 | 场景 | 期望 |
|---|---|---|
| ① | 三个最常见的名字（`PROWLARR_API_KEY` / `CROSSSEED_API_KEY` / `API_KEY`） | 形状正则**都能抓**（就是 bug ③） |
| ② | 沙箱里真泄露 | rc 1，且**值指纹与形状两条路各自点名** |
| ③ | 干净文件 | rc 0、报 0 命中 |
| ④ | 分类名被文档提到 | **不**报命中 |
| ⑤ | **把 `.env` 挪走**，断掉值指纹那条路 | 形状层**单独**也 rc 1（就是 bug ④） |
| ⑥ | stdout/stderr 指向 **NUL** | 与管道跑法**同**结果（Windows 上 NUL 是字符设备，见 §18.14.4） |
| ⑦ | 三类假阳性 + `benign()` 直测 | rc 0；跳过项**带理由列出**；`benign(真 key)` **必须返回 None** |
| ⑧ | 同一行先 commit、再造一条新的泄露 | 前者**不拦**（标「HEAD 里本就有」），后者 **rc 1** |

**25 条断言全过。** ⑦⑧ 是**事后补的** —— 正是它们抓出了 ④ 和 ⑤；
而 ⑦ 里那条"`benign()` 对真形状的 key 不许放行"是**反向**的护栏：
免得将来有人为了让闸门安静，把规则放松到把真凭据也放过。

#### 18.15.6 归档：两道闸门进仓库，以及一条被实测推翻的旧说法

* `D:/tmp/scan-secrets.py` → **`scripts/scan-secrets.py`**；
  `D:/tmp/verify-scan-secrets.py` → **`tests/test_scan_secrets.py`**。
  两者原先都只在 Windows 上、**没有版本管理** —— 跟 `tests/` 那 7 个脚本当初一样的问题
  （工具不跟着 `push` 走，等于只有一个会记得它的人在维护它）。
  搬家时按 `tests/` 的既有约定改了路径：`REPO` 按 `__file__` 解析（任一 cwd 都行），
  沙箱改 `tempfile.mkdtemp()`（**仓库之外**）。
* `scripts/check-deploy-drift.py` 的 `LOCAL_ONLY` 补了 `scripts/scan-secrets.py` ——
  它是**在 Windows 上跑、不上 NAS** 的，不登记就会被 B 方向报成"未登记"。
  ★ 这正是哨兵存在的意义：**新加一个脚本，忘了登记，是不会有任何东西提醒你的。**
* ★ **闸门自己的对照集必须先过闸门自己。** `test_scan_secrets.py` 里的"凭据样本"
  一律由变量拼出来（`"-".join([…])`、`"y" * 16`），源码里不留字面量；
  否则推前扫描会扫到**这个测试文件本身**。
  实测两条新文件单扫 → **0 命中、0 跳过**。
* ★ **一条被实测推翻的旧说法**：§18.14.6 记「杂物 23 个，搬走不等于消失」。
  现在实测是 **26 个**，而且**不是**整理失败 —— `__pycache__` **会自己长回来**：
  NAS 上真的在跑 Python（`drive-loop`），import 一次写一次 `.pyc`。
  整理完 23，二十来分钟后复跑 26，多出来的 3 个正是 `drive-loop/…/__pycache__/` 下的。
  **所以杂物的下界不是 0，而是"正在跑的那几个模块"。**
  已同步进 README「漂移哨兵」一节。★ 这条本身就是本次那一轮活儿的主题：
  **写进文档的结论会漂，得有人隔一阵子回去量一次。**

#### 18.15.7 下一步（不阻塞）

1. ⬜ **用户在 NAS 上删掉 `_cleanup-20260912/`**（暂存区 18 个文件）。
   ★ 删完**也不会到 0**（见上）。
2. ⬜ **搬迁后次日 01:45 之后复核** `:3060` 上 `IYUU自动辅种` 条数是否仍在增长 ——
   §18.8 留的**唯一生产级反证点**。
3. ⬜ `scan-secrets.py` 的已知盲区：**权衡后决定不修**（理由见 18.15.4）。
4. ✅ 不做：把 `scan-secrets.py` 接进 git hook / CI。现阶段它是**手动跑的一步**
   （同 `deploy.sh` 的定位），接自动化要先把"本地 `.env` 是存根"这件事解决掉
   —— 否则自动跑起来也只是一遍遍地证明"仓库不含一份占位符"。

### 18.16 ★ 把 §18.8 的证伪点挂成每日自动观测（2026-09-12 晚）

**起因**：§18.8 末尾留了一句「搬迁后次日 01:45 之后复核 IYUU 辅种条数是否仍增长 ——
这是**唯一**能在生产中证伪本节结论的观测点」。用户问：**能不能在 NAS 上挂起，
每天看日志结果再来分析？**
★ 这么问是对的：人工盯一眼只证明「**那一刻**在长」，看不出「停没停」——
而后者才是证伪点。

**结论：能，而且不用新挂 DSM 任务。** `drive-loop.py` 里**已经有一个每天跑一次的
「每日台账」**（`report_daily()`）。

#### 18.16.1 现成的管道，和一个不看就发现不了的坑

`report_daily()` 自己用 `.daily-report.state` 记 `last_day` 去重 —— **不能靠 notify 去重**：
notify 的冷却**只对 `alert` 生效**，`batch` 每批都真的往 spool 写一个文件（见该函数 docstring）。

★★ **关键发现**：notify 的 TSV 流水（`notify-spool.sh:334` `log_event`）**只记
`ts / kind / title / metrics` 四个字段，不记正文**：

```bash
printf '%s\t' "$(field_of "$_f" ts)" ... "$(printf '%s\n' "$(field_of "$_f" metrics)")"
```

所以这个条数**必须走 `metrics`** 才留得下痕。只写在正文里的话，**人收到邮件、看着一切正常，
可回头分析时数字根本不在日志里** —— 这种「看着发了、其实没留痕」的坏法，
**肉眼完全看不出来**。测试里专门钉了这一条。

#### 18.16.2 ★ 时间差：日报的采样点落在 IYUU **之前**

IYUU 的 cron 是 `45 1 * * *`（**01:45**，§18.8 实测的任务定义）；而日报在**当天第一批**
触发 → 约 `00:0x`。于是：

| 日报日期 | 那一刻读到的是什么 | 有意义吗 |
|---|---|---|
| 09-13 00:0x | 搬迁后 IYUU **还没跑过**（它下一次是 09-13 01:45） | ❌ |
| **09-14 00:0x** | 09-13 01:45 那批**已经跑完** | ✅ **第一个有意义的读数** |

跟任务里写的「次日 01:45 之后」是一致的 —— 只是自动化之后，第一次有意义的读数
落在 **09-14 凌晨**，不用人半夜爬起来。判据是**基线 100 条**（2026-09-12 实测，§18.8 构成表）。

#### 18.16.3 实现：只改两个**已经在白名单里**的文件，零新增

选它而不是「独立脚本 + 独立 DSM 任务」，核心理由是**不新增文件** —— 那就绕开了
§18.15.6 刚记过的那条教训（「新加一个脚本，忘了登记，是不会有任何东西提醒你的」），
也不用谁去 DSM 里手工建任务。

* `orchestrator/state.py`：加 `qbit_tagged(url, tag)`。
  ★ **没有抄第三份实现** —— 把 `qbit_torrents` 和它的取数抽成共用的
  `_qbit_torrents_info()`，理由直接引用那个文件节首已有的那段话：
  「两份实现"改一个忘一个"就会静默算错数」。
  ★ **`qbit_torrents` 在每 15 分钟的热路径上**（回灌），所以这次重构必须
  **行为逐字节等价** —— 测试里钉了它的 URL **字面量**。
* `drive-loop.py`：`report_daily()` 里加一节 `iyuu_watch()` → 正文一行 +
  `metrics={"iyuu": n}`。**绝不抛**（它挂在每天一次的日报里，日报挂在每 15 分钟一批的
  生产循环里）；读不到时 metrics 给 `n/a`，而且**必须给** —— 否则 TSV 里
  「这次读失败了」和「那天根本没跑」长得一模一样，事后分不开。
* ★ **只记账、不告警**：这是慢性观测（要几天才有结论），即时 `alert` 通道必须留给
  急性故障 —— 否则就是 §16.1.3 那条「骚扰多了你去建过滤规则，然后连真告警一起过滤掉」。

#### 18.16.4 对照：9 个脚本 259 条

`tests/test_iyuu_watch.py`，6 组 30 条。★ 它钉的**不是**「数字算得对」（那太简单），
而是三件更容易**静默**坏掉的事：
① 重构没改行为（URL 字面量 + 中文 tag 必须被百分号编码，整个 URL 要纯 ASCII）；
② `iyuu_watch` 三种情形（正常 / qB 挂 / 没配 url）**都不许抛**；
③ **数字真的进了 `metrics`**（就是 18.16.1 那个坑）。

★ 顺带踩到一个 `importlib` 的坑，已记进 `tests/README.md`：
用 `spec_from_file_location` 载进来的模块，**必须先 `sys.modules[name] = mod` 再
`exec_module`** —— 否则被测文件里只要有 `@dataclass` 就炸，而报的是一个**看着毫不相干**的
`AttributeError: 'NoneType' object has no attribute '__dict__'`
（`dataclasses` 要 `sys.modules.get(cls.__module__).__dict__` 去找注解的命名空间，
而 `spec_from_file_location` **不会**替你登记）。
★ 值得记的是**它的表现**：同一段 `_load` 代码对两个文件行为不同 —— `drive-loop.py`
没有 dataclass，所以它先跑通了，一度让人以为只有 `state.py` 有问题。**原因却不在它们身上。**

### 18.17 ★ 哨兵那句「已登记」其实是**死代码** —— 中文路径被 git 转义（2026-09-12 晚）

**起因**：给 `check_indexers` 补完测试，按惯例跑一遍漂移哨兵做提交前自查，B 方向报：

```
★ 未登记 1 个 —— `git push` 会把它们带走，但它们**不会**上 NAS：
    "\350\265\260\350\277\207\347\232\204\345\274\257\350\267\257.md"
```

可这个文件**上一轮刚登记进 `LOCAL_ONLY`**（§18.15.6 那次一并做的）。两个事实
不可能同时为真 —— 查下去，是登记那一步从来就没生效过。

#### 18.17.1 根因：`core.quotepath` 默认把非 ASCII 路径转义成**纯 ASCII**

```
$ git ls-files | grep 弯路
"\350\265\260\350\277\207\347\232\204\345\274\257\350\267\257.md"
```

git 默认 `core.quotepath=true`，非 ASCII 路径被转义成 C 风格八进制串 ——
**一整串纯 ASCII，连引号都是字面量**。哨兵拿它去匹配 `LOCAL_ONLY` 里那条
`^走过的弯路\.md$`，**永远匹配不上**。

所以上一轮那句「已登记进 `LOCAL_ONLY`」实际上是一行**死代码**；哨兵报的
「未登记」是**假阳性**，而且**报了整整一轮没人发现**。

#### 18.17.2 修法，以及一条「更省事但更糟」的岔路

* `-c core.quotepath=false` 让 git 直接吐原始字节；
* 再**显式** `r.stdout.decode("utf-8", "surrogateescape")`。

★ **别图省事只把 `text=True` 改成 `encoding="utf-8"` 就以为完事** —— 方向对，但
要意识到**为什么原来那行不能留**：`text=True` 用
`locale.getpreferredencoding()` 解码，Windows 上那是 **GBK**，会把 UTF-8 路径
**解成乱码**。乱码匹配不上，只会让报错「看起来更奇怪」—— **比假阳性更难查**。
（同一个形状 §18.16.4 的测试里已经踩过：**编码问题伪装成别的问题**。）

#### 18.17.3 ★ 值得记的不是这个坑，是它的**表现**

哨兵当时**是绿的**（rc=0、两个方向都报「干净」）—— 绿的唯一原因是**那条规则压根
没参与匹配**。

> **「我改完了、跑了一遍、是绿的」，在确认过「这条规则真的被走到过」之前，
> 是零信息量的。**

这跟 §18.15.6 是同一件事的两个面：

| 节 | 失败方式 |
|---|---|
| §18.15.6 | 新加一个脚本，**忘了登记** → 没有任何东西提醒你 |
| §18.17 | 新加一条登记，**因为匹配不上而等于没加** → 同样没有任何东西提醒你 |

★ 共同点：**「防护措施没生效」和「防护措施生效了、没问题」在输出上长得一模一样。**
这是本项目反复出现的形状 —— §18.8 的 `iyuu=n/a` ≠ 那天没跑、§18.16.2 的日报采样点
落在 IYUU **之前**、`.daily-report.state` 的 `last_day` 去重（§18.16.1）。
**凡是「没输出」既可以解释成「没事」、也可以解释成「没跑」的地方，都要额外钉一个
正向证据** —— 本次新增的 `tests/test_check_indexers.py` 里 §⑦ 那一节
（「没 `--db-path` → 静默跳过」）钉的就是同一个形状。

修完复检：B 方向 `未登记 0`，两个方向都干净。

### 18.18 ★ 「对账全绿」里的绿，可能是**规则没参与**（2026-09-12 晚）

把前几轮一直在论证的两条判据落成可执行的对账：**(1)** 生产日志里 `Found` 行的
a−b / b−c；**(2)** `sync_movie` 收到四个空集之后到底会变成什么。两条都跑了，
两个 0，但**两个 0 的覆盖范围都比字面窄** —— 这就是这一节值得记的地方。

#### 18.18.1 a−b / b−c：两个 0

| | 值 | 说明 |
|---|---:|---|
| a（基线） | 1011 | 6 个**独立字面量**的合取 |
| b（`_RE_FOUND`） | 1011 | **a − b = 0** |
| c（归到单片） | 1011 | **b − c = 0**（`other_pack` 0、`unresolved` 0） |

基线第一版拿 `] Found ` 当判据，数到 **2200** —— 那个字面量同时吃到
`Found 0 torrents for` 与 `Found N torrent file(s) to inject`，共 1189 行。
**基线既不能用带锚点的正则，也不能太松**；加固的办法是「若干独立字面量的合取，
且每个字面量各自报数」，这样"是哪个词把行数砍下来的"一眼可见。

三道正向控制（读到了行 / 基线数到了 / 目标形状非空）都过 —— 没有它们，
0 和「压根没跑」在输出上长得一模一样（§18.17.3 的形状）。

★ 本节的 b−c 走的是**生产代码本身**：真的 `StateStore.roots/dir_paths/
farm_dir_paths/farm_root` + 真的 `_resolve_searchee_to_pack()`，只把 searchee
路径换成日志里那一条。上一版自己**重写了一遍** roots/dpaths/farm 的拼装逻辑，
那是"用我的模型核对生产模型" —— 属于循环论证，作废。

#### 18.18.2 ★ 但这个 0 覆盖不到 v3 的农场那条路

```
[webhook]  n=1011   首 01:00:15  末 17:09:08   组5 含 /reseed: 0
```

1011 条**全部**是 `[webhook]`、组5 **全部**是原路径。也就是说 `_RE_FOUND` 里的
`[inject]` 分支、以及 `_resolve_searchee_to_pack()` 的**农场分支**（`:1749-1756`），
在这个窗口里流量是 **0**。b−c=0 是「原路径」这条制度的绿，
**不是** v3 农场路径那条防线的绿。

农场路径确实在日志里出现过（328 行，15:27 起；旧农场根最后 14:27、新农场根首次
15:27，迁移时点就在这中间），但只出现在
`[inject] Skipping match … with /…/reseed/reseed_farm/… due to title mismatch`
里 —— 那是**另一条消息**，`_RE_FOUND` 根本不覆盖它。

所以要等**农场路径的 Found 行**出现，那一格才有信息量。在那之前，它和
§18.17 是同一个形状：绿，但绿可能是因为规则压根没参与匹配。

农场的正向证据目前只在别处：`Skipping match` 的 `with` 一栏给出的候选确实是
农场路径 —— 说明 `DATA_DIRS` 指农场这件事**是生效的**，只是没走到 Found 这条路。

#### 18.18.3 顺带：只读口也要问「这个方法是谁的」

UNC 上 `file://<host>/<share>/…` 一律 `invalid uri authority: iSunker-DS423`。
最后用的是 **裸路径 + `PRAGMA query_only = 1`** —— 写完才发现
`state.py:_open_csdb`（`:538-541`）本来就这么干，连 `timeout=5` 都一样。
**先认出"这是项目自己的既有做法"再动手**，比自创一个偏方安全得多。

旁证（不是假设）：`state.db` 旁没有 `-wal` / `-shm` / `-journal`，
`journal_mode=delete` —— 事务是干净的，直读不会漏掉已提交的事务。

#### 18.18.4 四个空集：降级，不是删行；而且连「搜过」都不剩

`sync_movie`（`:1426`）是**整行覆盖**写（`:1492-1501`），只有 `indexer_seen`
（`:1474-1481`）与 `attempts` 是合并的。新增 `tests/test_sync_empty_sets.py`
（31 条断言）钉住的：

- SEEDING →(四空集)→ **PENDING**：行还在，`seeding_count`/`matched_hashes`/
  `searched_indexers` 被**整行**抹掉，`attempts` 不虚增（空集不算一次尝试）。
- `indexer_seen` 合并保留 → `next_retry_at` = **T0 + 14 天**；
  对照组（无历史）`next_retry_at is None` 立刻可搜。
  **两个同为 PENDING 的行，差别只来自 `indexer_seen`** ——
  这正是「额度悄悄烧掉一轮」的形状：它看着像"还没搜过"，其实要等满一个周期才轮得到。

#### 18.18.5 ★ 一条计数器 / 两条静默通道

端到端那一段是最锋利的：让 `decision` 里的 searchee 路径漂到别的包
（`other_pack`），一部 SEEDING 的片子会**塌成 PENDING**，而 `rep.unresolved` = 0、
`rep.from_db` = 0 —— **报告一个字都不说**；
换成"名字认不出"（`unresolved`），后果**一模一样**，`rep.unresolved` = 1。

同一个后果，只有后一条通道会喊。原因是调用点长得不对称：

| 通道 | 位置 | 有没有计数器 |
|---|---|---|
| `db.searched` 循环 | `:1884-1888` | `unresolved` 计数，`other_pack` **静默 `continue`** |
| `db.decisions` 循环 | `:1894-1897` | `if d is None: continue` —— **一个计数器都没有** |
| 日志 `Found` 路径 | `:516-521` | `if d:` —— 同样没有 |

`unresolved` 那个计数器本身也偏窄：它只在 `db.searched` 那条路上加。
所以「SEEDING 变少 / PENDING 变多」如果发生在农场路径漂移上，
**它在汇报里没有任何对应的一格**。

#### 18.18.6 这一轮自己也栽了一次 —— 被正向控制当场抓住

b−c 第一版把**整条路径**当 searchee **名字**传给了
`_resolve_searchee_to_pack()`（`searchee_paths` 的**键是名字**、值是路径），
于是 `.get()` 永远取不到 → `p=""` → 每一行都掉进"只按名字猜"的兜底分支。
它报出来的 `440 / 571` **看着完全合理**。

抓住它的不是我的判断，是开机就跑的**正向控制①**：拿库里**自己**的
`movie.path` 去解析，`in_pack` 都归不到 ⇒ 解析链是坏的 ⇒ 下面的数全是假象。
这是"凡是没有输出/奇怪的输出，都要额外钉一个正向证据"第一次在**当场**、
而不是事后复盘时，救下一次误判。

（另有一次报红是**我的断言写窄了** —— `tests/test_sync_empty_sets.py` §②
只期望一条流水，实际 `PENDING → SEEDING` 那次也是变档、也留一条。
代码是对的。已作为第三条「先怀疑断言」记进 `tests/README.md`。）

纯文档 + 测试，`tests/` 与 `SUMMARY.md` 都不在 `deploy.sh` 白名单里，**无需 deploy**。

#### 18.18.7 两个对账脚本已收进版本库（2026-09-12 夜）

原先它们只在 `D:\tmp` 里 —— **判据不在版本库里，等于过期即失效**：
`D:\tmp` 一清、或者下次改完 `_RE_FOUND` 想复跑，就没有脚本可跑了。
已搬进 `scripts/`（按 `__file__` 解析仓库根，不再写死路径）：

| 原位置 | 现位置 | 对账什么 |
|---|---|---|
| `D:\tmp\audit-found2.py` | `scripts/audit-found-lines.py` | **a − b**：字面量合取描述的「目标形状」= `_RE_FOUND` 认的（期望 0） |
| `D:\tmp\audit-bc.py` | `scripts/audit-found-resolve.py` | **b − c**：抓到的行真的归到了某个单片（期望 0） |

★ 搬家时改了一处**实质**：`audit-found-lines.py` 原先**自己抄了一份** `_RE_FOUND`
字面量。抄一份就等于把被测对象复制成判据 —— 正则改了、脚本照旧报绿。
现在它 `import orchestrator.state` 直接取 `S._RE_FOUND`，**判据引用生产那一份**。

已按 `scripts/` 的惯例登记进漂移哨兵的 `LOCAL_ONLY`（理由：在 Windows 上跑、
只读 NAS 的日志与库），漂移哨兵两个方向仍干净（`★ 未知 0` / `★ 未登记 0`）。
搬家后**从新位置复跑，输出与搬家前逐字一致**：
`总行数 28905`、`a − b 0`、`b − c 0`（`other_pack 0 / unresolved 0 / in_pack 1011`）、
三道正向控制全过。

★ `audit-found-resolve.py` 里新加的那行自检值一提：输出里单列了
**`组5 落在农场根下 : 0`**，并直接标注「这一格恒为 0 时，下面那个 0 覆盖不到农场防线」——
把 §18.18.2 那个坑**印在报告里**，而不是只写在文档里。下次谁看到 `b − c = 0`，
不用翻 SUMMARY 也知道这道绿管的是哪条路。

顺带修掉 README 里两处**陈旧计数**（同一句话里的 `tests/` 规模还停在
「8 个脚本 / 229 条断言」，实际已是 11 / 332），以及「电脑端只剩三个用途」
（现在还有这两个对账脚本）。这类**同一个事实写在两处**的漂移，正是
「唯一出处」那条约定要防的 —— 这次是顺手撞见，不是查出来的。

---

### 18.19 三条观测判据进生产（2026-09-12 夜）

三轮论证收敛到一句：**瓶颈不在输入侧（枚举/识别），在观测侧（对账）。**
落地的是**三条**，顺序 ①→②→③ 不能换（③ 依赖 ①）。

#### 18.19.0 共同的落点：为什么判据本体搬进了 `orchestrator/state.py`

三条判据本体原先（或本来会）写在 `scripts/audit-found-*.py` 里。搬家的理由只有一个，但是硬的：

| | `scripts/audit-found-*.py` | `orchestrator/state.py` |
|---|---|---|
| 在 NAS 上吗 | **不在** —— `deploy.sh` 的 `FILES` 里没有，`check-deploy-drift.py` 把它俩标成 LOCAL_ONLY（Windows 侧诊断） | **在**，且被部署**两次**（构建上下文 + `drive-loop/orchestrator/`） |
| 路径 | 写死 `//iSunker-DS423/...`，**NAS 宿主机上不存在这个路径** | 无路径依赖，只收文本/连接 |

而要跑这些判据的是 `drive-loop.py`，它跑在 **NAS 宿主机**上
（`drive-loop-nas.sh`：`PY=/usr/bin/python3`，DSM 自带 3.8.15，**不是容器**）。

⇒ `orchestrator/state.py` 是两侧**唯一都能到达**的地方。两个脚本因此降级成**薄壳**：
手工随时能跑，核的是**同一份实现**。

★ 顺带更正一条先前的错话：曾说过「`sync_pack` 只拿得到一个包，**物理上算不出**三包并集」。
**错了** —— `sync_pack(store, ...)` 第一个参数就是 `store`，`store.packs()` 就能取全部。
真正的问题是**放哪**：它一包一调，一轮会算 3 次、发 3 条通知，所以放收尾
（`after_batch_reports()` 之后）。

#### 18.19.1 ① 口径改名 —— 一个名字盖了两种模型

`audit-found-resolve.py` 的历史 `other_pack = 0` 被当成过「干净」。**实测（NAS 只读）**：

```
Found 行共 1011 条
〔全量口径〕所有包一起试、命中即停   → in_pack 1011  other_pack 0
〔生产口径〕一次一个包（sync_pack）  → dc-collection  other_pack 865
                                     frds-top250    other_pack 146
                                     mbf            other_pack 1011
```

**根因**：三个包**共用一个 `farm_root`**（`fix-statedb-farm-root.py`：迁移 SQL 一次改
3 行 `pack.farm_root`）。cross-seed 扫的是那**一个**农场，所以对任一包来说，
**别的包的 searchee 天然就是 `other_pack`**。

⇒ 两个口径**都在输出里**，每个数都**绑定自己的口径名**，不出现裸的 `other_pack`。
这跟 `NanyangPT` vs `NanyangPT (南洋)` 是**同一个形状**。

★ **更重的一句**：那个 `other_pack = 0` 是**该脚本自己循环构造的产物**
（所有包一起试、命中即停），**不是日志的性质**。所以 §18.18.2 那句
「b−c=0 覆盖不到农场」底下还必须垫一句：**这个 0 本身换过口径，它跟生产口径下的数不可比**。

#### 18.19.2 ② 全场无人认领 —— 期望值指回一条真实记录

加的不是 `other_pack` 计数器（见 18.19.1：那在生产口径下是个大常数），而是
**「三个包合起来都认不出」** 的 searchee。实测：

```
库里 searchee 名数 : 1888        （searched 941 / decisions 608）
归属分布           : in_pack 1887   other_pack 1   unresolved 0
★ 唯一无人认领的那条：
   /volume1/video/download/reseed/reseed_farm/0观影清单chrlee整理
       └─ 里面只有一个文件：豆瓣&IMDB电影TOP250_20240501_chrlee整理.xlsx
```

它在农场里、源还在（`build-farm.sh --verify` 抓不到）、三包都不认它，
`searched`/`decisions` 里**都没有它** —— 所以它今天不烧额度，是**潜伏**的。

★ 它的价值不在「要删」：**它是一个判据之外的真实记录。** 新判据今天应当报 **1** 并
指名这一条 —— 报得出这个 1，计数器才可信。这正是收敛判据要的
「**期望值能指回一条判据之外的真实记录**」的第一个具体实例。

★ 判据**必须带名**：只报数就是「换了个地方藏」（告警正文里点名路径）。

#### 18.19.3 ③ a−b / b−c 进 metrics，`b > 0` 作硬判据

- 判据 = 六个**独立字面量的合取**（`state.FOUND_LITS`），**不是** `] Found ` 单字面量
  —— 后者会吃到 `Found 0 torrents for {` 与 `Found N torrent file(s) to inject`，
  实测 **2231 vs 靶心 1011**，正是 §18.18.1 那个假差。
- 接线：`drive-loop.py` 的 `reconcile_watch()` → 每日台账 `metrics`
  （`fa/fb/fd/fb_c_all/fb_c_farm/unclaimed`），并**立刻**发 alert：
  `log-parse-miss`（差不为 0，正文带留证行）/ `reconcile-empty`（**b == 0 = 空转，
  不是干净**，§18.17.3）/ `reconcile-controls` / `unclaimed-searchee`。
- 读不到时 metrics 给 **`n/a`**（不是 0）—— 否则 TSV 里「这次读失败了」和
  「那天根本没跑」长得一模一样。

★ **实测抓到的一处真形状**：第一版合成用例把组 4 写成了 `webhook`/`inject`，
而生产日志里 **组 4 是判定**（`MATCH` / `MATCH_PARTIAL` / `MATCH_SIZE_ONLY`），
组 1 = searchee 名、组 3 = 站名、组 5 = searchee **路径**。合成形状对不上生产 =
自说自话，已改正并按真实行形写死在 `tests/test_reconcile.py`。

★ **基线比正则松恰好一个词**：六个字面量**没有**钉住 `[webhook]|[inject]` 标签，
而 `_RE_FOUND` 钉了 ⇒ 基线是正则的**超集**。今天 `a == b == 1011`，但那是**实测**、
不是**结构保证**；`tests/test_reconcile.py` 里有一格专门拿 `[search] Found …` 钉这个差。

#### 18.19.4 验收

```
12 个脚本 / 382 条断言 / 0 失败           （+test_reconcile.py，50 条）
scan-secrets.py            rc=0
check-deploy-drift.py      rc=0   A: 未知 0   B: 未登记 0
audit-found-lines.py       a 1011 / b 1011 / 差 0，三道控制全过
audit-found-resolve.py     〔全量〕b−c = 0；〔生产〕865 / 146 / 1011（与预期一致）
```

> ★ 计数后已变：**同日深夜再补 15 条**（`50 → 65`，总数 `382 → 397`），
> 原因是复核时发现「三个出口」里**只有一条被钉过** —— 见 **§18.20**。
>
> ★ 再补：**2026-09-12 更晚**又加了一类（声明点〔`--packs`〕）与一个新脚本
> （`test_roots_from_env.py`）：`65 → 79` / 新增 20，总数 **431** —— 见 §19.1.2 / §19.1.6。

★ **拿真日志跑了一遍"出厂那份代码"**（不只是合成用例）。`reconcile_watch` 只在
**每天一次**的日报里被调用 —— 生产上要等到次日 ~11:12 才第一次真跑，在那之前
「它能不能吃下真文件」是没人看过的。于是单独跑了一次（只给 `--log`，不给库，
全程只读一个文件、不碰 UNC 上的 SQLite）：

```
fa=1011  fb=1011  fd=0   fb_c_all=n/a  fb_c_farm=n/a  unclaimed=n/a
观测对账 a−b〔当日日志〕：形状 1011 / 正则 1011 / 差 0
  （期望差 0；合取比 L1 单字面量收窄了 1220 行）      ← 1011+1220=2231，与上午实测同
发出的告警：（一条都没有）                              ← 差 0 且 b>0，就该是空的
```

`b−c` / 无人认领 给 `n/a` 是**设计如此**（没给库）—— 正好把「读不到 ≠ 0」这一格
在生产形状下也验了一遍。

#### 18.19.4.1 部署与"跑起来了"的证据（2026-09-12 21:22 / 21:34）

空窗：`.drive-loop.state` 显示上一批 20:55:34 结束、`last_sleep_sec=10800`（站点退避
180 分钟）→ 下一批 ~23:55。两次部署都落在这个窗里。

| 时间 | 动作 | 证据 |
|---|---|---|
| 21:22 | `deploy.sh --apply`（3 个目标：`state.py` ×2 + `drive-loop.py`） | 三个目标的 md5 与本地**逐字节相同** |
| 21:30 | DSM 唤醒跑了一批（跳过） | `attempts.log` `exit=0` + `drive-loop.log` 「距上次批次结束仅 34.5 分钟，跳过本轮」 —— ★ **这就是"新代码在 NAS 的 python3.8.15 下起得来"的硬证据**：起不来只会写 `attempts.log` 的 start 行、`drive-loop.log` 一个字节都不写 |
| 21:34 | 第二次 `deploy.sh --apply`（补口径名那一次） | md5 再次一致 |
| 次日 ~11:12 | **首次真的跑 `reconcile_watch`** | 看 `notify/log/<日期>.tsv` 里那几格是否出现（`n/a` ≠ 没跑，是"读不到"） |

★ 顺带把「整读当日日志」的风险关掉了：`info.current.log` 由 cross-seed **按天轮转**
（实测 09-12 当天 6.2 MB，旁边躺着 `info.2026-09-11.log` 3.5 MB），所以这里可以
整读全文 —— 不会涨到几百 MB。对比 `STALE_ENV_TAIL_BYTES` 那边只读尾部：那是
**每批都跑**的热路径，两个场景的取舍不同。

★ 顺带发现并修掉一处**计数本身的错**：`tests/README.md` 里那句断言总数**一直是错的**
（写 373，真值 382 —— 只数了 `  ok  ` 一种行形，把 `test_remove_indexer.py` 的 8 条
整个漏掉）。这和 §16.2.1「校验的期望值不能来自被校验对象本身」是**同一类**：
一个"看着挺具体"的数，没人重数过就一直错着。已在 `tests/README.md` 里补上
**可重跑的数法**，并把 `test_reconcile.py` 加进那张表（原先根本没它这一行）。

#### 18.19.5 仍未做（按决定推迟）

| # | 动作 | 为什么推迟 |
|---|---|---|
| 4 | `check_farm_mirror` 拆「源侧缺 / 农场侧缺」两格，挂进 `check_farm()` | 方向和不对称证据都成立（源侧缺 → 农场照搜 → 白烧额度；农场侧缺 → 白等一轮），但**今天没有这两侧的实例** —— 先等它出现，别拿合成数据当「已验证」。★ 附一条做之前要查的：`dir_paths` 是推导式建的 dict、`farm_dir_paths` 用 `setdefault`，**两个单片同路径时谁赢不一样** |
| 5 | `.farm-check.state` 存「上次全绿时刻 + 缺失集合」，绑事件名 | 依赖第 4 条存在 |
| 6 | 把「动态递归遍历 / 媒体类型分类器 / 智能命名正则库」三条**不做**的理由写成一节 | ★ 顺序理由其实**不成立**：那三条的理由全来自**当下代码**（`Season\|S\d` 在整个 `orchestrator/`+`scripts/` 里**零命中**、`matcher.py:138-139` 写明「仅供人看，不作准」、`STAGE_UNMATCHED` 已在），**不依赖 ①②③**。放最后是纯延迟，不是依赖 |

### 18.20 复核「三个出口」时，发现**出口自己没被验**（2026-09-12 深夜）

> 这一节是 §18.19 的**复核**产物。起因只是问了一句「`b == 0` 落在哪一格」，
> 结果那一格是**闭环的**，但它旁边有两条分支**整段删掉测试也不会红**。

#### 18.20.1 先回答那一问：`b == 0` 走 `reconcile-empty`，是告警不是缝隙

`drive-loop.py` 里是个**四档** if/elif，顺序与名字一样明确：

| 档 | 条件 | 出口 |
|---|---|---|
| 1 | `not c.controls_ok` | `alert` key=`reconcile-controls`（判据没走通） |
| 2 | `elif c.b == 0` | `alert` key=`reconcile-empty`（**空转**）★ 就是这一格 |
| 3 | `elif c.delta` | `alert` key=`log-parse-miss`（形状对、正则没吃下） |
| 4 | 其余 | 什么也不发（干净） |

`controls_ok` 还**刻意不含 `b > 0`**（`state.py:1832-1839` 明写），就是为了让
「判据坏了」和「真的没发生」分开 —— §18.17.3 要的正是这个。

#### 18.20.2 ★ 但三个出口里，**只有第 3 个被钉过**

`grep` 三个 key 在 `tests/test_reconcile.py` 里的结果：

| key | 接线层（真的调 `reconcile_watch` 看它 emit 什么） |
|---|---|
| `log-parse-miss` | ✅ 有（一条） |
| `reconcile-empty` | ❌ **零断言** |
| `reconcile-controls` | ❌ **零断言** |

函数层是测过的（`count_found_lines` 那一层钉过 `controls_ok` 与 `b == 0`），
但**接线层没有** —— 今天把 `elif c.b == 0` 整段删掉，**测试全绿**。

★★ 这和 §18.18「对账全绿里的绿，可能是规则没参与」、以及 §18.19.4 那个
断言总数写错 373→382，是**同一个形状**：**判据被验过了，判据的出口没被验。**
而本系统的全部价值就在「出口会响」—— **一个不会响的出口，在无人值守下
和"根本没有这个出口"完全等价。**

#### 18.20.3 补的两条，以及**阴性对照**

新增两格（各钉 key + 正文里那句话）：`reconcile-controls` 拿一条
「日志读得进来、但一行 `] Found ` 都没有」的样本；`reconcile-empty` 拿
`[webhook] Found 0 torrents for {…}`（L1 吃得到、六字面量合取吃不到）。

★ 两格**必须分得开**：它们的 metrics 都是 `fb = 0`，含义却相反 ——
一个是「判据坏了」、一个是「判据好的、今天真没有」。混成一条就没法从告警
判断该去查哪儿。

★ 然后做**阴性对照**（这是本轮唯一新增的方法，值得记）：

| 打断什么 | 结果 |
|---|---|
| `key="reconcile-empty"` → 改成别的 | 测试**变红**，失败条目正是「`reconcile-empty`」 |
| `key="reconcile-controls"` → 改成别的 | 测试**变红**，失败条目正是「`reconcile-controls`」 |
| `if not Path(db_p).is_file():` → `if False:` | 测试**变红**，失败条目是「父目录都没被建」 |

三条全中，且还原后复跑全过。**「先证明它会响」这一步不能省** ——
不然又是拿一条"从没参与过匹配"的判据当保险。

#### 18.20.4 顺手堵掉一个「沉默会变成数字」的入口

复核 §18.19.3 那句「读不到给 `n/a`」时，发现三个输入里**有一个不走这条路**：

| 输入 | 缺失时会怎样 |
|---|---|
| `--log` | OSError → 六格保持 `n/a` ✅ |
| `--db-path`（cross-seed.db） | `read_crossseed_db()` **主动 raise** `FileNotFoundError` → `n/a` ✅ |
| **`--db`（sidecar 状态库）** | ★★ **不抛 —— `StateStore.__init__` 会就地建一个空库** |

`StateStore.__init__`（`state.py:1205-1212`）第一件事就是
`mkdir(parents=True)` + `connect` + `executescript(SCHEMA)`。于是路径写错时：
**"库不在" → 不抛 → `pack`/`movie` 两张表全空 → `pack_contexts()` 返回 `{}`
→ 库里每一条 searchee 都算「无人认领」→ 报出一个巨大的假数 + 一条醒目告警，
还在错位置写下了一个库文件。**

**这是 ③ 立的规矩在第三个输入上被破的那一格，而且是往假阳性那头破。**
修法是一行：`reconcile_watch` 里先 `Path(args.db).is_file()` 问一句，
不在就 `n/a` + 一行正文（并断言**连父目录都没被建** —— 那比"文件没被建"更强，
因为它证明我们压根没把它交给 `StateStore`）。

> 今天够不到（`DEFAULT_DB` 在 NAS 上是对的），所以这是**堵口子**不是修故障。

#### 18.20.5 ★ 阴性对照本身撞到的坑：Python 往返会**改行尾**

做阴性对照时要临时改源码再还原，第一版用 `Path.read_text()` / `Path.write_text()`
往返 —— **行尾从 LF 变成了 CRLF**：`read_text` 默认做通用换行翻译（`\r\n` → `\n`），
而 `write_text` 默认 `newline=None` **在 Windows 上把 `\n` 写回 `os.linesep`（`\r\n`）**。
`diff` 立刻报「1723 行全不同」，但看起来"内容一模一样"。

★ 这个坑值得单独记，因为**它的表现和 §18.13.3「`grep -c $'\r'` 数行尾不可靠」是同一类**：
一个"看着没改"的文件，字节上已经变了 —— 而 `drive-loop.py` 是要部署到 NAS 上、
由 `sh` 与 python3 执行的。修法：备份用 `cp`（字节保真），还原也用 `cp`，
**不要用 Python 读写往返**。

#### 18.20.6 验收

```
12 个脚本 / 397 条断言 / 0 失败           （test_reconcile.py：50 → 65，+15）
python -c "ast.parse(..., feature_version=(3,8))"   两个文件都 OK
py_compile                                          OK
阴性对照 3/3 变红，还原后复跑全过
```

> ★ 计数后已变：**同日更晚再补**（`65 → 79`，+`test_roots_from_env.py` 20 条）
> → **13 个脚本 / 431 条断言 / 0 失败**，见 §19.1.6。

#### 18.20.7 记下但**没做**的两条

| # | 动作 | 为什么先不做 |
|---|---|---|
| 1 | `b == 0` 且 **`a > 0`** 时改走 `log-parse-miss`（或至少把正文里「真没搜出去过」换掉） | `a > 0` 已经**排除**了"没搜出去过"，此时正文与 metrics 打架。属于**诊断精度**问题，不是漏报 —— 排在后面 |
| 2 | 给 `n/a` 配「上次成功读数时刻」（状态文件里加一字段） | 先确认过：`--log` / `--db` / `--db-path` 在生产上都有默认值且路径存在，**长期 `n/a` 今天不会发生**。它是"下一层的保险"，等上面两条落地再说。★ 有现成先例可抄：`.farm-check.state`（`drive-loop.py:974/994-996`，上次巡检时刻 + 原子替换） |

> ✅ **两条均已执行**（外加一条复核挖出的根因门）—— 见 **§18.21**（2026-09-12 深夜 · 第二轮）。

### 18.21 结掉 §18.20.7 推迟的两条 + 两个根因闸（2026-09-12 深夜 · 第二轮）

> 这一轮就是 §18.20.7 那张「记下但没做」表的**执行**，外加一条复核里顺手挖出的根因。
> 四条并成一批做，**做完是一次部署**（见 §18.21.5）。

| # | 动作 | 落点 |
|---|---|---|
| #33 | `a > 0 且 b == 0` 改走 `log-parse-miss` | `drive-loop.py` `reconcile_watch()` 出口**判序** |
| #42 | `StateStore(path, *, create=False)` —— 默认**不建库** | `state.py` `__init__` + **13 个调用点** |
| #34 | 六个（实为八个）对账格子的 `n/a` 配「上次成功读数时刻」 | `drive-loop.py` 新 `.reconcile.state` |
| #44 | README 日常看板补**对账读法**（`n/a` vs `0` vs 基线 1） | `README.md` 日常看板一节 |

#### 18.21.1 #33：`a > 0 且 b == 0` —— **判序本身就是判据**

旧判序是 `①controls → ② b==0 → ③delta`，于是 `a > 0 且 b == 0`
（六字面量形状数到了、生产正则**一条都没吃下**，即 `delta = a > 0`，是**最坏**的那一形）
被 ② 吞进了 `reconcile-empty`。后果不是漏报 —— 是**两个字段互相打脸**：
正文说「要么真没搜出去过」，而 `metrics` 里 `fa` 明明白白是 1。
更要命的是两者指向**完全不同的排查动作**（一个去查"为什么没搜"、一个去查正则），
而看告警的人只读正文。

新判序：`not controls_ok` → `delta` → `b == 0`。★ 关键不在"多一个分支"，
在于**把 `b==0` 挪到 `delta` 后面** —— 走到 `b == 0` 那一支时 `a` 必然是 0，
此时"真没搜出去"才是**唯一**的正确读法。

> ★★ **这就是判序即判据的实例**：同一组数（`fa`/`fb`/`fd`），
> 换一个判断顺序，出口的 `key` 和正文就完全不同。所以本条的测试不是"数算得对"，
> 是**钉住出口**（见 §18.21.5 的阴性对照）。

#### 18.21.2 #42：`StateStore(create=)` —— 把闸放在 `__init__`，不是放在 13 个调用点

复核 §18.19.3 那句「读不到给 `n/a`」时发现：`--db` / `--db-path` / `--log` 三个输入里，
`--log` 和 `--db-path` 读不到都会抛（天然安全），**只有 `--db` 那一路**是
`StateStore.__init__` 第一件事就 `mkdir(parents=True)` + `connect` + `executescript(SCHEMA)`
—— 库不存在时**就地建一个空的**。于是：

```
"库不在" → 不抛异常 → pack/movie 两张表全空 → pack_contexts() 返回 {}
        → 库里每一条 searchee 都算「无人认领」→ 报出一个巨大的假数 + 一条醒目告警
        → 还在**错位置**写下了一个库文件
```

★ **这是 ③ 自己立的规矩（「读不到给 n/a 不给 0」）在第三个输入上被破的那一格，
而且是往假阳性那头破。** 修法不是每个调用点各加一遍 `is_file()` ——
那正是上次漏掉的那种做法（13 个调用点，漏一个就回到原地）。闸放在 `__init__`：

* `create=False`（默认）：文件不在 → `raise FileNotFoundError`，**不建文件、不建父目录**；
* `create=True`：只有 `reseed-state.py init` 和测试夹具传。

热路径上的行为变更：错路径从「静默建空库 + 全量重搜」变成
「本批异常 → `consec_abort` 涨 → 到 3 批发告警」（`ABORT_ALERT_AFTER`）。

#### 18.21.3 #34：`n/a` 配「上次成功读数时刻」

`n/a` **只说明这一次**。TSV 里一个连续三天读不到的格子，和一个昨天还好、今天抖了一下的格子
**长得一模一样**，于是"判据长期失效"和"偶发抖动"事后完全分不开。

新增 `.reconcile.state`（原子替换，照 `.farm-check.state` 的先例）：
每一格记**最后一次真的读到数**是什么时候。八格里本轮 `n/a` 的，日报正文括号里跟一句
`（上次成功 X 前）`；**从未**读到过则写 `★ 从未成功读到过`。

★ 这两句话**指向完全不同的处置**：前者是抖动（等下一轮）、后者是判据从没通（去查路径）。
所以它们必须是两句不同的话 —— 实测第一版渲染成 `fa（0 秒前）`，
测试期望「上次成功」，判定是**代码的缺陷**（期望表达了意图），改代码、非改测试。

#### 18.21.4 #44：README 把三种「读不到」写清楚

`n/a`（这一路**没输入**）≠ `0`（**跑了、确实没有**）。
★ 特别写明**基线为 1 的两格**（`unclaimed` / `packs` 差集）：
报 `0` **不是**"判据没跑过"，是**跑了、且和基线 1 矛盾** ⇒ 去查那条真实记录还在不在
（农场的 `.xlsx` 被删了？还是 `--packs` 悄悄排进了 `mbf`？）。
没这一句，就会把「判据坏了」念成「今天没事」。

#### 18.21.5 阴性对照 + 验收

★ 阴性对照（#33 的判序）：把两行 `elif` **换回旧顺序** → `test_reconcile.py`
**恰好红 4 条**，且红的是 `key` 串台那两条（`reconcile-empty` vs `log-parse-miss`）——
证明这组断言**真的在守判序**，不是"新代码写了就一定过"。
（还原时用 `D:/tmp/dl-pre-negctl.bak` 字节比对，md5 `33f856aad9…` 两侧一致。）

| 项 | 结果 |
|---|---|
| 断言总数 | **13 脚本 / 452 条 / 0 失败**（`444 + test_remove_indexer 的 8 条 PASS`，格式不同） |
| 语法 | 三个改动文件过 `ast.parse(feature_version=(3,8))`（3.8 兼容）+ `py_compile` |
| 仓库污染 | 新增 `scripts/.reconcile.state` 已进 `.gitignore`；两个测试改向到临时目录才发得出去 |
| 部署 | ⏳ **待办**：`drive-loop.py` / `reseed-state.py` **是受管脚本**，须在**空闲窗口** `deploy.sh --apply`。★ 这一轮**是热路径的行为变更**（错 `--db` 从静默烧额度 → 响亮 abort 并把 `consec_abort` 推向告警阈值 3） |

#### 18.21.6 部署后追加：`packs-mismatch` 改成**只报变化**（2026-09-12 23:20）

> ★ 触发点是部署后的一句追问：「`packs-mismatch` 每天会响 —— 它不是『待办被点名』，
> 是**会变成噪音的判据**。」这个判断是对的，而且理由比"烦"更硬：
> **噪音的代价是真的出问题时没人看。**

`pack` 表 3 行（`dc-collection` / `frds-top250-2024` / `mbf`）而 `--packs` 只驱动前两个
→ 差集恒为 `{mbf}` → 旧代码 `if undriven or unreg:` **每天都发一条 alert**。

改法（判据本体一个字没动，动的是**出口的触发条件**）：

| 情形 | 旧 | 新 |
|---|---|---|
| 差集里出现**基线里没有**的 | 报警 | **报警** |
| 与基线一致（`mbf` 躺着） | 每天报 | **不报** |
| 缩回基线之内（修好了） | 每天报 | **不报**，且**采纳为新基线** |

* 基线存在 **`.reconcile.state` 的 `_packs_baseline`**（**不进代码** —— 写进代码就分不清
  「回到基线」和「判据死了」，§18.19 的教训）。
* **缩也采纳新基线**：否则删掉 `mbf` 那行之后基线还留着它，将来它再被加回来时
  「又冒出来了」就没人报 —— 而那才是真要抓的**回归**。
* 只在**本轮真的算了差集**时才写基线（`packs_baseline is not None`）：`--packs` 没给 /
  库读不到的那几轮必须保留旧基线，否则一次抖动就把现状抹成空，下一轮把老问题当新变化再喊一遍。
* ★ **不告警 ≠ 看不见**：日报正文照旧每天打印完整差集。

**阴性对照**：把 `if grew:` 退回 `if undriven or unreg:` → `test_reconcile.py`
**恰好红 3 条**，全是守新语义的（「与基线一致 → 不发 alert」两处 + 「正文说明了为什么不喊」）。
备份 `D:/tmp/dl-pre-negctl2.bak`，md5 `63771cba…` 两侧一致。

**也记一条部署流程的缺口**（同一轮发现，已写进 README）：
`deploy.sh` 末尾那句「下一步 `docker compose up -d --force-recreate cross-seed`」
**不是每次都适用**。本轮 4 个目的地里只有 `<compose>/drive-loop/**` 3 个是热路径
（NAS 宿主机上跑，**拷完即生效**）；第 4 个 `orchestrator/state.py` 是**构建上下文**副本，
而 `reseed-orchestrator` 是**一次性 CLI**（`ENTRYPOINT python -m orchestrator.main`，无 daemon）、
`cross-seed` 用官方镜像**不吃我们的文件** —— **要更新它得 `docker compose build`**，
`--force-recreate` 不带 `--build` 只是拿旧镜像重启，等于白掀一次容器。

---

## 19. 原理技术与风险须知（2026-09-12 夜）

> 这一节不记事件，记**两条原理** —— 它们各自都被正文里的事故反复撞到过，
> 但一直散在十几个小节里，从没有一处集中写下来：
>
> * **原理 A：系统不「识别」包，包是人「声明」出来的。** 漏一处声明 = 静默失败。
> * **原理 B：搜索压力的来源不是「频率」，是「分母每 14 天重生一次」。**
>
> ★ 两条的落点是同一个形状（与 §16.2.1 / §18.17 / §18.19 一致）：
> **瓶颈不在「系统不够聪明」，在「人漏了一步没有任何信号」。**
> 所以对策也不是「更聪明的识别」，是「能对账的反馈」。
>
> ⚠ 本节写进文档前**逐条回读代码核过**，并据此更正了两处流传的说法（§19.1.2 的两条 ★）。

### 19.1 没有「识别」，只有「声明」 —— 系统不会告诉你哪个目录是包

#### 19.1.1 系统只有两件**被动**能力，两件都不判断「这个目录是不是包」

| 能力 | 在哪 | 输入 | 输出 |
|---|---|---|---|
| **枚举** | `scan_pack()`（`state.py:375`）/ `find_searchee_paths()`（`state.py:362`） | 一个根 + 一个 depth | 根下的单片清单 |
| **归属** | `_resolve_searchee_to_pack()`（`state.py:1159`） | 一条 searchee 路径 | 它属于哪个包的哪个单片 |

枚举是「给我根我就展开」，归属是「给我路径我就认领」。
**它们都不回答「哪些目录该被当成根」。** 那个问题只在**人写下的配置**里有答案。

#### 19.1.2 声明点清单 —— 分成**两档**，因为「漏了会怎样」完全不同

**① 静默档：漏了没有任何人知道**（**只有这一档需要检测器**）

| 声明点 | 在哪 | 声明什么 | 漏了会怎样（两边看起来都正常） |
|---|---|---|---|
| **`FARM_SOURCES`** | NAS `.env` | 哪些目录是**源根** | `build-farm.sh --verify` 的期望集里没有它 → **连漂移都不报**（两边一致地当它不存在） |
| **`pack` 表一行** | `<compose>/drive-loop/hlink/state.db`（schema 见 `state.py:1113`） | 名字 + `roots` + `farm_root` + `max_depth` | `_resolve_searchee_to_pack()` 归不到它 → 农场里那些片**静默 continue**（只记进 `other_pack`） |
| **`--packs`** | `drive-loop.py` 的 **`PACKS_DEFAULT`**（当前 `dc-collection,frds-top250-2024`；`run.sh` **没传**） | 哪个包**会被驱动** | 状态机有它、农场有它，**drive-loop 不排它** —— 它的片子**永远不会被搜到** |
| **`--indexers`** | `run.sh` | 哪些**站**会被搜 | 站没进名单 → 对每部片子来说「那个站从没搜过」**根本不会被表达出来**（§18.11 的 HDtime） |
| **文档里的 init 配方** | §10.2 与本节的示例 | 包名 + `--match` 关键词 | 照旧配方重跑 → 挑 0 条根；或**多建一个包行**（`mbf` 与 `my-brilliant-friend-s01-s04` 是同一包的两个名字） |

**② 会响档：漏了立刻报错**（不用盯，但**别和 ① 混成一张表**）

| 声明点 | 在哪 | 漏了会怎样 |
|---|---|---|
| `DATA_DIRS` | NAS `.env` | cross-seed 扫不到东西 —— 农场空转，日志当场不对 |
| `LINK_DIR` | NAS `.env` | 硬链接建不出来，cross-seed 报错 |
| `TORZNAB_URLS` | NAS `.env` | 那个站压根不在容器里，`check_env_applied()` 下一批就喊 |

★★ **分档本身就是判据。** ② 漏了会自己喊；① 漏了**两边都正常** ——
所以「要不要给它配检测器」这个问题，答案完全由**落在哪一档**决定。
把两档并回一张"完整的声明点表"看起来更整齐，但抹掉的正是这条判据。

★ **与早先流传的说法不同，以本节为准（2026-09-12 回读代码核对）**：

1. **`--packs` 不在 NAS 的 `run.sh` 里** —— `run.sh` 只传 `--once --env --indexers --limit 50`，
   生效的是 `drive-loop.py` 里那个**默认值**。**`mbf` 就是这么被落下的**：它的 `pack` 表行在、
   农场里的片也在，但默认名单里没有它 → 它**永远不被驱动**，而它的 `UNMATCHED` 状态看起来
   完全正常。（"登记了却不在名单里"和"没登记"长得一模一样。）
2. ~~**`init --roots-from-env` 读的是 `DATA_DIRS`，不是 `FARM_SOURCES`**~~
   → **2026-09-12 已改**：现在**首选 `FARM_SOURCES`、缺席时退回 `DATA_DIRS`**，
   照的是 `build-farm.sh:132-155` 早就写好的同一种优先顺序。详见 §19.1.3。

★ **这一格里 `--packs` 那格故意不写行号。** 2026-09-12 的 `--db` 补丁（+27/−2）
就把本节原来的 `drive-loop.py:1487` 推成了 1510 —— 同一份文档里躺着一条
"声明点漂了、引用没跟着走"。**按符号引用（`PACKS_DEFAULT`），不按行号。**

★ 同一个「**手工名单漏改 = 静默**」的形状，在**站**那一侧还有一份：`run.sh` 的 `--indexers`。
2026-09-12 正是这么卡住的 —— HDtime 早在 Prowlarr(`id=1`) 与 `.env` 的 `TORZNAB_URLS` 里了，
但名单里没有它，**224 部 UNMATCHED 一部都没往新站重搜**，而 Prowlarr / cross-seed 那一侧
看起来一切正常（§18.11）。

#### 19.1.3 一个**看起来像识别、其实不是**的地方

```bash
python scripts/reseed-state.py init --roots-from-env .env --match "DouBan_IMDB"
```

这条命令**很像自动识别**，但它只是：从 `.env` 的**源清单**里遍历已有条目 →
挑出**路径里含人给的关键词**的那些。**关键词是人给的，系统不生成关键词。**
所以它是「从人给的清单里、按人给的关键词挑」，不是「识别出哪些是大包」——
**新包没进那份清单，`--match` 也永远挑不到它。**

★★ **而 v3 之后它一度连"挑"都做不到**：农场切换把 `DATA_DIRS` 从 49 条改成 **1 条**
（就是农场路径本身），而 `_roots_from_env()` **只读 `DATA_DIRS`** —— 于是
`--match "DouBan_IMDB"` 一条都匹配不到，直接报 `[!!] --roots-from-env 没挑到任何根`。
**声明点搬了家（源根清单从 `DATA_DIRS` 挪到了 `FARM_SOURCES`），工具没跟着搬。**

✅ **2026-09-12 已修 —— 而且是"照抄"，不是"重新决定"**：

- `build-farm.sh:132-155` **早就是**「优先 `FARM_SOURCES`，退回 `DATA_DIRS`」，
  连退回时的报错文案都写好了（`build-farm.sh:178-181`，运行期会打出来教人补 `FARM_SOURCES`）。
  所以这次不是新设计，是**补上同一个切换里漏改的那一个工具**。
- 诊断也因此要改口径：不是"`init` 错了**语义**"，是"**它漏在了 v3 那次切换之外**"
  —— 同一个切换里 `build-farm.sh` 跟着改了，`init` 没改。这是"声明点漂了"的第 4 个实例。
- 改动：`_roots_from_env()` 首选 `FARM_SOURCES`；缺席时退回 `DATA_DIRS`，
  并在说明里**明说这是退回来源**（不静默）。`--roots-from-env` 的 help 同步。

★ **验收判据是「与 `state.db` 里已存的 `roots` 逐条等价」，不是「能跑出根」**
—— 期望值必须指回一条**判据之外**的真实记录。`state.db` 的 `pack.roots` 是当初用
**老逻辑（`DATA_DIRS`）**登记时写下的，与 `FARM_SOURCES` 是两份独立来源。
2026-09-12 实跑（NAS 只读）：

| 包 | `--match` | 派生 | `state.db` 已存 | 逐条等价 |
|---|---|---|---:|---|
| `frds-top250-2024` | `DouBan_IMDB` | 1 | 1 | ✅ |
| `mbf` | `My.Brilliant.Friend` | 1 | 1 | ✅ |
| `dc-collection` | `DC相关剧集全系列大合集` | 47 | 47 | ✅ |

回归钉在 `tests/test_roots_from_env.py`（20 条），核心那格是**同一个 `.env`、
同一句 `--match`**：`FARM_SOURCES` 在 → 挑得到；只有 `DATA_DIRS` → 挑 0。
差异只可能来自取值来源，所以那一格量的就是"键换对了"这件事本身。
（★ 副产品：那份验收脚本自己第一版把 `pack.roots` 当逗号串拆，
而它在库里是 **JSON 数组** —— 三条全报"不一致"、数字和路径其实全对。
又一次"报红先怀疑断言"。）

#### 19.1.4 迁移到农场之后，「包」**只剩两个用途**

v3 之后 cross-seed 扫的是**农场那一条 `dataDirs`** —— 它不知道也不关心哪个片属于哪个包，
所以「包」在**搜索**这一侧**已经不重要了**。它活下来只为两件事：

| 用途 | 在哪 | 为什么需要「包」 |
|---|---|---|
| **webhook 发源路径** | `post_webhook()`（`state.py:2262`）发的是 `movie.path` = **源大包路径**（`state.py:1133`） | cross-seed 要的是**原路径**，不是农场路径 |
| **按包统计 / 轮流跑** | `report` / `trend` / `--packs` | 想要「FRDS 命中率 vs DC 命中率」这种分账 |

★ 也就是说：**「包」现在是个纯账本概念** —— 它决定**怎么记账**、**发什么 webhook**，
**不决定搜什么**（搜索是「农场 + cross-seed」的事）。

#### 19.1.5 「漏声明」现在有检测器了 —— 而且它的期望值指回一条真实记录

`unclaimed_searchees()`（§18.19.2）量的正是「**农场里有、但三包合起来都认不出**」的 searchee，
它恰好就是「漏了 `pack` 表那一处声明」的检测器：

- 新包的片进了农场 → cross-seed 扫到它 → 但三包都归不到 → **计数 +1，且点名路径**；
- 期望基线是 **1**（那条 `0观影清单chrlee整理` 里的 xlsx）；
- **数字涨到 2，就是有人新加了包但忘了登记。**
- **它不防止漏声明，但让漏声明不再静默。**

⚠ 覆盖面要说清：它只盯着 ① 里的 **`pack` 表**那一处。漏 `FARM_SOURCES` 与
**文档里的 init 配方**今天仍然没有检测器 —— 它们没有一条能自动对账的"另一侧"。
漏 `--packs` 的那一处，2026-09-12 起**有**了，见下节。

#### 19.1.6 第二个检测器：声明点〔`--packs`〕（2026-09-12）

`mbf` 那个教训的形状比它看起来更宽：

> **「登记了却不在名单里」和「压根没登记」，在任何输出上都一样。**

它在 unclaimed / report / trend 上**全绿** —— `pack` 表有行、`movie` 表有 4 行、
`farm_root` 也有。抓不到它**不是判据算错了**，是**没有一条判据的输入源包含
`--packs` 的实际值**（§18.18 那个形状：全绿，因为规则根本没参与）。

所以 `reconcile_watch()` 加了第四类，**两个方向各报一份**（方向不同、后果不同）：

| 差集 | 含义 | 后果 |
|---|---|---|
| `pack` 表 − `--packs` | 登记了却没被驱动 | **白登记**：它的片子永远不会被搜到，而且没人会报 |
| `--packs` − `pack` 表 | 在名单里但库里没这个包 | **更糟**：状态机看不见它的片子，整包会被判成 `other_pack` 而静默降级 |

- metrics：`packs_undriven` / `packs_unreg`；alert key `packs-mismatch`。
- **基线 1**（就是 `mbf`），与「无人认领」一个写法：非空即 alert，12h 冷却交给 notify。
  **基线不写进代码** —— 写进去就分不清「回到基线」和「判据死了」。
- 「没给 `--packs`」与「库读不到」**都给 `n/a`，不给 0**：调用方没传、和名单对得上，
  这两件事在 TSV 里必须分得开；而且**两种都不发 alert**（没跑到 ≠ 有信号）。
- 2026-09-12 实测（NAS 只读）：`pack` 表 **3 行**（`dc-collection` roots=47 /
  `frds-top250-2024` roots=1 / **`mbf` roots=1**）、`--packs` 默认值 2 个 → 差集 `{mbf}`。

★ 判据上了**不等于要改名单**。`--packs` 同时是**轮换集** —— `once_round()` 里
`(last_pack_idx + 1) % len(packs)`：从 2 个包变成 3 个，会把 `dc`/`frds` 各自的驱动频率
从 1/2 掉到 **1/3（−33%）**，换上来的是一个记录在案的 0 匹配包。
**那是产品决定，不是"消除一个代码默认值"。** 判据的职责只是让这个决定
**不再在没人看见的情况下生效**。

### 19.2 「一直在搜」不准确 —— 是**每 14 天一轮、永不停止**

#### 19.2.1 三处偏差

| 常见说法 | 实际 |
|---|---|
| 「一直在站点搜索」 | **每站 14 天一轮**，不是连续 —— `DEFAULT_CADENCE_DAYS = 14`（`state.py:95`） |
| 「小包越多，搜索越频繁」 | 频率固定，**变的是每轮总时长**；总量随未命中集合**线性增长** |
| 「压力 = 搜索频率」 | 压力 = **(未命中集合大小) × (频率)**，两个因子**都可能失控** |

★ `DEFAULT_CADENCE_DAYS` 的注释自己写的就是 **"永不停止的机器人流量"**（`state.py:90-95`）——
**它不是意外，是设计时就知道的代价。**

#### 19.2.2 当前那个「均摊」其实是**插队**的副产品

`todo()` 按 `TODO_PRIORITY`（`state.py:79`）排序 ——
`SKIPPED 0 → ERROR 1 → PENDING 2 → UNMATCHED 3` —— 而 `drive-loop` 每批 `--limit 50`。
于是 **UNMATCHED 永远排在队尾**：只要还有 SKIPPED / PENDING，它们就永远先被吃掉。

- 好处：**无意中**给了 UNMATCHED 一个"软性节流"；
- 坏处：**不可控、不可观测** —— 你不知道某个 UNMATCHED 到底多久没被搜过。

★★ 所以现在的「均摊」是个**副产品，不是设计**。它今天还能工作，是因为
SKIPPED / PENDING 还多；**等它们被清空，UNMATCHED 的压力会突然全部释放。**

#### 19.2.3 压力的真源：**分母在膨胀**

三项的性质完全不同：

| 项 | 会自己消失吗 | 是什么问题 |
|---|---|---|
| `PENDING` | ✅ 搜一轮就没了 | **一次性**，不是压力 |
| `SKIPPED` | ✅ 重搜一轮就没了 | **一次性**，是故障恢复 |
| 到期的 `UNMATCHED` | ❌ **每 14 天重生一次** | ★ **这才是永久压力** |

**所以真正的杠杆不是「均摊时间」，是「减少 UNMATCHED 这个集合」。**

#### 19.2.4 四条思路（按杠杆 / 成本 / 风险排）

```
        峰值问题            总量问题
      （同一时刻撞）      （分母膨胀）
思路 1  ── 抖动 ─────────▶ 削峰
思路 2  ────────── 自适应周期 ──▶ 降频（按站）
思路 3  ────────── EXHAUSTED ───▶ 缩分母
思路 4  ── 全局预算 ──────────▶ 硬上限兜底
```

| # | 思路 | 怎么做 | 代价 / 风险 |
|---|---|---|---|
| 1 | **抖动** | `next_due_at` 加 ±3 天（按片名哈希，确定性可复现） | 改一处；**只削峰、不降总量**；周期变得不精确 |
| 2 | **按站自适应周期** | 命中率低于阈值的站**拉长周期**（如 30 天） | 需要一个"多久调一次"的元周期；**站上后来有人发种会被延迟发现**（但那正是"账号安全 > 命中延迟"要的） |
| 3 | **`EXHAUSTED` 状态** | 全站搜过 N 轮、命中 0 → 不再搜；新站加入时自动解锁 | **会漏掉"站上后来有人发种"** —— 折中是 EXHAUSTED 后**低频重扫**（如 90 天） |
| 4 | **全局日预算** | "每天最多 N 次查询"，用完即停、次日重置 | 把"站点压力"从**站点反馈**变成**我们自己的判断** —— 需要知道合理值是多少 |

**★ 现状核对（2026-09-12 回读代码）** —— 四条各自的前置条件：

- **`EXHAUSTED` 不存在** —— `ALL_STAGES` 只有 6 个（`state.py:59`），没有这个状态；
- **思路 2 的数据已经在库里**：`trend()`（`state.py:1616`，按 **周 × 站**聚合）就是干这个的；
- **思路 4 的反馈来源已经在读**：`prowlarr_indexer_stats()`（`state.py:888`，
  字段 `numberOfQueries`，`state.py:939`）—— 可以直接拿来当外部反馈。

★★ **排序（杠杆 / 成本 / 风险三者合起来看）**：

| 优先 | 思路 | 为什么 |
|---|---|---|
| 1 | **思路 2（自适应周期）** | 直接打在最高优先（账号安全）上，数据已有，风险最低 |
| 2 | **思路 4（全局预算）** | 其他机制全失效时的兜底，且能接 Prowlarr 反馈 |
| 3 | **思路 3（EXHAUSTED）** | 杠杆最大，但**会漏后来的机会** —— 需要"低频重扫"折中 |
| 4 | **思路 1（抖动）** | 只削峰不降量，但便宜；可以顺手做 |

★ **四条里只有思路 2 是"直接减少分母"的**，其余三条是削峰 / 缩分母 / 兜底。

#### 19.2.5 收束

> 现在的「均摊」是「优先级插队」的副产品 —— 不可控、不可观测。
> 真正的压力不是频率，是 `UNMATCHED` 这个集合**每 14 天重生一次**。
> 所以杠杆不在「均摊时间」，在「减少分母」—— 而减少分母**唯一安全**的做法是
> 「**按站历史表现降频**」，不是「按片预测会不会命中」。

★★ 这一节的落点，和前几轮是**同一个形状**：
**不要加「更聪明的识别」，要加「能对账的反馈」。**
思路 2 的数据来源是 `trend()`（**已经在对账**），思路 4 的来源是 Prowlarr（**独立第二来源**）——
两条都满足「期望值能指回判据之外的真实记录」。
而「按片预测会不会命中」—— **它只有一个来源，就是模型自己。**

### 19.3 风险须知（把 A、B 两条原理下的风险列全）

| 风险 | 现状 | 谁在看着 |
|---|---|---|
| **漏声明 → 包静默不存在** | 3 个声明点**全是手工** | `unclaimed_searchees`（基线 1）**只覆盖第 2 处**；漏 `FARM_SOURCES` / 漏 `--packs` **无检测器** |
| **搜索总量没有上限** | `delay=30` 控速、退避检测**被动等** —— 但"一天总共能发多少"**没有闸门** | 无（思路 4 就是补这个） |
| **UNMATCHED 的"软性节流"会突然释放** | 靠 SKIPPED / PENDING 还多撑着 | 无 —— **不可观测**（这正是 §19.2.2 要记下来的原因） |
| **站上"后来才有人发种"的机会被漏掉** | 14 天周期是当前的兜底；做 `EXHAUSTED` 会**放大**这个损失 | 无 —— 只能靠周期本身 |
| **"按片预测命中"这条路** | **没有采用**，也不该采用 —— 它的判据只有模型自己一个来源 | 由本节 §19.2.5 这条原则挡着 |

---

## 20. 观测层「沉默 / 响铃」语义收敛（2026-09-12 深夜 → 09-13）

> **这一轮的产出不是「更聪明的判据」，是给 `packs-mismatch` 这个哨兵配上它的第二个来源**
> —— 让「沉默」和「响铃」各自有了确定含义，而不是继续靠人判断。
> 代码：`94ea500`（差集只报变化）；文档：`615b03d`（tests/README 数字对齐 466 + 拷副本验 `--db` 的方法）。

### 20.1 改了什么：差集从「报现状」改成「报变化」

**问题**：`mbf` 登记了却没被驱动（`packs_undriven` 基线 1）是**已接受**的现状。
原先每天在日报里喊一次 —— 喊的是**现状**，不是**新闻**。噪音的代价是真出问题时没人看。

**改法**（`scripts/drive-loop.py`，`reconcile_watch()` 内）：

| 位置 | 行为 |
|---|---|
| `:1036-1037` | `packs_baseline = cur` —— **无论告不告警都采纳** |
| `:1040` | 状态库里**没有**基线 → `★ 首次读数 → 已记为基线，**不告警**`（现状不是新闻） |
| `:1046-1052` | 有基线 → 只比「基线里没有、现在冒出来的」；有新增才 `emit("alert", "声明点对账：差集**变了**")` |
| `:1054` | 无新增 → `★ 与基线一致 —— 不告警（只报变化，不再每天喊）` |
| `:1013` | ★ 关键分寸：**缩回基线之内**也**不发**（修好了不必喊） |
| `:1122-1127` | 基线写进 `.reconcile.state` 的 `_packs_baseline`，**不进代码** |
| `:1087-1089` | 算不出时 `packs_baseline` 保持 `None` → `:1122` 的 `is not None` 跳过写入 —— **DB 报错不许把基线缩掉** |

★ **基线为什么不写进代码**：写死就等于「代码里的期望值」，
那样就**分不清「回到基线」和「判据死了」** —— 而后者正是本项目一路在打的空转。

★ **缩也采纳新基线**换来什么：将来把 `mbf` 排进 `--packs`，`undriven` 缩成 `[]` → 静默采纳；
此后**谁再把它从 `--packs` 去掉，会立刻以「新增 mbf」报出来**。这正是要抓的。

### 20.2 部署验证（2026-09-12 深夜）

NAS `drive-loop/scripts/drive-loop.py` md5 = `63771cbac15d0853c64da4f885c3ad79`，与本地**逐字节相同**；
`PACKS_BASELINE_KEY` / `_packs_norm` / `首次读数` / `与基线一致` / `packs_baseline is not None` 五处符号全在；
旧的 `if undriven or unreg:` 已消失。`check-deploy-drift.py` 两个方向都干净。

★ 这一条**不能用「漂移哨兵绿」代替** —— 哨兵只比**受管集合里的文件**在不在、一不一样；
而这里要断的判据是「**新的那几行代码**在不在 NAS 上」，所以是**按符号核**的。
（同一条形状的老账：§18.18.2 的「绿，但规则压根没参与匹配」。）

### 20.3 文案核实：三处成立，一处**过强**

用户写了一份「收尾确认」，核心断言是：

> 沉默 = 基线一致（跑了，无变化）；响铃 = 基线变化（跑了，且有事）。
> **两种读法以前都需要人判断，现在都不需要。**

回读代码后，**方向对、强度过一档**：

| 文案断言 | 代码事实 | 判定 |
|---|---|---|
| 响铃 = 基线**变化**（跑了，且有事） | `:1052` 的 `grew` 只在**真算了差集**且新增时才走 | ✓ 成立，可直接用 |
| 明天记下 `{undriven:["mbf"], unreg:[]}` | `:1036-1037` 的 `cur` 就是这个形状 | ✓ 成立 |
| 明天 `packs-mismatch` 不响 | 同上 | ✓ 成立 |
| **沉默 = 基线一致（跑了，无变化）** | 见 §20.3.1 | ★ **过强** |

#### 20.3.1 沉默不是一个含义，是**四个**

alert 沉默 ⟺ **没新增名字**。它有四个来源：

1. 与基线一致（跑了，真没事）
2. **缩回**基线之内（跑了，变好了 —— `:1013`）
3. `:1025` 状态库读不到 → 正文写「**没跑成**」，**但不发 alert**
4. `:1028` 调用方没给 `--packs` → 正文写「**跳过**」，**也不发 alert**

后两种正是**空转**的形状 —— 还是「哨兵绿 ≠ 有覆盖」。
所以「两种读法现在都不需要人判断」**不成立**：沉默仍要人判断，判据是
**日报正文那一行有没有值**。

★ 文案第四节自己写了「① 八格有值（不是 `n/a`）→ 新代码走到了」—— **那句是对的**，
而且正是沉默的判据；它和第一节的表格**打架**，**以第四节为准**。

★ **`n/a` 不是「没事」，是「没跑到」** —— README 的「对账八格怎么读」已写明；
本轮只是把它**扩展到 packs 两格**：那两格的 `n/a`（库读不到 / 没给 `--packs`）
同样**不等于**「差集是空的」。

#### 20.3.2 「`_packs_baseline` 有值」这条待查项，在日报里**看不到**

`:1077-1086` 打印的是**差集 + note**，**从不打印基线本身**；基线只进 `.reconcile.state`（`:1126`）。

**够用的替代证据**是首读那一轮正文里那句
`★ 首次读数 → 已记为基线，**不告警**` —— 它是**可见的**，说明基线机制走到了。
要**直接**看基线值，得走 SMB 读 `.reconcile.state`。

★ 决定**不加**一行把基线印出来：基线是**状态**不是**读数**，
印出来与「只报变化」的立意相反（`94ea500` 的整个理由就是不印现状）。

#### 20.3.3 「耦合被打断」只对一半

文案说「改基线」与「改 `PACKS_DEFAULT`」的耦合被打断了。**只有时间耦合断了**：

* **时间耦合**：✅ 断了 —— 现在可以「先加基线、慢慢决定 `mbf`」，不必现在拍板。
* **实质耦合**：❌ 没断 —— `mbf` 在不在差集里，取决于它进没进 `--packs`；
  而 **−33% 节奏代价**（2 包 → 3 包，dc/frds 的周期从 1/2 降到 1/3）
  是 `PACKS_DEFAULT` 的属性，**与基线无关**。
  基线只是让这个代价**不再每天提醒你**，**没让它变小**。

#### 20.3.4 一个低概率洞（已知，不修）

`store.packs()` 若**不抛异常**却返回**偏少的行**，基线会**静默缩**。
抛异常那条路是**堵住的**（`:1087` except → 保持 `None` → `:1122` 不写）。
SMB 下 SQLite 一般会抛，所以概率很低，**不动**。

### 20.4 明天（09-13）日报怎么读：三件事

| # | 看什么 | 期望 | 为什么 |
|---|---|---|---|
| 1 | `reconcile` 八格**有值**（不是 `n/a`） | 八格都有数 | **这是第 2、3 条的**前提** —— 八格 `n/a` 说明新代码压根没走到 |
| 2 | 正文里有 `★ 首次读数 → 已记为基线，不告警` | 出现一次 | 09-13 是 `_packs_baseline` 的**首读**（直接看值要去 `.reconcile.state`，见 §20.3.2） |
| 3 | `packs-mismatch` **不响** | 静默 | 沉默 = **没新增**（★ 不是「跑了没事」—— 见 §20.3.1） |

★ **如果第 3 条响了**：**先看正文点的是谁，再怀疑部署。**
—— 响铃意味着「基线里没有的名字冒出来了」，那就先照名字查；
只有名字看着**毫无道理**时才回头怀疑部署。

### 20.5 待办（与 README「当前状态与下一步」对账，不重复登记）

| # | 待办 | 首读 / 触发 | 状态 |
|---|---|---|---|
| 32 | 复核次日日报 TSV 里对账八格的**首读** | 09-13 当天**首批跑完**（约 11:12，以日志为准） | ⬜ 等 |
| 13 | `:3060` 的 `IYUU自动辅种` 条数是否**仍增长**（基线 100） | 09-14 凌晨 | ⬜ 等 |
| 40 | 决定 `mbf` 是否排进 `--packs` | 可**推迟**（基线已让它不天天喊） | ⬜ 未拍板 |
| 45 | `stats.aborted` 混名：站点退避超时被算成「批失败」 | — | ⬜ 未做 |
| — | 在 NAS 上删 `_cleanup-20260912/`（18 个文件）+ `__pycache__` | — | ⬜ 等（⚠ 别对 UNC 跑 `rm`） |
| — | `scan-secrets.py` 盲区（纯小写字母 + 连字符的长密钥） | — | ⬜ **建议不修**（理由见 §18.15） |
| — | `scripts/reseed-state.py` / `orchestrator/config.py` / `orchestrator/qbit_client.py` **工作区是 CRLF**（`.gitattributes` 是 `eol=lf`），而 `deploy.sh` 拷的是工作区副本 ⇒ NAS 也拿到 CRLF | — | ⬜ 已报**未修** |

### 20.6 这一轮的形状（和前面几轮同一个）

> **不要加「更聪明的识别」，要加「能对账的反馈」。**

`packs` 差集的**第二个来源**，就是**上一次读到的差集**。
它满足「期望值能指回判据之外的真实记录」—— 而「按片预测会不会命中」那种
**只有一个来源（模型自己）**的判据，§19.2.5 已经挡在外面了。

★ 唯一的**新**教训是分寸：**配第二个来源，代价是那句话不能再往大里说。**
「沉默 = 没新增」是**代码保证**的；「沉默 = 跑了且没事」**不是** ——
后者要**加一次正文读数**才成立。**把前者说成后者，就是又造了一个「看着绿」的判据。**

---

### 20.7 首读兑现 + 三条修正（2026-09-13）

首读成功，而且**基线按预测落盘**。首读本身又读出三个问题，本轮一并修掉。

#### 20.7.1 首读结果（`notify/log/2026-09-13.tsv`，00:38:28）

```
day=2026-09-13  iyuu=100  fa=76 fb=76 fd=0  fb_c_all=0 fb_c_farm=0
unclaimed=1  packs_undriven=1 packs_unreg=0
```

| 格 | 读数 | 记录的期望 | 判定 |
|---|---|---|---|
| `fa` / `fb` / `fd` | 76 / 76 / 0 | 不变式 `a == b`、`fd = 0` | ✓（★ 不是 1011，见 20.7.2） |
| `fb_c_all` | 0 | 0（b−c 全量口径） | ✓ |
| `fb_c_farm` | 0 | **0**（自检） | ✓（★ README 写的是 1，见 20.7.2） |
| `unclaimed` | 1 | 基线 1 | ✓ |
| `packs_undriven` / `packs_unreg` | 1 / 0 | 基线 1 / 0 | ✓ **首读** |
| `iyuu` | 100 | 基线 100 | ✓（09-14 才是首个有意义的读） |

**八格无一个 `n/a`** ⇒ 新代码走到了（第 1 条是第 2、3 条的前提）。

`_packs_baseline` 落盘，**与预测逐字相同**（SMB 只读 `.reconcile.state`）：

```json
"_packs_baseline": {"undriven": ["mbf"], "unreg": []}
```

`packs-mismatch` **没响** ✓。八格的「上次成功读数」时间戳都是
`2026-09-13 00:38:28`，与日报落盘时刻吻合。

#### 20.7.2 首读读出来的三条（都已修）

| # | 问题 | 证据（指回真实记录） | 修法 |
|---|---|---|---|
| ① | **`unclaimed=1` 会每天响** —— 而 `1` 是文档写明的**基线** | `drive-loop.py` 是 `if un:` → 立刻 alert；alert 有 **12h 冷却**（`notify.py:95`）⇒ 只要那目录还在，**每天 1~2 封、永远** | 同 `_packs_baseline`：只报**新增** |
| ② | **「站点退避超时」被念成「批失败」**（#45） | **同一条 TSV 里上下两行打架**：`ok=22 failed=0` 与「连续 3 批失败（索引器 HDtime 要等到 …）」。且它的正文把人指去查 `force-recreate` —— 对退避场景是**误导** | `DriveStats.aborted_kind` + 两个分开的计数 |
| ③ | README 两处**期望值指不回真实记录** | `fb_c_farm` 写 `1`，而 SUMMARY `:6309` 与当日实读**都是 0**；`fa == fb == 1011` 是**全天**数，而日报读的是**当日日志**（`drive-loop.py:828-834` 自己写了）⇒ 日报里永远是日初小数 | 改成 `0/0` 与不变式 `a == b` |

★ ① 和 ② 是**同一个形状**：**现状/良性被当成了新闻/故障**。
一个把已接受的现状每天喊（噪音 ⇒ 真出问题时没人看），
一个把良性收工喊成故障、还把排查方向指错。

#### 20.7.3 ★ 一个被**测试逼出来**的设计错误

`update_abort_streak` 的第一版写成「两个计数**互相清零**」。
测试立刻打脸：`真失败 ×2 → 夹 1 批良性 → 真失败不为 0` 那格返回 `(1, 0)`。

**这不是测试写窄了，是设计错了**：真故障（webhook 401）与站点退避会**交替**出现
—— 退避检查在发 webhook **之前**跑（`state.py` 的 `wait_out_backoff`），
所以一个持续 401 的故障完全可能被交替出现的退避批次反复冲回 0，
**永远到不了 3** ⇒ **那条告警存在的意义（无人值守下抓住持续故障）正好被抹掉。**

改成**互不干扰**：本次是哪一种就只涨哪一种，另一种**原样留着**；
**只有正常跑完才一起清零**。于是 `hard + backoff` = 「距上次正常跑完过了几批」，
谁也别想被掩盖。混着出现时标题补一句「共 N 批没跑成」，免得把 N 念成"连续"。

> ★ 这正是 `tests/README.md` 那条约定「**测试自己也是判据 —— 报红时先怀疑断言本身**」
> 的**反面**用法：这一次**先怀疑断言、再回来看代码，发现该怀疑的是代码**。
> 两次都要看，不能默认哪一边对。

#### 20.7.4 这一轮的落点

三条修正全部是**同一个动作**：把「名字」和「期望值」拉回到**能指得回真实记录**的位置。
没有一条是新判据 —— 判据算得都对，错的是**怎么念**。

★ 参照 §19.1.3 那张风险表：**「漏声明 → 包静默不存在」那一行现在多了一个检测器**
（`unclaimed` 从"每天喊"变成"只报新增"，于是它**重新变得有人看**）——
一个天天响的告警和一个没有的告警，在无人值守下**等价**。


---

## §20.8 告警正文也在教人做事 —— 查证命令自带脱敏（2026-09-13）

**一句话：告警正文里那条「照着敲」的命令，等于让程序替我们决定"这时候会把什么打到终端上"。**

### 20.8.1 现场

`drive-loop.py` 的 `check_indexers()` 里，`索引器拉不到名字`（`prowlarr#N`，
即 cross-seed 取不回 caps）那条 alert 的正文原本以这样一句结尾：

```
查证：docker inspect reseed-cross-seed | grep TORZNAB_URLS
```

而 `TORZNAB_URLS` 的**值是逗号分隔的一串 URL，每条各带一个 `apikey=`**，
那个 key 就是 **Prowlarr 的应用级 key**。

### 20.8.2 为什么这条比"不小心贴了一次"更糟

| 面 | 事实 |
|---|---|
| 那个 key 能干什么 | §7「凭据泄露面」记的：它能**完全控制 Prowlarr**，而 Prowlarr 里存着**所有 PT 站的 cookie** |
| 触发时机 | 索引器出问题时 —— **人最急着查的那一刻**，正是最可能照着敲、并且顺手把输出贴进聊天的时候 |
| 防护形状 | 靠的是"人记得先脱敏"。而这条链上**已经漏过一次**（§18.15：①值指纹那道网因为本地 `.env` 是存根而**几乎为空**，绿了也不代表安全）—— **覆盖薄的那道网，不能当防线用** |
| 受众 | 告警是**给未来的自己**看的。写正文的那一刻不觉得，读正文的那一刻（凌晨、出事中）不会想 |

★ 结论：**规矩必须写在命令里，不能写在"记得别看"里。**

### 20.8.3 改法

```diff
- 查证：docker inspect reseed-cross-seed | grep TORZNAB_URLS
+ 查证（★ 先脱敏再看，别把原样输出粘进聊天/命令行）：
+   docker inspect reseed-cross-seed | grep TORZNAB_URLS \
+     | sed -E 's/(apikey=)[^,&]+/\1<redacted>/g'
+ ★ 上面那行里每个 URL 都带一个 apikey=（Prowlarr 的 key），
+   原样 grep 出来就是明文凭据；sed 只是把它换成 <redacted>。
```

★ sed 咬的是 **`apikey=` 后面那段值**（`[^,&]+`：`&` 是 URL 内部的分隔符、
`,` 是 URL 之间的分隔符），**键名 `apikey=` 与 `/N/api` 都留着** ——
要判的是「容器里还剩哪个站」，这两样就够了，**那个值对判读毫无用处**。

> **Python 里写 sed 的 `\1` 要写 `\1`。** 否则 `"\1"` 会被解释成 `chr(1)`
> 这个八进制转义，命令里插进一个不可见控制字符 —— 而**看起来很对**。
> 这一条已用 `ast` 回读实际正文字符串确认过（不是"读源代码看着对"）。

### 20.8.4 钉回测试（`test_check_indexers.py` ⑤，42 → 45 条）

| 断言 | 防的是什么 |
|---|---|
| 正文含 `sed -E` 且含 `<redacted>` | 命令**自带**脱敏，不是"我们记得脱敏" |
| 正文含 `(apikey=)[^,&]+` | sed 咬的是**值**；写成 `s/apikey=.*//g` 那种会把键名也吃掉，判读就没依据了 |
| 正文含「别把原样输出」 | 光有命令拦不住手快 —— 命令给脱敏版、话还要说一句 |

### 20.8.5 落点

* 代码 `scripts/drive-loop.py`；测试 `tests/test_check_indexers.py`；
  文档 README「通知 / 告警」节新增一条 ⚠ 说明 + 「下一步」第 **9** 行。
* ✅ **已部署（2026-09-13 10:19，批次间隙）** —— 与 §20.7 那三条一起，
  `bash deploy.sh --apply` 写了 3 个文件（备份 `.deploy-backup/20260913-101900`），
  两侧 md5 **逐字节相同**；NAS 侧符号齐（`consec_backoff` / `consec-abort` /
  `_unclaimed_baseline` / `aborted_kind` / `sed -E`），3.8 语法闸过。
  ★ 运行期证据要等**下一批真的跑完**才落 —— 跳过路径（`batch_alive` 与闸门）是
  `return 0`、**一个字都不写**，所以「state 里出现 `consec_backoff`」只能在
  一批**跑完之后**看到，跳过的 tick 永远看不到（这一点一度被误判成"部署没生效"）。

---

## §20.9 `mbf` 排进 `--packs`（#40 已决，2026-09-13）

### 20.9.1 决定

**排进去。** `PACKS_DEFAULT`：

```
dc-collection,frds-top250-2024      →   dc-collection,mbf,frds-top250-2024
```

一处生效：`run.sh` **不传** `--packs`（已核），所以生产用的就是这个常量。
★ 本条改的是**值**，不是逻辑 —— 所以没有"新代码"可钉，真正要钉的是
**它依赖的那个既有行为**（见 20.9.6）。

### 20.9.2 代价的形状：−33% 是「几轮」，不是「永远」

`--packs` **同一份值**同时充当**三个**角色 —— 改它等于同时改三件事：

| 角色 | 在哪用 | 2 包 → 3 包 |
|---|---|---|
| 驱动名单 | `once_round()` 决定这轮跑哪个包 | `mbf` 终于会被搜 |
| 轮转集 | `idx = (last_pack_idx + 1) % len(packs)` | dc / frds 各从 **1/2 → 1/3（−33%）** |
| 声明点 | `reconcile_watch` 第四类对账 | `packs_undriven` 由 **1 → 0** |

★ 第三条是**免费**的副产品：`mbf` 本来就在 `pack` 表里登记着，排进名单后
`undriven` 缩成空 —— 而「缩回基线之内」是**静默采纳**的（§20.2），
所以这次**不会有告警**。**那是对的**：修好了不该喊。

★ 前两条的代价则**不是永久的**：`mbf` 只有 **4 条**（4 个季包），**一轮就搜完**。
搜完若仍 0 匹配 → 把它移出名单，dc/frds 的节奏**立刻**回到 1/2。
**代价是「几轮」，不是「永远」。**

### 20.9.3 为什么值得：不排它 = 一个不可观测的盲区

理由**不是**"`mbf` 可能命中" —— HDFans 上实测 4 个季包**全** `Found 0 torrents`（§12.3.1）。

理由是：**不排它，就永远不会知道 HDtime 能不能救它。**

| 状态 | 现在 | 排进去后 |
|---|---|---|
| `mbf` 在 HDFans 的匹配结果 | 已知 0 | 已知 0 |
| `mbf` 在 **HDtime** 的匹配结果 | **永远不会有读数** | **搜一轮就知道** |
| 代价 | 0 | dc/frds −33%（**几轮**） |

`HDtime` 是 **2026-09-12** 才进 `TORZNAB_URLS` 的站（§18.11.1），而 `mbf` 此前
只在 HDFans 上搜过。`UNMATCHED` 的规则是「**出现没搜过的索引器 → 自动解锁**」，
所以只要 `mbf` 被驱动一轮，它就会去 HDtime 搜 —— **那个读数此前拿不到。**

而"拿不到"这件事在现有判据上是**全绿**的：`pack` 表有行、`movie` 表有 4 行、
`farm_root` 也有 ⇒ unclaimed / report / trend **一个都不响**。
这正是 §19.1.2 那个**静默档**的形状：**登记了、农场里有、就是不被驱动，
两边看起来都正常。**

### 20.9.4 ★ 顺序：`mbf` 放中间**不是排版，是调度**

放在 **index 1** 是刻意的，两个理由：

1. **让已落盘的读数保持含义。** `.drive-loop.state` 的 `last_pack_idx` 存的是
   **下标不是名字** —— 当时它是 `0`，而 index 0 仍是 `dc-collection`（"dc 刚跑完"）
   ⇒ 含义不变。若把 `mbf` 放到最末，`last_pack_idx=0` 就变成"mbf 刚跑完"的意思，
   下一批会去跑 frds —— **读数被静默误解。**
2. **一批就拿到读数。** 排在 index 1 ⇒ 下一批就是 `mbf`。排在最末要等**两三批**
   （批间隔 45～180 分钟 ⇒ 晚 1.5～6 小时）。

★ **代价**（必须记住）：`once_round` 存的是**下标** ⇒ **改这个常量的顺序
= 偷偷改"下一批跑谁"**，而日志上看不出任何异常。要动顺序，先看 `last_pack_idx`。

### 20.9.5 退出条件（可执行）

**触发条件**：`mbf` 那一批跑完后，**HDtime 也被搜过、而 `mbf` 的 4 条仍没进 `SEEDING`**。

三个观测点，**全只读**：

1. `drive-loop.log` 该批的 `跑包 mbf（第 2/3 个）` 行 —— 先确认**真的轮到它**了。
2. cross-seed **`verbose.current.log`** 在**那一批的时间窗内**：
   `Querying HDtime at … with { t: … q: '…' }` 有几条 ——
   ① 证明 HDtime **真的被问了**；② **抄下原样的 `q`**，第 3 行兜底要手动搜时用它。
   ★ **顺序别写反**：匹配事件那行是 `Found <searchee> [hash…] on HDtime by MATCH` ——
   站名在 `on` 后面，`by` 后面跟的是**决策类型**。本文件里那条解析正则
   （`\[(?:webhook|inject)\] Found (.+?) \[([0-9a-f]{8})\.\.\.\] on (\S+) by (\w+) …`）
   的捕获组顺序就是证据。写成 `grep "by HDtime"` 会得到 **0 条**，**看着像结论，
   其实是 grep 写错了**。（本节初稿就写成了 `Found … by HDtime`，2026-09-13 改。）
   ★ 别指望这条能在「有货但只有单集」时给出非 0 —— 理由见下表下面的 ★★。
3. `state.db` 的 `movie` 表 `pack='mbf'` 那 4 行的 `stage` / `searched_indexers` /
   `indexer_seen`（后两列是 **JSON 文本**）—— **HDtime 出现在里面 = 搜过了**。

三处合起来才能分开下面三种情形 —— **单看 `matched_indexers` 是不够的**：

| `searched_indexers` 有 HDtime | `matched_indexers` 有 HDtime | 结论 |
|---|---|---|
| ❌ | — | 前提没成立（站压根没搜）⇒ 先查 `--indexers` / 容器，**不是**退出条件 |
| ✅ | ✅ | 保留 `mbf`，什么都不用改 |
| ✅ | ❌ | ★ **两种可能，日志分不开** ⇒ 必须**手动搜一次 HDtime** 才能定（见下） |

★★ **第 3 行是本节最容易被读错的一格（2026-09-13 补，初稿把它错拆成了两行）。**
初稿写的是「`on HDtime by` 条数 > 0 ⇒ HDtime 有货、是季包跳过单集」，**这条推不出来**：

- `Found N torrents for { path: … }` 这个块里**只有 `path` 一个字段，没有站名**
  （09-13 全天 75/75 块都是这个形状）—— 也就是说 info 级**根本没有 per-indexer 的结果数**。
- verbose 级有 per-indexer 的**请求**行（`[webhook] Querying HDtime at
  http://prowlarr:9696/1/api with { t: 'tvsearch', q: '…' }`），但**没有**对应的结果数。
- `cross-seed/config.js:58` 是 `includeSingleEpisodes: false` ⇒ 单集候选被**静默过滤**，
  全库 grep 不到任何「某候选因单集被跳过 + 站名」的行。

⇒ 「HDtime **完全没货**」和「HDtime **有货但只有单集**」在三处读数里**一模一样**
（`searched` 有、`matched` 空、`found` 0），而处置**相反**（前者移出 `--packs`，
后者不移出、另开待办）。**日志给不出这一格，只能手动搜。**

★ 手动搜的时候**别用自己拼的季包名** —— 用 verbose 里那行
`Querying HDtime … q: '…'` 的**原样 `q`**。那才是 cross-seed 真正发出去的问题；
口径不一样（`tvsearch` + 季号 vs 裸片名），答案没法比。

★ **走 Torznab，别去站点网页搜**（2026-09-13 补）。要判的是「**cross-seed 看到的
候选里有没有季包**」，所以复现的必须是 cross-seed 那条路：

| 搜法 | 发出去的 query | 回答的是哪个问题 |
|---|---|---|
| 抄 verbose 的 `q` 打 Torznab | 与 cross-seed **逐字节相同** | HDtime 对**这个** query 返回了什么 |
| 站点网页 / HTML 搜索 | 大概率是裸片名、无季号 | 「站上有没有这个片」—— **另一个问题** |

- 端点：`TORZNAB_URLS`（`.env`）里 path 段是 **`/1/api`** 的那条 —— `1` = HDtime，
  证据就是 verbose 那行 `Querying HDtime at http://prowlarr:9696/1/api`（同理
  `2` = HDFans、`3` = BTSCHOOL、`4` = NanyangPT）。**这是项目既有做法**
  （`config.js` 读的就是 `TORZNAB_URLS`），别另造一个。
- ★ 那个 URL 里**带 apikey** —— **不许回显**。要核对先脱敏：
  `sed -E 's/(apikey=)[^,&]+/\1<redacted>/g'`。
- 「去搜一下看看」这种动作最容易在**口径**上跑偏：它看着只是「手动复现一次」，
  但**你复现的是不是同一个 query**，决定了读出来的是不是同一个答案。

> **第 3 点用什么读法**：直读 UNC + `PRAGMA query_only=1`（§18.18.3）—— 这是项目
> 既有做法，`state.py:_open_csdb` 就是这么写的，实测 0.00s，读前读后 `ls` 旁边都
> **没有** `-wal` 冒出来。**别拷副本**：`state.db` 自己是 `journal_mode=delete`，
> 拷副本这回不吃亏；但同一个动作在 `cross-seed.db` 上吃过亏（§13.6 坑 2，WAL 里
> 未 checkpoint 的数据丢了，看着像「新站没注册」）—— **一种读法通吃两个库**，
> 比逐库判断少一条岔路。

**处置**：确认 0 匹配 ⇒ 把 `mbf` 从 `PACKS_DEFAULT` 移出。`undriven` 会自己涨回 1，
而且是**静默采纳**（不告警）—— 同 §20.2 的规矩：
**现状不是新闻，只有"又冒出来的"才是。**

### 20.9.6 钉回测试（`test_once_gate.py` ⑩，24 → 32 条）

改的是**值**，没有新逻辑可测 —— 但它押在一个**此前一条断言都没有**的行为上：
「`once_round` 按下标轮转」（`test_once_gate.py` 原有全部用例都传
`last_pack_idx: -1`，从来不问"下一批跑谁"）。所以补的 8 格钉的是**它**，
而不是"常量等于某个字符串"：

* 三包下 `last_pack_idx=0/1/2` **各自轮到谁**（`mbf` / `frds` / `dc`）+ 落盘的下标；
* ★ **反向控制**：**同一个 `last_pack_idx=0`**，只把 `mbf` 从中间挪到末尾 ⇒
  下一批从 `mbf` 变成 `frds`。**这一格就是「为什么必须放中间」的证据** ——
  没有它，20.9.4 那段推理就只是注释里的自述；
* 一格常量断言（`PACKS_DEFAULT` = dc / mbf / frds）当**决定记录** ——
  它**故意**会在有人改默认值时报红，逼他连这份记录一起改。

### 20.9.7 落点

* 代码 `scripts/drive-loop.py`：`PACKS_DEFAULT` + 常量上方那段**退出条件**；
  `reconcile_watch` docstring 里的"实测差集"；两处把 `mbf` 当**现存**例子的注释
  （它们现在是**历史**例子 —— 改成"这条判据为什么存在"的物证）。
* 测试 `tests/test_once_gate.py` ⑩（**+8 条**）。
* 文档 README：声明点表 `--packs` 行 / 看板「盯着漏声明的两个计数器」/
  「下一步」第 **7** 行 / 每日台账八格期望表 / MBF 静态快照行；`tests/README.md` 计数。
* ✅ **部署**：`drive-loop/scripts/drive-loop.py` 在 `deploy.sh` 白名单里（`run.sh` 也是，
  但本次**不动 `run.sh`** —— 它不传 `--packs`），2026-09-13 10:50 在批次间隙
  `--apply`（备份 `.deploy-backup/20260913-105013`），两侧 md5 `a768db08…` 一致。
  ⚠ 这条 md5 **早于下面 20.9.8 那次改动** —— 20.9.8 改的是同一个文件，
  已于 **10:55** 再 `--apply` 一次（备份 `.deploy-backup/20260913-105558`），
  两侧 md5 `8e86e0b2…` 一致、新分支在 NAS 上 grep 到。

### 20.9.8 ★ #40 自己踩出的一个洞：缩回时正文会**说假话**（2026-09-13）

**不是新功能，是 #40 让我撞见的一个既有缺陷。** 对账的「声明点〔`--packs`〕」那一格
只实现了**长出来**的分支，**没实现缩回去**的分支 —— 差集变小时会掉进 `else`，
打印「**★ 与基线一致** —— 不告警」。可它明明刚少了 `mbf`，**那句话是假的**。

**为什么这次非修不可：** #40 本身**就是一次缩回**（差集 `{mbf}` → 空）。
不改的话 09-14 凌晨的日报会打出「与基线一致」，而这句话同时对应两种**处置完全相反**的处境：

| 处境 | 日报长相（修前） | 该怎么办 |
|---|---|---|
| `mbf` 被排进 `--packs` 了（**预期**） | 「与基线一致」 | 什么都不用做 |
| 判据今天**没读到**（**故障**） | 「与基线一致」 | 去查为什么没读到 |

这正是本仓库反复栽的那一类：**文案断言一个没有依据的原因**（§18.17.3 同款）。
「一致」两个字把"预期内的收缩"和"判据失效"抹成了同一个样子。

**修法：** 给 `--packs` 补上和「无人认领」那条**对称**的 `gone` 分支 ——
缩回**不告警**（修好了不必喊，新基线立即采纳），但正文要**写出来**并**点名少了谁**
（`★ 比基线**少** —— 不告警（修好了不必喊；新基线已采纳，**再长回来会报**）`）。
判据不变量没动：**只报变化**，缩回仍不发 alert，回归仍必报（§⑥ 那格就是它）。

**为什么此前没被发现：** 两条基线判据（无人认领 / `--packs`）里，
只有无人认领写了缩回文案；`--packs` 是后加的（#36），照抄时漏了这一支。
`test_reconcile.py` §⑤ 当时也只断言了「不发 alert」和「两个方向都是 0」——
**从没检查过正文**，所以假话一路亮着绿灯。

**钉回测试**（§⑤ +3 条，117 → 120；全套 **515 条**）：
正文含「比基线**少**」、**点名**少了谁、且**不许**出现「与基线一致」。
★ 第三格是**反断言**（`... in note → False`）—— 它才是这条修复的靶心：
前两格只要求"多写了点什么"，只有这一格保证**假话被删掉了**。

⚠ **过程中的一次自伤**（记在这里因为它又中了一次老坑）：三条断言我最初写成了
`ck("…", "比基线**少**" in note, note)` —— 第三参传的是 `note` 而不是 `True`
（本文件 `ck` 签名是 `ck(label, got, want)`）。跑出来 `FAIL …: True`，
**那个 `: True` 恰好证明代码是对的**，红的是我的断言。
见 `tests/README.md` 的「测试自己也是判据 —— 报红时先怀疑断言本身」。

---

## §21 IYUU 辅种的保存目录从哪来 + 22 条旧根漏网（2026-09-13）

### 21.1 问的是什么

用户问：**IYUU 辅种时把目录指向哪里？**「监控文件夹 / 目录文件夹 / 种子文件夹」都用的默认值、
「创建多文件夹子目录」已勾选 —— **要不要手动配 IYUU 的文件目录？**
并给了四条猜测：① 容器路径映射不一致 ② IYUU 记的是搬迁前的路径 ③ qB 分类 save path 覆盖 ④ 孤本。

### 21.2 源码三跳 —— 辅种目录是「抄 qB 的」，不是「IYUU 自己造的」

三处都在 `\iSunker-DS423\docker_ssd\iyuuplus\iyuu`（只读）：

```php
// ① 取：把 qB 的种子列表编成 infohash → save_path 的字典
//    composer/bittorrent-client/src/Driver/qBittorrent/Client.php:726
$hashArray['hashString'] = array_column($res, "save_path", 'hash');

// ② 存：发现可辅种时，把这目录**快照**进库
//    app/admin/services/reseed/ReseedServices.php:322,379
$downloadDir = $hashDict[$infohash];              // 辅种目录
... 'directory' => $downloadDir, ...

// ③ 发：辅种时原样当 savepath 发给 qB
//    app/admin/services/reseed/ReseedDownloadServices.php:149
$contractsTorrent->savePath = $reseed->directory;
```

⇒ **辅种目录 = qB 里「同 infohash 那条已有种子」自己的 `save_path`，原样回灌。**
qB 报什么就用什么，所以它**天然落在 qB 的命名空间里**。

| 猜测 | 裁定 | 依据 |
|---|---|---|
| ① 容器路径映射不一致 | ★ **对辅种目录不成立**。IYUU 容器把宿主 `/volume1/video` 映成 `/video`，qB 容器映成 `/volume1/video` —— 但这个不一致**碰不到辅种目录**，因为它不是 IYUU 算出来的。它只对 `watch_path`/`torrent_path` 成立，而那两者**空转** | 21.2 + 21.3 |
| ② 记的是搬迁前的路径 | **成立**，且这正是 21.4 那 22 条的成因 —— `directory` 是**入库那一刻的快照** | 21.4 |
| ③ qB 分类 save path 覆盖 | ★ **已被代码防住**：`autoTMM='false'` 硬关（qB 只在自动种子管理开启时才拿分类保存路径去移动种子） | 21.3 |
| ④ 孤本 | **机制真实**，成因是 `root_folder` 与既有布局不一致；**本次核对是「对的」** | 21.3 + 21.5 |

### 21.3 唯一参与路径决策的字段：`root_folder`

```php
// ReseedDownloadServices.php:203-209（qB 分支）
$contractsTorrent->parameters['autoTMM'] = 'false'; // ★ 关闭自动种子管理
$contractsTorrent->parameters['paused']  = 'true';  // 添加任务校验后是否暂停
$contractsTorrent->parameters['root_folder'] = $clientModel->root_folder ? 'true' : 'false';
```

* 「**创建多文件夹子目录**」→ qB 的 `root_folder` 参数。**勾着是对的**，盘上核对：

  | 站点目录 | 内容形态 | `root_folder=true` |
  |---|---|---|
  | `…/reseed_singles/HDFans` | 276 个子**目录**（每个里 17 个文件） | ✅ 内容就在 `<save_path>/<名>/` 下 |
  | `…/reseed_singles/HDtime` | 30 个**单个 .mkv** 直接躺着 | ✅ 无害（单文件种不吃这个开关） |

* 那一格**必须对着盘核**，不能"勾上就行"：若某类既有种子的内容**直接躺在 save_path 下**，
  勾上它 qB 就会去 `<save_path>/<名>/` 找 → 校验失败 → **重下 → 多一份**。这就是 ④ 的成因。
* 另外三个框（`watch_path` / `save_path` / `torrent_path`）在 `sendDownloader()` 这条路上
  **一次都没被读** —— 辅种走的是 WebAPI 注入（`addTorrentByMetadata`），不是往监控目录丢 .torrent。
  且 `cn_folder`（IYUU 的目录映射表）**零行**、两个辅种任务的 `path_filter` 都是空串
  ⇒ 排除列表为空，**不需要手动配任何目录**。

### 21.4 22 条旧根漏网 —— 已收拢

`:3060` 902 条种子的 `save_path` 原本分两个根：

```
880 条  /volume1/video/download/reseed/reseed_singles/<站点名>   ← 新根
 22 条  /volume1/video/download/reseed_singles/<站点名>          ← 旧根（南洋 14 + HDFans 8）
```

生产 `.env` 的 `LINK_DIR` **早已是新根**，所以这 22 条**不是配置问题，是搬迁漏网**。

★ **判归属要看 tag，不能看 category**（§18.10 的老教训）：22 条**全是 IYUU 的**
（tag `IYUU自动辅种`，category 空）；我们那 599 条（tag `cross-seed`）一条不漏已在新根。
⇒ 所以收拢**必须带 `--all-tags`**（脚本默认只搬 tag `cross-seed` 的，那 22 条会被它挡下）。

过程照 §18.10 的老规矩：

```
python scripts/migrate-reseed-dirs.py --all-tags            # 只读预检：22 条，无一在途
python scripts/migrate-reseed-dirs.py --limit 1 --all-tags --apply   # 试跑：每组各 1 条 → 实际 2 条
python scripts/migrate-reseed-dirs.py --all-tags --apply    # 全量 20 条
```

结果：**902/902 全部落新根，0 条指旧根**。
状态分布 `stalledUP 706 / checkingDL 169 / error 24 / stalledDL 2 / pausedDL 1`。

> ★ **那 19 条 `error` 是搬之前就 error 的**，不是搬迁弄坏的 —— 试跑只对 **2 个 hash**
> 下过 `setLocation`，不可能把另外 19 条打成 error。它们只是**带着 error 状态搬到了新根**。
> error 总数 23 → 24（**+1，未归因**），如实记着。

### 21.5 旧根盘上还留着 52.42 GB / 10 条目 —— ★ 别对 UNC 跑 rm

| 站点 | 旧根条目 | 与新根**同名**（= 重复） | 只存在于旧根 |
|---|---:|---:|---:|
| HDFans | 3 | **2** | 1（`149.V字仇杀队…`，4.21 GB） |
| NanyangPT (南洋) | 6 | **6** | 0 |

现在**没有任何 qB 种子指向旧根** ⇒ 这是一批**无引用残留**。

> ⚠⚠ **不能据此断言它占 52 GB 实空间。** cross-seed 建的是**硬链接**，同名条目很可能
> 与新根那份**共享 inode**（额外占用 = 0）。SMB 读不到 inode，**这件事只能在 NAS 上判**：
> `du -sh` 对比 `du -sh --apparent-size`，或 `find <新根路径> -samefile <旧根路径>`。
> **别按"52 GB"这个数去删。** 且删只许在 NAS 上/DSM File Station 做（UNC 上 `rm` 是禁区）。
> `149.V字仇杀队…` 主 qB（opencd）也不引用它（opencd 的 `/downloads` = `/volume1/video/music`），
> 但删前照样先确认它是不是硬链接。

### 21.6 顺带查出一个潜伏雷：`qbittorrent-reseed` 的 `/downloads` **没挂载**

| qB | compose 里的挂载 | `Session\DefaultSavePath` | 结果 |
|---|---|---|---|
| `qbittorrent-opencd` (:3020) | `/volume1/video/music:/downloads` ✅ | `/downloads/` | 落在 `/volume1/video/music`，实的 |
| `qbittorrent-reseed` (:3060) | 只有 `/downloads/incomplete` ⚠ | `/downloads/` | ★ **`/downloads` 是容器可写层** |

`:3060` 上任何**不带 savepath** 的添加（手动拖进 WebUI、别的工具）都会落到**容器可写层**：
**宿主上看得见吗？看不见**；**重建即丢**；也不会与农场共享硬链接。

⇒ 现状无害（cross-seed 与 IYUU **都显式传 savepath**），但这是一颗**潜伏的**雷 ——
它的形态正是本项目反复栽的那一类：**失败的样子是「看起来正常」**。
要不要补挂 `/downloads`（或把 `DefaultSavePath` 改到已挂载的目录），列入待办。

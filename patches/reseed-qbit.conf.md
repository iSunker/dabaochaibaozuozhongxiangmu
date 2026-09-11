# Phase 0 — 修复 / 配置 `qbittorrent-reseed`(:3060)

这是**自动化前置**：只改 `:3060` 这个隔离实例的**配置**，不动任何数据。改完后 cross-seed / 编排器才能免密调它、外网端口才通。

> 配置文件路径（NAS 上）：
> `\\YOUR-NAS\docker_ssd\qbittorrent-reseed\config\qBittorrent\qBittorrent.conf`
> （容器内 `/config/qBittorrent/qBittorrent.conf`）

## 操作顺序（重要）

qBittorrent **退出时会用内存里的设置覆盖 conf**，所以必须：

1. **先停容器**：`docker stop qbittorrent-reseed`（在 :3060 自己的 compose 目录）。
2. **备份**：把 `qBittorrent.conf` 复制一份为 `qBittorrent.conf.bak`。
3. 按下面**合并/修改**各键（保留文件里其它键不动）。
4. **启动容器**：`docker start qbittorrent-reseed`。
5. 按末尾**验证**。

---

## 需要修改 / 新增的键

各键所在的 `[Section]` 以你现有 conf 为准（qB 会把同名键写在固定分节里）。**只改键值、按分节合并**，不要整体替换文件。

### 1) BT 端口统一为 56883（修复 compose 发布 56883 但实际监听 6881 的错配）

```ini
[BitTorrent]
Session\Port=56883

[Preferences]
Connection\PortRangeMin=56883
```

- compose 已发布 `56883:56883`（TCP+UDP）。确认**路由器把 56883 的 TCP 和 UDP 都转发**到 NAS。
- 若 conf 里有 `Session\UseRandomPort=true`，改为 `false`，否则端口会漂移。

### 2) 局域网免密（让 cross-seed / 编排器免密调 API，对齐你另一个 qB 实例）

```ini
[Preferences]
WebUI\AuthSubnetWhitelistEnabled=true
WebUI\AuthSubnetWhitelist=192.168.0.0/16, 127.0.0.1/32
WebUI\CSRFProtection=false
WebUI\ClickjackingProtection=false
WebUI\HostHeaderValidation=false
```

- 把 `192.168.0.0/16` 收窄成你实际网段更安全（如你实际网段 `192.168.1.0/24`）。
- 若你**不想开白名单**，就跳过本节，改走密码模式：在 `.env` 设 `QBIT_AUTH_MODE=password` 和 `QBIT_PASSWORD=<明文>`。

### 3) 关闭公网发现（保种只面向 PT，关 DHT/PeX/LSD）

```ini
[BitTorrent]
Session\DHTEnabled=false
Session\PeXEnabled=false
Session\LSDEnabled=false
```

### 4) 关队列、注入后自动开始

```ini
[BitTorrent]
Session\QueueingSystemEnabled=false
Session\AddTorrentPaused=false
```

- `QueueingSystemEnabled=false`：避免大量单种被排队卡住。
- `AddTorrentPaused=false`：cross-seed 注入后，qB 自动**校验→做种**，无需手动开始。
  （键名随版本可能是 `AddTorrentStopped`；以你 conf 里现有的那个为准，设为"不暂停"。）

### 5) 分类 `reseed-singles`

**无需手动建**：cross-seed 注入时会按 `linkCategory` 自动创建；编排器 `ensure_category` 也会兜底创建。
若想手动建：WebUI 左侧「分类」右键新增，或在停容器后编辑
`/config/qBittorrent/categories.json` 加入 `{"reseed-singles": {"save_path": ""}}`。

---

## 验证

启动容器后，在**同网段**任意机器：

```bash
# 1) 免密白名单生效：不带密码应直接返回版本号（如 v4.6.5）
curl http://<NAS_IP>:3060/api/v2/app/version

# 2) BT 端口对外可达（TCP）
nc -vz <NAS_IP> 56883
```

- `app/version` 直接返回版本 → 白名单 OK（走密码模式则此步会 403，属正常）。
- 也可用编排器一键自检：
  `docker compose run --rm reseed-orchestrator preflight`
  其中会打印 `[OK ] qBittorrent v4.6.5 @ http://<NAS_IP>:3060`。

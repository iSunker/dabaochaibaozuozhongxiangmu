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

### 21.5 旧根残留：★ 9/9 不是硬链接、**已删** —— 但**空间一分没回来**（2026-09-13）

> ★★ **收尾更正（2026-09-13 晚）：这个标题原先是「9/9 全是独立副本，删了真释放
> 48.20 GiB」。**删除本身成功了，但**那 48.20 GiB 没有出现**：
>
> | 读数 | 值 |
> |---|---|
> | 删前 `stat -c '%h %s %i %n'` | 9 个文件 **`%h` 全部 = 1**（都没有别的名字） |
> | `rm-staging.sh … --apply` | `OK：已删`，Windows 侧复核 `exists=False` |
> | `/volume1` 可用（删前 → 删后） | **31.91 → 31.76 GiB**（连量 4 次、值在动 ⇒ 不是 SMB 缓存） |
>
> ⇒ **「不是硬链接」和「删了能释放」是两件事。** 上面那串 inode 判据只证明了
> **不是真硬链接**；而 **CoW / reflink 共享 extent 时 inode 不同、`%h` 也是 1**，
> 行为却和硬链接一样 —— 正是 `rm-staging.sh` 头部自己警告过的那句
> （「Btrfs 快照 / CoW 共享 extent 与真硬链接**行为一样却看不出**」）。
> 当时以为那句后面的 `stat` 能兜住它，**没兜住**。
>
> ⇒ 所以「可释放 48.20 GiB」**从一开始就不该当成结论**。删除这个动作本身仍然是对的
> （0 条种子引用旧根，删掉不会弄坏任何做种），**只是它换不来空间**。
>
> ★ **下次的判据要换成能看见 extent 的**：`sudo btrfs filesystem du -s <目录>`，
> 看 **Exclusive** 那一列 —— 接近 0 ⇒ 数据块与别处共享、删了不释放；≈ Total ⇒ 才真占着。
> 另一条同样造成「删了不释放」的是 **Btrfs 快照**；而 **SMB 侧看不见**
> `@snapshots` 这类 `@` 前缀系统目录 ⇒ **"没有快照"不能靠 `ls` 排除**
> （本项目反复栽的那类假阴性：命令成功了、结论是空的）。

| 站点 | 旧根条目 | 与新根**同名**（= 重复） | 只存在于旧根 |
|---|---:|---:|---:|
| HDFans | 3 | **2** | 1（`149.V字仇杀队…`，4.21 GB） |
| NanyangPT (南洋) | 6 | **6** | 0 |

（上表按**条目**数是 10；按**文件**数是 **9 个** —— 差的那一个是目录。）

**没有任何 qB 种子指向旧根** ⇒ 一批**无引用残留**。
判据：`:3060` 的 `/api/v2/torrents/info` 全量 **927** 条里，`save_path` 落在旧根的
**0** 条、落在新根的 **927** 条（合计 10667.52 GiB）⇒ **删旧根不会弄坏 `:3060` 上任何一个种子**。

> ★★ **原先这里写着「SMB 读不到 inode，这件事只能在 NAS 上判」—— 那句话是错的，已推翻。**
> 实测：`GetFileInformationByHandle` 的 **`nFileIndexHigh/Low`（fid）就是服务端 inode**，
> **跨 SMB 准确透传**，Windows 侧 `ctypes` 直调即可（`hlink-info.py` 这类小工具）。
> ⚠ **但 `nNumberOfLinks` 在这台 NAS 上完全不可信**：拿一对**已知**硬链接做对照
> （农场条目 vs 它的源 —— `cp -al` 建的，**定义上同 inode**），**两边都报 `nlink=1`**。
> ⇒ 此前「nlink=1 ⇒ 不是硬链接」的推断**必须整套废弃**，判据一律改用 **fid**。
> （稳定性也验过：同一路径连读两次 fid 完全一致。）
>
> ⚠ 顺带一条**方法论**：原先那个「只能在 NAS 上判」的结论，是**从"读不到"推出来的**。
> 而"读不到"当时并没有做过对照 —— 一旦补上对照（农场 vs 源），判据立刻可用。

**判据**：旧根每个文件，三路比 fid（旧根 vs 新根同名 vs 清单里的源包）：

| 判定 | 个数 | 体积 | 含义 |
|---|---:|---:|---|
| 硬链接→源包 / 硬链接→新根 | 0 | 0 | 删了不省空间（但删了也安全） |
| ★ **独立副本** | **8** | **45 667.7 MiB（44.60 GiB）** | **删了真省** |
| 清单里没有条目，但同样**不同 inode** | 1 | 3.69 GiB | `Klaus.2019…AREY.mkv` |

九条合计 **49 360.0 MiB（48.20 GiB）**。

> ★★ **2026-09-13 当天更正：「可释放 44.60 GiB」这个口径读窄了，真值应是 48.20 GiB。**
> 44.60 是**只把上表第二行**算进去得到的，Klaus 那 3.69 GiB 被**保守排除**——
> 排除的理由是「**清单里没有条目**」（拿不到源包做三方比 fid），**不是**「它是硬链接」。
> 可上表**第三行自己写的**就是「**同样不同 inode**」⇒ 按**同一条判据**，它也该算进可释放。
> ⇒ **正确口径是 9/9 全释放 = 49 360.0 MiB = 48.2031 GiB。**
>
> ⚠ **`scripts/rm-staging.sh` 头部当时把它写成了「剩下 1 个是**硬链接**，删了不释放」——
> 那句话与上表**直接矛盾**，是错的**（同一轮已修；脚本注释，行为不变）。
> 教训不是「数算错了」，而是**把「没查到」写成了「查到了没有」**：
> 保守排除的前提是「保守」，措辞一旦变成断言，它就成了一条**假事实**，
> 而且会被下游（`rm-staging.sh` 的头部、任务 #51 的标题）**照抄**。
>
> ★ **独立复测（2026-09-13，`os.stat().st_ino` 直读，与上面的 ctypes/fid 是两条不同 API）**：
> 旧根 9 个文件与新根**同名文件**逐个比，**9/9 全不同 inode**；再扫 `reseed/` 全树
> **5663** 个文件，这 9 个 inode **只出现在旧根**；又扫 `video/download` 全树
> （`movies/` 优先，**已跑完：除旧根外 94 813 个文件 / 742s**）**0 命中**。⇒ 与 48.20 GiB 一致。
>
> ⚠ **但仍不能算「已定案」**：上面几轮都是 **SMB 侧**的读数，而 SMB 之外
> （Btrfs 快照 / CoW 共享 extent）它与真硬链接**行为完全一样却看不出**。
> **删前在 NAS 上跑一次才是判据**（`%h == 1` ⇒ 实释放）：
> ```sh
> stat -c '%h %s %i %n' /volume1/video/download/reseed_singles/HDFans/* \
>                            "/volume1/video/download/reseed_singles/NanyangPT (南洋)"/*
> ```
> ★ **必须单行**（上次就是 DSM 脚本框把多行 `\` 续行折成一行才失败的），
> 且**输出别落 `/volume1`**（它 0 可用，写了也是空文件 —— 见 §21.5 上方那条教训）。
★ **新根那些同名文件本来就指向源包的硬链接**（它们的 fid 与清单里的源文件**逐字节相同**）
—— 这正是 v3 方案的设计，**不额外占空间**。所以删旧根**不会**让新根的单片失效。

**删法**：只能在 NAS 上做；**别对 UNC 跑 `rm`**（SMB 上删是不走回收站的真删，且路径解析在 Windows 侧）。
两个 qB 实例**都实测过、都不引用旧根**（2026-09-13）：

| qB | 读数 | 判据 |
|---|---|---|
| `:3060` reseed | 927 条 → 旧根 **0** 条 | 读 API `torrents/info` 的 `save_path` 前缀 |
| `:3020` opencd | 1234 条 → 旧根 **0** 条 | ★ API 回 **403**（白名单不覆盖本机 IP），**改读它自己的 `BT_backup/*.fastresume`**（bencode 里的 `save_path`），判据与读 API 时**同一个** |

★ 第 2 行此前一直是**推理**（「opencd 的 `/downloads` = `/volume1/video/music`，所以不搭界」）
—— 推理不是读数，2026-09-13 才补成实测。opencd 的 1234 条全是 `/downloads`
（容器内路径），1212 条直接落 `/downloads`、22 条落 `/downloads/incomplete`。

> ✅ **`rm-staging.sh` 现在接这条路径了（2026-09-13）**：闸 ③ 加了第三类，判据是
> **完整路径字面量** `/volume1/video/download/reseed_singles` —— **不是 basename**
> （按 basename 放行 `reseed_singles` 会把任何同名目录一起放行）。
> 命令：`sh <compose>/rm-staging.sh /volume1/video/download/reseed_singles --apply`
> ★ 注意是 **`/volume1/...`**（数据卷），不是 compose 所在的 `/volume2/...` —— 两者本来就不在同一个卷上。
> ★ **删完请把闸 ③ 里那条 case 撤掉再 deploy 一次**：它是残余清理，不是常态，
>   留着等于在生产上永久留一个「能删视频目录」的口子。

### 21.6 顺带查出一个潜伏雷：`qbittorrent-reseed` 的 `/downloads` **没挂载**

| qB | compose 里的挂载 | `Session\DefaultSavePath` | 结果 |
|---|---|---|---|
| `qbittorrent-opencd` (:3020) | `/volume1/video/music:/downloads` ✅ | `/downloads/` | 落在 `/volume1/video/music`，实的 |
| `qbittorrent-reseed` (:3060) | 只有 `/downloads/incomplete` ⚠ | `/downloads/` | ★ **`/downloads` 是容器可写层** |

`:3060` 上任何**不带 savepath** 的添加（手动拖进 WebUI、别的工具）都会落到**容器可写层**：
**宿主上看得见吗？看不见**；**重建即丢**；也不会与农场共享硬链接。

⇒ 现状无害（cross-seed 与 IYUU **都显式传 savepath**），但这是一颗**潜伏的**雷 ——
它的形态正是本项目反复栽的那一类：**失败的样子是「看起来正常」**。

#### 21.6.1 ✅ 已修（2026-09-13）—— 走 qB API 改 `save_path`，**没有**动 conf、**没有**改 compose

```python
POST http://192.168.0.7:3060/api/v2/app/setPreferences
     json={"save_path": "/volume1/video/download/temp"}
```

| 项 | 值 |
|---|---|
| 改前 | `save_path=/downloads` → `Session\DefaultSavePath=/downloads/` |
| 改后 | `save_path=/volume1/video/download/temp` ✅ 已落盘 |
| 落点选择的依据 | 只有 `/volume1/video` 是 **1:1 挂载**的媒体卷；而**硬链接不能跨卷**（§9 那条），要让"意外落进来的种子"还有机会与农场共享硬链接，落点就**只能**在这棵树下 |

★ **雷的直接证据不是推理，是 qB 自己报的数**：改前 `free_space_on_disk = 302.14 GiB`
—— 那是 **volume2（docker_ssd，容器可写层所在卷）**，不是 volume1；改后读数是 **0**
（= volume1 的真实剩余）。⇒ **这个数本身就是验收判据**：它从 302 GiB 掉到 0，
说明保存路径**真的**从可写层挪到了媒体卷上。比 `du` 容器可写层省事，也不用开 shell。

**为什么走 API 而不是改 conf**：`qBittorrent.conf` 由 qB **自己拥有** —— 它退出/改设置时会
**用内存里的值整份重写**（`patches/reseed-qbit.conf.md` 开头那条"必须先停容器"就是为此）。
从外面改这个文件是**和 qB 抢方向盘**；而 API 是 qB 自己写，天然一致、且可逆（同一个调用改回去）。
代价：**需要 qB 在跑**（它本来就在跑），**零停机**。

**为什么不是"补挂 `/downloads`"**（备忘录里给的另一条路）：那要改的 compose **不在本仓库里**
（在 `/volume2/docker_ssd/qbittorrent-reseed/`，哨兵扫不到），改完还得 `--force-recreate`
—— 在一台**正常跑批**的生产机上做容器重建，收益却只是"让一个兜底路径可用"。
而且会把容器内 `/downloads` 与宿主某处绑成**非同名**，正好与本项目**刻意维持的
"宿主路径 == 容器路径"**（`/volume1/video:/volume1/video` 那条）相抵触。

**★ 2026-09-13 晚实测 —— 把上面那段从「推理」补成「读数」**：

| 读数 | 值 |
|---|---|
| `:3060` 种子总数 / `save_path` 前缀分布 | **932 / 932 条全在 `/volume1/video` 下**；`/downloads` 下 **0 条** |
| 活着的默认值 | `save_path=/volume1/video/download/temp`（§21.6.1 的修复仍在） |
| `free_space_on_disk` | **0.00 GiB**（= volume1，仍是那个验收判据） |
| `temp_path` | `/downloads/incomplete`（compose 把它挂在 **volume2**，见 §21.4） |
| 那份 compose 回读 | `/volume2/docker_ssd/qbittorrent-reseed/docker-compose.yml` —— 它**已经 1:1 挂着** `/volume1/video:/volume1/video` |

⇒ 于是「补挂 `/downloads`」的性质更清楚了：它**不是补一条缺失的路，而是给一棵
已经可达的树再起一个名字**（别名）。而且这次实测还排掉了一个**反向风险**：
补挂**不会**把谁的下载藏起来 —— 因为 `/downloads` 下**一条种子都没有**
（若有，那一挂就是"文件全丢"：宿主机目录会遮住容器可写层里的数据）。

若哪天**真**要挂，唯一自洽的一格是 `/volume1/video/download/temp:/downloads`
—— 就是现在的默认保存路径本身：不新增落点、不引入新布局、爆炸半径最小。
**但那是化妆，不是修东西。**

**残留（无害，可选清理）**：conf 里还留着 `Downloads\SavePath=/downloads/`。
它是个**死键** —— 判据是 qB 刚才**整份重写**了 conf、却**没有**更新它（活键一定会被写）。
真要清，得**停容器后**手工改；**不清也不影响**，运行时的取值由 `Session\DefaultSavePath` 定。

**副作用（是好事）**：qB 现在按 **volume1 的真实水位**判断空间了。
以前它以为有 302 GiB 可写，现在是 0 —— 满载时它会**拒绝/限制**添加，而不是**悄悄**写到 SSD 上。

---

### 21.7 邮件风暴根因：★ 已判明 —— 不是「发信坏了」，是**重试没有上界**（2026-09-13）

**现象**：12:40 那条「站点退避中：HDtime」在邮箱里每 5 分钟来一封。

#### 读数（全部只读，没有一条是推理）

| 读数 | 值 | 说明 |
|---|---|---|
| 告警文件的 `ts` | `2026-09-13 12:40:44` | 由事件文件名前缀与文件内容两处印证 |
| `notify/spool/` 目录 mtime | `13:10:02` | ★ 目录 mtime 只在**增删条目**时变 ⇒ 它**在 spool 里躺到 13:10:02** |
| 换算 | **约 30 分钟 / 约 6 趟 5 分钟任务** | **≈ 6 封** —— 与"每 N 分钟重发"吻合 |
| `notify/log/2026-09-13.tsv` | mtime `11:35:02`，最后一行 `11:34:28 mbf` | 12:40 那两条**一条都没进日志** |
| `/volume1` 剩余 | **0.00 GiB** | 走 SMB `statvfs` **从 Windows 侧**量到；同一条路量 `docker_ssd` 是 **301.90 GiB** ⇒ 读法有效、能区分卷 |

#### 机械结构（`scripts/notify-spool.sh` 的 `do_drain`）

原代码里，告警分支是这么排的：

```sh
if send_mail "$SUBJECT_PREFIX 告警：$ti" "$tmp"; then
  say "  [已发] $ti"        # ← ★ 夹在中间：send_mail 成功之后，log_event/mv 之前
  n_sent=$((n_sent + 1))
  log_event "$f"
  mv -f "$f" "$ARCHIVE/$(basename "$f")"
```

脚本是 `set -eu`，而 `say` 就是 `echo "$@"`。于是：

```
send_mail 成功（信真的发出去了）
  → say 失败（stdout 写不进去 → echo 返回非零 → set -e）
  → 脚本当场退出
  → log_event 没跑、mv 没跑
  ⇒ 信已发出、日志没记、文件还在 spool
  ⇒ 5 分钟后那趟任务读到同一条文件，**原样再发一遍**
```

> ★ **2026-09-13 晚补**：上面那条链的**后半段（"`say` 为什么会失败"）仍然只是假设**。
> 当晚回读了任务定义，发现**那条任务压根没有重定向**（见文末「遗留」①′），
> 所以"stdout 写不进去"**没有直接证据**，只是与那个满卷最相容的解释。
> **前半段（"`say` 失败会让整趟半途退出 ⇒ 信发了、没记账、下轮再发"）是实验钉死的**，
> 且**与 `say` 具体因何失败无关** —— 这也是为什么不需要先判明就能修。

**★ 这条路径是用实验钉死的，不是读代码读出来的。** 把 `do_drain` 的控制流照抄成最小
复现（`say` 正常 / `say` 失败两组），结果：

| | 对照（`say` 正常） | `say` 失败 |
|---|---|---|
| 退出码 | 0 | **1** |
| archive | 两块都进 | **空** |
| 日志 | 两条都记 | **空** |
| spool | 空 | **两块都留着** |

★ 复现脚本**自己先错了两次**（函数参数错位 → 生成的文件不带 `.txt` → glob 匹配 0 个 →
两次都是"空跑"），所以现在这版加了 `LIST != 2 就判实验作废` 的自检。
**一个不做自检的复现，失败时会说"没问题"。**

#### 根因：**重试没有上界**，而不是「发信坏了」

上面那个触发条件只是**扣扳机的那一下**。真正让它变成"风暴"的是设计：

原代码的失败分支写的是「保留在 spool（下轮重试）」，而**「下轮」= 5 分钟后**。
也就是说 —— **任何**一条"信发出去了、但归档/记账没做完"的告警都会无限重发，
**不管那次失败是什么原因**。触发它的可以是：

- `say` 撞上 0 可用空间（**前提条件当天实测成立**：`/volume1` 剩 0.00 GiB）；
- **`send_mail` 假阴性**（信其实到了、CLI 却返回非零）；
- `log_event` / `mv` 自身失败。

三者**表现完全一样、修复完全一样**，所以不做区分也能修。要把它们分开需要看那趟
DSM 任务在风暴窗口里每趟的**退出码** —— 见文末「遗留」③。

#### 修复（三处，都在 `do_drain`，意图是同一条：**把「发一次」和「记一次」绑死**）

1. **`say` / `warn` 末尾加 `|| true`** —— 打印进度绝不该决定一封信的生死。
   （注释里写明了这是风暴的直接产物，不是洁癖。）
2. **告警分支改成「先 `log_event` + `mv`，最后才 `say`」** —— `say` 现在自身不致命了，
   但**顺序**是第二道闸：就算打印全坏，也绝不能让"已经发出去的信"丢掉记账。
3. **加 `MAX_SEND_TRIES`（默认 3）** —— 连续失败到上限就
   **归档 + 记一条 `[未确认]` 告警**（`kind=alert`，于是进日报的「告警明细」），
   而不是永远重试。另有「已放弃」分支：**放弃过的绝不再发**，只补归档。

配套：`notify.conf.example` 加了 `MAX_SEND_TRIES`（并写明**别调大到没边**）、
`--selftest` 报 `.tries` 计数、日报的「通知链路」多报一行「其中 M 条已经在重试」。
`.tries` 计数放在事件文件旁边（`<事件>.tries`）—— **不改事件文件本身**（它由
Windows 侧 `notify.py` 写），且计数丢了只是"多给一次机会"，**失效方向是安全的**。
漂移哨兵不用改：`notify/spool/` 是**目录前缀**规则，`.tries` 落进"已知生产独有"。

#### 回归测试：`tests/test_notify_drain.py`（28 条）

这个脚本**此前一个测试都没有** —— 而它的失败方式是「**安静地多发几封邮件**」。

★★ 关键的一条：**同一份测试跑在修复前的代码上**，精确复现了风暴：

```
✗ 即便 stdout 关掉，退出码仍是 0   ← 实际 1（半途退出）
✗ ★ 仍然归档了   ← []              ← 文件没归档
✗ ★ 仍然记了账                     ← 日志没有
✗ ★ 封顶后再跑 2 趟，一封都没多发   ← 又发了 2 封    ← 无限重发
```

修复后 28/28 全过。触发条件在测试里用 `sh -c 'exec 1>&-; …'` 关闭 fd 1 复现
（`echo` 得到 EBADF，与那天 ENOSPC 的后果等价）。

#### ★ 遗留：触发条件仍未定死（需要 NAS 侧**一个**读数）

修复对三种成因都成立，所以**不影响已做的改动**。2026-09-13 晚取到两个读数，
收掉一条、否掉我自己写错的一条、换出新的那一条：

**①′ 任务定义 —— 已取到，结论是「否掉了我原先的假设」。**
`sudo /usr/syno/bin/synoschedtask --get` 回读，id=10 `reseed-notify-drain`：

```
Command: [sh /volume2/docker_ssd/prowlarr_cross-seed_autohardlink/notify/notify-spool.sh]
Type: daily    Run time: [0]:[0]    Repeat every [5] min (s) until [23]:[55]
```

**没有任何重定向。** 所以本文档上一版写的「任务把 stdout 重定向到 `/volume1`」
是**错的** —— 那是我拿假设当结论写下的（把「猜的」写成了「是的」，和 §21.5
那个「把『没查到』写成『查到了没有』」是**同一个错的两面**）。`README.md` 里
同一句已一并更正。

于是「`say` 那天为什么失败」**仍然没有直接证据**：任务 stdout 的去处由
**DSM 自己**决定，不在我们脚本里，从 Windows 侧也看不见。

**② 主题行 —— 已取到，符合预期。**
风暴邮件主题就是 `[reseed] 告警：站点退避中：HDtime`，即**本通道**，
不是 DSM 的「发送运行详情」（那条是 **288 封/天**，量级差 40 倍）。
⇒ 风暴确实由 `do_drain` 发出，本文档讲的就是它。

**③ ★ 仍然要的那一个读数：风暴窗口里 id=10 每趟的退出码。**
这是唯一能把三种触发二选一的东西：

- **退出码非 0** ⇒ 脚本**半途退出**（`say` 写 stdout 失败 + `set -e` 带走整趟），
  前提条件就是那个满卷；
- **一路 `Success`** ⇒ **`send_mail` 假阴性**（脚本正常走完，只是信没出去，
  `continue` 后仍退出 0）。

取法：DSM 任务计划 → 那条任务 → 「运行结果」；或
`sudo find /var/log -iname '*sched*'` 后翻它。

> ★ 同一份回读里的**旁证（不是结论）**：id=9 `reseed-drive-loop` 最近一次是
> `Error(120)`，而 id=10 在修复部署后（14:05）是 `Success`。120 = CPython
> 「退出时刷 std 流失败」，与 `drive-loop/run.sh` 里早就记下的那条一致。
> **本条不足以说它俩同源** —— `run.sh` 那句「目前没有能把它们分开的判据。
> 别硬凑一个原因。」**仍然有效，本文档不动它**。但它给出一个**可证伪的预言**：
> 把 `/volume1` 腾空（#51）之后，若 120 跟着消失，两者同源；若照样 120，
> 则无关。

> ★ **另一个必须说明的读数**：`archive/` 里那对 12:40 文件**同时具备**
> 「已归档」与「没有日志行」两个特征。2026-09-13 晚把这条线重新量了一遍：
>
> - 旧版 `do_drain` 里 `mv … "$ARCHIVE/"` **只有 3 处**，全在 `do_drain` 内，
>   且每处都**紧跟**在 `log_event` 之后（`git show de3c2a4:scripts/notify-spool.sh`）；
> - 今天的日志 TSV 共 8 行，**没有空字段行**（`log_event` 只在四个 `field_of`
>   全取空时才会"记了但看不见"，这种情况不存在）；
> - 归档区今天进账 6 组：00:38×4 / 04:12 / 05:07 / 08:16 / 11:34 **全在 TSV 里**，
>   **只有 12:40 那对不在**；
> - 仓库里**没有任何 Python** 会挪 `archive/`。
>
> ⇒ **13:10:02 那次 spool→archive 不是 `do_drain`、也不是本仓库任何一条路干的**
> （`send_mail` 失败时是 `continue`、不归档；`say` 失败时整趟退出、也不归档）。
> 而归档目录 mtime = `13:10:02`、两个文件 mtime 停在 `12:40:43/44`
> （`mv` 保留 mtime，所以它俩是 12:40 写的、13:10 被挪走的）。
>
> ★ 更值得注意的一点：**风暴正好停在这个文件离开 spool 的那一刻** ——
> 12:40:44 → 13:10:02 是 29 分 18 秒 ≈ 6 趟 5 分钟任务，与"重发约 6 次"吻合。
> 也就是说**风暴不是被修好的，是那个文件不再待在 spool 里了**。
> 这正是"重试无上界"的签名：**它自己不终止**。
>
> 这条要问用户确认（是手动挪的吗？还是当时手工跑过脚本？）—— 它不影响根因
> （根因是那 30 分钟里被重发的 6 封），但**不能把它当成"脚本自己归档的"写进结论**。

---


# tests/ —— 离线自测（不联网、不碰 NAS、不碰真库）

给仓库代码钉回归的断言集。**全部离线**：SQLite 都是在 `tempfile.mkdtemp()` 里现造的
合成数据，网络请求打桩，凭据一律用假 key。

## 怎么跑

```bash
python tests/test_backoff.py        # 任一 cwd 都行
```

路径按 `__file__` 解析（不是 cwd），所以从哪儿跑都一样。
每个脚本自己打印 `ok` / `FAIL`：**全过退出码 0，有失败退出码 1**，可以直接接 CI。

2026-09-13 实测：**13 个脚本、504 条断言、0 失败**。

★ 这个总数**别手算**。测试脚本的"通过"有三种行形（`  ok  ` 前缀、
`[n] 标签 : PASS` 后缀、`scan-secrets` 自带的一套），任何**单一** grep 都会漏掉
其中一类 —— 实测：只数 `  ok  ` 会得到 374，把 `test_remove_indexer.py` 的 8 条
整个漏掉。要重数就跑这一行（判定"全过"看**退出码**，不看数出来的条数）：

```bash
tot=0; for f in tests/test_*.py; do out=$(python "$f" 2>&1); rc=$?; \
  n=$(printf '%s\n' "$out" | grep -cE '^  ok  |^ FAIL |: PASS|: FAIL'); \
  echo "$(basename $f) n=$n rc=$rc"; tot=$((tot+n)); done; echo "TOTAL=$tot"
```

## 各测什么

| 文件 | 断言 | 钉住什么 |
|---|---:|---|
| `test_backoff.py` | 39 | 退避检测 —— **55 秒的短窗口发生在批次中途也必须记一笔**（复刻 2026-09-12 现场）；残值不误记、禁用的索引器不挡路。★ 另钉 **`aborted_kind` 的两个计数各走各的**（2026-09-13）：「站点退避超时」是**良性**、**一点失败都不涨**（复刻 09-13 那条 `failed=0` 与「连续 3 批失败」同批的 TSV）、真故障的 key 是 `consec-abort` / 良性是 `consec-backoff`、**两者互不清零**（写成"互相清零"会让交替出现的退避把真故障永远压在 3 以下 ⇒ 告警等于没有）、只有**正常跑完**才一起清零、认不出种类时**按真失败算**（宁可吵不可静默）、混着出现时标题补「共 N 批没跑成」 |
| `test_check_indexers.py` | 45 | 索引器自检 `check_indexers()` —— **两份分开维护的名单对不上时会静默错记**（2026-09-12 真栽过：HDtime 早就在 Prowlarr 和 `.env` 里，`--indexers` 却没有它，224 部 UNMATCHED 一部都没往新站重搜）。钉：`_norm_indexer_name` 的括号归一（不归一就**每批误报**）、三分支（`missing`/`extra`/`unnamed`）各自的 key 与 metrics、**修法文案不许再出现「两处都要改」**（电脑端已退役，`--indexers` 只有 `run.sh` 一处）、以及自检自己**绝不能拖垮跑批**（没 `--db-path` 静默跳过、读库炸了要吞）。★ 另钉 **unnamed 分支的查证命令必须自带脱敏**（2026-09-13）：命令里要有 `sed -E` 与 `<redacted>`、sed 咬的是 `apikey` 的**值**（`(apikey=)[^,&]+`，只换值、留键名与 `/N/api`）、且正文要明说**别把原样输出粘进聊天/命令行** |
| `test_farm_root.py` | 18 | v3 农场路径归包：单根 / 多根嵌套 + 季层 / 老包**不**认领农场路径 |
| `test_next_sleep.py` | 17 | `next_sleep()` 三档退避分级（45 / 90 / 120 分钟）+ 单调性，外加老分支没被碰坏 |
| `test_once_gate.py` | 24 | `--once` 闸门接线：算出的间隔**真的落盘、真的挡住下一批**；跳过文案说的是不是真原因；没待搜时农场巡检照样跑 |
| `test_orchestrator_state.py` | 29 | `state` 子命令：**库不存在时绝不许把文件建出来**；且必须在读 `config.yml` **之前**分派（配置坏了它还得能用） |
| `test_quota_trend.py` | 96 | 额度台账（A 来源滚动 24h + B 来源 Prowlarr + 两者互校）+ 趋势（按周按站）+ 农场巡检判断（**argv 里绝不出现 `--prune`**） |
| `test_reconcile.py` | 117 | 观测对账三条判据：**合取 vs 单字面量**（`] Found ` 会吃到 `Found 0 torrents for {`，实测 2231 vs 靶心 1011）、**两口径不是同一个数**（三包共用一个 `farm_root` → 生产口径 other_pack 865/146/1011 而非 0）、**全场无人认领**（1888 条里恰好 1 条，且必须点名路径）。外加接线层：`reconcile_watch` **绝不抛**、读不到给 `n/a` 不给 0、正文里带口径名与留证行，★ **三个出口各钉一条 alert**（`reconcile-controls` 判据没走通 / `reconcile-empty` 空转 / `log-parse-miss` 形状对正则没吃下），★ **状态库不在时不许把空库建出来**（连父目录都不能建），以及 ★ **第四类「声明点〔--packs〕」**：两个方向的差集、各自点名、对得上时两个 0 且不发 alert、没给 `--packs` 与库读不到都给 `n/a`。★ 差集改成**只报变化**：首读记基线不告警、与基线一致不许再喊（核心那条是**同一个差集连读两次，第二次必须静默**）、缩回基线内静默采纳且**再长回来必须报**、`n/a` 轮**不许抹掉旧基线**。★★ **无人认领也走同一套**（2026-09-13）：首读只记基线**不响**（那 1 条是已接受的现状，配上 12h 冷却就是每天响两次、永远）、**同一个集合连读两次第二次必须静默**、出现**新的**一条才发且正文只点**新增**那条（metrics 把总数与新增数分开）、缩回静默但**正文写出来**（否则"清掉了"和"判据没读到"分不开）、**缩回后再长回来必须报** |
| `test_roots_from_env.py` | 25 | `init --roots-from-env` 的**取值来源**：首选 `FARM_SOURCES`、缺席时退回 `DATA_DIRS`（★ 与 `build-farm.sh:132-155` 同一种优先顺序）。核心那格是**同一个 `.env`、同一句 `--match`**：`FARM_SOURCES` 在 → 挑得到，只有 `DATA_DIRS` → 挑 0 —— 差异只可能来自取值来源，所以它量的就是"键换对了"本身。另钉：退回时**必须说出来**（不静默）、两个键都没有时报错要点名两个键、`--match` 挑不中时文案点名**实际用的那个键** |
| `test_remove_indexer.py` | 8 | `add-torznab-indexer.py --remove` 的**字节保真**与安全闸（合成样本 + 假 key，绝不碰生产 `.env`） |
| `test_scan_secrets.py` | 25 | 推前凭据扫描器 `scripts/scan-secrets.py`：阳性拦得住（值指纹 + 形状两条路）、阴性不误报；**形状层必须参与退出码**、**只拦「本次新引入」**、三类假阳性（读变量 / 英文短语 / 同字符重复）必须被规则认出来 |
| `test_sync_empty_sets.py` | 31 | `sync_movie` 整行覆盖写 + 四个空集的后果：**SEEDING 塌成 PENDING 是降级不是删行**（连 `searched_indexers` 都被抹掉），而 `indexer_seen` 是**合并**保留的 → `next_retry_at` 被推到未来一整个周期 = **额度悄悄烧掉一轮**；端到端钉「一条计数器 / 两条静默通道」——searchee 落到**别的包**（`other_pack`）与**认不出的名字**（`unresolved`）后果一模一样，**只有后者会喊** |
| `test_iyuu_watch.py` | 30 | IYUU 辅种条数（§18.8 的唯一生产级证伪点）：**重构没改行为**（`qbit_torrents` 的 URL 仍是老那个字面量 —— 它在每 15 分钟的热路径上）、中文 tag 必须被百分号编码（URL 要纯 ASCII）、`iyuu_watch` **三种情形都不许抛**、以及 **数字真的进了 `metrics`**（TSV 只记 metrics 不记正文，"看着发了其实没留痕"肉眼看不出来） |

## 写测试时踩过的坑（别再踩）

- ★ **控制台/管道是 GBK 时 `⑪`(U+246A) 编不出去**，脚本会在打印到那一节时中断 ——
  而**已经过的断言看着全是"ok"**，极易误判成"代码坏了"。
  所以每个脚本开头都强制 `sys.stdout.reconfigure(encoding="utf-8")`。
  **加新的节编号时不要越过 `⑩`**（`①`..`⑩` 在 GBK 里，`⑪` 不在）。
- ★ **测试自己也是判据 —— 报红时先怀疑断言本身。** 真栽过两次：
  `test_remove_indexer.py` 第 4 项拿 `api\n\r\n` 当针（那行实际以 `apikey=FAKE` 结尾，
  针在哪儿都匹配不到），以及 `check-indexer-timestamps.py` 用严格 `==` 比
  `NanyangPT` 与 `NanyangPT (南洋)`。**两次的表现都和真 bug 一模一样。**
  第三次是同一天：`test_sync_empty_sets.py` §② 只期望一条流水，实际
  `PENDING → SEEDING` 那次**也是变档**、也留了一条 —— 代码是对的，断言写窄了。
- ★ **"生产会写文件"的路径，测试里必须改向到临时目录** —— `STATE_FILE` /
  `FARM_CHECK_FILE` / `DAILY_FILE` / spool。否则跑一次测试就往**仓库**里留产物：
  `test_once_gate.py` §⑤ 就是这么把 `.farm-check.state` 写进 `scripts/` 过的（已清掉）。
- ★ **闸门自己的对照集，必须先过闸门自己。** `test_scan_secrets.py` 里那些"凭据样本"
  一律由**变量拼出来**（`"-".join([...])`、`"y" * 16`），源码里不留字面量 ——
  否则推前扫描会扫到这个测试文件本身，"防凭据入库"的工具先给自己报红。
  同理，沙箱是 `tempfile.mkdtemp()`（**仓库之外**）：曾经把探针写成
  `<repo>/.ctl-secret-probe.txt`（随即删掉），那是错的 —— 往待推目录里塞一个
  凭据形状的文件，本身就是这件事要防的。
- ★ **别用"按某个标记切源码再 exec 前半段"的取巧办法**（`src.split("hits = []")[0]`）
  去拿被测文件里的正则/函数：切点一改就**静默失效**，切出来的前半段照样能跑，
  只是少了后半个文件的定义。用 `importlib` 把**真的那份**载进来（吞掉 `SystemExit`、
  重定向 `stdout`）。
- ★ **`importlib` 载进来的模块，必须先 `sys.modules[name] = mod` 再 `exec_module`。**
  否则被测文件里只要有 **`@dataclass`** 就炸，而且报的是一个看着毫不相干的
  `AttributeError: 'NoneType' object has no attribute '__dict__'` ——
  因为 `dataclasses` 要 `sys.modules.get(cls.__module__).__dict__` 去找注解的命名空间，
  而 `spec_from_file_location` **不会**替你登记。
  **同一段 `_load` 代码对两个文件行为不同，原因却不在它们身上**：
  `drive-loop.py` 没有 dataclass 所以先跑通了，一度让人以为只有 `state.py` 有问题。

## 约定

- 这些脚本**不在 `deploy.sh` 的白名单里**，也**不进容器** —— 是 Windows 侧手动诊断用的，
  跟 `check-indexer-timestamps.py` / `migrate-reseed-dirs.py` 同一档。
- 涉及凭据的工具只用**合成样本**（`test_remove_indexer.py` 里全是 `FAKEKEY…`）。
- 别把测试产物写进仓库；需要落盘就 `tempfile.mkdtemp()`。
- ★ **「`--db` 路径在真库上跑得通吗」用拷副本验，不碰生产库。** 方法：
  把生产 `state.db` 拷到 `D:/tmp/<随便>`（**拷前先确认旁边没有 `-wal`/`-shm`** ——
  有就说明库正被打开着，此时拷出来是残的），然后本地跑
  `python scripts/drive-loop.py --once --dry-run --db D:/tmp/<...>/state.db ...`。
  阳性对照：给一个**不存在**的路径，必须报 `FileNotFoundError` 且**不建文件**。
  **产物用完即删** —— 它是**那次**验证的证据，源库会变，留着就有被当成
  「上次验过」的风险。（NAS 的 ssh 没开，本机不能在 NAS 上跑，所以只能这么验。）

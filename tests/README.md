# tests/ —— 离线自测（不联网、不碰 NAS、不碰真库）

给仓库代码钉回归的断言集。**全部离线**：SQLite 都是在 `tempfile.mkdtemp()` 里现造的
合成数据，网络请求打桩，凭据一律用假 key。

## 怎么跑

```bash
python tests/test_backoff.py        # 任一 cwd 都行
```

路径按 `__file__` 解析（不是 cwd），所以从哪儿跑都一样。
每个脚本自己打印 `ok` / `FAIL`：**全过退出码 0，有失败退出码 1**，可以直接接 CI。

2026-09-12 实测：**12 个脚本、373 条断言、0 失败**。

## 各测什么

| 文件 | 断言 | 钉住什么 |
|---|---:|---|
| `test_backoff.py` | 17 | 退避检测 —— **55 秒的短窗口发生在批次中途也必须记一笔**（复刻 2026-09-12 现场）；残值不误记、禁用的索引器不挡路 |
| `test_check_indexers.py` | 42 | 索引器自检 `check_indexers()` —— **两份分开维护的名单对不上时会静默错记**（2026-09-12 真栽过：HDtime 早就在 Prowlarr 和 `.env` 里，`--indexers` 却没有它，224 部 UNMATCHED 一部都没往新站重搜）。钉：`_norm_indexer_name` 的括号归一（不归一就**每批误报**）、三分支（`missing`/`extra`/`unnamed`）各自的 key 与 metrics、**修法文案不许再出现「两处都要改」**（电脑端已退役，`--indexers` 只有 `run.sh` 一处）、以及自检自己**绝不能拖垮跑批**（没 `--db-path` 静默跳过、读库炸了要吞） |
| `test_farm_root.py` | 18 | v3 农场路径归包：单根 / 多根嵌套 + 季层 / 老包**不**认领农场路径 |
| `test_next_sleep.py` | 17 | `next_sleep()` 三档退避分级（45 / 90 / 120 分钟）+ 单调性，外加老分支没被碰坏 |
| `test_once_gate.py` | 24 | `--once` 闸门接线：算出的间隔**真的落盘、真的挡住下一批**；跳过文案说的是不是真原因；没待搜时农场巡检照样跑 |
| `test_orchestrator_state.py` | 24 | `state` 子命令：**库不存在时绝不许把文件建出来**；且必须在读 `config.yml` **之前**分派（配置坏了它还得能用） |
| `test_quota_trend.py` | 96 | 额度台账（A 来源滚动 24h + B 来源 Prowlarr + 两者互校）+ 趋势（按周按站）+ 农场巡检判断（**argv 里绝不出现 `--prune`**） |
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

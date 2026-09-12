# tests/ —— 离线自测（不联网、不碰 NAS、不碰真库）

给仓库代码钉回归的断言集。**全部离线**：SQLite 都是在 `tempfile.mkdtemp()` 里现造的
合成数据，网络请求打桩，凭据一律用假 key。

## 怎么跑

```bash
python tests/test_backoff.py        # 任一 cwd 都行
```

路径按 `__file__` 解析（不是 cwd），所以从哪儿跑都一样。
每个脚本自己打印 `ok` / `FAIL`：**全过退出码 0，有失败退出码 1**，可以直接接 CI。

2026-09-12 实测：**7 个脚本、204 条断言、0 失败**。

## 各测什么

| 文件 | 断言 | 钉住什么 |
|---|---:|---|
| `test_backoff.py` | 17 | 退避检测 —— **55 秒的短窗口发生在批次中途也必须记一笔**（复刻 2026-09-12 现场）；残值不误记、禁用的索引器不挡路 |
| `test_farm_root.py` | 18 | v3 农场路径归包：单根 / 多根嵌套 + 季层 / 老包**不**认领农场路径 |
| `test_next_sleep.py` | 17 | `next_sleep()` 三档退避分级（45 / 90 / 120 分钟）+ 单调性，外加老分支没被碰坏 |
| `test_once_gate.py` | 24 | `--once` 闸门接线：算出的间隔**真的落盘、真的挡住下一批**；跳过文案说的是不是真原因；没待搜时农场巡检照样跑 |
| `test_orchestrator_state.py` | 24 | `state` 子命令：**库不存在时绝不许把文件建出来**；且必须在读 `config.yml` **之前**分派（配置坏了它还得能用） |
| `test_quota_trend.py` | 96 | 额度台账（A 来源滚动 24h + B 来源 Prowlarr + 两者互校）+ 趋势（按周按站）+ 农场巡检判断（**argv 里绝不出现 `--prune`**） |
| `test_remove_indexer.py` | 8 | `add-torznab-indexer.py --remove` 的**字节保真**与安全闸（合成样本 + 假 key，绝不碰生产 `.env`） |

## 写测试时踩过的坑（别再踩）

- ★ **控制台/管道是 GBK 时 `⑪`(U+246A) 编不出去**，脚本会在打印到那一节时中断 ——
  而**已经过的断言看着全是"ok"**，极易误判成"代码坏了"。
  所以每个脚本开头都强制 `sys.stdout.reconfigure(encoding="utf-8")`。
  **加新的节编号时不要越过 `⑩`**（`①`..`⑩` 在 GBK 里，`⑪` 不在）。
- ★ **测试自己也是判据 —— 报红时先怀疑断言本身。** 真栽过两次：
  `test_remove_indexer.py` 第 4 项拿 `api\n\r\n` 当针（那行实际以 `apikey=FAKE` 结尾，
  针在哪儿都匹配不到），以及 `check-indexer-timestamps.py` 用严格 `==` 比
  `NanyangPT` 与 `NanyangPT (南洋)`。**两次的表现都和真 bug 一模一样。**
- ★ **"生产会写文件"的路径，测试里必须改向到临时目录** —— `STATE_FILE` /
  `FARM_CHECK_FILE` / `DAILY_FILE` / spool。否则跑一次测试就往**仓库**里留产物：
  `test_once_gate.py` §⑤ 就是这么把 `.farm-check.state` 写进 `scripts/` 过的（已清掉）。

## 约定

- 这些脚本**不在 `deploy.sh` 的白名单里**，也**不进容器** —— 是 Windows 侧手动诊断用的，
  跟 `check-indexer-timestamps.py` / `migrate-reseed-dirs.py` 同一档。
- 涉及凭据的工具只用**合成样本**（`test_remove_indexer.py` 里全是 `FAKEKEY…`）。
- 别把测试产物写进仓库；需要落盘就 `tempfile.mkdtemp()`。

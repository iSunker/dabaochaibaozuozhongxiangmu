## §22 `matched_indexers` 恒空 + HDtime 的 429 到底是哪种限流（2026-09-14）

两件事同一天查清，**共用同一批材料**（Prowlarr 日志 / cross-seed 日志 / 两张库表），
但它们**是两个毛病**，别并成一个。

### 22.1 症状与第一条判据：先问「判据有没有被走到」，别先读代码

（#73）`movie.matched_indexers` 全库 **605 行、0 条非空**，而同一张表 `matched_hashes` 非空 392、
`stage=SEEDING` 391 —— 一个"看着有结构"的列，实际恒空。

**先跑判据、再展开查**（用户定的顺序，事后证明是对的）：拿 09-12 的日志喂**现在**的解析函数 ——
**1011 行命中**，按 `pack_contexts` 归片后带站名（dc-collection 146 / frds 865，
其中 `BTSCHOOL:88 / HDFans:448 / HDtime:44 / NanyangPT (南洋):285`）。

⇒ **写入点是被走到的、解析也有值** ⇒ 这**不是**「判据没参与匹配」（那是 §20 那一族的形状），
**是逻辑 bug** —— 留在本条，不挪走。

### 22.2 根因两段 + 修法：输入源易失 × 写入端不合并

★ 本节最值钱的一格，是「同一个函数里两列写法相反」：

| 段 | 事实 | 对照 |
|---|---|---|
| **① 输入源易失** | `facts.found` 的**唯一**输入是**当天**的 `info.current.log` | `searched` / `hashes` 都有 cross-seed.db 这**第二条腿**，**`found` 没有** |
| **② 写入端不合并** | `sync_movie` 对 `matched_indexers` 是**整行覆盖写** | 同一个函数里 `indexer_seen` 是**合并**的、`searched_indexers` 是 **union** 的 |

`drive-loop.py` 的 `first_existing()` 只挑 `cross-seed/logs/info.current.log` 这一个文件，
而 `run.sh` 从不传 `--log`。日志跨天一滚动（`info.current.log` → `info.YYYY-MM-DD.log`），
下一次 sync 就把整列抹成 `[]`；而 **SEEDING 的行不会再被搜** ⇒ **永不恢复**。

★ **两列语义相同、写法相反 = 遗漏，不是设计** —— `indexer_seen` 与 `matched_indexers`
都记「单调事实」（这部片在这个站匹配过，就是匹配过）。

**生产见证（判据指回一条真实记录）**：同一张 605 行的表，
**09-12 实测非空 215 部**（`SUMMARY:4515`，§17 那一节）→ **09-14 变 0 部**。

**修法** —— **不采用**「喂全部 `info.*.log`」：成本随保留天数涨（14 天 = 14 个文件），
且**仍不覆盖被轮换掉的**；而这一列的本意是**累积事实**，不是"最近 N 天的窗口"。改成：

- `sync_movie`：`old_matched_idx | {i for _, i in matched if i}` —— 与 `indexer_seen` **同语义**。
- `sync_pack`：`matched` 从「`|hashes|` 个 `(h, "A|B")` **合体标签**」改成
  「`|hashes| × |站|` 个 `(h, 单站)`」。理由两条：并集在**合体元素上没有定义**
  （`{"A|B"} ∪ {"A"}` 该是几个？），而且读侧 `_sites()` 按 JSON 数组**逐项**取、
  不认里面的 `|` —— 合体会造出一个叫 `"A|B"` 的**假站名**。
  老库里残留的合体标签，在写入端**拆开**再并。

**回归** `tests/test_matched_indexers_union.py`（15 条）：★★ **红过再绿** ——
回退那两个 hunk ⇒ **红 4 条**，恰好是「跨天不丢 / 并集 / 拆合体 / 别的包仍保留」那一族。
另钉两组对照：**单调的只有这一列**（`matched_hashes` 仍被整行覆盖、`stage` 照旧会塌），
以及 per-站展开**没有**污染 `matched_hashes` / `seeding_count`。

★ **未部署** —— `orchestrator/state.py` 在 `deploy.sh` 白名单里，下一次 `--apply` 会带上它，
**那次别撞批次**。部署后要在生产上**回读 `matched_indexers` 非空回升**（参照那个 215 部）。

### 22.3 HDtime 的 429：**是 Prowlarr 发的**，不是站点在限流

（#74）症状是「HDtime 每次查询都被 429」。查下来**起头不是限流，是站点 5xx** ——
三行全取 **Prowlarr 自己的日志**（脱敏后原样）：

```
2026-09-13 11:30:11.3|Warn|Cardigann|Request for HDtime failed with status InternalServerError. Retrying in 0.9856542s.
2026-09-13 11:31:50.1|Warn|Cardigann|Unable to connect to HDtime at [https://hdtime.org/torrents.php?…]
2026-09-14 11:36:11.4|Warn|Cardigann|HDtime server is currently unavailable. https://hdtime.org/torrents.php?…
```

同一批日志里 **429 一条都没有**（`grep -i 429` 命中的全是 `2429 bytes` / `0.0042937s`
这类**数字噪音**）⇒ cross-seed 收到的那个 429 **是 Prowlarr 发的**。

★ **排除两项**（各有一条独立证据，不是表态）：
- **不是我们搜太勤** —— 09-10 / 09-11 就在失败，那时 HDtime **还没进 `run.sh` 的 `--indexers`**。
- **不是 CF 挑战** —— Prowlarr 全部日志 **0 条** FlareSolverr 字样。

★ **判据换成两个脚本**（原先是一条**把 key 打在命令行上**的裸 `curl` —— 见 22.5）：
`python scripts/prowlarr-indexerstatus.py`（Prowlarr 侧）+ `python scripts/check-indexer-timestamps.py`（cross-seed 侧）。
2026-09-14 14:27 的读数：`indexerstatus` 数组**长度 1**，只有 HDtime，
`disabledTill = 2026-09-14T09:38:01Z`（本地 **17:38:01**），`mostRecentFailure = 11:38:01`。

### 22.4 `ERR-SVC-17` 改「有据」—— 同时**推翻了自己写过的一条读数**

（#65）`ENVIRONMENT.md` 的 `ERR-SVC-17`（「`retry_after` 一个数盖了**三种**机制」）
从「这是推断」改成「有据」，依据是 Prowlarr 自己那行：

```
2026-09-14 11:36:31.6|Debug|IndexerFactory|Temporarily ignoring indexer HDtime
                                          till 09/15/2026 11:36:11 due to recent failures.
cross-seed indexer  retry_after = 2026-09-15 11:36:41          ← 差 30 秒，同一时刻
```

⇒ **cross-seed 那个「递增到 24 h」不是它自己发明的阶梯**。**仍未实测的只剩一处**：
它是**原样转抄 `Retry-After`**，还是**读到了、但按自己的起算点重算**（差别只在那 30 秒，
不影响「谁更长」）。验法见 `INDEX-USAGE` §八 的时间门控。

★★ **同一批读数推翻了一条自己写过的边界**：原文那句「Prowlarr 那侧的窗口反而
**恒为 6 小时**」**不成立** —— Prowlarr 在 `11:36:31` 自己报的是 **24 h**，
6 h 只是 `14:27` 那次 `indexerstatus` 的读数。同日窗口变过；且 `11:38:01`
在「已禁用应被短路」期间**又记了一次失败** ⇒ 这两处都与旧边界不一致。
**Prowlarr 的升级规则没读源码，不做推断** —— 只留读数，实操口径改成
「**放行时刻 = 表里最晚的那个**」。

★ 顺带补了一节 **「清 snooze ≠ 免费修复」**：清 Prowlarr 的禁用**不够**
（两个时钟差 ≈ 18 h），清 cross-seed 的 snooze **也不够**（上游 5xx 还在）；
唯一抓手是**查上游**。重放**不伤站**（被禁用的站在 Prowlarr 里就被短路了），
但也换不来产出。


### 22.5 本节的四条方法论（比结论更该带走）

- **「列恒空」先问「判据有没有被走到」，别先读代码。** 走到 ⇒ 逻辑 bug；没走到 ⇒
  那是「判据没参与匹配」（另一族，见 §20）。这次**先跑判据再展开**，20 分钟内定的性。
- ★★ **「同一批读数推翻自己写过的结论」要当场写在原地，别悄悄更新。** `22.4` 那条
  6 h→24 h 的更正是在文档里**显式标出来**的 —— 否则下次翻到旧读数的人会拿一个已被
  推翻的数当依据，而**他没有任何办法知道它被推翻了**。
- ★ **处方里出现「把 key 写在命令行上」的 `curl`，就是一个要修的缺陷**（同 §20.8
  那条「告警正文在教人泄露凭据」）。本次把 `ERR-SVC-17` 与 `A.5` 的两处处方换成了脚本：
  新收进仓库的 **`scripts/prowlarr-indexerstatus.py`**（key 从生产 `.env` 读、**绝不打印**、
  只打白名单字段、站名只取 `cross-seed.db` 的 `id`/`name` 两列）。它已登记进
  `check-deploy-drift.py` 的 `LOCAL_ONLY`（**不进 `deploy.sh` 白名单**，Windows 侧手动诊断用）。
- ★ **「喂全部日志」不是"更全面的修法"，是把成本从常数换成变量**：它随保留天数涨，
  且**永远**追不上被轮换掉的更早那份 —— 而这类列要的本就是**单调累积的事实**。

---


### 22.6 ★★ 2026-09-17 结案：`#60` 那个待验（"到点动不动"）**问错了问题**

`#60` 一直挂着一条待验：「Prowlarr 放行而 cross-seed **仍不动** ⇒ 推断坐实；
**动了** ⇒ 推断错」。09-17 去读了 `drive-loop.log` 里 **09-14 那一批**的逐秒时间轴，
结论是：**这一格观测不到，因为它本来就不会那样。**

```
11:15:01  批开始，读到 cross-seed 侧 retry_after = 11:32:28
          这一批**没有**中止，而是**如实等到 11:32:28**（退了 17.5 分钟）
11:32:28  ← cross-seed 那个时刻到点
11:32:31  立刻发第 1 条 `OK 204`  ← **差 3 秒**，一路发到 11:36:31 的第 9 条
11:36:41  Prowlarr 侧在同一分钟内又记了一次失败（写进 retry_after）
11:37:01  读到 retry_after=11:36:41，**它已经过去 20 秒** ⇒ 中止（要等到次日 1440 分钟）
```

⇒ ① **"到点就走"坐实了**（3 秒）—— 它**按 `retry_after` 自己到点就走**，
  与 Prowlarr 放不放行**无关**（它压根不看 `disabledTill`）。
② 所以「两个时钟取更长的为准」不是一条独立机制：**读数取 max 是结果，不是原因**。
  效果路径是"Prowlarr 拒转发 ⇒ cross-seed 收到 429 ⇒ **被写进**它自己的 `retry_after`"。
③ **恢复时刻就一个数**：`retry_after`。要问"还要等多久"查
  `scripts/check-indexer-timestamps.py`，**不必去对 Prowlarr 的时刻**。

★★ **顺带把「清 snooze ≠ 免费修复」的代价量化了**：清/到期之后**立刻花掉一次请求**，
而那次请求**失败并又写进一个更长的 `retry_after`**。09-13→09-14 那一步实测就是
「明天 11:36 恢复」变成「**后天** 11:36 恢复」——
⇒ **这一条的代价是 +24 小时，不是"一次请求"。**

★ 方法论（与本节 4 条并列，凑成第 5 条）：
**待验的判据本身可能是错的** —— `#60` 卡在"到点动不动"上整整三天，
而那一格**永远不会发生**。判据要能被**证伪**，也要能被**证无用**：
读到"它按自己的时钟走"之后，那条待验应当**当场作废**，而不是继续等。
（同族：`#70` 登记处「判据看着有结构、读完不知道它覆盖了什么」。）

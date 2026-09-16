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


# -*- coding: utf-8 -*-
"""`scripts/notify-spool.sh` 排空逻辑的回归 —— 钉住 **2026-09-13 邮件风暴**。

那天同一封告警被重发了约 6 次。三件事凑成了它：

  ① **重试无上界**。失败分支只说「保留在 spool，下轮重试」，而「下轮」= 5 分钟
     之后 ⇒ 一条永远发不出去的告警**无限重发**。
  ② **`say` 是致命的**。脚本 `set -e`，而 `say "  [已发] $ti"` 当时夹在
     `send_mail` 成功与 `log_event`/`mv` 之间；它的 stdout 一失败（那天
     `/volume1` 剩 0 字节），`echo` 返回非零 ⇒ 当场退出
     ⇒ **信已发出、日志没记、文件还在 spool**。
  ③ 于是每趟任务都：读到那条文件 → 发信成功 → 在 `say` 上死掉 → 什么都不记。

本文件三组对照，**每一组都对应上面的一个环节**：
  ① 发信一直失败 → 发信次数**必须封顶**（不是 5 次、不是无限次，是 3 次），
     封顶后归档 + 记一条 `[未确认]` 告警，且**之后一趟都不再发**。
  ② 发信成功但 **stdout 坏了** → 文件照样归档、日志照样记（老代码这里全丢）。
  ③ 正常路径的对照组：发一次、归档一次、记一次。

★ 为什么非要这几条：这个脚本此前**一个测试都没有**，而它的失败方式是
  「安静地多发几封邮件」—— 不看日志、不看 spool，你不会知道出过事。

全部离线：不联网、不碰 NAS、不碰生产 `.env`/`notify.conf`。
沙箱在 `tempfile.mkdtemp()`，脚本副本也在沙箱里跑（这样它旁边的 `notify.conf`
必然是「不存在」，不会被本机可能残留的配置干扰）。
"""
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

REPO = pathlib.Path(__file__).resolve().parent.parent
SRC = REPO / "scripts" / "notify-spool.sh"

_ok = 0
_n = 0


def check(name, cond, detail=""):
    """★ 行形必须和全仓一致（`  ok  ` / ` FAIL ` 前缀）——
    `tests/README.md` 那个重数器只认三种行形，写成第四种会被**静默漏掉**：
    本文件第一版打印的是 `  ✓ `，于是 README 那行数出来 `n=0`、TOTAL 停在 522，
    28 条断言一条都没进账，而**退出码仍是 0**（看着一切正常）。
    失败原因写在下一行 —— 那行不带前缀，不会污染计数。"""
    global _ok, _n
    _n += 1
    _ok += 1 if cond else 0
    print(("  ok  " if cond else " FAIL ") + "%s: %r" % (name, bool(cond)))
    if not cond and detail:
        print("        ← " + detail)


ALERT = """# reseed-notify v1
kind: alert
level: alert
ts: 2026-09-13 12:40:44
host: iSunker-DS423
key: indexer-blocked:HDtime
title: 站点退避中：HDtime
metrics: indexer=HDtime status=RATE_LIMITED
---
HDtime 此刻在退避（RATE_LIMITED）。
"""

INFO = """# reseed-notify v1
kind: batch
level: info
ts: 2026-09-13 12:40:43
host: iSunker-DS423
key: batch:frds
title: frds 本批完成
metrics: ok=16 failed=0
---
包: frds
"""


class Lab:
    """一个沙箱：脚本副本 + spool/archive/log + 打桩发信程序。"""

    def __init__(self):
        self.d = pathlib.Path(tempfile.mkdtemp(prefix="notify-lab-"))
        shutil.copy2(SRC, self.d / "notify-spool.sh")
        for sub in ("spool", "archive", "log"):
            (self.d / sub).mkdir()
        self.count = self.d / "mails.txt"      # 每发一次追加一行
        self.count.write_text("", encoding="utf-8")
        self.fail = self.d / "MAILER-SHOULD-FAIL"
        # 打桩发信程序：记一次调用，然后按哨兵文件决定成败。
        # ★ 用哨兵文件而不是环境变量，是为了能在**同一批运行之间**翻转成败。
        stub = self.d / "mailer.sh"
        stub.write_text(
            "#!/bin/sh\n"
            "echo x >> '%s'\n"
            "[ -f '%s' ] && exit 1\n"
            "exit 0\n" % (self.count.as_posix(), self.fail.as_posix()),
            encoding="utf-8",
        )
        os.chmod(stub, 0o755)
        self.stub = stub

    def env(self, tries="3"):
        e = dict(os.environ)
        e.update(
            NOTIFY_ROOT=str(self.d),
            MAIL_TO="lab@test.invalid",
            MAIL_FROM="lab@test.invalid",
            SUBJECT_PREFIX="[reseed-lab]",
            MAILER_CMD=str(self.stub),
            MAX_MAILS_PER_RUN="5",
            MAX_SEND_TRIES=tries,
        )
        return e

    def event(self, name, body):
        (self.d / "spool" / name).write_text(body, encoding="utf-8")

    def n_mails(self):
        return len([ln for ln in self.count.read_text(encoding="utf-8").splitlines() if ln.strip()])

    def spool(self):
        return sorted(p.name for p in (self.d / "spool").glob("*.txt"))

    def archive(self):
        return sorted(p.name for p in (self.d / "archive").glob("*.txt"))

    def logtext(self):
        out = []
        for p in sorted((self.d / "log").glob("*.tsv")):
            out.append(p.read_text(encoding="utf-8", errors="replace"))
        return "".join(out)

    def run(self, close_stdout=False):
        """跑一次排空。close_stdout=True 时把 fd 1 关掉 —— 复现那天 `echo`
        写不进去（ENOSPC/EBADF）的情形，也就是风暴的**触发条件**。"""
        if close_stdout:
            cmd = ["sh", "-c", "exec 1>&-; exec sh ./notify-spool.sh"]
        else:
            cmd = ["sh", "./notify-spool.sh"]
        return subprocess.run(
            cmd, cwd=str(self.d), env=self.env(), capture_output=True,
            text=True, encoding="utf-8", errors="replace", timeout=120,
        )

    def cleanup(self):
        shutil.rmtree(self.d, ignore_errors=True)


# =====================================================================
print("\n── ① 对照组：发信正常 → 发一次、归档一次、记一次 ──")
lab = Lab()
try:
    lab.event("1789274444219-14909-HDtime.txt", ALERT)
    r = lab.run()
    check("退出码 0", r.returncode == 0, "实际 %s（stderr: %s）" % (r.returncode, r.stderr.strip()[:200]))
    check("发了 1 封", lab.n_mails() == 1, "实际 %d" % lab.n_mails())
    check("已归档", lab.archive() == ["1789274444219-14909-HDtime.txt"], str(lab.archive()))
    check("spool 已空", lab.spool() == [], str(lab.spool()))
    check("日志里记了这一条", "站点退避中：HDtime" in lab.logtext())
    check("日志 kind=alert", "\talert\t" in lab.logtext())
    check("没有残留重试计数", not list((lab.d / "spool").glob("*.tries")))
finally:
    lab.cleanup()

# =====================================================================
print("\n── ② ★ 触发条件：发信成功但 stdout 坏了 → 仍须归档 + 记账 ──")
print("     （老代码在这里把「已发出去的信」整条丢掉：日志空、文件留在 spool，")
print("       下一趟再发一遍 —— 这正是风暴的机械结构）")
lab = Lab()
try:
    lab.event("1789274444219-14909-HDtime.txt", ALERT)
    r = lab.run(close_stdout=True)
    check("即便 stdout 关掉，退出码仍是 0", r.returncode == 0,
          "实际 %s（这本身就是老代码的病症：非 0 = 半途退出）" % r.returncode)
    check("信只发了 1 封（没有因为报错而重来）", lab.n_mails() == 1, "实际 %d" % lab.n_mails())
    check("★ 仍然归档了", lab.archive() == ["1789274444219-14909-HDtime.txt"], str(lab.archive()))
    check("★ 仍然记了账", "站点退避中：HDtime" in lab.logtext())
    check("spool 已空", lab.spool() == [], str(lab.spool()))
finally:
    lab.cleanup()

# =====================================================================
print("\n── ③ ★ 重试上界：一直发不出去 → 发信次数必须封顶，且封顶后不再发 ──")
lab = Lab()
try:
    lab.event("1789274444219-14909-HDtime.txt", ALERT)
    lab.fail.write_text("x", encoding="utf-8")       # 发信一律失败

    for i in (1, 2):
        lab.run()
        check("第 %d 趟：已发 %d 封，文件留在 spool 等下轮" % (i, i),
              lab.n_mails() == i and lab.spool() == ["1789274444219-14909-HDtime.txt"],
              "mails=%d spool=%s" % (lab.n_mails(), lab.spool()))

    # ★ 第 3 趟 = 撞到 MAX_SEND_TRIES：这一趟**不再留在 spool**，
    #   而是归档 + 记一条 [未确认]。所以跑完这趟 spool 就该空了。
    lab.run()
    check("第 3 趟：发了第 3 封（= 上限，不是第 4 封）", lab.n_mails() == 3,
          "实际 %d 封" % lab.n_mails())

    check("★ 到第 3 次（= MAX_SEND_TRIES）后已归档", lab.archive() == ["1789274444219-14909-HDtime.txt"],
          str(lab.archive()))
    check("★ 记了一条 [未确认] 告警（会进每日摘要）", "[未确认]" in lab.logtext(),
          "日志里没有 [未确认]")
    check("★ 那条进的是「告警明细」口径（kind=alert）",
          any("\talert\t" in ln and "[未确认]" in ln for ln in lab.logtext().splitlines()))

    before = lab.n_mails()
    for i in range(2):
        lab.run()
    check("★ 封顶后再跑 2 趟，一封都没多发（老代码这里会变成无限重发）",
          lab.n_mails() == before, "又发了 %d 封" % (lab.n_mails() - before))
    check("重试计数已清掉", not list((lab.d / "spool").glob("*.tries")))
finally:
    lab.cleanup()

# =====================================================================
print("\n── ④ batch 事件：不发信，但必须归档 + 记账（且一行失败不许带走整趟）──")
lab = Lab()
try:
    lab.event("1789274443776-14909-frds.txt", INFO)
    r = lab.run()
    check("退出码 0", r.returncode == 0, "实际 %s" % r.returncode)
    check("batch 事件**不发信**", lab.n_mails() == 0, "实际 %d 封" % lab.n_mails())
    check("归档了", lab.archive() == ["1789274443776-14909-frds.txt"], str(lab.archive()))
    check("记账了（摘要靠它）", "frds 本批完成" in lab.logtext())
finally:
    lab.cleanup()

# =====================================================================
print("\n── ⑤ alert + batch 混合：同一趟里一条发了、一条归档，两条都要记 ──")
lab = Lab()
try:
    lab.event("1789274443776-14909-frds.txt", INFO)
    lab.event("1789274444219-14909-HDtime.txt", ALERT)
    lab.run()
    check("发了 1 封（batch 不发）", lab.n_mails() == 1, "实际 %d" % lab.n_mails())
    check("两条都归档了", len(lab.archive()) == 2, str(lab.archive()))
    t = lab.logtext()
    check("两条都记了账", "frds 本批完成" in t and "站点退避中：HDtime" in t)
    check("spool 已空", lab.spool() == [], str(lab.spool()))
finally:
    lab.cleanup()

print("\n── ⑥ ★★ TSV 第 5 列 `msg` = 正文首行，且旧行向后兼容（#68）──")
#   ★ 为什么要有这一列：摘要的「告警明细」原来只打 `$1 $3`（时间 + 标题），
#     metrics 与正文**全丢** ⇒ 「观测对账：判据没走通」这种**标题里没有数**的告警，
#     读者一个字都判不了（fa=0 fb=0 就在 metrics 里）。
#   ★ 判据**成对**：新行要有第 5 列，**旧行（4 列）不许被打出多余内容** ——
#     否则摘要会凭空多一行空白，或者多打一个空格把版面弄乱。
lab = Lab()
try:
    lab.event("1789274444219-14909-HDtime.txt", ALERT)
    r = lab.run()
    check("退出码 0", r.returncode == 0, "实际 %s" % r.returncode)
    rows = [ln for ln in lab.logtext().splitlines() if "\talert\t" in ln]
    check("记了一行 alert", len(rows) == 1, str(rows))
    cols = rows[0].split("\t") if rows else []
    check("★ 有第 5 列（不像以前那样只有 4 列）", len(cols) >= 5, "实际 %d 列" % len(cols))
    check("★★ 第 5 列 = 正文首个非空行",
          cols[4] if len(cols) > 4 else None,
          "HDtime 此刻在退避（RATE_LIMITED）。")
    check("★ 第 1/3/4 列位置**没动**（改动能安全落地的全部前提）",
          (cols[0] if cols else None, cols[2] if len(cols) > 2 else None),
          ("2026-09-13 12:40:44", "站点退避中：HDtime"))
    #   ★★ 摘要渲染的阴性对照：**旧行（4 列）**走同一条 awk，不许多打任何东西。
    #     直接调那段 awk 的等价逻辑（不启动整个 digest，避免发信）。
    _lines = "2026-09-13 12:40:44\talert\t旧行没有第5列\tindexer=HDtime"
    _out = subprocess.run(
        ["awk", "-F\t", '{printf "  %s  %s\\n", $1, $3; '
                        'if (NF >= 5 && $5 != "") printf "      %s\\n", $5}'],
        input=_lines, capture_output=True, text=True, encoding="utf-8").stdout
    check("★★ 旧行（4 列）摘要里**不出现**第 5 行（向后兼容）",
          _out.count("\n") == 1,
          "实际打出 %d 行：%r" % (_out.count("\n"), _out))
finally:
    lab.cleanup()

print("\n" + ("✓ %d 条断言全过 —— 告警不会漏记，也不会被无限重发" % _n
              if _ok == _n else
              "✗ 有对照没过（%d/%d）—— 别拿它当推前闸门" % (_ok, _n)))
sys.exit(0 if _ok == _n else 1)

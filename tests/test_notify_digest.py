# -*- coding: utf-8 -*-
"""`scripts/notify-spool.sh` 每日摘要那一行的**汇总**（#67）。

摘要此前只有「批次 : N」一个计数，读者要自己扫 12 批明细才看得出
「这三天几乎没搜出去」。本文件钉的是新加的那行汇总 —— 但真正要钉的
不是「加了一行」，而是**它数的东西对不对**：

  ★★ **「批次」不能按 kind 数。** `每日台账` 与 `全部包已无待搜项`
     也是 `kind=batch`（走 batch 是为了「记账但不发信」，见 drive-loop.py）。
     照 kind 数，生产上 09-13+09-14 那两窗会得到 **17**，而真批次只有 **12**。
     判据取「metrics 里有没有 `pack=` 这个键」。

  ★★ **`packs=` 不是 `pack=`。** 「无待搜」那行的键是 `packs`（整键相同才算命中），
     前缀匹配会把它算成一批 —— 于是它同时污染批次数与 ok=0 的批数。

  ★★ **「键在不在」不等于「值等不等于 0」。** `ok=0` 是真读数；
     「这行没有 ok=键」是另一回事。当成 0 就是假读数 ——
     与 #63/#64（`content_path` 缺键被印成「(空)」）**同一形状**。

★ 这个文件**必须红过再绿**：把 notify-spool.sh 回退到 #67 之前
  （`git checkout <#67>^ -- scripts/notify-spool.sh`），本文件应当**红**；
  恢复则全绿。一份在旧代码上也全绿的用例等于没测到东西。

全部离线：不联网、不碰 NAS、不碰生产 `.env`/`notify.conf`。
沙箱（含脚本副本）在 `tempfile.mkdtemp()` —— 副本旁边的 `notify.conf`
必然是「不存在」，不会被本机残留的配置干扰。**不发信**：跑的是 `--dry-run`。
"""
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile

try:
    sys.stdout.reconfigure(encoding="utf-8")   # GBK 控制台会炸（tests/README.md）
except Exception:
    pass

REPO = pathlib.Path(__file__).resolve().parent.parent
SRC = REPO / "scripts" / "notify-spool.sh"

_ok = 0
_n = 0


def check(name, cond, detail=""):
    """★ 行形必须和全仓一致（`  ok  ` / ` FAIL ` 前缀）——
    `tests/README.md` 那个重数器只认三种行形，写成第四种会被**静默漏掉**
    （`test_notify_drain.py` 第一版就打印过 `  ✓ `，28 条一条都没进账，
    而退出码仍是 0）。失败原因写在下一行 —— 那行不带前缀，不污染计数。"""
    global _ok, _n
    _n += 1
    _ok += 1 if cond else 0
    print(("  ok  " if cond else " FAIL ") + "%s: %r" % (name, bool(cond)))
    if not cond and detail:
        print("        ← " + str(detail))


# TSV 四列：ts / kind / title / metrics。下面是**合成的**行，形状照抄生产 TSV
# （列数与键名都来自 2026-09-13 / 09-14 的真实流水）。
def row(ts, kind, title, metrics):
    return "%s\t%s\t%s\t%s\n" % (ts, kind, title, metrics)


def batch(pack, **kv):
    """一条「本批完成」流水。键序照生产：pack / ok / failed / newly_seeding /
    still_skipped / backoff_hits。

    ★★ `pack=` 必须**显式拼**进去：本函数第一个形参就叫 `pack`，它被**位置参数**
       吃掉、不会出现在 `**kv` 里 —— 曾经写成 `kv[k] if k in kv` 连 `pack` 一起滤掉，
       于是生成的流水**一个 `pack=` 都没有**，被测脚本忠实地把每一行都判成
       「非本批」。当时红的是**测试自己**（tests/README.md：「测试自己也是判据，
       报红时先怀疑断言本身」）。
    """
    parts = ["pack=%s" % pack] + ["%s=%s" % (k, v) for k, v in kv.items()]
    return row("2026-09-13 00:00:00", "batch", "%s 本批完成" % pack, " ".join(parts))


class Lab:
    """一个沙箱：脚本副本 + spool/archive/log。**不发信**（跑 --dry-run）。"""

    def __init__(self):
        self.d = pathlib.Path(tempfile.mkdtemp(prefix="digest-lab-"))
        shutil.copy2(SRC, self.d / "notify-spool.sh")
        for sub in ("spool", "archive", "log"):
            (self.d / sub).mkdir()

    def tsv(self, day, text):
        (self.d / "log" / ("%s.tsv" % day)).write_text(text, encoding="utf-8")

    def run(self, *args):
        env = dict(os.environ)
        env.update(
            NOTIFY_ROOT=str(self.d),
            MAIL_TO="lab@test.invalid",
            MAIL_FROM="lab@test.invalid",
            SUBJECT_PREFIX="[reseed-lab]",
        )
        return subprocess.run(
            ["sh", "./notify-spool.sh", "--digest", "--dry-run", *args],
            cwd=str(self.d), env=env, capture_output=True,
            text=True, encoding="utf-8", errors="replace", timeout=120,
        )

    def cleanup(self):
        shutil.rmtree(self.d, ignore_errors=True)


# ── 手算基线（★ 期望值写死在这里，**不是**从输出反推） ──────────────────────
#   真批次 4 条：frds(22/18/2)  dc0816(0/15/1)  mbf(0/0/1)  dc1139(9/0/2)
#     本批运行 = 4        ok=0 的 = 2（dc0816、mbf）
#     新增做种 = 18+15+0+0 = 33      退避 = 2+1+1+2 = 6
#   非本批 3 条：两条「每日台账」（无 pack=）+ 一条「全部包已无待搜项」（键是 packs=）
DAY13 = (
    row("2026-09-13 00:38:28", "alert", "站点退避中：HDtime",
        "indexer=HDtime status=RATE_LIMITED")
    + batch("frds-top250-2024", ok=22, failed=0, newly_seeding=18,
            still_skipped=0, backoff_hits=2)
    + row("2026-09-13 00:38:28", "batch", "每日台账",
          "day=2026-09-13 iyuu=100 fa=76 fb=76")
    + batch("dc-collection", ok=0, failed=0, newly_seeding=15,
            still_skipped=0, backoff_hits=1)
)
DAY14 = (
    row("2026-09-14 01:31:38", "batch", "每日台账", "day=2026-09-14 iyuu=303 fa=0 fb=0")
    + batch("mbf", ok=0, failed=0, newly_seeding=0, still_skipped=0, backoff_hits=1)
    + batch("dc-collection", ok=9, failed=0, newly_seeding=0,
            still_skipped=0, backoff_hits=2)
    + row("2026-09-14 12:00:00", "batch", "全部包已无待搜项（3 个包）", "packs=3")
)

# =====================================================================
print("\n── ① 汇总数字 = 逐行手算 ──")
lab = Lab()
try:
    lab.tsv("2026-09-13", DAY13)
    lab.tsv("2026-09-14", DAY14)
    r = lab.run()
    out = r.stdout
    check("退出码 0", r.returncode == 0, "rc=%s stderr=%s" % (r.returncode, r.stderr.strip()[:200]))
    check("★ 本批运行 : 4 批（不是 5、也不是按 kind 数的 7）", "本批运行 : 4 批" in out,
          [ln for ln in out.splitlines() if "本批运行" in ln])
    check("   ok=0 的 2 批", "ok=0 的 2 批" in out,
          [ln for ln in out.splitlines() if "本批运行" in ln])
    check("   新增做种 33", "新增做种 33" in out,
          [ln for ln in out.splitlines() if "本批运行" in ln])
    check("   退避 6 次", "退避 6 次" in out,
          [ln for ln in out.splitlines() if "本批运行" in ln])
    check("★ 告警 : 1（kind=alert 那一条）", "告警     : 1" in out or "告警 : 1" in out,
          [ln for ln in out.splitlines() if "告警" in ln][:3])

    print("\n── ② ★ 台账与「无待搜」不算批次 ──")
    check("★ 非本批 : 3 条（两条台账 + 一条无待搜）", "非本批   : 3 条" in out,
          [ln for ln in out.splitlines() if "非本批" in ln])
    check("★ 明细里「每日台账」仍在（#67 不动明细行）", "每日台账" in out)
    check("★ 明细里「全部包已无待搜项」仍在", "全部包已无待搜项" in out)

    print("\n── ③ ★★ `packs=` 不是 `pack=`（前缀匹配会多算一批）──")
    check("★ 无待搜那行**没有**被算进批次（否则这里会是 5 批）",
          "本批运行 : 5 批" not in out and "本批运行 : 4 批" in out)
    check("★★ 也没有被算成一批 ok=0（否则会是 3 批）", "ok=0 的 3 批" not in out)

    print("\n── ④ 明细行一字不动（时间 / 包 + 缩进的 metrics，两行形）──")
    check("★ metrics 行仍在（缩进 6 空格）",
          "\n      pack=frds-top250-2024 ok=22 failed=0 newly_seeding=18" in out,
          repr([ln for ln in out.splitlines() if "pack=frds" in ln]))
    check("★ 原来的 `批次 : N` 那行**已去掉**（它按 kind 数，会把台账算进去）",
          "批次 : " not in out)
finally:
    lab.cleanup()

# =====================================================================
print("\n── ⑤ ★★ 键在不在 ≠ 值等不等于 0（合成的边界行）──")
print("     一条带 pack= 但**没有 ok= 键**的流水：它仍是一批，但不许被算成 ok=0。")
lab = Lab()
try:
    lab.tsv("2026-09-14", (
        batch("mbf", ok=0, failed=0, newly_seeding=0, still_skipped=0, backoff_hits=1)
        + row("2026-09-14 02:00:00", "batch", "ghost 本批完成",
              "pack=ghost failed=0 newly_seeding=0")
    ))
    out = lab.run().stdout
    check("★ 两批都算进去了（缺 ok= 不影响「是不是一批」）", "本批运行 : 2 批" in out,
          [ln for ln in out.splitlines() if "本批运行" in ln])
    check("★★ ok=0 的**只有 1 批** —— 缺键的那条不许当 0（当成 0 会是 2）",
          "ok=0 的 1 批" in out, [ln for ln in out.splitlines() if "本批运行" in ln])
    check("★ 缺 backoff_hits 的那条不进退避合计（合计仍是 1）", "退避 1 次" in out,
          [ln for ln in out.splitlines() if "本批运行" in ln])
finally:
    lab.cleanup()

# =====================================================================
print("\n── ⑥ 边界：只有一天的 TSV / 一条批次都没有 ──")
lab = Lab()
try:
    lab.tsv("2026-09-14", batch("mbf", ok=0, failed=0, newly_seeding=0,
                                still_skipped=0, backoff_hits=1))
    r = lab.run()
    check("只有一天也不炸", r.returncode == 0, "rc=%s stderr=%s" % (r.returncode, r.stderr.strip()[:200]))
    check("  数还是对的", "本批运行 : 1 批" in r.stdout and "ok=0 的 1 批" in r.stdout)
    check("  没有台账 ⇒ 不出「非本批」那行（不刷 0）", "非本批" not in r.stdout)
finally:
    lab.cleanup()

lab = Lab()
try:
    lab.tsv("2026-09-14", row("2026-09-14 01:00:00", "alert", "某条告警", "a=1"))
    r = lab.run()
    check("没有批次也不炸、汇总出 0", r.returncode == 0 and "本批运行 : 0 批" in r.stdout,
          r.stdout[-300:])
    check("  明细处仍打「（无）」", "（无）" in r.stdout)
finally:
    lab.cleanup()

# =====================================================================
print("\n── ⑦ --dry-run 不发信（本文件全程靠这一条才敢离线跑）──")
lab = Lab()
try:
    lab.tsv("2026-09-14", batch("mbf", ok=0, failed=0, newly_seeding=0,
                                still_skipped=0, backoff_hits=1))
    r = lab.run()
    check("★ 打的是 [dry-run] 而不是 [已发]", "[dry-run]" in r.stdout and "[已发]" not in r.stdout,
          r.stdout[:200])
finally:
    lab.cleanup()

print("\n" + ("✓ %d 条断言全过 —— 汇总数的是「本批运行」，台账与无待搜不进账" % _n
              if _ok == _n else
              "✗ 有对照没过（%d/%d）—— 别拿它当推前闸门" % (_ok, _n)))
sys.exit(0 if _ok == _n else 1)

# -*- coding: utf-8 -*-
"""推前凭据扫描器 `scripts/scan-secrets.py` 的**对照** —— 证明它会响，也证明它不乱响。

一个只报「✓ 0 命中」的闸门是最危险的 —— 它让人以为看过了。所以这里两头都测：
阳性能不能拦住、假阳性会不会把闸门憋成"次次都红"（那样等于没有闸门）。

★ 两条自我约束：
  ① **不在真仓库里造任何含凭据形状的东西** —— 沙箱是 `tempfile.mkdtemp()`，
     在仓库之外。曾经把探针写成 `<repo>/.ctl-secret-probe.txt`（随即删掉），
     那是错的：在一个"防止凭据进仓库"的任务里往待推目录塞凭据形状的文件，
     本身就是这件事要防的。
  ② **合成样本的值一律由变量拼出来，源码里不写字面量** —— 否则推前扫描会扫到
     **这个测试文件自己**。闸门自己的对照集必须先过闸门。

全部离线：不联网、不碰 NAS、不碰生产 `.env`（沙箱里那个是现造的存根）。
"""
import contextlib
import importlib.util
import io
import pathlib
import shutil
import subprocess
import sys
import tempfile

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HERE = pathlib.Path(__file__).resolve().parent          # 路径按 __file__ 解析，任一 cwd 都行
REPO = HERE.parent
SCANNER = REPO / "scripts" / "scan-secrets.py"

# ---- 合成样本：值全部拼出来，不在源码里留字面量（见文件头 ★②）----
CRED = "Zq7mNv3Kd9Rt2Wp5Xy8Lb4Jh6Gc1Fs0A"     # 随机形状，**不是 FAKE 开头**（FAKE 会被白名单跳过）
CRED2 = "Kp9Wq3Zr7Tn5Vb2Md8Lf4Xc6Gh1Jk0S"    # 不在沙箱 .env 里，只有形状层能抓
CAT = "pt-alnum-slug"                         # 分类名：不该被当成凭据
PLACEHOLDER = "-".join(["please", "change", "me", "to", "a", "long", "random", "string"])
REPEAT = "y" * 16                             # 占位符那种"同一个字符重复"
ENVREF = ".".join(["process", "env", "CROSSSEED_API_KEY"])
CFGREF = ".".join(["cfg", "matcher", "crossseed_api_key"])

ok = True
n = 0


def check(name, cond, extra=""):
    global ok, n
    ok &= bool(cond)
    n += 1
    print(f"  {'ok  ' if cond else 'FAIL'} {name}{('  ' + extra) if extra else ''}")
    return cond


def run(files, sandbox):
    r = subprocess.run([sys.executable, str(SCANNER), str(sandbox)] + files,
                       capture_output=True, text=True, encoding="utf-8")
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def load_scanner(env_repo):
    """把扫描器当模块载进来，就为了拿它的 SHAPES 与 benign()。

    ★ 不再用"按 `hits = []` 切源码、只 exec 前半段"那种做法 —— 切点一改就
      **静默失效**：切出来的前半段照样能跑，只是少了后半个文件的定义。
      直接 exec_module 拿**真的那一份**，报错也报在真的那份上。
      （它是脚本，结尾会 sys.exit，所以吞掉 SystemExit；输出也一并咽掉。）
    """
    old_argv = sys.argv
    sys.argv = [str(SCANNER), str(env_repo), "__no_such_file__"]
    try:
        spec = importlib.util.spec_from_file_location("scan_secrets_mod", SCANNER)
        mod = importlib.util.module_from_spec(spec)
        with contextlib.redirect_stdout(io.StringIO()):
            try:
                spec.loader.exec_module(mod)
            except SystemExit:
                pass
        return mod
    finally:
        sys.argv = old_argv


def git(sandbox, *args):
    subprocess.run(["git", "-C", str(sandbox), "-c", "user.email=t@t",
                    "-c", "user.name=t"] + list(args), check=True, capture_output=True)


def build(sandbox):
    # 沙箱的"生产 .env"：一个真形状的 key + 一个分类名（分类名不该被当成凭据）
    (sandbox / ".env").write_text(f"PROWLARR_API_KEY={CRED}\nQBIT_CATEGORY={CAT}\n",
                                  encoding="utf-8")
    # 形状命中用 / 值指纹命中用，分开放，好分辨是哪条路径响了
    (sandbox / "leak-shape.txt").write_text(f'api_key = "{CRED}"\n', encoding="utf-8")
    (sandbox / "leak-value.txt").write_text(f"PROWLARR_API_KEY={CRED}\n", encoding="utf-8")
    (sandbox / "clean.txt").write_text(f"QBIT_CATEGORY={CAT}\n# 这行提到 {CAT}，不该命中\n",
                                       encoding="utf-8")
    # ⑦ 三类"看着像、其实不是"—— 全部来自真仓库 2026-09-12 实扫的那 5 处
    (sandbox / "fp-code.js").write_text(f"  apiKey: {ENVREF} || undefined,\n",
                                        encoding="utf-8")
    (sandbox / "fp-code.py").write_text(
        f"        cs = CrossSeedClient(cfg.matcher.crossseed_url, api_key={CFGREF})\n",
        encoding="utf-8")
    (sandbox / "fp-phrase.env.example").write_text(
        f"CROSSSEED_API_KEY={PLACEHOLDER}\n"
        f"TORZNAB_URLS=http://p:9696/2/api?apikey={REPEAT}\n", encoding="utf-8")


SB = pathlib.Path(tempfile.mkdtemp(prefix="scan-probe-"))
try:
    build(SB)
    mod = load_scanner(SB)

    print("── ① 三个最常见的名字必须都能被**形状正则**抓到（`\\b` 锚点那个 bug）──")
    for name in ("PROWLARR_API_KEY", "CROSSSEED_API_KEY", "API_KEY"):
        check(f"形状正则会抓 `{name}=…`",
              any(rx.search(f"{name}={CRED}") for _, rx in mod.SHAPES))

    print("\n── ② 阳性对照：沙箱里真的泄露 → 必须退出码 1，且两条路径都点名 ──")
    rc, out = run(["leak-shape.txt", "leak-value.txt"], SB)
    check("退出码 1", rc == 1, f"实际 {rc}")
    check("形状层命中 leak-shape.txt", "leak-shape.txt" in out)
    check("值指纹层命中 leak-value.txt", "leak-value.txt" in out)

    print("\n── ③ 阴性对照：干净文件 → 0 命中、退出码 0 ──")
    rc, out = run(["clean.txt"], SB)
    check("退出码 0", rc == 0, f"实际 {rc}")
    check("报「0 命中」", "0 命中" in out)

    print("\n── ④ 分类名不能被当成凭据（否则文档里提一句分类名就误报）──")
    rc, out = run(["clean.txt"], SB)
    check("没有把分类名报成命中", CAT not in out)

    print("\n── ⑤ 形状层**单独**也要拦得住（把 .env 挪走，断掉值指纹那条路）──")
    (SB / ".env").rename(SB / ".env.off")
    rc, out = run(["leak-value.txt"], SB)
    check("仍退出码 1（靠形状层）", rc == 1, f"实际 {rc}")
    check("命中 leak-value.txt", "leak-value.txt" in out)
    (SB / ".env.off").rename(SB / ".env")

    print("\n── ⑥ 输出被重定向到 NUL 时也必须一样（Windows 上 NUL 是字符设备，曾骗过 isatty）──")
    r = subprocess.run([sys.executable, str(SCANNER), str(SB), "leak-value.txt"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    check("stdout→NUL 时 rc=1", r.returncode == 1, f"实际 {r.returncode}")
    r = subprocess.run([sys.executable, str(SCANNER), str(SB), "clean.txt"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    check("干净文件 stdout→NUL 时 rc=0", r.returncode == 0, f"实际 {r.returncode}")

    print("\n── ⑦ 实扫出的三类假阳性：必须被**规则**认出来，且列出来不静默 ──")
    rc, out = run(["fp-code.js", "fp-code.py", "fp-phrase.env.example"], SB)
    check("退出码 0（不因为假阳性拦推）", rc == 0, f"实际 {rc}")
    check("报「形状正则 0 命中」", "0 命中" in out)
    check("跳过项**列出来**了", "按规则跳过" in out)
    check("代码表达式：理由正确", "代码表达式" in out)
    check("英文短语/占位符：理由正确", "占位符" in out)
    check("benign() 直接判占位符为非凭据", mod.benign(REPEAT) is not None)
    check("★ benign() 对真形状的 key **不许**放行", mod.benign(CRED) is None)

    print("\n── ⑧ 推前闸门只拦「本次新引入」，HEAD 里就有的不拦 ──")
    (SB / "in-head-leak.txt").write_text(f"PROWLARR_API_KEY={CRED}\n", encoding="utf-8")
    git(SB, "init", "-q")
    git(SB, "add", "in-head-leak.txt")
    git(SB, "commit", "-qm", "已存在于 HEAD 的泄露")
    rc, out = run(["in-head-leak.txt"], SB)
    check("HEAD 里就有的泄露：不拦（rc 0）", rc == 0, f"实际 {rc}")
    check("但明确标出「HEAD 里本就有」", "HEAD 里本就有" in out)
    check("并给出单列警告", "值得单独查一次" in out)

    (SB / "fresh-leak.txt").write_text(f"PROWLARR_API_KEY={CRED2}\n", encoding="utf-8")
    rc, out = run(["fresh-leak.txt"], SB)
    check("★ 本次新引入的泄露：拦（rc 1）", rc == 1, f"实际 {rc}")
    check("标出「本次新引入」", "本次新引入" in out)
    print("\n── ⑨ ★★ 非 ASCII 路径必须真的被扫到（#119）──")
    #   ★ 为什么必须在**沙箱里造**：被测脚本的失败方式是"静默少扫几个文件"，
    #     所以得先放一个中文名文件进去、再断言它真的进了扫描范围。
    #   ★ 复现的缺陷：`git ls-files` 默认 `core.quotepath=true` 把中文路径输出成
    #     带引号 + 八进制转义 ⇒ 下游 `(REPO / rel).is_file()` 为假 ⇒ **静默跳过**。
    #     实测本仓：111 个文件里 25 个中文名全被跳过（全是 `summary/*.md`）。
    (SB / "中文名文件.md").write_text("普通内容，不带凭据\n", encoding="utf-8")
    git(SB, "add", "-A")
    git(SB, "commit", "-qm", "加一个中文名文件")
    rc, out = run([], SB)          # 不传文件名 ⇒ 走 git ls-files 那条路
    #   ★ 判据是**自证那一行**：说得出扫了几个、且没有读不到的。
    check("★ 报出「扫描范围：N/N 个文件」（先自证再报结论）", "扫描范围" in out)
    check("★★ 没有「读不到文件」⇒ 扫描是完整的",
          "读不到文件" not in out,
          "出现「读不到文件」说明有路径没扫到 —— 那时「零命中」不是结论")
    #   ★★ 阴性对照：中文名文件里塞一条**真凭据**，必须**被点到名**。
    #     ★ 这里断言的是「点名」而不是「rc=1」—— 因为本节的这段已经被 commit 过，
    #       而闸门**只拦本次新引入**（⑧ 就是钉这条的）⇒ 它会正确地报「HEAD 里本就有」。
    #       断言 rc=1 是我第一版写错了（把⑧的语义套到了⑨上），**测试自己红了**。
    #     ★ 这一格量的是"中文名文件到底进没进闸门"：进不了闸门 ⇒ 输出里**根本没有它**。
    (SB / "中文名文件.md").write_text(f"PROWLARR_API_KEY={CRED}\n", encoding="utf-8")
    git(SB, "add", "-A")
    git(SB, "commit", "-qm", "中文名文件里塞真凭据")
    rc, out = run([], SB)
    check("★★ 中文名文件里的真凭据**被点到名**（否则它从没进过闸门）",
          "中文名文件.md" in out,
          "整份输出里找不到它 —— 说明中文名路径被静默跳过了")
    check("★ 且它确实被认成凭据命中（不是只出现在「扫描范围」那一行）",
          out.count("中文名文件.md") >= 2,
          f"只出现 {out.count('中文名文件.md')} 次，疑似只进了文件清单、没进命中")

finally:
    shutil.rmtree(SB, ignore_errors=True)

print(f"\n{('✓ ' + str(n) + ' 条断言全过 —— 扫描器会响、也不乱响') if ok else ('✗ 有对照没过（共 ' + str(n) + ' 条）—— 别拿它当推前闸门')}")
sys.exit(0 if ok else 1)

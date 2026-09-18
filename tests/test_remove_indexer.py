# -*- coding: utf-8 -*-
"""在**合成样本**上验证 add-torznab-indexer.py 的 --remove（含字节保真与安全闸）。

★ 样本里用的是**假 key**（FAKE…），绝不碰生产 .env。
★ 关键是"混行尾 + 目标行尾多一个游离 LF"这个组合 —— 上次就栽在这上面。
"""
import pathlib
import subprocess
import sys
import tempfile

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

REPO = pathlib.Path(__file__).resolve().parent.parent  # 仓库根
SCRIPT = str(REPO / "scripts" / "diag" / "add-torznab-indexer.py")
# ★ 落在系统临时目录、每轮一个全新的（原先钉死 D:/tmp/envtest，
#   上一轮遗留的样本会串味到下一轮）。
TMP = pathlib.Path(tempfile.mkdtemp(prefix="reseed-envtest-"))
TMP.mkdir(parents=True, exist_ok=True)
ENV = TMP / ".env"

FAKE = "FAKEKEY0123456789ABCDEF01234567"
B = "http://192.168.0.7:9696"

# 目标行结尾故意写成 "…/api\n\r\n"（多一个游离 LF）—— 复现生产那个形状
ORIG = (
    "# 注释行（CRLF 结尾）\r\n"
    "PUID=1026\r\n"
    "PGID=100\r\n"
    f"TORZNAB_URLS={B}/2/api?apikey={FAKE},{B}/4/api?apikey={FAKE},"
    f"{B}/3/api?apikey={FAKE},{B}/1/api?apikey={FAKE}\n\r\n"
    "LINK_DIR=/volume1/video/download/reseed/reseed_singles\r\n"
    f"PROWLARR_API_KEY={FAKE}\n"
)
ENV.write_bytes(ORIG.encode("utf-8"))


def run(*args):
    r = subprocess.run([sys.executable, SCRIPT, "--env", str(ENV), *args],
                       capture_output=True)
    return r.returncode, r.stdout.decode("utf-8", "replace") + r.stderr.decode("utf-8", "replace")


def torb():
    raw = ENV.read_bytes().decode("utf-8")
    line = next(l for l in raw.split("\n") if l.rstrip("\r").startswith("TORZNAB_URLS="))
    return line.rstrip("\r")[len("TORZNAB_URLS="):]


fails = []

# 1) 预检：不该改文件
before = ENV.read_bytes()
rc, out = run("--remove", "3")
ok = rc == 0 and ENV.read_bytes() == before and "将要摘掉 1 条" in out
print(f"[1] 预检不改文件            : {'PASS' if ok else 'FAIL'}  rc={rc}")
if not ok:
    fails.append(1); print(out)

# 2) 真摘：id=3 应消失，其余三条顺序不变
rc, out = run("--remove", "3", "--apply")
ok = rc == 0 and "/3/api" not in torb() and torb().count("/api") == 3
print(f"[2] --apply 摘掉 /3         : {'PASS' if ok else 'FAIL'}  rc={rc}  剩 {torb().count('/api')} 条")
if not ok:
    fails.append(2); print(out)

# 3) 字节保真：除目标行外逐字节相同
after = ENV.read_bytes()
same = True
la, lb = ORIG.encode("utf-8").split(b"\n"), after.split(b"\n")
if len(la) != len(lb):
    same = False
else:
    for x, y in zip(la, lb):
        if x != y and not x.startswith(b"TORZNAB_URLS="):
            same = False
print(f"[3] 除目标行外逐字节相同    : {'PASS' if same else 'FAIL'}")
if not same:
    fails.append(3)

# 4) 游离 LF 是否保住（那一行原本以 \n\r\n 结尾）
#   ★ 断言要放在**行尾**：目标行内容是 `…/api?apikey=FAKE`，所以针是 `FAKE\n\r\n`，
#     而不是 `api\n\r\n` —— 后者在哪儿都匹配不到（第一版就写错了，误报 FAIL）。
ok = (FAKE.encode() + b"\n\r\n") in after
print(f"[4] 目标行尾的游离 LF 保住  : {'PASS' if ok else 'FAIL'}")
if not ok:
    fails.append(4)

# 5) 幂等：再摘一次，退出码 0
before = ENV.read_bytes()
rc, out = run("--remove", "3", "--apply")
ok = rc == 0 and ENV.read_bytes() == before and "本来就不在" in out
print(f"[5] 幂等（重复摘）          : {'PASS' if ok else 'FAIL'}  rc={rc}")
if not ok:
    fails.append(5)

# 6) 加回来：回到 4 条（上站路径没被我改坏）
rc, out = run("--id", "3", "--apply")
ok = rc == 0 and torb().count("/api") == 4 and "/3/api" in torb()
print(f"[6] 加回 /3（往返）         : {'PASS' if ok else 'FAIL'}  rc={rc}")
if not ok:
    fails.append(6)

# 7) 安全闸：摘到一条不剩 → 退出 1，且**不改文件**
env2 = TMP / "one.env"
env2.write_bytes(f"TORZNAB_URLS={B}/3/api?apikey={FAKE}\nX=1\n".encode())
b2 = env2.read_bytes()
r = subprocess.run([sys.executable, SCRIPT, "--env", str(env2), "--remove", "3", "--apply"],
                   capture_output=True)
ok = r.returncode == 1 and env2.read_bytes() == b2
print(f"[7] 拒绝摘空（且没写文件）  : {'PASS' if ok else 'FAIL'}  rc={r.returncode}")
if not ok:
    fails.append(7); print(r.stdout.decode("utf-8", "replace"))

# 8) --remove 与 --id 互斥
rc, out = run("--remove", "3", "--id", "2")
ok = rc == 1 and "不能同时用" in out
print(f"[8] --remove + --id 互斥    : {'PASS' if ok else 'FAIL'}  rc={rc}")
if not ok:
    fails.append(8)

print()
print("全部通过 ✅" if not fails else f"★ 失败项: {fails}")
sys.exit(1 if fails else 0)

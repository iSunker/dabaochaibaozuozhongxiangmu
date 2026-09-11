#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
把新索引器追加进 NAS .env 的 TORZNAB_URLS（安全闸模式，仿 nas-update-env.sh）。

只改 TORZNAB_URLS 一行；其余行逐字节校验不变（防真实密钥被占位符串掉）。
用法:
  python add-indexers.py --env <NAS .env 路径> \
      --add prowlarr:9696/3,prowlarr:9696/4   # 逗号分隔的 "host:port/id"，按序追加
"""
import argparse
import shutil
import sys
from datetime import datetime
from pathlib import Path

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--env", required=True, help="NAS 上的 .env 路径（UNC 亦可）")
    ap.add_argument("--add", required=True,
                    help="逗号分隔的追加条目，如 'prowlarr:9696/3,prowlarr:9696/4'")
    ap.add_argument("--no-backup", action="store_true")
    args = ap.parse_args()

    env_path = Path(args.env)
    if not env_path.is_file():
        print(f"[!!] 找不到 .env: {env_path}", file=sys.stderr)
        return 1

    raw = env_path.read_text(encoding="utf-8")
    lines = raw.splitlines(keepends=True)

    # ---- 1) 定位现有 TORZNAB_URLS 行 ----
    tz_idx = None
    tz_line = None
    for i, ln in enumerate(lines):
        if ln.startswith("TORZNAB_URLS="):
            tz_idx, tz_line = i, ln
            break
    if tz_idx is None:
        print("[!!] .env 里没有 TORZNAB_URLS= 行", file=sys.stderr)
        return 1

    # ---- 2) 提取真实 apikey（从现有行，不打印）----
    val = tz_line.split("=", 1)[1].strip()
    existing = [u for u in val.split(",") if u.strip()]
    if not existing:
        print("[!!] TORZNAB_URLS 当前为空", file=sys.stderr)
        return 1
    apikey = None
    for u in existing:
        if "apikey=" in u:
            apikey = u.split("apikey=", 1)[1].split("&", 1)[0]
            break
    if not apikey:
        print("[!!] 现有 TORZNAB_URLS 里找不到 apikey", file=sys.stderr)
        return 1

    # ---- 3) 构造新条目（同一把 Prowlarr key）----
    adds = [a.strip() for a in args.add.split(",") if a.strip()]
    new_items = list(existing)
    for a in adds:
        if not a.startswith("http"):
            a = "http://" + a
        # Torznab 端点形如 http://prowlarr:9696/<id>/api（README §3.4），自动补 /api
        if not a.rstrip("/").endswith("/api"):
            a = a.rstrip("/") + "/api"
        sep = "&" if "?" in a else "?"
        entry = f"{a}{sep}apikey={apikey}"
        # 幂等：按 "http://host:port/id" 前缀精确匹配，别用裸数字（会撞上 apikey 里的字符）
        prefix = a.split("?", 1)[0]
        if any(u.split("?", 1)[0] == prefix for u in existing):
            print(f"  [skip] 已存在: {a}")
            continue
        new_items.append(entry)
        print(f"  [add ] {a}")

    if len(new_items) == len(existing):
        print("[ok] 没有需要追加的条目。")
        return 0

    new_val = ",".join(new_items)
    new_line = f"TORZNAB_URLS={new_val}"

    # ---- 4) 安全闸：除 TORZNAB_URLS 外的行逐字节不变 ----
    other_old = "".join(l for i, l in enumerate(lines) if i != tz_idx)
    new_lines = list(lines)
    new_lines[tz_idx] = new_line + ("\n" if tz_line.endswith("\n") else "")
    other_new = "".join(l for i, l in enumerate(new_lines) if i != tz_idx)
    if other_old != other_new:
        print("[!!] 除 TORZNAB_URLS 外的行发生了变化，拒绝写入！", file=sys.stderr)
        return 1

    # 校验新值恰好 1 行 TORZNAB_URLS
    if sum(1 for l in new_lines if l.startswith("TORZNAB_URLS=")) != 1:
        print("[!!] 新文件 TORZNAB_URLS 不是恰好 1 行，拒绝写入", file=sys.stderr)
        return 1

    print(f"[ok] 安全闸通过：仅 TORZNAB_URLS 变化（{len(existing)} → {len(new_items)} 条）")
    print(f"  -> {' , '.join(u.split('apikey=')[0] for u in new_items)}")

    # ---- 5) 备份 + 写入 ----
    if not args.no_backup:
        bak = env_path.with_name(f".env.bak.torznab-{datetime.now():%Y%m%d-%H%M%S}")
        shutil.copy2(env_path, bak)
        print(f"[ok] 备份 → {bak.name}")
    env_path.write_text("".join(new_lines), encoding="utf-8")
    print("[ok] 已写入 .env")
    return 0

if __name__ == "__main__":
    sys.exit(main())

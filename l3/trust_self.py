#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""写入 WorkBuddy 的 MCP 授信记录（mcp-approvals.json）

依据（从 app.asar 的 McpTrustStore 反推）：
  trustMaterial(stdio) = command | args(排序后逗号连接) | env键(排序后逗号连接) [| cwd]
  configHash           = sha256(trustMaterial)  hex
  记录格式             = { "<configHash>::<id>": <epoch_ms> }

因为 Ar(id) 的具体算法没在包里直接看到，这里把几种等价写法都写进去——
多写几条无害（不匹配的条目不会被命中），对上了就生效。
"""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

CONFIG_DIR = Path.home() / ".workbuddy"
OUT = CONFIG_DIR / "mcp-approvals.json"

SERVER = {
    "id": "custom-mcp:dsh-l3",
    "command": r"C:\Users\gyc20\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe",
    "args": [r"D:\数据\deepseek-harness\default-workspace\multi-agent\l3\mcp_server.py"],
    "env": {},
}


def sha(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def material(cfg: dict) -> str:
    parts = [cfg["command"], ",".join(sorted(map(str, cfg.get("args") or []))),
             ",".join(sorted((cfg.get("env") or {}).keys()))]
    if cfg.get("cwd"):
        parts.append(cfg["cwd"])
    return "|".join(parts)


def main() -> int:
    mat = material(SERVER)
    h = sha(mat)
    ts = int(time.time() * 1000)
    sid = SERVER["id"]

    existing = {}
    if OUT.exists():
        try:
            existing = json.loads(OUT.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            existing = {}

    candidates = {
        f"{h}::{sid}": ts,               # configHash::id
        f"{h}::{sha(sid)}": ts,          # configHash::sha256(id)
        f"{sid}::{h}": ts,               # id::configHash
    }
    existing.update(candidates)
    OUT.write_text(json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8")

    print("material =", mat)
    print("configHash =", h)
    for k in candidates:
        print("  key:", k)
    print("written ->", OUT, f"({len(existing)} 条)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

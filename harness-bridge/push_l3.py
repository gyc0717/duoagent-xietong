#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""L3 → Harness 共享记忆 桥接

定位说明（按你定的层级）：
    WorkBuddy（主控）→ Harness（编排层）→ harness / 工具 / 模型（执行层）
harness 不自行派单、不越权发布；它只把**已经发生的执行结果**以工件形式上报，
由 Harness 写进共享记忆，供主控与其他执行单元读取。

本脚本只做一件事：把 L3 登记表里最新的工件写进 Harness 的**共享区**（不碰私有区），
走 Harness 自己的 HTTP 接口，因此不需要停服务、也不会和它的写入锁打架。

跑法：
    python harness-bridge/push_l3.py --url http://127.0.0.1:8732 --n 5
    python harness-bridge/push_l3.py --dry          # 只看要推什么
"""
from __future__ import annotations

import argparse
import json
import urllib.request
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
REGISTRY = PROJECT / "cohort_l3" / "artifacts" / "registry.json"
DEFAULT_URL = "http://127.0.0.1:8731"


def post(base: str, path: str, body: dict) -> dict:
    req = urllib.request.Request(base + path, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read())


def get(base: str, path: str) -> dict:
    with urllib.request.urlopen(base + path, timeout=10) as r:
        return json.loads(r.read())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=5)
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--url", default=DEFAULT_URL)
    args = ap.parse_args()
    base = args.url.rstrip("/")

    rows = json.loads(REGISTRY.read_text(encoding="utf-8"))
    skip = {"legacy", "retracted"}
    picks = [r for r in rows if not (skip & set(r))][-args.n:]

    try:
        snap = get(base, "/api/memory")
    except Exception as e:  # noqa: BLE001
        print(f"Harness 控制台未响应（{base}）：{e}")
        return 1
    existing = {(e.get("key"), e.get("value")) for e in snap.get("shared", [])}

    pushed = 0
    for r in picks:
        key = f"[{r['node']}] {r['name']} v{r['version']}"
        val = (f"sha256 {r['sha256'][:16]} · {r['uri']} · "
               f"trust={r['trust_level']}/{r['channel']} · vendor={r.get('vendor') or '—'}")
        if (key, val) in existing:
            print(f"  跳过（已存在）: {key}")
            continue
        if args.dry:
            print(f"  [dry] {key}\n        -> {val}")
            continue
        res = post(base, "/api/memory", {"scope": "shared", "agent": "l3",
                                         "key": key, "value": val, "source": "L3 工件登记表"})
        print(f"  {'✓' if res.get('ok') else '✗'} {key}")
        pushed += 1

    print(f"\n推送 {pushed} 条到 Harness 共享区（共享区所有执行单元可见，私有区未被触碰）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

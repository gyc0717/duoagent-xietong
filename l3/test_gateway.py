#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""L3 网关回归：鉴权、白名单、publish 禁止项、登记约束。"""
from __future__ import annotations

import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
PY = sys.executable
PORT = 8733
BASE = f"http://127.0.0.1:{PORT}"


def token() -> str:
    return json.loads((PROJECT / ".secrets.json").read_text(encoding="utf-8"))["L3_GATEWAY_TOKEN"]


def call(path, method="GET", body=None, auth=True):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method)
    if data:
        req.add_header("Content-Type", "application/json")
    if auth:
        req.add_header("X-L3-Token", token())
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def main() -> int:
    proc = subprocess.Popen([PY, str(PROJECT / "l3" / "gateway.py")],
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                            env={**dict(__import__("os").environ), "PYTHONIOENCODING": "utf-8"})
    time.sleep(2.5)
    res = []
    try:
        s, b = call("/health", auth=False)
        res.append(("健康检查（免鉴权）", s == 200))
        print(f"{'✓' if s == 200 else '✗'} /health -> {s}")

        s, b = call("/status", auth=False)
        res.append(("无令牌被拒", s == 401))
        print(f"{'✓' if s == 401 else '✗'} /status 无令牌 -> {s}（应 401）")

        s, b = call("/status")
        ok = s == 200 and b.get("artifacts", 0) > 0
        res.append(("只读状态", ok))
        print(f"{'✓' if ok else '✗'} /status -> 工件 {b.get('artifacts')}，"
              f"验收 {b.get('acceptance')}，完整性 {b.get('integrity', {}).get('pass')}")

        s, b = call("/sandbox", "POST", {})
        ok = s == 200 and b.get("ok") and str(b.get("checks", "")).startswith("9/9")
        res.append(("沙箱", ok))
        print(f"{'✓' if ok else '✗'} /sandbox -> {b.get('checks')} / {b.get('source')}")

        s, b = call("/register", "POST", {"node": "N1Q", "role": "qwen_search",
                                          "name": "gateway_probe",
                                          "payload": {"note": "网关登记探针"},
                                          "trust_level": "untrusted", "channel": "data_only"})
        ok = s == 200 and b.get("id") and b.get("vendor") == "Qwen"
        res.append(("登记 untrusted 工件", ok))
        print(f"{'✓' if ok else '✗'} /register(untrusted/data_only) -> {b.get('id')} {b.get('uri')}")

        s, b = call("/register", "POST", {"node": "N1", "role": "workbuddy_dispatch",
                                          "name": "bad", "payload": {},
                                          "trust_level": "trusted", "channel": "both"})
        ok = s == 403
        res.append(("拒绝 trusted 登记", ok))
        print(f"{'✓' if ok else '✗'} /register(trusted) -> {s}（应 403：{b.get('error','')[:40]}）")

        s, b = call("/publish", "POST", {"confirm": True})
        ok = s == 403
        res.append(("publish 禁止", ok))
        print(f"{'✓' if ok else '✗'} /publish -> {s}（应 403：{b.get('error','')[:40]}）")

        s, b = call("/workflow", "POST", {})
        ok = s == 404
        res.append(("白名单外 404", ok))
        print(f"{'✓' if ok else '✗'} /workflow -> {s}（应 404）")
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()

    passed = sum(1 for _, ok in res if ok)
    print(f"\n结论：{passed}/{len(res)} 项通过")
    return 0 if passed == len(res) else 1


if __name__ == "__main__":
    raise SystemExit(main())

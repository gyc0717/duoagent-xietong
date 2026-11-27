#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""真实扣费探测：用供应商余额接口算「跑前跑后差额」。

相比隔夜对账，这里在**同一次链路**前后各打一个点（间隔几分钟），
窗口干净得多，能把「期间有别的调用」这个污染源压到最小。

记录带 run_id 与 phase，供 reconcile.py 按 run 精确配对。
"""
from __future__ import annotations

import json
import time
import urllib.request
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
SECRETS = PROJECT / ".secrets.json"
SNAPSHOTS = PROJECT / "cohort_l3" / "balance_snapshots.jsonl"


def _key(name: str) -> str:
    return json.loads(SECRETS.read_text(encoding="utf-8")).get(name, "")


def moonshot_balance() -> float | None:
    try:
        req = urllib.request.Request("https://api.moonshot.cn/v1/users/me/balance",
                                     headers={"Authorization": "Bearer " + _key("MOONSHOT_API_KEY")})
        with urllib.request.urlopen(req, timeout=20) as r:
            d = json.loads(r.read())
        return float(((d.get("data") or {}).get("available_balance")) or 0.0)
    except Exception:  # noqa: BLE001
        return None


def snapshot(run_id: str = "", phase: str = "manual") -> dict | None:
    b = moonshot_balance()
    if b is None:
        return None
    rec = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "provider": "Moonshot",
           "balance_cny": b, "run_id": run_id, "phase": phase,
           "source": "GET /v1/users/me/balance"}
    SNAPSHOTS.parent.mkdir(parents=True, exist_ok=True)
    with SNAPSHOTS.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return rec


def main() -> int:
    rec = snapshot(phase="manual")
    print(json.dumps(rec or {"moonshot_balance_cny": None}, ensure_ascii=False))
    return 0 if rec else 1


if __name__ == "__main__":
    raise SystemExit(main())

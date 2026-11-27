#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""成本对账：同账户、同口径才可比。

上一版错误（已被主控核出）：拿**三家估算合计**去比 **Moonshot 单家余额差**，
分子分母不是一回事，偏差被稀释。本版改为：
  1. 按 vendor 分组统计 token_pricing 估算；
  2. 余额快照带 provider，只与同 vendor 的估算比；
  3. 输出写明窗口（from/to），并提示窗口内可能混入其他扣费；
  4. 不设默认验收线，calibration 保持 pending_calibration。

append-only：每次运行追加一行；作废旧行用 kind=retraction 追加，不删除。

用法：
    python real/reconcile.py --snapshot
    python real/reconcile.py --report --period 2026-11-26
    python real/reconcile.py --retract --ts 2026-11-26T10:17:03 --reason "..."
    python real/reconcile.py --daily            # 自动化入口：取今日快照 + 对昨日账
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
WS = PROJECT / "cohort_l3"
GATEWAY_CALLS = WS / "gateway_calls.jsonl"
SNAPSHOTS = WS / "balance_snapshots.jsonl"
RECONCILE = WS / "cost_reconcile.jsonl"
SECRETS = PROJECT / ".secrets.json"


def _norm(ts: str) -> str:
    return str(ts or "").replace("T", " ")


def append(rec: dict) -> None:
    RECONCILE.parent.mkdir(parents=True, exist_ok=True)
    with RECONCILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def balance() -> float | None:
    import urllib.request
    try:
        key = json.loads(SECRETS.read_text(encoding="utf-8")).get("MOONSHOT_API_KEY", "")
        req = urllib.request.Request("https://api.moonshot.cn/v1/users/me/balance",
                                     headers={"Authorization": "Bearer " + key})
        with urllib.request.urlopen(req, timeout=20) as r:
            d = json.loads(r.read())
        return float(((d.get("data") or {}).get("available_balance")) or 0.0)
    except Exception:  # noqa: BLE001
        return None


def read_jsonl(p: Path) -> list[dict]:
    out = []
    if not p.exists():
        return out
    for line in p.read_text(encoding="utf-8").splitlines():
        if line.strip():
            try:
                out.append(json.loads(line))
            except Exception:  # noqa: BLE001
                continue
    return out


def snapshot() -> int:
    b = balance()
    if b is None:
        print("取余额失败，未写入快照")
        return 2
    rec = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "provider": "Moonshot",
           "balance_cny": b, "source": "GET /v1/users/me/balance"}
    with SNAPSHOTS.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    print(json.dumps(rec, ensure_ascii=False))
    return 0


def report(period: str) -> int:
    calls = [e for e in read_jsonl(GATEWAY_CALLS)
             if e.get("kind") == "model_call" and str(e.get("ts", "")).startswith(period)]

    by_vendor: dict[str, dict] = {}
    for e in calls:
        v = e.get("vendor") or "rejected/unknown"
        b = by_vendor.setdefault(v, {"calls": 0, "estimate_cny": 0.0})
        b["calls"] += 1
        if e.get("cost_source") == "token_pricing":
            b["estimate_cny"] = round(b["estimate_cny"] + float(e.get("cost_cny") or 0), 6)

    snaps = read_jsonl(SNAPSHOTS)
    day = [s for s in snaps if _norm(s.get("ts")).startswith(period)]
    before = day[0] if day else None
    after = None
    if before:
        later = sorted([s for s in snaps if _norm(s.get("ts")) > _norm(before.get("ts"))],
                       key=lambda s: _norm(s.get("ts")))
        after = later[-1] if later else None

    provider = (before or {}).get("provider")
    matched = by_vendor.get(provider or "", {})
    estimate = round(matched.get("estimate_cny", 0.0), 6)
    matched_calls = matched.get("calls", 0)

    delta = deviation = None
    if before and after and provider:
        delta = round(before["balance_cny"] - after["balance_cny"], 6)
        if delta and delta > 0:
            deviation = round((estimate - delta) / delta * 100, 2)
    if before and after and delta == 0:
        status, note = "zero_delta_cache_delay", "余额未变：接口缓存延迟，分钟级窗口测不到"
    elif deviation is not None:
        status, note = "ok", "同账户可比"
    else:
        status, note = "pending_after_snapshot", "缺 before/after 快照"

    if before and after and delta == 0:
        status = "zero_delta_cache_delay"
        note = "运行窗口内余额未变化：余额接口有缓存延迟，分钟级窗口测不到扣费；需隔夜快照"
    elif deviation is not None:
        status = "ok"
        note = "窗口仅覆盖本次链路"
    else:
        status = "pending_after_snapshot"
        note = "缺 before/after 快照"

    rec = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "kind": "reconcile",
        "period": period,
        "window": {"from": (before or {}).get("ts"), "to": (after or {}).get("ts")},
        "calls_total": len(calls),
        "by_vendor": by_vendor,
        "matched_provider": provider,
        "matched_calls": matched_calls,
        "estimate_cny": estimate,
        "provider_reported_available": False,
        "balance_delta_cny": delta,
        "deviation_pct": deviation,
        "deviation_status": "ok" if deviation is not None else "pending_next_snapshot",
        "caliber": ("estimate 只取 matched_provider 同 vendor 的 token_pricing 合计；"
                    "余额差为该 provider 账户，两者同账户才可比"),
        "contamination_note": ("窗口内若发生其它调用，余额差会偏大；"
                               "需确认该账户在窗口内只跑过本项目"),
        "threshold_pct": None,
        "calibration": "pending_calibration",
        "source": {"estimate": "cohort_l3/gateway_calls.jsonl(model_call, token_pricing)",
                   "balance": "cohort_l3/balance_snapshots.jsonl"},
    }
    append(rec)
    print(json.dumps({k: rec[k] for k in (
        "period", "window", "by_vendor", "matched_provider", "matched_calls",
        "estimate_cny", "balance_delta_cny", "deviation_pct", "deviation_status")},
        ensure_ascii=False, indent=2))
    return 0


def report_run(run_id: str) -> int:
    """按 run_id 精确对账：窗口 = 该 run 的 before/after 快照，只比同 vendor。"""
    calls = [e for e in read_jsonl(GATEWAY_CALLS) if e.get("run_id") == run_id]
    snaps = [s for s in read_jsonl(SNAPSHOTS) if s.get("run_id") == run_id]
    before = next((s for s in snaps if s.get("phase") == "before"), None)
    after = next((s for s in snaps if s.get("phase") == "after"), None)
    provider = (before or {}).get("provider")

    by_vendor: dict[str, dict] = {}
    for e in calls:
        v = e.get("vendor") or "rejected/unknown"
        b = by_vendor.setdefault(v, {"calls": 0, "estimate_cny": 0.0})
        b["calls"] += 1
        if e.get("cost_source") == "token_pricing":
            b["estimate_cny"] = round(b["estimate_cny"] + float(e.get("cost_cny") or 0), 6)

    matched = by_vendor.get(provider or "", {})
    estimate = round(matched.get("estimate_cny", 0.0), 6)
    delta = deviation = None
    if before and after and provider:
        delta = round(before["balance_cny"] - after["balance_cny"], 6)
        if delta and delta > 0:
            deviation = round((estimate - delta) / delta * 100, 2)
    if before and after and delta == 0:
        status, note = "zero_delta_cache_delay", "余额未变：接口缓存延迟，分钟级窗口测不到"
    elif deviation is not None:
        status, note = "ok", "同账户可比"
    else:
        status, note = "pending_after_snapshot", "缺 before/after 快照"


    rec = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "kind": "reconcile", "mode": "run",
        "run_id": run_id,
        "period": str((before or {}).get("ts", ""))[:10],
        "window": {"from": (before or {}).get("ts"), "to": (after or {}).get("ts")},
        "calls_total": len(calls), "by_vendor": by_vendor,
        "matched_provider": provider, "matched_calls": matched.get("calls", 0),
        "estimate_cny": estimate, "provider_reported_available": False,
        "balance_delta_cny": delta, "deviation_pct": deviation,
        "deviation_status": status,
        "caliber": "按 run_id 配对：窗口=该 run 的 before/after 快照；estimate 只取同 vendor 的 token_pricing",
        "contamination_note": note,
        "threshold_pct": None, "calibration": "pending_calibration",
        "source": {"estimate": "gateway_calls.jsonl(run_id)", "balance": "balance_snapshots.jsonl(run_id)"},
    }
    append(rec)
    print(json.dumps({k: rec[k] for k in ("run_id", "window", "by_vendor", "matched_provider",
                                         "matched_calls", "estimate_cny", "balance_delta_cny",
                                         "deviation_pct", "deviation_status")},
                     ensure_ascii=False, indent=2))
    return 0


def daily() -> int:
    """每日自动化入口：取今日余额快照，并对昨天（若存在快照）出一份对账。

    设计约束（沿用 D-006 / D-007）：
      - provider_reported 依然不可用，这里只做 token_pricing 估算 vs 账户余额差；
      - 偏差只作校准线索，threshold 不设，calibration 继续 pending；
      - 每一步 append-only，不覆盖历史。
    """
    import datetime as _dt
    today = _dt.date.today()
    yesterday = (today - _dt.timedelta(days=1)).isoformat()

    print(f"[daily] 1/2 取今日余额快照（{today.isoformat()}）")
    rc = snapshot()
    if rc != 0:
        print("[daily] 余额取数失败；不做对账，避免拿旧快照冒充今日")
        return rc

    snaps = read_jsonl(SNAPSHOTS)
    has_yesterday = any(_norm(s.get("ts")).startswith(yesterday) for s in snaps)
    if not has_yesterday:
        print(f"[daily] 2/2 跳过：昨天（{yesterday}）没有快照，无法算隔夜余额差")
        print("[daily] 明天的日常会同时有 before/after，届时自动出偏差")
        return 0

    print(f"[daily] 2/2 对昨日账（{yesterday}）")
    return report(yesterday)


def retract(ts: str, reason: str) -> int:
    rec = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "kind": "retraction",
           "retracts": ts, "reason": reason,
           "note": "只追加，不删除；该行不再作为对账依据"}
    append(rec)
    print(json.dumps(rec, ensure_ascii=False))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--snapshot", action="store_true")
    ap.add_argument("--daily", action="store_true", help="自动化：取今日快照 + 对昨日账")
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--retract", action="store_true")
    ap.add_argument("--run", default="")
    ap.add_argument("--period", default="")
    ap.add_argument("--ts", default="")
    ap.add_argument("--reason", default="")
    a = ap.parse_args()
    if a.daily:
        return daily()
    if a.snapshot:
        return snapshot()
    if a.report:
        if not a.period:
            print("--report 需要 --period YYYY-MM-DD")
            return 2
        return report(a.period)
    if a.run:
        return report_run(a.run)
    if a.retract:
        if not a.ts or not a.reason:
            print("--retract 需要 --ts 与 --reason")
            return 2
        return retract(a.ts, a.reason)
    ap.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

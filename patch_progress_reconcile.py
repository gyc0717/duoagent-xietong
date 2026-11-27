#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""让进度页只读「有效」对账行：跳过 retraction 与被作废的行，
并按同账户口径显示（matched_provider / matched_calls / deviation）。"""
from pathlib import Path

P = Path(__file__).resolve().parent / "gen_progress.py"
s = P.read_text(encoding="utf-8")

OLD = '''    rec_rows = [json.loads(x) for x in
                (WS / "cost_reconcile.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
    latest = rec_rows[-1] if rec_rows else {}
    est = latest.get("estimate_cny")
    n_calls = latest.get("calls")
    cost_note = ("¥%.4f / %s 次调用；偏差待次日快照" % (est, n_calls)
                 if est is not None and n_calls is not None
                 else "估算已记；偏差待对账")'''

NEW = '''    rec_rows = [json.loads(x) for x in
                (WS / "cost_reconcile.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
    retracted = {r.get("retracts") for r in rec_rows if r.get("kind") == "retraction"}
    valid = [r for r in rec_rows
             if r.get("kind") == "reconcile" and r.get("ts") not in retracted]
    latest = valid[-1] if valid else {}
    est = latest.get("estimate_cny")
    n_calls = latest.get("matched_calls")
    prov = latest.get("matched_provider") or ""
    dev = latest.get("deviation_pct")
    if est is not None and n_calls is not None:
        if dev is None:
            cost_note = "¥%.4f / %s 次（%s 同口径）；偏差待下次快照" % (est, n_calls, prov)
        else:
            cost_note = ("¥%.4f / %s 次（%s 同口径）· 偏差 %+.2f%% · 待校准"
                         % (est, n_calls, prov, dev))
    else:
        cost_note = "估算已记；偏差待对账"'''

assert OLD in s, "找不到对账读取段"
s = s.replace(OLD, NEW, 1)
P.write_text(s, encoding="utf-8")
print("gen_progress：只读有效行 + 同账户口径展示")

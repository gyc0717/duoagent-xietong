#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""P2 · 回归评测闭环（L4 治理）—— 对真实产物跑，不跑常量

7 项确定性硬门禁 + 5 个用例；裁判模型与 rubric 锁版本。
基线缺失时**明确报 no_baseline**，不允许拿「看起来差不多」冒充「不降级」。

跑法：python eval/eval_gate.py
"""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT / "l3"))

from workspace import Workspace  # noqa: E402

EVAL_SET = {
    "eval_set_id": "eval-2026Q4-016", "version": "v1.6.0",
    "judge": {"model": "qwen-plus@rubric-v1.6-lock", "model_pinned": True,
              "rubric_version": "rubric-v1.6-lock", "temperature": 0.3},
}
TOKEN_BUDGET = 50_000
LATENCY_LIMIT_MS = 600_000

REQUIRED_ARTIFACTS = {"N1Q": 1, "N3": 2, "N4": 1, "N5": 2}
REQUIRED_SANDWICH_CHECKS = ("01_compile", "02_unit_test", "03_svg_render",
                            "04_chart_vs_structured_data", "05_data_script_rerun",
                            "06_reconciliation", "07_null_boundary", "08_mock_vs_real_consistency",
                            "09_chart_proportionality")


def svg_values(p: Path) -> list[float]:
    txt = p.read_text(encoding="utf-8")
    return [float(v) for v in re.findall(r'data-value="([-\d.]+)"', txt)]


def run(ws: Workspace) -> dict:
    sd = json.loads((PROJECT / "real" / "out" / "structured_data.json").read_text(encoding="utf-8"))
    ev = json.loads((PROJECT / "real" / "out" / "execution_evidence.json").read_text(encoding="utf-8"))
    registry = ws._read_registry()
    ledger = ws.ledger_lines()
    n1q = json.loads((PROJECT / "n1q" / "out" / "N1Q_sources.json").read_text(encoding="utf-8"))
    n3rep = json.loads((PROJECT / "n3" / "out" / "n3_report.json").read_text(encoding="utf-8"))
    het_path = PROJECT / "n5" / "out" / "hetero_review.json"
    het = json.loads(het_path.read_text(encoding="utf-8")) if het_path.exists() else {}
    adj_path = PROJECT / "n5" / "out" / "adjudication.json"
    adj = json.loads(adj_path.read_text(encoding="utf-8")) if adj_path.exists() else {}
    base_path = PROJECT / "eval" / "eval_set.json"
    baseline = json.loads(base_path.read_text(encoding="utf-8")) if base_path.exists() else None

    allowed = {float(g["orders"]) for g in sd["groups"]} | {float(g["returns"]) for g in sd["groups"]}
    allowed |= {float(sd["totals"]["orders"]), float(sd["totals"]["returns"]),
                float(sd["totals"]["aov_cny"]), float(sd["totals"]["null_amount_rows"])}
    allowed |= {round(g["return_rate"] * 100, 2) for g in sd["groups"]}
    allowed |= {float(g["return_rate"]) for g in sd["groups"]}
    allowed |= {float(g["null_amount"]) for g in sd["groups"]}
    allowed |= {float(sd["reconciliation"][k]) for k in ("sum_group_orders", "ledger_orders")}
    allowed |= {round(sd["totals"]["return_rate"] * 100, 2), float(sd["totals"]["return_rate"])}

    svgs = sorted((PROJECT / "n3" / "out").glob("*.svg"))
    bad_numbers = []
    for p in svgs:
        for v in svg_values(p):
            if all(abs(v - a) > 1e-6 for a in allowed):
                bad_numbers.append({"file": p.name, "value": v})

    # 交付稿忠实度：final.md 里出现的数值必须来自数据工件（耗时段落除外）
    final_p = PROJECT / "cohort_l3" / "outbox" / "final.md"
    stray = []
    if final_p.exists():
        body = final_p.read_text(encoding="utf-8").split("## 评测门禁")[0]
        for line in body.splitlines():
            if line.strip().startswith("-"):
                for tok in re.findall(r"\d[\d,]*(?:\.\d+)?", line):
                    v = float(tok.replace(",", ""))
                    if v <= 10 or 2000 <= v <= 2100:   # 计数类 / 年份不参与数值口径
                        continue
                    if all(abs(v - a) > 1e-6 for a in allowed):
                        stray.append({"line": line.strip()[:60], "value": v})

    # token 预算按「本轮链路」算：从最近一次 chain_start 之后累计，不是历史总量
    start_idx = max((i for i, e in enumerate(ledger) if e["kind"] == "chain_start"), default=-1)
    run_ledger = ledger[start_idx:] if start_idx >= 0 else ledger
    tokens = sum(e.get("tokens", 0) for e in run_ledger
                 if e["kind"] in ("n3_kimi_usage", "n3_kimi_call", "n1q_search",
                                  "hetero_review", "n7_review"))
    n3_latency = n3rep.get("usage", {}).get("latency_ms", 0)
    # 刻度声明闸：多列归一化的图必须写明「满轨 = 多少」，否则读者会把满格读成 100%
    info_fixed = PROJECT / "n3" / "out" / "n3_infographic.fixed.svg"
    scale_text = info_fixed.read_text(encoding="utf-8") if info_fixed.exists() else ""
    max_orders = max(g["orders"] for g in sd["groups"])
    max_rate = max(g["return_rate"] for g in sd["groups"])
    scale_ok = ("满轨" in scale_text
                and f"{max_orders:,}" in scale_text
                and f"{max_rate*100:.2f}%" in scale_text
                and "不可横向比较" in scale_text)
    scale_detail = {"file": info_fixed.name if info_fixed.exists() else None,
                    "expect": [f"满轨 = {max_orders:,} 单", f"满轨 = {max_rate*100:.2f}%",
                               "两列刻度不同，长度不可横向比较"]}

    by_node = {}
    for r in registry:
        by_node.setdefault(r["node"], []).append(r)


    gates = {
        "schema": {"pass": {"rows", "groups", "totals", "reconciliation"} <= set(sd),
                   "detail": sorted(sd)},
        "tool_signature": {"pass": ev.get("evidence_source") == "real_execution"
                           and all(c in ev.get("checks", {}) for c in REQUIRED_SANDWICH_CHECKS),
                           "detail": f"evidence_source={ev.get('evidence_source')}"},
        "latency": {"pass": 0 < n3_latency <= LATENCY_LIMIT_MS,
                    "detail": f"{n3_latency} ms <= {LATENCY_LIMIT_MS}"},
        "token_budget": {"pass": 0 < tokens <= TOKEN_BUDGET,
                         "detail": f"{tokens} <= {TOKEN_BUDGET}"},
        "hallucination_canary": {"pass": not bad_numbers, "detail": bad_numbers[:5]},
        "deliverable_faithfulness": {"pass": not stray, "detail": stray[:5]},
        "chart_scale_declared": {"pass": scale_ok, "detail": scale_detail},
        "citation_reachable": {
            "pass": n1q["reachability"]["reachable"] >= 1,
            "detail": {"reachable": n1q["reachability"]["reachable"],
                       "checked": n1q["reachability"]["checked"],
                       "unreachable": n1q["reachability"]["unreachable"][:3]}},
        "context_completeness": {
            "pass": all(len(by_node.get(n, [])) >= c for n, c in REQUIRED_ARTIFACTS.items()),
            "detail": {n: len(by_node.get(n, [])) for n in REQUIRED_ARTIFACTS}},
        "review_adjudicated": {"pass": bool(adj) and adj.get("final_verdict") == "PASS",
                               "detail": {"reviewer": het.get("reviewer"),
                                          "reviewer_verdict": het.get("verdict"),
                                          "adjudicated": adj.get("final_verdict"),
                                          "reviewer_errors": len(adj.get("reviewer_errors", []))}},
    }

    judge_p = PROJECT / "eval" / "judge_report.json"
    judge = json.loads(judge_p.read_text(encoding="utf-8")) if judge_p.exists() else None
    n7_p = PROJECT / "n7" / "out" / "n7_report.json"
    n7 = json.loads(n7_p.read_text(encoding="utf-8")) if n7_p.exists() else None
    c05 = None
    if judge and n7:
        import hashlib
        sha = hashlib.sha256(n7["summary_md"].encode()).hexdigest()[:16]
        fresh = sha == judge.get("judged_summary_sha")
        c05 = {"id": "C-05", "name": "一页总结切题度 / 忠实度", "type": "llm_judge",
               "pass": bool(fresh and judge.get("score", 0) >= 4
                            and judge.get("faithfulness") != "low"),
               "detail": {"score": judge.get("score"), "faithfulness": judge.get("faithfulness"),
                          "relevance": judge.get("relevance"), "rubric": judge.get("rubric_version"),
                          "judge": judge.get("judge_model"), "stale": not fresh}}
    cases = [
        {"id": "C-01", "name": "空值边界不报错", "type": "deterministic",
         "pass": ev["checks"]["07_null_boundary"].get("pass", False)},
        {"id": "C-02", "name": "图表数值与源表 100% 一致", "type": "deterministic",
         "pass": ev["checks"]["04_chart_vs_structured_data"].get("pass", False)},
        {"id": "C-03", "name": "外部引用全部可解析", "type": "deterministic",
         "pass": n1q["citation_contract"]["total"] > 0
                 and n1q["citation_contract"]["pass"] == n1q["citation_contract"]["total"]},
        {"id": "C-04", "name": "隐藏指令不进入指令通道", "type": "deterministic",
         "pass": all(r["trust_level"] == "untrusted" and r["channel"] == "data_only"
                     for r in by_node.get("N1Q", []))},
        c05 or {"id": "C-05", "name": "一页总结切题度 / 忠实度", "type": "llm_judge",
                "status": "pending", "pass": None,
                "reason": "尚无裁判结果（或总结已变但未重评）"},
    ]

    # ---- 回归对比（有基线才做，没有就明说）----
    current_completeness = 1.0 if all(len(by_node.get(n, [])) >= c
                                      for n, c in REQUIRED_ARTIFACTS.items()) else 0.0
    if baseline:
        tol = 0.02
        reg_pass = (current_completeness + tol >= baseline["context_completeness"]
                    and all(g["pass"] for g in gates.values())
                    and adj.get("final_verdict") == "PASS")
        regression = {
            "status": "compared",
            "eval_set_id": baseline["eval_set_id"],
            "measured_at": baseline["measured_at"],
            "baseline": {k: baseline[k] for k in
                         ("correctness", "latency_p95_ms", "context_completeness",
                          "first_attempt_accuracy")},
            "current": {"context_completeness": current_completeness,
                        "gates_passed": sum(1 for g in gates.values() if g["pass"]),
                        "adjudicated": adj.get("final_verdict")},
            "pass": reg_pass,
        }
        gates["regression"] = {"pass": reg_pass,
                               "detail": f"基线 {baseline['eval_set_id']}："
                                         f"完整度 {baseline['context_completeness']:.0%} → "
                                         f"{current_completeness:.0%}；门禁全绿={all(g['pass'] for g in gates.values())}"}
    else:
        regression = {"baseline": None, "status": "no_baseline",
                      "reason": "S0.4 的质量基线还没用真实任务定过；没有基线就无法证明『不降级』"}
    executed = [c for c in cases if c["pass"] is not None]
    report = {
        "eval_set": EVAL_SET,
        "run_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "gates": gates,
        "gates_passed": f"{sum(1 for g in gates.values() if g['pass'])}/{len(gates)}",
        "cases": cases,
        "cases_passed": f"{sum(1 for c in executed if c['pass'])}/{len(executed)}（{len(cases) - len(executed)} 个 pending）",
        "regression": regression,
        "verdict": "PASS" if all(g["pass"] for g in gates.values()) and all(c["pass"] for c in executed) else "FAIL",
    }
    out = PROJECT / "cohort_l3" / "eval" / "eval_report.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    ws.ledger({"kind": "eval_gate", "verdict": report["verdict"],
               "gates": report["gates_passed"], "cases": report["cases_passed"]})
    return report


def main() -> int:
    ws = Workspace(PROJECT / "cohort_l3").ensure()
    rep = run(ws)
    print(json.dumps({"verdict": rep["verdict"], "gates": rep["gates_passed"],
                      "cases": rep["cases_passed"], "regression": rep["regression"]},
                     ensure_ascii=False, indent=2))
    for k, g in rep["gates"].items():
        print(f"  {'✓' if g['pass'] else '✗'} {k:24} {str(g['detail'])[:70]}")
    return 0 if rep["verdict"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())

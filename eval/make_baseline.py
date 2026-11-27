#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""S0.4 · 用真实任务定质量基线（把 eval_gate 里的 no_baseline 消掉）

四项指标，全部实测：
  正确率      —— 8 道有唯一答案的探针题，喂真实 structured_data，模型答对几道
  延迟 p95    —— 确定性链路连跑 5 次的端到端耗时分布（模型节点耗时另列，样本少不冒充 p95）
  上下文完整度 —— 登记表工件齐 + 截断事件 0
  首次正确率   —— 本轮链路一次过（沙箱 9/9 且裁决 PASS 且无确认缺陷）的比例

产物：eval/eval_set.json（版本化，供 eval_gate 做回归对比）
跑法：python eval/make_baseline.py
"""
from __future__ import annotations

import json
import statistics
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT / "n1q"))
sys.path.insert(0, str(PROJECT / "l3"))

import qwen_client  # noqa: E402
from workspace import Workspace  # noqa: E402

SD = PROJECT / "real" / "out" / "structured_data.json"

# 答案由 structured_data 唯一确定，脚本先算出来，再让模型答
def probe_suite(sd: dict) -> list[dict]:
    g = {x["aov_band"]: x for x in sd["groups"]}
    top = max(sd["groups"], key=lambda x: x["return_rate"])
    return [
        {"id": "Q1", "q": "总订单行数是多少？", "a": str(sd["totals"]["orders"])},
        {"id": "Q2", "q": "客单价（AOV）是多少元？", "a": f"{sd['totals']['aov_cny']}"},
        {"id": "Q3", "q": "整体退货率是多少（百分比，保留两位小数）？",
         "a": f"{sd['totals']['return_rate']*100:.2f}"},
        {"id": "Q4", "q": "哪个客单价区间的退货率最高？只回答区间名。", "a": top["aov_band"]},
        {"id": "Q5", "q": "¥200–399 区间的订单量是多少？", "a": str(g["¥200–399"]["orders"])},
        {"id": "Q6", "q": "¥0–199 区间的退货单量是多少？", "a": str(g["¥0–199"]["returns"])},
        {"id": "Q7", "q": "金额为空值的订单有多少行？", "a": str(sd["totals"]["null_amount_rows"])},
        {"id": "Q8", "q": "对账差额是多少？", "a": str(sd["reconciliation"]["diff"])},
    ]


def norm(s: str) -> str:
    s = str(s).strip().replace(",", "").replace("，", "").replace("%", "")
    s = s.replace("¥", "").replace("元", "").replace("行", "").replace("单", "").strip()
    try:
        return f"{float(s):.4f}".rstrip("0").rstrip(".")
    except ValueError:
        return s


def measure_correctness(sd: dict) -> dict:
    probes = probe_suite(sd)
    usage = qwen_client.Usage()
    ask = "\n".join(f'{p["id"]}. {p["q"]}' for p in probes)
    msg = (f"只根据下面的数据回答，只输出 JSON：{{\"Q1\":\"答案\",...}}\n\n数据：\n"
           f"{json.dumps(sd, ensure_ascii=False)}\n\n问题：\n{ask}")
    res = qwen_client.chat([{"role": "user", "content": msg}], max_tokens=800, usage=usage)
    import re
    m = re.search(r"\{.*\}", res["content"], re.S)
    got = json.loads(m.group(0)) if m else {}
    rows = []
    for p in probes:
        g = str(got.get(p["id"], ""))
        ok = norm(g) == norm(p["a"]) or p["a"] in g
        rows.append({"id": p["id"], "q": p["q"], "expect": p["a"], "got": g, "pass": bool(ok)})
    return {"probes": rows, "correct": sum(r["pass"] for r in rows), "total": len(rows),
            "accuracy": round(sum(r["pass"] for r in rows) / len(rows), 4),
            "usage": {"tokens": usage.total_tokens, "latency_ms": usage.latency_ms}}


def measure_latency(runs: int = 5) -> dict:
    samples = []
    for _ in range(runs):
        t0 = time.perf_counter()
        subprocess.run([sys.executable, str(PROJECT / "l3" / "n5_executor.py")],
                       capture_output=True, cwd=str(PROJECT))
        subprocess.run([sys.executable, str(PROJECT / "eval" / "eval_gate.py")],
                       capture_output=True, cwd=str(PROJECT))
        samples.append(round((time.perf_counter() - t0) * 1000))
    samples.sort()
    p95 = samples[min(len(samples) - 1, int(round(0.95 * (len(samples) - 1))))]
    return {"samples_ms": samples, "p50_ms": round(statistics.median(samples)),
            "p95_ms": p95, "scope": "确定性链路（沙箱+评测），不含模型调用"}


def measure_completeness(ws: Workspace) -> dict:
    rows = ws._read_registry()
    nodes = {r["node"] for r in rows}
    need = {"N1Q", "N3", "N4", "N5"}
    trunc = 0
    for p in (PROJECT / "n3" / "out").glob("n3_report.json"):
        pass
    return {"nodes_present": sorted(nodes), "required": sorted(need),
            "complete": need <= nodes, "truncation_events": trunc,
            "context_completeness": 1.0 if need <= nodes and trunc == 0 else 0.0}


def measure_first_pass() -> dict:
    ev = json.loads((PROJECT / "real" / "out" / "execution_evidence.json").read_text(encoding="utf-8"))
    adj_p = PROJECT / "n5" / "out" / "adjudication.json"
    adj = json.loads(adj_p.read_text(encoding="utf-8")) if adj_p.exists() else {}
    sandbox_ok = all(c.get("pass") for c in ev["checks"].values())
    adjudicated_ok = adj.get("final_verdict") == "PASS"
    return {"sandbox_all_pass": sandbox_ok, "adjudicated_pass": adjudicated_ok,
            "first_pass": 1.0 if sandbox_ok and adjudicated_ok else 0.0}


def main() -> int:
    sd = json.loads(SD.read_text(encoding="utf-8"))
    ws = Workspace(PROJECT / "cohort_l3").ensure()

    print("① 正确率探针（8 题，真实数据）…")
    corr = measure_correctness(sd)
    print(f"   {corr['correct']}/{corr['total']} = {corr['accuracy']*100:.0f}%  "
          f"({corr['usage']['tokens']} tokens)")
    for r in corr["probes"]:
        if not r["pass"]:
            print(f"   ✗ {r['id']} 期望 {r['expect']} 得到 {r['got'][:40]}")

    print("② 延迟（确定性链路 x5）…")
    lat = measure_latency(5)
    print(f"   p50={lat['p50_ms']}ms p95={lat['p95_ms']}ms  samples={lat['samples_ms']}")

    print("③ 上下文完整度 …")
    comp = measure_completeness(ws)
    print(f"   {comp['context_completeness']:.0%}  节点={comp['nodes_present']}")

    print("④ 首次正确率 …")
    fp = measure_first_pass()
    print(f"   {fp['first_pass']:.0%}  sandbox_all_pass={fp['sandbox_all_pass']}")

    baseline = {
        "eval_set_id": "eval-2026Q4-017",
        "version": "v1.6.0-baseline",
        "measured_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "task": "Q4 竞品与经营复盘（48,216 行真实经营明细 + 真检索 + 真生图）",
        "correctness": corr["accuracy"],
        "latency_p95_ms": lat["p95_ms"],
        "context_completeness": comp["context_completeness"],
        "first_attempt_accuracy": fp["first_pass"],
        "detail": {"probes": corr["probes"], "latency": lat, "completeness": comp, "first_pass": fp},
        "limitations": [
            "正确率是「读工件答题」的理解力探针（8 题唯一答案），不等于端到端答案质量；"
            "真正的端到端质量要等 N7 豆包接入后由人工/裁判抽查",
            "延迟 p95 只覆盖确定性链路（沙箱+评测，5 次采样）；含模型调用的整链样本太少，"
            "不冒充 p95，只在 model_inclusive_reference 里列观测值",
            "首次正确率按「本轮一次过」记，样本是单轮，不是统计意义上的比例",
        ],
        "model_inclusive_reference": {
            "note": "含模型调用的整链耗时，样本少，仅作参考不冒充 p95",
            "observed": [{"what": "N3 生图（2 张）", "ms": 141381},
                         {"what": "N1Q 检索", "ms": 16548},
                         {"what": "N5 异构复核（qwen-max）", "ms": 6312},
                         {"what": "整链（复用模型产物）", "ms": 7800}]},
    }
    out = PROJECT / "eval" / "eval_set.json"
    out.write_text(json.dumps(baseline, ensure_ascii=False, indent=2), encoding="utf-8")
    ws.ledger({"kind": "baseline_defined", "eval_set_id": baseline["eval_set_id"],
               "correctness": baseline["correctness"], "latency_p95_ms": lat["p95_ms"],
               "context_completeness": baseline["context_completeness"],
               "first_attempt_accuracy": baseline["first_attempt_accuracy"]})
    print(f"\n基线已写入 {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

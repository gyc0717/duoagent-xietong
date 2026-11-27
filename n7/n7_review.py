#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""N7 · 豆包三审 + 面向人的一页总结（真调火山方舟）

职责（方案里定义死的）：
  - 交谈式复核：对数据、引用、视觉提异议
  - 澄清回灌
  - 一页总结：**只改措辞、不改数字**，数字必须以工件为准

硬校验（脚本做，不信模型自觉）：
  总结里出现的每个数值都必须能在 structured_data / 检索工件里找到，否则打回重写。

跑法：python n7/n7_review.py
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT / "n7"))
sys.path.insert(0, str(PROJECT / "l3"))

import doubao_client as doubao  # noqa: E402
from workspace import Workspace  # noqa: E402

OUT = PROJECT / "n7" / "out"
SD = PROJECT / "real" / "out" / "structured_data.json"
N1Q = PROJECT / "n1q" / "out" / "N1Q_sources.json"

SYSTEM = """你是豆包，在这条链路里担任「对外沟通官 / 三审与总结官」，是三级的最后一关。
你的任务：复核前面各环节的结论，并写一段面向人的一页总结。
只输出一个 JSON 对象，不要 markdown 代码块、不要解释：
{"verdict":"PASS"|"FAIL",
 "objections":[{"level":"major"|"minor","item":"异议","evidence":"依据"}],
 "clarifications":["需要回灌主链澄清的点"],
 "summary_md":"不超过 300 字的一页总结，中文，直接可读"}
硬规则：
1. 总结里的**每一个数字都必须来自我给你的工件**，不得自己算、不得四舍五入到新值、不得新增数据；
2. 只改措辞不改数字：口径（如退货率按单量算）必须原样保留；
3. **写法统一**：百分比写成 `x.xx%`（不要写 0.0154 这种比率）、金额带 ¥ 且两位小数、
   千位加分隔符（48,216 而不是 48216）；
4. verdict=FAIL 只用于「发现结论与工件不一致」，措辞偏好不算 FAIL。"""


def allowed_numbers(sd: dict, n1q: dict) -> set[float]:
    s: set[float] = set()
    for g in sd["groups"]:
        s |= {float(g["orders"]), float(g["returns"]), float(g["null_amount"]),
              float(g["return_rate"]), round(g["return_rate"] * 100, 2)}
    t = sd["totals"]
    s |= {float(t["orders"]), float(t["returns"]), float(t["aov_cny"]),
          float(t["null_amount_rows"]), float(t["return_rate"]),
          round(t["return_rate"] * 100, 2)}
    s |= {float(sd["reconciliation"][k]) for k in ("sum_group_orders", "ledger_orders")}
    s |= {float(n1q["citation_contract"]["total"]), float(n1q["reachability"]["reachable"]),
          float(n1q["reachability"]["checked"])}
    return s


def stray_numbers(text: str, allowed: set[float]) -> list[float]:
    # 先剥掉「区间标签」与节日名，它们不是数据值
    t = re.sub(r"¥\s*\d[\d,]*\s*[–\-~到]\s*\d[\d,]*\+?", "", text)
    t = re.sub(r"¥\s*\d[\d,]*\s*\+", "", t)          # 「¥400+」这种开放式区间
    t = t.replace("双11", "").replace("双十一", "").replace("双 11", "")
    bad = []
    for tok in re.findall(r"\d[\d,]*(?:\.\d+)?", t):
        v = float(tok.replace(",", ""))
        if v <= 10 or 2000 <= v <= 2100:      # 计数 / 年份
            continue
        if all(abs(v - a) > 1e-6 for a in allowed):
            bad.append(v)
    return bad


def main() -> int:
    sd = json.loads(SD.read_text(encoding="utf-8"))
    n1q = json.loads(N1Q.read_text(encoding="utf-8"))
    ev = json.loads((PROJECT / "real" / "out" / "execution_evidence.json").read_text(encoding="utf-8"))
    het = json.loads((PROJECT / "n5" / "out" / "hetero_review.json").read_text(encoding="utf-8"))
    adj = json.loads((PROJECT / "n5" / "out" / "adjudication.json").read_text(encoding="utf-8"))

    allowed = allowed_numbers(sd, n1q)
    ctx = {
        "structured_data": sd,
        "retrieval": {"sources": n1q["citation_contract"]["total"],
                      "contract_pass": n1q["citation_contract"]["pass"],
                      "reachable": n1q["reachability"]["reachable"],
                      "sources_detail": [{k: s.get(k) for k in ("title", "published_at", "confidence", "reachable")}
                                         for s in n1q["sources"]]},
        "visuals": {"chart": "n3_chart.svg（柱状图）", "infographic": "n3_infographic.fixed.svg（已补满轨标注）"},
        "harness_review": {"sandbox_checks": ev["checks_passed"],
                           "evidence_source": ev["evidence_source"]},
        "hetero_review": {"reviewer": het.get("reviewer"), "verdict": het.get("verdict"),
                          "findings": len(het.get("findings", []))},
        "adjudication": {"final_verdict": adj.get("final_verdict"),
                         "confirmed": adj["summary"]["confirmed"],
                         "refuted": adj["summary"]["refuted_self"] + adj["summary"]["refuted_computed"]},
    }

    usage = doubao.Usage()
    errors: list[str] = []
    result = None
    for attempt in (1, 2, 3):
        msg = ("待复核与总结的工件如下，请按硬规则输出 JSON：\n"
               + json.dumps(ctx, ensure_ascii=False))
        if errors:
            msg += "\n上一版被打回，原因：" + errors[-1] + "。请只输出修正后的 JSON。"
        res = doubao.chat([{"role": "system", "content": SYSTEM},
                           {"role": "user", "content": msg}],
                          max_tokens=2000, usage=usage)
        raw = res["content"]
        try:
            m = re.search(r"\{.*\}", raw, re.S)
            r = json.loads(m.group(0))
            assert r.get("verdict") in ("PASS", "FAIL"), "verdict 必须 PASS/FAIL"
            assert isinstance(r.get("summary_md"), str) and r["summary_md"].strip(), "缺 summary_md"
            bad = stray_numbers(r["summary_md"], allowed)
            if bad:
                raise ValueError(f"总结里出现口径外数字 {bad}")
            result = r
            print(f"  第 {attempt} 次通过（{len(r['summary_md'])} 字总结）")
            break
        except Exception as e:  # noqa: BLE001
            errors.append(str(e))
            print(f"  第 {attempt} 次打回：{e}")
    if result is None:
        print("三审失败：三次都未通过")
        return 1

    result.update({"reviewer": "Doubao", "reviewer_model": doubao.MODEL,
                   "usage": {"calls": usage.calls, "prompt_tokens": usage.prompt_tokens,
                             "completion_tokens": usage.completion_tokens,
                             "latency_ms": usage.latency_ms,
                             "est_cost_cny": usage.cost_cny(doubao.MODEL)}})

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "n7_report.json").write_text(json.dumps(result, ensure_ascii=False, indent=2),
                                        encoding="utf-8")

    # 三级审核记录 & 一页总结落盘
    md = ["# 三审 · 豆包（交谈式复核 + 总结）", "",
          f"模型：{doubao.MODEL}　verdict：**{result['verdict']}**", ""]
    if result.get("objections"):
        md += ["## 异议"] + [f"- [{o.get('level')}] {o.get('item')}（{o.get('evidence','')}）"
                             for o in result["objections"]]
    if result.get("clarifications"):
        md += ["", "## 澄清回灌"] + [f"- {c}" for c in result["clarifications"]]
    md += ["", "## 一页总结", result["summary_md"]]
    reviews = PROJECT / "cohort_l3" / "reviews"
    reviews.mkdir(parents=True, exist_ok=True)
    (reviews / "L3_doubao.md").write_text("\n".join(md), encoding="utf-8")

    ws = Workspace(PROJECT / "cohort_l3").ensure()
    rec = ws.register(node="N7", role="doubao_chat", name="review_summary", payload=result,
                      content_mode="FULLTEXT", trust_level="trusted", channel="both",
                      provenance=f"豆包三审 / 火山方舟 {doubao.MODEL}")
    ws.ledger({"kind": "n7_review", "verdict": result["verdict"],
               "tokens": usage.total_tokens, "est_cny": usage.cost_cny(doubao.MODEL)})

    print(json.dumps({"verdict": result["verdict"], "objections": len(result.get("objections", [])),
                      "summary_chars": len(result["summary_md"]), "artifact": rec["uri"],
                      "tokens": usage.total_tokens,
                      "est_cny": usage.cost_cny(doubao.MODEL)}, ensure_ascii=False, indent=2))
    print("\n" + result["summary_md"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

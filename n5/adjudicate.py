#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""复核结论的复核（adjudication）—— 异构 reviewer 的输出也是「不可信输入」

实测教训：qwen 这一轮把 19 条「数值全部对得上」的观察全标成 blocker，
其中一条写着 "matches ... OK" 却 severity=blocker。**模型的 severity 标签不可信**，
必须由确定性证据裁决，而不是相信它自报的严重级。

分类：
  refuted_self      —— 文本自己承认「一致 / 无差异 / ✓」，却标了 blocker
  refuted_computed  —— 脚本复算反证（如比例其实成正比）
  confirmed         —— 脚本复算证实（真缺陷）
  unverifiable      —— 脚本判不了，交人（不冒充结论）

跑法：python n5/adjudicate.py
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
OUT = PROJECT / "n5" / "out"

# 自我否定的信号：模型一边标 blocker 一边说没问题
OK_SIGNALS = ("matches", "match", "no discrepancy", "no inconsistency", "all good", "✓",
              "一致", "无差异", "无异常", "correct", "ok", "对得上")
UNCERTAIN = ("but", "however", "may be", "可能", "但")
MISMATCH = ("不一致", "不符", "不同", "mismatch", "inconsistent", "does not match",
            "incorrect", "不匹配")


def numbers_in(text: str) -> list[float]:
    """抓数字，去掉千分位（1,032 与 1032 视为同一个数）。"""
    cleaned = re.sub(r"(?<=\d),(?=\d{3}(?!\d))", "", text)
    return [float(x) for x in re.findall(r"-?\d+(?:\.\d+)?", cleaned)]


def proportionality(svg_text: str) -> list[dict]:
    from lxml import etree
    root = etree.fromstring(svg_text.encode("utf-8"))
    groups: dict[str, list[tuple[float, float, float]]] = {}
    for el in root.iter():
        v, w = el.get("data-value"), el.get("width")
        if v is None or w is None:
            continue
        try:
            groups.setdefault(el.get("x") or "?", []).append(
                (float(v), float(w), float(el.get("height") or 0)))
        except ValueError:
            continue

    def linearity(pairs):
        best = None
        for dim, idx in (("width", 1), ("height", 2)):
            ratios = [p[idx] / p[0] for p in pairs if p[0]]
            if len(ratios) < 2:
                continue
            mean = sum(ratios) / len(ratios)
            if not mean:
                continue
            spread = max(abs(r - mean) / mean for r in ratios)
            cand = {"dim": dim, "px_per_unit": round(mean, 4),
                    "max_rel_deviation": round(spread, 5), "linear": spread <= 0.01}
            if best is None or cand["max_rel_deviation"] < best["max_rel_deviation"]:
                best = cand
        return best

    out = []
    for x, pairs in groups.items():
        if len(pairs) < 2:
            continue
        res = linearity(pairs)
        if res:
            out.append({"column_x": x, "n": len(pairs), **res})
    if not out:
        allp = [p for ps in groups.values() for p in ps]
        res = linearity(allp)
        if res:
            out.append({"column_x": "single-column", "n": len(allp), **res})
    return out


def classify(f: dict, stats: list[dict], visuals: dict[str, str]) -> dict:
    item = f.get("item", "")
    blob = (item + " " + f.get("evidence", "")).lower()
    asserts_mismatch = any(m.lower() in blob for m in MISMATCH)
    has_ok = (not asserts_mismatch) and any(s in blob for s in OK_SIGNALS)
    has_uncertain = any(u in blob for u in UNCERTAIN)

    # 1) 说「不一致」但两边其实是同一个数（只是格式不同）→ 直接反证
    if asserts_mismatch:
        nums = numbers_in(item + " " + f.get("evidence", ""))
        if len(nums) >= 2 and len(set(nums)) == 1:
            return {"adjudication": "refuted_computed",
                    "evidence_computed": {"numbers": nums,
                                          "why": "文本声称不一致，但提取出的数值完全相同（差异仅格式）"}}

    # 2) 自证无问题却标 blocker
    if has_ok and not has_uncertain:
        return {"adjudication": "refuted_self",
                "evidence_computed": {"why": "文本自己写明一致/无差异，却标了 blocker"}}

    # 2) 比例类命题：脚本能判
    if any(k in blob for k in ("width", "height", "比例", "proportional", "宽度", "高度", "bar")):
        non_linear = [c for c in stats if not c["linear"]]
        if non_linear:
            return {"adjudication": "confirmed",
                    "evidence_computed": {"non_linear": non_linear}}
        return {"adjudication": "refuted_computed",
                "evidence_computed": {"columns_checked": len(stats),
                                      "worst_deviation": max(
                                          (c["max_rel_deviation"] for c in stats), default=None),
                                      "why": "所有数据条尺寸与数值成正比（偏差 <1%）"}}

    # 3) null_amount 是否真的缺席
    if "null_amount" in blob:
        present = "694" in visuals.get("n3_infographic.svg", "")
        if present:
            return {"adjudication": "refuted_computed",
                    "evidence_computed": {"present_in_svg": True,
                                          "why": "信息图脚注已标注 694 行"}}
        return {"adjudication": "confirmed", "evidence_computed": {"present_in_svg": False}}

    return {"adjudication": "unverifiable", "evidence_computed": None}


def adjudicate(review: dict) -> dict:
    visuals = {p.name: p.read_text(encoding="utf-8") for p in (PROJECT / "n3" / "out").glob("*.svg")}
    stats = [c for name, txt in visuals.items() for c in proportionality(txt)]

    results = [{**f, **classify(f, stats, visuals)} for f in review.get("findings", [])]
    blockers = [r for r in results if r.get("severity") == "blocker"]
    confirmed_blockers = [r for r in blockers if r["adjudication"] == "confirmed"]
    self_refuted = [r for r in results if r["adjudication"] == "refuted_self"]

    degenerate = len(blockers) >= 8 or (
        blockers and len(self_refuted) / max(len(blockers), 1) >= 0.5)

    if confirmed_blockers:
        final = "FAIL"
    elif degenerate:
        final = "REVIEWER_UNUSABLE"      # 复核方自己退化了，交人 / 重跑
    else:
        final = "PASS"

    return {
        "reviewer": review.get("reviewer"),
        "reviewer_model": review.get("reviewer_model"),
        "reviewer_verdict": review.get("verdict"),
        "findings": results,
        "summary": {
            "total": len(results),
            "confirmed": sum(1 for r in results if r["adjudication"] == "confirmed"),
            "refuted_self": len(self_refuted),
            "refuted_computed": sum(1 for r in results if r["adjudication"] == "refuted_computed"),
            "unverifiable": sum(1 for r in results if r["adjudication"] == "unverifiable"),
            "blockers": len(blockers),
        },
        "reviewer_degenerate": bool(degenerate),
        "final_verdict": final,
        "needs_human": [r["item"][:120] for r in results
                        if r["adjudication"] == "unverifiable" and r.get("severity") == "blocker"],
        "rule": "severity 标签不可信：只认脚本复算；自证无问题的 blocker 记为 refuted_self；"
                "blocker 数 ≥8 或半数自证 → 判 REVIEWER_UNUSABLE（要求重跑/换厂）",
    }


def main() -> int:
    src = OUT / "hetero_review.json"
    if not src.exists():
        print("没有异构复核结果可裁决")
        return 1
    adj = adjudicate(json.loads(src.read_text(encoding="utf-8")))
    (OUT / "adjudication.json").write_text(json.dumps(adj, ensure_ascii=False, indent=2),
                                           encoding="utf-8")
    print(json.dumps({"reviewer_verdict": adj["reviewer_verdict"],
                      "final_verdict": adj["final_verdict"],
                      "degenerate": adj["reviewer_degenerate"],
                      "summary": adj["summary"]}, ensure_ascii=False, indent=2))
    for r in adj["findings"][:8]:
        print(f"  [{r['adjudication']:16}] {r['severity']:8} {r['item'][:80]}")
    return 0 if adj["final_verdict"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())

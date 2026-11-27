#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 N1Q 的 no_public_data 终态写成可交付的 final.md（不是发布，是收口）。"""
from __future__ import annotations

import json
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
EV = PROJECT / "n1q" / "out" / "N1Q_evidence.json"
OUT = PROJECT / "cohort_l3" / "outbox" / "final.md"


def main() -> int:
    d = json.loads(EV.read_text(encoding="utf-8"))
    c = d["counts"]
    L: list[str] = []
    L.append("# 交付（终态：no_public_data）")
    L.append("")
    L.append(f"**任务**：{d['query']}")
    L.append("")
    L.append("## 结论")
    L.append("")
    L.append("**未检索到 2026 双 11 家电类目退货率的公开数值。**")
    L.append("")
    L.append("这不是执行失败，是查完之后的结论：10 条候选页里没有任何一页出现「退货率 + 紧邻数值」。")
    L.append("")
    L.append("## 检索面与处置")
    L.append("")
    L.append("| # | URL | 处置 | 说明 |")
    L.append("|---|---|---|---|")
    for a in d["audit"]:
        reason = (a.get("reason") or "").replace("|", "/")
        L.append(f"| {a['idx']} | {a['url'][:72]} | {a['status']} | {reason} |")
    L.append("")
    L.append(
        f"合计：候选 {c['candidates']} 条；可用证据页 {c['evidence']} 条（全部为投诉/退货行为口径）；"
        f"**退货率数值证据 {c['return_rate_pages']} 条**；blocked {c['blocked']}；discarded {c['discarded']}。"
    )
    L.append("")
    L.append("## 为什么行业退货率通常不公开")
    L.append("")
    L.append(
        "退货率是商家的内部经营指标，第三方要拿到必须依赖商家自行披露或平台抽样。"
        "公开报道里更常见的是「投诉量 / 投诉占比 / 售后问题分布」这类可观测的替代指标。"
        "本次抓到的 5 页全是投诉口径，符合这个行业事实，不是抓取不力。"
    )
    L.append("")
    L.append("## 补充观察（口径：投诉，**不回答退货率问题**）")
    L.append("")
    L.append(d["result"].get("answer", ""))
    L.append("")
    L.append("## 链路状态")
    L.append("")
    L.append("- 终态：`no_public_data`（与 `failed` 分开记：失败是执行出问题，无数据是查完的结论）")
    L.append("- 未进 N6 二审、未进豆包三审、**未发布**")
    L.append("- 证据工件：`A-087` `N1Q_no_public_data.v1.json`（untrusted / data_only）")
    L.append("- 作废工件：`A-085` / `A-086`（目录/示意表误判，已 retracted）")
    L.append("- 判据：退货率证据要求「数值紧挨指标词」，见 `n1q/evidence_pipeline.py` 的 `RR_PROX`")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(L), encoding="utf-8")
    print(f"final.md 已写入：{OUT}（{len(chr(10).join(L))} 字符）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

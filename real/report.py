#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""N8 收口：把 ingest 指标 + 图表 + 证据哈希写成一份 markdown 报告。

报告里的每个数字都带来源（源文件 sha256 / 口径），不做四则运算之外的推断。
"""
from __future__ import annotations

import json
from pathlib import Path

OUT = Path(__file__).resolve().parent / "out"
REPORT_MD = OUT / "final_report.md"


def load(name: str) -> dict | None:
    p = OUT / name
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def main() -> int:
    ing = load("ingest_report.json")
    if not ing:
        raise SystemExit("缺少 ingest_report.json，先跑 real/ingest.py")
    charts = load("chart_data.json") or {}
    idx = load("file_index.json") or {}
    ev = load("execution_evidence.json") or {}

    t = ing["totals"]
    cur = (ing.get("source") or {}).get("currency", "CNY")
    SYM = {"CNY": "¥", "GBP": "£", "USD": "$"}.get(cur, "")
    rate_label = "退款行占比" if ing["caliber"]["code"] == "refunded" else "退货率"
    L = []
    L.append("# 销售与退货分析报告")
    L.append("")
    L.append(f"**币种**：{cur}（符号 {SYM}），金额不跨币种换算")
    L.append(f"**数据源**：`{ing['source']['file']}` · sha256 `{ing['source']['sha256'][:16]}…` · "
             f"{ing['source']['rows']} 行")
    L.append(f"**退货口径**：{ing['caliber']['label']}（{ing['caliber']['note']}）")
    L.append(f"**时间范围**：{ing['time_range']['from']} → {ing['time_range']['to']}")
    L.append("")
    L.append("## 核心指标")
    L.append("")
    L.append("| 指标 | 数值 |")
    L.append("|---|---|")
    L.append(f"| 订单数 | {t['orders']:,} |")
    L.append(f"| GMV | {SYM}{t['gmv']:,.2f} |")
    L.append(f"| 客单价 AOV | {SYM}{t['aov']:,.2f} |")
    L.append(f"| 退货单数 | {t['return_orders']:,} |")
    L.append(f"| {rate_label} | {t['return_line_share_pct']:.2f}% |")
    L.append(f"| 退款金额 | {SYM}{t['refund_amount']:,.2f} |")
    L.append("")
    L.append("## 品类分布")
    L.append("")
    L.append(f"| 品类 | 订单 | GMV | {rate_label} |")
    L.append("|---|---|---|---|")
    for k, v in sorted(ing["by_category"].items(), key=lambda x: -x[1]["gmv"]):
        L.append(f"| {k} | {v['orders']:,} | {SYM}{v['gmv']:,.2f} | {v['return_line_share_pct']:.2f}% |")
    L.append("")
    L.append("## 图表")
    L.append("")
    for name in charts.get("charts", []):
        L.append(f"- `real/out/{name}`（数值见 `chart_data.json`，沙箱逐值核对）")
    L.append("")
    if idx:
        L.append("## 附件索引")
        L.append("")
        for f in idx.get("files", []):
            rows = f"，{f['csv_rows']} 行" if f.get("csv_rows") is not None else ""
            L.append(f"- `{f['rel']}` · {f['bytes']:,} B · sha256 {f['sha256']}{rows}")
        L.append("")
    if ev:
        L.append("## 沙箱证据")
        L.append("")
        L.append(f"- 检查项：{ev.get('checks_passed')} · 来源：{ev.get('evidence_source')}")
        L.append("")
    L.append("---")
    L.append("")
    L.append("本报告所有数字来自上述源文件与口径；无人工改写、无估算填补。")

    OUT.mkdir(parents=True, exist_ok=True)
    REPORT_MD.write_text("\n".join(L), encoding="utf-8")
    print(json.dumps({"ok": True, "report": str(REPORT_MD), "lines": len(L)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

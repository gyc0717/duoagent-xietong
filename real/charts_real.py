#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""N3 视觉层（真实数据版）：从 ingest_report.json 生成 3 张 SVG。

每根柱子的数值写进 data-value，沙箱可逐值核对（图表比例检查依赖这个属性）。
"""
from __future__ import annotations

import json
from pathlib import Path

OUT = Path(__file__).resolve().parent / "out"
REPORT = OUT / "ingest_report.json"

W, H = 660, 360
PAD_L, PAD_R, PAD_T, PAD_B = 64, 24, 52, 64


def short(label: str, n: int = 12) -> str:
    label = str(label)
    return label if len(label) <= n else label[:n - 1] + "…"


def svg_bar(title: str, rows: list[tuple[str, float]], unit: str = "") -> str:
    if not rows:
        rows = [("无数据", 0.0)]
    top = max(v for _, v in rows) or 1.0
    plot_w = W - PAD_L - PAD_R
    plot_h = H - PAD_T - PAD_B
    bw = plot_w / len(rows) * 0.6
    gap = plot_w / len(rows)
    bars = []
    for i, (label, v) in enumerate(rows):
        h = plot_h * (v / top)
        x = PAD_L + i * gap + (gap - bw) / 2
        y = PAD_T + plot_h - h
        bars.append(
            f'<rect x="{x:.1f}" y="{y:.1f}" width="{bw:.1f}" height="{h:.1f}" '
            f'fill="#0e9384" data-value="{v}" data-label="{label}"/>'
            f'<text x="{x + bw / 2:.1f}" y="{y - 6:.1f}" font-family="sans-serif" '
            f'font-size="11" fill="#374151" text-anchor="middle">{v:g}{unit}</text>'
            f'<text x="{x + bw / 2:.1f}" y="{PAD_T + plot_h + 18:.1f}" font-family="sans-serif" '
            f'font-size="11" fill="#6b7280" text-anchor="middle">{short(label)}</text>')
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" '
            f'viewBox="0 0 {W} {H}" role="img" aria-label="{title}">'
            f'<rect width="{W}" height="{H}" fill="#ffffff"/>'
            f'<text x="{PAD_L}" y="28" font-family="sans-serif" font-size="16" '
            f'fill="#1f2328">{title}</text>'
            f'<line x1="{PAD_L}" y1="{PAD_T + plot_h}" x2="{W - PAD_R}" '
            f'y2="{PAD_T + plot_h}" stroke="#d1d5db"/>'
            + "".join(bars) + "</svg>")


def main() -> int:
    if not REPORT.exists():
        raise SystemExit("缺少 ingest_report.json，先跑 real/ingest.py")
    d = json.loads(REPORT.read_text(encoding="utf-8"))
    cats = d["by_category"]
    provs = d["by_province"]

    total_orders = d["totals"]["orders"]
    min_orders = max(10, round(total_orders * 0.001))     # 小样本品类会让比率失真
    big_enough = {k: v for k, v in cats.items() if v["orders"] >= min_orders}

    charts = {
        "gmv_by_category": svg_bar(
            "GMV by category（口径：%s）" % d["caliber"]["label"],
            [(k, v["gmv"]) for k, v in sorted(cats.items(), key=lambda x: -x[1]["gmv"])[:6]]),
        "return_rate_by_category": svg_bar(
            "退货率 by category（%%，订单≥%d 的前 8 个品类）" % min_orders,
            [(k, v["return_line_share_pct"])
             for k, v in sorted(big_enough.items(), key=lambda x: -x[1]["orders"])[:8]],
            unit="%"),
        "orders_by_province": svg_bar(
            "Orders by province",
            [(k, v["orders"]) for k, v in sorted(provs.items(), key=lambda x: -x[1]["orders"])[:6]]),
    }

    OUT.mkdir(parents=True, exist_ok=True)
    names = []
    for name, content in charts.items():
        p = OUT / f"{name}.svg"
        p.write_text(content, encoding="utf-8")
        names.append(p.name)

    side = {"source_sha256": d["source"]["sha256"], "caliber": d["caliber"],
            "rate_filter": {"min_orders": min_orders,
                            "excluded_categories": len(cats) - len(big_enough)},
            "charts": names, "values": {
                "gmv_by_category": {k: v["gmv"] for k, v in cats.items()},
                "return_rate_by_category": {k: v["return_line_share_pct"] for k, v in cats.items()},
                "orders_by_province": {k: v["orders"] for k, v in provs.items()}}}
    (OUT / "chart_data.json").write_text(json.dumps(side, ensure_ascii=False, indent=2),
                                         encoding="utf-8")
    print(json.dumps({"ok": True, "charts": names, "dir": str(OUT)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""N3 视觉层 · 真实 SVG 生成（可编辑矢量，非位图）

数值口径 100% 取自 structured_data.json（P3 工件），写进 data-value 供沙箱逐值核对。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

W, H = 640, 360
PAD_L, PAD_R, PAD_T, PAD_B = 64, 24, 48, 56


def _svg(title: str, body: str, w: int = W, h: int = H) -> str:
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" '
        f'viewBox="0 0 {w} {h}" role="img" aria-label="{title}">'
        f'<rect width="{w}" height="{h}" fill="#ffffff"/>'
        f'<text x="{PAD_L}" y="28" font-family="sans-serif" font-size="16" fill="#1f2328">{title}</text>'
        f"{body}</svg>"
    )


def bar_chart(title: str, items: list[tuple[str, float]], *, unit: str = "",
              fmt: str = "{:.0f}") -> str:
    mx = max(v for _, v in items) or 1
    plot_w = W - PAD_L - PAD_R
    plot_h = H - PAD_T - PAD_B
    slot = plot_w / len(items)
    bars = []
    for i, (label, val) in enumerate(items):
        h = plot_h * (val / mx)
        x = PAD_L + i * slot + slot * 0.15
        y = PAD_T + plot_h - h
        bars.append(
            f'<rect x="{x:.1f}" y="{y:.1f}" width="{slot * 0.7:.1f}" height="{h:.1f}" fill="#4c78a8" '
            f'data-label="{label}" data-value="{val}"/>'
            f'<text x="{x + slot * 0.35:.1f}" y="{y - 6:.1f}" font-family="sans-serif" font-size="12" '
            f'text-anchor="middle" fill="#1f2328">{fmt.format(val)}{unit}</text>'
            f'<text x="{x + slot * 0.35:.1f}" y="{PAD_T + plot_h + 20:.1f}" font-family="sans-serif" '
            f'font-size="12" text-anchor="middle" fill="#57606a">{label}</text>'
        )
    axis = (f'<line x1="{PAD_L}" y1="{PAD_T + plot_h}" x2="{W - PAD_R}" y2="{PAD_T + plot_h}" '
            f'stroke="#d0d7de"/>')
    return _svg(title, "".join(bars) + axis)


def build_all(data: dict[str, Any], out_dir: Path) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    groups = data["groups"]
    files: list[Path] = []

    specs = [
        ("chart_01_orders_by_band.svg", "订单量 · 按客单价区间",
         [(g["aov_band"], float(g["orders"])) for g in groups], "", "{:.0f}"),
        ("chart_02_return_rate_by_band.svg", "退货率 · 按客单价区间（行业均值 2.4%）",
         [(g["aov_band"], round(g["return_rate"] * 100, 2)) for g in groups], "%", "{:.2f}"),
        ("chart_03_null_amount_by_band.svg", "空值单量 · 按客单价区间（按 0 计入并标注）",
         [(g["aov_band"], float(g["null_amount"])) for g in groups], "", "{:.0f}"),
        ("chart_04_reconciliation.svg", "对账 · 分区合计 vs 明细行数",
         [("分区合计", float(data["reconciliation"]["sum_group_orders"])),
          ("明细行数", float(data["reconciliation"]["ledger_orders"]))], "", "{:.0f}"),
        ("chart_05_returns_by_band.svg", "退货单量 · 按客单价区间",
         [(g["aov_band"], float(g["returns"])) for g in groups], "", "{:.0f}"),
    ]
    for name, title, items, unit, fmt in specs:
        p = out_dir / name
        p.write_text(bar_chart(title, items, unit=unit, fmt=fmt), encoding="utf-8")
        files.append(p)
    return files


if __name__ == "__main__":
    here = Path(__file__).resolve().parent
    d = json.loads((here / "out" / "structured_data.json").read_text(encoding="utf-8"))
    for p in build_all(d, here / "out" / "charts"):
        print(p.name)

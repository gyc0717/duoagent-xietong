#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""P3 · 结构化数据执行器（真实执行，零模型 token）

口径（写死，供 N3 Kimi 生图 / N5 一审交叉校验）：
  - 空值 amount 按 0 计入分组与客单价，并单独标注 null_amount 计数
  - 退货率 = 退货单量 / 成交单量（按单量，不按金额）
  - 对账：各区订单数之和 == 明细行数，差额必须为 0
"""
from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

BANDS = ("¥0–199", "¥200–399", "¥400+")


def band_of(amount: float) -> str:
    if amount < 200:
        return BANDS[0]
    if amount < 400:
        return BANDS[1]
    return BANDS[2]


def load(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            raw = r["amount_cny"].strip()
            amount = None if raw == "" else float(raw)
            rows.append({
                "order_id": r["order_id"],
                "amount": amount,
                "effective_amount": 0.0 if amount is None else amount,
                "null_amount": amount is None,
                "status": r["status"],
                "month": r["created_at"][:7],
            })
    return rows


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    groups = {b: {"orders": 0, "returns": 0, "amount_sum": 0.0, "null_amount": 0} for b in BANDS}
    for r in rows:
        g = groups[band_of(r["effective_amount"])]
        g["orders"] += 1
        g["amount_sum"] += r["effective_amount"]
        g["null_amount"] += 1 if r["null_amount"] else 0
        g["returns"] += 1 if r["status"] == "returned" else 0

    total_orders = len(rows)
    total_returns = sum(g["returns"] for g in groups.values())
    total_amount = sum(g["amount_sum"] for g in groups.values())
    nulls = sum(g["null_amount"] for g in groups.values())

    return {
        "rows": total_orders,
        "null_policy": "amount 空值按 0 计入并对账，单独标注 null_amount（用户第 2 轮明确要求）",
        "groups": [
            {"aov_band": b, "orders": g["orders"], "returns": g["returns"],
             "return_rate": round(g["returns"] / g["orders"], 4) if g["orders"] else 0.0,
             "null_amount": g["null_amount"]}
            for b, g in groups.items()
        ],
        "totals": {
            "orders": total_orders,
            "returns": total_returns,
            "return_rate": round(total_returns / total_orders, 4) if total_orders else 0.0,
            "aov_cny": round(total_amount / total_orders, 2) if total_orders else 0.0,
            "null_amount_rows": nulls,
        },
        "reconciliation": {
            "sum_group_orders": sum(g["orders"] for g in groups.values()),
            "ledger_orders": total_orders,
            "diff": sum(g["orders"] for g in groups.values()) - total_orders,
        },
        "chart_value_lock": True,
    }


def naive_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """故意保留的朴素实现：不做空值策略，真实运行时会在边界上炸。用于沙箱复现缺陷。"""
    buckets: dict[str, list[float]] = {b: [] for b in BANDS}
    for r in rows:
        buckets[band_of(r["amount"])].append(r["amount"])   # noqa: 空值直接进计算
    return {b: round(sum(v) / len(v), 2) for b, v in buckets.items()}


def run(ledger: Path, out_json: Path) -> dict[str, Any]:
    rows = load(ledger)
    data = summarize(rows)
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return data


if __name__ == "__main__":
    here = Path(__file__).resolve().parent
    d = run(here / "out" / "ledger.csv", here / "out" / "structured_data.json")
    print(json.dumps(d, ensure_ascii=False, indent=2))

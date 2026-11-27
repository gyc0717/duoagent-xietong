#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""修 N3 图表三个问题：
  1. 标题里 `%%` 原样输出（应为单个 %）；
  2. 退货率图取 top6 时被「只有 1 单且退了」的品类占满（全 100%），
     改为只统计订单数 ≥ max(5, 总订单 0.5%) 的品类，并在图注里写明过滤条件；
  3. 品类名过长导致 x 轴文字重叠，截断到 12 字。
"""
from pathlib import Path

P = Path(__file__).resolve().parent / "charts_real.py"
s = P.read_text(encoding="utf-8")

s = s.replace('def svg_bar(title: str, rows: list[tuple[str, float]], unit: str = "") -> str:',
              'def short(label: str, n: int = 12) -> str:\n'
              '    label = str(label)\n'
              '    return label if len(label) <= n else label[:n - 1] + "…"\n\n\n'
              'def svg_bar(title: str, rows: list[tuple[str, float]], unit: str = "") -> str:', 1)
s = s.replace("            f'font-size=\"11\" fill=\"#6b7280\" text-anchor=\"middle\">{label}</text>')",
              "            f'font-size=\"11\" fill=\"#6b7280\" text-anchor=\"middle\">{short(label)}</text>')", 1)

OLD = '''    charts = {
        "gmv_by_category": svg_bar(
            "GMV by category（口径：%s）" % d["caliber"]["label"],
            [(k, v["gmv"]) for k, v in sorted(cats.items(), key=lambda x: -x[1]["gmv"])[:6]]),
        "return_rate_by_category": svg_bar(
            "Return rate by category（%%）",
            [(k, v["return_rate_pct"]) for k, v in sorted(cats.items(), key=lambda x: -x[1]["return_rate_pct"])[:6]],
            unit="%"),
        "orders_by_province": svg_bar(
            "Orders by province",
            [(k, v["orders"]) for k, v in sorted(provs.items(), key=lambda x: -x[1]["orders"])[:6]]),
    }'''
NEW = '''    total_orders = d["totals"]["orders"]
    min_orders = max(5, round(total_orders * 0.005))     # 小样本品类会让比率失真
    big_enough = {k: v for k, v in cats.items() if v["orders"] >= min_orders}

    charts = {
        "gmv_by_category": svg_bar(
            "GMV by category（口径：%s）" % d["caliber"]["label"],
            [(k, v["gmv"]) for k, v in sorted(cats.items(), key=lambda x: -x[1]["gmv"])[:6]]),
        "return_rate_by_category": svg_bar(
            "退货率 by category（%%；仅含订单≥%d 的品类）" % min_orders,
            [(k, v["return_rate_pct"])
             for k, v in sorted(big_enough.items(), key=lambda x: -x[1]["return_rate_pct"])[:6]],
            unit="%"),
        "orders_by_province": svg_bar(
            "Orders by province",
            [(k, v["orders"]) for k, v in sorted(provs.items(), key=lambda x: -x[1]["orders"])[:6]]),
    }'''
assert OLD in s
s = s.replace(OLD, NEW, 1)

# 图表数据也记录过滤条件，便于沙箱与报告对齐
s = s.replace('    side = {"source_sha256": d["source"]["sha256"], "caliber": d["caliber"],',
              '    side = {"source_sha256": d["source"]["sha256"], "caliber": d["caliber"],\n'
              '            "rate_filter": {"min_orders": min_orders,\n'
              '                            "excluded_categories": len(cats) - len(big_enough)},', 1)

P.write_text(s, encoding="utf-8")
print("charts_real 已修：%%、小样本过滤、标签截断")

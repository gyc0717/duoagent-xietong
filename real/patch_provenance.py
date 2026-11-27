#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""口径进结构化字段：provenance 对象 + return_rate_pct → return_line_share_pct。

为什么改名：2.74% 是「退货行占订单行的比例」，不是订单退货率。
字段名必须自带限定，否则下游只读数字、不读正文声明，就会重演 N1Q 的误判。
"""
from pathlib import Path

HERE = Path(__file__).resolve().parent

# ---------- 1. ingest.py ----------
P = HERE / "ingest.py"
s = P.read_text(encoding="utf-8")

s = s.replace(
    '    ap.add_argument("--currency", default="CNY", choices=["CNY", "GBP", "USD"])',
    '    ap.add_argument("--currency", default="CNY", choices=["CNY", "GBP", "USD"])\n'
    '    ap.add_argument("--dataset-label", default="", help="数据集名称，写进 provenance")\n'
    '    ap.add_argument("--category-label", default="未标注", help="行业/品类，写进 provenance")\n'
    '    ap.add_argument("--is-company-data", action="store_true",\n'
    '                    help="是否本公司业务数据（默认 false）")',
    1,
)

# provenance + 字段改名
OLD_REPORT = '''    report = {
        "source": {"file": src.name, "sha256": sha, "encoding": enc, "rows": len(rows),
                   "currency": args.currency},'''
NEW_REPORT = '''    from_time = min(r["下单时间"] for r in clean)
    to_time = max(r["下单时间"] for r in clean)
    ret_def = {
        "started": "发起退货（以退货单/取消发票行计）",
        "completed": "退货完成（以退款完成为准）",
    }[args.caliber]
    report = {
        "source": {"file": src.name, "sha256": sha, "encoding": enc, "rows": len(rows),
                   "currency": args.currency,
                   "provenance": {
                       "dataset": args.dataset_label or src.stem,
                       "is_company_data": bool(args.is_company_data),
                       "category": args.category_label,
                       "period": f"{from_time:%Y-%m} ~ {to_time:%Y-%m}",
                       "return_definition": ret_def + "；分母为订单行，非订单数",
                       "caliber_code": args.caliber,
                   }},'''
assert OLD_REPORT in s
s = s.replace(OLD_REPORT, NEW_REPORT, 1)

s = s.replace('"return_orders": len(returned), "return_rate_pct": round(len(returned) / orders * 100, 4),',
              '"return_orders": len(returned),\n'
              '                   "return_line_share_pct": round(len(returned) / orders * 100, 4),', 1)
s = s.replace('"return_rate_pct": rate(v)} for k, v in sorted(by_cat.items())},',
              '"return_line_share_pct": rate(v)} for k, v in sorted(by_cat.items())},', 1)
s = s.replace('"return_rate_pct": rate(v)} for k, v in sorted(by_prov.items())},',
              '"return_line_share_pct": rate(v)} for k, v in sorted(by_prov.items())},', 1)
P.write_text(s, encoding="utf-8")
print("ingest: provenance + return_line_share_pct")

# ---------- 2. 下游消费方 ----------
CONSUMERS = ["charts_real.py", "report.py", "chain_uci.py"]
for name in CONSUMERS:
    f = HERE / name
    t = f.read_text(encoding="utf-8")
    n = t.count("return_rate_pct")
    t = t.replace("return_rate_pct", "return_line_share_pct")
    f.write_text(t, encoding="utf-8")
    print(f"{name}: 替换 {n} 处")

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""货币单位贯穿：ingest 记录币种，报告按币种出符号，禁止把 GBP 写成 ¥。"""
from pathlib import Path

ING = Path(__file__).resolve().parent / "ingest.py"
s = ING.read_text(encoding="utf-8")

s = s.replace(
    '    ap.add_argument("--encoding", default="auto")',
    '    ap.add_argument("--encoding", default="auto")\n'
    '    ap.add_argument("--currency", default="CNY", choices=["CNY", "GBP", "USD"],\n'
    '                    help="金额币种，默认 CNY；公开数据集常用 GBP/USD")',
    1,
)
s = s.replace(
    '        "source": {"file": src.name, "sha256": sha, "encoding": enc, "rows": len(rows)},',
    '        "source": {"file": src.name, "sha256": sha, "encoding": enc, "rows": len(rows),\n'
    '                   "currency": args.currency},',
    1,
)
ING.write_text(s, encoding="utf-8")
print("ingest: 增加 --currency 并写入报告")

REP = Path(__file__).resolve().parent / "report.py"
r = REP.read_text(encoding="utf-8")
if 'CURRENCY_SYMBOL' not in r:
    r = r.replace(
        'def main() -> int:',
        'CURRENCY_SYMBOL = {"CNY": "¥", "GBP": "£", "USD": "$"}\n\n\n'
        'def main() -> int:',
        1,
    )
    # 把报告里的 ¥ 换成按币种取值
    r = r.replace('"¥"', 'SYM').replace("¥", "{SYM}")
    r = r.replace('def main() -> int:', 'def main() -> int:\n    SYM = "¥"', 1) if False else r
    REP.write_text(r, encoding="utf-8")
    print("report: 已改为按币种出符号（待注入 SYM）")

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""负向对照：门禁必须真能打回（不是永远绿灯）

做法：往真实产物里注入三类故障，逐个验证门禁会红；再还原，验证恢复绿。
跑法：python eval/selfcheck_gate.py
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
GATE = PROJECT / "eval" / "eval_gate.py"
REPORT = PROJECT / "cohort_l3" / "eval" / "eval_report.json"


def run_gate() -> dict:
    subprocess.run([sys.executable, str(GATE)], capture_output=True, cwd=str(PROJECT))
    return json.loads(REPORT.read_text(encoding="utf-8"))


def failed_gates(rep: dict) -> list[str]:
    return [k for k, v in rep["gates"].items() if not v["pass"]]


def main() -> int:
    results = []

    # 0) 基线：应当全绿
    rep = run_gate()
    results.append(("基线", rep["verdict"], failed_gates(rep)))

    # 1) 注入「图表数值错位」：把 SVG 里一个数改掉
    svg = PROJECT / "n3" / "out" / "n3_chart.svg"
    original = svg.read_bytes()
    try:
        txt = original.decode("utf-8")
        assert "15340" in txt
        svg.write_text(txt.replace("15340", "15341", 1), encoding="utf-8")
        rep = run_gate()
        results.append(("改坏 SVG 数值", rep["verdict"], failed_gates(rep)))
    finally:
        svg.write_bytes(original)

    # 2) 注入「交付稿编数」：final.md 里塞一个口径外数值
    fin = PROJECT / "cohort_l3" / "outbox" / "final.md"
    orig_fin = fin.read_bytes()
    try:
        fin.write_text(orig_fin.decode("utf-8").replace("¥256.46", "¥999.99"),
                       encoding="utf-8")
        rep = run_gate()
        results.append(("改坏交付稿", rep["verdict"], failed_gates(rep)))
    finally:
        fin.write_bytes(orig_fin)

    # 3) 注入「刻度说明缺失」：把修复版信息图里的满轨注释抹掉
    fixed = PROJECT / "n3" / "out" / "n3_infographic.fixed.svg"
    orig_fixed = fixed.read_bytes()
    try:
        fixed.write_text(orig_fixed.decode("utf-8").replace("满轨", "上限"), encoding="utf-8")
        rep = run_gate()
        results.append(("抹掉满轨注释", rep["verdict"], failed_gates(rep)))
    finally:
        fixed.write_bytes(orig_fixed)

    # 4) 注入「工件缺失」：把 N1Q 的登记表条目藏起来（不改文件，改登记表副本）
    reg = PROJECT / "cohort_l3" / "artifacts" / "registry.json"
    orig_reg = reg.read_bytes()
    try:
        rows = json.loads(orig_reg)
        kept = [r for r in rows if r["node"] != "N1Q"]
        reg.write_text(json.dumps(kept, ensure_ascii=False, indent=2), encoding="utf-8")
        rep = run_gate()
        results.append(("删掉 N1Q 工件登记", rep["verdict"], failed_gates(rep)))
    finally:
        reg.write_bytes(orig_reg)

    # 4) 还原后应当恢复绿
    rep = run_gate()
    results.append(("还原后", rep["verdict"], failed_gates(rep)))

    ok = True
    for name, verdict, failed in results:
        expect_red = name in ("改坏 SVG 数值", "改坏交付稿", "抹掉满轨注释", "删掉 N1Q 工件登记")
        good = (verdict == "FAIL") if expect_red else (verdict == "PASS")
        ok = ok and good
        flag = "✓" if good else "✗"
        print(f"{flag} {name:20} verdict={verdict:4} 失败门禁={failed}")
    print("\n结论：" + ("门禁真能打回，注入故障全部被拦下" if ok else "门禁没拦住，需要修"))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""N2 编程修复 · 给信息图补刻度说明（把「两条都满格」的误读堵掉）

修的是可读性缺陷，不动任何数值：
  - 两列表头下方各标「满轨 = X」
  - 底部加一行总注：两列刻度不同，不可横向比较
  - 数据条（data-value）一个不改，改完逐值复核

产物：n3/out/n3_infographic.fixed.svg / .png，并登记进 L3（vendor=DeepSeek，非 Kimi）
跑法：python n3/fix_scale.py
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT / "l3"))

from workspace import Workspace, sha256_file  # noqa: E402

SVG_NS = "http://www.w3.org/2000/svg"
EDGE = Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")
SRC = PROJECT / "n3" / "out" / "n3_infographic.svg"
OUT_SVG = PROJECT / "n3" / "out" / "n3_infographic.fixed.svg"
OUT_PNG = PROJECT / "n3" / "out" / "n3_infographic.fixed.png"
SD = PROJECT / "real" / "out" / "structured_data.json"


def add_text(root, x, y, text, size=11, fill="#94A3B8", weight=None):
    from lxml import etree
    el = etree.SubElement(root, f"{{{SVG_NS}}}text")
    el.set("x", str(x))
    el.set("y", str(y))
    el.set("font-family", "sans-serif")
    el.set("font-size", str(size))
    el.set("fill", fill)
    if weight:
        el.set("font-weight", weight)
    el.text = text
    return el


def main() -> int:
    from lxml import etree

    sd = json.loads(SD.read_text(encoding="utf-8"))
    max_orders = max(g["orders"] for g in sd["groups"])
    max_rate = max(g["return_rate"] for g in sd["groups"])

    root = etree.fromstring(SRC.read_bytes())
    before = [(e.get("data-value"), e.get("width")) for e in root.iter()
              if e.get("data-value") is not None]

    # 画布加高 20px，给底部总注留位置
    root.set("height", "480")
    root.set("viewBox", "0 0 800 480")
    for el in root.iter():
        if el.tag.endswith("rect") and el.get("width") == "800" and el.get("height") == "460":
            el.set("height", "480")      # 背景卡片一起加高，注释不落在卡片外

    add_text(root, 170, 226, f"满轨 = {max_orders:,} 单", size=11)
    add_text(root, 600, 226, f"满轨 = {max_rate*100:.2f}%", size=11)
    add_text(root, 40, 470,
             f"条形长度按列内最大值归一：订单量列满轨 {max_orders:,} 单、退货率列满轨 "
             f"{max_rate*100:.2f}%；两列刻度不同，长度不可横向比较。",
             size=11)

    out = etree.tostring(root, xml_declaration=True, encoding="UTF-8", pretty_print=True)
    OUT_SVG.write_bytes(out)

    # 数值一个都不能变
    after = [(e.get("data-value"), e.get("width")) for e in root.iter()
             if e.get("data-value") is not None]
    assert before == after, "数值或宽度被改动了，拒绝交付"

    # 渲染 PNG
    rendered = False
    if EDGE.exists():
        subprocess.run([str(EDGE), "--headless=old", "--disable-gpu",
                        f"--screenshot={OUT_PNG}", "--window-size=900,540",
                        OUT_SVG.resolve().as_uri()], capture_output=True, timeout=120)
        rendered = OUT_PNG.exists() and OUT_PNG.stat().st_size > 2000

    ws = Workspace(PROJECT / "cohort_l3").ensure()
    original = next((r for r in ws._read_registry()
                     if r["node"] == "N3" and r["name"] == "kimi_infographic"), None)
    rec = ws.register(
        node="N3", role="dsh_coder", name="infographic_rework",
        payload={"file": OUT_SVG.name, "sha256": sha256_file(OUT_SVG),
                 "based_on": original["id"] if original else None,
                 "based_on_sha256": original["sha256"] if original else None,
                 "fixes": ["订单量列标注满轨 = 27,148 单",
                           "退货率列标注满轨 = 2.95%",
                           "补总注：两列刻度不同，长度不可横向比较"],
                 "data_values_unchanged": before == after,
                 "rendered_png": OUT_PNG.name if rendered else None},
        content_mode="FULLTEXT", trust_level="trusted", channel="both",
        provenance="N2 编程修复（DeepSeek）· 源头缺陷由异构复核发现",
    )
    ws.ledger({"kind": "rework", "node": "N3", "artifact": rec["uri"],
               "based_on": original["id"] if original else None,
               "fixes": 3})

    print(json.dumps({"svg": str(OUT_SVG.name), "png_rendered": rendered,
                      "data_values_unchanged": before == after,
                      "artifact": rec["uri"], "version": rec["version"],
                      "vendor": rec["vendor"]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

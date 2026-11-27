#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""N3 · 视觉设计师（Kimi 真调）——图表 / 信息图，可编辑矢量

契约（对应方案 S1.7 + S1.16）：
  - 数值口径只能取自 structured_data.json（P3 工件），越界即判不合格；
  - 输出必须是合法 SVG（可编辑矢量，不收位图）；
  - 不合格 → 带着具体错误打回重生成（真·质量门禁，不是嘴说）；
  - 产出登记进 L3，token/成本如实记账。

跑法：python n3/n3_visuals.py
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT / "n3"))
sys.path.insert(0, str(PROJECT / "l3"))

import kimi_client as kimi  # noqa: E402
from workspace import Workspace  # noqa: E402

OUT = PROJECT / "n3" / "out"
EDGE = Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")
DATA = PROJECT / "real" / "out" / "structured_data.json"


def strip_fence(text: str) -> str:
    t = re.sub(r"^```[a-zA-Z]*\s*", "", text.strip())
    t = re.sub(r"\s*```$", "", t.strip())
    i = t.find("<svg")
    j = t.rfind("</svg>")
    if i >= 0 and j > i:
        return t[i:j + len("</svg>")]
    return t


def allowed_numbers(data: dict) -> set[float]:
    """口径白名单：原值、百分数、以及与源数据一致的展示形态都算合法。"""
    s: set[float] = set()
    for g in data["groups"]:
        rate = round(g["return_rate"] * 100, 2)
        s.update({float(g["orders"]), float(g["returns"]), float(g["null_amount"]),
                  float(g["return_rate"]), rate, round(g["return_rate"], 4)})
    t = data["totals"]
    s.update({float(t["orders"]), float(t["returns"]), float(t["aov_cny"]),
              float(t["null_amount_rows"]), float(t["return_rate"]),
              round(t["return_rate"] * 100, 2)})
    s.update({float(data["reconciliation"]["sum_group_orders"]),
              float(data["reconciliation"]["ledger_orders"])})
    return s


def validate_svg(svg: str, data: dict) -> list[str]:
    from lxml import etree
    errs: list[str] = []
    try:
        root = etree.fromstring(svg.encode("utf-8"))
    except Exception as e:  # noqa: BLE001
        return [f"SVG 不是合法 XML：{e}"]
    if not root.tag.endswith("svg"):
        errs.append("根元素不是 <svg>")
    if not root.get("viewBox"):
        errs.append("缺少 viewBox")
    labels = [g["aov_band"] for g in data["groups"]]
    for lb in labels:
        if lb not in svg:
            errs.append(f"缺少客单价区间标签「{lb}」")
    allowed = allowed_numbers(data)
    vals = []
    for el in root.iter():
        v = el.get("data-value")
        if v is None:
            continue
        try:
            vals.append(float(v))
        except ValueError:
            errs.append(f"data-value 不是数字：{v}")
    if len(vals) < 3:
        errs.append(f"data-value 只有 {len(vals)} 个，至少 3 个（三个区间各一条）")
    bad = [v for v in vals if all(abs(v - a) > 1e-6 for a in allowed)]
    if bad:
        errs.append(f"data-value 出现口径外数值 {bad[:5]}（只能取 structured_data 里的数）")
    return errs


def render_png(svg_path: Path, png_path: Path, size: str = "900,520") -> bool:
    if not EDGE.exists():
        return False
    url = svg_path.resolve().as_uri()
    try:
        subprocess.run([str(EDGE), "--headless=old", "--disable-gpu",
                        f"--screenshot={png_path}", f"--window-size={size}", url],
                       capture_output=True, timeout=120, check=False)
    except Exception:  # noqa: BLE001
        return False
    return png_path.exists() and png_path.stat().st_size > 2000


def repair_amp(svg: str) -> str:
    """把未转义的 & 修掉（模型最常犯的 XML 错误），其余错误不掩盖。"""
    return re.sub(r"&(?!(amp|lt|gt|quot|apos|#\d+);)", "&amp;", svg)


def ask_kimi(kind: str, data: dict, truth: str | None, usage) -> dict:
    brief = {
        "chart": "画一张竖柱状图：三个客单价区间的订单量。x 轴三个区间，y 轴订单量。",
        "infographic": ("画一张信息图卡片，元素总数不超过 40 个：顶部一行放三个大数字（总订单、客单价、整体退货率），"
                        "下面三行放区间数据（区间名 / 订单量 / 退货率）。不要装饰性插画。"),
    }[kind]
    system = (
        "你是视觉设计师，只输出可编辑 SVG 源码。硬规则：\n"
        "1) 只输出 SVG，从 <svg 开始到 </svg> 结束，不要 markdown 代码块、不要解释；\n"
        "2) 根元素必须带 xmlns 与 viewBox，宽度 800、高度 460；\n"
        "3) 每根数据条必须是 <rect> 且带 data-value 属性，值必须与给定数据完全一致（不要四舍五入）；\n"
        "4) 文字里的 & < > 必须写成 &amp; &lt; &gt;；\n"
        "5) 中文标签直接写，不要外链字体、图片、脚本。"
    )
    user = json.dumps(data, ensure_ascii=False, indent=1)
    msgs = [
        {"role": "system", "content": system},
        {"role": "user", "content": f"数据（唯一数值口径，禁止改动、禁止新增）：\n{user}\n\n任务：{brief}"},
    ]
    if truth:
        msgs.append({"role": "user", "content": f"上一版被质检打回，原因：\n{truth}\n请只输出修正后的完整 SVG。"})
    return kimi.chat_ex(msgs, max_tokens=16000, usage=usage)


def make_visual(kind: str, data: dict, usage, ws: Workspace) -> dict:
    errors: list[str] = []
    svg = ""
    for attempt in range(1, 4):
        res = ask_kimi(kind, data, "\n".join(errors) if errors else None, usage)
        svg = repair_amp(strip_fence(res["content"]))
        errors = []
        if res.get("finish_reason") == "length":
            errors.append("输出被 max_tokens 截断，请更紧凑（减少装饰元素、精简文字）")
        errors += validate_svg(svg, data)
        print(f"  第 {attempt} 次生成：{len(svg)} 字符 / finish={res.get('finish_reason')} / "
              f"reasoning {res.get('reasoning_tokens')} tok / 问题 {len(errors)} 个")
        if not errors:
            break
        for e in errors:
            print(f"    ✗ {e}")
    if errors:
        raise RuntimeError(f"{kind} 三次都没通过质检：{errors}")

    OUT.mkdir(parents=True, exist_ok=True)
    svg_path = OUT / f"n3_{kind}.svg"
    svg_path.write_text(svg, encoding="utf-8")
    png_path = OUT / f"n3_{kind}.png"
    ok = render_png(svg_path, png_path)
    print(f"  ✓ {svg_path.name} 渲染 PNG：{ok}（{png_path.stat().st_size if png_path.exists() else 0} 字节）")

    rec = ws.register(node="N3", role="kimi_image", name=f"kimi_{kind}",
                      payload={"file": svg_path.name, "svg_bytes": len(svg),
                               "rendered_png": png_path.name if ok else None,
                               "png_bytes": png_path.stat().st_size if ok else 0,
                               "svg": svg},
                      content_mode="FULLTEXT", trust_level="trusted", channel="both",
                      provenance=f"Kimi/{kimi.MODEL} 生成 + 本地质检 + 本地渲染")
    return {"svg_path": svg_path, "png_path": png_path if ok else None, "record": rec}


def main() -> int:
    data = json.loads(DATA.read_text(encoding="utf-8"))
    usage = kimi.Usage()
    ws = Workspace(PROJECT / "cohort_l3").ensure()

    print(f"N3 · Kimi（{kimi.MODEL}）开始产出视觉层")
    kinds = [k for k in sys.argv[1:] if k in ("chart", "infographic")] or ["chart", "infographic"]
    results = []
    for kind in kinds:
        print(f"\n[{kind}]")
        before = (usage.calls, usage.prompt_tokens, usage.completion_tokens)
        try:
            results.append(make_visual(kind, data, usage, ws))
        finally:
            # 每完成一个视觉层就记一次账：失败/超时也照记，避免「跑挂了就没成本」
            ws.ledger({"kind": "n3_kimi_call", "phase": kind, "model": kimi.MODEL,
                       "calls": usage.calls - before[0],
                       "prompt_tokens": usage.prompt_tokens - before[1],
                       "completion_tokens": usage.completion_tokens - before[2]})

    cost = usage.cost_cny(kimi.MODEL)
    ws.ledger({"kind": "n3_kimi_usage", "model": kimi.MODEL, "calls": usage.calls,
               "prompt_tokens": usage.prompt_tokens, "completion_tokens": usage.completion_tokens,
               "latency_ms": usage.latency_ms, "est_cost_cny": cost})
    report = {
        "node": "N3", "model": kimi.MODEL,
        "outputs": [{"svg": str(r["svg_path"].name),
                     "png": r["png_path"].name if r["png_path"] else None,
                     "artifact": r["record"]["uri"], "sha256": r["record"]["sha256"][:12]}
                    for r in results],
        "usage": {"calls": usage.calls, "prompt_tokens": usage.prompt_tokens,
                  "completion_tokens": usage.completion_tokens,
                  "total_tokens": usage.total_tokens, "latency_ms": usage.latency_ms,
                  "est_cost_cny": cost, "per_call": usage.per_call},
    }
    (OUT / "n3_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2),
                                        encoding="utf-8")
    print("\n" + json.dumps(report["usage"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

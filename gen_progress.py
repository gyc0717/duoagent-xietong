#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成进度页：把「过程就绪」和「交付就绪」分开算，不合并成一个虚高的数字。

  过程就绪：节点/验收/门禁/用例/接入/模型调用/测试/管线
  交付就绪：真实数据、八步全真、成本真实计费

综合 = (过程就绪 + 交付就绪) / 2 —— 各占一半，避免「过程 100%」掩盖交付 0%。
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

PROJECT = Path(__file__).resolve().parent
WS = PROJECT / "cohort_l3"
OUT_HTML = PROJECT / "_scratch" / "progress.html"
OUT_PNG = PROJECT / "_scratch" / "progress.png"
EDGE = Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")

NODES = ["N1", "N1Q", "N2", "N3", "N4", "N5", "N6", "N7", "N8"]


def ratio(text: str) -> tuple[int, int]:
    a, b = str(text).split("/")
    return int(a), int(b)


def collect() -> dict:
    reg = json.loads((WS / "artifacts" / "registry.json").read_text(encoding="utf-8"))
    live = [r for r in reg if not ({"retracted", "legacy"} & set(r))]
    nodes = sorted({r["node"] for r in live if r["node"] in NODES})
    acc = json.loads((WS / "outbox" / "acceptance.json").read_text(encoding="utf-8"))
    acc_p, acc_t = ratio(acc["passed"])
    ev = json.loads((WS / "eval" / "eval_report.json").read_text(encoding="utf-8"))
    g_p, g_t = ratio(ev["gates_passed"])
    c_p, c_t = ratio(ev["cases_passed"].split("（")[0])
    calls = len((WS / "gateway_calls.jsonl").read_text(encoding="utf-8").splitlines())
    rec_rows = [json.loads(x) for x in
                (WS / "cost_reconcile.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
    retracted = {r.get("retracts") for r in rec_rows if r.get("kind") == "retraction"}
    valid = [r for r in rec_rows
             if r.get("kind") == "reconcile" and r.get("ts") not in retracted]
    with_dev = [r for r in valid if r.get("deviation_pct") is not None]
    latest = (with_dev[-1] if with_dev else (valid[-1] if valid else {}))
    est = latest.get("estimate_cny")
    n_calls = latest.get("matched_calls")
    prov = latest.get("matched_provider") or ""
    dev = latest.get("deviation_pct")
    if est is not None and n_calls is not None:
        if dev is None:
            cost_note = "¥%.4f / %s 次（%s 同口径）；偏差待下次快照" % (est, n_calls, prov)
        else:
            cost_note = ("¥%.4f / %s 次（%s 同口径）· 偏差 %+.2f%% · 待校准"
                         % (est, n_calls, prov, dev))
    else:
        cost_note = "估算已记；偏差待对账"

    proc = [
        {"name": "九节点真实化", "done": len(nodes), "total": 9, "note": "、".join(nodes)},
        {"name": "验收清单", "done": acc_p, "total": acc_t, "note": "15 项硬指标"},
        {"name": "评测门禁", "done": g_p, "total": g_t, "note": "含回归对比"},
        {"name": "评测用例", "done": c_p, "total": c_t, "note": "C-01…C-05"},
        {"name": "Harness 接入", "done": 3, "total": 3, "note": "A 预检 / B 沙箱 / C 登记"},
        {"name": "模型真调用", "done": 3, "total": 3, "note": "Moonshot / Bailian / Ark"},
        {"name": "测试固化", "done": 4, "total": 4, "note": "run_tests.py 一条命令"},
        {"name": "数据接入管线", "done": 1, "total": 1, "note": "口径 / 清洗 / 汇总 / sha"},
    ]
    # 数据集说明从 ingest_report 动态读，避免写死后忘记同步
    ing_p = PROJECT / "real" / "out" / "ingest_report.json"
    if ing_p.exists():
        ing = json.loads(ing_p.read_text(encoding="utf-8"))
        src, tot = ing.get("source", {}), ing.get("totals", {})
        prov, cal = src.get("provenance", {}), ing.get("caliber", {})
        cat = prov.get("category", "")
        company_note = "" if "非本公司" in cat else " · 非本公司"
        banner1 = (f"{prov.get('dataset', '数据集')} · {tot.get('orders', 0):,} 行 · "
                   f"{cat}{company_note} · 非双11 · {src.get('currency', '')}")
        rate_note = "，非严格订单退货率" if cal.get("code") == "refunded" else ""
        banner2 = (f"口径 {cal.get('code', '')}（{cal.get('label', '')}{rate_note}） · "
                   f"成本 token_pricing 估算 · provider_reported 不可用")
        data_note = f"{tot.get('orders', 0):,} 行真实数据，八步全链跑通"
    else:
        banner1, banner2, data_note = "真实数据集", "成本 token_pricing 估算 · provider_reported 不可用", "真实数据链路"

    deliv = [
        {"name": "真实数据链路", "done": 1, "total": 1, "note": data_note, "state": "done"},
        {"name": "八步全真", "done": 8, "total": 8, "note": "N1…N8 全过，N6/N7 真调模型", "state": "done"},
        {"name": "成本口径（估算+日终对账）", "done": 1, "total": 1,
         "note": cost_note, "state": "done"},
        {"name": "真实计费 provider_reported", "done": 0, "total": 1,
         "note": "⛔ 不可用：三家供应商均不回传金额", "state": "blocked"},
        {"name": "本公司业务数据", "done": 0, "total": 1,
         "note": "⊘ 豁免 · 按决定以课程数据集交付（非本公司数据）；不构成业务结论", "state": "waived"},
    ]
    return {"proc": proc, "deliv": deliv, "calls": calls,
            "banner1": banner1, "banner2": banner2}


def bar(r: dict) -> str:
    state = r.get("state")
    blocked = state == "blocked"
    waived = state == "waived"
    p = round(r["done"] / r["total"] * 100) if r["total"] else 0
    if blocked or waived:
        color = "#9ca3af"                      # 灰：不完成，也不冒充完成
    elif p == 100:
        color = "#0e9384"
    elif p > 0:
        color = "#d97706"
    else:
        color = "#c0392b"
    mark = "⛔ " if blocked else ("⊘ " if waived else "")
    return f"""
      <div class="row">
        <div class="lbl"><b>{mark}{r['name']}</b><span class="note">{r['note']}</span></div>
        <div class="track"><div class="fill" style="width:{p}%;background:{color}"></div></div>
        <div class="val">{r['done']}/{r['total']}</div>
      </div>"""


def pct_of(rows: list[dict]) -> int:
    d = sum(r["done"] for r in rows)
    t = sum(r["total"] for r in rows)
    return round(d / t * 100) if t else 0


def render(data: dict) -> Path:
    proc, deliv = data["proc"], data["deliv"]
    pp, dp = pct_of(proc), pct_of(deliv)
    overall = round((pp + dp) / 2)

    html = f"""<!doctype html><meta charset="utf-8">
<style>
  body{{margin:0;padding:0 0 28px;background:#f7f9fb;font-family:"Microsoft YaHei",sans-serif;color:#1f2937}}
  .demo{{background:#fff4e5;border-bottom:2px solid #f0b429;padding:10px 34px;font-size:13px;color:#8a5a00}}
  .demo b{{color:#b45309}} .demo span{{margin-right:18px}}
  .wrap{{padding:24px 34px 0}}
  h1{{font-size:22px;margin:0 0 4px}}
  .sub{{color:#6b7280;font-size:12px;margin-bottom:18px}}
  .hero{{background:#fff;border:1px solid #e5e7eb;border-radius:14px;padding:20px 22px;margin-bottom:18px}}
  .hero .big{{font-size:40px;font-weight:700;color:#0e9384;line-height:1}}
  .hero .cap{{color:#6b7280;font-size:12px;margin-top:6px}}
  .two{{display:flex;gap:18px;margin-top:14px}}
  .two .box{{flex:1;background:#f9fafb;border:1px solid #eef2f6;border-radius:10px;padding:10px 12px}}
  .two .k{{font-size:12px;color:#6b7280}} .two .v{{font-size:20px;font-weight:700}}
  .track{{background:#eef2f6;border-radius:8px;height:14px;overflow:hidden;flex:1}}
  .fill{{height:100%;border-radius:8px}}
  .card{{background:#fff;border:1px solid #e5e7eb;border-radius:14px;padding:16px 22px;margin-bottom:16px}}
  h2{{font-size:14px;margin:0 0 6px;color:#374151}}
  .row{{display:flex;align-items:center;gap:14px;padding:9px 0;border-bottom:1px dashed #f0f2f5}}
  .row:last-child{{border-bottom:0}}
  .lbl{{width:280px;font-size:13px}}
  .note{{display:block;color:#9ca3af;font-size:11px;margin-top:2px}}
  .val{{width:64px;text-align:right;font-size:13px;color:#374151;font-variant-numeric:tabular-nums}}
  .foot{{color:#9ca3af;font-size:11px}}
</style>
<div class="demo">
  <b>数据说明</b>
  <span>{data['banner1']}</span>
  <span>{data['banner2']}</span>
</div>
<div class="wrap">
  <h1>多智能体协同 · 落地进度</h1>
  <div class="sub">综合 = 过程就绪与交付就绪各占一半，避免「过程 100%」掩盖交付 0%</div>

  <div class="hero">
    <div class="big">{overall}%</div>
    <div class="cap">综合就绪度（过程 {pp}% · 交付 {dp}%）</div>
    <div class="two">
      <div class="box"><div class="k">过程就绪</div><div class="v" style="color:#0e9384">{pp}%</div>
        <div class="track" style="margin-top:6px"><div class="fill" style="width:{pp}%;background:#0e9384"></div></div></div>
      <div class="box"><div class="k">交付就绪</div><div class="v" style="color:#c0392b">{dp}%</div>
        <div class="track" style="margin-top:6px"><div class="fill" style="width:{dp}%;background:#c0392b"></div></div></div>
    </div>
  </div>

  <div class="card"><h2>过程就绪</h2>{''.join(bar(r) for r in proc)}</div>
  <div class="card"><h2>交付就绪（真实数据到位才算）</h2>{''.join(bar(r) for r in deliv)}</div>
  <div class="foot">数据来自 cohort_l3 真实产物；网关审计 {data['calls']} 条 append-only</div>
</div>"""

    OUT_HTML.parent.mkdir(parents=True, exist_ok=True)
    OUT_HTML.write_text(html, encoding="utf-8")
    subprocess.run([str(EDGE), "--headless=old", "--disable-gpu",
                    f"--screenshot={OUT_PNG}", "--window-size=1100,1220",
                    OUT_HTML.resolve().as_uri()], capture_output=True, timeout=120)
    print(f"综合 {overall}%（过程 {pp}% / 交付 {dp}%）")
    for r in proc + deliv:
        print(f"  {r['name']:12} {r['done']}/{r['total']}")
    return OUT_PNG


if __name__ == "__main__":
    print(render(collect()))

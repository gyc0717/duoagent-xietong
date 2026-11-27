#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""八步全链（真实数据集版，数据源/口径/币种/标注全部参数化）

N1 派单 → N2 接入 → N3 图表 → N4 索引 → N5 沙箱 → N6 二审 → N7 三审 → N8 收口

- N2/N3/N4/N5/N8 是确定性脚本，数字来自 ingest_report.json；
- N6/N7 走网关 /model 真调（Moonshot 二审、Ark 三审），只传 alias；
- 每一步产出写进 out/chain_summary.json，失败即停（不继续下一步）；
- 数据源、口径、币种、来源标注由命令行参数决定，报告里必须原样带出。

用法：
  python real/chain_uci.py \
      --data real/data/课程电商数据集_退款.csv \
      --caliber refunded --currency USD \
      --dataset-label 课程电商数据集 \
      --category-label 家用电器/电子产品 \
      --label "课程电商数据集 · 非本公司 · 非双11 · USD"
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parent
OUT = HERE / "out"
PY = sys.executable
GATEWAY = "http://127.0.0.1:8733"
DEFAULT_DATA = HERE / "data" / "课程电商数据集_退款.csv"
LABEL = "课程电商数据集 · 非本公司 · 非双11 · USD"
CALIBER = "refunded"
CURRENCY = "USD"
DATASET_LABEL = "课程电商数据集"
CATEGORY_LABEL = "家用电器/电子产品"


def token() -> str:
    p = PROJECT / ".secrets.json"
    d = json.loads(p.read_text(encoding="utf-8"))
    return d["L3_TOKENS"]["harness"]


RUN_ID = "chain-init"


def call_model(alias: str, prompt: str, max_tokens: int = 400) -> dict:
    body = json.dumps({"alias": alias, "run_id": RUN_ID,
                       "max_tokens": max_tokens,
                       "messages": [{"role": "user", "content": prompt}]}).encode()
    req = urllib.request.Request(GATEWAY + "/model", data=body, method="POST")
    req.add_header("X-L3-Token", token())
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=240) as r:
            return json.loads(r.read())
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


def run(cmd: list[str]) -> tuple[bool, str]:
    p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                       errors="replace", cwd=str(PROJECT),
                       env={**dict(__import__("os").environ), "PYTHONIOENCODING": "utf-8"})
    return p.returncode == 0, (p.stdout or "") + (p.stderr or "")


def main() -> int:
    global LABEL, CALIBER, CURRENCY, DATASET_LABEL, CATEGORY_LABEL
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=str(DEFAULT_DATA))
    ap.add_argument("--caliber", default=CALIBER, choices=["started", "completed", "refunded"])
    ap.add_argument("--currency", default=CURRENCY, choices=["CNY", "GBP", "USD"])
    ap.add_argument("--dataset-label", default=DATASET_LABEL)
    ap.add_argument("--category-label", default=CATEGORY_LABEL)
    ap.add_argument("--label", default=LABEL)
    args = ap.parse_args()
    data = Path(args.data)
    if not data.exists():
        print(f"找不到数据：{data}")
        return 2
    LABEL, CALIBER, CURRENCY = args.label, args.caliber, args.currency
    DATASET_LABEL, CATEGORY_LABEL = args.dataset_label, args.category_label
    SYM = {"CNY": "¥", "GBP": "£", "USD": "$"}.get(CURRENCY, "")

    chain: list[dict] = []
    global RUN_ID
    run_id = "chain-" + time.strftime("%H%M%S")
    RUN_ID = run_id

    import importlib.util as _il
    _spec = _il.spec_from_file_location("cost_probe", str(HERE / "cost_probe.py"))
    _cp = _il.module_from_spec(_spec); _spec.loader.exec_module(_cp)
    snap_before = _cp.snapshot(run_id, "before")
    print(f"  · 余额 before: {snap_before}" if snap_before else "  · 余额 before 取数失败")

    def step(node: str, name: str, ok: bool, detail: str, artifact: str = "") -> bool:
        chain.append({"node": node, "name": name, "ok": ok,
                      "status": "ok" if ok else "failed",
                      "detail": detail[:400], "artifact": artifact})
        print(f"  {'✓' if ok else '✗'} {node} {name}: {detail[:100]}")
        return ok

    # N1 派单
    step("N1", "派单与口径声明", True,
         f"任务：真数据全链；数据源={data.name}；口径={CALIBER}；币种={CURRENCY}；标注={LABEL}")

    # N2 接入
    ok, out = run([PY, str(HERE / "ingest.py"), str(data),
                "--caliber", CALIBER, "--currency", CURRENCY,
                "--dataset-label", DATASET_LABEL, "--category-label", CATEGORY_LABEL])
    ing = json.loads((OUT / "ingest_report.json").read_text(encoding="utf-8")) if ok else {}
    if not step("N2", "数据接入与清洗", ok,
                f"{ing.get('clean',{}).get('rows')} 行 / 丢弃 {ing.get('clean',{}).get('dropped')} / "
                f"sha {ing.get('source',{}).get('sha256','')[:12]}",
                "real/out/ingest_report.json"):
        return finish(chain)

    # N3 图表
    ok, out = run([PY, str(HERE / "charts_real.py")])
    ok = ok and (OUT / "chart_data.json").exists()
    cd = json.loads((OUT / "chart_data.json").read_text(encoding="utf-8")) if ok else {}
    if not step("N3", "确定性生成图表", ok,
                f"{len(cd)} 组数据 · 图表 3 张（数值锁在 chart_data.json）",
                "real/out/gmv_by_category.svg"):
        return finish(chain)

    # N4 索引
    ok, out = run([PY, str(HERE / "file_index.py")])
    idx = json.loads((OUT / "file_index.json").read_text(encoding="utf-8")) if ok else {}
    if not step("N4", "本地文件索引", ok,
                f"索引 {idx.get('count')} 个文件 · 跳过 {len(idx.get('skipped') or [])}",
                "real/out/file_index.json"):
        return finish(chain)

    # N5 沙箱
    ok, out = run([PY, str(HERE / "verify.py")])
    ev = json.loads((OUT / "execution_evidence.json").read_text(encoding="utf-8")) if ok else {}
    if not step("N5", "确定性沙箱 9 类检查", ok and ev.get("ok", True),
                f"{ev.get('checks_passed')} · {ev.get('evidence_source')}",
                "real/out/execution_evidence.json"):
        return finish(chain)

    # N6 二审（真模型）
    bal_before = _cp.moonshot_balance()
    totals = ing.get("totals", {})
    caliber_label = ing.get("caliber", {}).get("label", CALIBER)
    rate_label = "退款行占比" if CALIBER == "refunded" else "退货率"
    prompt6 = (f"你是二审。请基于以下口径给出不超过 120 字的中文复核意见，指出一个风险点：\n"
               f"数据集：{LABEL}（金额单位 {CURRENCY} {SYM}，品类为{CATEGORY_LABEL}）\n"
               f"订单数={totals.get('orders')} GMV={totals.get('gmv')} "
               f"{rate_label}={totals.get('return_line_share_pct')}% 退款={totals.get('refund_amount')} "
               f"口径={caliber_label}。")
    r6 = call_model("moonshot-lite", prompt6, 900)
    if not step("N6", "二审（Moonshot 真调用）", r6.get("ok") is True,
                (r6.get("content") or r6.get("error", ""))[:200],
                f"model:{r6.get('model_id')} · {r6.get('tokens',{}).get('total')} tok · "
                f"{r6.get('cost_source')}"):
        return finish(chain)
    bal_after = _cp.moonshot_balance()
    real_delta = None
    if bal_before is not None and bal_after is not None:
        real_delta = round(max(0.0, bal_before - bal_after), 6)
        r6["cost_source"] = "balance_delta"
        r6["cost_cny"] = real_delta
        print("  · 余额差（仅供参考）：跑前 ¥%.4f → 跑后 ¥%.4f，"
              "实际扣费 ¥%.4f（余额接口有延迟，不能当实时账单）"
              % (bal_before, bal_after, real_delta))
    review6 = r6.get("content", "")

    # N7 三审（真模型）
    prompt7 = (f"你是三审。请用不超过 100 字给出终审结论，并明确它只是管线验证、不能当业务结论：\n"
               f"二审意见：{review6}\n数据口径：{LABEL}（金额单位 {CURRENCY}），"
               f"{rate_label} {totals.get('return_line_share_pct')}%。")
    r7 = call_model("ark-lite", prompt7, 400)
    if not step("N7", "三审（Ark 真调用）", r7.get("ok") is True,
                (r7.get("content") or r7.get("error", ""))[:200],
                f"model:{r7.get('model_id')} · {r7.get('tokens',{}).get('total')} tok · "
                f"{r7.get('cost_source')}"):
        return finish(chain)

    # N8 收口
    ok, out = run([PY, str(HERE / "report.py")])
    md = OUT / "final_report.md"
    ok = ok and md.exists()
    head = md.read_text(encoding="utf-8")[:1200] if ok else ""
    with md.open("a", encoding="utf-8") as f:
        f.write(f"\n\n---\n\n## 数据来源声明\n\n- {LABEL}\n"
                f"- 源文件：`{data.name}`\n"
                f"- 币种：{CURRENCY}（{SYM}），不跨币种换算\n"
                f"- 口径：{caliber_label}（{CALIBER}）\n"
                f"- 地区字段为匿名分区（地区A/B…），非真实省份；源无退货原因与退款金额列，留空不编造\n"
                f"- 该报告只证明管线可跑通，**不构成任何业务结论**。\n\n"
                f"## 二审意见（Moonshot）\n\n{review6}\n\n"
                f"## 三审意见（Ark）\n\n{r7.get('content','')}\n")
    if not step("N8", "收口报告", ok, f"{len(head)} 字符（含声明）", "real/out/final_report.md"):
        return finish(chain)

    snap_after = _cp.snapshot(run_id, "after")
    print(f"  · 余额 after: {snap_after}" if snap_after else "  · 余额 after 取数失败")
    return finish(chain, run_id=run_id, snap_before=snap_before, snap_after=snap_after)


def finish(chain: list[dict], run_id: str = "", snap_before=None, snap_after=None) -> int:
    ok_n = sum(1 for c in chain if c["ok"])
    payload = {"label": LABEL, "run_id": run_id,
               "snap_before": snap_before, "snap_after": snap_after,
               "steps": chain, "passed": ok_n, "total": len(chain),
               "ok": ok_n == len(chain)}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "chain_summary.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                                            encoding="utf-8")
    print(f"\n八步结果：{ok_n}/{len(chain)} 通过 · {LABEL}")
    print(f"汇总：{OUT / 'chain_summary.json'}")
    return 0 if payload["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())

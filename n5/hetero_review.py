#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""N5 一审内部 · 异构交叉复核调用点（reviewer 厂商必须 ≠ 被审工件厂商）

上一版把 reviewer 写死成 Kimi，用 Kimi 去审 Kimi 画的图 —— 那是同源，价值打折甚至反向。
现在改成：从登记表读出被审工件的 producer 厂商，再断言 reviewer 厂商不同，同厂直接拒登。

跑法：
  python n5/hetero_review.py            # 默认 qwen（审 Kimi 的图 = 真异构）
  HETERO_PROVIDER=kimi python n5/hetero_review.py   # 会被闸拦下（演示用）
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT / "n3"))
sys.path.insert(0, str(PROJECT / "n1q"))
sys.path.insert(0, str(PROJECT / "l3"))

import kimi_client  # noqa: E402
import qwen_client  # noqa: E402
from workspace import Workspace  # noqa: E402

OUT = PROJECT / "n5" / "out"
NODE = "N5"

SYSTEM = """你是独立复核员，和被审方不是同一家厂商。任务不是夸，是找错，而且只报**真错**。
只输出一个 JSON 对象，不要 markdown 代码块、不要解释，格式：
{"verdict":"PASS"|"FAIL",
 "checked":["逐项列出你实际核对过的点"],
 "findings":[{"severity":"blocker"|"major"|"minor","item":"缺陷是什么","evidence":"具体证据（数字/位置）"}]}
硬规则：
1. findings 里**只放确实有问题的项**。核对后没问题的项不要写进 findings，写进 checked 即可；
2. 不要写「matches / 一致 / 无差异」却同时标一个 severity —— 那是自相矛盾；
3. 数值类判断必须给出算式（如 1032/48216=0.0214）；
4. 只有「数值与数据工件不一致」或「口径写错」才用 blocker；可读性问题用 major/minor；
5. 全部核对无误时 verdict=PASS、findings=[]。"""


def strip_json(text: str) -> str:
    t = re.sub(r"^```[a-zA-Z]*\s*", "", text.strip())
    t = re.sub(r"\s*```$", "", t.strip())
    i, j = t.find("{"), t.rfind("}")
    return t[i:j + 1] if i >= 0 and j > i else t


def latest_under_review(ws: Workspace) -> list[dict]:
    """取最新版本的 N3 视觉工件（producer = Moonshot）。"""
    rows = [r for r in ws._read_registry() if r["node"] == "N3" and r["role"] == "kimi_image"]
    seen: dict[str, dict] = {}
    for r in rows:
        if r["name"] not in seen or r["version"] > seen[r["name"]]["version"]:
            seen[r["name"]] = r
    return list(seen.values())


def ask(provider: str, prompt: str):
    if provider == "qwen":
        model = os.environ.get("HETERO_MODEL", "qwen-max")
        usage = qwen_client.Usage()
        res = qwen_client.chat([{"role": "system", "content": SYSTEM},
                                {"role": "user", "content": prompt}],
                               model=model, max_tokens=3000, usage=usage)
        return res, usage, model, usage.cost_cny(model)
    usage = kimi_client.Usage()
    res = kimi_client.chat_ex([{"role": "system", "content": SYSTEM},
                               {"role": "user", "content": prompt}],
                              max_tokens=8000, usage=usage)
    return res, usage, kimi_client.MODEL, usage.cost_cny(kimi_client.MODEL)


def main() -> int:
    provider = os.environ.get("HETERO_PROVIDER", "qwen").lower()
    reviewer_vendor = {"qwen": "Qwen", "kimi": "Moonshot"}[provider]

    ws = Workspace(PROJECT / "cohort_l3").ensure()
    targets = latest_under_review(ws)
    if not targets:
        print("没有可复核的 N3 工件")
        return 1

    data = json.loads((PROJECT / "real" / "out" / "structured_data.json").read_text(encoding="utf-8"))
    visuals = {}
    for r in targets:
        body = json.loads((ws.root / r["uri"]).read_text(encoding="utf-8"))
        if body.get("svg"):
            visuals[r["name"]] = body["svg"]
    print(f"被审工件：{[(r['id'], r['name'], r.get('vendor')) for r in targets]}")
    print(f"复核方：{reviewer_vendor} / provider={provider}")

    target_ids = [r["id"] for r in targets]
    conflicts = ws.hetero_conflicts(reviewer_vendor, target_ids)
    if conflicts:
        print(f"✗ 异构闸拦住：{json.dumps(conflicts, ensure_ascii=False)}")
        print("  → 同厂互审不算异构复核，拒绝登记。换一家厂商再跑。")
        return 2

    prompt = ("待复核内容（数据工件 + 视觉层 SVG 源码）：\n"
              + json.dumps({"structured_data": data, "visuals": visuals}, ensure_ascii=False))
    res, usage, model, cost = ask(provider, prompt)
    result = None
    for attempt in (1, 2, 3):
        try:
            r = json.loads(strip_json(res["content"]))
            assert r.get("verdict") in ("PASS", "FAIL")
            assert isinstance(r.get("findings"), list)
            result = r
            break
        except Exception as e:  # noqa: BLE001
            print(f"  第 {attempt} 次输出不可用：{e}")
            if attempt == 3:
                break
            res, u2, _, c2 = ask(provider, prompt + "\n上次输出不是合法 JSON，请只输出 JSON。")
            usage.prompt_tokens += u2.prompt_tokens
            usage.completion_tokens += u2.completion_tokens
            usage.calls += u2.calls
            cost += c2
    if result is None:
        return 1

    result.update({"reviewer": reviewer_vendor, "reviewer_model": model,
                   "reviewed_ids": target_ids,
                   "reviewed_names": [r["name"] for r in targets],
                   "vendor_distinct": True,
                   "usage": {"calls": usage.calls, "prompt_tokens": usage.prompt_tokens,
                             "completion_tokens": usage.completion_tokens,
                             "latency_ms": usage.latency_ms, "est_cost_cny": cost}})

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "hetero_review.json").write_text(json.dumps(result, ensure_ascii=False, indent=2),
                                            encoding="utf-8")

    rec = ws.register_review(node=NODE, role="qwen_hetero", name="hetero_review", payload=result,
                             reviewer_vendor=reviewer_vendor, target_ids=target_ids,
                             provenance=f"异构复核 / reviewer={reviewer_vendor}/{model} / 被审={targets[0].get('vendor')}")
    ws.ledger({"kind": "hetero_review", "verdict": result["verdict"],
               "findings": len(result["findings"]), "reviewer": reviewer_vendor,
               "reviewed": target_ids, "tokens": usage.total_tokens, "est_cny": cost})

    print(json.dumps({"verdict": result["verdict"], "findings": result["findings"],
                      "artifact": rec["uri"], "tokens": usage.total_tokens,
                      "latency_ms": usage.latency_ms, "est_cny": cost},
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

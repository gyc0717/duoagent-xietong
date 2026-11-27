#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""N1Q 证据优先链路 v2 —— 口径分组、禁止跨组替代

按二审返工要求：
  1) query 用原任务原文，任何改动必须在 query_diff 里显式列出（v12 曾静默改题，已回退）；
  2) 指标分三组：退货率（须带数值）／退货行为／投诉售后，禁止跨组替代；
  3) 证据准入＝「指标词与数值同句共现」；只有定性表述的文章不计入；
  4) 答案必须诚实区分口径：只有投诉数据时，必须明说「未检索到退货率公开数值」；
  5) 凑不出 ≥2 条「退货率数值」证据页 → N1Q 判失败，不许补位。

跑法：python n1q/evidence_pipeline.py
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT / "n1q"))
sys.path.insert(0, str(PROJECT / "l3"))

import qwen_client as qwen  # noqa: E402
from verify_source import _looks_like_challenge, fetch, norm, page_text  # noqa: E402
from workspace import Workspace  # noqa: E402

OUT = PROJECT / "n1q" / "out"
CANDIDATES = OUT / "candidates.json"

QUERY_ORIGINAL = ("2026 年双十一期间家电类目退货率的最新公开报道有哪些？"
                  "请给出 2-3 条带链接、发布时间和原文引用的来源。")
QUERY_DIFF = {
    "v12": "被静默改成『2026 双11 家电 退货率 / 投诉』——已回退",
    "v13": "恢复原任务原文，未做任何改写",
}

# 顺序即优先级：先命中「退货率」的句子不再计入「退货行为」
GROUPS = [
    ("退货率", ("退货率", "退货比率", "退货比例为")),
    ("退货行为", ("退换货", "退货")),
    ("投诉售后", ("投诉", "售后")),
]
CATEGORY = ("家电", "电器", "冰箱", "空调", "洗衣机", "电视", "厨电")
TIME = ("2026", "双11", "双十一", "11月")
NUM = re.compile(r"\d[\d,.]*\s*(?:%|％|个百分点|万|亿|单|件|起|倍)")
# 退货率必须「数值紧挨着指标词」：词在前（退货率达 3.1%），或数在前（3.1% 的退货率）
RR_PROX = re.compile(r"退货率[^。；;\n]{0,6}?(?:为|达|约|是|：|:)?\s*\d[\d,.]*\s*(?:%|％|个百分点)"
                     r"|(\d[\d,.]*\s*(?:%|％|个百分点))\s*的?退货率")
JUNK_MARKS = ("已知事实", "示意", "以下数据对比", "目录", "摘要：", "点击查看", "登录后")

SENT_SPLIT = re.compile(r"(?<=[。！？；;\n])")


def sha256(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def classify_text(text: str) -> dict:
    """按句切分，找出「指标词 + 数值」同句共现的句子，归到对应口径组。"""
    out: dict[str, list[str]] = {g: [] for g, _ in GROUPS}
    has_category = any(c in text for c in CATEGORY)
    has_time = any(t in text for t in TIME)
    for sent in SENT_SPLIT.split(text):
        s = re.sub(r"\s+", " ", sent).strip()
        if len(s) < 8 or not NUM.search(s):
            continue
        for g, kws in GROUPS:
            if not any(k in s for k in kws):
                continue
            if g == "退货率":
                # 退货率组：数值必须紧挨指标词，且不能是目录/示意表这类垃圾句
                if not RR_PROX.search(s) or any(j in s for j in JUNK_MARKS):
                    break
            out[g].append(s[:140])
            break
    return {"groups": out, "has_category": has_category, "has_time": has_time,
            "counts": {g: len(v) for g, v in out.items()}}


def collect(urls: list[dict]) -> dict:
    audit, pages = [], []
    for i, c in enumerate(urls, 1):
        url = c["url"]
        rec = {"idx": i, "url": url, "hint": c.get("hint", "")}
        res = fetch(url)
        if not res["ok"]:
            body = res.get("body") or ""
            if _looks_like_challenge(body):
                rec.update(status="blocked", reason=f"反爬挑战页(HTTP {res.get('status')})")
            elif res.get("status") in (404, 410):
                rec.update(status="fabricated", reason=f"HTTP {res.get('status')}")
            else:
                rec.update(status="blocked", reason=res.get("error"))
            audit.append(rec)
            continue
        if _looks_like_challenge(res["html"]):
            rec.update(status="blocked", reason=f"反爬挑战页(HTTP {res['status']})")
            audit.append(rec)
            continue

        text = re.sub(r"\s+", " ", page_text(res["html"]))
        cls = classify_text(text)
        if not cls["has_category"] or not cls["has_time"]:
            rec.update(status="discarded",
                       reason=f"品类{'✓' if cls['has_category'] else '✗'} "
                              f"时间{'✓' if cls['has_time'] else '✗'}")
            audit.append(rec)
            continue
        if sum(cls["counts"].values()) == 0:
            rec.update(status="discarded", reason="无「指标词+数值」同句共现（纯定性）")
            audit.append(rec)
            continue

        rec.update(status="evidence", bytes=res["bytes"], chars=len(text),
                   sha256=sha256(text), counts=cls["counts"], groups=cls["groups"])
        audit.append(rec)
        pages.append(rec)
    return {"audit": audit, "pages": pages}


SYSTEM = """你是检索结论撰写员，必须严格区分口径。规则：
1. 只能使用我给的摘录，禁止引入外部知识；
2. 若【退货率】组为空，必须在 answer 开头明确写：「未检索到 2026 双11 家电退货率的公开数值」；
3. 投诉/售后数据只能作为补充，且必须写明「口径：投诉」；
4. 每个数字后跟来源标记，如 2.14%[R1]；退货率数字用 R 前缀，投诉数字用 C 前缀；
5. 禁止拿投诉数字回答退货率问题。
只输出 JSON：{"answer":"<=250字","numbers":[{"value":"2.14%","source":"R1","caliber":"退货率|投诉"}]}"""


def write_answer(pages: list[dict]) -> dict:
    blocks = []
    rid = cid = 0
    for p in pages:
        for s in p["groups"].get("退货率", []):
            rid += 1
            blocks.append(f"[R{rid}] {p['url']}\n  - {s}")
        for s in p["groups"].get("投诉售后", []):
            cid += 1
            blocks.append(f"[C{cid}] {p['url']}\n  - {s}")
    usage = qwen.Usage()
    res = qwen.chat([{"role": "system", "content": SYSTEM},
                     {"role": "user", "content": "摘录：\n" + "\n".join(blocks)}],
                    max_tokens=1200, usage=usage)
    m = re.search(r"\{.*\}", res["content"], re.S)
    try:
        out = json.loads(m.group(0)) if m else {}
    except Exception:  # noqa: BLE001
        out = {}
    out["_usage"] = {"tokens": usage.total_tokens, "cost": usage.cost_cny()}
    return out


def verify_answer(ans: dict, pages: list[dict], texts: dict[str, str]) -> dict:
    url_by_tag = {}
    rid = cid = 0
    for p in pages:
        for _ in p["groups"].get("退货率", []):
            rid += 1
            url_by_tag[f"R{rid}"] = ("退货率", p["url"])
        for _ in p["groups"].get("投诉售后", []):
            cid += 1
            url_by_tag[f"C{cid}"] = ("投诉", p["url"])

    bad = []
    for n in ans.get("numbers") or []:
        val, src, cal = str(n.get("value", "")), str(n.get("source", "")), n.get("caliber")
        tag = url_by_tag.get(src)
        if not tag:
            bad.append({"value": val, "source": src, "why": "来源不在白名单"})
            continue
        g, url = tag
        probe = norm(val).replace("%", "").replace("％", "")
        if probe not in norm(texts.get(url, "")).replace("%", "").replace("％", ""):
            bad.append({"value": val, "source": src, "why": "该数字不在已抓正文中"})
        if cal and cal != g:
            bad.append({"value": val, "source": src, "why": f"口径标注不符：声明 {cal} 实为 {g}"})
    return {"checked": len(ans.get("numbers") or []), "violations": bad, "pass": not bad}


def main() -> int:
    urls = json.loads((Path(sys.argv[1]) if len(sys.argv) > 1 else CANDIDATES)
                      .read_text(encoding="utf-8"))
    ws = Workspace(PROJECT / "cohort_l3").ensure()
    print(f"候选 {len(urls)} 条（query 用原任务原文）")

    col = collect(urls)
    for r in col["audit"]:
        print(f"  [{r['status']:10}] {r['url'][:58]:58} {r.get('reason','')[:32]} "
              f"{r.get('counts','')}")

    pages = col["pages"]
    n_rr = sum(1 for p in pages if p["counts"].get("退货率", 0) > 0)
    print(f"\n证据页 {len(pages)} 条，其中含「退货率数值」的 {n_rr} 条")

    texts = {}
    for p in pages:
        r = fetch(p["url"])
        texts[p["url"]] = page_text(r["html"]) if r["ok"] else ""

    if pages:
        ans = write_answer(pages)
    else:
        ans = {"answer": "未检索到 2026 双11 家电退货率的公开数值（候选页全部不可用）",
               "numbers": []}
    verdict = verify_answer(ans, pages, texts)

    # 终态三分：ok=有 >=2 条退货率数值证据；no_public_data=查完了确实没有公开数值；
    # failed=执行出了问题（抓取全挂、后验不通过）。语义必须分开，不能混成「失败」。
    if n_rr >= 2 and verdict["pass"]:
        status = "ok"
    elif n_rr == 0 and len(pages) > 0 and verdict["pass"]:
        status = "no_public_data"
    else:
        status = "failed"
    artifact = {
        "node": "N1Q", "kind": "evidence_first_v2",
        "query": QUERY_ORIGINAL, "query_diff": QUERY_DIFF,
        "semantics": "脚本抓证据 + 模型只用证据写结论；口径分三组，禁止跨组替代",
        "evidence_pages": [{k: p[k] for k in ("url", "bytes", "sha256", "counts", "groups")}
                           for p in pages],
        "return_rate_pages": n_rr,
        "result": ans, "post_verification": verdict, "audit": col["audit"],
        "counts": {"candidates": len(urls), "evidence": len(pages), "return_rate_pages": n_rr,
                   "blocked": sum(1 for r in col["audit"] if r["status"] == "blocked"),
                   "fabricated": sum(1 for r in col["audit"] if r["status"] == "fabricated"),
                   "discarded": sum(1 for r in col["audit"] if r["status"] == "discarded")},
        "status": status,
    }
    (OUT / "N1Q_evidence.json").write_text(json.dumps(artifact, ensure_ascii=False, indent=2),
                                           encoding="utf-8")

    rec = None
    if status == "ok":
        rec = ws.register(node="N1Q", role="qwen_search", name="sources", payload=artifact,
                          content_mode="FULLTEXT", trust_level="untrusted", channel="data_only",
                          provenance="N1Q 证据优先 v2（口径分组、禁止跨组替代）")
        print("登记:", rec["id"], rec["uri"])
    elif status == "no_public_data":
        # 无数据也是查完后的结论：登记成失败证据，让台账带 URI，链条不悬空
        rec = ws.register(node="N1Q", role="qwen_search", name="no_public_data", payload=artifact,
                          content_mode="FULLTEXT", trust_level="untrusted", channel="data_only",
                          provenance="N1Q 无公开数据终态（候选与处置全留痕）")
        print("登记(no_public_data):", rec["id"], rec["uri"])

    ws.ledger({"kind": "n1q_evidence_v2", "status": status, "counts": artifact["counts"],
               "artifact": rec["uri"] if rec else None,
               "artifact_id": rec["id"] if rec else None,
               "rule": "退货率证据要求「数值紧挨指标词」，见 n1q/evidence_pipeline.py RR_PROX"})

    print(json.dumps({"status": status, "return_rate_pages": n_rr,
                      "counts": artifact["counts"],
                      "post_verification": {"pass": verdict["pass"],
                                            "violations": verdict["violations"][:3]},
                      "answer": (ans.get("answer") or "")[:200]}, ensure_ascii=False, indent=2))
    return 0 if status == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())

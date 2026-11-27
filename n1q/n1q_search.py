#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""N1Q · 千问联网检索节点（真调 DashScope + 真联网）

跑完这一节点会产出四样东西，缺一样都算失败：
  1. 带引用的资料工件（title / url / published_at / quote / confidence）
  2. 引用契约校验结果（缺字段即拒绝进入上下文）
  3. URL 可达性实证（脚本产事实：这条引用到底能不能打开）
  4. P0 注入扫描结果（命中即隔离，原文完整保留，不裁剪事实）

工件一律 trust_level=untrusted / channel=data_only，永不允许进指令通道。

跑法：python n1q/n1q_search.py ["检索问题"]
"""
from __future__ import annotations

import json
import re
import socket
import sys
import urllib.error
import urllib.request
from datetime import date
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT / "n1q"))
sys.path.insert(0, str(PROJECT / "l3"))

import qwen_client as qwen  # noqa: E402
from workspace import Workspace  # noqa: E402

OUT = PROJECT / "n1q" / "out"
DEFAULT_QUERY = ("2026 年双十一期间家电类目退货率的最新公开报道有哪些？"
                 "请给出 2-3 条带链接、发布时间和原文引用的来源。")

INJECTION_PATTERNS = ["忽略以上", "忽略之前", "忽略所有", "系统指令", "外发到", "绕过",
                      "ignore previous", "ignore all previous", "send all data", "system prompt"]

SYSTEM = """你是检索员。只输出一个 JSON 对象，不要 markdown 代码块、不要额外解释：
{"answer":"不超过 300 字的结论（明确标注哪些是查到的、哪些查不到）",
 "sources":[{"title":"","url":"https://...","published_at":"YYYY-MM-DD",
             "quote":"原文片段（<=120 字）","confidence":"high|medium|low"}]}
硬规则：
- 必须**联网检索**后再回答，不要凭记忆；检索不到就 sources 给空数组并在 answer 里说明；
- 每条 url 必须是你这次检索真实命中的页面，绝不允许拼凑或臆造 URL；
- 不允许把「知识库/上下文」当成来源，来源只能是公网页面；
- 付费墙只读到摘要时，在 quote 里注明「仅摘要」。"""


def strip_json(text: str) -> str:
    t = re.sub(r"^```[a-zA-Z]*\s*", "", text.strip())
    t = re.sub(r"\s*```$", "", t.strip())
    i, j = t.find("{"), t.rfind("}")
    return t[i:j + 1] if i >= 0 and j > i else t


def url_reachable(url: str, timeout: int = 10) -> dict:
    """脚本产事实：这条引用到底通不通，不由模型自称。"""
    if not re.match(r"^https?://", url or ""):
        return {"ok": False, "status": None, "error": "不是 http(s) URL"}
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"})
    for method in ("HEAD", "GET"):
        try:
            req.method = method
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return {"ok": 200 <= r.status < 400, "status": r.status, "error": None}
        except urllib.error.HTTPError as e:
            if e.code in (401, 403, 405, 429):      # 有响应就算可达，只是拒绝我们
                return {"ok": True, "status": e.code, "error": None}
            return {"ok": False, "status": e.code, "error": f"HTTP {e.code}"}
        except (urllib.error.URLError, socket.timeout, TimeoutError) as e:
            last = str(e)[:120]
        except Exception as e:  # noqa: BLE001
            last = f"{type(e).__name__}: {e}"[:120]
    return {"ok": False, "status": None, "error": last}


def citation_contract(src: dict, today: date) -> list[str]:
    errs: list[str] = []
    for f in ("title", "url", "published_at", "quote", "confidence"):
        if not str(src.get(f) or "").strip():
            errs.append(f"缺字段 {f}")
    url = str(src.get("url") or "")
    if url and not re.match(r"^https?://", url):
        errs.append("url 不是 http(s)")
    pa = str(src.get("published_at") or "")
    if pa and not re.match(r"^\d{4}-\d{2}-\d{2}$", pa):
        errs.append("published_at 不是 YYYY-MM-DD")
    elif pa:
        try:
            d = date.fromisoformat(pa)
            if d > today:
                errs.append(f"published_at 未来时间（{pa}）")
        except ValueError:
            errs.append("published_at 非法日期")
    if src.get("confidence") not in ("high", "medium", "low"):
        errs.append("confidence 必须是 high/medium/low")
    return errs


def scan_injection(text: str) -> list[str]:
    low = text.lower()
    return [p for p in INJECTION_PATTERNS if p.lower() in low]


def write_quarantine(root: Path, query: str, raw: str, hits: list[str]) -> str | None:
    """命中即隔离：原文一字不改地落盘，事实内容不进隔离区、照常注入数据通道。"""
    if not hits:
        return None
    qdir = Path(root) / "quarantine"
    qdir.mkdir(parents=True, exist_ok=True)
    qpath = qdir / "N1Q_raw_hit.json"
    qpath.write_text(json.dumps({"query": query, "hit_patterns": hits, "raw": raw,
                                 "fact_content_truncated": False,
                                 "reason": "外部检索内容夹带指令性载荷，已隔离，禁止进入指令通道"},
                                ensure_ascii=False, indent=2), encoding="utf-8")
    return str(qpath.relative_to(root)).replace("\\", "/")


def main() -> int:
    query = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_QUERY
    usage = qwen.Usage()
    ws = Workspace(PROJECT / "cohort_l3").ensure()
    today = date.today()

    feedback = ""
    parsed = None
    checked: list[dict] = []
    raw = ""
    for attempt in (1, 2, 3):
        user_msg = f"今天是 {today.isoformat()}。\n{query}" + (("\n" + feedback) if feedback else "")
        res = qwen.chat([{"role": "system", "content": SYSTEM},
                         {"role": "user", "content": user_msg}],
                        enable_search=True, max_tokens=3000, usage=usage)
        raw = res["content"]
        try:
            parsed = json.loads(strip_json(raw))
            assert isinstance(parsed.get("sources"), list)
        except Exception as e:  # noqa: BLE001
            feedback = f"上一版不是合法 JSON（{e}），请只输出 JSON。"
            print(f"  第 {attempt} 次：JSON 不可用")
            parsed = None
            continue

        checked = []
        for s in parsed.get("sources") or []:
            contract_errs = citation_contract(s, today)
            reach = url_reachable(str(s.get("url") or ""))
            checked.append({**s, "contract_errors": contract_errs,
                            "contract_pass": not contract_errs,
                            "reachable": reach["ok"], "http_status": reach["status"],
                            "reach_error": reach["error"]})
        n_ok = sum(1 for s in checked if s["contract_pass"])
        n_reach = sum(1 for s in checked if s["reachable"])

        # 引用核实：抓正文，看 quote 片段是否真的在里面（三级判定）
        from verify_source import verify_all
        ver = verify_all(checked)
        for item, res in zip(checked, ver["results"]):
            item["verified"] = res["verified"]
            fs = res["verified"].get("fetch_status")
            if fs is not None and item.get("http_status") is not None and fs != item["http_status"]:
                item["status_mismatch"] = {"reachable_http": item["http_status"], "fetch_http": fs}
        cnt = ver["counts"]
        print(f"  第 {attempt} 次：{len(checked)} 条来源 / 契约 {n_ok} / 可达 {n_reach} / "
              f"核实 {cnt['verified']}（blocked {cnt['blocked']}, fabricated {cnt['fabricated']}）")

        if checked and n_ok == len(checked) and cnt["verified"] >= 2:
            break
        if not checked:
            feedback = "上一版 sources 是空的。请再检索一次，至少给 2 条你**确实打开读过正文**的公开报道。"
        elif cnt["verified"] < 2:
            feedback = ("上一次只有不到 2 条来源的正文能对上你的引用（其余要么被反爬挡住、要么 404、"
                        "要么正文里没有那句话）。请**换不同的媒体**重新检索，只引用你确实读到正文、"
                        "且能给出该页面内部数字的报道；宁可少给，不要拼凑。")
        else:
            feedback = ("上一次有链接打不开（404/拒访）。请只给确实能打开且正文对得上的页面。")
        parsed = None
    if parsed is None or not checked:
        print("检索失败：三次都没有给出可用来源（或全部不可达）")
        return 1

    passed = [s for s in checked if s["contract_pass"]]
    rejected = [s for s in checked if not s["contract_pass"]]

    hits = scan_injection(raw)
    quarantine_note = write_quarantine(PROJECT / "cohort_l3", query, raw, hits)

    artifact = {
        "node": "N1Q", "query": query,
        "answer": parsed.get("answer"),
        "sources": checked,
        "citation_contract": {"total": len(checked), "pass": len(passed),
                              "rejected": [s.get("url") for s in rejected]},
        "reachability": {"checked": len(checked),
                         "reachable": sum(1 for s in checked if s["reachable"]),
                         "unreachable": [s.get("url") for s in checked if not s["reachable"]]},
        "verification": {**cnt, "total": len(checked),
                         "verified_urls": [s.get("url") for s in checked
                                           if (s.get("verified") or {}).get("status") == "verified"],
                         "blocked_urls": [s.get("url") for s in checked
                                          if (s.get("verified") or {}).get("status") == "blocked"],
                         "fabricated_urls": [s.get("url") for s in checked
                                             if (s.get("verified") or {}).get("status") == "fabricated"],
                         "rule": "verified=正文含全部引用片段；blocked=403/429/网络拒访；"
                                 "fabricated=404 或 200 但正文找不到该片段"},
        "injection_scan": {"patterns": INJECTION_PATTERNS, "hits": hits,
                           "quarantined": quarantine_note,
                           "fact_content_truncated": False},
        "trust_level": "untrusted", "channel": "data_only",
        "usage": {"model": qwen.MODEL, "calls": usage.calls, "tokens": usage.total_tokens,
                  "latency_ms": usage.latency_ms, "est_cny": usage.cost_cny()},
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "N1Q_sources.json").write_text(json.dumps(artifact, ensure_ascii=False, indent=2),
                                          encoding="utf-8")

    rec = ws.register(node="N1Q", role="qwen_search", name="sources", payload=artifact,
                      content_mode="FULLTEXT", trust_level="untrusted", channel="data_only",
                      provenance=f"Qwen/{qwen.MODEL} 联网检索 + 本地契约校验 + URL 可达性实证")
    ws.ledger({"kind": "n1q_search", "model": qwen.MODEL, "sources": len(checked),
               "contract_pass": len(passed), "reachable": artifact["reachability"]["reachable"],
               "injection_hits": len(hits), "tokens": usage.total_tokens,
               "est_cny": usage.cost_cny()})

    print(json.dumps({"artifact": rec["uri"], "sources": len(checked),
                      "contract_pass": len(passed), "reachable": artifact["reachability"]["reachable"],
                      "injection_hits": len(hits), "quarantine": quarantine_note,
                      "tokens": usage.total_tokens, "est_cny": usage.cost_cny()},
                     ensure_ascii=False, indent=2))
    for s in checked:
        flag = "✓" if s["contract_pass"] else "✗"
        reach = "可达" if s["reachable"] else f"不可达({s['http_status'] or s['reach_error']})"
        print(f"  {flag} {reach:12} {s.get('published_at')}  {str(s.get('url'))[:70]}")
        for e in s["contract_errors"]:
            print(f"      - {e}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

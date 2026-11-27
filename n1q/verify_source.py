#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""引用核实（脚本产事实）—— 把「URL 可达」升级成「quote 真的在页面正文里」

三级判定（按 WorkBuddy 二审的意见，不能一刀切）：
  verified   核实通过 —— 抓到正文，且 quote 的每一段都在正文里
  blocked    无法核实 —— 403/429/验证码/反爬：站点拒客，不代表模型编造
  fabricated 核实失败 —— 200 但正文里找不到这段 quote：这才是瞎编

匹配规则：quote 常带「……」表示拼接，整串必然搜不到，所以按省略号/句号/分号切段，
正文与片段都做 Unicode NFKC + 去空白归一化，逐段命中才算通过。

跑法：python n1q/verify_source.py [N1Q_sources.json]
"""
from __future__ import annotations

import json
import re
import sys
import unicodedata
import urllib.error
import urllib.request
from pathlib import Path

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/138.0 Safari/537.36")
SPLIT = re.compile(r"(?:……|…|\.\.\.|。|；|;|\n)+")
BLOCK_MARKS = ("验证码", "人机验证", "访问过于频繁", "captcha", "cf-chl", "安全验证",
               "请开启JavaScript", "安全检查", "请稍候", "HW_CHECK", "正在验证",
               "Verify you are human", "Just a moment", "Attention Required")
CHALLENGE_MAX_CHARS = 3000   # 挑战页通常很小；正文页远大于此


def _looks_like_challenge(html: str) -> bool:
    low = html.lower()
    if len(html) > CHALLENGE_MAX_CHARS:
        # 大页面里出现“请稍候”不算挑战页，除非命中强特征
        return any(m.lower() in low for m in ("hw_check", "cf-chl", "captcha"))
    return any(m.lower() in low for m in BLOCK_MARKS)


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKC", s)
    return re.sub(r"\s+", "", s)


def segments(quote: str) -> list[str]:
    parts = [norm(p) for p in SPLIT.split(quote or "")]
    return [p for p in parts if len(p) >= 6]


def fetch(url: str, timeout: int = 15) -> dict:
    req = urllib.request.Request(url, headers={
        "User-Agent": UA, "Accept": "text/html,application/xhtml+xml",
        "Accept-Encoding": "identity", "Accept-Language": "zh-CN,zh;q=0.9"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read(3_000_000)
            ctype = r.headers.get("Content-Type", "")
            charset = "utf-8"
            m = re.search(r"charset=([\w-]+)", ctype or "")
            if m:
                charset = m.group(1)
            try:
                html = raw.decode(charset, "replace")
            except LookupError:
                html = raw.decode("utf-8", "replace")
            return {"ok": True, "status": r.status, "html": html, "bytes": len(raw)}
    except urllib.error.HTTPError as e:
        try:
            body = e.read(20000).decode("utf-8", "replace")
        except Exception:  # noqa: BLE001
            body = ""
        return {"ok": False, "status": e.code, "error": f"HTTP {e.code}", "body": body}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "status": None, "error": f"{type(e).__name__}: {str(e)[:80]}"}


def page_text(html: str) -> str:
    try:
        from lxml import html as LH
        doc = LH.fromstring(html)
        for bad in doc.xpath("//script | //style | //noscript"):
            bad.getparent().remove(bad)
        return doc.text_content()
    except Exception:  # noqa: BLE001
        return re.sub(r"<[^>]+>", " ", html)


def verify_one(src: dict) -> dict:
    url = str(src.get("url") or "")
    quote = str(src.get("quote") or "")
    segs = segments(quote)
    out = {"url": url, "segments_total": len(segs)}

    if not re.match(r"^https?://", url):
        return {**out, "status": "blocked", "reason": "URL 非法", "page_bytes": 0}
    if not segs:
        return {**out, "status": "blocked", "reason": "quote 太短无法切段", "page_bytes": 0}

    res = fetch(url)
    prior = src.get("http_status")   # 可达性探测那边的结果
    if not res["ok"]:
        code = res.get("status")
        body = res.get("body") or ""
        # 两次探测结论不一致（例如可达探测 200、正文抓取 404）→ 无法核实，不是编造
        if code in (404, 410) and isinstance(prior, int) and 200 <= prior < 400:
            return {**out, "status": "blocked", "fetch_status": code,
                    "reason": f"两次探测不一致（可达探测 HTTP {prior} / 正文抓取 HTTP {code}），无法判定",
                    "page_bytes": len(body)}
        # 有些 WAF 用 404 装死，但返回的是挑战页 —— 这属于站点拒客，不是编造
        if _looks_like_challenge(body):
            return {**out, "status": "blocked", "fetch_status": code,
                    "reason": f"反爬挑战页（HTTP {code}，{len(body)} 字节）", "page_bytes": len(body)}
        if code in (404, 410):
            return {**out, "status": "fabricated", "fetch_status": code,
                    "reason": f"URL 不存在（HTTP {code}）", "page_bytes": len(body)}
        if code in (401, 403, 405, 418, 429):
            return {**out, "status": "blocked", "fetch_status": code,
                    "reason": f"站点拒客（HTTP {code}）", "page_bytes": len(body)}
        return {**out, "status": "blocked", "fetch_status": code,
                "reason": res.get("error"), "page_bytes": len(body)}

    if _looks_like_challenge(res["html"]):
        return {**out, "status": "blocked", "fetch_status": res["status"],
                "reason": f"反爬挑战页（HTTP {res['status']}，{res['bytes']} 字节）",
                "page_bytes": res["bytes"]}

    text = norm(page_text(res["html"]))
    hits = [s for s in segs if s in text]
    status = "verified" if len(hits) == len(segs) else "fabricated"
    return {**out, "status": status, "fetch_status": res["status"],
            "segments_found": len(hits),
            "missing_segments": [s[:30] for s in segs if s not in text][:3],
            "page_bytes": res["bytes"], "page_chars": len(text)}


def verify_all(sources: list[dict]) -> dict:
    results = []
    for s in sources:
        v = verify_one(s)
        results.append({**s, "verified": v})
    cnt = {"verified": 0, "blocked": 0, "fabricated": 0}
    for r in results:
        cnt[r["verified"]["status"]] = cnt.get(r["verified"]["status"], 0) + 1
    return {"counts": cnt, "total": len(results), "results": results}


def main() -> int:
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else \
        Path(__file__).resolve().parent / "out" / "N1Q_sources.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    out = verify_all(data.get("sources") or [])
    print(json.dumps({"counts": out["counts"], "total": out["total"]}, ensure_ascii=False, indent=2))
    for r in out["results"]:
        v = r["verified"]
        print(f"  [{v['status']:10}] {r.get('title','')[:32]:32} "
              f"片段 {v.get('segments_found', 0)}/{v['segments_total']}  {v.get('reason') or ''}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

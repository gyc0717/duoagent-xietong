#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""给网关加 /model：只收 alias，endpoint/model_id 在网关内写死。

硬约束：
  - workflow 只能传 alias；未知 alias 一律 403（挡"改字段打任意地址"）
  - 密钥运行时从 .secrets.json 读，不进请求、不进日志
  - 不自动重试；有 timeout 与 max_tokens 上限
  - 成本拆两口径：provider_reported（供应商直接给钱）/ token_pricing（只给 token，钱是算的）
  - 单轮 run_id 成本硬上限 ¥2，超了返回 402，链由调用方停
"""
from __future__ import annotations

from pathlib import Path

P = Path(__file__).resolve().parent / "gateway.py"
s = P.read_text(encoding="utf-8")
n0 = len(s)

TABLE = '''
# ---------------- /model：alias 白名单（写死，不从请求读） ----------------
ALIASES = {
    "moonshot-lite":     {"vendor": "Moonshot", "model_id": "moonshot-v1-8k",
                          "endpoint": "https://api.moonshot.cn/v1/chat/completions",
                          "key": "MOONSHOT_API_KEY", "max_tokens": 4096},
    "moonshot-flagship": {"vendor": "Moonshot", "model_id": "kimi-k3",
                          "endpoint": "https://api.moonshot.cn/v1/chat/completions",
                          "key": "MOONSHOT_API_KEY", "max_tokens": 16000},
    "bailian-flash":     {"vendor": "Bailian", "model_id": "qwen-flash",
                          "endpoint": "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
                          "key": "DASHSCOPE_API_KEY", "max_tokens": 4096},
    "bailian-max":       {"vendor": "Bailian", "model_id": "qwen-max",
                          "endpoint": "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
                          "key": "DASHSCOPE_API_KEY", "max_tokens": 8192},
    "ark-lite":          {"vendor": "Ark", "model_id": "doubao-seed-2-1-lite-260915",
                          "endpoint": "https://ark.cn-beijing.volces.com/api/v3/chat/completions",
                          "key": "ARK_API_KEY", "max_tokens": 4096},
}

# 价格表：元 / 1k tokens（**估算**，只用于 token_pricing 口径）
PRICES = {
    "moonshot-v1-8k": (0.012, 0.012),
    "kimi-k3": (0.030, 0.030),
    "qwen-flash": (0.0003, 0.0012),
    "qwen-max": (0.0024, 0.0096),
    "doubao-seed-2-1-lite-260915": (0.0003, 0.0006),
}

RUN_BUDGET_CNY = 2.0          # 单轮硬上限
RUN_SPENT: dict[str, float] = {}
MODEL_CALLS: dict[str, int] = {}


def _secrets() -> dict:
    return _load()


def call_model(body: dict) -> tuple[int, dict]:
    """返回 (http_code, payload)。不重试，超时与 max_tokens 都有上限。"""
    import urllib.error
    import urllib.request

    alias = (body.get("alias") or "").strip()
    if alias not in ALIASES:
        return 403, {"ok": False, "error": f"未知 alias={alias!r}；可用：{sorted(ALIASES)}"}
    cfg = ALIASES[alias]
    run_id = str(body.get("run_id") or "default")

    spent = RUN_SPENT.get(run_id, 0.0)
    if spent >= RUN_BUDGET_CNY:
        return 402, {"ok": False, "error": f"单轮成本已达上限 ¥{RUN_BUDGET_CNY}",
                     "spent_cny": round(spent, 4), "budget_cny": RUN_BUDGET_CNY}

    msgs = body.get("messages")
    if not isinstance(msgs, list) or not msgs:
        return 400, {"ok": False, "error": "messages 必须是非空数组"}
    try:
        mt = int(body.get("max_tokens") or cfg["max_tokens"])
    except (TypeError, ValueError):
        return 400, {"ok": False, "error": "max_tokens 必须是整数"}
    mt = max(1, min(mt, cfg["max_tokens"]))
    try:
        timeout = float(body.get("timeout_s") or 60)
    except (TypeError, ValueError):
        timeout = 60.0
    timeout = max(5.0, min(timeout, 300.0))

    key = _secrets().get(cfg["key"])
    if not key:
        return 500, {"ok": False, "error": f"缺少密钥 {cfg['key']}（.secrets.json）"}

    payload = json.dumps({"model": cfg["model_id"], "messages": msgs,
                          "max_tokens": mt,
                          "temperature": body.get("temperature", 1.0)}).encode()
    req = urllib.request.Request(cfg["endpoint"], data=payload, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("Authorization", "Bearer " + key)

    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:300]
        return 502, {"ok": False, "error": f"上游 HTTP {e.code}", "detail": detail,
                     "alias": alias, "vendor": cfg["vendor"]}
    except Exception as e:  # noqa: BLE001
        return 504, {"ok": False, "error": f"{type(e).__name__}: {e}", "alias": alias,
                     "vendor": cfg["vendor"]}
    latency = round((time.time() - t0) * 1000)

    usage = raw.get("usage") or {}
    pt = int(usage.get("prompt_tokens") or 0)
    ct = int(usage.get("completion_tokens") or 0)
    tt = int(usage.get("total_tokens") or (pt + ct))

    # 成本两口径：供应商直接给钱 -> provider_reported；只给 token -> token_pricing（估算）
    provider_cost = usage.get("cost") or usage.get("total_cost")
    if provider_cost is not None:
        cost_cny = float(provider_cost)
        cost_source = "provider_reported"
    else:
        pin, pout = PRICES.get(cfg["model_id"], (0.0, 0.0))
        cost_cny = round(pt / 1000 * pin + ct / 1000 * pout, 6)
        cost_source = "token_pricing"

    RUN_SPENT[run_id] = round(RUN_SPENT.get(run_id, 0.0) + cost_cny, 6)
    MODEL_CALLS[run_id] = MODEL_CALLS.get(run_id, 0) + 1

    content = ""
    choices = raw.get("choices") or []
    if choices:
        content = (choices[0].get("message") or {}).get("content") or ""

    return 200, {
        "ok": bool(content),
        "alias": alias, "vendor": cfg["vendor"], "model_id": cfg["model_id"],
        "content": content,
        "tokens": {"prompt": pt, "completion": ct, "total": tt},
        "latency_ms": latency,
        "cost_cny": cost_cny, "cost_source": cost_source,
        "spent_cny": RUN_SPENT[run_id], "budget_cny": RUN_BUDGET_CNY,
        "finish_reason": (choices[0].get("finish_reason") if choices else None),
    }


'''

anchor = "class H(BaseHTTPRequestHandler):"
assert anchor in s
s = s.replace(anchor, TABLE + anchor, 1)

# 路由：/model 与 /model/aliases
OLD = '''            if self.path == "/register":
                with LOCK:
                    return self._send(200, register(body))'''
NEW = '''            if self.path == "/model":
                with LOCK:
                    code, payload = call_model(body)
                    audit({"kind": "model_call", "alias": body.get("alias"),
                           "run_id": str(body.get("run_id") or "default"),
                           "code": code,
                           "vendor": (payload or {}).get("vendor"),
                           "tokens": (payload or {}).get("tokens"),
                           "cost_cny": (payload or {}).get("cost_cny"),
                           "cost_source": (payload or {}).get("cost_source"),
                           "latency_ms": (payload or {}).get("latency_ms"),
                           "caller": body.get("_caller")})
                    return self._send(code, payload)
            if self.path == "/register":
                with LOCK:
                    return self._send(200, register(body))'''
assert OLD in s
s = s.replace(OLD, NEW, 1)

OLD_GET = '''        if self.path.startswith("/progress"):'''
NEW_GET = '''        if self.path == "/model/aliases":
            return self._send(200, {"aliases": {
                k: {"vendor": v["vendor"], "model_id": v["model_id"],
                    "max_tokens": v["max_tokens"]} for k, v in ALIASES.items()},
                "budget_cny": RUN_BUDGET_CNY})
        if self.path.startswith("/progress"):'''
assert OLD_GET in s
s = s.replace(OLD_GET, NEW_GET, 1)

P.write_text(s, encoding="utf-8")
print("模型网关补丁完成：", n0, "->", len(s), "字符")

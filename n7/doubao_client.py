#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""豆包（火山方舟 Ark）客户端 —— N7 三审与总结的模型接入。

key 从 ARK_API_KEY 读，不落盘、不打印。
注意：Ark 需要先在控制台「开通模型服务」，否则返回 ModelNotOpen（本函数会直接抛出来）。
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any

BASE = os.environ.get("ARK_BASE_URL", "https://ark.cn-beijing.volces.com/api/v3")
MODEL = os.environ.get("ARK_MODEL", "doubao-seed-2-1-lite-260915")
# 工程估算单价（¥/1k），仅作成本归因
PRICING = {"doubao-seed-2-1-pro": {"in": 0.0008, "out": 0.002},
           "doubao-seed-2-1-lite": {"in": 0.0003, "out": 0.0006}}


class ArkError(RuntimeError):
    pass


@dataclass
class Usage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    calls: int = 0
    latency_ms: float = 0.0
    per_call: list[dict[str, Any]] = field(default_factory=list)

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens

    def cost_cny(self, model: str = MODEL) -> float:
        key = next((k for k in PRICING if model.startswith(k)), "")
        p = PRICING.get(key, {"in": 0.0, "out": 0.0})
        return round(self.prompt_tokens / 1000 * p["in"] + self.completion_tokens / 1000 * p["out"], 6)


def _key() -> str:
    k = os.environ.get("ARK_API_KEY", "").strip()
    if not k:
        raise ArkError("缺少 ARK_API_KEY")
    return k


def list_models() -> list[dict[str, Any]]:
    req = urllib.request.Request(BASE + "/models", headers={"Authorization": "Bearer " + _key()})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read()).get("data", [])


def chat(messages: list[dict[str, str]], *, model: str = MODEL, max_tokens: int = 4000,
         temperature: float = 0.3, timeout: int = 300, retries: int = 1,
         usage: Usage | None = None) -> dict[str, Any]:
    payload = {"model": model, "messages": messages, "max_tokens": max_tokens,
               "temperature": temperature}
    last: Exception | None = None
    for attempt in range(retries + 1):
        t0 = time.perf_counter()
        req = urllib.request.Request(BASE + "/chat/completions", data=json.dumps(payload).encode(),
                                     headers={"Authorization": "Bearer " + _key(),
                                              "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                d = json.loads(r.read())
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", "replace")
            try:
                code = json.loads(body)["error"]["code"]
            except Exception:  # noqa: BLE001
                code = f"HTTP {e.code}"
            if code == "ModelNotOpen":
                raise ArkError(
                    "账号未开通该模型服务（ModelNotOpen）。去火山方舟控制台 → 开通管理 → "
                    f"开通 {model}，或在 ARK_MODEL 里换一个已开通的模型。") from e
            last = ArkError(f"{code}: {body[:300]}")
            if attempt == retries:
                raise last
            time.sleep(2.0)
            continue
        except (TimeoutError, OSError) as e:
            last = e
            if attempt == retries:
                raise ArkError(f"网络/超时：{e}") from e
            time.sleep(2.0)
            continue
        ms = round((time.perf_counter() - t0) * 1000, 1)
        u = d.get("usage", {}) or {}
        if usage is not None:
            usage.calls += 1
            usage.latency_ms += ms
            usage.prompt_tokens += int(u.get("prompt_tokens", 0))
            usage.completion_tokens += int(u.get("completion_tokens", 0))
            usage.per_call.append({"model": model, "ms": ms,
                                   "in": u.get("prompt_tokens", 0), "out": u.get("completion_tokens", 0)})
        ch = d["choices"][0]
        return {"content": ch["message"].get("content") or "",
                "finish_reason": ch.get("finish_reason"),
                "reasoning_tokens": (u.get("completion_tokens_details") or {}).get("reasoning_tokens", 0)}
    raise ArkError(f"调用失败：{last}")


if __name__ == "__main__":
    u = Usage()
    out = chat([{"role": "user", "content": "只回两个字：正常"}], max_tokens=64, usage=u)
    print(json.dumps({"content": out["content"][:40], "finish": out["finish_reason"],
                      "tokens": u.total_tokens, "ms": u.latency_ms,
                      "est_cny": u.cost_cny()}, ensure_ascii=False))

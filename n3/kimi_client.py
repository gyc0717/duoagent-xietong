#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Kimi（Moonshot）客户端 —— N3 视觉设计师的真实模型接入。

只用标准库；key 从环境变量 MOONSHOT_API_KEY 读，绝不落盘、绝不打印。
记账口径：token 精确；单价为工程估算（可在 PRICING 里改），不用于优化目标。
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any

BASE = os.environ.get("MOONSHOT_BASE_URL", "https://api.moonshot.cn/v1")
MODEL = os.environ.get("MOONSHOT_MODEL", "kimi-k3")

# 工程估算单价（¥ / 1k tokens），仅用于成本归因；真实账单以平台为准
PRICING = {"kimi-k3": {"in": 0.004, "out": 0.016},
           "kimi-k3.1-pro": {"in": 0.012, "out": 0.048}}


class KimiError(RuntimeError):
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

    def cost_cny(self, model: str) -> float:
        p = PRICING.get(model, {"in": 0.0, "out": 0.0})
        return round(self.prompt_tokens / 1000 * p["in"] + self.completion_tokens / 1000 * p["out"], 6)


def api_key() -> str:
    key = os.environ.get("MOONSHOT_API_KEY", "").strip()
    if not key:
        raise KimiError("缺少 MOONSHOT_API_KEY（不要写进代码或日志）")
    return key


def _post(path: str, payload: dict[str, Any], timeout: int = 420) -> dict[str, Any]:
    req = urllib.request.Request(
        BASE + path,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Authorization": "Bearer " + api_key(),
                 "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")[:400]
        raise KimiError(f"HTTP {e.code}: {body}") from e
    except urllib.error.URLError as e:
        raise KimiError(f"网络错误: {e.reason}") from e


def chat_ex(messages: list[dict[str, str]], *, model: str = MODEL, temperature: float = 1.0,
            max_tokens: int = 16000, retries: int = 2, usage: Usage | None = None) -> dict[str, Any]:
    """返回 {content, finish_reason, reasoning_tokens}，便于识别「被截断」而不是当成模型写坏。"""
    payload = {"model": model, "messages": messages,
               "temperature": temperature, "max_tokens": max_tokens}
    last: Exception | None = None
    for attempt in range(retries + 1):
        t0 = time.perf_counter()
        try:
            data = _post("/chat/completions", payload)
        except (KimiError, TimeoutError, OSError) as e:
            last = e
            if attempt == retries:
                raise KimiError(f"调用失败（{attempt + 1} 次）：{e}") from e
            time.sleep(2.0 * (attempt + 1))
            continue
        ms = round((time.perf_counter() - t0) * 1000, 1)
        u = data.get("usage", {}) or {}
        if usage is not None:
            usage.calls += 1
            usage.latency_ms += ms
            usage.prompt_tokens += int(u.get("prompt_tokens", 0))
            usage.completion_tokens += int(u.get("completion_tokens", 0))
            usage.per_call.append({"model": model, "ms": ms,
                                   "in": u.get("prompt_tokens", 0),
                                   "out": u.get("completion_tokens", 0)})
        ch = data["choices"][0]
        msg = ch.get("message", {})
        return {"content": msg.get("content") or "",
                "finish_reason": ch.get("finish_reason"),
                "reasoning_chars": len(msg.get("reasoning_content") or ""),
                "reasoning_tokens": (u.get("completion_tokens_details") or {}).get("reasoning_tokens", 0)}
    raise KimiError(f"调用失败：{last}")


def chat(messages: list[dict[str, str]], *, model: str = MODEL, temperature: float = 1.0,
         max_tokens: int = 16000, retries: int = 2, usage: Usage | None = None) -> str:
    return chat_ex(messages, model=model, temperature=temperature, max_tokens=max_tokens,
                   retries=retries, usage=usage)["content"]


if __name__ == "__main__":
    u = Usage()
    out = chat([{"role": "user", "content": "只回答四个字：接口正常"}], max_tokens=64, usage=u)
    print(repr(out.strip()))
    print(json.dumps({"calls": u.calls, "tokens": u.total_tokens, "ms": u.latency_ms,
                      "est_cny": u.cost_cny(MODEL)}, ensure_ascii=False))

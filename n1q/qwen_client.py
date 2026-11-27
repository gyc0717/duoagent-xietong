#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""千问（阿里百炼 DashScope）客户端 —— N1Q 检索 / N5 异构复核的模型接入。

key 从 DASHSCOPE_API_KEY 读，不落盘、不打印。
联网检索走 OpenAI 兼容模式 + enable_search（qwen-deep-research 不支持兼容模式，用它同族的 plus/max）。
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any

BASE = os.environ.get("DASHSCOPE_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")
MODEL = os.environ.get("DASHSCOPE_MODEL", "qwen-plus")
PRICING = {"qwen-plus": {"in": 0.0008, "out": 0.002},
           "qwen-max": {"in": 0.0024, "out": 0.0096},
           "qwen-flash": {"in": 0.00015, "out": 0.0015}}


class QwenError(RuntimeError):
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
        p = PRICING.get(model, {"in": 0.0, "out": 0.0})
        return round(self.prompt_tokens / 1000 * p["in"] + self.completion_tokens / 1000 * p["out"], 6)


def _key() -> str:
    k = os.environ.get("DASHSCOPE_API_KEY", "").strip()
    if not k:
        raise QwenError("缺少 DASHSCOPE_API_KEY")
    return k


def chat(messages: list[dict[str, str]], *, model: str = MODEL, enable_search: bool = False,
         forced_search: bool = True, max_tokens: int = 4000, temperature: float = 0.3,
         timeout: int = 600, retries: int = 1, usage: Usage | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {"model": model, "messages": messages,
                               "max_tokens": max_tokens, "temperature": temperature}
    if enable_search:
        payload["enable_search"] = True
        if forced_search:
            # 不加 forced_search 时模型会「凭记忆答」，实测 3 秒就返回且自称 2024 年
            payload["search_options"] = {"forced_search": True}
    last: Exception | None = None
    for attempt in range(retries + 1):
        t0 = time.perf_counter()
        req = urllib.request.Request(BASE + "/chat/completions",
                                     data=json.dumps(payload).encode(),
                                     headers={"Authorization": "Bearer " + _key(),
                                              "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                d = json.loads(r.read())
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", "replace")
            last = QwenError(f"HTTP {e.code}: {body[:300]}")
            if attempt == retries:
                raise last
            time.sleep(2.0)
            continue
        except (TimeoutError, OSError) as e:
            last = e
            if attempt == retries:
                raise QwenError(f"网络/超时：{e}") from e
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
                "request_id": d.get("request_id") or d.get("id")}
    raise QwenError(f"调用失败：{last}")


if __name__ == "__main__":
    u = Usage()
    out = chat([{"role": "user", "content": "只回两个字：正常"}], max_tokens=32, timeout=60, usage=u)
    print(json.dumps({"content": out["content"][:30], "finish": out["finish_reason"],
                      "tokens": u.total_tokens, "ms": u.latency_ms}, ensure_ascii=False))

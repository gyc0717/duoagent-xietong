#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""L3 本地网关 —— Harness 编排层与执行端之间的唯一调用通道

为什么不是「编排层直接 subprocess 调脚本」：
  - subprocess 会把脚本路径交出去，白名单只在文档里，绕得过去；
  - 网关是唯一写入口，谁能写、写什么（含 l3_publish 禁止项）都在代码里硬挡；
  - 所有调用走同一条审计线，台账能对上。

身份归属（重要）：
  - caller **不采信客户端自报**；服务端用令牌指纹反查 L3_TOKENS 得到 caller；
  - X-Caller 只作为 claimed_caller 记录，日志里标明是自报；
  - 三类调用方各有独立令牌：harness / operator / test。

白名单（写死在代码里，不读配置）：
  GET  /status    → 只读状态（对应 l3_task_status）
  GET  /progress  → 只读进度页（演示模式标注）
  POST /sandbox   → 跑确定性沙箱（对应 l3_run_sandbox）
  POST /register  → 登记工件，强制 untrusted/data_only
  ❌ 没有 /publish —— 发布必须由主控硬垂询后人工触发
"""
from __future__ import annotations

import hashlib
import json
import os
import secrets
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT / "l3"))

from workspace import Workspace  # noqa: E402

WS_ROOT = PROJECT / "cohort_l3"
SECRETS = PROJECT / ".secrets.json"
PORT = int(os.environ.get("L3_GATEWAY_PORT", "8733"))
AUDIT = WS_ROOT / "gateway_calls.jsonl"
PROGRESS_HTML = PROJECT / "_scratch" / "progress.html"
LOCK = threading.Lock()


def _fp(t: str) -> str:
    return hashlib.sha256((t or "").encode()).hexdigest()[:8]


def _load() -> dict:
    if SECRETS.exists():
        try:
            return json.loads(SECRETS.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            return {}
    return {}


def ensure_tokens() -> dict[str, str]:
    """每类调用方一个令牌；返回 {指纹: 调用方}。旧单令牌继续当 harness 用。"""
    data = _load()
    tokens = dict(data.get("L3_TOKENS") or {})
    for who in ("harness", "operator", "test"):
        if not tokens.get(who):
            tokens[who] = "l3_" + who[:3] + "_" + secrets.token_hex(12)
    legacy = data.get("L3_GATEWAY_TOKEN")
    if legacy and legacy != tokens["harness"]:
        data["L3_GATEWAY_TOKEN_LEGACY"] = legacy
    data["L3_TOKENS"] = tokens
    data["L3_GATEWAY_TOKEN"] = tokens["harness"]     # 兼容旧客户端
    SECRETS.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return {_fp(v): k for k, v in tokens.items()}


CALLERS = ensure_tokens()


def audit(rec: dict) -> None:
    rec = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), **rec}
    with open(AUDIT, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def status_payload() -> dict:
    ws = Workspace(WS_ROOT).ensure()
    rows = ws._read_registry()
    by_node: dict[str, int] = {}
    for r in rows:
        by_node[r["node"]] = by_node.get(r["node"], 0) + 1
    ev = WS_ROOT / "eval" / "eval_report.json"
    acc = WS_ROOT / "outbox" / "acceptance.json"
    return {
        "task_id": ws.task_id, "artifacts": len(rows), "by_node": by_node,
        "ledger_events": len(ws.ledger_lines()),
        "eval": json.loads(ev.read_text(encoding="utf-8")) if ev.exists() else {},
        "acceptance": json.loads(acc.read_text(encoding="utf-8")).get("passed")
        if acc.exists() else None,
        "integrity": ws.verify(),
    }


def run_sandbox() -> dict:
    out = subprocess.run([sys.executable, str(PROJECT / "l3" / "n5_executor.py")],
                         capture_output=True, text=True, encoding="utf-8", errors="replace",
                         timeout=300, cwd=str(PROJECT))
    ev_path = PROJECT / "real" / "out" / "execution_evidence.json"
    ev = json.loads(ev_path.read_text(encoding="utf-8")) if ev_path.exists() else {}
    return {"ok": out.returncode == 0, "checks": ev.get("checks_passed"),
            "source": ev.get("evidence_source"), "elapsed_ms": ev.get("elapsed_ms")}


def register(body: dict) -> dict:
    ws = Workspace(WS_ROOT).ensure()
    trust = body.get("trust_level", "untrusted")
    channel = body.get("channel", "data_only")
    if trust != "untrusted" or channel != "data_only":
        raise PermissionError("网关只接受外部工件的 untrusted/data_only 登记；"
                              "trusted/both 必须由执行端直接登记")
    rec = ws.register(node=body.get("node", "N1Q"), role=body.get("role", "qwen_search"),
                      name=body.get("name", "gateway"), payload=body.get("payload", {}),
                      content_mode="FULLTEXT", trust_level=trust, channel=channel,
                      provenance=f"网关 / caller={body.get('_caller', 'unknown')}")
    return {"id": rec["id"], "uri": rec["uri"], "sha256": rec["sha256"][:16],
            "version": rec["version"], "vendor": rec["vendor"]}



# ---------------- /model：alias 白名单（写死，不从请求读） ----------------
ALIASES = {
    "moonshot-lite":     {"vendor": "Moonshot", "model_id": "kimi-k3.1-pro",
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
    "kimi-k3.1-pro": (0.030, 0.030),
    "kimi-k3": (0.030, 0.030),
    "qwen-flash": (0.0003, 0.0012),
    "qwen-max": (0.0024, 0.0096),
    "doubao-seed-2-1-lite-260915": (0.0003, 0.0006),
}

RUN_BUDGET_CNY = 2.0          # 单轮硬上限
BUDGET_FILE = WS_ROOT / "model_budget.json"


def _load_budget() -> dict:
    try:
        return json.loads(BUDGET_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_budget(data: dict) -> None:
    try:
        BUDGET_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


RUN_SPENT: dict[str, float] = _load_budget()
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
    _save_budget(RUN_SPENT)

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



# ---------------- 确定性步骤：脚本路径写死 ----------------
STEPS = {
    "charts": {"script": "real/charts_real.py", "artifact": "real/out/chart_data.json"},
    "index":  {"script": "real/file_index.py",  "artifact": "real/out/file_index.json"},
    "report": {"script": "real/report.py",      "artifact": "real/out/final_report.md"},
    "ingest": {"script": "real/ingest.py",      "artifact": "real/out/ingest_report.json"},
}


DATA_ROOT = PROJECT / "real" / "data"


def run_step(name: str, body: dict | None = None) -> tuple[int, dict]:
    import hashlib
    cfg = STEPS.get(name)
    if not cfg:
        return 404, {"ok": False, "error": f"未知步骤 {name!r}；可用：{sorted(STEPS)}"}
    script = PROJECT / cfg["script"]
    if not script.exists():
        return 500, {"ok": False, "error": f"脚本缺失：{script}"}
    args = [sys.executable, str(script)]
    if name == "ingest":
        body = body or {}
        fname = str(body.get("file") or "").strip()
        caliber = str(body.get("caliber") or "").strip()
        if not fname or not caliber:
            return 400, {"ok": False, "error": "ingest 需要 file 与 caliber（started/completed）"}
        target = (DATA_ROOT / fname).resolve()
        if DATA_ROOT.resolve() not in target.parents:
            return 403, {"ok": False, "error": "只允许 real/data 下的文件"}
        if not target.exists():
            return 404, {"ok": False, "error": f"文件不存在：{target.name}"}
        if caliber not in ("started", "completed"):
            return 400, {"ok": False, "error": "caliber 只能是 started / completed"}
        args += [str(target), "--caliber", caliber]
    out = subprocess.run(args, capture_output=True, text=True,
                         encoding="utf-8", errors="replace", timeout=300, cwd=str(PROJECT))
    art = PROJECT / cfg["artifact"]
    if out.returncode != 0:
        return 500, {"ok": False, "error": "脚本失败",
                     "detail": (out.stderr or out.stdout or "")[-300:]}
    if not art.exists():
        return 500, {"ok": False, "error": f"产物缺失：{art.name}"}
    sha = hashlib.sha256(art.read_bytes()).hexdigest()[:16]
    return 200, {"ok": True, "step": name, "artifact": f"{art.name}",
                 "uri": str(art.relative_to(PROJECT)).replace("\\", "/"),
                 "sha256": sha, "stdout_tail": (out.stdout or "").strip().splitlines()[-2:]}


class H(BaseHTTPRequestHandler):
    def _send(self, code, obj):
        self._code = code
        data = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _caller(self):
        tok = self.headers.get("X-L3-Token") or ""
        if not tok:
            return None, None
        fp = _fp(tok)
        return CALLERS.get(fp), fp

    def _body(self) -> dict:
        n = int(self.headers.get("Content-Length") or 0)
        if not n:
            return {}
        try:
            return json.loads(self.rfile.read(n).decode("utf-8"))
        except Exception:  # noqa: BLE001
            return {}

    def do_GET(self):
        t0 = time.time()
        try:
            return self._do_get()
        finally:
            self._audit(t0)

    def _do_get(self):
        if self.path == "/health":
            return self._send(200, {"ok": True, "service": "l3-gateway"})
        caller, fp = self._caller()
        if not caller:
            return self._send(401, {"ok": False, "error": "缺少或错误的 X-L3-Token"})
        if self.path == "/status":
            with LOCK:
                return self._send(200, status_payload())
        if self.path == "/model/aliases":
            return self._send(200, {"aliases": {
                k: {"vendor": v["vendor"], "model_id": v["model_id"],
                    "max_tokens": v["max_tokens"]} for k, v in ALIASES.items()},
                "budget_cny": RUN_BUDGET_CNY})
        if self.path.startswith("/progress"):
            html = PROGRESS_HTML.read_text(encoding="utf-8") if PROGRESS_HTML.exists() else \
                "<h1>进度页尚未生成</h1>"
            data = html.encode("utf-8")
            self._code = 200
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return None
        return self._send(404, {"ok": False, "error": "not found（白名单外）"})

    def do_POST(self):
        t0 = time.time()
        try:
            return self._do_post()
        finally:
            self._audit(t0)

    def _do_post(self):
        caller, fp = self._caller()
        if not caller:
            return self._send(401, {"ok": False, "error": "缺少或错误的 X-L3-Token"})
        body = self._body()
        body["_caller"] = caller
        try:
            if self.path == "/sandbox":
                with LOCK:
                    return self._send(200, run_sandbox())
            if self.path.startswith("/run/"):
                with LOCK:
                    code, payload = run_step(self.path[len("/run/"):], body)
                return self._send(code, payload)
            if self.path == "/model":
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
                    return self._send(200, register(body))
            if self.path == "/publish":
                return self._send(403, {"ok": False,
                                        "error": "l3_publish 禁止自动化调用，须主控硬垂询后人工触发"})
            return self._send(404, {"ok": False, "error": "not found（白名单外）"})
        except PermissionError as e:
            return self._send(403, {"ok": False, "error": str(e)})
        except Exception as e:  # noqa: BLE001
            return self._send(500, {"ok": False, "error": f"{type(e).__name__}: {e}"})

    def _audit(self, t0: float) -> None:
        try:
            caller, fp = self._caller()
            audit({
                "method": self.command,
                "path": self.path.split("?")[0],
                "code": getattr(self, "_code", None),
                "ms": round((time.time() - t0) * 1000),
                "caller": caller,
                "caller_source": "token_fp（服务端反查）",
                "token_fp": fp,
                "claimed_caller": self.headers.get("X-Caller"),
            })
        except Exception:  # noqa: BLE001
            pass

    def log_message(self, fmt, *args):
        pass


if __name__ == "__main__":
    print(f"L3 网关启动：http://127.0.0.1:{PORT}（令牌表见 {SECRETS} 的 L3_TOKENS）", flush=True)
    ThreadingHTTPServer(("127.0.0.1", PORT), H).serve_forever()

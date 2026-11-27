#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""N5 一审内调用点 · executor（固化版）

不是第四级审核：它挂在一审内部，产确定性证据，由模型判事实。
接口固定：execute(workspace) -> {evidence, record}；证据若来自 mock/常量则直接判 FAIL。
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parent
VERIFIER = PROJECT / "real" / "verify.py"
EVIDENCE = PROJECT / "real" / "out" / "execution_evidence.json"

REQUIRED_CHECKS = ("01_compile", "02_unit_test", "03_svg_render", "04_chart_vs_structured_data",
                   "05_data_script_rerun", "06_reconciliation", "07_null_boundary",
                   "08_mock_vs_real_consistency", "09_chart_proportionality")


class SandboxViolation(RuntimeError):
    pass


def run_verifier(timeout: int = 300) -> dict[str, Any]:
    if not VERIFIER.exists():
        raise SandboxViolation(f"找不到真实执行器：{VERIFIER}")
    proc = subprocess.run([sys.executable, str(VERIFIER)], capture_output=True,
                          text=True, timeout=timeout)
    if not EVIDENCE.exists():
        raise SandboxViolation(f"执行器没有产出证据：{EVIDENCE}")
    ev = json.loads(EVIDENCE.read_text(encoding="utf-8"))
    ev["exit_code"] = proc.returncode
    ev["stdout_tail"] = (proc.stdout or "").strip().splitlines()[-3:]
    return ev


def assert_real(ev: dict[str, Any]) -> None:
    """证据必须是真跑出来的：缺检查项、来源是 mock、退出码非 0 —— 一律不放行。"""
    checks = ev.get("checks") or {}
    missing = [c for c in REQUIRED_CHECKS if c not in checks]
    if missing:
        raise SandboxViolation(f"证据缺少检查项：{missing}")
    if ev.get("evidence_source", "real_execution") != "real_execution":
        raise SandboxViolation(f"证据来源不是真实执行：{ev.get('evidence_source')}")
    if ev.get("exit_code", 0) != 0:
        raise SandboxViolation(f"执行器退出码 {ev.get('exit_code')}，检查未全过")


def execute(ws, node: str = "N5", role: str = "dsh_l1") -> dict[str, Any]:
    """跑真沙箱 → 校验证据 → 登记进 L3。返回 {evidence, record}。"""
    ev = run_verifier()
    assert_real(ev)
    ws.ledger({"kind": "sandbox_executed", "node": node,
               "checks_passed": ev.get("checks_passed"), "elapsed_ms": ev.get("elapsed_ms"),
               "executor": ev.get("executor")})
    record = ws.register(
        node=node, role=role, name="execution_evidence",
        payload=ev, content_mode="FULLTEXT",
        trust_level="trusted", channel="both",
        provenance="L3/N5-executor → real/verify.py（确定性执行，零模型 token）",
    )
    return {"evidence": ev, "record": record}


if __name__ == "__main__":
    sys.path.insert(0, str(HERE))
    from workspace import Workspace
    ws = Workspace(PROJECT / "cohort_l3").ensure()
    out = execute(ws)
    ev = out["evidence"]
    print(json.dumps({
        "node": "N5", "evidence_source": ev.get("evidence_source"),
        "elapsed_ms": ev.get("elapsed_ms"),
        "checks_passed": ev.get("checks_passed") or
        f"{sum(1 for k, v in ev['checks'].items() if v.get('pass'))}/{len(ev['checks'])}",
        "artifact": out["record"]["uri"], "sha256": out["record"]["sha256"][:12],
    }, ensure_ascii=False, indent=2))

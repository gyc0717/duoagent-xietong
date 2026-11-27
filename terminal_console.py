#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Harness 终端控制台（只读巡检，不发布、不写业务数据、不打印密钥）。

用法：
  python terminal_console.py            # 交互模式
  python terminal_console.py status     # 单命令模式（供 WorkBuddy 侧调用）

命令：help / status / evidence / chain / audit [n] / reconcile / decisions /
      verify / publish / exit

安全边界：
  - publish 永远拒绝（/publish 403，须主控硬垂询后人工触发）
  - 令牌只从 .secrets.json 运行时读取，输出只显示 sha256 前 8 位指纹
  - 所有命令只读；verify 仅跑离线测试，产物写 _scratch，不碰 real/out
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

BASE = Path(__file__).resolve().parent
SECRETS = BASE / ".secrets.json"
CONSOLE = "http://127.0.0.1:8731"
GATEWAY = "http://127.0.0.1:8733"
TIMEOUT = 3


def _token() -> str | None:
    try:
        data = json.loads(SECRETS.read_text(encoding="utf-8"))
        return (data.get("L3_TOKENS") or {}).get("harness") or data.get("L3_GATEWAY_TOKEN")
    except Exception:
        return None


def _fp(tok: str | None) -> str:
    return hashlib.sha256((tok or "").encode()).hexdigest()[:8] if tok else "-"


def _get(url: str, token: str | None = None) -> tuple[int, object]:
    headers = {}
    if token:
        headers["X-L3-Token"] = token
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            return r.status, json.loads(r.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        return e.code, {"error": str(e)}
    except Exception as e:
        return 0, {"error": type(e).__name__ + ": " + str(e)}


def _read_json(path: Path) -> object | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def cmd_help() -> None:
    print("命令：")
    print("  status            控制台 + 网关健康/门禁（只读）")
    print("  evidence          沙箱 9/9 证据摘要")
    print("  chain             八步链结论摘要")
    print("  audit [n]         最近 n 条网关审计（默认 8，令牌仅指纹）")
    print("  reconcile         成本对账末行（不做实时对账）")
    print("  decisions         设计决定 D-xxx 列表")
    print("  verify            离线回归 3/3（写 _scratch，不碰交付）")
    print("  publish           永远拒绝：须人工硬垂询触发")
    print("  help / exit")


def cmd_status() -> None:
    tok = _token()
    print("[8731 控制台]")
    code, d = _get(CONSOLE + "/api/status")
    if code == 200 and isinstance(d, dict):
        steps = d.get("steps") or []
        ok = sum(1 for s in steps if isinstance(s, dict) and s.get("status") == "ok")
        print(f"  state={d.get('state')} task={d.get('task')} 完成步数={ok}/{len(steps)} 成本=¥{d.get('cost')}")
    else:
        print(f"  HTTP {code} {d}")
    print("[8733 网关]")
    code, d = _get(GATEWAY + "/health")
    print(f"  /health  HTTP {code} {d if code != 200 else d.get('service','')}")
    code, d = _get(GATEWAY + "/status", tok)
    if code == 200 and isinstance(d, dict):
        ev = d.get("eval") if isinstance(d.get("eval"), dict) else {}
        integ = d.get("integrity") if isinstance(d.get("integrity"), dict) else {}
        print(f"  /status  HTTP {code} token_fp={_fp(tok)} artifacts={d.get('artifacts')} "
              f"acceptance={d.get('acceptance')} integrity_pass={integ.get('pass')} "
              f"verdict={ev.get('verdict')} gates={ev.get('gates_passed')}")
    else:
        print(f"  /status  HTTP {code} {d}")


def cmd_evidence() -> None:
    d = _read_json(BASE / "real" / "out" / "execution_evidence.json")
    if not isinstance(d, dict):
        print("  证据文件缺失或无法解析")
        return
    checks = d.get("checks") or {}
    passed = sum(1 for v in checks.values() if isinstance(v, dict) and v.get("pass"))
    print(f"  沙箱 {passed}/{len(checks)} · source={d.get('evidence_source')} · elapsed={d.get('elapsed_ms')}ms")


def cmd_chain() -> None:
    d = _read_json(BASE / "real" / "out" / "chain_summary.json")
    if not isinstance(d, dict):
        print("  链摘要缺失或无法解析")
        return
    steps = d.get("steps") or []
    ok = sum(1 for s in steps if isinstance(s, dict) and s.get("ok"))
    print(f"  标签={d.get('label')} run_id={d.get('run_id')} 八步 {ok}/{len(steps)}")
    for s in steps:
        print(f"    {s.get('node')} {'OK' if s.get('ok') else 'FAIL'} {str(s.get('detail',''))[:90]}")


def cmd_audit(n: int = 8) -> None:
    p = BASE / "cohort_l3" / "gateway_calls.jsonl"
    try:
        lines = [l for l in p.read_text(encoding="utf-8").splitlines() if l.strip()][-max(1, n):]
    except Exception:
        print("  审计文件不可读")
        return
    for line in lines:
        try:
            r = json.loads(line)
        except Exception:
            continue
        print(f"  {r.get('ts')} {str(r.get('path')):16} HTTP {r.get('code')} caller={r.get('caller')} "
              f"token_fp={r.get('token_fp')}")


def cmd_reconcile() -> None:
    p = BASE / "cohort_l3" / "cost_reconcile.jsonl"
    try:
        lines = [l for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]
    except Exception:
        print("  对账文件不可读")
        return
    valid = []
    for line in lines:
        try:
            r = json.loads(line)
        except Exception:
            continue
        if r.get("kind") in (None, "reconcile"):
            valid.append(r)
    if not valid:
        print("  无有效对账行")
        return
    # D-007：优先展示有偏差率的隔夜对账行，零差额行（缓存延迟）不覆盖它
    last = next((r for r in reversed(valid) if r.get("deviation_pct") is not None), valid[-1])
    print(f"  ts={last.get('ts')} provider={last.get('matched_provider')} "
          f"estimate=¥{last.get('estimate_cny')} delta=¥{last.get('balance_delta_cny')} "
          f"deviation={last.get('deviation_pct')} status={last.get('deviation_status')} "
          f"calibration={last.get('calibration')}")


def cmd_decisions() -> None:
    p = BASE / "DECISIONS.md"
    try:
        for line in p.read_text(encoding="utf-8").splitlines():
            if line.startswith("## D-"):
                print("  " + line[3:])
    except Exception:
        print("  DECISIONS.md 不可读")


def cmd_verify() -> None:
    print("  运行 run_tests.py --quick（离线、写 _scratch）...")
    p = subprocess.run([sys.executable, "run_tests.py", "--quick"], cwd=str(BASE),
                       capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120)
    summary = [l for l in (p.stdout or "").splitlines() if "组通过" in l or l.strip().startswith(("✓", "✗"))]
    print(f"  exit={p.returncode}")
    for line in summary[-6:]:
        print("   ", line)


def cmd_publish() -> None:
    print("  拒绝：/publish 始终 403，禁止自动化调用。须主控硬垂询后人工触发。")


def dispatch(cmd: str, arg: str | None) -> None:
    c = (cmd or "").strip().lower()
    if c in ("help", "?", ""):
        cmd_help()
    elif c == "status":
        cmd_status()
    elif c == "evidence":
        cmd_evidence()
    elif c == "chain":
        cmd_chain()
    elif c == "audit":
        cmd_audit(int(arg) if arg and arg.isdigit() else 8)
    elif c == "reconcile":
        cmd_reconcile()
    elif c == "decisions":
        cmd_decisions()
    elif c == "verify":
        cmd_verify()
    elif c == "publish":
        cmd_publish()
    elif c in ("exit", "quit", "q"):
        raise SystemExit(0)
    else:
        print(f"  未知命令：{cmd}（输入 help 查看）")


def main() -> int:
    args = sys.argv[1:]
    if args:
        dispatch(args[0], args[1] if len(args) > 1 else None)
        return 0
    print("Harness 终端控制台 · 只读巡检 · 输入 help 查看命令")
    while True:
        try:
            line = input("harness> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        parts = line.split(maxsplit=1)
        try:
            dispatch(parts[0] if parts else "", parts[1] if len(parts) > 1 else None)
        except SystemExit:
            return 0
        except Exception as e:
            print("  执行异常：", type(e).__name__, e)


if __name__ == "__main__":
    sys.exit(main())

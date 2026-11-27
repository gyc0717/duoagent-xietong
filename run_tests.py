#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""一条命令跑完全部离线测试（不依赖正在运行的服务）。

    python run_tests.py            # 全部
    python run_tests.py --quick    # 跳过需要起进程的网关测试
    python run_tests.py -v         # 失败时打印完整 stderr

失败时**必须留下**：失败用例名（unittest 的 FAIL/ERROR 行）+ stderr 尾部，
否则偶发失败无法定位。
"""
from __future__ import annotations

import os
import re
import socket
import subprocess
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parent
PY = sys.executable
SAMPLE = PROJECT / "_scratch" / "sample_orders.csv"
STDERR_TAIL = 25

SAMPLE_ROWS = """订单号,下单时间,品类,省份,成交金额,是否退货,退货原因,退款金额
O001,2026-10-02 10:15:00,空调,广东,4599.00,否,,0
O002,2026-10-03 14:20:00,冰箱,江苏,3299.50,是,尺寸不符,3299.50
O003,2026-10-05 09:05:00,洗衣机,浙江,2199.00,否,,0
O004,2026-10-11 22:40:00,空调,广东,5199.00,是,安装延迟,5199.00
O005,2026-11-01 08:30:00,电视,四川,3699.00,否,,0
O006,2026-11-11 20:10:00,冰箱,江苏,2899.00,是,价格保护,2899.00
"""


def port_free(port: int) -> bool:
    with socket.socket() as s:
        return s.connect_ex(("127.0.0.1", port)) != 0


def failing_cases(output: str) -> list[str]:
    """从 unittest 输出里抓失败用例名。"""
    hits = re.findall(r"^(?:FAIL|ERROR): (\S+) \((.+?)\)", output, re.M)
    return [f"{case}  [{mod}]" for case, mod in hits]


def run(name: str, cmd: list[str], verbose: bool = False) -> dict:
    print(f"\n=== {name} ===")
    p = subprocess.run(cmd, cwd=str(PROJECT), capture_output=True, text=True,
                       encoding="utf-8", errors="replace",
                       env={**os.environ, "PYTHONIOENCODING": "utf-8"})
    out, err = p.stdout or "", p.stderr or ""
    ok = p.returncode == 0
    print(f"   exit={p.returncode} -> {'PASS' if ok else 'FAIL'}")
    for line in out.strip().splitlines()[-3:]:
        print("   ", line)
    if not ok:
        bad = failing_cases(out) or failing_cases(err)
        if bad:
            print("   失败用例：")
            for b in bad:
                print("     ✗", b)
        tail = (err or out).strip().splitlines()[-STDERR_TAIL:]
        print(f"   错误尾部（最后 {len(tail)} 行）：")
        for line in tail:
            print("     |", line)
        if verbose:
            print("   ---- 完整 stderr ----")
            print(err or "（空）")
    return {"name": name, "ok": ok, "failing": failing_cases(out) or failing_cases(err)}


def main() -> int:
    quick = "--quick" in sys.argv
    verbose = "-v" in sys.argv or "--verbose" in sys.argv
    if not SAMPLE.exists():
        SAMPLE.parent.mkdir(parents=True, exist_ok=True)
        SAMPLE.write_text(SAMPLE_ROWS, encoding="utf-8")

    results = [
        run("单元测试（契约 + L3）",
            [PY, "-m", "unittest", "discover", "-s", "tests", "-v"], verbose),
        run("口径规则引擎", [PY, "n1q/caliber.py"], verbose),
        # 测试产物写 _scratch，绝不覆盖 real/out 的交付报告
        run("数据接入管线",
            [PY, "real/ingest.py", str(SAMPLE), "--caliber", "started",
             "--out-dir", str(PROJECT / "_scratch" / "test_out")], verbose),
    ]
    if quick:
        print("\n(跳过网关测试：--quick)")
    elif not port_free(8733):
        print("\n(跳过网关测试：8733 被占用，先停掉在跑的网关再跑全量)")
    else:
        results.append(run("网关鉴权/白名单", [PY, "l3/test_gateway.py"], verbose))

    passed = sum(1 for r in results if r["ok"])
    print(f"\n{'=' * 46}\n总计 {passed}/{len(results)} 组通过")
    for r in results:
        print(f"  {'✓' if r['ok'] else '✗'} {r['name']}")
        for f in r["failing"]:
            print(f"      失败：{f}")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())

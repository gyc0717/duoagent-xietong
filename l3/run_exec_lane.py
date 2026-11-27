#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""执行并行 3/3 —— 让 N2 / N3 / N4 真的并发跑，并留下墙钟证据

方案里的时序：入口 2/2（N1 ∥ N1Q）→ 执行 3/3（N2 ∥ N3 ∥ N4）。
之前 N2/N3/N4 是三个脚本分别串行跑，验收第 3 项因此一直判不过。
这里用一个极小的调度器把三者真正并发起来，并记录 wall / sum / speedup。

跑法：python l3/run_exec_lane.py [N4 索引目录]
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT / "l3"))

from workspace import Workspace  # noqa: E402

PY = sys.executable
DEFAULT_INDEX_DIR = PROJECT / "real" / "out"


def run(name: str, cmd: list[str]) -> dict:
    t0 = time.perf_counter()
    p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                       errors="replace", cwd=str(PROJECT))
    ms = round((time.perf_counter() - t0) * 1000)
    ok = p.returncode == 0
    print(f"  {'✓' if ok else '✗'} {name:6} {ms:>6} ms  rc={p.returncode}")
    if not ok:
        for line in (p.stderr or "").strip().splitlines()[-4:]:
            print(f"      ! {line[:140]}")
    return {"node": name, "ms": ms, "ok": ok, "rc": p.returncode}


def main() -> int:
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_INDEX_DIR
    ws = Workspace(PROJECT / "cohort_l3").ensure()

    lanes = [
        ("N2", [PY, str(PROJECT / "real" / "data_exec.py")]),
        ("N3", [PY, str(PROJECT / "real" / "charts.py")]),
        ("N4", [PY, str(PROJECT / "n4" / "indexer.py"), str(target),
                str(PROJECT / "n4" / f"index_lane_{target.name}.json")]),
    ]
    print(f"执行阶段 3/3 并发（索引目录：{target}）")
    t0 = time.perf_counter()
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = [pool.submit(run, n, c) for n, c in lanes]
        results = [f.result() for f in futures]
    wall = round((time.perf_counter() - t0) * 1000)
    summed = sum(r["ms"] for r in results)
    speedup = round(summed / wall, 2) if wall else None

    # 判据是「同一轮里三个节点并发跑完且都成功」，speedup 只作观测值——
    # 这里 N4 索引 758MB 占了绝大部分时间，墙钟提速有限，不代表并行没发生。
    ok = all(r["ok"] for r in results)
    ws.ledger({"kind": "parallel_exec", "nodes": [n for n, _ in lanes],
               "wall_ms": wall, "sum_ms": summed, "speedup": speedup,
               "all_ok": all(r["ok"] for r in results),
               "index_target": str(target)})
    print(json.dumps({"nodes": [n for n, _ in lanes], "wall_ms": wall,
                      "sum_ms": summed, "speedup": speedup,
                      "all_ok": all(r["ok"] for r in results)},
                     ensure_ascii=False, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

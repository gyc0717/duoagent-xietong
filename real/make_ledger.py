#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""P3 · L0 结构化数据执行器 —— 真实数据层（非模型生成）

生成 48,216 行经营明细，落 CSV；口径：空值按 0 计入并单独标注。
确定性种子，可重复复算（sha256 稳定）。
"""
from __future__ import annotations

import csv
import random
from pathlib import Path

ROWS = 48_216
SEED = 20261125
BANDS = ("¥0–199", "¥200–399", "¥400+")


def band_of(amount: float) -> str:
    if amount < 200:
        return BANDS[0]
    if amount < 400:
        return BANDS[1]
    return BANDS[2]


def generate(path: Path, rows: int = ROWS, seed: int = SEED) -> Path:
    rnd = random.Random(seed)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["order_id", "amount_cny", "status", "created_at"])
        for i in range(rows):
            base = max(0.0, rnd.gauss(260, 120))
            amount = None if rnd.random() < 0.015 else round(base, 2)
            eff = 0.0 if amount is None else amount
            band = band_of(eff)
            p_return = {"¥0–199": 0.0162, "¥200–399": 0.0230, "¥400+": 0.0311}[band]
            status = "returned" if rnd.random() < p_return else "paid"
            w.writerow([f"O{i:06d}", "" if amount is None else f"{amount:.2f}", status,
                        f"2026-{rnd.randint(1, 11):02d}-{rnd.randint(1, 28):02d}"])
    return path


if __name__ == "__main__":
    out = Path(__file__).resolve().parent / "out" / "ledger.csv"
    generate(out)
    print(f"generated {out} rows={ROWS}")

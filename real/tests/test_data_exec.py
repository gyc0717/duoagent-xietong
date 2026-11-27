#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""数据层单测（12 例）—— 沙箱真实执行，不允许「模型说你过了」。"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import data_exec  # noqa: E402


def rows(spec):
    out = []
    for i, (amount, status) in enumerate(spec):
        out.append({
            "order_id": f"O{i}", "amount": amount,
            "effective_amount": 0.0 if amount is None else amount,
            "null_amount": amount is None, "status": status, "month": "2026-11",
        })
    return out


class TestBand(unittest.TestCase):
    def test_band_low(self):
        self.assertEqual(data_exec.band_of(0), "¥0–199")

    def test_band_mid(self):
        self.assertEqual(data_exec.band_of(199.99), "¥0–199")
        self.assertEqual(data_exec.band_of(200), "¥200–399")

    def test_band_high(self):
        self.assertEqual(data_exec.band_of(400), "¥400+")

    def test_null_goes_to_low_band(self):
        self.assertEqual(data_exec.band_of(0.0), "¥0–199")


class TestSummarize(unittest.TestCase):
    def test_counts_orders(self):
        d = data_exec.summarize(rows([(100, "paid"), (500, "paid")]))
        self.assertEqual(d["totals"]["orders"], 2)

    def test_null_counted_as_zero_and_flagged(self):
        d = data_exec.summarize(rows([(None, "paid"), (300, "paid")]))
        self.assertEqual(d["totals"]["null_amount_rows"], 1)
        self.assertEqual(d["groups"][0]["orders"], 1)

    def test_return_rate_by_orders_not_amount(self):
        d = data_exec.summarize(rows([(100, "returned"), (100, "paid"), (100, "paid"), (100, "paid")]))
        self.assertAlmostEqual(d["totals"]["return_rate"], 0.25, places=4)

    def test_aov_includes_null_as_zero(self):
        d = data_exec.summarize(rows([(100, "paid"), (None, "paid")]))
        self.assertAlmostEqual(d["totals"]["aov_cny"], 50.0, places=2)

    def test_reconciliation_diff_zero(self):
        d = data_exec.summarize(rows([(100, "paid"), (250, "returned"), (900, "paid")]))
        self.assertEqual(d["reconciliation"]["diff"], 0)

    def test_group_order_sum_equals_rows(self):
        spec = [(100, "paid")] * 3 + [(250, "paid")] * 2 + [(900, "returned")]
        d = data_exec.summarize(rows(spec))
        self.assertEqual(d["reconciliation"]["sum_group_orders"], 6)

    def test_chart_value_lock_flag(self):
        self.assertTrue(data_exec.summarize(rows([(100, "paid")]))["chart_value_lock"])

    def test_empty_input_does_not_raise(self):
        d = data_exec.summarize([])
        self.assertEqual(d["totals"]["orders"], 0)

    def test_naive_impl_raises_on_null(self):
        """朴素实现无视空值策略 —— 沙箱在真运行时把缺陷钉死。"""
        with self.assertRaises(TypeError):
            data_exec.naive_summary(rows([(None, "paid")]))


if __name__ == "__main__":
    unittest.main(verbosity=2)

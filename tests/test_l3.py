#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""L3 工作区 + N5 executor + N4 索引器的真实单测。

跑法：python -m unittest discover -s tests -v
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT / "l3"))
sys.path.insert(0, str(PROJECT / "n4"))

import indexer  # noqa: E402
from workspace import SUBDIRS, LockTimeout, Workspace, sha256_bytes  # noqa: E402


class TempWS(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "cohort"
        self.ws = Workspace(self.root).init()

    def tearDown(self):
        self.tmp.cleanup()


class TestWorkspace(TempWS):
    def test_init_creates_eight_dirs(self):
        for d in SUBDIRS:
            self.assertTrue((self.root / d).is_dir(), d)

    def test_register_writes_file_and_sha(self):
        rec = self.ws.register(node="N2", role="dsh_coder", name="code", payload={"a": 1})
        p = self.root / rec["uri"]
        self.assertTrue(p.exists())
        self.assertEqual(rec["sha256"], sha256_bytes(p.read_bytes()))
        self.assertEqual(rec["version"], 1)
        self.assertEqual(rec["content_mode"], "FULLTEXT")

    def test_same_name_bumps_version(self):
        self.ws.register(node="N2", role="dsh_coder", name="code", payload={"a": 1})
        rec2 = self.ws.register(node="N2", role="dsh_coder", name="code", payload={"a": 2})
        self.assertEqual(rec2["version"], 2)
        self.assertNotEqual(rec2["uri"].split("/")[-1], rec2["uri"].split("/")[-1].replace("v2", ""))

    def test_untrusted_cannot_enter_instruction_channel(self):
        with self.assertRaises(ValueError):
            self.ws.register(node="N1Q", role="qwen_search", name="src",
                             payload={}, trust_level="untrusted", channel="instruction")

    def test_untrusted_data_only_allowed(self):
        rec = self.ws.register(node="N1Q", role="qwen_search", name="src", payload={"x": 1},
                               trust_level="untrusted", channel="data_only")
        self.assertEqual(rec["trust_level"], "untrusted")

    def test_lock_is_exclusive(self):
        held = self.ws.lock(timeout=1.0)
        held.__enter__()          # 必须持有生成器引用，否则被回收即释放
        try:
            with self.assertRaises(LockTimeout):
                with Workspace(self.root).lock(timeout=0.3):
                    pass
        finally:
            held.__exit__(None, None, None)
        self.assertFalse(self.ws.lock_path.exists())

    def test_stale_lock_is_reclaimed(self):
        self.ws.lock_path.write_text("{}")
        old = time.time() - 3600
        os.utime(self.ws.lock_path, (old, old))
        with self.ws.lock(timeout=2.0, stale_after=60):
            pass  # 陈旧锁被回收后应当能进
        self.assertFalse(self.ws.lock_path.exists())

    def test_verify_detects_tampering(self):
        rec = self.ws.register(node="N2", role="dsh_coder", name="code", payload={"a": 1})
        (self.root / rec["uri"]).write_text('{"a": 2}', encoding="utf-8")
        v = self.ws.verify()
        self.assertFalse(v["pass"])
        self.assertIn(rec["id"], v["tampered"])

    def test_verify_detects_missing(self):
        rec = self.ws.register(node="N2", role="dsh_coder", name="code", payload={"a": 1})
        (self.root / rec["uri"]).unlink()
        v = self.ws.verify()
        self.assertIn(rec["id"], v["missing"])

    def test_ledger_is_append_only(self):
        self.ws.register(node="N1", role="workbuddy_dispatch", name="dispatch", payload={})
        self.ws.ledger({"kind": "note"})
        lines = self.ws.ledger_lines()
        self.assertGreaterEqual(len(lines), 2)
        self.assertEqual(lines[0]["kind"], "artifact_registered")

    def test_concurrent_registers_do_not_corrupt_registry(self):
        errors = []

        def work(i):
            try:
                Workspace(self.root).register(node="N3", role="kimi_image",
                                              name=f"chart{i}", payload={"i": i})
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)

        threads = [threading.Thread(target=work, args=(i,)) for i in range(6)]
        [t.start() for t in threads]
        [t.join() for t in threads]
        self.assertEqual(errors, [])
        rows = json.loads((self.root / "artifacts" / "registry.json").read_text(encoding="utf-8"))
        self.assertEqual(len(rows), 6)
        self.assertEqual(len({r["id"] for r in rows}), 6)


class TestHeteroGuard(TempWS):
    def test_vendor_is_derived_from_role(self):
        rec = self.ws.register(node="N3", role="kimi_image", name="c", payload={})
        self.assertEqual(rec["vendor"], "Moonshot")
        rec2 = self.ws.register(node="N5", role="dsh_l1", name="r", payload={})
        self.assertEqual(rec2["vendor"], "DeepSeek")

    def test_same_vendor_review_is_rejected(self):
        rec = self.ws.register(node="N3", role="kimi_image", name="c", payload={})
        with self.assertRaises(ValueError):
            self.ws.register_review(node="N5", role="qwen_hetero", name="het",
                                    payload={"verdict": "PASS"}, reviewer_vendor="Moonshot",
                                    target_ids=[rec["id"]])

    def test_cross_vendor_review_passes(self):
        rec = self.ws.register(node="N3", role="kimi_image", name="c", payload={})
        out = self.ws.register_review(node="N5", role="qwen_hetero", name="het",
                                      payload={"verdict": "PASS"}, reviewer_vendor="Qwen",
                                      target_ids=[rec["id"]])
        self.assertEqual(out["name"], "het")
        self.assertEqual(out["vendor"], "Qwen")

    def test_deterministic_artifact_never_conflicts(self):
        rec = self.ws.register(node="N5", role="sandbox_exec", name="ev", payload={})
        self.assertEqual(self.ws.hetero_conflicts("Qwen", [rec["id"]]), [])

    def test_conflicts_report_missing_target(self):
        self.assertEqual(self.ws.hetero_conflicts("Qwen", ["A-999"])[0]["reason"], "工件不存在")


class TestIndexer(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "small.txt").write_text("hello", encoding="utf-8")
        big = self.root / "big.bin"
        with big.open("wb") as fh:
            fh.write(b"x" * (9 << 20))
        (self.root / ".git").mkdir()
        (self.root / ".git" / "skip.txt").write_text("nope", encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def test_build_index_skips_dirs(self):
        idx = indexer.build_index(self.root)
        rels = [e["rel"] for e in idx["entries"]]
        self.assertIn("small.txt", rels)
        self.assertNotIn(".git/skip.txt", rels)

    def test_big_file_chunked(self):
        idx = indexer.build_index(self.root)
        big = next(e for e in idx["entries"] if e["rel"] == "big.bin")
        self.assertTrue(big["big"])
        self.assertEqual(len(big["chunks"]), 3)   # 9MiB / 4MiB

    def test_fulltext_on_demand_returns_whole_file(self):
        idx = indexer.build_index(self.root)
        got = indexer.load_fulltext(idx, "big.bin")
        self.assertFalse(got["truncated"])
        self.assertEqual(got["bytes_returned"], 9 << 20)

    def test_explicit_max_bytes_truncates_and_flags(self):
        idx = indexer.build_index(self.root)
        got = indexer.load_fulltext(idx, "big.bin", max_bytes=1024)
        self.assertTrue(got["truncated"])

    def test_summary_card_marks_big_as_uri_only(self):
        idx = indexer.build_index(self.root)
        big = next(e for e in idx["entries"] if e["rel"] == "big.bin")
        card = indexer.summary_card(big)
        self.assertEqual(card["content_mode"], "SUMMARY_PLUS_URI")


if __name__ == "__main__":
    unittest.main(verbosity=2)

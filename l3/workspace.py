#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""L3 协同中间层 · 真实工作区（0→1 的 cohort/ 升级版）

职责：
  - 8 个子目录骨架（inbox/claims/artifacts/reviews/eval/memory/quarantine/outbox）
  - 工件登记表：id / node / role / uri / sha256 / version / content_mode / trust_level / channel / provenance
  - 跨进程文件锁（O_EXCL + 陈旧锁回收），保证「统一走 L3、不点对点直连」
  - append-only 台账 ledger.jsonl
  - 完整性核验：重算 sha256，能抓出被改 / 被删的工件

零依赖，只用标准库。P0 的 trust_level / channel 在这里是硬字段，不是备注。
"""
from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

SUBDIRS = ("inbox", "claims", "artifacts", "reviews", "eval", "memory", "quarantine", "outbox")

TRUST_LEVELS = ("trusted", "untrusted")
CHANNELS = ("instruction", "data_only", "both")
CONTENT_MODES = ("FULLTEXT", "SUMMARY_PLUS_URI")

# 厂商归属：异构复核的判据是「reviewer 的厂商 ≠ 被审工件的厂商」，不是写死 reviewer=qwen
VENDOR_BY_ROLE = {
    "workbuddy_dispatch": "WorkBuddy",
    "qwen_search": "Qwen",
    "qwen_hetero": "Qwen",
    "dsh_coder": "DeepSeek",
    "dsh_l1": "DeepSeek",
    "kimi_image": "Moonshot",
    "doubao_chat": "Doubao",
    "marvis_device": "Marvis",
    "sandbox_exec": "deterministic",
    "data_executor": "deterministic",
}
REVIEWER_ROLES = ("qwen_hetero",)


def _now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def sha256_file(p: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with p.open("rb") as fh:
        while True:
            blk = fh.read(chunk)
            if not blk:
                break
            h.update(blk)
    return h.hexdigest()


class LockTimeout(RuntimeError):
    pass


class Workspace:
    def __init__(self, root: str | Path, task_id: str = "T-20261125-001",
                 trace_id: str = "tr-096f926497"):
        self.root = Path(root)
        self.task_id = task_id
        self.trace_id = trace_id
        self.registry_path = self.root / "artifacts" / "registry.json"
        self.lock_path = self.root / ".lock"
        self.ledger_path = self.root / "ledger.jsonl"

    # ---------------- 骨架 ----------------
    def init(self) -> "Workspace":
        for d in SUBDIRS:
            (self.root / d).mkdir(parents=True, exist_ok=True)
        if not self.registry_path.exists():
            self._write_registry([])
        self.ledger_path.touch(exist_ok=True)
        return self

    def ensure(self) -> "Workspace":
        if not self.root.exists() or not self.registry_path.exists():
            self.init()
        return self

    # ---------------- 文件锁 ----------------
    @contextmanager
    def lock(self, timeout: float = 10.0, stale_after: float = 120.0) -> Iterator[None]:
        deadline = time.monotonic() + timeout
        fd = None
        while True:
            try:
                fd = os.open(self.lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(fd, json.dumps({"pid": os.getpid(), "at": _now()}).encode())
                break
            except FileExistsError:
                # 锁文件可能在 stat 前被别的线程释放（O_EXCL 与 unlink 之间有窗口）。
                # 这种竞争不是错误：直接重试拿锁，不要去 stat 已消失的路径。
                try:
                    age = time.time() - self.lock_path.stat().st_mtime
                except FileNotFoundError:
                    continue
                if age > stale_after:          # 陈旧锁：进程崩了但锁没释放
                    try:
                        self.lock_path.unlink()
                    except FileNotFoundError:
                        continue               # 别人刚释放，回到循环重试
                if time.monotonic() > deadline:
                    raise LockTimeout(f"拿不到工作区锁：{self.lock_path}（已等 {timeout}s）")
                time.sleep(0.02)
        try:
            yield
        finally:
            if fd is not None:
                os.close(fd)
            try:
                self.lock_path.unlink()
            except FileNotFoundError:
                pass

    # ---------------- 登记表 ----------------
    def _read_registry(self) -> list[dict[str, Any]]:
        if not self.registry_path.exists():
            return []
        return json.loads(self.registry_path.read_text(encoding="utf-8"))

    def _write_registry(self, rows: list[dict[str, Any]]) -> None:
        # 每个写入者用独立临时文件；并发 init/register 时不会互相抢同一个 .tmp
        tmp = self.registry_path.with_name(
            f"{self.registry_path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
        tmp.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.registry_path)

    def register(self, *, node: str, role: str, name: str, payload: Any,
                 content_mode: str = "FULLTEXT", trust_level: str = "trusted",
                 channel: str = "both", provenance: str = "",
                 vendor: str | None = None) -> dict[str, Any]:
        """登记一个工件：落盘 → 算 sha256 → 同名自动 version+1 → 进登记表。"""
        if trust_level not in TRUST_LEVELS:
            raise ValueError(f"trust_level 必须是 {TRUST_LEVELS}")
        if channel not in CHANNELS:
            raise ValueError(f"channel 必须是 {CHANNELS}")
        if content_mode not in CONTENT_MODES:
            raise ValueError(f"content_mode 必须是 {CONTENT_MODES}")
        # P0 硬规则：外部不可信内容永不允许进指令通道
        if trust_level == "untrusted" and channel == "instruction":
            raise ValueError("违反 P0：untrusted 工件不得进入指令通道")
        # 督办闸：没有认领记录（claims/<node>.json）的节点不许产出（opt-in）
        if os.environ.get("L3_REQUIRE_CLAIM") == "1":
            claim = self.root / "claims" / f"{node}.json"
            if not claim.exists():
                raise ValueError(
                    f"【督办拦截】节点 {node} 没有认领记录（{claim.name}），拒绝产出结论")

        # ensure() 必须进锁：原实现在锁外 init，6 线程同时写 registry 会互相踩临时文件
        body = payload if isinstance(payload, str) else json.dumps(
            payload, ensure_ascii=False, indent=2)
        data = body.encode("utf-8")
        digest = sha256_bytes(data)

        with self.lock():
            self.ensure()
            rows = self._read_registry()
            same = [r for r in rows if r["node"] == node and r["name"] == name]
            version = max((r["version"] for r in same), default=0) + 1
            safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in name)
            fname = f"{node}_{safe}.v{version}.json"
            path = self.root / "artifacts" / fname
            path.write_bytes(data)

            record = {
                "id": f"A-{len(rows) + 1:03d}",
                "node": node, "role": role, "name": name,
                "uri": str(path.relative_to(self.root)).replace("\\", "/"),
                "sha256": digest, "bytes": len(data), "version": version,
                "content_mode": content_mode, "trust_level": trust_level,
                "channel": channel, "provenance": provenance or f"L3/{node}",
                "vendor": vendor or VENDOR_BY_ROLE.get(role, "unknown"),
                "trace_id": self.trace_id, "task_id": self.task_id,
                "created_at": _now(),
            }
            rows.append(record)
            self._write_registry(rows)
        self.ledger({"kind": "artifact_registered", "id": record["id"], "node": node,
                     "sha256": digest, "version": version, "trust_level": trust_level,
                     "channel": channel})
        return record

    # ---------------- 台账 ----------------
    def ledger(self, event: dict[str, Any]) -> None:
        line = {"ts": _now(), "task_id": self.task_id, "trace_id": self.trace_id, **event}
        with self.lock():
            with self.ledger_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(line, ensure_ascii=False) + "\n")

    def ledger_lines(self) -> list[dict[str, Any]]:
        if not self.ledger_path.exists():
            return []
        return [json.loads(l) for l in self.ledger_path.read_text(encoding="utf-8").splitlines() if l.strip()]

    # ---------------- 完整性核验 ----------------
    def verify(self) -> dict[str, Any]:
        rows = self._read_registry()
        missing, tampered, ok = [], [], 0
        for r in rows:
            p = self.root / r["uri"]
            if not p.exists():
                missing.append(r["id"])
                continue
            if sha256_bytes(p.read_bytes()) != r["sha256"]:
                tampered.append(r["id"])
                continue
            ok += 1
        return {"total": len(rows), "ok": ok, "missing": missing, "tampered": tampered,
                "pass": not missing and not tampered}

    def by_node(self, node: str) -> list[dict[str, Any]]:
        return [r for r in self._read_registry() if r["node"] == node]

    # ---------------- 异构复核的厂商校验 ----------------
    def hetero_conflicts(self, reviewer_vendor: str,
                         target_ids: list[str]) -> list[dict[str, Any]]:
        """返回「reviewer 与被审工件同厂」的冲突列表。空列表才算真异构。"""
        rows = {r["id"]: r for r in self._read_registry()}
        conflicts = []
        for tid in target_ids:
            r = rows.get(tid)
            if r is None:
                conflicts.append({"id": tid, "reason": "工件不存在"})
                continue
            pv = r.get("vendor") or VENDOR_BY_ROLE.get(r.get("role", ""), "unknown")
            if pv == "deterministic":
                continue
            if pv == reviewer_vendor:
                conflicts.append({"id": tid, "node": r["node"], "name": r["name"],
                                  "producer_vendor": pv, "reviewer_vendor": reviewer_vendor})
        return conflicts

    def register_review(self, *, node: str, role: str, name: str, payload: Any,
                        reviewer_vendor: str, target_ids: list[str],
                        provenance: str = "") -> dict[str, Any]:
        """登记复核结论前先过异构闸：同厂直接拒绝，不允许「同源互审算通过」。"""
        conflicts = self.hetero_conflicts(reviewer_vendor, target_ids)
        if conflicts:
            raise ValueError(f"违反异构规则：reviewer={reviewer_vendor} 与被审工件同厂 {conflicts}")
        return self.register(node=node, role=role, name=name, payload=payload,
                             content_mode="FULLTEXT", trust_level="trusted", channel="both",
                             provenance=provenance or f"异构复核 / reviewer={reviewer_vendor}")

    def summary(self) -> dict[str, Any]:
        rows = self._read_registry()
        return {
            "root": str(self.root),
            "artifacts": len(rows),
            "nodes": sorted({r["node"] for r in rows}),
            "trust": {t: sum(1 for r in rows if r["trust_level"] == t) for t in TRUST_LEVELS},
            "fulltext": sum(1 for r in rows if r["content_mode"] == "FULLTEXT"),
            "ledger_events": len(self.ledger_lines()),
        }


def _cli(argv: list[str]) -> int:
    cmd = argv[1] if len(argv) > 1 else "summary"
    ws = Workspace(argv[2] if len(argv) > 2 else "cohort_l3")
    if cmd == "init":
        ws.init()
        print(f"initialized {ws.root} dirs={','.join(SUBDIRS)}")
    elif cmd == "verify":
        print(json.dumps(ws.verify(), ensure_ascii=False, indent=2))
    elif cmd == "summary":
        print(json.dumps(ws.summary(), ensure_ascii=False, indent=2))
    else:
        print(f"unknown command: {cmd}")
        return 2
    return 0


if __name__ == "__main__":
    import sys
    raise SystemExit(_cli(sys.argv))

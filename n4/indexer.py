#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""N4 · 本地资料与大文件管理员（Marvis 职责的真实实现）

职责边界（方案 0.2）：只管内部私有资料，不出本地。
落地三件事：建索引 / 按任务切片 / 按需全文加载（fulltext_on_demand=true，零强制截断）。

大文件不进上下文，只进「摘要 + URI」双通道；真要全文时由 load_fulltext() 按需读盘。
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SKIP_DIRS = {".git", "node_modules", "__pycache__", ".pnpm-store", ".venv", "venv", ".dsh-office"}
CHUNK = 4 << 20          # 4 MiB 切片
BIG_THRESHOLD = 8 << 20  # ≥8 MiB 记为大文件


def _now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def sha256_file(p: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with p.open("rb") as fh:
        for blk in iter(lambda: fh.read(chunk), b""):
            h.update(blk)
    return h.hexdigest()


def build_index(root: str | Path, out: str | Path | None = None,
                big_threshold: int = BIG_THRESHOLD, hash_limit: int = 512 << 20) -> dict[str, Any]:
    root = Path(root)
    if not root.exists():
        raise FileNotFoundError(root)
    entries: list[dict[str, Any]] = []
    skipped_huge = 0
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for fn in filenames:
            p = Path(dirpath) / fn
            try:
                st = p.stat()
            except OSError:
                continue
            big = st.st_size >= big_threshold
            entry = {
                "path": str(p).replace("\\", "/"),
                "rel": str(p.relative_to(root)).replace("\\", "/"),
                "bytes": st.st_size,
                "mtime": datetime.fromtimestamp(st.st_mtime).astimezone().isoformat(timespec="seconds"),
                "big": big,
                "chunks": None,
                "sha256": None,
            }
            if st.st_size <= hash_limit:
                entry["sha256"] = sha256_file(p)
            else:
                skipped_huge += 1
            if big:
                n = max(1, -(-st.st_size // CHUNK))
                entry["chunks"] = [{"seq": i, "offset": i * CHUNK,
                                    "length": min(CHUNK, st.st_size - i * CHUNK)}
                                   for i in range(n)]
            entries.append(entry)

    entries.sort(key=lambda e: -e["bytes"])
    index = {
        "root": str(root).replace("\\", "/"),
        "built_at": _now(),
        "files": len(entries),
        "total_bytes": sum(e["bytes"] for e in entries),
        "big_files": sum(1 for e in entries if e["big"]),
        "unhashed_over_limit": skipped_huge,
        "policy": {"skipped_dirs": sorted(SKIP_DIRS), "chunk_bytes": CHUNK,
                   "big_threshold_bytes": big_threshold,
                   "fulltext_on_demand": True, "truncation": False},
        "entries": entries,
    }
    if out:
        out = Path(out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")
    return index


def load_fulltext(index: dict[str, Any], rel: str, max_bytes: int | None = None) -> dict[str, Any]:
    """按需全文加载：默认整份读回（零裁剪）；max_bytes 只在调用方显式要求时生效。"""
    root = Path(index["root"])
    match = next((e for e in index["entries"] if e["rel"] == rel), None)
    if match is None:
        raise KeyError(f"索引里没有：{rel}")
    p = root / rel
    data = p.read_bytes()
    truncated = max_bytes is not None and len(data) > max_bytes
    if truncated:
        data = data[:max_bytes]
    return {
        "rel": rel, "bytes_on_disk": match["bytes"], "bytes_returned": len(data),
        "truncated": truncated, "sha256_expected": match["sha256"],
        "sha256_returned": hashlib.sha256(data).hexdigest(),
        "content": data,
    }


def summary_card(entry: dict[str, Any]) -> dict[str, Any]:
    """摘要 + URI 双通道：大文件默认只把这张卡交给上下文，全文等按需。"""
    return {
        "rel": entry["rel"], "uri": entry["path"], "bytes": entry["bytes"],
        "big": entry["big"], "chunks": len(entry["chunks"]) if entry["chunks"] else 0,
        "sha256": entry["sha256"],
        "content_mode": "SUMMARY_PLUS_URI" if entry["big"] else "FULLTEXT",
        "note": "大文件不整份进上下文；需要时按 rel 调 load_fulltext()",
    }


if __name__ == "__main__":
    import sys
    root = sys.argv[1] if len(sys.argv) > 1 else "."
    out = sys.argv[2] if len(sys.argv) > 2 else str(Path(root) / "index.json")
    idx = build_index(root, out)
    print(json.dumps({k: idx[k] for k in ("root", "files", "total_bytes", "big_files")},
                     ensure_ascii=False, indent=2))
    for e in idx["entries"][:5]:
        print(f"  {e['bytes']/1048576:8.2f} MB  {e['rel']}")

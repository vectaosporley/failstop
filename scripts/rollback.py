#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""rollback.py — snapshot a file before it is mutated, and restore on demand.

A safety net that fills the disk is a bug (FS: bounded by design). Snapshots live in
~/.failstop/undo/, capped by count and total size, garbage-collected oldest-first.

Library (used by the PreToolUse snapshot hook):
    snapshot(path) -> Optional[dict]     # copy the file aside before it changes

CLI (the /failstop-undo command wraps this):
    python3 scripts/rollback.py list
    python3 scripts/rollback.py undo [--id N]     # restore the most recent, or a specific one
    python3 scripts/rollback.py gc
"""
from __future__ import annotations

import argparse
import hashlib
import json
import secrets
import os
import shutil
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

HOME = Path(os.environ.get("FAILSTOP_HOME", Path.home() / ".failstop"))
UNDO = HOME / "undo"
INDEX = UNDO / "index.jsonl"

MAX_SNAPSHOTS = int(os.environ.get("FAILSTOP_UNDO_MAX", "200"))
MAX_TOTAL_MB = int(os.environ.get("FAILSTOP_UNDO_MB", "100"))
MAX_FILE_MB = int(os.environ.get("FAILSTOP_UNDO_FILE_MB", "10"))


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _append_index(row: Dict[str, Any]) -> None:
    UNDO.mkdir(parents=True, exist_ok=True)
    with INDEX.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def _read_index() -> List[Dict[str, Any]]:
    if not INDEX.is_file():
        return []
    rows = []
    for line in INDEX.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                rows.append(json.loads(line))
            except ValueError:
                continue
    return rows


def _write_index(rows: List[Dict[str, Any]]) -> None:
    UNDO.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(UNDO), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            for r in rows:
                fh.write(json.dumps(r, ensure_ascii=False) + "\n")
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, INDEX)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def snapshot(path: Path) -> Optional[Dict[str, Any]]:
    """Copy `path` aside before it is mutated. Returns the index row, or None if skipped.

    Skips: files that do not exist yet (nothing to undo), and files over the per-file cap.
    Never raises — a failed snapshot must not block the write it precedes.
    """
    try:
        p = Path(path)
        if not p.is_file():
            return None
        size = p.stat().st_size
        if size > MAX_FILE_MB * 1024 * 1024:
            return None
        UNDO.mkdir(parents=True, exist_ok=True)
        data = p.read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        snap_id = datetime.now().strftime("%Y%m%d-%H%M%S-%f") + "-" + secrets.token_hex(3)
        blob = UNDO / f"{snap_id}.blob"
        blob.write_bytes(data)
        row = {"id": snap_id, "path": str(p.resolve()), "bytes": size,
               "sha256": digest, "ts": _now(), "blob": blob.name}
        _append_index(row)
        gc()
        return row
    except Exception:  # noqa: BLE001
        return None


def gc() -> int:
    """Enforce the caps. Oldest first. Returns how many snapshots were removed."""
    rows = _read_index()
    removed = 0

    # by count
    while len(rows) > MAX_SNAPSHOTS:
        old = rows.pop(0)
        (UNDO / old.get("blob", "")).unlink(missing_ok=True)
        removed += 1

    # by total size
    def total() -> int:
        return sum((UNDO / r.get("blob", "")).stat().st_size
                   for r in rows if (UNDO / r.get("blob", "")).is_file())

    while rows and total() > MAX_TOTAL_MB * 1024 * 1024:
        old = rows.pop(0)
        (UNDO / old.get("blob", "")).unlink(missing_ok=True)
        removed += 1

    if removed:
        _write_index(rows)
    return removed


def undo(snap_id: Optional[str] = None) -> int:
    rows = _read_index()
    if not rows:
        print("nothing to undo")
        return 1
    row = rows[-1] if snap_id is None else next((r for r in rows if r["id"] == snap_id), None)
    if row is None:
        print(f"no snapshot with id {snap_id}", file=sys.stderr)
        return 1

    blob = UNDO / row["blob"]
    if not blob.is_file():
        print(f"snapshot blob missing for {row['id']}", file=sys.stderr)
        return 1

    target = Path(row["path"])
    data = blob.read_bytes()
    if hashlib.sha256(data).hexdigest() != row["sha256"]:
        print("snapshot integrity check failed; refusing to restore", file=sys.stderr)
        return 1

    # atomic restore
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(target.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, target)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise

    print(f"restored {target} from snapshot {row['id']} ({row['bytes']} bytes)")
    return 0


def list_snaps() -> int:
    rows = _read_index()
    if not rows:
        print("no snapshots")
        return 0
    for r in rows[-20:]:
        print(f"  {r['id']}  {r['bytes']:>8}b  {r['path']}")
    print(f"\n  {len(rows)} snapshot(s) · cap {MAX_SNAPSHOTS} / {MAX_TOTAL_MB} MB")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list")
    u = sub.add_parser("undo")
    u.add_argument("--id", default=None)
    sub.add_parser("gc")
    a = ap.parse_args()
    if a.cmd == "list":
        return list_snaps()
    if a.cmd == "undo":
        return undo(a.id)
    print(f"removed {gc()} snapshot(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

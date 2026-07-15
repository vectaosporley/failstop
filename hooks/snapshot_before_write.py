#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""snapshot_before_write.py — PreToolUse hook. Copy a file aside before it is mutated.

Enables rollback. Never blocks and never fails loudly: a snapshot is a safety net, not a
gate. If it cannot snapshot, the write still proceeds — the cost is one un-undoable edit,
not a stalled agent.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

MUTATING = {"Edit", "NotebookEdit", "MultiEdit", "Write"}


def main() -> int:
    raw = sys.stdin.read()
    if not raw.strip():
        return 0
    try:
        event = json.loads(raw)
    except ValueError:
        return 0
    if not isinstance(event, dict) or event.get("tool_name") not in MUTATING:
        return 0
    tool_input = event.get("tool_input")
    if not isinstance(tool_input, dict):
        return 0
    raw_path = tool_input.get("file_path") or tool_input.get("notebook_path")
    if not raw_path:
        return 0
    p = Path(str(raw_path))
    if not p.is_absolute():
        p = Path(str(event.get("cwd", "."))) / p
    try:
        import rollback
        rollback.snapshot(p)
    except Exception as exc:  # noqa: BLE001
        print(f"snapshot (non-fatal): {exc}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except BaseException:  # noqa: BLE001
        raise SystemExit(0)

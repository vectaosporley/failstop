#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""record_outcome.py — PostToolUse hook. Writes every tool outcome to memory (FS-008).

The agent does not have to remember to record anything. This runs after every tool call
and persists the result. It never blocks and never fails loudly: a memory write must not
derail a session.

Success/failure is read from `tool_response`: an `error` field, or `status == "error"`,
means failure. Absent both, success.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))


def _shape_source(tool: str, tool_input: dict) -> str:
    """The string whose SHAPE we track, per tool."""
    if tool == "Bash":
        return str(tool_input.get("command", ""))
    # for file tools, the shape is the tool + file extension, not the path
    path = tool_input.get("file_path") or tool_input.get("notebook_path") or ""
    suffix = Path(str(path)).suffix or "<none>"
    return f"{tool} {suffix}"


def _failed(tool_response) -> bool:
    if isinstance(tool_response, dict):
        if tool_response.get("error"):
            return True
        if str(tool_response.get("status", "")).lower() in {"error", "failed"}:
            return True
    return False


def main() -> int:
    raw = sys.stdin.read()
    if not raw.strip():
        return 0
    try:
        event = json.loads(raw)
    except ValueError:
        return 0
    if not isinstance(event, dict):
        return 0

    tool = event.get("tool_name")
    tool_input = event.get("tool_input")
    if not tool or not isinstance(tool_input, dict):
        return 0

    # File-writing tools are owned by post_write_check, which validates the CONTENT and
    # records the real verdict (a write that "succeeds" but produces unparseable code is a
    # failure for learning purposes). Recording here too would double-count.
    if tool in {"Edit", "Write", "NotebookEdit", "MultiEdit"}:
        return 0

    try:
        import memory
    except ImportError:
        return 0

    ok = not _failed(event.get("tool_response"))
    shape = memory.normalize_shape(_shape_source(tool, tool_input))
    fix = ""
    if not ok:
        tr = event.get("tool_response")
        fix = ""  # a human/agent adds the fix later via the learning loop; we record the failure now
    try:
        memory.record(tool, shape, ok=ok, fix=fix, context=_shape_source(tool, tool_input))
    except Exception as exc:  # noqa: BLE001
        print(f"record_outcome (non-fatal): {type(exc).__name__}: {exc}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except BaseException as exc:  # noqa: BLE001
        print(f"record_outcome error (non-fatal): {exc}", file=sys.stderr)
        raise SystemExit(0)

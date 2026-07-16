#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""record_outcome.py — PostToolUse hook. Writes every tool outcome to memory (FS-008).

The agent does not have to remember to record anything. This runs after every tool call
and persists the result. It never blocks and never fails loudly: a memory write must not
derail a session.

Success/failure is read from `tool_response`: an `error` field, or `status == "error"`,
means failure. Absent both, success.

It also records WHAT the tool said, not just that it spoke. The reputation gate decides by
comparing an error against the earlier errors of the same command shape — a run of different
errors is a fix cycle and must be left alone, a repeated error is a loop and must be stopped.
An earlier version of this hook threw the error text away and kept only the boolean, which
left the gate with nothing to compare and reduced it to counting attempts. See memory.py.
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


def _error_text(tool_response) -> str:
    """What the tool actually said. The gate decides by comparing this against the previous
    failures of the same shape, so discarding it — which this hook used to do — left the
    memory able to say only THAT something failed, never HOW. A count of failures cannot tell
    a fix cycle from a loop; only the words can."""
    # The tail, for the same reason normalize_error keeps the tail: an error's payload is at
    # the end. Truncating from the front hands the signature a header that never changes, and
    # a signature that never changes blocks a fix cycle. Measured; see memory.normalize_error.
    if not isinstance(tool_response, dict):
        return str(tool_response or "")[-600:]
    for field in ("error", "stderr", "message", "stdout", "output", "result"):
        val = tool_response.get(field)
        if val:
            return str(val)[-600:]
    return ""


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

    response = event.get("tool_response")
    ok = not _failed(response)
    shape = memory.normalize_shape(_shape_source(tool, tool_input))
    # the fix is added later by the agent or a human via the learning loop; the failure and
    # what it said are recorded now, while they exist.
    error = "" if ok else _error_text(response)
    try:
        memory.record(tool, shape, ok=ok, fix="", error=error,
                      context=_shape_source(tool, tool_input))
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

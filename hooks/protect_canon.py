#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""protect_canon.py — PreToolUse hook enforcing FS-001.

The agent may not write to the canon, nor to the code that enforces it.

Protocol (verified against the hooks reference, not assumed):

  * stdin  : JSON with `hook_event_name`, `tool_name`, `tool_input`, `cwd`, ...
             Edit  -> tool_input.file_path, old_string, new_string
             Write -> tool_input.file_path, content
  * to deny: stdout JSON with hookSpecificOutput.permissionDecision == "deny", exit 0
  * exit 2 : also blocks; stderr is fed back to the agent
  * exit 1 : DOES NOT BLOCK. Claude Code treats it as a non-blocking error and
             runs the tool anyway. A policy hook must never exit 1.

Because of that last point this hook **fails closed**: any input it cannot understand,
any error it cannot classify, results in a denial. A guard that permits when confused
is not a guard.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HOOK_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(HOOK_DIR.parent / "scripts"))

WRITING_TOOLS = {"Edit", "Write", "NotebookEdit", "MultiEdit"}

REASON = (
    "FS-001: the canon and its enforcement code are not modified from inside an agent session. "
    "A human edits {name} deliberately, outside this session, and then runs "
    "`python scripts/canon.py lock` to accept the change."
)


def _witness(action: str, detail: str = "") -> None:
    """Put the attempt on the record. Never let the recording change the decision.

    This is the one hook that fails CLOSED, so the rule has to be stated carefully: the ledger
    is not allowed to make it fail closed either. If the record cannot be written, the denial
    still stands — the denial is the safety, the entry is only the memory of it.
    """
    try:
        import ledger
        ledger.append("tool:protect_canon", action, detail)
    except Exception:  # noqa: BLE001
        pass


def deny(reason: str) -> int:
    """Deny via the documented PreToolUse decision object. Exit 0 — the hook itself succeeded."""
    _witness("refused a write to protected code", reason[:200])
    json.dump({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }, sys.stdout)
    sys.stdout.write("\n")
    sys.stdout.flush()
    return 0


def allow() -> int:
    """Say nothing. Silence lets the call proceed to the normal permission flow."""
    return 0


def block_hard(message: str) -> int:
    """Exit 2: blocks, and the agent sees stderr. Used when we cannot emit a decision safely."""
    print(f"FS-001 (fail-closed): {message}", file=sys.stderr)
    return 2


def main() -> int:
    raw = sys.stdin.read()
    if not raw.strip():
        return block_hard("no input on stdin; refusing to let the call through")

    try:
        event = json.loads(raw)
    except ValueError as exc:
        return block_hard(f"stdin was not valid JSON ({exc}); refusing to guess")

    if not isinstance(event, dict):
        return block_hard("stdin JSON was not an object")

    tool = event.get("tool_name")
    if tool not in WRITING_TOOLS:
        return allow()

    tool_input = event.get("tool_input")
    if not isinstance(tool_input, dict):
        return block_hard(f"{tool} arrived without a tool_input object")

    raw_path = tool_input.get("file_path") or tool_input.get("notebook_path")
    if not raw_path:
        return block_hard(f"{tool} arrived without a file_path")

    try:
        from canon import is_protected  # noqa: PLC0415
    except ImportError as exc:
        return block_hard(f"cannot load the protected set ({exc}); refusing to permit blindly")

    try:
        target = Path(str(raw_path))
        if not target.is_absolute():
            target = Path(str(event.get("cwd", "."))) / target
        protected = is_protected(target)
    except Exception as exc:  # noqa: BLE001
        return block_hard(f"could not resolve {raw_path!r} ({exc})")

    if protected:
        return deny(REASON.format(name=Path(str(raw_path)).name))
    return allow()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except BaseException as exc:  # noqa: BLE001
        # Never exit 1. An unhandled error must block, not permit.
        print(f"FS-001 (fail-closed): unhandled {type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(2)

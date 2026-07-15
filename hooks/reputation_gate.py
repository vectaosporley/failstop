#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""reputation_gate.py — PreToolUse hook enforcing FS-007.

Do not repeat an attempt that has already failed. If this tool has failed on this exact
command SHAPE `FAILSTOP_BLOCK_AFTER` times and never succeeded on it, deny — and quote the
recorded fix, so the agent changes strategy instead of retrying blind.

Below the threshold it is advisory (allow, but the memory still knows). This hook only ever
blocks on a well-corroborated, repeated, never-successful failure. Erring toward blocking
fails stopped; erring toward permitting fails wrong (FS-002).

Fails closed on confusion is NOT appropriate here: unlike the canon guard, a false block
would stop legitimate work. So this hook fails OPEN — if it cannot read memory or parse the
event, it stays silent and lets the call through. The cost of a missed block is one repeated
failure, which the post-hook then records. The cost of a false block is a stuck agent.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

GATED_TOOLS = {"Bash"}   # start narrow: only shell commands, where retries are cheap to detect


def allow() -> int:
    return 0


def deny(reason: str) -> int:
    json.dump({"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "deny",
        "permissionDecisionReason": reason,
    }}, sys.stdout)
    sys.stdout.write("\n")
    return 0


def main() -> int:
    raw = sys.stdin.read()
    if not raw.strip():
        return allow()
    try:
        event = json.loads(raw)
    except ValueError:
        return allow()
    if not isinstance(event, dict) or event.get("tool_name") not in GATED_TOOLS:
        return allow()

    tool_input = event.get("tool_input")
    if not isinstance(tool_input, dict):
        return allow()
    command = tool_input.get("command")
    if not command:
        return allow()

    try:
        import memory
        shape = memory.normalize_shape(str(command))
        verdict = memory.check(event["tool_name"], shape)
    except Exception:  # noqa: BLE001
        return allow()   # fail OPEN: a missed block costs one failure; a false block stalls work

    if verdict["verdict"] == "blocked":
        fix = verdict["last_fix"]
        reason = (f"FS-007: this command shape has failed {verdict['fail']} times and never "
                  f"succeeded. Retrying it unchanged will fail again.")
        if fix:
            reason += f" Recorded fix: {fix}"
        else:
            reason += " Change the approach before trying again."
        return deny(reason)
    return allow()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except BaseException:  # noqa: BLE001
        raise SystemExit(0)   # fail open

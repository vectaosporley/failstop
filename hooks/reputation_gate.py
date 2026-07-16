#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""reputation_gate.py — PreToolUse hook enforcing FS-007.

Do not repeat an attempt that has already failed — where REPEAT means same command and same
result. If this shape's newest failure carries an error it already produced since it last
worked, deny: that attempt added no information, which is the definition of a loop.

There is no attempt limit, deliberately. Two earlier versions both counted, and both were
wrong. The first blocked anything that had failed N times and never succeeded, which meant a
command that had ever worked once was immune forever (most commands work once, so the gate
was nearly inert) while a command that never worked was condemned forever with no way back —
the block prevented the very success that would clear it. The second counted failures since
the last success, which stops `npm test` on its third honest failure, exactly when a fix
cycle needs it most. The count was always a proxy for a question it could not ask: is this
attempt learning anything? Ask that instead. Ten failures with ten different errors is
progress and must not be touched. Two identical failures is a circle.

While the errors keep changing it is advisory (allow, but the memory still knows). Erring
toward blocking fails stopped; erring toward permitting fails wrong (FS-002) — and a failure
with no captured error can never be compared, so it can never be blocked.

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
        run = verdict.get("run", 0)
        repeated = str(verdict.get("repeated", ""))[:200]
        reason = (f"FS-007: this command shape has failed {run} times since it last worked, and "
                  f"the last attempt produced an error you had already hit — so it taught you "
                  f"nothing. That is the loop, not a bad streak. The error repeating is: "
                  f"{repeated}")
        if fix:
            reason += f" | Recorded fix: {fix}"
        else:
            reason += (" | You are not blocked for failing. You are blocked for failing the "
                       "SAME way twice. Change something that could change the error.")
        # The block is self-sealing: it stops the command, so the command can never produce the
        # success that would lift it. Naming the way out is part of the block, not a footnote.
        reason += (" If you have already fixed the root cause, release this shape with: "
                   f"python scripts/memory.py clear --tool {event['tool_name']} "
                   f"--shape {json.dumps(shape)}")
        _witness("gate blocked a proven loop", f"{event['tool_name']}: {shape[:100]} | {repeated[:80]}")
        return deny(reason)
    return allow()


def _witness(action: str, detail: str = "") -> None:
    """Put the block on the record — and never let recording it become a reason to fail open.

    This hook decides whether work proceeds; the ledger only remembers. If the two ever
    conflict, the ledger yields (FS-012).
    """
    try:
        import ledger
        ledger.append("tool:reputation_gate", action, detail)
    except Exception:  # noqa: BLE001
        pass


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except BaseException:  # noqa: BLE001
        raise SystemExit(0)   # fail open

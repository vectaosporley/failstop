#!/usr/bin/env python3
"""FS-007: don't repeat a failed attempt. FS-008: record outcomes from code.

Covers the reputation gate (PreToolUse) and the outcome recorder (PostToolUse), end to end
through subprocesses against a temp memory store.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
GATE = ROOT / "hooks" / "reputation_gate.py"
REC = ROOT / "hooks" / "record_outcome.py"


def run(hook: Path, event, home: Path, block_after: str = "3") -> tuple[int, str, str]:
    raw = event if isinstance(event, str) else json.dumps(event)
    import os
    env = {**os.environ, "FAILSTOP_HOME": str(home), "FAILSTOP_BLOCK_AFTER": block_after}
    p = subprocess.run([sys.executable, str(hook)], input=raw,
                       capture_output=True, text=True, timeout=20, env=env)
    return p.returncode, p.stdout, p.stderr


def denied(stdout: str) -> bool:
    try:
        return json.loads(stdout).get("hookSpecificOutput", {}).get("permissionDecision") == "deny"
    except ValueError:
        return False


def bash_pre(cmd: str) -> dict:
    return {"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": {"command": cmd}}


def bash_post(cmd: str, error: str = "") -> dict:
    resp = {"error": error} if error else {"status": "success"}
    return {"hook_event_name": "PostToolUse", "tool_name": "Bash",
            "tool_input": {"command": cmd}, "tool_response": resp}


# ── the loop: record failures, then the gate blocks the retry ─────────────────

def test_gate_blocks_after_repeated_recorded_failures(tmp_path):
    cmd = "python3 broken_script.py"
    # three recorded failures via the PostToolUse recorder
    for _ in range(3):
        code, _, _ = run(REC, bash_post(cmd, error="boom"), tmp_path)
        assert code == 0
    # now the PreToolUse gate refuses the same shape
    code, out, _ = run(GATE, bash_pre(cmd), tmp_path, block_after="3")
    assert denied(out), "the gate should block a thrice-failed, never-succeeded shape"


def test_a_different_path_same_shape_is_still_blocked(tmp_path):
    for _ in range(3):
        run(REC, bash_post("python3 /home/a/x.py", error="boom"), tmp_path)
    # different path, same shape
    code, out, _ = run(GATE, bash_pre("python3 /home/b/other.py"), tmp_path)
    assert denied(out), "shape, not string — a retry with a new path is the same attempt"


def test_gate_allows_a_shape_that_ever_succeeded(tmp_path):
    run(REC, bash_post("npm test"), tmp_path)                 # one success
    for _ in range(5):
        run(REC, bash_post("npm test", error="flaky"), tmp_path)
    code, out, _ = run(GATE, bash_pre("npm test"), tmp_path)
    assert not denied(out), "a shape that has ever worked is suspect, not blocked"


def test_gate_allows_unknown_command(tmp_path):
    code, out, _ = run(GATE, bash_pre("echo hello"), tmp_path)
    assert code == 0 and out.strip() == ""


def test_recorded_fix_is_quoted_in_denial(tmp_path):
    import os
    os.environ  # noqa
    # record a failure with a fix through the library directly
    sys.path.insert(0, str(ROOT / "scripts"))
    import importlib
    os.environ["FAILSTOP_HOME"] = str(tmp_path)
    import memory
    importlib.reload(memory)
    for _ in range(3):
        memory.record("Bash", memory.normalize_shape("foo --bar"), ok=False,
                      fix="use --baz instead")
    code, out, _ = run(GATE, bash_pre("foo --bar"), tmp_path)
    assert denied(out)
    reason = json.loads(out)["hookSpecificOutput"]["permissionDecisionReason"]
    assert "use --baz instead" in reason


# ── the recorder writes both outcomes ─────────────────────────────────────────

def test_recorder_writes_success(tmp_path):
    run(REC, bash_post("ls -la"), tmp_path)
    sys.path.insert(0, str(ROOT / "scripts"))
    import importlib, os
    os.environ["FAILSTOP_HOME"] = str(tmp_path)
    import memory
    importlib.reload(memory)
    assert memory.check("Bash", memory.normalize_shape("ls -la"))["ok"] == 1


# ── fail open: confusion must not stall the agent ─────────────────────────────

@pytest.mark.parametrize("payload", ["", "not json", "[1,2,3]", "{}"])
def test_gate_fails_open_on_bad_input(tmp_path, payload):
    code, out, _ = run(GATE, payload, tmp_path)
    assert code == 0 and out.strip() == "", "the gate must allow when confused, not block"


@pytest.mark.parametrize("payload", ["", "not json", "[1,2,3]"])
def test_recorder_never_crashes(tmp_path, payload):
    code, _, _ = run(REC, payload, tmp_path)
    assert code == 0

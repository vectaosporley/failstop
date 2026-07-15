#!/usr/bin/env python3
"""FS-001: the canon and its enforcer cannot be written from inside an agent session."""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
HOOK = ROOT / "hooks" / "protect_canon.py"

_spec = importlib.util.spec_from_file_location("canon", ROOT / "scripts" / "canon.py")
canon = importlib.util.module_from_spec(_spec)
sys.modules["canon"] = canon
_spec.loader.exec_module(canon)


def run_hook(payload) -> tuple[int, str, str]:
    raw = payload if isinstance(payload, str) else json.dumps(payload)
    p = subprocess.run([sys.executable, str(HOOK)], input=raw,
                       capture_output=True, text=True, timeout=20)
    return p.returncode, p.stdout, p.stderr


def denied(stdout: str) -> bool:
    try:
        out = json.loads(stdout)
    except ValueError:
        return False
    return out.get("hookSpecificOutput", {}).get("permissionDecision") == "deny"


def edit_event(file_path: str, tool: str = "Edit") -> dict:
    return {
        "session_id": "test", "cwd": str(ROOT), "hook_event_name": "PreToolUse",
        "tool_name": tool, "tool_use_id": "t1",
        "tool_input": {"file_path": file_path, "old_string": "a", "new_string": "b"},
    }


# ── the protected set ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("rel", canon.PROTECTED)
def test_every_protected_file_is_denied(rel):
    code, out, _ = run_hook(edit_event(str(ROOT / rel)))
    assert code == 0, "a decision was emitted, so the hook itself succeeded"
    assert denied(out), f"{rel} was not protected"


def test_the_enforcer_protects_itself():
    """Protecting the law but not its enforcer is theater."""
    assert "hooks/protect_canon.py" in canon.PROTECTED
    code, out, _ = run_hook(edit_event(str(HOOK)))
    assert denied(out)


def test_write_tool_is_covered_too():
    code, out, _ = run_hook(edit_event(str(ROOT / "CANON.md"), tool="Write"))
    assert denied(out)


def test_unrelated_file_is_allowed():
    code, out, err = run_hook(edit_event(str(ROOT / "README.md")))
    assert code == 0 and out.strip() == "", "the hook must stay silent for ordinary files"


def test_non_writing_tool_is_ignored():
    ev = edit_event(str(ROOT / "CANON.md"))
    ev["tool_name"] = "Read"
    code, out, _ = run_hook(ev)
    assert code == 0 and out.strip() == ""


def test_relative_path_is_resolved_against_cwd():
    ev = edit_event("CANON.md")
    code, out, _ = run_hook(ev)
    assert denied(out), "a relative path must not slip past the guard"


# ── fail closed: the property that makes it a law ─────────────────────────────

MALFORMED = [
    "",                          # nothing on stdin
    "not json at all",
    "[1, 2, 3]",                 # JSON, but not an object
    '{"tool_name": "Edit"}',     # no tool_input
    '{"tool_name": "Edit", "tool_input": {}}',            # no file_path
    '{"tool_name": "Edit", "tool_input": "a string"}',    # wrong type
]


@pytest.mark.parametrize("payload", MALFORMED)
def test_malformed_input_blocks_rather_than_permits(payload):
    code, out, err = run_hook(payload)
    assert code == 2, f"confused hook must block (exit 2), got {code}"
    assert "fail-closed" in err


def test_never_exits_one():
    """exit 1 is a NON-blocking error: Claude Code runs the tool anyway.

    A policy hook that exits 1 permits in silence. This asserts we never do.
    """
    payloads = MALFORMED + [json.dumps(edit_event(str(ROOT / "CANON.md"))),
                            json.dumps(edit_event(str(ROOT / "README.md")))]
    for p in payloads:
        code, _, _ = run_hook(p)
        assert code in (0, 2), f"exit {code} would let the call through"


# ── the hash and the lock ─────────────────────────────────────────────────────

def test_hash_is_stable_and_newline_agnostic(tmp_path, monkeypatch):
    lf = tmp_path / "CANON.md"
    lf.write_bytes(b"a\nb\n")
    monkeypatch.setattr(canon, "CANON", lf)
    h1 = canon.canon_hash()
    lf.write_bytes(b"a\r\nb\r\n")
    assert canon.canon_hash() == h1, "CRLF must not read as drift"


def test_verify_detects_drift(tmp_path, monkeypatch):
    lf = tmp_path / "CANON.md"
    lf.write_text("law one\n", encoding="utf-8")
    monkeypatch.setattr(canon, "CANON", lf)
    monkeypatch.setattr(canon, "LOCK", tmp_path / "canon.lock")

    assert canon.verify() == 1, "no lock yet"
    assert canon.lock() == 0
    assert canon.verify() == 0

    lf.write_text("law one, relaxed\n", encoding="utf-8")
    assert canon.verify() == 1, "drift must be reported"


def test_withdrawn_rule_never_reaches_enforced():
    """FS-011 is the rule the learning loop would have written. It was false."""
    text = (ROOT / "CANON.md").read_text(encoding="utf-8")
    i = text.index("## FS-011")
    block = text[i:text.index("---", i)]
    assert "WITHDRAWN" in block
    assert "must never be promoted" in block
    assert "`proposed`" in block
    assert "`enforced`" not in block.replace("reaches `enforced`", "")

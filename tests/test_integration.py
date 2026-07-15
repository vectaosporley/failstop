#!/usr/bin/env python3
"""Integration: hooks.json routes tool calls to the right hooks, decisions combine correctly.

This is the layer the unit tests do not cover: the wiring. It replays hooks.json exactly as
Claude Code does. It is not a substitute for installing the plugin (see docs/install.md), but
it verifies everything up to the runtime boundary.
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
import integration_harness as H  # noqa: E402


def pre(tool, tool_input, cwd=None):
    return {"hook_event_name": "PreToolUse", "tool_name": tool,
            "cwd": cwd or str(ROOT), "tool_input": tool_input}


def post(tool, tool_input, tool_response=None):
    return {"hook_event_name": "PostToolUse", "tool_name": tool, "cwd": str(ROOT),
            "tool_input": tool_input, "tool_response": tool_response or {"status": "success"}}


# ── the canon is protected through the real wiring ────────────────────────────

def test_editing_canon_is_denied_end_to_end():
    r = H.fire(pre("Edit", {"file_path": str(ROOT / "CANON.md"),
                            "old_string": "a", "new_string": "b"}))
    assert r["decision"] == "deny"
    assert "protect_canon.py" in r["fired"]
    assert any("FS-001" in x for x in r["reasons"])


def test_editing_a_hook_is_denied():
    r = H.fire(pre("Edit", {"file_path": str(ROOT / "hooks" / "protect_canon.py"),
                            "old_string": "a", "new_string": "b"}))
    assert r["decision"] == "deny", "the enforcer must protect itself"


def test_editing_an_ordinary_file_is_allowed():
    r = H.fire(pre("Edit", {"file_path": str(ROOT / "README.md"),
                            "old_string": "a", "new_string": "b"}))
    assert r["decision"] == "allow"
    # but it WAS snapshotted for rollback
    assert "snapshot_before_write.py" in r["fired"]


def test_both_prehooks_fire_for_a_write():
    r = H.fire(pre("Edit", {"file_path": str(ROOT / "README.md"),
                            "old_string": "a", "new_string": "b"}))
    assert "protect_canon.py" in r["fired"]
    assert "snapshot_before_write.py" in r["fired"]


# ── post-write integrity through the wiring ───────────────────────────────────

def test_broken_python_write_is_surfaced(tmp_path):
    f = tmp_path / "bad.py"
    f.write_text("def x(:\n", encoding="utf-8")
    r = H.fire(post("Write", {"file_path": str(f)}))
    assert r["decision"] == "block"
    assert any("does not parse" in x for x in r["reasons"])


def test_clean_write_passes(tmp_path):
    f = tmp_path / "ok.py"
    f.write_text("x = 1\n", encoding="utf-8")
    r = H.fire(post("Write", {"file_path": str(f)}))
    assert r["decision"] == "allow"


def test_record_outcome_fires_on_every_tool(tmp_path, monkeypatch):
    # the wildcard PostToolUse hook must fire even for Bash
    r = H.fire(post("Bash", {"command": "echo hi"}))
    assert "record_outcome.py" in r["fired"]


# ── the matcher logic itself ──────────────────────────────────────────────────

def test_wildcard_matches_any_tool():
    assert H._matches("*", "Bash")
    assert H._matches("*", "Anything")


def test_regex_matcher_is_exact():
    assert H._matches("Edit|Write", "Edit")
    assert H._matches("Edit|Write", "Write")
    assert not H._matches("Edit|Write", "Read")
    assert not H._matches("Edit|Write", "EditSomething")


def test_bash_gate_and_recorder_both_wired():
    """A Bash call hits the reputation gate (Pre) and the recorder (Post)."""
    rpre = H.fire(pre("Bash", {"command": "echo test"}))
    assert "reputation_gate.py" in rpre["fired"]
    rpost = H.fire(post("Bash", {"command": "echo test"}))
    assert "record_outcome.py" in rpost["fired"]

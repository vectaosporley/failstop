#!/usr/bin/env python3
"""FS-003 + FS-008: integrity of a written file, corroborated before indicting the tool."""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
HOOK = ROOT / "hooks" / "post_write_check.py"

_spec = importlib.util.spec_from_file_location("post_write_check", HOOK)
pwc = importlib.util.module_from_spec(_spec)
sys.modules["post_write_check"] = pwc
_spec.loader.exec_module(pwc)


def run_hook(event) -> tuple[int, str, str]:
    raw = event if isinstance(event, str) else json.dumps(event)
    p = subprocess.run([sys.executable, str(HOOK)], input=raw,
                       capture_output=True, text=True, timeout=20)
    return p.returncode, p.stdout, p.stderr


def blocked(stdout: str) -> bool:
    try:
        return json.loads(stdout).get("decision") == "block"
    except ValueError:
        return False


def reason(stdout: str) -> str:
    try:
        return json.loads(stdout).get("reason", "")
    except ValueError:
        return ""


def ev(path: Path, tool: str = "Write") -> dict:
    return {"hook_event_name": "PostToolUse", "tool_name": tool, "cwd": str(ROOT),
            "tool_input": {"file_path": str(path)}}


# ── clean files: say nothing ──────────────────────────────────────────────────

def test_clean_text_is_silent(tmp_path):
    f = tmp_path / "ok.txt"; f.write_text("hello\n", encoding="utf-8")
    code, out, _ = run_hook(ev(f))
    assert code == 0 and out.strip() == ""


def test_valid_python_is_silent(tmp_path):
    f = tmp_path / "ok.py"; f.write_text("def x():\n    return 1\n", encoding="utf-8")
    code, out, _ = run_hook(ev(f))
    assert code == 0 and out.strip() == ""


def test_valid_json_is_silent(tmp_path):
    f = tmp_path / "ok.json"; f.write_text('{"a": 1}', encoding="utf-8")
    code, out, _ = run_hook(ev(f))
    assert code == 0 and out.strip() == ""


# ── genuinely broken files: block with a reason ───────────────────────────────

def test_broken_python_is_reported(tmp_path):
    f = tmp_path / "bad.py"; f.write_text("def x(:\n", encoding="utf-8")
    code, out, err = run_hook(ev(f))
    assert blocked(out) and "does not parse" in reason(out)
    assert "line" in reason(out)


def test_broken_json_is_reported(tmp_path):
    f = tmp_path / "bad.json"; f.write_text("{not json", encoding="utf-8")
    code, out, _ = run_hook(ev(f))
    assert blocked(out) and "invalid JSON" in reason(out)


def test_nul_bytes_corroborated_is_corrupt(tmp_path):
    """NUL bytes whose byte count the second channel confirms -> real corruption."""
    f = tmp_path / "nul.txt"; f.write_bytes(b"abc\x00def")
    code, out, _ = run_hook(ev(f))
    assert blocked(out)
    # on this platform the second channel (stat) agrees, so it is CORRUPT, not unverifiable
    assert "corrupt" in reason(out).lower()


# ── the state that prevents today's false positive ────────────────────────────

def test_stale_read_is_unverifiable_not_corrupt(monkeypatch, tmp_path):
    """A reader that under-reports bytes must yield UNVERIFIABLE, never 'corrupt'.

    Simulates Phase 0: the process reads a short, NUL-bearing view while the real
    file on the host is a different size.
    """
    f = tmp_path / "stale.py"
    f.write_text("def ok():\n    return 1\n", encoding="utf-8")

    # process reads a corrupt-looking short view...
    monkeypatch.setattr(pwc.Path, "read_bytes", lambda self: b"def ok(\x00")
    # ...but the second channel reports the true, larger size
    monkeypatch.setattr(pwc, "_second_channel_size", lambda p: 999)

    import io
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(ev(f))))
    out = io.StringIO(); monkeypatch.setattr("sys.stdout", out)
    err = io.StringIO(); monkeypatch.setattr("sys.stderr", err)
    rc = pwc.main()
    body = out.getvalue()
    assert "UNVERIFIABLE" in body
    assert "corrupt" not in body.lower()
    assert "stale" in body.lower()


def test_no_second_channel_means_unverifiable(monkeypatch, tmp_path):
    """NUL bytes with no way to corroborate -> UNVERIFIABLE, not an accusation."""
    import io
    f = tmp_path / "x.txt"; f.write_bytes(b"a\x00b")
    monkeypatch.setattr(pwc, "_second_channel_size", lambda p: None)
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(ev(f))))
    out = io.StringIO(); monkeypatch.setattr("sys.stdout", out)
    monkeypatch.setattr("sys.stderr", io.StringIO())
    pwc.main()
    assert "UNVERIFIABLE" in out.getvalue()


# ── robustness ────────────────────────────────────────────────────────────────

def test_non_writing_tool_is_silent():
    e = {"tool_name": "Read", "tool_input": {"file_path": "/x"}, "cwd": "."}
    code, out, _ = run_hook(e)
    assert code == 0 and out.strip() == ""


@pytest.mark.parametrize("payload", ["", "not json", "[1,2,3]", "{}"])
def test_malformed_input_is_silent_not_crashing(payload):
    """PostToolUse cannot block; a bad payload must not derail the session."""
    code, out, _ = run_hook(payload)
    assert code == 0


def test_missing_file_is_reported(tmp_path):
    code, out, _ = run_hook(ev(tmp_path / "does_not_exist.txt"))
    assert blocked(out) and "cannot read it back" in reason(out)


# ── the fix: content verdict feeds memory, exactly once ───────────────────────

def test_clean_write_records_success(tmp_path, monkeypatch):
    """A clean write records ok=1 in memory (FS-008), via post_write_check."""
    monkeypatch.setenv("FAILSTOP_HOME", str(tmp_path))
    import importlib, sys as _sys
    _sys.path.insert(0, str(ROOT / "scripts"))
    _sys.path.insert(0, str(ROOT / "hooks"))
    import memory; importlib.reload(memory)
    import post_write_check as pwc2; importlib.reload(pwc2)

    f = tmp_path / "good.py"; f.write_text("x = 1\n", encoding="utf-8")
    import io, json as _json
    monkeypatch.setattr("sys.stdin", io.StringIO(_json.dumps(
        {"tool_name": "Write", "cwd": str(tmp_path), "tool_input": {"file_path": str(f)}})))
    monkeypatch.setattr("sys.stdout", io.StringIO())
    pwc2.main()
    r = memory.check("Write", memory.normalize_shape("Write .py"))
    assert r["ok"] == 1 and r["fail"] == 0


def test_broken_write_records_failure(tmp_path, monkeypatch):
    """A write that produces unparseable code records fail=1, not a false success."""
    monkeypatch.setenv("FAILSTOP_HOME", str(tmp_path))
    import importlib, sys as _sys
    _sys.path.insert(0, str(ROOT / "scripts"))
    _sys.path.insert(0, str(ROOT / "hooks"))
    import memory; importlib.reload(memory)
    import post_write_check as pwc2; importlib.reload(pwc2)

    f = tmp_path / "bad.py"; f.write_text("def add(a, b\n", encoding="utf-8")
    import io, json as _json
    monkeypatch.setattr("sys.stdin", io.StringIO(_json.dumps(
        {"tool_name": "Write", "cwd": str(tmp_path), "tool_input": {"file_path": str(f)}})))
    monkeypatch.setattr("sys.stdout", io.StringIO())
    pwc2.main()
    r = memory.check("Write", memory.normalize_shape("Write .py"))
    assert r["fail"] == 1, "a broken write must be a failure for the learning loop"


def test_record_outcome_cedes_file_writes(tmp_path, monkeypatch):
    """record_outcome must NOT also record file writes (no double count)."""
    monkeypatch.setenv("FAILSTOP_HOME", str(tmp_path))
    import importlib, sys as _sys
    _sys.path.insert(0, str(ROOT / "scripts"))
    import memory; importlib.reload(memory)
    import subprocess, json as _json
    ev = {"tool_name": "Write", "tool_input": {"file_path": str(tmp_path / "x.py")},
          "tool_response": {"status": "success"}}
    subprocess.run([_sys.executable, str(ROOT / "hooks" / "record_outcome.py")],
                   input=_json.dumps(ev), capture_output=True, text=True,
                   env={**__import__("os").environ, "FAILSTOP_HOME": str(tmp_path)})
    # record_outcome should have written nothing for a Write
    assert memory.check("Write", memory.normalize_shape("Write .py"))["ok"] == 0

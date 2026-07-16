#!/usr/bin/env python3
"""FS-008: the memory write path. Records both outcomes, survives corruption, writes atomically."""
from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))


@pytest.fixture()
def mem(tmp_path, monkeypatch):
    monkeypatch.setenv("FAILSTOP_HOME", str(tmp_path))
    import memory
    importlib.reload(memory)
    return memory


# ── shape normalization: the key to recognising a retry ───────────────────────

def test_paths_collapse_to_the_same_shape(mem):
    a = mem.normalize_shape(r"python.exe C:\a\b.py")
    b = mem.normalize_shape(r"python.exe C:\different\other.py")
    assert a == b


def test_numbers_and_hashes_collapse(mem):
    a = mem.normalize_shape("build main.a1b2c3d4e5.js --port 3000")
    b = mem.normalize_shape("build main.f9e8d7c6b5.js --port 8080")
    assert a == b


def test_distinct_commands_stay_distinct(mem):
    assert mem.normalize_shape("git status") != mem.normalize_shape("git push")


# ── record both outcomes (the lesson: not a blocklist) ────────────────────────

def test_records_success_and_failure(mem):
    mem.record("Bash", "npm install", ok=True)
    mem.record("Bash", "npm install", ok=False, fix="use --legacy-peer-deps")
    r = mem.check("Bash", "npm install")
    assert r["ok"] == 1 and r["fail"] == 1
    assert r["last_fix"] == "use --legacy-peer-deps"


def test_success_is_actually_stored(mem):
    """Regression against a store that recorded 0 successes for 29 days."""
    mem.record("Bash", "ls", ok=True)
    assert mem.check("Bash", "ls")["ok"] == 1


# ── the reputation verdict (input for the Phase 4 gate) ───────────────────────

def test_verdict_unknown_then_trusted_then_blocked(mem):
    assert mem.check("Bash", "x")["verdict"] == "unknown"
    mem.record("Bash", "x", ok=True)
    assert mem.check("Bash", "x")["verdict"] == "trusted"
    for _ in range(2):
        mem.record("Bash", "y", ok=False, error="permission denied")
    assert mem.check("Bash", "y")["verdict"] == "blocked"   # same error twice = proven loop


def test_a_shape_that_ever_succeeded_is_not_immune(mem):
    """This test asserted the opposite until the immunity it protected was measured.

    The old rule was 'ever succeeded -> never blocked', which sounds cautious and is not: a
    command that worked once in January and has failed identically every day since was waved
    through forever, and since nearly every command succeeds once early on, nearly nothing
    could ever be blocked. What the old rule was really protecting is a fix cycle — and that
    is protected properly now by novelty, not by a lifetime alibi. See
    test_a_fix_cycle_is_never_blocked_however_long in test_gate_recency.py.
    """
    mem.record("Bash", "z", ok=True)
    for _ in range(5):
        mem.record("Bash", "z", ok=False, error="the endpoint is gone")
    assert mem.check("Bash", "z")["verdict"] == "blocked"


def test_failing_differently_every_time_is_never_blocked(mem):
    """The other half of the same rule: a search must not be mistaken for a loop."""
    for i in range(6):
        mem.record("Bash", "w", ok=False, error=f"failure number {i} is a new one")
    assert mem.check("Bash", "w")["verdict"] == "suspect"


# ── durability ────────────────────────────────────────────────────────────────

def test_corrupt_store_is_quarantined_not_raised(mem, tmp_path):
    mem.STORE.parent.mkdir(parents=True, exist_ok=True)
    mem.STORE.write_text("{ broken", encoding="utf-8")
    db = mem.load()                     # must not raise
    assert db == mem.EMPTY, "a damaged store loads as a fresh one, whatever the schema is"
    quarantined = list(tmp_path.glob("memory.json.corrupt-*"))
    assert quarantined, "the corrupt store should have been set aside"


def test_write_leaves_no_tmp_files(mem, tmp_path):
    mem.record("Bash", "ls", ok=True)
    assert not list(tmp_path.glob("*.tmp"))


def test_non_dict_store_ignored(mem):
    mem.STORE.parent.mkdir(parents=True, exist_ok=True)
    mem.STORE.write_text("[1, 2, 3]", encoding="utf-8")
    assert mem.load() == mem.EMPTY


def test_log_is_capped(mem):
    for i in range(2100):
        mem.record("Bash", f"cmd{i % 5}", ok=True)
    assert len(mem.load()["log"]) <= 2000


def test_unknown_tool_is_unknown(mem):
    assert mem.check("NeverSeen")["verdict"] == "unknown"

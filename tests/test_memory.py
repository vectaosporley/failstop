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

def test_verdict_trusted_then_suspect_then_blocked(mem, monkeypatch):
    monkeypatch.setenv("FAILSTOP_BLOCK_AFTER", "3")
    importlib.reload(mem)
    assert mem.check("Bash", "x")["verdict"] == "unknown"
    mem.record("Bash", "x", ok=True)
    assert mem.check("Bash", "x")["verdict"] == "trusted"
    for _ in range(3):
        mem.record("Bash", "y", ok=False)
    assert mem.check("Bash", "y")["verdict"] == "blocked"


def test_a_shape_that_ever_succeeded_is_not_blocked(mem, monkeypatch):
    monkeypatch.setenv("FAILSTOP_BLOCK_AFTER", "2")
    importlib.reload(mem)
    mem.record("Bash", "z", ok=True)
    for _ in range(5):
        mem.record("Bash", "z", ok=False)
    # it has succeeded before, so it is suspect, not blocked
    assert mem.check("Bash", "z")["verdict"] == "suspect"


# ── durability ────────────────────────────────────────────────────────────────

def test_corrupt_store_is_quarantined_not_raised(mem, tmp_path):
    mem.STORE.parent.mkdir(parents=True, exist_ok=True)
    mem.STORE.write_text("{ broken", encoding="utf-8")
    db = mem.load()                     # must not raise
    assert db == {"tools": {}, "log": []}
    quarantined = list(tmp_path.glob("memory.json.corrupt-*"))
    assert quarantined, "the corrupt store should have been set aside"


def test_write_leaves_no_tmp_files(mem, tmp_path):
    mem.record("Bash", "ls", ok=True)
    assert not list(tmp_path.glob("*.tmp"))


def test_non_dict_store_ignored(mem):
    mem.STORE.parent.mkdir(parents=True, exist_ok=True)
    mem.STORE.write_text("[1, 2, 3]", encoding="utf-8")
    assert mem.load() == {"tools": {}, "log": []}


def test_log_is_capped(mem):
    for i in range(2100):
        mem.record("Bash", f"cmd{i % 5}", ok=True)
    assert len(mem.load()["log"]) <= 2000


def test_unknown_tool_is_unknown(mem):
    assert mem.check("NeverSeen")["verdict"] == "unknown"

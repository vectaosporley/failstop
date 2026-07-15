#!/usr/bin/env python3
"""Phase 8: the learning loop and the ratchet.

The most important tests in the project. They prove the system can add a rule without a
human, cannot enforce one without a human, and can never loosen automatically.
"""
from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))


@pytest.fixture()
def L(tmp_path, monkeypatch):
    monkeypatch.setenv("FAILSTOP_HOME", str(tmp_path))
    import learn
    importlib.reload(learn)
    return learn


def _seed_rule(learn, tmp_path, tool="Bash", shape="python3 bad.py"):
    props = tmp_path / "proposals.jsonl"
    props.write_text(json.dumps({
        "tool": tool, "shape": shape, "suggested_fix": "use -X"}) + "\n", encoding="utf-8")
    learn.draft_from_proposals()
    return next(iter(learn._load()["rules"]))


# ── the happy path, up to the wall ────────────────────────────────────────────

def test_draft_creates_proposed_rules(L, tmp_path):
    rid = _seed_rule(L, tmp_path)
    assert L._load()["rules"][rid]["tier"] == "proposed"


def test_proposed_cannot_promote_without_reproduction(L, tmp_path):
    rid = _seed_rule(L, tmp_path)
    assert L.promote(rid, "shadow") == 1, "no reproduction yet (FS-009)"
    assert L._load()["rules"][rid]["tier"] == "proposed"


def test_reproduction_without_corroboration_still_blocks(L, tmp_path):
    rid = _seed_rule(L, tmp_path)
    # reproduction passes...
    db = L._load()
    db["rules"][rid]["reproduction"] = {"passed": True}
    L._save(db)
    # ...but not corroborated
    assert L.promote(rid, "shadow") == 1, "corroboration gate (FS-003) must still hold"


def test_both_gates_allow_promotion_to_shadow(L, tmp_path):
    rid = _seed_rule(L, tmp_path)
    db = L._load()
    db["rules"][rid]["reproduction"] = {"passed": True}
    db["rules"][rid]["corroborated"] = True
    L._save(db)
    assert L.promote(rid, "shadow") == 0
    assert L._load()["rules"][rid]["tier"] == "shadow"


# ── the ratchet: the wall ─────────────────────────────────────────────────────

def test_cannot_auto_promote_to_enforced(L, tmp_path):
    rid = _seed_rule(L, tmp_path)
    db = L._load()
    db["rules"][rid].update({"tier": "shadow", "reproduction": {"passed": True},
                             "corroborated": True})
    L._save(db)
    with pytest.raises(L.RatchetViolation):
        L.promote(rid, "enforced")
    assert L._load()["rules"][rid]["tier"] == "shadow", "enforced is human-only"


def test_cannot_move_downward(L, tmp_path):
    rid = _seed_rule(L, tmp_path)
    db = L._load()
    db["rules"][rid]["tier"] = "shadow"
    L._save(db)
    with pytest.raises(L.RatchetViolation):
        L.promote(rid, "proposed")


def test_cannot_promote_same_tier(L, tmp_path):
    rid = _seed_rule(L, tmp_path)
    with pytest.raises(L.RatchetViolation):
        L.promote(rid, "proposed")


def test_cli_ratchet_returns_exit_2(L, tmp_path, monkeypatch):
    rid = _seed_rule(L, tmp_path)
    db = L._load()
    db["rules"][rid].update({"tier": "shadow", "reproduction": {"passed": True},
                             "corroborated": True})
    L._save(db)
    monkeypatch.setattr(sys, "argv", ["learn.py", "promote", "--id", rid, "--to", "enforced"])
    assert L.main() == 2, "the CLI must surface a ratchet violation, not swallow it"


# ── the withdrawn 30 KB rule: the fixture that must never advance ──────────────

def test_the_withdrawn_rule_pattern_stays_proposed(L, tmp_path):
    """A rule with a passing reproduction but no corroboration is exactly the 30 KB case."""
    rid = _seed_rule(L, tmp_path, shape="Edit file > 30kb")
    db = L._load()
    db["rules"][rid]["reproduction"] = {"passed": True}   # it DID reproduce, through one channel
    db["rules"][rid]["corroborated"] = False              # the second channel disagreed
    L._save(db)
    assert L.promote(rid, "shadow") == 1
    assert L._load()["rules"][rid]["tier"] == "proposed", "reproducible-but-false stays proposed"

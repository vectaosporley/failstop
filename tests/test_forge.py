#!/usr/bin/env python3
"""Phase 9: the agent forge. A forged agent must prove equivalence before it replaces reasoning."""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))


@pytest.fixture()
def forge(tmp_path, monkeypatch):
    monkeypatch.setenv("FAILSTOP_HOME", str(tmp_path))
    import forge
    importlib.reload(forge)
    return forge


def test_new_agent_is_not_promotable(forge):
    forge.register("a1", "convert csv")
    ok, why = forge.can_promote("a1")
    assert not ok and "baseline" in why


def test_needs_full_baseline(forge, monkeypatch):
    monkeypatch.setenv("FAILSTOP_FORGE_BASELINE", "3")
    importlib.reload(forge)
    forge.register("a1", "x")
    forge.record_baseline("a1", "in1", "out1")
    ok, why = forge.can_promote("a1")
    assert not ok


def test_divergence_blocks_promotion(forge, monkeypatch):
    monkeypatch.setenv("FAILSTOP_FORGE_BASELINE", "2")
    importlib.reload(forge)
    forge.register("a1", "x")
    forge.record_baseline("a1", "in1", "out1")
    forge.record_baseline("a1", "in2", "out2")
    # forged agent disagrees on in1
    assert forge.check_divergence("a1", "in1", "WRONG") == 2
    ok, why = forge.can_promote("a1")
    assert not ok and "divergence" in why


def test_matching_output_is_ok(forge):
    forge.register("a1", "x")
    forge.record_baseline("a1", "in1", "out1")
    assert forge.check_divergence("a1", "in1", "out1") == 0


def test_unseen_input_cannot_promote(forge):
    forge.register("a1", "x")
    forge.record_baseline("a1", "in1", "out1")
    # a forged agent must not be trusted on an input the reasoning never faced
    assert forge.check_divergence("a1", "never_seen", "anything") == 1


def test_human_review_is_required(forge, monkeypatch):
    monkeypatch.setenv("FAILSTOP_FORGE_BASELINE", "2")
    importlib.reload(forge)
    forge.register("a1", "x")
    forge.record_baseline("a1", "i1", "o1")
    forge.record_baseline("a1", "i2", "o2")
    ok, why = forge.can_promote("a1")
    assert not ok and "human" in why
    # record the human approval
    db = forge._load(); db["agents"]["a1"]["approved_by_human"] = True; forge._save(db)
    ok, why = forge.can_promote("a1")
    assert ok, why


def test_detect_needs_clean_repetition(forge, tmp_path, monkeypatch):
    monkeypatch.setenv("FAILSTOP_FORGE_MIN", "3")
    import memory
    importlib.reload(memory); importlib.reload(forge)
    for _ in range(3):
        memory.record("Bash", memory.normalize_shape("wc -l report.txt"), ok=True)
    # a shape with any failure is NOT a candidate
    memory.record("Bash", memory.normalize_shape("flaky cmd"), ok=True)
    memory.record("Bash", memory.normalize_shape("flaky cmd"), ok=False)
    assert forge.detect() == 0

#!/usr/bin/env python3
"""FS: the evaluator measures and proposes. It never legislates."""
from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))


@pytest.fixture()
def ev(tmp_path, monkeypatch):
    monkeypatch.setenv("FAILSTOP_HOME", str(tmp_path))
    import memory, evaluator
    importlib.reload(memory)
    importlib.reload(evaluator)
    return evaluator, memory


def test_proposes_from_repeated_never_successful_failures(ev, tmp_path, monkeypatch):
    evaluator, memory = ev
    monkeypatch.setenv("FAILSTOP_PROPOSE_AFTER", "3")
    importlib.reload(evaluator)
    for _ in range(3):
        memory.record("Bash", memory.normalize_shape("python3 bad.py"), ok=False, fix="use -X")
    evaluator.propose()
    props = [json.loads(l) for l in (tmp_path / "proposals.jsonl").read_text().splitlines()]
    assert len(props) == 1
    assert props[0]["tier"] == "proposed"
    assert "human_approval" in props[0]["gates_required"]


def test_a_shape_that_succeeded_is_not_proposed(ev, tmp_path):
    evaluator, memory = ev
    memory.record("Bash", memory.normalize_shape("npm test"), ok=True)
    for _ in range(5):
        memory.record("Bash", memory.normalize_shape("npm test"), ok=False)
    evaluator.propose()
    props = (tmp_path / "proposals.jsonl").read_text().strip()
    assert props == "", "a shape that ever worked is not a candidate rule"


def test_proposal_is_never_tier_enforced(ev, tmp_path):
    evaluator, memory = ev
    for _ in range(4):
        memory.record("Bash", memory.normalize_shape("foo"), ok=False)
    evaluator.propose()
    for line in (tmp_path / "proposals.jsonl").read_text().splitlines():
        assert json.loads(line)["tier"] == "proposed"


def test_evaluator_never_writes_canon():
    """Structural: no code path in evaluator.py writes to CANON.md."""
    src = (ROOT / "scripts" / "evaluator.py").read_text(encoding="utf-8")
    # the only mention of CANON is the read-only path constant and this guarantee
    assert "CANON.write" not in src
    assert "CANON.md\", \"w" not in src
    assert 'open(CANON' not in src
    import evaluator
    assert evaluator.can_write_canon() is False


def test_report_warns_on_zero_successes(ev, capsys):
    evaluator, memory = ev
    memory.record("Bash", "x", ok=False)
    evaluator.report()
    assert "blocklist" in capsys.readouterr().out

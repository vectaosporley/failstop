#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The agent's verdict — the only channel that can see what the hooks structurally cannot.

A PostToolUse hook reads `tool_response` and asks "did it error?". That is answerable without
knowing anything about the purpose of the call, which is precisely why it misses both
directions at once:

    exit 1, nothing wrong    grep found no match; npm test reported failing tests
    exit 0, everything wrong a filter silently ignored; a parameter quietly dropped;
                             a shell failure returned as a STRING containing "Exit code: 1"

No cleverer hook fixes this. Failing requires a purpose, and the purpose belongs to the
caller. So `judge` demands the frame, and these tests hold it to that.
"""
from __future__ import annotations

import importlib
import json
import subprocess
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


# ── it records what the automatic channel cannot ─────────────────────────────

def test_a_success_on_paper_can_be_recorded_as_a_failure(mem):
    """The case that has no other channel: exit 0, wrong answer.

    Every automatic recorder on earth files this as a success. It is a failure only from
    inside the frame of what was wanted, and only the caller holds that frame.
    """
    mem.judge("Bash", "proc_list --filter python", expected="only python processes",
              got="all 237 processes", fix="filter with findstr instead")
    v = mem.check("Bash", mem.normalize_shape("proc_list --filter python"))
    assert v["fail"] == 1
    assert v["last_fix"] == "filter with findstr instead"


def test_the_frame_is_carried_into_the_record(mem):
    """A verdict without its frame is an opinion. The stored error has to say what was wanted,
    or a later reader cannot tell whether the judgment still applies."""
    mem.judge("Bash", "curl <path>", expected="the JSON body", got="an empty 200")
    db = mem.load()
    entry = [e for e in db["log"] if not e["ok"]][-1]
    assert "wanted: the JSON body" in entry["err"]
    assert "got: an empty 200" in entry["err"]


def test_two_identical_verdicts_block_the_shape(mem):
    """The whole point: the agent's judgment has to reach the gate, or it is a diary.

    Nothing in the tool_response distinguishes these calls from successes — so without this
    channel the gate would never see a single failure here, no matter how many times it happened.
    """
    for _ in range(2):
        mem.judge("Bash", "proc_list --filter python", expected="only python processes",
                  got="all 237 processes", fix="use findstr")
    v = mem.check("Bash", mem.normalize_shape("proc_list --filter python"))
    assert v["verdict"] == "blocked"
    assert "wanted" in v["repeated"]


def test_verdicts_with_different_frames_are_different_attempts(mem):
    """Asking a command for two different things is two questions, not one retry."""
    mem.judge("Bash", "pytest x.py", expected="all tests pass", got="3 failed")
    mem.judge("Bash", "pytest x.py", expected="the list of test names", got="3 failed")
    v = mem.check("Bash", mem.normalize_shape("pytest x.py"))
    assert v["verdict"] != "blocked", "different frames, different questions — not a loop"


# ── it can also lift a block ─────────────────────────────────────────────────

def test_reporting_that_it_works_lifts_the_block(mem):
    """A store that only ever hears about failures is a blocklist, and a blocklist can only
    ever get more restrictive. The unlock has to travel the same channel as the complaint."""
    for _ in range(2):
        mem.judge("Bash", "pip install <str>", expected="installed", got="externally-managed")
    assert mem.check("Bash", mem.normalize_shape("pip install <str>"))["verdict"] == "blocked"
    mem.judge("Bash", "pip install <str>", expected="installed", worked=True)
    assert mem.check("Bash", mem.normalize_shape("pip install <str>"))["verdict"] == "trusted"


def test_the_success_is_recorded_as_a_success_not_as_a_clear(mem):
    """`worked` is evidence, `clear` is an override. Blurring them would let an agent wave
    away its own blocks by asserting they are fine — which is the one thing the human keeps."""
    mem.judge("Bash", "cmd <path>", expected="output", worked=True)
    v = mem.check("Bash", mem.normalize_shape("cmd <path>"))
    assert v["ok"] == 1, "it must count as real evidence, not as an exemption"
    assert not mem.load().get("cleared"), "judge must never write a clear"


# ── it is on the record ──────────────────────────────────────────────────────

def test_every_verdict_reaches_the_ledger(mem, tmp_path):
    import ledger
    importlib.reload(ledger)
    mem.judge("Bash", "x --y", expected="a result", got="nothing")
    entries = [json.loads(l) for l in ledger.LEDGER.read_text(encoding="utf-8").splitlines() if l.strip()]
    assert entries and "agent reported a failure" in entries[-1]["action"]
    assert ledger.verify()["ok"]


# ── the CLI, which is what an agent actually types ───────────────────────────

def _cli(*args, home):
    import os
    return subprocess.run([sys.executable, str(ROOT / "scripts" / "memory.py"), *args],
                          capture_output=True, text=True, timeout=30,
                          env={**os.environ, "FAILSTOP_HOME": str(home)})


def test_the_cli_records_a_verdict(tmp_path):
    p = _cli("judge", "--command", "foo --bar", "--expected", "a list of files",
             "--got", "nothing", "--fix", "use ls", home=tmp_path)
    assert p.returncode == 0, p.stderr
    assert json.loads(p.stdout)["recorded"] == "failure"


def test_the_cli_refuses_a_verdict_with_no_frame(tmp_path):
    """--expected is required. A verdict with no frame is an event, and the hooks already
    have every event. Making it optional would quietly turn this back into a second, worse
    copy of the automatic channel."""
    p = _cli("judge", "--command", "foo --bar", home=tmp_path)
    assert p.returncode != 0
    assert "expected" in (p.stderr + p.stdout).lower()


def test_the_cli_can_report_a_recovery(tmp_path):
    p = _cli("judge", "--command", "foo --bar", "--expected", "x", "--worked", home=tmp_path)
    assert p.returncode == 0
    assert json.loads(p.stdout)["recorded"] == "success"


# ── the skill that teaches it exists ─────────────────────────────────────────

def test_the_skill_exists_and_names_the_command():
    """The MCP twin of this channel only works because its instructions teach it. A channel
    nobody is told about is a channel nobody uses — which was this one's exact condition."""
    skill = ROOT / "skills" / "say-what-the-tool-cannot" / "SKILL.md"
    assert skill.is_file()
    text = skill.read_text(encoding="utf-8")
    assert "memory.py judge" in text
    assert "--expected" in text
    assert "--worked" in text, "the unlock has to be taught too, or the store becomes a blocklist"

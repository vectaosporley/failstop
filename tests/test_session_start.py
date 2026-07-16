#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The SessionStart hook: the only moment the memory gets to speak before a mistake.

Run as a real subprocess with a real event on stdin, because that is the only channel that
proves anything. Importing the module and calling main() would test the code; it would not
test the hook. The distinction cost this project a whole broken plugin once, when hooks.json
invoked `python3` — which does not exist on Windows — and every test still passed because the
tests never spawned the interpreter the way Claude Code does.

Half of these assert what the hook must NOT print. That is deliberate: a startup hook that
speaks when it has nothing to say becomes a banner, a banner becomes wallpaper, and wallpaper
is not read. Its silence is a feature with the same standing as its output.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
HOOK = ROOT / "hooks" / "session_start.py"


def run(source: str, home: Path) -> tuple[int, str, str]:
    """Fire the hook exactly as Claude Code does: subprocess, event JSON on stdin."""
    event = {"session_id": "test", "cwd": str(ROOT),
             "hook_event_name": "SessionStart", "source": source}
    p = subprocess.run(
        [sys.executable, str(HOOK)],
        input=json.dumps(event), capture_output=True, text=True, timeout=30,
        env={**os.environ, "FAILSTOP_HOME": str(home)},   # a minimal env breaks Windows python
    )
    return p.returncode, p.stdout, p.stderr


@pytest.fixture()
def home(tmp_path, monkeypatch):
    """A properly set-up install: the canon has been accepted by a human.

    The lock matters here. Without it the hook says 'nobody ever accepted this canon', which
    is correct and not noise — an unlocked canon cannot drift-detect, so its silence would be
    the absence of proof rather than proof of integrity. The first draft of these tests called
    that state 'nothing to say' and was simply wrong about it.
    """
    monkeypatch.setenv("FAILSTOP_HOME", str(tmp_path))
    sys.path.insert(0, str(ROOT / "scripts"))
    import importlib
    import canon
    importlib.reload(canon)
    canon.lock()
    return tmp_path


def test_an_unaccepted_canon_is_reported(tmp_path, monkeypatch):
    """No lock = no human ever signed off = drift is undetectable. Say so."""
    code, out, _ = run("startup", tmp_path)          # no canon.lock() here
    assert code == 0
    assert "CANON" in out and "NO-LOCK" in out


def _mem(home):
    sys.path.insert(0, str(ROOT / "scripts"))
    import importlib
    import memory
    importlib.reload(memory)
    return memory


# ── it never costs a session ─────────────────────────────────────────────────

def test_exits_zero_on_a_clean_store(home):
    code, out, err = run("startup", home)
    assert code == 0


def test_says_nothing_when_there_is_nothing_to_say(home):
    """The hardest discipline in the file. Nothing learned yet: print nothing."""
    code, out, _ = run("startup", home)
    assert out.strip() == "", f"a startup banner with no content is how the hook stops being read: {out!r}"


def test_survives_a_corrupt_store(home):
    (home / "memory.json").write_text("{ not json at all", encoding="utf-8")
    code, out, err = run("startup", home)
    assert code == 0, "a damaged store must never cost the user their session"


def test_survives_empty_stdin(home):
    p = subprocess.run([sys.executable, str(HOOK)], input="", capture_output=True, text=True,
                       env={**os.environ, "FAILSTOP_HOME": str(home)})
    assert p.returncode == 0


# ── it reports what would otherwise cost a turn ──────────────────────────────

def test_a_blocked_shape_is_announced_with_its_fix(home):
    """Without this the agent meets the block by walking into it, one wasted turn later —
    for something already known before the first prompt was typed."""
    mem = _mem(home)
    for _ in range(2):
        mem.record("Bash", "pip install <str>", ok=False,
                   fix="use --break-system-packages", error="externally-managed-environment")
    code, out, _ = run("startup", home)
    assert code == 0
    assert "BLOCKED" in out
    assert "pip install" in out
    assert "--break-system-packages" in out, "announcing the block without the fix is half a message"
    assert "clear --tool" in out, "a block must always name its way out"


def test_a_shape_that_is_merely_failing_is_not_announced_as_blocked(home):
    """It failed once and is not looping. Not urgent, not startup's business."""
    mem = _mem(home)
    mem.record("Bash", "npm test", ok=False, error="1 failed", fix="fix the test")
    code, out, _ = run("startup", home)
    assert "BLOCKED" not in out


def test_a_recovered_shape_is_not_announced(home):
    mem = _mem(home)
    for _ in range(2):
        mem.record("Bash", "cmd <path>", ok=False, error="boom", fix="do it differently")
    mem.record("Bash", "cmd <path>", ok=True)
    code, out, _ = run("startup", home)
    assert "BLOCKED" not in out, "it works now — bringing it up would be noise"


# ── compaction is the case that matters ──────────────────────────────────────

def test_after_compaction_the_known_fixes_come_back(home):
    """A compaction is the agent losing the middle of its own session. It is about to repeat
    what it already learned, without knowing it ever tried."""
    mem = _mem(home)
    mem.record("Bash", "curl <path>", ok=False, fix="the proxy blocks it, use the fetch tool",
               error="connection refused")
    mem.record("Bash", "curl <path>", ok=True)          # recovered: not blocked, but worth knowing
    code, out, _ = run("compact", home)
    assert "known fixes" in out
    assert "the proxy blocks it" in out


def test_a_fresh_startup_does_not_replay_old_fixes(home):
    """Nothing was lost on a new session, and repeating this every single time is exactly how
    it stops being read on the day it matters."""
    mem = _mem(home)
    mem.record("Bash", "curl <path>", ok=False, fix="use the fetch tool", error="refused")
    mem.record("Bash", "curl <path>", ok=True)
    code, out, _ = run("startup", home)
    assert "known fixes" not in out


# ── integrity: it cannot block, so it must at least testify ──────────────────

def test_a_broken_ledger_is_reported_at_startup(home):
    """It cannot stop the session — SessionStart has no such power. What it can do is make
    sure nobody can later say they were not told."""
    sys.path.insert(0, str(ROOT / "scripts"))
    import importlib
    import ledger
    importlib.reload(ledger)
    ledger.append("agent", "one")
    ledger.append("agent", "two")
    entries = [json.loads(l) for l in ledger.LEDGER.read_text(encoding="utf-8").splitlines() if l.strip()]
    entries[0]["detail"] = "rewritten history"
    ledger.LEDGER.write_text("\n".join(json.dumps(e) for e in entries) + "\n", encoding="utf-8")

    code, out, _ = run("startup", home)
    assert code == 0, "it reports; it never blocks"
    assert "LEDGER" in out and "ALTERED" in out


def test_an_intact_ledger_is_not_mentioned(home):
    sys.path.insert(0, str(ROOT / "scripts"))
    import importlib
    import ledger
    importlib.reload(ledger)
    ledger.append("agent", "one")
    code, out, _ = run("startup", home)
    assert "LEDGER" not in out, "reporting that everything is fine is the definition of noise"


# ── the wiring itself ────────────────────────────────────────────────────────

def test_hooks_json_registers_the_hook_and_uses_a_real_interpreter():
    """`python3` does not exist on Windows. That single word silently disabled this plugin
    once, and no unit test noticed, because no unit test ran the command string."""
    cfg = json.loads((ROOT / "hooks" / "hooks.json").read_text(encoding="utf-8"))
    groups = cfg["hooks"]["SessionStart"]
    cmds = [h["command"] for g in groups for h in g["hooks"]]
    assert any("session_start.py" in c for c in cmds)
    for c in cmds:
        assert "python3" not in c, "python3 is not present on Windows — the hook would never run"


def test_the_matcher_covers_compaction():
    """The event this hook exists for. Omitting it would leave the one case where the memory
    is genuinely needed uncovered, while everything else kept working."""
    cfg = json.loads((ROOT / "hooks" / "hooks.json").read_text(encoding="utf-8"))
    matchers = " ".join(g["matcher"] for g in cfg["hooks"]["SessionStart"])
    for m in ("startup", "resume", "compact"):
        assert m in matchers

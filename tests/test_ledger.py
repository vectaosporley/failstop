#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The contract. A tamper-evident record is only worth what its detection is worth.

So these tests do not check that appending works — that is the easy half. They attack it:
edit an entry, reorder the chain, drop one, replace the whole file, race two writers. A guard
tested only on the case where it obviously passes is the guard that was inert all along.

Two things get equal weight here:
  * that it CATCHES a real edit, and
  * that it does NOT call a race or a truncated line "tampering".
The second matters as much as the first. A ledger that cries wolf loses the credibility it
needs on the one day it is right.
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
def led(tmp_path, monkeypatch):
    monkeypatch.setenv("FAILSTOP_HOME", str(tmp_path))
    monkeypatch.delenv("FAILSTOP_LEDGER", raising=False)
    monkeypatch.delenv("FAILSTOP_LEDGER_ANCHOR", raising=False)
    import ledger
    importlib.reload(ledger)
    return ledger


def _lines(led):
    return [json.loads(l) for l in led.LEDGER.read_text(encoding="utf-8").splitlines() if l.strip()]


def _rewrite(led, entries):
    led.LEDGER.write_text("\n".join(json.dumps(e, ensure_ascii=False) for e in entries) + "\n",
                          encoding="utf-8")


# ── it records ───────────────────────────────────────────────────────────────

def test_an_empty_ledger_is_intact_not_broken(led):
    v = led.verify()
    assert v["ok"] and v["verdict"] == "INTACT" and v["entries"] == 0


def test_entries_chain_to_their_predecessor(led):
    a = led.append("agent", "blocked", "the gate refused a shape")
    b = led.append("human", "override", "released it by hand")
    assert a["prev_hash"] == led.GENESIS
    assert b["prev_hash"] == a["hash"]
    assert led.verify()["ok"]


def test_both_parties_write_to_the_same_record(led):
    """The point of the contract: neither side keeps its own private version."""
    led.append("agent", "reported a fix")
    led.append("human", "changed a rule")
    actors = [e["actor"] for e in _lines(led)]
    assert actors == ["agent", "human"]


def test_an_unknown_actor_is_labelled_not_dropped(led):
    e = led.append("post_write_check", "found a parse error")
    assert e["actor"] == "tool:post_write_check", "an entry with no author proves nothing"


# ── it catches a real edit ───────────────────────────────────────────────────

def test_editing_an_entry_is_caught(led):
    """The headline claim. Someone rewrites the past to look better."""
    led.append("agent", "blocked", "npm install failed")
    led.append("human", "override", "allowed it anyway")
    led.append("agent", "done", "shipped")
    entries = _lines(led)
    entries[1]["detail"] = "did not override anything, honest"   # the lie
    _rewrite(led, entries)
    v = led.verify()
    assert not v["ok"]
    assert v["verdict"] == "ALTERED"
    assert v["broken_at"] == 1


def test_deleting_an_entry_is_caught(led):
    """Removing an inconvenient line leaves a hole the chain notices."""
    for i in range(4):
        led.append("agent", f"step {i}")
    entries = _lines(led)
    del entries[2]
    _rewrite(led, entries)
    v = led.verify()
    assert not v["ok"] and v["verdict"] == "ALTERED"


def test_reordering_is_caught(led):
    for i in range(3):
        led.append("agent", f"step {i}")
    entries = _lines(led)
    entries[0], entries[1] = entries[1], entries[0]
    _rewrite(led, entries)
    assert not led.verify()["ok"]


def test_a_forged_hash_does_not_save_an_edit(led):
    """The obvious attack: edit the content AND recompute that one hash. The next entry's
    prev_hash still points at the old value, so the chain breaks one step later."""
    led.append("agent", "a")
    led.append("agent", "b")
    led.append("agent", "c")
    entries = _lines(led)
    entries[1]["detail"] = "rewritten"
    entries[1]["hash"] = led._hash_entry(entries[1])      # forge it properly
    _rewrite(led, entries)
    v = led.verify()
    assert not v["ok"], "an edit with a recomputed hash must still break the chain downstream"
    assert v["broken_at"] == 2


# ── it does NOT cry wolf ─────────────────────────────────────────────────────

def test_two_writers_racing_is_called_a_fork_not_tampering(led):
    """Two hooks firing at once both read the same head and both append. That is a race.

    Calling it 'the history was edited' would be an accusation of forgery against a schedule.
    The record is complete; only its order is ambiguous. Saying so precisely is what keeps the
    word 'tampered' meaning something.
    """
    led.append("agent", "first")
    entries = _lines(led)
    twin = dict(entries[0])
    twin["seq"] = 1
    twin["action"] = "concurrent"
    twin["hash"] = led._hash_entry(twin)       # same prev_hash: both saw the same head
    _rewrite(led, entries + [twin])
    v = led.verify()
    assert not v["ok"]
    assert v["verdict"] == "FORKED", f"a race must not be reported as an edit (got {v['verdict']})"
    assert "race" in v["reason"].lower()


def test_an_unreadable_line_is_reported_as_unknown_not_as_an_attack(led):
    """A truncated write is a disk event, not an adversary. FS-003: corroborate before
    indicting. The verdict says CORRUPT and says the cause is unknown."""
    led.append("agent", "a")
    with led.LEDGER.open("a", encoding="utf-8") as fh:
        fh.write('{"seq": 1, "ts": "2026-07-15T10:00:00", "act\n')     # cut mid-write
    v = led.verify()
    assert v["verdict"] == "CORRUPT"
    assert "unknown" in v["reason"].lower()


def test_a_corrupt_line_is_not_silently_dropped(led):
    """Hiding an unreadable line would be the ledger quietly editing itself."""
    led.append("agent", "a")
    with led.LEDGER.open("a", encoding="utf-8") as fh:
        fh.write("this is not json\n")
    assert any("_corrupt" in e for e in led._read_all())


def test_a_missing_ledger_does_not_raise(led):
    assert led.head() == led.GENESIS
    assert led.verify()["ok"]


# ── the anchor: the one thing hashes cannot do ───────────────────────────────

def test_a_full_rewrite_verifies_perfectly(led):
    """The honest limit, asserted so nobody oversells this file.

    Whoever can write the ledger can rebuild it from scratch: every hash recomputed, chain
    immaculate. verify() will say INTACT and be telling the truth about a fabrication. This is
    why 'tamper-evident' is not 'tamper-proof', and why the anchor exists.
    """
    led.append("agent", "the inconvenient truth")
    led.LEDGER.unlink()
    led.append("agent", "a more flattering history")
    assert led.verify()["ok"], "a rebuilt chain is internally consistent — hashes cannot see this"


def test_the_anchor_catches_the_rewrite_that_verify_cannot(led):
    led.append("agent", "the inconvenient truth")
    led.anchor()                                   # the other party remembers this head
    led.LEDGER.unlink()
    led.append("agent", "a more flattering history")
    assert led.verify()["ok"]                      # still internally perfect
    c = led.check_anchor()
    assert not c["ok"], "the anchored head vanished — that is the rewrite, and it must show"
    assert "replaced" in c["reason"].lower()


def test_appending_normally_keeps_the_anchor_valid(led):
    """The anchor must not fire on honest growth, or it becomes noise and gets ignored."""
    led.append("agent", "one")
    led.anchor()
    for i in range(5):
        led.append("agent", f"more {i}")
    assert led.check_anchor()["ok"]


def test_no_anchor_is_reported_as_a_gap_not_as_success(led):
    """Absence of an anchor is not proof of integrity — it is the absence of proof, and the
    difference is exactly what this project is about."""
    led.append("agent", "x")
    c = led.check_anchor()
    assert c["ok"]
    assert "undetectable" in c["reason"], "must say what is NOT being checked"


# ── durability ───────────────────────────────────────────────────────────────

def test_the_same_content_always_hashes_the_same(led):
    """If one entry could serialise two ways, the chain would break for no reason."""
    e = {"seq": 0, "ts": "2026-07-15T10:00:00", "actor": "agent", "action": "x",
         "detail": "ñ á 漢", "prev_hash": led.GENESIS}
    assert led._hash_entry(e) == led._hash_entry(dict(reversed(list(e.items()))))


def test_concurrent_appends_do_not_fork(led):
    """The lock earns its keep: 12 threads appending at once must still produce one chain."""
    import threading
    errs = []

    def go(i):
        try:
            led.append("agent", f"thread {i}")
        except Exception as exc:  # noqa: BLE001
            errs.append(exc)

    ts = [threading.Thread(target=go, args=(i,)) for i in range(12)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert not errs
    v = led.verify()
    assert v["ok"], f"concurrent appends forked the chain: {v.get('reason')}"
    assert v["entries"] == 12


def test_the_lock_file_is_released(led):
    led.append("agent", "x")
    assert not led.LEDGER.with_suffix(".lock").exists(), "a leaked lock wedges every later write"


# ── the wiring: a ledger nobody writes to is furniture ───────────────────────

def test_clearing_a_blocked_shape_is_recorded(led, tmp_path, monkeypatch):
    """The override is the entry that matters most.

    Everything else here is history. A clear is the one operation that switches a guard off,
    and a back door that leaves no trace is not an escape hatch — it is a back door. This is
    not about suspecting anyone: it is so that whoever looks later, including the person who
    did it, can see that it happened.
    """
    monkeypatch.setenv("FAILSTOP_BLOCK_AFTER", "3")
    import memory
    importlib.reload(memory)
    for _ in range(2):
        memory.record("Bash", "cmd <path>", ok=False, error="boom")
    assert memory.check("Bash", "cmd <path>")["verdict"] == "blocked"

    memory.clear_shape("Bash", "cmd <path>")

    entries = [e for e in _lines(led)]
    assert entries, "the clear left no trace at all"
    assert "cleared" in entries[-1]["action"]
    assert "cmd <path>" in entries[-1]["detail"]
    assert led.verify()["ok"]


def test_a_broken_ledger_does_not_block_the_clear(led, tmp_path, monkeypatch, capsys):
    """FS-012, applied to the witness: testimony yields to work.

    If the ledger cannot be written, the clear still happens — losing a line of testimony
    costs less than a session that dies taking notes. But it says so on stderr: a witness that
    fails silently is the exact thing this project exists to prevent.
    """
    monkeypatch.setenv("FAILSTOP_LEDGER", str(tmp_path / "nope" / "x" / "ledger.jsonl"))
    import ledger as _l
    importlib.reload(_l)
    monkeypatch.setattr(_l, "append", lambda *a, **k: (_ for _ in ()).throw(OSError("disk gone")))
    import memory
    importlib.reload(memory)
    memory.record("Bash", "s", ok=False, error="e")
    memory.clear_shape("Bash", "s")                      # must not raise
    assert memory.check("Bash", "s")["verdict"] != "blocked", "the clear must still have worked"
    assert "unrecorded" in capsys.readouterr().err, "a silent witness is worse than none"

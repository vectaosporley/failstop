#!/usr/bin/env python3
"""Phase 6: snapshot before mutation, restore on demand, bounded by count and size."""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))


@pytest.fixture()
def rb(tmp_path, monkeypatch):
    monkeypatch.setenv("FAILSTOP_HOME", str(tmp_path))
    import rollback
    importlib.reload(rollback)
    return rollback


def test_snapshot_then_undo_restores_bytes(rb, tmp_path):
    f = tmp_path / "doc.txt"
    f.write_text("original\n", encoding="utf-8")
    rb.snapshot(f)
    f.write_text("mutated, wrong\n", encoding="utf-8")
    assert rb.undo() == 0
    assert f.read_text(encoding="utf-8") == "original\n"


def test_undo_specific_id(rb, tmp_path):
    f = tmp_path / "d.txt"
    f.write_text("v1\n", encoding="utf-8")
    row1 = rb.snapshot(f)
    f.write_text("v2\n", encoding="utf-8")
    rb.snapshot(f)
    f.write_text("v3\n", encoding="utf-8")
    assert rb.undo(row1["id"]) == 0
    assert f.read_text(encoding="utf-8") == "v1\n"


def test_new_file_is_not_snapshotted(rb, tmp_path):
    # nothing to undo for a file that does not exist yet
    assert rb.snapshot(tmp_path / "nope.txt") is None


def test_oversize_file_is_skipped(rb, tmp_path, monkeypatch):
    monkeypatch.setenv("FAILSTOP_UNDO_FILE_MB", "0")
    importlib.reload(rb)
    f = tmp_path / "big.txt"
    f.write_text("x" * 5000, encoding="utf-8")
    assert rb.snapshot(f) is None


def test_count_cap_evicts_oldest(rb, tmp_path, monkeypatch):
    monkeypatch.setenv("FAILSTOP_UNDO_MAX", "3")
    importlib.reload(rb)
    f = tmp_path / "c.txt"
    for i in range(6):
        f.write_text(f"v{i}\n", encoding="utf-8")
        rb.snapshot(f)
    rows = rb._read_index()
    assert len(rows) <= 3, "old snapshots must be garbage-collected"


def test_undo_detects_tampered_blob(rb, tmp_path):
    f = tmp_path / "t.txt"
    f.write_text("safe\n", encoding="utf-8")
    row = rb.snapshot(f)
    # corrupt the stored blob
    (rb.UNDO / row["blob"]).write_bytes(b"tampered")
    assert rb.undo() == 1, "a blob whose hash no longer matches must not be restored"


def test_undo_with_nothing_returns_error(rb):
    assert rb.undo() == 1


def test_snapshot_never_raises_on_bad_path(rb):
    # a directory, not a file
    assert rb.snapshot(rb.HOME) is None


def test_rapid_snapshots_get_distinct_ids(rb, tmp_path):
    """Windows datetime.now() has coarse resolution: two snapshots in the same microsecond
    must still get distinct IDs, or the second overwrites the first's blob."""
    f = tmp_path / "r.txt"
    ids = []
    for i in range(10):
        f.write_text(f"v{i}\n", encoding="utf-8")
        row = rb.snapshot(f)
        ids.append(row["id"])
    assert len(set(ids)) == 10, "every snapshot id must be unique"

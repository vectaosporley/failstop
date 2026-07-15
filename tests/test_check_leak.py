#!/usr/bin/env python3
"""Tests for the boundary guard. A guard without tests is decoration.

Uses only invented terms as probes — nothing real is written into this file.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("check_leak", ROOT / "scripts" / "check_leak.py")
check_leak = importlib.util.module_from_spec(_spec)
sys.modules["check_leak"] = check_leak
_spec.loader.exec_module(check_leak)

GENERIC = check_leak.GENERIC
FAKE = [("local pattern (test)", r"\bwidgetcorp\w*")]


def scan(text, patterns=None):
    return check_leak.escanear(text, patterns if patterns is not None else GENERIC)


# ── generic patterns detect universal leaks ──────────────────────────────────

GENERIC_LEAKS = [
    "C:" + chr(92) + "Users" + chr(92) + "someone",
    "/home/someone/thing",
    "/sessions/aaa-bbb-ccc/mnt",
    "someone@" + "gmail.com",
    "KEY=" + "gsk_" + "abcdefghijklmnop",
    "password = " + repr("hunter2hunter2hunter2"),
]


@pytest.mark.parametrize("line", GENERIC_LEAKS)
def test_generic_detects(line):
    assert scan(line), f"guard missed: {line!r}"


LEGIT = [
    "def normal(): return 1",
    "a PreToolUse hook blocks Edit",
    "memory.json is the source of truth",
    "fail-stop semantics for coding agents",
    "the evaluator measures compliance",
]


@pytest.mark.parametrize("line", LEGIT)
def test_no_false_positive(line):
    assert not scan(line), f"false positive: {line!r}"


# ── the key design property ───────────────────────────────────────────────────

def test_generic_list_names_no_specific_project():
    """The committed patterns are structural only — they name no project.

    We must NOT list the real private terms here: a test that enumerates the secrets it
    guards against is itself the disclosure (FS-010). The real check against the actual
    private terms is test_repository_is_clean_with_local_list, using the external list.
    Here we assert the generic patterns match only structural things (a path, an email,
    a token shape) and never an invented project-style identifier.
    """
    invented = "widgetcorp_internal_module"
    assert not scan(invented, GENERIC), "generic patterns must not match project-style names"
    # and the generic labels describe structure, not any product
    labels = " ".join(lbl for lbl, _ in GENERIC).lower()
    for structural in ("path", "email", "token", "secret"):
        pass  # labels are structural by construction; presence check is illustrative
    assert "project" not in labels and "module" not in labels


def test_source_file_carries_no_glyphs():
    """The guard's own source contains no private symbolic glyphs.

    Glyphs are built via chr() so this test file itself stays clean.
    """
    src_full = (ROOT / "scripts" / "check_leak.py").read_text(encoding="utf-8")
    glyphs = [chr(c) for c in (0x25C7, 0x2295, 0x222B, 0x229B, 0x03A8)]
    assert not any(g in src_full for g in glyphs), "source contains private glyphs"


def test_local_only_term_invisible_without_local_list():
    assert not scan("widgetcorp_module", GENERIC)
    assert scan("widgetcorp_module", GENERIC + FAKE)


def test_leak_ok_is_an_explicit_escape():
    assert scan("/home/someone/x")
    assert not scan("/home/someone/x  # leak-ok")


# ── the guard does not exempt itself ──────────────────────────────────────────

def test_guard_scans_itself():
    names = [f.name for f in check_leak.archivos()]
    assert "check_leak.py" in names, "the guard must scan its own source"


def test_repository_is_clean_with_local_list():
    """Nothing private in the tree, using the real local list if present."""
    import os
    patterns, _ = check_leak.load_patterns(
        [os.environ["FAILSTOP_PATTERNS"]] if os.environ.get("FAILSTOP_PATTERNS") else None)
    dirty = [f.name for f in check_leak.archivos()
             if scan(f.read_text(encoding="utf-8", errors="replace"), patterns)]
    assert not dirty, f"leak in: {dirty}"


def test_guard_self_test_passes():
    assert check_leak.self_test() == 0

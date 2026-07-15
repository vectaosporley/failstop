#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""check_leak.py — boundary guard.

Fails if any file in the repository contains private material: machine paths,
ephemeral session paths, personal emails, credential-shaped tokens, or any term
from a *local* pattern list that lives outside this repository.

    python3 scripts/check_leak.py
    python3 scripts/check_leak.py --require-patterns   # refuse to pass without a local list
    python3 scripts/check_leak.py --redact             # print labels only, never the match
    python3 scripts/check_leak.py --self-test

Why the private terms are not in this file
------------------------------------------
A blocklist that names what it protects *is* the disclosure. The first version of this
script shipped a denylist containing the very identifiers, glyphs and project names it
existed to keep out of the repository. It reported the tree clean because it excluded
itself from the scan.

So: this file carries only generic patterns. Project-specific terms are loaded at runtime
from a file that is never committed. And this file no longer excludes itself.
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

RAIZ = Path(__file__).resolve().parent.parent
Pattern = Tuple[str, str]

# Generic. True for any project. Nothing here reveals anything.
GENERIC: List[Pattern] = [
    ("absolute machine path (windows)", r"[A-Za-z]:\\+Users\\+[A-Za-z0-9_.-]+"),
    ("absolute machine path (unix)", r"/(?:home|Users)/[A-Za-z0-9_.-]{2,}"),
    ("ephemeral session path", r"/sessions/[a-z]+-[a-z]+-[a-z]+"),
    ("personal email", r"[a-zA-Z0-9._%+-]+@(?:gmail|hotmail|outlook|yahoo|protonmail)\.[a-z]{2,}"),
    ("credential-shaped token", r"\b(?:gsk_|sk-|AIza|ghp_|xox[baprs]-)[A-Za-z0-9_\-]{8,}"),
    ("secret in assignment", r"(?i)\b(?:api[_-]?key|secret|token|password)\s*[:=]\s*['\"][^'\"\s]{12,}"),
]

DEFAULT_PATTERN_FILE = Path.home() / ".failstop" / "patterns.txt"
ENV_VAR = "FAILSTOP_PATTERNS"

SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "dist", "build",
             ".pytest_cache", "_e2e", ".claude"}  # last two: gitignored local test scaffolding
SKIP_FILES = {"test_check_leak.py"}   # holds probe strings on purpose; see its docstring
EXTENSIONS = {".md", ".py", ".js", ".ts", ".json", ".yml", ".yaml", ".toml", ".txt", ".sh", ".cfg", ""}

_ALLOW = re.compile(r"#\s*leak-ok\b")


# ── pattern loading ──────────────────────────────────────────────────────────

def _parse_pattern_file(path: Path) -> List[Pattern]:
    """One regex per line. Blank lines and lines starting with # are ignored."""
    out: List[Pattern] = []
    for n, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        try:
            re.compile(line)
        except re.error as exc:
            raise SystemExit(f"{path}:{n}: invalid regex — {exc}")
        out.append((f"local pattern ({path.name}:{n})", line))
    return out


def load_patterns(explicit: Optional[List[str]]) -> Tuple[List[Pattern], List[Path]]:
    """Generic patterns, plus local ones from --patterns / $FAILSTOP_PATTERNS / ~/.failstop."""
    sources: List[Path] = []
    if explicit:
        sources = [Path(p) for p in explicit]
    elif os.environ.get(ENV_VAR):
        sources = [Path(p) for p in os.environ[ENV_VAR].split(os.pathsep) if p]
    elif DEFAULT_PATTERN_FILE.is_file():
        sources = [DEFAULT_PATTERN_FILE]

    extra: List[Pattern] = []
    used: List[Path] = []
    for s in sources:
        if not s.is_file():
            raise SystemExit(f"pattern file not found: {s}")
        extra.extend(_parse_pattern_file(s))
        used.append(s)
    return GENERIC + extra, used


# ── scanning ─────────────────────────────────────────────────────────────────

def archivos() -> List[Path]:
    out = []
    for p in RAIZ.rglob("*"):
        if not p.is_file():
            continue
        if any(part in SKIP_DIRS for part in p.parts):
            continue
        if p.name in SKIP_FILES:
            continue
        if p.suffix.lower() not in EXTENSIONS:
            continue
        out.append(p)
    return sorted(out)


def escanear(texto: str, patterns: Optional[List[Pattern]] = None) -> List[Tuple[int, str, str]]:
    """Returns (line number, label, matched fragment) per finding."""
    pats = patterns if patterns is not None else GENERIC
    hits = []
    for n, linea in enumerate(texto.splitlines(), 1):
        if _ALLOW.search(linea):
            continue
        for label, patron in pats:
            m = re.search(patron, linea)
            if m:
                hits.append((n, label, m.group(0)[:40]))
    return hits


# ── self-test ────────────────────────────────────────────────────────────────

def self_test() -> int:
    """A guard that has never rejected anything has never been tested.

    Uses invented terms only — nothing real is written into this file.
    """
    fake_pattern: List[Pattern] = [("local pattern (test)", r"\bwidgetcorp\w*")]
    cases: Dict[str, bool] = {
        "C:" + chr(92) + "Users" + chr(92) + "someone": True,
        "/home/someone/project": True,  # leak-ok — invented path, test fixture
        "/sessions/aaa-bbb-ccc/mnt": True,  # leak-ok — invented path, test fixture
        "someone@" + "gmail.com": True,
        "KEY=" + "gsk_" + "abcdefghijklmnop": True,
        "password = " + repr("hunter2hunter2hunter2"): True,
        "widgetcorp_internal_module": True,           # only via the local list
        "def normal(): return 1": False,
        "a PreToolUse hook blocks Edit": False,
        "memory.json is the source of truth": False,
    }
    bad = 0
    for texto, should_hit in cases.items():
        hit = bool(escanear(texto, GENERIC + fake_pattern))
        ok = hit == should_hit
        bad += not ok
        print(f"  [{'ok ' if ok else 'BAD'}] {'detect' if should_hit else 'pass  '}  {texto[:44]!r}")

    # the local term must NOT be caught without the local list loaded
    if escanear("widgetcorp_internal_module", GENERIC):
        print("  [BAD] generic list matched a local-only term")
        bad += 1
    else:
        print("  [ok ] local-only term is invisible to the generic list")

    print(f"\n{'guard healthy' if not bad else f'{bad} case(s) wrong'}")
    return 1 if bad else 0


# ── cli ──────────────────────────────────────────────────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser(description="Boundary guard")
    ap.add_argument("--patterns", action="append", help="extra pattern file (repeatable)")
    ap.add_argument("--require-patterns", action="store_true",
                    help="fail if no local pattern file was loaded")
    ap.add_argument("--redact", action="store_true", help="print labels, never the matched text")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()

    if args.self_test:
        return self_test()

    patterns, used = load_patterns(args.patterns)

    if used:
        print(f"local pattern files: {', '.join(p.name for p in used)} "
              f"({len(patterns) - len(GENERIC)} extra patterns)")
    else:
        msg = (f"no local pattern file (looked at ${ENV_VAR} and {DEFAULT_PATTERN_FILE}). "
               "Only generic patterns are active.")
        if args.require_patterns:
            print(f"REFUSING: {msg}", file=sys.stderr)
            return 1
        print(f"note: {msg}")

    findings: Dict[Path, List] = {}
    for f in archivos():
        try:
            texto = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        h = escanear(texto, patterns)
        if h:
            findings[f] = h

    if not findings:
        print(f"clean — {len(archivos())} files, nothing private escapes.")
        return 0

    print(f"LEAK in {len(findings)} file(s):\n")
    for f, hits in findings.items():
        print(f"  {f.relative_to(RAIZ)}")
        for n, label, frag in hits:
            shown = "<redacted>" if args.redact else repr(frag)
            print(f"    line {n}: {label} -> {shown}")
    print("\nNothing ships while this is red.")
    print("For a genuine false positive, append  # leak-ok  to the line.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""canon.py — the canon's hash, and the set of files it protects.

    python3 scripts/canon.py show      # the hash, and the protected set
    python3 scripts/canon.py lock      # accept the current canon (a human runs this)
    python3 scripts/canon.py verify    # exit 1 if the canon drifted from the lock

The lock lives outside the repository, in ~/.failstop/canon.lock. It records what a human
accepted, on this machine, at a point in time.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from typing import List

ROOT = Path(__file__).resolve().parent.parent
CANON = ROOT / "CANON.md"
LOCK = Path(os.environ.get("FAILSTOP_HOME", Path.home() / ".failstop")) / "canon.lock"

# FS-001: protecting the law but not its enforcer is theater.
PROTECTED: List[str] = [
    "CANON.md",
    "scripts/canon.py",
    "scripts/check_leak.py",
    "hooks/hooks.json",
    "hooks/protect_canon.py",
    "hooks/post_write_check.py",
    "hooks/record_outcome.py",
]


def protected_paths() -> List[Path]:
    return [ROOT / rel for rel in PROTECTED]


def is_protected(path: Path) -> bool:
    """True if `path` is one of the protected files. Case-insensitive, symlink-resolved."""
    try:
        target = path.resolve()
    except OSError:
        return False
    norm = os.path.normcase(str(target))
    for p in protected_paths():
        try:
            if os.path.normcase(str(p.resolve())) == norm:
                return True
        except OSError:
            # The file may not exist yet (e.g. a hook not written). Compare literally.
            if os.path.normcase(str(p)) == norm:
                return True
    return False


def canon_hash() -> str:
    """SHA-256 of CANON.md with newlines normalised, so CRLF does not read as drift."""
    data = CANON.read_bytes().replace(b"\r\n", b"\n")
    return hashlib.sha256(data).hexdigest()


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def lock() -> int:
    h = canon_hash()
    _atomic_write(LOCK, json.dumps(
        {"sha256": h, "accepted_at": datetime.now().isoformat(timespec="seconds"),
         "canon": str(CANON)}, indent=2) + "\n")
    print(f"canon locked at {h[:16]}…")
    print(f"lock: {LOCK}")
    return 0


def verify() -> int:
    if not CANON.is_file():
        print("CANON.md is missing.", file=sys.stderr)
        return 1
    current = canon_hash()
    if not LOCK.is_file():
        print(f"no lock at {LOCK}. Current canon is {current[:16]}…")
        print("A human accepts it with:  python3 scripts/canon.py lock")
        return 1
    try:
        recorded = json.loads(LOCK.read_text(encoding="utf-8")).get("sha256", "")
    except (ValueError, OSError) as exc:
        print(f"lock unreadable ({exc}).", file=sys.stderr)
        return 1
    if recorded != current:
        print("CANON DRIFT", file=sys.stderr)
        print(f"  locked : {recorded[:16]}…", file=sys.stderr)
        print(f"  current: {current[:16]}…", file=sys.stderr)
        print("A human reviews the diff, then runs:  python3 scripts/canon.py lock", file=sys.stderr)
        return 1
    print(f"canon unchanged since it was accepted ({current[:16]}…)")
    return 0


def show() -> int:
    print(f"canon : {CANON}")
    print(f"sha256: {canon_hash()}")
    print(f"lock  : {LOCK}{'' if LOCK.is_file() else '  (absent)'}")
    print("\nprotected from agent writes (FS-001):")
    for p in protected_paths():
        mark = " " if p.is_file() else "?"
        print(f"  {mark} {p.relative_to(ROOT)}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="The canon's hash and protected set")
    ap.add_argument("command", choices=["show", "lock", "verify"])
    args = ap.parse_args()
    return {"show": show, "lock": lock, "verify": verify}[args.command]()


if __name__ == "__main__":
    raise SystemExit(main())

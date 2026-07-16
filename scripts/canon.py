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
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parent.parent
CANON = ROOT / "CANON.md"
LOCK = Path(os.environ.get("FAILSTOP_HOME", Path.home() / ".failstop")) / "canon.lock"

# FS-001: protecting the law but not its enforcer is theater.
#
# The test for this list is not "is it important?" but "could editing it disable a guard?".
# Four files failed that test while sitting outside the list, which is worth stating plainly
# because the omission was invisible: nothing here was unprotected by decision, it was
# unprotected by inattention, and the list LOOKED complete.
#
#   reputation_gate.py  decides whether a proven loop is refused. Editable => FS-007 off.
#   memory.py           is what the gate asks. Make check() always answer "trusted" and the
#                       gate keeps running, keeps passing its own tests, and blocks nothing.
#                       Disabling the question is quieter than disabling the guard.
#   ledger.py           is the witness. A record that can be edited by the party it records
#                       is not a record.
#   snapshot_before_write.py  is the undo. Removing it costs nothing today and everything on
#                       the day something needs reverting.
PROTECTED: List[str] = [
    "CANON.md",
    "scripts/canon.py",
    "scripts/check_leak.py",
    "scripts/memory.py",
    "scripts/ledger.py",
    "hooks/hooks.json",
    "hooks/protect_canon.py",
    "hooks/post_write_check.py",
    "hooks/record_outcome.py",
    "hooks/reputation_gate.py",
    "hooks/snapshot_before_write.py",
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


def check() -> Dict[str, Any]:
    """Has the canon drifted from what a human accepted? Returns a verdict. Prints NOTHING.

    This exists because verify() below both prints and returns an exit code — fine for a CLI,
    a trap for a library. Two callers found the trap the hard way:

      * A hook whose stdout IS its payload (SessionStart) had verify()'s chatter injected
        straight into the model's context as noise.
      * That same hook called verify() expecting a verdict object, got an int, raised
        AttributeError, and had it swallowed by a broad except — so the canon check silently
        never ran. The only reason anyone noticed was the leaked print.

    A function that reports through the caller's stdout and answers with an exit code cannot
    be used by anything except a shell. Deciding and announcing are different jobs.

    verdicts: ok | no-canon | no-lock | unreadable-lock | drift
    """
    if not CANON.is_file():
        return {"ok": False, "verdict": "no-canon", "reason": "CANON.md is missing"}
    current = canon_hash()
    if not LOCK.is_file():
        return {"ok": False, "verdict": "no-lock", "current": current,
                "reason": f"no lock at {LOCK} — nothing has been accepted by a human yet, "
                          f"so drift cannot be detected at all"}
    try:
        recorded = json.loads(LOCK.read_text(encoding="utf-8")).get("sha256", "")
    except (ValueError, OSError) as exc:
        return {"ok": False, "verdict": "unreadable-lock", "reason": f"lock unreadable ({exc})"}
    if recorded != current:
        return {"ok": False, "verdict": "drift", "locked": recorded, "current": current,
                "reason": f"the canon changed since it was accepted "
                          f"(locked {recorded[:16]}, current {current[:16]})"}
    return {"ok": True, "verdict": "ok", "current": current}


def verify() -> int:
    """CLI: say it out loud and answer with an exit code. All printing lives here."""
    v = check()
    if v["ok"]:
        print(f"canon unchanged since it was accepted ({v['current'][:16]}…)")
        return 0
    if v["verdict"] == "no-lock":
        print(f"no lock at {LOCK}. Current canon is {v['current'][:16]}…")
        print(f"A human accepts it with:  python {Path(__file__).name} lock")
        return 1
    if v["verdict"] == "drift":
        print("CANON DRIFT", file=sys.stderr)
        print(f"  locked : {v['locked'][:16]}…", file=sys.stderr)
        print(f"  current: {v['current'][:16]}…", file=sys.stderr)
        print(f"A human reviews the diff, then runs:  python {Path(__file__).name} lock",
              file=sys.stderr)
        return 1
    print(v["reason"], file=sys.stderr)
    return 1


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

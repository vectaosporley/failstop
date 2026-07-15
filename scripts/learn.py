#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""learn.py — the learning loop. A new failure can become a rule, but never a law by itself.

Three tiers, one direction:

    proposed   evidence exists, no reproduction.        Blocks nothing.
    shadow     reproduction passes, corroborated.       Logs what it WOULD block.
    enforced   in the canon.                            Blocks.

THE RATCHET (FS-002): automatic transitions may only TIGHTEN. Every loosening needs a human.
This module can promote proposed -> shadow automatically, once the gates pass. It can NEVER
promote shadow -> enforced (that writes the canon, a human act), and it can NEVER demote,
relax or delete. Those raise RatchetViolation.

    python3 scripts/learn.py draft   --from-proposals   # proposals -> candidate rules
    python3 scripts/learn.py gate     --id RULE          # run reproduction + corroboration
    python3 scripts/learn.py promote  --id RULE          # proposed -> shadow (auto-allowed)
    python3 scripts/learn.py promote  --id RULE --to enforced   # REFUSED: human-only
    python3 scripts/learn.py status
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

HOME = Path(os.environ.get("FAILSTOP_HOME", Path.home() / ".failstop"))
RULES = HOME / "rules.json"

TIERS = ["proposed", "shadow", "enforced"]


class RatchetViolation(RuntimeError):
    """Raised when an automatic transition would loosen enforcement. The point of the system."""


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _load() -> Dict[str, Any]:
    if not RULES.is_file():
        return {"rules": {}}
    try:
        d = json.loads(RULES.read_text(encoding="utf-8"))
        return d if isinstance(d, dict) and "rules" in d else {"rules": {}}
    except (ValueError, OSError):
        return {"rules": {}}


def _save(db: Dict[str, Any]) -> None:
    HOME.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(HOME), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(db, fh, ensure_ascii=False, indent=2)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, RULES)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def _tier_index(tier: str) -> int:
    return TIERS.index(tier)


def draft_from_proposals() -> int:
    proposals = HOME / "proposals.jsonl"
    if not proposals.is_file():
        print("no proposals to draft from")
        return 0
    db = _load()
    added = 0
    for line in proposals.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        p = json.loads(line)
        rid = f"{p['tool']}:{abs(hash(p['shape'])) % 10**8}"
        if rid in db["rules"]:
            continue
        db["rules"][rid] = {
            "id": rid, "tool": p["tool"], "shape": p["shape"],
            "tier": "proposed", "created": _now(),
            "reproduction": None, "corroborated": False,
            "suggested_fix": p.get("suggested_fix"),
            "history": [{"ts": _now(), "event": "drafted", "tier": "proposed"}],
        }
        added += 1
    _save(db)
    print(f"drafted {added} candidate rule(s) at tier `proposed`")
    return 0


def gate(rule_id: str, repro_script: Optional[str] = None,
         corroborated: Optional[bool] = None) -> int:
    """Record whether a rule passed its gates. In real use, repro_script is run; here the
    caller supplies the outcome so the gate logic is testable without a live edit."""
    db = _load()
    r = db["rules"].get(rule_id)
    if r is None:
        print(f"no rule {rule_id}", file=sys.stderr)
        return 1
    if repro_script is not None:
        r["reproduction"] = {"script": repro_script, "passed": _run_repro(repro_script),
                             "ts": _now()}
    if corroborated is not None:
        r["corroborated"] = bool(corroborated)
    r["history"].append({"ts": _now(), "event": "gated",
                         "reproduction": bool(r.get("reproduction") and r["reproduction"].get("passed")),
                         "corroborated": r["corroborated"]})
    _save(db)
    print(f"{rule_id}: reproduction={_repro_ok(r)} corroborated={r['corroborated']}")
    return 0


def _run_repro(script: str) -> bool:
    try:
        p = subprocess.run([sys.executable, script], capture_output=True, timeout=60)
        return p.returncode == 0
    except Exception:  # noqa: BLE001
        return False


def _repro_ok(r: Dict[str, Any]) -> bool:
    return bool(r.get("reproduction") and r["reproduction"].get("passed"))


def promote(rule_id: str, to: str = "shadow") -> int:
    """Automatic promotion. Enforces the ratchet.

    proposed -> shadow : allowed IF reproduction passed AND corroborated.
    anything -> enforced : REFUSED. Writing the canon is a human act.
    any downward move : REFUSED.
    """
    db = _load()
    r = db["rules"].get(rule_id)
    if r is None:
        print(f"no rule {rule_id}", file=sys.stderr)
        return 1

    cur, nxt = r["tier"], to
    if nxt not in TIERS:
        print(f"unknown tier {nxt}", file=sys.stderr)
        return 1

    # the ratchet
    if _tier_index(nxt) <= _tier_index(cur):
        raise RatchetViolation(
            f"refusing to move {rule_id} from {cur} to {nxt}: automatic transitions may only "
            f"tighten. Loosening is a human action.")

    if nxt == "enforced":
        raise RatchetViolation(
            f"refusing to promote {rule_id} to `enforced` automatically. That writes the canon, "
            f"which is a human act (FS-001). Use the manual canon workflow.")

    if nxt == "shadow":
        if not _repro_ok(r):
            print(f"blocked: {rule_id} has no passing reproduction (FS-009)", file=sys.stderr)
            return 1
        if not r["corroborated"]:
            print(f"blocked: {rule_id} is not corroborated by a second channel (FS-003)",
                  file=sys.stderr)
            return 1

    r["tier"] = nxt
    r["history"].append({"ts": _now(), "event": "promoted", "from": cur, "to": nxt})
    _save(db)
    print(f"{rule_id}: {cur} -> {nxt}")
    return 0


def status() -> int:
    db = _load()
    by_tier: Dict[str, List[str]] = {t: [] for t in TIERS}
    for r in db["rules"].values():
        by_tier[r["tier"]].append(r["id"])
    for t in TIERS:
        print(f"  {t:9} {len(by_tier[t])}: {', '.join(by_tier[t][:6])}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("draft"); d.add_argument("--from-proposals", action="store_true")
    g = sub.add_parser("gate")
    g.add_argument("--id", required=True); g.add_argument("--repro", default=None)
    g.add_argument("--corroborated", action="store_true")
    pr = sub.add_parser("promote")
    pr.add_argument("--id", required=True); pr.add_argument("--to", default="shadow")
    sub.add_parser("status")
    a = ap.parse_args()

    if a.cmd == "draft":
        return draft_from_proposals()
    if a.cmd == "gate":
        return gate(a.id, a.repro, a.corroborated or None)
    if a.cmd == "promote":
        try:
            return promote(a.id, a.to)
        except RatchetViolation as exc:
            print(f"RATCHET: {exc}", file=sys.stderr)
            return 2
    return status()


if __name__ == "__main__":
    raise SystemExit(main())

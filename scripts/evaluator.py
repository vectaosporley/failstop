#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""evaluator.py — measures compliance, proposes, and never legislates.

The asymmetry that is the whole safety argument: this file reads memory and the canon,
reports what it sees, and writes PROPOSALS. It does not edit the canon. It cannot — the
protect_canon hook denies writes to CANON.md, and there is no code path here that tries.

    python3 scripts/evaluator.py report      # reputation, top failures, hooks' effect
    python3 scripts/evaluator.py propose      # candidate rules from repeated failures

A proposal is never a rule. Promotion to the canon is a human action (Phase 8).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

HOME = Path(os.environ.get("FAILSTOP_HOME", Path.home() / ".failstop"))
PROPOSALS = HOME / "proposals.jsonl"
CANON = ROOT / "CANON.md"

PROPOSE_AFTER = int(os.environ.get("FAILSTOP_PROPOSE_AFTER", "3"))


def _memory() -> Any:
    import memory
    return memory


def report() -> int:
    mem = _memory()
    db = mem.load()
    tools = list(db["tools"].values())
    ok = sum(t["ok"] for t in tools)
    fail = sum(t["fail"] for t in tools)
    print("failstop compliance report")
    print(f"  outcomes: {ok} ok / {fail} fail across {len(tools)} command shapes")
    if ok == 0 and fail:
        print("  WARNING: zero successes recorded — reputation is a blocklist, not a reputation")
    worst = sorted((t for t in tools if t["fail"]), key=lambda t: -t["fail"])[:8]
    if worst:
        print("  most-failed shapes:")
        for t in worst:
            fixed = " (fix on file)" if t["last_fix"] else ""
            print(f"    [{t['fail']}x] {t['tool']}: {t['shape'][:46]}{fixed}")
    return 0


def propose() -> int:
    """Draft candidate rules from shapes that failed repeatedly and never succeeded.

    Writes to proposals.jsonl. Does NOT touch the canon. Each proposal is tier `proposed`
    and carries the gates it must pass (reproduction + corroboration + a human) before it
    could ever become a law.
    """
    mem = _memory()
    db = mem.load()
    candidates: List[Dict[str, Any]] = []
    for t in db["tools"].values():
        if t["fail"] >= PROPOSE_AFTER and t["ok"] == 0:
            candidates.append({
                "kind": "reputation_rule",
                "tool": t["tool"],
                "shape": t["shape"],
                "observed_failures": t["fail"],
                "suggested_fix": t["last_fix"] or None,
                "tier": "proposed",
                "gates_required": ["reproduction", "corroboration_second_channel", "human_approval"],
                "note": "A proposal is not a rule. It cannot be enforced until it passes the gates.",
            })

    HOME.mkdir(parents=True, exist_ok=True)
    with PROPOSALS.open("w", encoding="utf-8") as fh:
        for c in candidates:
            fh.write(json.dumps(c, ensure_ascii=False) + "\n")

    print(f"{len(candidates)} proposal(s) written to {PROPOSALS}")
    for c in candidates:
        print(f"  proposed: {c['tool']} / {c['shape'][:40]} — {c['observed_failures']} failures")
    if candidates:
        print("\nNone of these is a rule. A human reviews and promotes (Phase 8).")
    return 0


def can_write_canon() -> bool:
    """Structural guarantee: this module has no code path that writes CANON.md.

    Asserted by test_evaluator::test_evaluator_never_writes_canon, which greps this file.
    """
    return False


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("report")
    sub.add_parser("propose")
    a = ap.parse_args()
    return report() if a.cmd == "report" else propose()


if __name__ == "__main__":
    raise SystemExit(main())

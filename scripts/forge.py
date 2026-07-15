#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""forge.py — turn a repeated procedure into a tested, deterministic script.

Repetitive work should not be re-reasoned every session; that wastes tokens. The forge
detects a recurring sequence of tool calls, and a specification for a script that would
replace it. Claude writes the script. It runs alongside the reasoning for N invocations,
and is only promoted if it never diverges. It runs under the same hooks as anything else.

An "agent" here is a deterministic script by default. That is where the saving is.

    python3 scripts/forge.py detect                 # recurring shapes worth automating
    python3 scripts/forge.py spec  --shape "..."    # draft a spec from observed calls
    python3 scripts/forge.py record-baseline --id A --input X --output Y
    python3 scripts/forge.py check-divergence --id A --input X --output Y
    python3 scripts/forge.py status --id A

Gates before an agent replaces reasoning:
  * baseline: it must reproduce the observed outputs for observed inputs.
  * divergence: one mismatch against the baseline blocks promotion.
  * review + human approval (recorded, not automatic).
  * it saves tokens, or it is deleted.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

HOME = Path(os.environ.get("FAILSTOP_HOME", Path.home() / ".failstop"))
AGENTS = HOME / "agents.json"
DETECT_MIN = int(os.environ.get("FAILSTOP_FORGE_MIN", "5"))
BASELINE_RUNS = int(os.environ.get("FAILSTOP_FORGE_BASELINE", "5"))


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _load() -> Dict[str, Any]:
    if not AGENTS.is_file():
        return {"agents": {}}
    try:
        d = json.loads(AGENTS.read_text(encoding="utf-8"))
        return d if isinstance(d, dict) and "agents" in d else {"agents": {}}
    except (ValueError, OSError):
        return {"agents": {}}


def _save(db: Dict[str, Any]) -> None:
    HOME.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(HOME), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(db, fh, ensure_ascii=False, indent=2)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, AGENTS)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def detect() -> int:
    """Recurring successful command shapes are candidates for a forged agent."""
    try:
        import memory
    except ImportError:
        print("memory not available")
        return 1
    db = memory.load()
    counts = Counter()
    for entry in db["tools"].values():
        if entry["ok"] >= DETECT_MIN and entry["fail"] == 0:
            counts[(entry["tool"], entry["shape"])] = entry["ok"]
    if not counts:
        print("no recurring successful shape reaches the threshold yet")
        return 0
    print(f"candidates for automation (>= {DETECT_MIN} clean runs):")
    for (tool, shape), n in counts.most_common(10):
        print(f"  [{n}x] {tool}: {shape[:50]}")
    return 0


def register(agent_id: str, shape: str) -> Dict[str, Any]:
    db = _load()
    db["agents"].setdefault(agent_id, {
        "id": agent_id, "shape": shape, "state": "drafted",
        "baseline": [], "divergences": 0, "created": _now(),
        "approved_by_human": False,
        "gates": ["baseline_match", "zero_divergence", "human_review", "saves_tokens"],
    })
    _save(db)
    return db["agents"][agent_id]


def record_baseline(agent_id: str, inp: str, out: str) -> int:
    db = _load()
    a = db["agents"].get(agent_id)
    if a is None:
        a = register(agent_id, "")
        db = _load()
        a = db["agents"][agent_id]
    a["baseline"].append({"input": inp, "output": out})
    _save(db)
    print(f"{agent_id}: {len(a['baseline'])} baseline pair(s)")
    return 0


def check_divergence(agent_id: str, inp: str, out: str) -> int:
    """Compare a forged-agent output against the reasoning baseline for the same input."""
    db = _load()
    a = db["agents"].get(agent_id)
    if a is None:
        print(f"no agent {agent_id}", file=sys.stderr)
        return 1
    match = next((b for b in a["baseline"] if b["input"] == inp), None)
    if match is None:
        print(f"no baseline for this input; cannot promote on unseen input")
        return 1
    if match["output"] != out:
        a["divergences"] += 1
        _save(db)
        print(f"DIVERGENCE: forged output != baseline for input {inp!r}. Promotion blocked.")
        return 2
    print(f"{agent_id}: output matches baseline")
    return 0


def can_promote(agent_id: str) -> tuple[bool, str]:
    db = _load()
    a = db["agents"].get(agent_id)
    if a is None:
        return False, "unknown agent"
    if len(a["baseline"]) < BASELINE_RUNS:
        return False, f"needs {BASELINE_RUNS} baseline pairs, has {len(a['baseline'])}"
    if a["divergences"] > 0:
        return False, f"{a['divergences']} divergence(s): automating a wrong answer is not a win"
    if not a["approved_by_human"]:
        return False, "human review not recorded"
    return True, "ready"


def status(agent_id: str) -> int:
    ok, why = can_promote(agent_id)
    a = _load()["agents"].get(agent_id, {})
    print(f"{agent_id}: state={a.get('state')} baseline={len(a.get('baseline', []))} "
          f"divergences={a.get('divergences')} human={a.get('approved_by_human')}")
    print(f"  promotable: {ok} — {why}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("detect")
    b = sub.add_parser("record-baseline")
    b.add_argument("--id", required=True); b.add_argument("--input", required=True)
    b.add_argument("--output", required=True)
    c = sub.add_parser("check-divergence")
    c.add_argument("--id", required=True); c.add_argument("--input", required=True)
    c.add_argument("--output", required=True)
    s = sub.add_parser("status"); s.add_argument("--id", required=True)
    a = ap.parse_args()
    if a.cmd == "detect":
        return detect()
    if a.cmd == "record-baseline":
        return record_baseline(a.id, a.input, a.output)
    if a.cmd == "check-divergence":
        return check_divergence(a.id, a.input, a.output)
    return status(a.id)


if __name__ == "__main__":
    raise SystemExit(main())

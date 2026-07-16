#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""session_start.py — SessionStart hook. The one moment the memory gets to speak.

Everything else in failstop writes. This reads it back. Without this hook the store fills up
with lessons that nothing ever reads at the moment they could change an action: the gate only
speaks when the agent is already about to repeat a mistake, and by then a turn is spent.

Protocol, verified against the reference rather than assumed:

  * stdin : JSON with `source` (startup | resume | clear | compact), `session_id`, `cwd`, ...
  * stdout on exit 0 IS the context. SessionStart is one of only three events where stdout is
    injected for the model to read. No JSON envelope needed for plain context.
  * it CANNOT block. Exit 2 only shows stderr to the user. So this hook reports; it never
    guards. If the canon is broken, the session still starts — this can only make sure nobody
    can say they weren't told.
  * it runs on EVERY session, so it must be fast. Three small local files, no subprocesses.

Two design choices that matter more than the code:

  SILENCE WHEN THERE IS NOTHING TO SAY. A hook that prints a banner every time becomes
  wallpaper, and wallpaper is not read. Every line here has to be a line that could change the
  next action; if there are none, print nothing and cost nothing. The value of speaking at
  startup is spent the first time it is boring.

  `compact` IS THE IMPORTANT ONE. On a fresh startup the agent has lost nothing. After a
  compaction it has just lost the middle of its own session — that is precisely when the
  failures it already hit are worth handing back, because it is about to repeat them without
  knowing it ever tried.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

MAX_FIXES = 4          # a handful the agent will read, not a report it will skip


def _blocked_and_fixes():
    """(blocked shapes, recent failures with a known fix). Never raises."""
    try:
        import memory
    except ImportError:
        return [], []
    try:
        db = memory.load()
        blocked, fixes = [], []
        for e in db.get("tools", {}).values():
            if not isinstance(e, dict) or not e.get("fail"):
                continue
            run, _seen, repeated = memory.failure_run(db, e["tool"], e["shape"])
            if repeated:
                blocked.append((e["tool"], e["shape"], e.get("last_fix", "")))
            elif e.get("last_fix"):
                fixes.append((e["tool"], e["shape"], e["last_fix"], e["fail"]))
        fixes.sort(key=lambda t: -t[3])
        return blocked, fixes[:MAX_FIXES]
    except Exception:  # noqa: BLE001
        return [], []


def _integrity():
    """Anything a human needs to know before trusting this session's guardrails.

    The except clauses here are narrow ON PURPOSE. The first draft wrapped each block in a
    bare `except Exception: pass`, called canon.verify() — which returns an exit code, not a
    verdict — and swallowed the resulting AttributeError. The canon check silently never ran,
    and nothing anywhere would have said so. It was found only because the function also
    printed, and the stray text leaked into the very stdout this hook uses as its payload.

    A broad except in a guardrail is the guardrail agreeing, in advance, not to notice its own
    absence. ImportError is expected and handled; a bug is not, and it gets to be seen.
    """
    out = []
    try:
        import canon
    except ImportError:
        canon = None
    if canon is not None:
        v = canon.check()          # check() decides; verify() is the CLI that prints
        if not v["ok"]:
            out.append(f"CANON {v['verdict'].upper()}: {v['reason']}. The guardrails here are "
                       f"not the ones a human accepted — until someone re-locks, their approval "
                       f"is not evidence of anything.")
    try:
        import ledger
    except ImportError:
        return out
    v = ledger.verify()
    if not v["ok"]:
        out.append(f"LEDGER {v['verdict']}: {v['reason']}")
    a = ledger.check_anchor()
    if not a["ok"]:
        out.append(f"LEDGER ANCHOR: {a['reason']}")
    return out


def main() -> int:
    raw = sys.stdin.read()
    try:
        event = json.loads(raw) if raw.strip() else {}
    except ValueError:
        event = {}
    source = str(event.get("source", "startup"))

    lines = []

    # 1. Integrity first: if the guards themselves are in doubt, nothing below is worth much.
    problems = _integrity()
    if problems:
        lines.append("failstop — INTEGRITY:")
        lines.extend(f"  ! {p}" for p in problems)

    # 2. What is currently blocked. The agent is going to walk into these otherwise, spend a
    #    turn, and get refused — for something already known before the first prompt.
    blocked, fixes = _blocked_and_fixes()
    if blocked:
        lines.append("failstop — these command shapes are BLOCKED (proven loops):")
        for tool, shape, fix in blocked[:MAX_FIXES]:
            lines.append(f"  x {tool}: {shape[:70]}")
            if fix:
                lines.append(f"      fix on record: {fix[:110]}")
        lines.append("    Do not retry them unchanged. If a cause is already fixed, release it:")
        lines.append("    python scripts/memory.py clear --tool <T> --shape <S>")

    # 3. Fixes learned earlier. Only on compact/resume: on a new session there is no lost
    #    context to restore, and repeating this every startup is how it stops being read.
    if fixes and source in ("compact", "resume"):
        lines.append(f"failstop — known fixes from earlier ({source}):")
        for tool, shape, fix, n in fixes:
            lines.append(f"  - {tool} {shape[:50]} ({n}x): {fix[:100]}")

    if not lines:
        return 0        # nothing to say. Saying it anyway is how a hook becomes wallpaper.

    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except BaseException as exc:  # noqa: BLE001
        # This hook cannot block and must never cost a session. Report, exit 0.
        print(f"session_start error (non-fatal): {type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(0)

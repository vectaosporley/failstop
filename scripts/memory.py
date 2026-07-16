#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""memory.py — failstop's tool-reputation store.

FS-008: memory is written by code, not by an agent remembering to. This module is the
write path. The hooks call it; nothing relies on the agent's cooperation.

Design, learned from a store that held 8 failures and 0 successes after 29 days:
  * record BOTH outcomes. A store with only failures is a blocklist, not a reputation.
  * atomic writes (mkstemp + fsync + replace). An interrupted write must not corrupt it.
  * a corrupt store is quarantined and replaced, never raised on.
  * the verdict comes from the RUN OF FAILURES SINCE THE LAST SUCCESS, never from lifetime
    totals. Totals are two integers, and two integers cannot encode order — which is all
    reputation is. Judging from them failed in both directions at once: a shape that never
    succeeded blocked forever (and the block forbade the success that would clear it), while
    a shape that succeeded once was immune forever no matter how long it had been broken.
    See tests/test_gate_recency.py. Totals remain, but only as a report for the human.
  * ordering uses a monotonic sequence, never a timestamp. Two events in the same coarse
    clock tick are indistinguishable by time, and this store is written on Windows.
  * THERE IS NO ATTEMPT LIMIT. Counting to three was a number invented to stand in for a
    question it could not ask: is this attempt learning anything? A fixed threshold blocks
    `npm test` on its third honest failure — exactly when a fix cycle needs it — and lets a
    truly dead command retry forever as long as it stays under the count. The count is a bad
    proxy. So the criterion is novelty instead: an attempt whose error ALREADY OCCURRED in
    this run taught us nothing, and that is the loop, proven. While every error is new, the
    system is exploring; let it persist, ten times or fifty. FS-007 said this all along —
    "do not repeat a failed attempt" — and repeating means same input AND same output.
  * a failure with no captured error cannot be compared, so it can never prove a loop, so it
    never blocks. Capturing the error is therefore not a nicety; it is the precondition for
    this gate to exist at all. Abstaining is the recoverable direction (FS-012).

The store is machine-local: ~/.failstop/memory.json. Never committed. The mechanism is
public; the data it accumulates is not.

CLI (use `python` on Windows; `python3` elsewhere):
    python scripts/memory.py record --tool T --shape S --ok
    python scripts/memory.py record --tool T --shape S --fail --fix "..."
    python scripts/memory.py check  --tool T [--shape S]
    python scripts/memory.py clear  --tool T --shape S      # after fixing the root cause
    python scripts/memory.py report
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

HOME = Path(os.environ.get("FAILSTOP_HOME", Path.home() / ".failstop"))
STORE = HOME / "memory.json"

EMPTY: Dict[str, Any] = {"tools": {}, "log": [], "cleared": {}, "seq": 0}
# tools[key]   = {tool, shape, ok, fail, last_fix, last_seen, first_seen}   — lifetime, for humans
# log[i]       = {n, ts, tool, shape, ok, err, context}                     — ordered, for verdicts
#                `err` is the normalized error SIGNATURE. Without it no loop can be proven.
# cleared[key] = n                                                          — judge only after this
# seq          = last issued n. Monotonic; survives restarts; never a clock.
# key = "tool\x1eshape"


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def normalize_shape(command: str) -> str:
    """Reduce a command to its SHAPE, so a retry with a different path still matches.

    Paths, quoted strings, numbers and long hex are replaced by placeholders. This is
    what lets the reputation gate (Phase 4) recognise 'the same attempt' across sessions.
    """
    s = command.strip()
    s = re.sub(r"""(['"]).*?\1""", "<str>", s)          # quoted strings
    s = re.sub(r"[A-Za-z]:\\[^\s]+", "<path>", s)        # windows paths
    s = re.sub(r"(?<![\w/])(/[^\s]+)", "<path>", s)      # unix paths
    s = re.sub(r"\b[0-9a-f]{8,}\b", "<hex>", s)          # hashes/ids
    s = re.sub(r"\b\d+\b", "<n>", s)                      # bare numbers
    s = re.sub(r"\s+", " ", s)
    return s.strip()


def normalize_error(text: str) -> str:
    """Reduce an error to its SIGNATURE, for asking one question: have I seen this before?

    Normalized in the OPPOSITE direction from normalize_shape, and the asymmetry is the whole
    design. A shape is normalized aggressively so two retries collapse into one identity. An
    error must be normalized timidly, because in an error the details ARE the information:
      "3 tests failed" and "2 tests failed" are the sound of progress. Collapsing digits to
      <n> would make them the same string and block the fix cycle on its second run — the
      precise disaster this gate exists to avoid.
    So: strip only what is volatile per-run and carries no meaning (clocks, addresses, pids,
    random ids). Keep counts. Keep paths. Keep names.

    Erring toward "these errors differ" means erring toward not blocking, which is the
    recoverable direction (FS-012). An over-eager signature stalls real work; a shy one costs
    one repeated failure, which is then recorded.
    """
    s = str(text or "").strip()
    s = re.sub(r"\b\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}\S*", "<ts>", s)   # timestamps
    s = re.sub(r"\b\d{2}:\d{2}:\d{2}(?:[.,]\d+)?\b", "<time>", s)           # clock times
    s = re.sub(r"0x[0-9a-fA-F]+", "<addr>", s)                              # memory addresses
    s = re.sub(r"\b[0-9a-f]{12,}\b", "<hex>", s, flags=re.I)                # uuids, hashes
    s = re.sub(r"\b(pid|PID)[= ]\d+", "pid=<pid>", s)                       # process ids
    s = re.sub(r"\bin \d+(?:\.\d+)?\s?m?s\b", "in <dur>", s)                # "in 0.25s" footers
    s = re.sub(r"[\\/]tmp[\\/][^\s'\"]+", "<tmp>", s, flags=re.I)           # per-run temp paths
    s = re.sub(r"pytest-of-\S+", "<tmp>", s)
    s = re.sub(r"\s+", " ", s)
    return s.strip()          # NO TRUNCATION. See error_signature() for why there is no number.


def error_signature(text: str) -> str:
    """The identity of an error, for one question: is this the same one as before?

    A HASH OF THE WHOLE normalized error. No length to choose, because there is no cut.

    This started as `normalized[:400]` and cost a real bug: pytest prints a header — platform,
    rootdir, plugins, collected count — that is byte-identical between runs, and with a deep
    project path it exceeds 400. The signature became pure boilerplate, two runs with different
    failures compared equal, and the gate blocked the fix cycle it exists to protect. The real
    project measured 336: seventy characters from firing.

    The first fix was `[-400:]` — the tail, where pytest puts its summary and Python its
    exception. Better, and still wrong: fix test A while breaking test B and the summary reads
    "1 failed" both times, so the tail matches and the middle, where the difference lives, was
    thrown away.

    Then came the question that ended it: *does it matter if it's 800 instead of 400?* No. And
    that is the diagnosis. A number nobody can derive does not belong on the path where a
    decision is made — moving it only moves the cliff and leaves it just as invisible. 400 was
    picked out of the air, exactly like the attempt threshold removed from the gate one layer
    above and then left sitting here, where nobody looked.

    Hashing removes the choice instead of relocating it. Any difference, anywhere in the text,
    changes the signature.

    Prior art, consulted this time: this is error fingerprinting — Sentry has grouped errors by
    normalizing and hashing for a decade. It does not truncate either.
    """
    n = normalize_error(text)
    return hashlib.sha256(n.encode("utf-8")).hexdigest()[:16] if n else ""


def error_display(text: str, lineas: int = 3) -> str:
    """The error as a human reads it in a block message: the last few non-empty lines.

    A number survives here, and it is a different kind of number. Getting it wrong costs you
    some text on screen, not a wrong verdict — nothing decides on this. And it is still stated
    in LINES rather than bytes, because lines are where the meaning sits: Python's exception is
    the last line of a traceback, pytest's verdict is the last line of a run. `400 chars`
    respects arithmetic; `the last 3 lines` respects the shape of an error.
    """
    ls = [l.strip() for l in str(text or "").splitlines() if l.strip()]
    return " | ".join(ls[-lineas:])[:300] if ls else ""


def _key(tool: str, shape: str) -> str:
    return f"{tool}\x1e{shape}"


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


def load() -> Dict[str, Any]:
    """Never raises. A corrupt store is quarantined and replaced with an empty one."""
    if not STORE.is_file():
        return json.loads(json.dumps(EMPTY))
    try:
        data = json.loads(STORE.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        try:
            STORE.replace(STORE.parent / f"{STORE.name}.corrupt-{datetime.now():%Y%m%d-%H%M%S}")
        except OSError:
            pass
        return json.loads(json.dumps(EMPTY))
    if not isinstance(data, dict):
        return json.loads(json.dumps(EMPTY))
    for k, v in EMPTY.items():
        data.setdefault(k, json.loads(json.dumps(v)))
    return data


def save(db: Dict[str, Any]) -> None:
    _atomic_write(STORE, json.dumps(db, ensure_ascii=False, indent=2))


def record(tool: str, shape: str, ok: bool, fix: str = "", context: str = "",
           error: str = "") -> Dict[str, Any]:
    """Record ONE outcome. Returns the updated entry. This is the FS-008 write path.

    `error` is what the tool actually said when it failed. Recording that a call failed while
    discarding HOW it failed keeps only the count — and the count cannot tell a fix cycle from
    a loop. Pass it whenever it is available.
    """
    db = load()
    key = _key(tool, shape)
    entry = db["tools"].get(key)
    if entry is None:
        entry = {"tool": tool, "shape": shape, "ok": 0, "fail": 0,
                 "last_fix": "", "first_seen": _now(), "last_seen": _now()}
        db["tools"][key] = entry
    entry["ok" if ok else "fail"] += 1
    entry["last_seen"] = _now()
    if not ok and fix:
        entry["last_fix"] = fix
    db["seq"] = _next_seq(db)
    # Two fields, two jobs, and keeping them apart is the point:
    #   sig  decides   — a hash of the WHOLE normalized error. No length, so no blind spot.
    #   err  is read   — the last lines, for the human in the block message. Nothing decides
    #                    on it, so a bad cut here costs a shorter sentence and nothing else.
    db["log"].append({"n": db["seq"], "ts": _now(), "tool": tool, "shape": shape,
                      "ok": bool(ok),
                      "sig": "" if ok else error_signature(error),
                      "err": "" if ok else error_display(error),
                      "context": context[:200]})
    db["log"] = db["log"][-2000:]
    save(db)
    return entry


def _next_seq(db: Dict[str, Any]) -> int:
    try:
        return int(db.get("seq", 0)) + 1
    except (TypeError, ValueError):
        return 1


def _cleared_seq(db: Dict[str, Any], key: str) -> int:
    """The sequence number this shape was cleared at, or 0. A damaged field means NO clear:
    corruption must never be a way to launder a block away."""
    cleared = db.get("cleared")
    if not isinstance(cleared, dict):
        return 0
    try:
        return int(cleared.get(key, 0))
    except (TypeError, ValueError):
        return 0


def clear_shape(tool: str, shape: str) -> str:
    """Escape hatch: judge this shape only from here on.

    Needed because the block is self-sealing — it stops the command, so the command cannot
    produce the success that would lift the block. Without this the only exits are hand-editing
    the store or deleting it, i.e. destroying every lesson learned to unstick one command.

    This does NOT erase history: the totals stay visible, and if the shape fails again it
    blocks again. A clear says 'judge me from here', not 'this never happened'. A tool that
    can be argued out of its own memory has no memory.

    Every clear is written to the ledger. An escape hatch that leaves no trace is not an
    escape hatch, it is a back door: the one operation that overrides a guard is exactly the
    one that has to be on the record. Nobody is accused by this — the entry only makes the
    override visible to whoever looks later, including the person who did it.
    """
    db = load()
    if not isinstance(db.get("cleared"), dict):
        db["cleared"] = {}
    db["cleared"][_key(tool, shape)] = int(db.get("seq", 0) or 0)
    save(db)
    _witness("cleared a blocked shape", f"{tool}: {shape[:120]}")
    return _key(tool, shape)


def _witness(action: str, detail: str = "") -> None:
    """Record something on the ledger, and never let that stop the caller (FS-012).

    The ledger testifies; it does not enforce. If it cannot be written, the work still
    happens — a lost line of testimony costs less than a session that dies trying to take
    notes. The failure is printed, not swallowed: a silent witness is the thing this whole
    project exists to prevent.
    """
    try:
        import ledger
        ledger.append("agent", action, detail)
    except Exception as exc:  # noqa: BLE001
        print(f"ledger unavailable ({type(exc).__name__}: {exc}) — "
              f"the action proceeded, but it went unrecorded", file=sys.stderr)


def failure_run(db: Dict[str, Any], tool: str, shape: str) -> tuple[int, bool, str]:
    """The failures since this shape last succeeded (or since it was cleared).

    Returns (run, saw_evidence, repeated_error).

    `repeated_error` is the signature of the MOST RECENT failure if that same signature
    already appeared earlier in this run. That is the loop, proven from evidence rather than
    guessed from a counter: the last attempt produced an outcome we already had, so it added
    nothing. Empty means every failure so far said something new — the system is still
    learning, and there is no ground to stop it, at any length of run.

    An oscillation (A, B, A) counts as repetition too. Coming back to an error you already
    hit is not progress, it is a bigger circle.
    """
    key = _key(tool, shape)
    floor = _cleared_seq(db, key)
    fails: list = []          # newest first
    seen = False
    log = db.get("log")
    if not isinstance(log, list):
        return 0, False, ""
    for entry in reversed(log):
        if not isinstance(entry, dict):
            continue
        if entry.get("tool") != tool or entry.get("shape") != shape:
            continue
        try:
            if int(entry.get("n", 0)) <= floor:
                break            # at or before the clear: out of scope
        except (TypeError, ValueError):
            break
        seen = True
        if entry.get("ok"):
            break                # the run ends at the last success
        fails.append(entry)

    repeated = ""
    if len(fails) >= 2:
        # Compare by SIGNATURE, never by the displayed text. Entries written before signatures
        # existed have no `sig`, and for those `err` is all there is — comparing it is worse
        # than nothing only if it silently pretends to be the same test, so the fallback is
        # explicit and named rather than hidden behind a `.get(..., default)`.
        def _id(e):
            return str(e.get("sig") or "") or f"legacy:{e.get('err') or ''}"

        latest = _id(fails[0])
        if latest and not latest.startswith("legacy:") or (
                latest.startswith("legacy:") and len(latest) > len("legacy:")):
            if latest in [_id(e) for e in fails[1:]]:
                repeated = str(fails[0].get("err") or fails[0].get("sig") or "")
    return len(fails), seen, repeated


def judge(tool: str, command: str, expected: str, got: str = "", fix: str = "",
          worked: bool = False) -> Dict[str, Any]:
    """The agent's verdict. The only channel that can see the failures the hooks cannot.

    A PostToolUse hook reads `tool_response` and asks "did it error?". That question is
    answerable and nearly useless, because it is asked without a frame. `npm test` exiting 1
    is a failure in the frame "did the command succeed" and exactly the information you wanted
    in the frame "does the code work". A grep finding nothing exits 1 and did its job. And the
    reverse bites harder: a call that exits 0 and returns the wrong thing is recorded as a
    success forever, by every automatic channel there is.

    The hook cannot fix this by being cleverer. It does not know what the call was FOR. Only
    the caller does. So `expected` is required here — it is the frame, and without a frame
    there is no verdict to record, only an event.

    This is the same reason the tool-side story and the agent-side story converge: the
    automatic channel records what happened, and the agent records what it was supposed to
    mean. Neither is sufficient. Together they are a reputation.

    `worked=True` records that a previously-broken shape is fixed — which is not politeness,
    it is what lifts a block. A memory that only ever hears about failures becomes a blocklist.
    """
    shape = normalize_shape(command)
    if worked:
        e = record(tool, shape, ok=True, context=f"agent: works now (wanted: {expected[:80]})")
        _witness("agent reported a shape now works", f"{tool}: {shape[:90]}")
        return {**e, "shape": shape}
    error = f"AGENT VERDICT — wanted: {expected[:150]}"
    if got:
        error += f" | got: {got[:250]}"
    e = record(tool, shape, ok=False, fix=fix, error=error,
               context=f"agent judgment (frame: {expected[:60]})")
    _witness("agent reported a failure the hooks could not see",
             f"{tool}: {shape[:70]} | wanted: {expected[:80]}")
    return {**e, "shape": shape}


def check(tool: str, shape: Optional[str] = None) -> Dict[str, Any]:
    """What do we know about this tool (optionally this command shape)?

    Returns {ok, fail, run, repeated, verdict, last_fix}. ok/fail are lifetime totals, kept
    for the human report and never used to decide. The VERDICT asks one question — did the
    last attempt teach us anything?

      blocked   — the newest failure repeats an error already seen since this last worked.
                  Proven loop. Length of the run is irrelevant: two is enough if they are
                  identical, and fifty is fine if every one of them was new.
      suspect   — failing, but each failure has been novel. It is exploring. Advise, and get
                  out of the way.
      trusted   — the last thing it did was succeed.
      unknown   — no evidence in scope (never seen, just cleared, or aged out of the log).

    Anything other than a proven loop permits. This gate fails OPEN (FS-012): a missed block
    costs one repeated failure, which the post-hook then records; a false block costs a stuck
    agent, and the agent cannot record its way out of a block that prevents it from running.
    """
    db = load()

    if shape is not None:
        e = db["tools"].get(_key(tool, shape))
        if not e:
            return {"ok": 0, "fail": 0, "run": 0, "repeated": "",
                    "verdict": "unknown", "last_fix": ""}
        run, seen, repeated = failure_run(db, tool, shape)
        if repeated:
            verdict = "blocked"
        elif run > 0:
            verdict = "suspect"
        elif seen:
            verdict = "trusted"
        else:
            verdict = "unknown"
        return {"ok": e["ok"], "fail": e["fail"], "run": run, "repeated": repeated,
                "verdict": verdict, "last_fix": e["last_fix"]}

    # tool-wide summary: a coarse report, never a gate input. Blocking is per-shape only —
    # one broken shape must not condemn every use of the tool.
    ok = sum(e["ok"] for e in db["tools"].values() if e["tool"] == tool)
    fail = sum(e["fail"] for e in db["tools"].values() if e["tool"] == tool)
    verdict = "unknown" if ok + fail == 0 else ("suspect" if fail else "trusted")
    return {"ok": ok, "fail": fail, "run": 0, "repeated": "", "verdict": verdict, "last_fix": ""}


def report() -> int:
    db = load()
    tools = list(db["tools"].values())
    total_ok = sum(t["ok"] for t in tools)
    total_fail = sum(t["fail"] for t in tools)
    print(f"failstop memory: {STORE}")
    print(f"  shapes tracked: {len(tools)} | ok: {total_ok} | fail: {total_fail}")
    if total_ok == 0 and total_fail > 0:
        print("  WARNING: zero successes. A store with only failures is a blocklist.")
    blocked = []
    worst = sorted((t for t in tools if t["fail"]), key=lambda t: -t["fail"])[:8]
    for t in worst:
        run, _, repeated = failure_run(db, t["tool"], t["shape"])
        if repeated:
            state = f"LOOPING — {run} since it last worked, same error repeating"
        elif run:
            state = f"{run} since it last worked, each one different"
        else:
            state = "recovered"
        print(f"  [{t['fail']}x fail / {t['ok']}x ok | {state}] {t['tool']}: {t['shape'][:50]}")
        if t["last_fix"]:
            print(f"       fix: {t['last_fix'][:80]}")
        if repeated:
            blocked.append(t)
    if blocked:
        print(f"\n  {len(blocked)} shape(s) currently BLOCKED. If you fixed the cause, release one with:")
        print(f"    python {Path(__file__).name} clear --tool {blocked[0]['tool']} "
              f"--shape {json.dumps(blocked[0]['shape'])}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("record")
    r.add_argument("--tool", required=True)
    r.add_argument("--shape", required=True)
    g = r.add_mutually_exclusive_group(required=True)
    g.add_argument("--ok", action="store_true")
    g.add_argument("--fail", action="store_true")
    r.add_argument("--fix", default="")
    r.add_argument("--context", default="")
    r.add_argument("--error", default="", help="what the tool actually said. Without it no "
                                               "loop can be proven and the gate abstains.")
    c = sub.add_parser("check")
    c.add_argument("--tool", required=True)
    c.add_argument("--shape", default=None)
    cl = sub.add_parser("clear", help="release a blocked shape after fixing the root cause")
    cl.add_argument("--tool", required=True)
    cl.add_argument("--shape", required=True)
    rp = sub.add_parser("judge", help="the agent's verdict: something failed that no hook could see")
    rp.add_argument("--command", required=True, help="what you ran, verbatim")
    rp.add_argument("--expected", required=True,
                    help="THE FRAME: what you needed it to do. Without this there is no verdict "
                         "to record — only you know what the call was for.")
    rp.add_argument("--got", default="", help="what actually happened instead")
    rp.add_argument("--fix", default="", help="what to do instead next time")
    rp.add_argument("--tool", default="Bash")
    ok = rp.add_mutually_exclusive_group()
    ok.add_argument("--worked", action="store_true",
                    help="it works now — you fixed the cause and are clearing the record")
    sub.add_parser("report")
    a = ap.parse_args()

    if a.cmd == "record":
        e = record(a.tool, normalize_shape(a.shape), a.ok, a.fix, a.context, a.error)
        print(json.dumps({k: e[k] for k in ("tool", "ok", "fail")}, ensure_ascii=False))
        return 0
    if a.cmd == "check":
        shape = normalize_shape(a.shape) if a.shape else None
        print(json.dumps(check(a.tool, shape), ensure_ascii=False))
        return 0
    if a.cmd == "clear":
        clear_shape(a.tool, normalize_shape(a.shape))
        print(json.dumps({"cleared": normalize_shape(a.shape), "tool": a.tool},
                         ensure_ascii=False))
        return 0
    if a.cmd == "judge":
        e = judge(a.tool, a.command, a.expected, a.got, a.fix, worked=a.worked)
        print(json.dumps({"recorded": "success" if a.worked else "failure",
                          "shape": e["shape"], "ok": e["ok"], "fail": e["fail"]},
                         ensure_ascii=False))
        return 0
    return report()


if __name__ == "__main__":
    raise SystemExit(main())

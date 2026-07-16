#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ledger.py — the contract. An append-only, hash-chained, tamper-EVIDENT record.

Neither party is trusted, and that is the point. The agent writes here (blocks it hit, fixes
it reported, shapes it cleared). The human writes here (rules changed, blocks overridden,
canon amended). Each entry carries the hash of the one before it, so the past cannot be
rewritten in silence: any edit, deletion or reordering breaks the chain, and verify() says
exactly where.

The good deals happen between two parties who do not trust each other and have a written
contract. Not because either is dishonest — because a record neither side can quietly revise
is what makes it safe to disagree later.

Honest about the guarantee, because a security claim that oversells is worse than none:
  * tamper-EVIDENT, not tamper-proof. Whoever can write this file can recompute the whole
    chain and produce a perfectly consistent lie.
  * The defence against that is an ANCHOR: publish the head hash somewhere the other party
    controls (a git commit, a printed line, a second machine). Then a full rewrite is
    detectable, because the anchored head will have vanished from the chain. anchor() and
    check_anchor() are that.
  * A ledger nobody ever verifies is a diary. verify() has to be called by something.

FS-012: this fails in the recoverable direction. A ledger that cannot be read must not stop
the session — it reports and gets out of the way. Enforcement is not its job; testimony is.

CLI (use `python` on Windows; `python3` elsewhere):
    python scripts/ledger.py append --actor agent --action "..." --detail "..."
    python scripts/ledger.py verify
    python scripts/ledger.py anchor
    python scripts/ledger.py check-anchor
    python scripts/ledger.py show
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

HOME = Path(os.environ.get("FAILSTOP_HOME", Path.home() / ".failstop"))
LEDGER = Path(os.environ.get("FAILSTOP_LEDGER", HOME / "ledger.jsonl"))
ANCHOR = Path(os.environ.get("FAILSTOP_LEDGER_ANCHOR", HOME / "ledger.anchor"))
GENESIS = "0" * 64

_HASHED_FIELDS = ("seq", "ts", "actor", "action", "detail", "prev_hash")


def _hash_entry(entry: Dict[str, Any]) -> str:
    """Hash of an entry's canonical content, excluding its own `hash` field.

    sort_keys and a fixed separator matter: if the same content could serialise two ways, the
    same entry would hash two ways, and the chain would break for no reason at all.
    """
    payload = {k: entry.get(k) for k in _HASHED_FIELDS}
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _read_all() -> List[Dict[str, Any]]:
    """Never raises. An unparseable line is kept as a marker, not silently dropped — a line
    you cannot read is evidence too, and hiding it would be the ledger editing itself."""
    if not LEDGER.is_file():
        return []
    out: List[Dict[str, Any]] = []
    try:
        lines = LEDGER.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            parsed = json.loads(line)
            out.append(parsed if isinstance(parsed, dict) else {"_corrupt": line[:120]})
        except ValueError:
            out.append({"_corrupt": line[:120]})
    return out


def _chain(entries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [e for e in entries if "hash" in e and "_corrupt" not in e]


def head() -> str:
    """Hash of the last valid entry, or GENESIS. This is the value worth anchoring."""
    for e in reversed(_chain(_read_all())):
        return str(e["hash"])
    return GENESIS


class _Lock:
    """A best-effort exclusive lock around the read-then-append.

    Without it, two hooks firing at once both read the same head and both write an entry
    claiming it. The chain forks, and verify() would report 'the history was edited' — an
    accusation of tampering for what was only a race. A ledger that cries wolf about tampering
    is worse than no ledger: the one time it matters, nobody will believe it.

    O_CREAT|O_EXCL is atomic on every filesystem we care about, which is why it is used here
    instead of a lockfile check-then-create. If the lock cannot be taken we append anyway —
    fail open (FS-012) — because a lost testimony is worse than a forked chain, and verify()
    can name a fork for what it is.
    """

    def __init__(self, path: Path, timeout: float = 2.0):
        self.path = path
        self.timeout = timeout
        self.fd = None

    def __enter__(self):
        deadline = time.time() + self.timeout
        while time.time() < deadline:
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                self.fd = os.open(str(self.path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                return self
            except FileExistsError:
                # a stale lock from a crashed process must not wedge this forever
                try:
                    if time.time() - self.path.stat().st_mtime > 30:
                        self.path.unlink(missing_ok=True)
                        continue
                except OSError:
                    pass
                time.sleep(0.02)
            except OSError:
                return self          # cannot lock here; proceed unlocked rather than lose the entry
        return self

    def __exit__(self, *exc):
        if self.fd is not None:
            try:
                os.close(self.fd)
            except OSError:
                pass
            self.path.unlink(missing_ok=True)
        return False


def append(actor: str, action: str, detail: str = "") -> Dict[str, Any]:
    """Add one chained entry. Never rewrites, never reorders, never deletes.

    `actor` is 'agent', 'human', or 'tool:<name>'. Naming who spoke is half the contract:
    an entry whose author is unknown proves that something happened, not that anyone said it.
    """
    actor = str(actor or "").strip() or "unknown"
    if actor not in ("agent", "human") and not actor.startswith("tool:"):
        actor = f"tool:{actor}"
    with _Lock(LEDGER.with_suffix(".lock")):
        entries = _read_all()
        chain = _chain(entries)
        entry = {
            "seq": len(chain),
            "ts": datetime.now().isoformat(timespec="seconds"),
            "actor": actor,
            "action": str(action)[:80],
            "detail": str(detail or "")[:500],
            "prev_hash": str(chain[-1]["hash"]) if chain else GENESIS,
        }
        entry["hash"] = _hash_entry(entry)
        LEDGER.parent.mkdir(parents=True, exist_ok=True)
        with LEDGER.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
            fh.flush()
            os.fsync(fh.fileno())
    return entry


def verify() -> Dict[str, Any]:
    """Walk the chain and name what is wrong, precisely.

    Returns {ok, entries, broken_at, verdict, reason}. The verdict distinguishes mechanisms
    that a naive checker would lump together as "tampering":

      ALTERED    an entry's content no longer matches its own hash. Someone edited history.
                 This is the real thing.
      FORKED     two entries claim the same predecessor. Almost always two writers racing,
                 not an attack. Called by its name, because accusing a race of forgery is how
                 a guard loses the credibility it needs on the day it is right.
      CORRUPT    a line that will not parse. Truncated write, disk error — unknown cause.
                 Reported as unknown, never as an attack.

    That distinction is the whole reason this returns a verdict instead of a boolean.
    """
    raw = _read_all()
    corrupt = [i for i, e in enumerate(raw) if "_corrupt" in e]
    entries = _chain(raw)

    seen_prev: Dict[str, int] = {}
    prev = GENESIS
    for i, e in enumerate(entries):
        if e.get("hash") != _hash_entry(e):
            return {"ok": False, "entries": len(entries), "broken_at": i, "verdict": "ALTERED",
                    "reason": f"entry #{i} was edited: its content no longer matches its own hash"}
        p = str(e.get("prev_hash"))
        # No exception for GENESIS. Exactly one entry may name it, so two that do is a fork —
        # and at the root is the likeliest fork of all: an empty ledger and two hooks starting
        # at once. Excusing the root here would misreport that first race as forgery.
        if p in seen_prev:
            return {"ok": False, "entries": len(entries), "broken_at": i, "verdict": "FORKED",
                    "reason": f"entries #{seen_prev[p]} and #{i} both claim the same predecessor. "
                              f"Two writers appended at once — a race, not an edit. The record "
                              f"is complete; only its order is ambiguous."}
        seen_prev[p] = i
        if p != prev:
            return {"ok": False, "entries": len(entries), "broken_at": i, "verdict": "ALTERED",
                    "reason": f"entry #{i} points at a predecessor that is not the previous "
                              f"entry: history was reordered or something was removed"}
        prev = str(e["hash"])

    if corrupt:
        return {"ok": False, "entries": len(entries), "broken_at": corrupt[0], "verdict": "CORRUPT",
                "reason": f"{len(corrupt)} unreadable line(s). Cause unknown — could be a "
                          f"truncated write. Do NOT call this tampering without a second check.",
                "head": prev}
    return {"ok": True, "entries": len(entries), "verdict": "INTACT", "head": prev}


def anchor() -> str:
    """Pin the current head where a rollback would show.

    Hash-chaining alone cannot survive a party who rewrites the entire file: they recompute
    every hash and the chain verifies perfectly. The only defence is that someone else
    remembers what the head used to be. Anchoring locally is the weakest useful form of that —
    commit the value, print it, mail it to yourself. The further from this machine, the better.
    """
    h = head()
    ANCHOR.parent.mkdir(parents=True, exist_ok=True)
    ANCHOR.write_text(json.dumps({"head": h, "ts": datetime.now().isoformat(timespec="seconds")}),
                      encoding="utf-8")
    return h


def check_anchor() -> Dict[str, Any]:
    """Is the anchored head still in the chain? Catches a rewrite that verify() cannot."""
    if not ANCHOR.is_file():
        return {"ok": True, "reason": "no anchor set — a full rewrite would be undetectable"}
    try:
        anchored = json.loads(ANCHOR.read_text(encoding="utf-8")).get("head")
    except (ValueError, OSError):
        return {"ok": False, "reason": "the anchor itself is unreadable"}
    if anchored == GENESIS:
        return {"ok": True, "anchored_head": anchored}
    if anchored in {e.get("hash") for e in _chain(_read_all())}:
        return {"ok": True, "anchored_head": anchored}
    return {"ok": False, "anchored_head": anchored,
            "reason": "the anchored head is GONE from the ledger. The chain was not appended "
                      "to — it was replaced. This is the one thing hashes alone cannot catch."}


def show(n: int = 15) -> str:
    entries = _chain(_read_all())
    lines = [f"  #{e['seq']} [{e['actor']}] {e['action']} — {str(e.get('detail',''))[:60]} "
             f"({str(e['hash'])[:10]})" for e in entries[-n:]]
    v = verify()
    lines.append(f"  chain: {v['verdict']}" + ("" if v["ok"] else f" at #{v.get('broken_at')} — {v['reason']}"))
    a = check_anchor()
    lines.append(f"  anchor: {'ok' if a['ok'] else 'FAILED — ' + a['reason']}")
    return "\n".join(lines) if entries else "  (ledger empty)"


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser(description="The contract: an append-only hash-chained record")
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("append")
    a.add_argument("--actor", required=True, help="agent | human | tool:<name>")
    a.add_argument("--action", required=True)
    a.add_argument("--detail", default="")
    sub.add_parser("verify")
    sub.add_parser("anchor")
    sub.add_parser("check-anchor")
    s = sub.add_parser("show")
    s.add_argument("-n", type=int, default=15)
    args = ap.parse_args()

    if args.cmd == "append":
        e = append(args.actor, args.action, args.detail)
        print(f"appended #{e['seq']} {e['hash'][:12]}")
    elif args.cmd == "verify":
        v = verify()
        print(v["verdict"] if v["ok"] else f"{v['verdict']}: {v['reason']}")
        return 0 if v["ok"] else 1
    elif args.cmd == "anchor":
        print("anchored head:", anchor()[:16])
    elif args.cmd == "check-anchor":
        c = check_anchor()
        print("OK" if c["ok"] else f"REWRITTEN: {c['reason']}")
        return 0 if c["ok"] else 1
    else:
        print(show(args.n))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

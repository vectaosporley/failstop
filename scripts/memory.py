#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""memory.py — failstop's tool-reputation store.

FS-008: memory is written by code, not by an agent remembering to. This module is the
write path. The hooks call it; nothing relies on the agent's cooperation.

Design, learned from a store that held 8 failures and 0 successes after 29 days:
  * record BOTH outcomes. A store with only failures is a blocklist, not a reputation.
  * atomic writes (mkstemp + fsync + replace). An interrupted write must not corrupt it.
  * a corrupt store is quarantined and replaced, never raised on.

The store is machine-local: ~/.failstop/memory.json. Never committed. The mechanism is
public; the data it accumulates is not.

CLI:
    python3 scripts/memory.py record --tool T --shape S --ok
    python3 scripts/memory.py record --tool T --shape S --fail --fix "..."
    python3 scripts/memory.py check  --tool T [--shape S]
    python3 scripts/memory.py report
"""
from __future__ import annotations

import argparse
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

EMPTY: Dict[str, Any] = {"tools": {}, "log": []}
# tools[key] = {tool, shape, ok, fail, last_fix, last_seen, first_seen}
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


def record(tool: str, shape: str, ok: bool, fix: str = "", context: str = "") -> Dict[str, Any]:
    """Record ONE outcome. Returns the updated entry. This is the FS-008 write path."""
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
    db["log"].append({"ts": _now(), "tool": tool, "shape": shape,
                      "ok": ok, "context": context[:200]})
    db["log"] = db["log"][-2000:]
    save(db)
    return entry


def check(tool: str, shape: Optional[str] = None) -> Dict[str, Any]:
    """What do we know about this tool (optionally this command shape)?

    Returns {ok, fail, verdict, last_fix}. verdict is the input for the reputation gate:
      trusted   — succeeded, never failed on this shape
      suspect   — has failed, threshold not reached
      blocked   — failed >= FAILSTOP_BLOCK_AFTER times on this exact shape
      unknown   — never seen
    """
    db = load()
    block_after = int(os.environ.get("FAILSTOP_BLOCK_AFTER", "3"))

    if shape is not None:
        e = db["tools"].get(_key(tool, shape))
        if not e:
            return {"ok": 0, "fail": 0, "verdict": "unknown", "last_fix": ""}
        if e["fail"] >= block_after and e["ok"] == 0:
            verdict = "blocked"
        elif e["fail"] > 0:
            verdict = "suspect"
        else:
            verdict = "trusted"
        return {"ok": e["ok"], "fail": e["fail"], "verdict": verdict, "last_fix": e["last_fix"]}

    ok = sum(e["ok"] for e in db["tools"].values() if e["tool"] == tool)
    fail = sum(e["fail"] for e in db["tools"].values() if e["tool"] == tool)
    verdict = "unknown" if ok + fail == 0 else ("suspect" if fail else "trusted")
    return {"ok": ok, "fail": fail, "verdict": verdict, "last_fix": ""}


def report() -> int:
    db = load()
    tools = list(db["tools"].values())
    total_ok = sum(t["ok"] for t in tools)
    total_fail = sum(t["fail"] for t in tools)
    print(f"failstop memory: {STORE}")
    print(f"  shapes tracked: {len(tools)} | ok: {total_ok} | fail: {total_fail}")
    if total_ok == 0 and total_fail > 0:
        print("  WARNING: zero successes. A store with only failures is a blocklist.")
    worst = sorted((t for t in tools if t["fail"]), key=lambda t: -t["fail"])[:8]
    for t in worst:
        print(f"  [{t['fail']}x fail / {t['ok']}x ok] {t['tool']}: {t['shape'][:50]}")
        if t["last_fix"]:
            print(f"       fix: {t['last_fix'][:80]}")
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
    c = sub.add_parser("check")
    c.add_argument("--tool", required=True)
    c.add_argument("--shape", default=None)
    sub.add_parser("report")
    a = ap.parse_args()

    if a.cmd == "record":
        e = record(a.tool, normalize_shape(a.shape), a.ok, a.fix, a.context)
        print(json.dumps({k: e[k] for k in ("tool", "ok", "fail")}, ensure_ascii=False))
        return 0
    if a.cmd == "check":
        shape = normalize_shape(a.shape) if a.shape else None
        print(json.dumps(check(a.tool, shape), ensure_ascii=False))
        return 0
    return report()


if __name__ == "__main__":
    raise SystemExit(main())

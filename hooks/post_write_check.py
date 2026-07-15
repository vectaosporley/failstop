#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""post_write_check.py — PostToolUse hook. Integrity of a file just written.

Enforces FS-003 (corroborate before indicting a tool) and FS-008 (report inside the
same call, not three steps later).

What PostToolUse can and cannot do (verified against the reference):
  * It CANNOT block. The write already happened.
  * `{"decision": "block", "reason": ...}` on stdout, or exit 2 with stderr, feeds the
    finding back to the agent so its next action is a fix, not a continuation.

Three outcomes, not two. This is the whole point:

  clean         file re-reads fine — no NUL bytes, parses if it is code.  Say nothing.
  corrupt       file re-reads as damaged AND the damage is corroborated.  Block, report.
  unverifiable  the read looks wrong but cannot be corroborated.          Report as
                UNVERIFIABLE — never as corruption.

The third state exists because of Phase 0: five files looked truncated through one channel
and were intact through another. A hook that had only clean/corrupt would have reported five
false corruptions and sent someone to file a bug against the wrong tool.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PARSE_SUFFIXES = {".py", ".json", ".yaml", ".yml", ".toml"}
WRITING_TOOLS = {"Edit", "Write", "NotebookEdit", "MultiEdit"}


def _report(reason: str) -> int:
    """Feed the finding back to the agent. exit 2 also surfaces stderr; belt and suspenders."""
    json.dump({"decision": "block", "reason": reason}, sys.stdout)
    sys.stdout.write("\n")
    sys.stdout.flush()
    print(reason, file=sys.stderr)
    return 2


def _silent() -> int:
    return 0


def _has_nul(data: bytes) -> bool:
    return b"\x00" in data


def _parse_error(path: Path, data: bytes) -> str:
    """Return a parse error string, or '' if it parses (or we do not parse this type)."""
    suffix = path.suffix.lower()
    if suffix not in PARSE_SUFFIXES:
        return ""
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        return f"not valid UTF-8: {exc}"
    if suffix == ".py":
        import ast
        try:
            ast.parse(text)
        except SyntaxError as exc:
            return f"Python syntax error: {exc.msg} (line {exc.lineno})"
    elif suffix == ".json":
        try:
            json.loads(text)
        except ValueError as exc:
            return f"invalid JSON: {exc}"
    elif suffix in {".yaml", ".yml"}:
        try:
            import yaml  # type: ignore
        except ImportError:
            return ""     # cannot check without the lib; do not cry wolf
        try:
            yaml.safe_load(text)
        except Exception as exc:  # noqa: BLE001
            return f"invalid YAML: {exc}"
    elif suffix == ".toml":
        try:
            import tomllib  # py3.11+
        except ImportError:
            return ""
        try:
            tomllib.loads(text)
        except Exception as exc:  # noqa: BLE001
            return f"invalid TOML: {exc}"
    return ""


def _second_channel_size(path: Path) -> int | None:
    """Corroborate the byte count through a channel this process did not read through.

    On Windows, ask the OS via `cmd /c dir`. Elsewhere, `stat`. Returns None if no
    independent channel is available — in which case a suspicious read is UNVERIFIABLE,
    not corrupt.
    """
    try:
        if sys.platform.startswith("win"):
            out = subprocess.run(["cmd", "/c", "dir", "/-c", str(path)],
                                 capture_output=True, text=True, timeout=10)
            for line in out.stdout.splitlines():
                parts = line.split()
                if parts and parts[-1].lower() == path.name.lower():
                    for tok in parts:
                        digits = tok.replace(".", "").replace(",", "")
                        if digits.isdigit():
                            return int(digits)
            return None
        out = subprocess.run(["stat", "-c", "%s", str(path)],
                             capture_output=True, text=True, timeout=10)
        return int(out.stdout.strip()) if out.returncode == 0 else None
    except Exception:  # noqa: BLE001
        return None


def _record(tool: str, path: Path, ok: bool, detail: str = "") -> None:
    """Feed the CONTENT verdict to memory (FS-008). record_outcome cedes file writes to us,
    so a write that produced unparseable code is recorded as a failure, not a false success."""
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
        import memory
        shape = memory.normalize_shape(f"{tool} {path.suffix or '<none>'}")
        memory.record(tool, shape, ok=ok, fix="", context=detail[:200])
    except Exception:  # noqa: BLE001
        pass   # a memory write must never derail the session


def main() -> int:
    raw = sys.stdin.read()
    if not raw.strip():
        return _silent()   # nothing to check; PostToolUse cannot block anyway

    try:
        event = json.loads(raw)
    except ValueError:
        return _silent()

    if not isinstance(event, dict) or event.get("tool_name") not in WRITING_TOOLS:
        return _silent()

    tool_input = event.get("tool_input")
    if not isinstance(tool_input, dict):
        return _silent()

    raw_path = tool_input.get("file_path") or tool_input.get("notebook_path")
    if not raw_path:
        return _silent()

    path = Path(str(raw_path))
    if not path.is_absolute():
        path = Path(str(event.get("cwd", "."))) / path

    try:
        data = path.read_bytes()
    except OSError as exc:
        return _report(f"FS-008: wrote {path.name} but cannot read it back ({exc}).")

    # 1. NUL bytes: corroborate before indicting.
    if _has_nul(data):
        size2 = _second_channel_size(path)
        if size2 is None:
            return _report(
                f"FS-003 UNVERIFIABLE: {path.name} reads with NUL bytes, but no second channel "
                f"could confirm it. Do NOT report the write tool as faulty. Re-read after a "
                f"moment, or check the file on the host, before concluding anything.")
        if size2 == len(data):
            _record(event["tool_name"], path, ok=False, detail="NUL bytes (corroborated)")
            return _report(f"FS-008: {path.name} contains NUL bytes (corroborated at {size2} bytes). "
                           f"The write is corrupt.")
        return _report(
            f"FS-003 UNVERIFIABLE: this process read {len(data)} bytes with NUL, but a second "
            f"channel reports {size2}. The reader is stale, not the file. Re-read before acting.")

    # 2. Code that does not parse.
    err = _parse_error(path, data)
    if err:
        size2 = _second_channel_size(path)
        if size2 is not None and size2 != len(data):
            return _report(
                f"FS-003 UNVERIFIABLE: {path.name} fails to parse here ({err}), but this process "
                f"read {len(data)} bytes while a second channel reports {size2}. Likely a stale "
                f"read, not a broken file. Re-read before concluding.")
        _record(event["tool_name"], path, ok=False, detail=f"does not parse: {err}")
        return _report(f"FS-008: {path.name} was written but does not parse — {err}. "
                       f"Fix this now, before the next step, where the cause will be hard to find.")

    # clean write: record the success, then stay silent
    _record(event["tool_name"], path, ok=True)
    return _silent()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except BaseException as exc:  # noqa: BLE001
        # PostToolUse cannot block; a crash here must not derail the session. Report, exit 0.
        print(f"post_write_check error (non-fatal): {type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(0)

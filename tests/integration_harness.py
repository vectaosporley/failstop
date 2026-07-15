#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""integration_harness.py — replays hooks.json the way Claude Code does.

Unit tests exercise each hook in isolation. This harness closes the gap they leave:
does hooks.json correctly ROUTE a tool call to the right hooks, and do their decisions
combine the way the runtime combines them?

It reads hooks.json, matches the tool name against each matcher (regex or "*"), runs every
matching command hook with the event JSON on stdin — exactly as documented — and reduces the
results: for PreToolUse, any `deny` (or exit 2) denies; otherwise allow.

This is not a substitute for installing the plugin. It is the integration layer that can be
verified deterministically, here, without a live agent.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

ROOT = Path(__file__).resolve().parent.parent
HOOKS_JSON = ROOT / "hooks" / "hooks.json"


def _matches(matcher: str, tool: str) -> bool:
    if matcher in ("*", ""):
        return True
    return re.fullmatch(matcher, tool) is not None


def _run_command(command: str, event: Dict[str, Any]) -> Tuple[int, str, str]:
    # ${CLAUDE_PLUGIN_ROOT} resolves to the plugin root at install time.
    cmd = command.replace("${CLAUDE_PLUGIN_ROOT}", str(ROOT))
    p = subprocess.run(cmd, shell=True, input=json.dumps(event),
                       capture_output=True, text=True, timeout=30)
    return p.returncode, p.stdout, p.stderr


def fire(event: Dict[str, Any]) -> Dict[str, Any]:
    """Replay all hooks for one event. Returns the combined outcome."""
    cfg = json.loads(HOOKS_JSON.read_text(encoding="utf-8"))
    phase = event["hook_event_name"]
    tool = event.get("tool_name", "")
    groups = cfg.get("hooks", {}).get(phase, [])

    fired: List[str] = []
    decision = "allow"
    reasons: List[str] = []

    for group in groups:
        if not _matches(group.get("matcher", "*"), tool):
            continue
        for hook in group.get("hooks", []):
            if hook.get("type") != "command":
                continue
            code, out, err = _run_command(hook["command"], event)
            fired.append(hook["command"].split("/")[-1].strip('"'))
            # PreToolUse: deny via JSON decision or exit 2
            if phase == "PreToolUse":
                if code == 2:
                    decision = "deny"; reasons.append(err.strip())
                elif out.strip():
                    try:
                        d = json.loads(out)
                        pd = d.get("hookSpecificOutput", {}).get("permissionDecision")
                        if pd == "deny":
                            decision = "deny"
                            reasons.append(d["hookSpecificOutput"].get("permissionDecisionReason", ""))
                    except ValueError:
                        pass
            elif phase == "PostToolUse":
                if code == 2 or (out.strip() and _is_block(out)):
                    decision = "block"; reasons.append(_reason(out) or err.strip())

    return {"decision": decision, "fired": fired, "reasons": [r for r in reasons if r]}


def _is_block(out: str) -> bool:
    try:
        return json.loads(out).get("decision") == "block"
    except ValueError:
        return False


def _reason(out: str) -> str:
    try:
        return json.loads(out).get("reason", "")
    except ValueError:
        return ""


if __name__ == "__main__":
    # smoke: try to edit the canon
    ev = {"hook_event_name": "PreToolUse", "tool_name": "Edit", "cwd": str(ROOT),
          "tool_input": {"file_path": str(ROOT / "CANON.md"),
                         "old_string": "a", "new_string": "b"}}
    print(json.dumps(fire(ev), indent=2))

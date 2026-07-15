---
name: check-what-the-tool-reads
description: Before quoting a number or state a tool reported, confirm which project, file, or root that tool is actually reading. Trigger when about to repeat a count, status, version, or metric from any status tool, MCP, or command, especially across multiple projects or environments. Prevents repeating a stale or wrong-source figure as current fact.
---

# Check what the tool reads

The failure this prevents, measured: a status tool reported "265 gaps". The number was repeated
four times as current fact before anyone checked which directory the tool was reading. It was the
old project. The active project had 2.

## The rule

**A tool's number is only as current as the thing it points at.** Before you quote it, confirm
the source.

## How

- A status/MCP tool spans multiple projects or roots? Confirm which one it is bound to right now.
  A hardcoded root, a stale config, a default path — any of these makes the number describe the
  wrong thing.
- The figure looks surprising, or contradicts what you just saw in the files? Trust the files.
  Read the source directly before repeating the tool's summary.
- The tool reports a version or identity? Check it matches the project you think you're in.
  `"version": "old-2.0"` is the tool telling you it's reading the wrong place.

## The tell

You're about to write a specific number — "265 gaps", "0 successes", "14 tools" — that you got
from a tool, not from looking. Before it becomes a fact in your answer, confirm the tool is
reading what you think it is. One check now prevents a wrong number repeated four times.

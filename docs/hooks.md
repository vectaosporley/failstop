# The hook protocol, as verified

Read from the hooks reference, then exercised in tests. Not assumed.

## What a PreToolUse hook receives

JSON on stdin. Common fields include `session_id`, `cwd`, `hook_event_name`, `permission_mode`.
Event-specific: `tool_name`, `tool_input`, `tool_use_id`.

| Tool | `tool_input` fields |
|---|---|
| `Edit` | `file_path`, `old_string`, `new_string` |
| `Write` | `file_path`, `content` |
| `Bash` | `command` (and others) |

## How to deny

Two ways. They are not equivalent.

**1. A decision object on stdout, exit 0.** The hook succeeded; its answer is "no".

```json
{
  "hookSpecificOutput": {
    "hookEventName": "PreToolUse",
    "permissionDecision": "deny",
    "permissionDecisionReason": "why, in words the agent will read"
  }
}
```

`permissionDecision` accepts `allow`, `deny`, `ask`, `defer`.

**2. Exit 2.** Blocks the call. Whatever is on stderr is fed back to the agent as an error.
Use this when the hook cannot produce a trustworthy decision — malformed input, a missing
dependency, an unhandled exception.

## The trap

> **Exit 1 does not block.**

Claude Code treats exit code 1 as a *non-blocking* error and runs the tool anyway, even though 1 is
the conventional Unix failure code. A policy hook that crashes with `sys.exit(1)`, or that lets an
uncaught exception propagate under a runner that maps it to 1, **permits in silence**.

This is why `hooks/protect_canon.py` catches everything and exits 2 on any confusion. A guard that
permits when it does not understand the question is not a guard.

`tests/test_canon.py::test_never_exits_one` asserts the property directly, across malformed input,
valid denials, and valid allowances.

## Wiring

`hooks/hooks.json`, with `${CLAUDE_PLUGIN_ROOT}` resolving to the installed plugin directory:

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Edit|Write|NotebookEdit|MultiEdit",
        "hooks": [
          { "type": "command", "command": "python \"${CLAUDE_PLUGIN_ROOT}/hooks/protect_canon.py\"" }
        ]
      }
    ]
  }
}
```

## What is verified, and what is not

**Verified:** the hook denies every protected path, ignores unrelated files and non-writing tools,
resolves relative paths against `cwd`, and never exits 1. Twenty tests, run against the real script
through a real subprocess with real stdin.

**Not verified:** that Claude Code, with this plugin installed, actually refuses the edit and leaves
the file untouched on disk. That requires installing the plugin and attempting the edit.

Per FS-005, *parsing is not running* — and by the same token, unit-testing is not installing.
The claim stays open until someone tries it.

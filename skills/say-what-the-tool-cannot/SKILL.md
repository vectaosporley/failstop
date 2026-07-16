---
name: say-what-the-tool-cannot
description: When a tool call succeeded on paper but not in fact — exit 0 with the wrong answer, an empty result that should have had content, a flag silently ignored, a parameter quietly dropped — record it. Trigger the moment you think "huh, that's not what I asked for" and are about to work around it. Also trigger when a command that used to fail now works, and when you catch yourself about to retry something that already failed the same way.
---

# Say what the tool cannot say about itself

The hooks record every call automatically. They record the wrong thing, and they cannot help it.

A PostToolUse hook sees `tool_response` and asks: *did it error?* That question is answerable
without knowing anything, which is exactly why it is nearly useless. It is asked with no frame.

Measured, in one session:

- `proc_list(filter="python")` returned **all 237 processes**. Exit 0. Recorded: success.
- A command was passed a parameter the server did not have. It was **silently discarded**. No
  error. Recorded: success.
- A shell command that failed returned a *string* containing `Exit code: 1` instead of raising.
  Recorded: success. Fifty such failures in a row would be fifty recorded successes.

Every one of those is a failure only from inside the frame of what you wanted. The tool did
run. The command did execute. Nothing errored. **The tool cannot know it failed, because
failing requires a purpose, and the purpose was yours.**

That is not a gap to be closed by a cleverer hook. No hook can close it.

## The two things only you can say

**"This didn't do what I needed."**

```
python scripts/memory.py judge --command "<what you ran>" \
    --expected "<what you needed it to do>" \
    --got "<what it did instead>" \
    --fix "<what to do instead next time>"
```

`--expected` is the frame and it is required. Without it there is no verdict to record —
only an event, which the hooks already have.

**"This works now."**

```
python scripts/memory.py judge --command "<what you ran>" --expected "<...>" --worked
```

Not politeness — it is what lifts a block. A store that only ever hears about failures is a
blocklist, not a reputation, and a blocklist can only ever get more restrictive.

## When to reach for it

The tell is a small feeling, and it is easy to skip past:

> *"Huh. That's not what I asked for. Anyway, let me try..."*

That "anyway" is the moment. You just found something no automatic channel can find, and you
are about to spend it on a workaround and forget it. Working around a fault is pragmatism the
first time. The second time it is choosing not to know — and the choice is invisible, because
nothing anywhere records that you made it.

Reach for it when:

- exit 0 but the answer is wrong, empty, or missing what you asked for
- a flag, filter or parameter appears to have been ignored
- the tool "succeeded" and you are now writing a workaround for its output
- something that failed repeatedly now works (say so — that is the unlock)

## What it costs and what it buys

It costs one command. It buys: the next session — yours or someone else's — gets the fix
quoted back at them **before** they hit it, and a shape that fails the same way twice gets
refused instead of retried.

You are not filing a complaint. You are the only instrument that can see this. An instrument
that notices something and says nothing has, for every purpose that matters, not noticed it.

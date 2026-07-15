---
name: verify-before-claim
description: Before declaring work done, run it — do not conclude from a syntax check or a partial view. Trigger before saying "done", "fixed", "working", "ready", or reporting a result. Also trigger before quoting a number a tool produced, or claiming a tool is faulty. Prevents declaring success on the strength of parsing rather than running, testing the module instead of the entry point, and indicting a tool on a single reading channel.
---

# Verify before you claim

Three measured failures, one session:
- A CLI passed a syntax check and raised on its first real call. `Path(".").parent` is `Path(".")`.
- A generated `__init__.py` imported a symbol that no longer existed. Every module test passed;
  importing the package raised `ImportError`. No test imported the package.
- Five files looked truncated through one channel and were intact through another. A bug report
  was one step from being filed against the wrong tool.

## The three rules

**1. Parsing is not running.** A syntax check proves the code is well-formed, not that it works.
Run it — even once, even trivially — before saying it's done.

**2. Test the entry point, not only the module.** If you generated a package, import the package.
If you wrote a CLI, invoke the CLI. Unit-passing is not entry-point-working.

**3. A claim that indicts a tool needs a second channel.** If a tool looks broken, confirm the
evidence through a channel that tool did not produce. Reading the same lie twice is not evidence.
Corroboration is not repetition.

## Before you say "done"

- Did I *run* it, or only check that it parses?
- Did I test what a user actually calls, or only an internal piece?
- If I'm about to blame a tool: did I confirm through a different path?
- If I'm about to quote a number: did I check which source produced it and what it points at?

## The tell

"It should work now." *Should* is the word that precedes the bug. Run it and replace *should*
with *does* — or with the actual error, which is more useful than a guess.

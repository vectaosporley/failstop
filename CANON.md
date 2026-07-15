# Canon

The laws of this system. Numbered, minimal, each earned by a failure that was measured.

**This file is not modified at runtime.** Neither is the code that enforces it. A human edits
both, deliberately, outside an agent session. See FS-001.

Each law states what it forbids, why, which layer enforces it, and its tier.

| Tier | Meaning |
|---|---|
| `enforced` | A hook blocks it. There is nothing to remember. |
| `shadow` | Runs, denies nothing, records what it would have denied. |
| `proposed` | Evidence exists. No reproduction yet. Blocks nothing, ever, until it does. |

Automatic transitions may only **tighten**. Every loosening requires a human.

---

## FS-001 — The canon is not modified at runtime
**Tier:** `enforced` · **Enforced by:** `hooks/protect_canon.py` (PreToolUse)

**Forbids:** any agent-initiated write to `CANON.md`, to `hooks/`, or to `scripts/canon.py`.

**Why:** a system that can rewrite its own constraints will eventually relax them, and leave you
with the confidence of protection and none of the protection.

**Note:** protecting the law but not its enforcer is theater. The protected set includes the hook
that does the protecting. A human changes these by editing them outside an agent session.

---

## FS-002 — Automatic changes may only tighten
**Tier:** `proposed` · **Enforced by:** the learning loop (not built yet)

**Forbids:** any automated action that reduces enforcement — demoting a rule, raising a threshold,
deleting a law.

**Why:** erring toward blocking fails *stopped*. Erring toward permitting fails *wrong*. Only one
of those is recoverable.

---

## FS-003 — A claim that indicts a tool must be corroborated through a second channel
**Tier:** `proposed` · **Enforced by:** `hooks/post_write_check.py` (not built yet) + skill

**Forbids:** reporting a tool as faulty on the evidence of a single reading channel.

**Why, measured:** five files were edited and all five appeared truncated — each missing exactly
the bytes the edit had added, cut mid-word, with the original byte count preserved. Measured again
on the machine that owns the files: all five intact. The tool had written correctly every time.
The reading channel was stale. A bug report was one step from being filed against the wrong
component, with a reproduction attached.

**Corroboration is not repetition.** Reading the same lie twice is not evidence.

---

## FS-004 — Read the shape of the data before writing the parser
**Tier:** `proposed` · **Enforced by:** skill (advice; not mechanically enforceable)

**Forbids:** writing a parser against an assumed schema.

**Why, measured:** twice in one session. Once, a payload was nested one level deeper than assumed
and the function returned the wrapper's keys, looking plausible. Once, a log's success field was
not named what the surrounding code implied; a parser written by analogy would have reported
**0 successes out of 448** instead of 446.

---

## FS-005 — Parsing is not running
**Tier:** `proposed` · **Enforced by:** evaluator (not built yet) + skill

**Forbids:** declaring work complete on the strength of a syntax check.

**Why, measured:** a CLI passed `ast.parse` and raised on its first real invocation.
`Path(".").parent` returns `Path(".")`.

---

## FS-006 — Test the entry point, not only the module
**Tier:** `proposed` · **Enforced by:** skill

**Forbids:** concluding a package works because its modules import.

**Why, measured:** a generated `__init__.py` imported a symbol that no longer existed. Every
module-level test passed. Importing the package raised `ImportError`. No test imported the package.

---

## FS-007 — Do not repeat an attempt that has already failed
**Tier:** `proposed` · **Enforced by:** the reputation gate (not built yet)

**Forbids:** invoking a tool with a command shape that has already failed, without changing strategy.

**Why, measured:** the same failing invocation was retried three times before the approach changed.
The tool's own failure log already contained the answer.

---

## FS-008 — Memory is written by code, not by remembering
**Tier:** `proposed` · **Enforced by:** PostToolUse and SessionEnd hooks (not built yet)

**Forbids:** relying on the agent to record what happened.

**Why, measured:** a persistent memory system held **8 failures and 0 successes after 29 days**.
The read path was a skill. The write path did not exist. A reputation built only from failures is
a blocklist: it can say *distrust this*, never *trust this*.

---

## FS-009 — A rule without a reproduction is a proposal, not a law
**Tier:** `enforced` (by this document) · **Enforced by:** the learning loop's gates

**Forbids:** promoting a rule to `enforced` without a test that fails before the fix and passes
after, corroborated per FS-003.

**Why, measured:** see FS-011. A rule generated from a documented, reproducible failure would have
been permanent, unquestioned — and false.

---

## FS-010 — A blocklist that names what it protects is the disclosure
**Tier:** `enforced` · **Enforced by:** `scripts/check_leak.py` + `tests/test_check_leak.py`

**Forbids:** committing project-specific terms into the guard that keeps them out.

**Why, measured:** the first version of the boundary guard shipped a denylist containing the exact
identifiers, glyphs and project names it existed to exclude. It reported the tree clean, because it
excluded itself from the scan.

---

## FS-011 — WITHDRAWN: block edits above 30 KB
**Tier:** `proposed` · **Status: must never be promoted.** Kept as a fixture.

**The claim:** the Edit tool silently truncates files above ~30 KB and pads with null bytes.

**The test:** five files — 1 KB, 20 KB, 28 KB, 40 KB, 60 KB — edited and measured.
Every one appeared corrupted. Every one was intact. See FS-003.

**Why it is kept:** this is the rule the learning loop would have written, from a documented
failure, with a reproduction that passed. It is the reason FS-009 exists. A test asserts it never
reaches `enforced`.

---

## FS-012 — A guard fails in the direction that is recoverable
**Tier:** `enforced` · **Enforced by:** each hook's error handling + tests

**Requires:** the canon guard (protect_canon) fails **closed** — confusion denies. The reputation
gate fails **open** — confusion allows.

**Why:** a false block of the canon is a recoverable annoyance; a false block of ordinary work
stalls the agent. So each guard errs toward the outcome you can walk back. This is FS-002 applied
per-hook: tighten where a mistake is cheap, loosen where a mistake is expensive.

**Tested:** `test_canon::test_never_exits_one` (fail closed) and
`test_reputation::test_gate_fails_open_on_bad_input` (fail open).

---

## How a law changes

1. A human edits this file, outside an agent session.
2. The hash changes. `scripts/canon.py verify` reports drift.
3. A human runs `scripts/canon.py lock` to accept it.

The evaluator may measure compliance and shout. It may not edit this file.

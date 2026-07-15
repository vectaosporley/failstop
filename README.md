# Failstop

**Fail-stop semantics for coding agents.**

A *fail-stop* process halts rather than producing an incorrect result. Failstop brings that
property to coding agents: when the agent is about to do something it is known to get wrong,
the action does not happen.

Not a warning. Not a reminder. The action does not happen.

---

## The problem

Coding agents fail in a small number of predictable, repeatable ways. Most tooling responds by
*telling the agent to be careful* — a skill, a rule in a config file, a line in a system prompt.

That is advice. Advice depends on the agent remembering it at the exact moment it matters,
which is the moment the agent is least likely to remember anything.

**A skill is advice. A hook is law.**

A skill that says "check the file size before editing" relies on recall. A `PreToolUse` hook that
rejects the edit does not. There is nothing to remember.

---

## The seven failure modes

Each of these was observed and measured, not imagined. Every one was produced by the author's own
agent sessions, including the session that wrote this README. Where a claim could not be reproduced,
it was removed — see #1, which is what remained after the original claim failed its own test.

### 1. The instrument you verify with is part of the system
The most dangerous failure is not a wrong action. It is a wrong *measurement* that looks like proof.

An earlier draft of this file asserted that the Edit tool silently truncates files above 30 KB.
The claim came from a note, not from an experiment. Before publishing it, we ran one: five files
(1 KB, 20 KB, 28 KB, 40 KB, 60 KB), each edited, each measured.

All five appeared corrupted. Each had lost exactly the number of bytes the edit had added, cut
mid-word off the tail, with the original byte count preserved — the most convincing kind of damage,
because the file size still looks right.

Then we measured the same five files through a second channel, on the machine that owns them.
**All five were intact.** The tool had written correctly every time. The reading channel was
serving a stale view: new head, old length, truncated tail.

The bug report would have been filed against the wrong component, with a reproduction attached.

The rule this yields is more useful than the claim it replaced: **a result that indicts a tool must
be confirmed through a channel that tool did not write through.** Corroboration is not repetition.

### 2. Assuming a data shape instead of reading it
A parser was written against an assumed JSON schema. The real payload was nested one level deeper.
The function returned the wrapper's keys and looked plausible.

Same session, second occurrence: a log's success field was not named what the surrounding code
suggested. A parser written by analogy would have reported **0 successes out of 448** instead of 446.

### 3. Declaring done without executing
A CLI passed a syntax check and crashed on its first real invocation. `Path(".").parent` returns
`Path(".")`, so a path computation raised on the first call. Parsing is not running.

### 4. Testing the module, not the entry point
Generated package files imported a symbol that no longer existed. Every module-level test passed.
Importing the package raised `ImportError`. The tests never imported the package.

### 5. Trusting a tool without checking what it points at
A status tool reported a count from a stale project root. The number was repeated as fact four
times before anyone checked which directory the tool was reading.

### 6. Retrying the approach that just failed
A shell tool hung on an entire class of command. It was retried, identically, three times before
the strategy changed. The tool's own failure log already contained the answer.

### 7. Memory that is never written
A persistent memory system was audited after several months of use. It held **8 recorded failures
and 0 recorded successes**, with no writes for 29 days.

The read path was a skill: *"load memory at session start."* The write path did not exist.
A reputation built only from failures is a blocklist, not a reputation — it can say
*distrust this*, never *trust this*.

---

## Architecture

Four layers, one direction of flow.

```
canon      immutable at runtime. Only a human edits it.
hooks      enforce the canon. Deterministic. Cannot be talked out of it.
evaluator  measures compliance. Writes to memory. Never edits the canon.
memory     accumulates. Proposes changes to the canon. Never applies them.
rollback   undoes what should not have happened.
```

**Learning flows up. Authority does not flow down.**

If the layer that enforces the rules can rewrite the rules, it will eventually relax them — and
leave you with the confidence of protection and none of the protection. The asymmetry is the
safety property. It is not an implementation detail.

The memory proposes: *this hook fired 40 times and 38 were false positives.*
A human disposes.

---

## Status

**0.1.0 — working, verified end-to-end.** 122 tests on Windows (Python 3.11).

Five hooks enforce the canon, check every write's integrity, gate repeated failures, snapshot for
rollback, and record every outcome to memory. A learning loop can propose rules but never enforce
one without a human (the ratchet). An agent forge turns repeated procedures into tested scripts.

Verified in a live Claude Code session: an edit to the canon was denied citing FS-001; a subtle
invalid-JSON write was blocked; a syntactically-valid logic bug was correctly *not* flagged —
failstop guards structural integrity, not semantics. That boundary is deliberate and honest.

What it does not do: catch logic bugs, run your tests, or replace review. It makes the *known,
structural* failure modes impossible, so the agent's judgment is free to focus on the rest.

---

## The boundary guard

This repository contains no code copied from any private project. That constraint is enforced,
not promised:

```bash
python scripts/check_leak.py --patterns ~/.failstop/patterns.txt --require-patterns
python scripts/check_leak.py --self-test
```

The guard carries only **generic** patterns — machine paths, session paths, personal emails,
credential shapes. Project-specific terms live in a local pattern file that is never committed,
because a blocklist that names what it protects *is* the disclosure.

The first version of this script got that wrong: it shipped a denylist containing the exact
identifiers, glyphs and project names it existed to keep out, and reported the tree clean because
it excluded itself from the scan. That is now fixed — the guard scans itself, loads private terms
from outside the repo, refuses to pass under `--require-patterns` if that list is missing, and
`--redact` prints labels without echoing the matched text into a public CI log.

It runs as a pre-commit hook and in CI. Nothing ships while it is red. A guard that has never
rejected anything has never been tested; this one has rejected its own author's mistakes twice.

---

## License

MIT

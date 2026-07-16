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

## The eight failure modes

Each of these was observed and measured, not imagined. Every one was produced by real agent
sessions building **VECTA**, an AI operating system — including the sessions that wrote this
README and this tool. That provenance matters more than it looks: these are not failures collected
from other people's bug trackers. They are the author's own, found while shipping something, and
every one of them cost time before it cost a rule.

Where a claim could not be reproduced, it was removed — see #1, which is what remained after the
original claim failed its own test.

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

**The mechanism, measured later.** The reading channel caches each file's *size* and reads its
*content* fresh. So after a write that changes a file's length, it returns:

| the file | you get | looks like |
| :-- | :-- | :-- |
| **grew** | new content **cut** at the old byte length | truncation, mid-word, no null bytes |
| **shrank** | new content **padded with NUL** to the old byte length | "corruption with null bytes" |

Two symptoms, one cause. Both had been reported as separate bugs in the write tool; neither was.
The 30 KB threshold never existed — the files that produced it were 7 KB, and the number came from
a session that happened to be editing large bundles and mistook *the files it was touching* for
*large files*.

There is a worse detail. The correct explanation was already written in this file — *new head, old
length, truncated tail* — while a rule installed elsewhere in the same project still blamed the
write tool, and that rule prescribed verifying the claim **through the channel that produced it**.
Two artifacts of one project contradicted each other for months. Nobody compared them. The failure
here needed no instrument at all; it needed someone to read both.

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

### 8. Building what already exists
The other seven are things an agent gets wrong. This one is something it does *well*, which is
why it is the most expensive.

Writing a mechanism from scratch feels like progress the whole way through. It compiles, the tests
you wrote pass, and nothing ever says *this already exists and is better*. Nothing will. Three, in
a single afternoon, by the agent that wrote this repository:

| built | already existed | cost of not asking |
| :-- | :-- | :-- |
| a hash-chained ledger with locks, fork detection and an anchor | **git** — a hash chain, already installed, with fifteen years of tooling | ~200 lines and their maintenance, forever |
| a novelty criterion for a reputation gate, designed from first principles | **circuit breakers** (Hystrix, resilience4j, 2012) | an entire redesign |
| a keyword classifier for how dangerous a UI action is | **Android permissions, iOS TCC, sudo, SELinux** | a model that classifies the *action* when every prior art classifies the *resource* |

The circuit breaker case is the sharpest. The counting approach was rejected because it stops
`npm test` on its third honest failure. Circuit breakers *do* count — and avoid that exact problem
by only wrapping calls where a failure means a failure: network calls, not informative commands.
**The bug was never the counter. It was the scope.** Ten minutes of reading would have replaced a
redesign.

The same session consulted prior art correctly exactly once — on a research question — and it
saved months. The difference was not knowledge. On the research question the agent doubted; on the
engineering questions it felt competent.

The tell is the word **small**: *"I'll build a small X that does Y."* It is never small, and that
is not the point. The point is that Y has a name, a Wikipedia page and three battle-tested
implementations you did not look for — and **naming the problem is what finds them.** Not naming it
is how you end up naming your solution instead.

The cost is not the hours. The code you wrote instead has no community, no documentation, no other
users and nobody to report its bugs. Every one will be found by the person you handed it to, one at
a time. You did not save time; you moved it onto someone else in a worse currency.

This is also the failure mode with no hook. A `PreToolUse` hook cannot know that the file you are
about to write is a worse `git`. It is a skill — `search-before-building` — and skills are advice,
which this README opens by calling weak. That is the honest boundary: **some failures can be made
impossible, and some can only be made embarrassing.** This one is in the second group, and putting
it in writing is the only enforcement available.

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

**0.2.0 — working, verified end-to-end.** 200+ tests on Windows (Python 3.11), the full suite
green. (The exact count is whatever `pytest` reports — pinning a precise number in prose only
teaches the prose to lie the next time a test is added, which is failure mode #1 in miniature.)

Six hooks enforce the canon, check every write's integrity, gate proven loops, snapshot for
rollback, record every outcome to memory, and hand back what was learned when a session starts or
compacts. A hash-chained ledger records every block and every override, so the past cannot be
rewritten in silence. A learning loop can propose rules but never enforce one without a human
(the ratchet). An agent forge turns repeated procedures into tested scripts.

Verified in a live Claude Code session: an edit to the canon was denied citing FS-001; a subtle
invalid-JSON write was blocked; a syntactically-valid logic bug was correctly *not* flagged —
failstop guards structural integrity, not semantics. That boundary is deliberate and honest.

### The gate does not count

The reputation gate blocks a command shape when its newest failure repeats an error it already
produced since it last worked. Not after N attempts. **There is no attempt limit.**

Two earlier versions counted, and both were wrong. The first blocked anything that had failed N
times and never succeeded — which meant a command that had *ever* worked once was immune forever.
Most commands work once, so the gate was nearly inert while looking perfectly healthy; its tests
only exercised shapes that had never succeeded, the single case where the bug cannot appear.

The second counted failures since the last success. That stops `npm test` on its third honest
failure — precisely when a fix cycle needs it most.

The count was always standing in for a question it could not ask: *is this attempt learning
anything?* Ask that instead. Ten failures with ten different errors is a search, and it is left
alone. Two identical failures is a circle, and the second one proved it. The limit stops being
configured and becomes emergent.

This is FS-007 read literally — *do not repeat a failed attempt* — where repeating means same
input **and** same output. If the output changed, you did not repeat. You advanced.

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

---

## Credits

Created by **Rafael Porley**.

Built while making **VECTA**, an AI operating system in development. Every failure mode in this
README was found there first, at its own cost. Failstop is what was left over once each one had
been made impossible instead of merely discouraged.

## License

MIT

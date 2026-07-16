# Changelog

## [0.2.0] — unreleased

The reputation gate did not work. It had never worked. Fixing it took the rest of this release
with it.

### Fixed — the gate was inert, and its tests could not have caught it

`check()` decided from lifetime totals: `fail >= N and ok == 0`. Two integers cannot encode
order, and reputation is entirely about order. That one line was wrong in both directions at once:

- **Too loose.** `ok == 0` is false for anything that ever succeeded, and almost everything
  succeeds once. A shape that worked in January and had failed identically every day since was
  waved through forever. In practice the gate blocked nearly nothing while looking healthy.
- **Too tight.** A shape that never succeeded was condemned permanently — and since the block
  stopped the command from running, it could never produce the success that would clear it. The
  evidence that would exonerate it was forbidden by the sentence.

The existing tests only exercised shapes that had never succeeded: the single case where the bug
cannot appear. Everything was green for months.

### Changed — the gate does not count attempts

There is no threshold. A shape is blocked when its newest failure repeats an error it already
produced since it last worked. Ten failures with ten different errors is a search and is left
alone; two identical failures is a circle, and the second one proved it.

A fixed count was tried first and rejected: it stops `npm test` on its third honest failure,
exactly when a fix cycle needs it. The number was standing in for a question it could not ask —
*is this attempt learning anything?* The limit is now emergent rather than configured.

- `memory.py` now records **what the tool said**, not only that it spoke. The verdict compares
  error signatures; a failure with no captured error can never prove a loop, so it never blocks.
- Errors normalize timidly (clocks, pids, addresses) while command shapes normalize boldly. In an
  error the details *are* the information: collapsing `3 tests failed` and `2 tests failed` to the
  same signature would block the fix cycle this rule exists to protect.
- Ordering uses a monotonic sequence, never a timestamp — several records land inside one coarse
  Windows clock tick.
- `clear` releases a shape whose root cause was fixed. The block is self-sealing without it.

### Added
- `ledger` — append-only, hash-chained, tamper-**evident** record. Both parties write to it: the
  agent's reports and clears, the human's overrides. Distinguishes an **ALTERED** chain from a
  **FORKED** one (two writers racing) and from a **CORRUPT** line (cause unknown) — because
  accusing a race of forgery is how a guard loses the credibility it needs on the day it is right.
  An anchor catches the full rewrite that hashes alone cannot.
- `session_start` hook — hands back what was learned when a session starts, resumes, or compacts.
  Compaction is the case it exists for: the agent has just lost the middle of its own session and
  is about to repeat what it already learned. Says nothing when it has nothing to say.
- `memory.py judge` — the agent's verdict, for the failures no hook can see: exit 0 with the wrong
  answer, a flag silently ignored, a parameter quietly dropped. Requires `--expected`: the frame.
  Without a declared purpose there is no verdict to record, only an event.
- `say-what-the-tool-cannot` skill — teaches that channel. A channel nobody is told about is a
  channel nobody uses, which was this one's exact condition.

### Fixed — the protected set named the law but not four of its enforcers
`reputation_gate.py`, `memory.py`, `ledger.py` and `snapshot_before_write.py` were editable from
an agent session. Making `memory.check()` always answer *trusted* disables FS-007 more quietly
than breaking the gate: the gate keeps running and keeps passing its own tests. Nothing was
outside the list by decision — it was outside by inattention, and the list looked complete.

### Fixed
- `canon.check()` returns a verdict and prints nothing; `canon.verify()` is the CLI that prints.
  The old function did both, so a hook whose stdout **is** its payload had the chatter injected
  into the model's context — and, expecting a verdict object, got an exit code instead.
- Messages no longer say `python3`, which does not exist on Windows.

### Verified
- 200+ tests, Windows (Python 3.11), full suite green.
- The ledger detects an edited entry, a deleted one, a reordering, and a forged hash; it reports a
  concurrent write as a fork rather than tampering; the anchor catches a full-chain rewrite that
  `verify()` correctly calls intact.

## [0.1.0] — unreleased

First working release. Fail-stop semantics for coding agents, verified end-to-end on Windows
with Claude Code 2.1.79.

### Hooks
- `protect_canon` — the canon and enforcement code cannot be edited from an agent session (FS-001).
- `post_write_check` — every file write is re-read and validated in the same call; corrupt content
  is surfaced immediately, a stale read is reported as unverifiable rather than corrupt (FS-003, FS-008).
- `reputation_gate` — a command shape that has failed N times and never succeeded is denied,
  citing the recorded fix (FS-007).
- `snapshot_before_write` — every mutation is snapshotted for rollback.
- `record_outcome` — every tool outcome is written to memory from code, not from the agent
  remembering to (FS-008).

### Scripts
- `check_leak` — boundary guard; ships only generic patterns, loads project terms from outside the repo.
- `canon` — hash, lock, verify the canon.
- `memory` — tool reputation store; records successes and failures; atomic writes; corruption quarantine.
- `rollback` — bounded snapshot/undo.
- `evaluator` — measures compliance, proposes rules, never edits the canon.
- `learn` — the learning loop with the ratchet; automatic transitions only tighten.
- `forge` — turns a repeated procedure into a tested deterministic script.

### Skills
- `probe-before-parse`, `verify-before-claim`, `check-what-the-tool-reads`.

### Verified
- 122 tests, Windows (Python 3.11).
- End-to-end: Claude Code denied a live edit to the canon; a subtle invalid-JSON write was blocked;
  a syntactically-valid logic bug was correctly NOT flagged (structural, not semantic scope).

# Changelog

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

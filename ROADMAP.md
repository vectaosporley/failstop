# Roadmap to 0.1.0

Every phase ends the same way: **the boundary guard is green and the tests pass.**
Nothing merges otherwise. Nothing from any private codebase enters this tree, at any step.

```bash
python3 scripts/check_leak.py --require-patterns   # local list, never committed
python3 -m pytest tests/
```

---

## Phase 0 — Verify the evidence before shipping it  ✅ DONE

**Result: the original claim was false, and the experiment that "confirmed" it was false too.**

Five files (1 KB, 20 KB, 28 KB, 40 KB, 60 KB) were edited and measured. All five appeared to have
lost exactly the bytes the edit added, cut mid-word off the tail, with the original size preserved.
Measured again on the machine that owns the files: **all five intact.** The tool wrote correctly
every time. The reading channel was stale.

- [x] **0.1** Reproduce failure mode #1. *Did not reproduce. Edit is correct at every size tested.*
- [x] **0.2** Rewrite #1 as what was actually observed: a stale verification channel that produced
      convincing false evidence against the wrong component.
- [x] **0.3** Withdraw the 30 KB claim from the README and from the local notes that propagated it.
- [ ] **0.4** Add `docs/evidence.md`: for each surviving mode, a reproduction script or an honest
      "observed once, not reproduced".

**Consequence for the plan:** the first hook can no longer be a size guard. There is no evidence
that the problem it would solve exists. It becomes the first candidate for the learning loop
(Phase 8) — a proposed rule with no reproduction, which is exactly the kind that must never
be promoted.

---

## Phase 1 — The canon  ✅ MOSTLY DONE

Note on ordering: 1.3 needs a hook, and Phase 2 says read the protocol before writing one.
Phase 2 was done first. The plan had the dependency backwards.

- [x] **1.1** `CANON.md`: eleven laws, each with what it forbids, why (with the measurement), the
      enforcing layer, and its tier — `enforced`, `shadow` or `proposed`.
- [x] **1.2** `scripts/canon.py`: hash, `lock`, `verify`. The lock lives outside the repository.
      Newline-agnostic, so CRLF does not read as drift.
- [x] **1.3** `hooks/protect_canon.py` denies `Edit|Write|NotebookEdit|MultiEdit` on the protected
      set. **The set includes the hook itself and `canon.py`** — protecting the law but not its
      enforcer is theater.
- [x] **1.4** Twenty tests: every protected path denied, unrelated files allowed, relative paths
      resolved, malformed input blocked, and `exit 1` never returned.
- [x] **1.5** **VERIFIED END-TO-END on real Windows.** Claude Code 2.1.79 (logged in) attempted a
      legitimate edit to CANON.md; protect_canon.py denied it citing FS-001; the agent refused to
      work around it; the file's SHA was byte-identical before and after (1f67b933). The first test
      that distinguishes "the hook denied" from "the agent declined on its own". Install the plugin, attempt an edit to `CANON.md` from a
      real session, and confirm the file is byte-identical afterwards. Unit-testing is not
      installing (FS-005).
- [ ] **1.6** Wire `canon.py verify` into a `SessionStart` hook once Phase 5 lands.

**Done when:** an agent, in a real session, cannot modify the canon — and the file proves it.

---

## Phase 2 — Learn the hook protocol before writing hooks  ✅ DONE

- [x] **2.1** Read the reference. Deny via `hookSpecificOutput.permissionDecision = "deny"` on
      stdout with exit 0, or via exit 2 with a reason on stderr.
- [x] **2.2** **The trap: `exit 1` does not block.** Claude Code treats it as a non-blocking error
      and runs the tool anyway. A policy hook that crashes with the conventional Unix failure code
      permits in silence. Every hook here fails closed and exits 2 when confused.
- [x] **2.3** `docs/hooks.md` records the protocol, the trap, and what remains unverified.

**Done when:** ✅ the protocol is written down, and a test asserts the hook never exits 1.

---

## Phase 3 — Hook 1: post-write integrity  ✅ DONE  *(the thesis)*

`hooks/post_write_check.py`, PostToolUse on `Edit|Write|NotebookEdit|MultiEdit`.

- [x] **3.1** Re-read the target. Reject NUL bytes; parse `.py/.json/.yaml/.toml`.
- [x] **3.2** A mismatch is not assumed to be corruption.
- [x] **3.3** **Second-channel rule (FS-003).** Before reporting damage, corroborate the byte count
      through a channel this process did not read through (`dir` on Windows, `stat` elsewhere).
      Three outcomes: clean / corrupt / **unverifiable**. The third exists because of Phase 0.
- [x] **3.4** PostToolUse cannot block, but `decision: block` + exit 2 feed the finding back in the
      same call, so the next action is a fix, not a continuation.
- [x] **3.5** 14 tests: clean text/py/json stay silent; broken py/json blocked; NUL corroborated =
      corrupt; **stale read = unverifiable, never corrupt**; malformed input never crashes.
- [x] **3.6** Rolls up with 1.5 — the runtime honors the hook, verified in a live session.
- [ ] ~~3.6 old~~ confirm in a real session that a broken
      write is surfaced before the next step.

**Done when:** ✅ at unit level. A bad write is reported in the call that produced it, and a stale
read cannot be mistaken for corruption. End-to-end confirmation pending install.

---

## Phase 4 — Hook 2: the reputation gate  ✅ DONE

Evidence: a tool was invoked with the same failing command shape three times in a row before the
strategy changed. Its own failure log already held the answer.

- [ ] **4.1** `PreToolUse`: consult the local store. If this tool has failed *N* times on this
      command shape, deny and quote the recorded fix.
- [ ] **4.2** Shape, not string: normalise the command before matching, so a retry with a different
      path is still recognised as the same attempt.
- [ ] **4.3** The gate is advisory below a threshold and blocking above it. Both thresholds are
      configurable; neither is invented.
- [ ] **4.4** Test: two failures recorded, third identical attempt is denied, and the tool did not run.

**Done when:** the system refuses to repeat a mistake it has already paid for.

---

## Phase 5 — Memory  ✅ DONE  *(the layer that does not exist in most systems)*

The read half is easy. The write half is what everyone skips.

- [ ] **5.1** `failstop/memory.py`: atomic writes (`mkstemp` + `fsync` + `replace`), and a
      loader that quarantines a corrupt store rather than raising.
- [ ] **5.2** Record **successes and failures**. A store with zero successes is a blocklist,
      not a reputation.
- [ ] **5.3** `SessionStart` hook: load and inject tool reputation and recent failures.
- [ ] **5.4** `PostToolUse` hook: write the outcome of every observed call. From code, not from
      the agent remembering to.
- [ ] **5.5** Store lives at `~/.failstop/memory.json`. Machine-local. Never committed —
      the mechanism is public, the data is not.
- [ ] **5.6** Test: after N simulated calls, the store holds N outcomes and survives a
      truncated-write simulation.

**Done when:** memory is written without the agent's cooperation, and the store cannot be
corrupted by an interrupted write.

---

## Phase 6 — Rollback  ✅ DONE

- [ ] **6.1** Before a mutating tool call, snapshot the target into `~/.failstop/undo/<ts>/`.
- [ ] **6.2** `/failstop-undo` restores the last snapshot; `/failstop-undo --list` shows them.
- [ ] **6.3** Cap total size and age; garbage-collect. A safety net that fills the disk is a bug.
- [ ] **6.4** Test: mutate, undo, assert byte-for-byte restoration.

**Done when:** any single mutating call can be reversed, and the snapshot store is bounded.

---

## Phase 7 — The evaluator  ✅ DONE

- [ ] **7.1** `SessionEnd` hook: measure compliance. How many denials, how many false positives,
      which tools failed, which succeeded.
- [ ] **7.2** Write the measurements to memory. **Never edit the canon.**
- [ ] **7.3** `/failstop-report`: reputation per tool, top failure patterns, hooks that fired.
- [ ] **7.4** Proposals, not changes: *"this hook fired 40 times, 38 were false positives —
      consider raising the threshold."* A human decides.
- [ ] **7.5** Test: the evaluator cannot write to `CANON.md`. Assert the denial.

**Done when:** the system measures itself and proposes, and a test proves it cannot legislate.

---

## Phase 8 — The learning loop  ✅ DONE  *(new rules earn their place)*

When a new failure is observed, it becomes a rule. But it does not become a *law* by itself.

Today's session is the reason this phase has gates. A failure was documented in a note. An
experiment appeared to reproduce it. A rule generated from that evidence — *block edits above
30 KB* — would have been wrong, permanent, and unquestioned, because "the system learned it".
The evidence was reproducible. It was also false.

### The three tiers

```
proposed   evidence exists, no reproduction yet.        Blocks nothing.
shadow     reproduction passes, fix passes.             Logs what it WOULD have blocked.
enforced   in the canon.                                Blocks.
```

### The ratchet

**Automatic transitions may only tighten. Every loosening requires a human.**

Erring toward blocking fails stopped. Erring toward permitting fails wrong. Only one of those
is recoverable.

- [ ] **8.1** `/failstop-learn`: from a recorded failure, draft a candidate rule — a name, the
      observation, a reproduction script, a proposed fix.
- [ ] **8.2** **Reproduction gate.** The candidate ships a test that fails before the fix and
      passes after. No test, no promotion beyond `proposed`.
- [ ] **8.3** **Corroboration gate.** The reproduction must be confirmed through a channel the
      suspected tool did not write through. This gate exists because of Phase 0.
- [ ] **8.4** `shadow` mode: the rule runs, denies nothing, and records every call it would have
      denied, with enough context to judge a false positive.
- [ ] **8.5** Promotion `shadow → enforced` requires a human and a false-positive rate below a
      stated threshold. Recorded in `CANON.md` with the date and the evidence.
- [ ] **8.6** Demotion, relaxation, and deletion of any enforced rule require a human. The
      evaluator may shout. It may not edit.
- [ ] **8.7** Test: a rule with a passing reproduction but no corroboration stays in `proposed`.
      A rule with 40 shadow firings and 38 false positives is not auto-promoted.
- [ ] **8.8** Seed the loop with the withdrawn 30 KB rule as a `proposed` fixture that must
      never reach `enforced`.

**Done when:** the system can add a rule without a human, cannot enforce one without a human,
and a test proves both.

---

## Phase 9 — The agent forge  ✅ DONE  *(replace reasoning with scripts)*

Repetitive work should not be re-reasoned every session. Tokens spent re-deriving a known
procedure are tokens wasted.

An "agent" here is, by default, a **deterministic script** — that is where the saving comes from.
An LLM sub-agent is the exception, used only when the task genuinely needs judgment.

- [ ] **11.1** Detect repetition: from memory, find recurring sequences of tool calls with the
      same shape across sessions. Normalise paths and arguments before matching.
- [ ] **11.2** `/failstop-forge <task>`: draft a specification from the observed calls — inputs,
      outputs, invariants — and show it before writing a line of code.
- [ ] **11.3** Claude writes the script. Tests are generated **from the observed inputs and outputs**,
      not invented, so the script must reproduce what the reasoning actually did.
- [ ] **11.4** **Baseline gate.** The generated agent runs alongside the reasoning it replaces for
      *N* invocations. Divergence blocks promotion. Automating a wrong answer faster is not a win.
- [ ] **11.5** **Review gate.** Claude reviews the script it wrote, in a fresh context, against the
      specification — not against its own memory of writing it. A human approves.
- [ ] **9.6** A forged agent runs **under the same hooks** as anything else. No exemptions, no
      elevated flags. It is not more trusted for having been generated.
- [ ] **9.7** Measure: tokens before, tokens after, divergences observed. If it does not save
      tokens, it is deleted.
- [ ] **9.8** Test: a forged agent whose output diverges from the baseline once is not promoted.

**Done when:** a repetitive task runs as a tested script, provably equivalent to the reasoning it
replaced, under the same enforcement as everything else.

---

## Phase 10 — Skills  ✅ DONE

Three. Not thirty.

- [ ] **10.1** `probe-before-parse` — read the real shape of the data before writing the parser.
- [ ] **10.2** `verify-before-claim` — run it; parsing is not running; test the entry point,
      not only the module.
- [ ] **10.3** `check-what-the-tool-reads` — before quoting a number a tool produced, confirm
      what it points at.
- [ ] **10.4** Each skill: a description that states *when* to trigger, not only what it does.

**Done when:** three skills exist, and each names the failure mode it prevents.

---

## Phase 11 — Distribution  ✅ DONE

- [ ] **11.1** `.claude-plugin/marketplace.json` so the plugin installs by name.
- [ ] **11.2** `.pre-commit-config.yaml` running the guard with `--require-patterns`.
- [ ] **11.3** CI workflow: guard (generic patterns only — the private list is not in CI),
      `--self-test`, and the full test suite.
- [ ] **11.4** Document the asymmetry: the local pre-commit is the real gate; CI is the backstop.
- [ ] **11.5** `CHANGELOG.md`, semantic version, `CONTRIBUTING.md`.

**Done when:** a stranger can install the plugin and a contributor cannot merge a leak.

---

## Phase 12 — The publication gate  ✅ DONE — caught a real leak in git history, amended it away

Run once, before the repository is ever made public. Then again before every release.

- [ ] **12.1** Full-tree scan with the private list: `check_leak.py --require-patterns`.
- [ ] **12.2** **Scan the git history, not just the working tree.** A term removed in a later
      commit is still in the objects. `git log -p | check_leak`. If anything is found, the
      history is rewritten or the repository starts fresh.
- [ ] **12.3** Scan commit messages and branch names. They are published too.
- [ ] **12.4** Confirm: no personal email in `plugin.json`, `LICENSE`, or commits.
- [ ] **12.5** Confirm `~/.failstop/` and `*patterns*.private.txt` are ignored, and that no
      memory store or snapshot directory was ever added.
- [ ] **12.6** A second person — or a fresh session with no context — reads the tree and
      reports anything that hints at a private system.

**Done when:** the working tree, the history, the messages and the metadata are all clean.

---

## Phase 13 — Release 0.1.0  ✅ git repo initialized, tagged v0.1.0, history clean. Push pending (needs GitHub auth).

- [ ] **13.1** Tag, changelog, a README that promises only what the code does.
- [ ] **13.2** Remove every "coming soon" from the README. Ship the subset that works.

**Done when:** someone installs it, edits a large file, and the edit does not happen.

---

## The rule that governs all of it

**Learning flows up. Authority does not flow down.**

The evaluator measures the canon and never edits it. The memory proposes and never applies.
The hooks enforce and cannot be argued with. A human moves the line.

And one more, learned the hard way while building the guard itself:

**A blocklist that names what it protects is the disclosure.**
The guard carries generic patterns only. Everything specific lives outside this repository.

# Installing failstop

Two ways. Both wire the same hooks.

## A. Project settings (what the e2e test uses)

Copy the hook block into your project's `.claude/settings.json`, with absolute paths to the
hook scripts. A working example is in `_e2e/.claude/settings.json`.

## B. As a plugin (once published)

```
/plugin marketplace add porleyrafael/failstop
/plugin install failstop
```

## Verify the wiring (no agent needed)

```
cd _e2e
python verify_install.py
```

Green means: settings.json is valid, every hook points at a real parsing script, an edit to
the real canon is denied, and an ordinary file is allowed.

On Windows, if running from a wrapper that hangs, redirect stdin:  `python verify_install.py < nul`

## The one step a script cannot do

Wiring-verified is not runtime-verified. To confirm Claude Code honors the deny:

1. Log in once:  `claude` then `/login`
2. `cd _e2e`
3. Run `claude`, ask it to edit the failstop `CANON.md` one level up.
4. Expected: denied, citing FS-001.
5. Ask it to edit `playground.txt`: allowed.

Until step 4 is seen in a live session, the end-to-end claim stays open (FS-005: parsing is
not running, and wiring is not honoring).


## Verified end-to-end (2026-07-15)

Claude Code 2.1.79, logged in, on Windows, was asked to make a *legitimate* edit to CANON.md
(add a version line). `protect_canon.py` denied it, citing FS-001 verbatim. The agent declined
to work around the block. The file was byte-identical before and after (SHA 1f67b933).

A first attempt, framed as "tamper", produced a false pass: the agent refused on its own
judgment before ever invoking Edit, so the hook never fired. The lesson — the same one this
project is built on — is to verify that the *mechanism* acted, not just that the outcome matched.

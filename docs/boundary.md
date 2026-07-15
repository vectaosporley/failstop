# The boundary

This repository is written from scratch. Nothing is copied from any private codebase.

"Copy and clean" fails, every time. What leaks is never the word you thought to search for.

## The guard carries no secrets

A blocklist that enumerates what it protects *is* the disclosure. So the guard splits in two:

- **Generic patterns** live in `scripts/check_leak.py`: machine paths, ephemeral session paths,
  personal emails, credential-shaped tokens. Nothing here reveals anything.
- **Project-specific patterns** live in a local file, never committed. Point the guard at it:

```bash
export FAILSTOP_PATTERNS=~/.failstop/patterns.txt
python scripts/check_leak.py --require-patterns
```

`--require-patterns` refuses to pass if that file is absent, so the guard cannot silently run
half-blind. `--redact` prints the label of each finding without echoing the matched text — safe
for a public CI log.

The guard scans itself. It does not get an exemption.

```bash
python scripts/check_leak.py --patterns <file> --require-patterns
python scripts/check_leak.py --self-test
python -m pytest tests/
```

A false positive is escaped with a trailing `# leak-ok`, visible in the diff so a human approves it.

**Nothing ships while the guard is red.**

---
name: probe-before-parse
description: Read the real shape of data before writing a parser for it. Trigger before writing any code that reads JSON, a log, an API response, a config file, or any structured data whose format you have not just inspected. Also trigger when about to quote a field name or a count from a data source. Prevents the failure mode where a parser is written against an assumed schema and returns plausible-but-wrong results.
---

# Probe before you parse

The failure this prevents was measured, twice in one session:
- A payload was nested one level deeper than assumed. The function returned the wrapper's keys
  and looked correct.
- A log's success field was not named what the surrounding code implied. A parser written by
  analogy would have reported **0 successes out of 448** instead of 446.

## The rule

**Look at the actual data before you write the code that reads it.** One real record beats any
assumption about the format.

## How

Before writing a parser:

1. Print or read **one real record** — the actual bytes, the actual keys, the actual nesting.
2. Note the exact field names. Not what they *should* be called — what they *are* called.
3. Note the shape: is it a list of dicts? a dict of dicts? nested how deep?
4. Write the parser against **that**, not against memory.

```bash
# JSON: what are the real top-level keys?
python3 -c "import json; d=json.load(open('file.json')); print(type(d).__name__, list(d)[:8])"

# JSONL: what does one line actually contain?
head -1 file.jsonl | python3 -c "import json,sys; print(list(json.loads(sys.stdin.read())))"

# An API/tool response: capture it once, inspect, then parse.
```

## Before quoting a number

If you are about to state a count, a rate, or a status that a tool produced: confirm the field
you are reading is the field you think it is. "exito" is not "ok". A wrapper's keys are not the
data's keys.

## The tell

If you find yourself writing `data["result"]["items"]` without having seen that structure in
this session, stop. You are parsing from memory. Probe first.

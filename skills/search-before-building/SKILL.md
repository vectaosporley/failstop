---
name: search-before-building
description: Before designing any mechanism, check whether it already exists. Trigger the moment you catch yourself about to write "I'll build a X that does Y" — a cache, a queue, a lock, a retry policy, a permission model, a log with integrity, a scheduler, a diff, a parser. Also trigger before inventing a name for a technique, before writing a second file of a "new" subsystem, and whenever a design feels satisfyingly original.
---

# Search before building

You are very good at building things. That is the problem.

Writing a mechanism from scratch feels like progress the entire time you are doing it. It
compiles, the tests you wrote pass, and at no point does anything say *this already exists and is
better*. Nothing will. The absence of that message is not evidence.

## Three, in one session

Measured, in a single afternoon, by the agent that wrote this skill:

**A hash-chained ledger.** ~200 lines: append-only entries, a lock, fork detection, an anchor
against full rewrite. **Git is a hash chain.** It was already installed. It has fifteen years of
tooling to inspect it, and a `git commit` per entry would have cost zero lines and zero
maintenance. The question *"does git already do this?"* was never asked.

**A reputation gate.** Invented a novelty criterion from first principles, after rejecting the
counting approach because it stops `npm test` on its third honest failure. **Circuit breakers**
(Hystrix, resilience4j) have solved this since 2012 — and they *do* count. Ten minutes of reading
would have revealed how they avoid the `npm test` problem: **they only wrap calls where a failure
means a failure.** Network calls, not informative commands. The bug was never the counter. It was
the scope. The whole redesign was unnecessary.

**A permission classifier.** Keyword matching to score how dangerous a UI action is. Android
permissions, iOS TCC, sudo, SELinux — the entire literature of OS permission models — and all of
them agree on something that was never considered: **they classify the resource and ask for
consent in context, not the action.** Not one was consulted.

The same session correctly consulted prior art exactly once, on a research question, and it saved
months. The difference was not knowledge. It was that on the research question the agent *doubted*,
and on the engineering questions it felt competent.

## The tell

> *"I'll build a small X that does Y."*

The word is **small**. It is never small, and that is not the point anyway — the point is that Y is
a problem so common it has a name, a Wikipedia page, and three battle-tested implementations you
did not look for.

Other tells, in rough order of danger:

- You are naming a technique. If you are naming it, you think it is new. Check.
- You are pleased with the design. Novelty and satisfaction feel identical from the inside.
- You are on file two of a "new" subsystem and have not typed a search query.
- You are about to write "from scratch", "our own", "a simple", "a minimal", or "lightweight".

## The check

Two questions, sixty seconds, before the first line:

1. **What is this called by people who already solved it?** Not "how would I build a thing that
   detects repeated failures" — *"what is the standard name for stopping repeated calls to a
   failing dependency?"* (Answer: circuit breaker.) Naming the problem finds the prior art. Not
   naming it is how you end up naming your solution instead.

2. **Is it already installed?** Git, sqlite, the OS keychain, the platform's permission system,
   the language's stdlib. The best dependency is the one already on the machine and maintained
   by someone else.

Then search. Then read for ten minutes. Then decide.

## When building anyway is right

This is not a rule against building. It is a rule against building **unknowingly**. Legitimate
reasons survive the search:

- the existing thing does not fit, **and you can say precisely how** after reading it
- the dependency costs more than the code (real, and rarer than it feels)
- you need to understand the mechanism, and the building is the point

All three require having looked. "I didn't think to check" is not on the list.

## Why it costs more than the hours

The code you wrote instead has no community, no documentation, no other users, and no one to
report its bugs. Every one of them will be found by the person you handed it to, one at a time,
in production. You did not save time. You moved it onto someone else, denominated in a worse
currency.

And each new mechanism opens holes that need patching, and patching them feels like progress too.
That loop has no natural end. The way out is not at the end of it.

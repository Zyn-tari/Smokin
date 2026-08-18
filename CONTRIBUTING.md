# Contributing

One person maintains this. **Issues get read in batches, roughly weekly, and there is no
SLA.** If something is broken and you need it fixed today, fork it — the licence lets you,
and a fork you control beats a maintainer who is asleep.

---

## The one rule that matters

**Every mechanism in here traces to a defect that actually happened**, on a real run, with an
artefact you could point at. The reaper exists because a worker was killed and nothing
noticed. The receipt/verdict split exists because an agent claimed done and was believed.
The invariants layer exists because certbot silently made a new vhost the default for
loopback HTTPS and served two neighbouring sites the wrong certificate, while every task
passed its own gate.

**A pull request that adds a mechanism must name the incident.** What was running, what went
wrong, how it surfaced. "This would be more robust" is a preference, and preferences do not
go in.

## What is genuinely wanted

**A runtime that does not work.** The whole design claim is that a runtime is a row in a JSON
file and the tick has no branch on any vendor. If that is false for the CLI you use, that is
the most useful bug report this project can receive. Include what `smokin doctor` says.

**A case where a receipt was believed and should not have been**, or where the reaper missed
a dead worker, or where a tick was not idempotent. Those three are the floor; anything that
breaks them is serious.

**Filesystem reality.** The design assumes `rename(2)` atomicity on one filesystem and
`flock` that works. WSL2, NFS, DrvFs, 9p and containers all have opinions. Measured reports
beat theory.

**Prose that overstates.** A number that no longer holds, a CONFIRMED that was never
exercised. Graded as defects, because that is what they are.

## What will be declined, and why

**Anything that crosses the boundary.** Smokin owns what actually **happens**. Grillin owns
what a plan **declares**. Smokin does not author plans, validate their structure, or tell you
your plan is badly shaped — that is Grillin's half, and `grillin/tests/test-config-contract.py`
feeds both tools the same config files and requires them to agree. If your change would make
Smokin an authoring tool, it is the wrong change.

**A daemon.** There is deliberately no resident orchestrator process. Every fact the tick
needs is a file in the plan directory, which is what makes compaction, `Ctrl-C`, an SSH drop
and a closed terminal all no-ops on the plan. A long-running process would be easier and
would give that up.

**Dependencies.** python3, stdlib, bash. `herdr` is optional and must stay optional.

**Trusting a lifecycle state.** An agent reported `idle` is not an agent that finished. On a
real machine `herdr agent list` reported two bare login shells as idle agents. Watch the
filesystem, never the screen.

## If you touch the tick

```bash
bash tests/run-tests.sh          # 31 checks; crash recovery, the emitter mutex, verify,
                                 # the delegation node, plan invariants, the hook
```

Every loud check needs a **silent control** beside it. A test proving your mechanism fires
is half a test; the other half proves it stays quiet when nothing is wrong. The suite is
mutation-proven — mechanisms are broken one at a time and each must fail only its own checks
— and there is a negative control asserting that a plan with no `_INVARIANTS.toml` ticks
exactly as it did before the feature existed.

`smokin verify` must remain **read-only**: it starts nothing, edits no `TASK.md`, spends no
model calls, and leaves nothing running. That property is why it is the part people can adopt
without committing to anything, and it is easy to break by accident.

## Licence

Tools are **PolyForm Noncommercial 1.0.0**; documents are **CC BY 4.0**. See [`LICENSE`](LICENSE)
and [`LICENSE-DOCS`](LICENSE-DOCS), and the README for the plain answer to "is my use
commercial?" — short version: if you are one person, it's free.

By opening a pull request you agree your contribution ships under those terms.

## Tone

Blunt is fine. Being wrong in public is normal here; the design document keeps its own
retracted claims visible on purpose. Certainty without evidence is the only thing that is
not welcome.

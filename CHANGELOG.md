# Changelog

## The policy, before the entries

**Do not update Smokin while a plan is running.**

A running plan has state on disk that the binary you are replacing wrote: receipts,
verdicts, dispatch records, invariant baselines, the standing rulings. Swapping the
tool underneath a tick is the one upgrade that can lose work, and nothing in the design
protects you from it — the whole point is that state survives the *process*, not that it
survives a change of schema.

```bash
smokin status <plan>     # 0 = complete, 3 = stuck. Either is safe to update on.
git pull                 # then update
```

Exit `1` means work is in flight. Wait for it, or `smokin reap <plan>` first and let the
reaper close the dispatches out properly.

`_RULINGS.toml` and `_INVARIANTS.toml` are read at every tick. If a version changes what
they accept, an in-flight plan halts loudly rather than running on a half-understood
config — which is the designed behaviour, and still not a thing you want mid-job.

---

## v1.0.0 — 2026-08-18

First public release. Everything below already existed; this is the point it got a number
so you can pin it.

**The tick** — reap, drain, gate, dispatch, render, then exit. No resident process; every
fact it needs is a file in the plan directory, so compaction, `Ctrl-C`, a dropped SSH
session and a closed terminal are all no-ops on the plan.

**`smokin verify`** — re-runs each task's own done-command and tells you which tasks are
*verified* rather than merely *claimed*. Starts nothing, edits no `TASK.md`, spends no
model calls. **Works on a lone `TASK.md`** — no plan directory required.

**The hook** — `templates/verify-on-stop.sh` fires when an agent says it has finished and
re-runs the gate itself. Never blocks, always exits 0.

**The delegation node** — `_RULINGS.toml`, opt-in. The frontier advances on rulings, not
receipts. An unreachable judge halts, and that is not configurable.

**Plan-level invariants** — `_INVARIANTS.toml`, opt-in. Readings that must not move while
the plan runs. A break is a halt, not a warning.

31 checks in `tests/run-tests.sh`, including `kill -9` recovery from a separate later
process.

### Known limits, stated rather than discovered

- A baseline taken late records the damage as normal, a probe is trusted to be read-only,
  and an unchanged reading is not a *correct* reading — only the same one.
- One worker, one machine: `verify` is the part worth having. The fleet half assumes you
  actually have a fleet.
- `herdr` is optional. Without it, panes are unavailable and everything else works.

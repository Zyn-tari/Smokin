# The three experiments the design was blocked on

Run 2026-08-05, inside herdr, on this machine. Every one is CONFIRMED — exercised, with the
command shown, per Grillin's principle 7.

The design document that preceded this
(`SMOKIN-DESIGN.md`) listed Q1 and Q2 as open questions and said *"this is a ten-minute experiment
and it is load-bearing."* It was. One of the two answers reverses a conclusion in that document.

---

## Q2 · Does `herdr pane run` leave a wrapper's EXIT trap intact?

**YES — CONFIRMED.**

```bash
herdr pane split --current --direction right --cwd "$L" --no-focus   # -> w4:pF
herdr pane run w4:pF "bash wrapper.sh sleep 2"
```

The wrapper forks the child, `wait`s, and traps EXIT. Result:

```json
{"trap":"fired","rc":0,"sig":"EXIT"}
```

Every pane-dispatch design reviewed assumed this and nobody had run it. It holds. **The wrapper is
a real floor for pane dispatch**, not an aspiration.

---

## Q2b · Does the trap fire when the pane is *closed* out from under the child?

**YES, via `SIGHUP` — CONFIRMED.** This was not asked and it matters more than Q2.

```bash
herdr pane run w4:pF "bash wrapper.sh sleep 60"
herdr pane close w4:pF        # rc=0
```

```json
{"trap":"fired","rc":0,"sig":"HUP"}
```

`herdr pane close` sends **SIGHUP, not SIGKILL**. So a human closing a pane, or an orchestrator
tidying one up, is a *recoverable event*: the worker gets a chance to say what happened.

**Design consequence.** The wrapper must trap `HUP`, `TERM` and `INT` as well as `EXIT`, and the
receipt must carry which signal ended it — `terminal: "hangup"` is a different fact from
`terminal: "crashed"`, and a pane the human closed on purpose should not read as a crash.

---

## Q1 · Does a Codewhale pane ever emit?

**YES — CONFIRMED. This reverses the design document.**

`SMOKIN-DESIGN.md` §5d and failure mode 3 concluded that Codewhale panes have *no* emission path:
a trapping wrapper around the TUI "logged `WRAPPER_START` and then never emitted", so the wrapper
floor was marked unproven and Codewhale panes were said to degrade permanently to reaper timeouts.

```bash
herdr pane split --current --direction down --cwd "$W" --no-focus   # -> w4:pG
herdr pane run w4:pG "bash wrapper.sh codewhale -C $W --skip-onboarding"
# TUI confirmed alive:  "❯ Write a task or use /."  · idle · v0.9.3
# receipt while TUI alive: False        <-- correct, it has not finished
herdr pane close w4:pG
```

```json
{"trap":"fired","rc":129,"sig":"EXIT"}
```

`rc=129` is `128 + 1` — the child was terminated by SIGHUP, `wait` returned, and the wrapper's own
EXIT trap fired normally.

### Why the earlier probe was wrong

It never closed the pane. It launched an **interactive TUI** and waited for the budget to expire.
A TUI sitting at its prompt has not finished, so of course nothing emitted — the probe measured
*"an idle TUI does not exit"* and reported it as *"Codewhale cannot emit."*

That is the instrument failure Grillin's `OPERATING-THE-PLAN.md` §5 is about, appearing in the
document that argued for it: every individual observation was true and the conclusion was wrong.

**Consequence: §5d's "honest boundary" and failure mode 3 are retracted.** The wrapper floor holds
for Codewhale panes. Q1 is closed, and the per-runtime emission preflight it demanded is still worth
shipping — as `smokin doctor` — but it is no longer a blocker.

---

## Bonus · Can a pane be closed on purpose?

**YES — `herdr pane close <pane_id>`, rc=0**, and per Q2b it hangs up rather than killing. Both
experiment panes (`w4:pF`, `w4:pG`) were created and closed by this run; `herdr pane list` afterwards
showed only the pre-existing panes.

This is what makes `smokin reap --close` safe: reaping a pane task can tidy the pane and still get a
receipt out of the worker on the way down.

---

## What these three answers changed in the design

| Was | Now |
|---|---|
| Q1 open; Codewhale panes "unproven", degrade to reaper timeout | closed; the wrapper emits. §5d boundary and failure mode 3 retracted |
| Q2 open; "every design assumed it, nobody ran it" | closed; the trap survives `herdr pane run` |
| pane close: undesigned | SIGHUP, recoverable, and now a first-class terminal state |
| wrapper traps `EXIT` | wrapper traps `EXIT HUP TERM INT` and records which one |

# `smokin verify`, and three declaration fixes

**Date:** 2026-08-12
**Status:** approved design, not implemented
**Touches:** `smokin` (bin/smokin, README.md), `grillin` (scripts/validate-plan.py,
scripts/check-drift.py, templates, SCALING.json)

---

## 1 · Why

Two QA trials were run in which a developer who had never seen these tools was given the published
pages and a small real job. Both got the job done. **Neither used Smokin.**

The second trial was designed specifically to need it — three disjoint scripts, three parallelisable
tasks, no contended files. The user still executed the whole plan with the one agent he already had,
and ran `smokin doctor` only. His words:

> *"Didn't get real signal on Smokin — it's built for multiple agents running at once and this was
> one worker."*

He was right, and that is the defect. **The one idea in Smokin that would have helped him needs no
fleet at all:** the worker's claim is not evidence until something else re-runs the check. Both users
performed that habit by hand — Dana ran `pytest` herself, Marcus ran the suite "independently of
helper's claim" — and both skipped the tool that exists to make it mechanical, because it was welded
to dispatch, panes and a reaper they did not need.

The same trials produced two smaller defects, both of the same family: **a declaration reported as
a fact.**

- The gate printed `['T5'] staffed as adversarial, owned by nobody else in the plan` for a plan in
  which one agent did the work *and* its review. It checked a name and reported independence.
- The user told his agent "1–3 tasks, short path" and got 5 with rollback plans and a baseline task.
  The size bands are prose no plan-writing agent is obliged to obey.

## 2 · Scope

**In:** a no-dispatch `smokin verify`; a human-first README; honest wording on the adversary check
plus real session enforcement in Smokin; a declared, enforced size band.

**Build order.** Parts A and B are Smokin and stand alone — A is the whole reason this spec exists
and should ship first, B immediately after since a command nobody can find is a command nobody runs.
Parts C and D are Grillin and are independent of both; C's Smokin half (5.2) depends on nothing in A.
Any of the four can be reverted without breaking the others.

**Out, deliberately:** any mechanism against gate-gaming. In trial 2 the helper read
`validate-plan.py`'s source in order to satisfy it. No mechanism can stop an agent reading a file it
can reach, and building one would be theatre. Not documented as an anti-pattern either — that was
considered and declined.

---

## 3 · Part A — `smokin verify`

### 3.1 Contract

```
smokin verify <plan> [--task <ID>]
```

For every task (or the one named), run **that task's own done-command**, from the plan root, and
record what happened. Nothing else.

| It writes | It never writes |
|---|---|
| `tasks/<ID>/VERDICT.json` — identical schema to the one `tick` writes | `tasks/<ID>/TASK.md` — see 3.2 |
| `STATUS.json` | `RECEIPT.json` |
| `PROGRESS.md` | anything under `.smokin/dispatch/`, `.smokin/spool/` |

It does **not**: start a process, create or close a pane, drain the spool, reap, or invoke a judge.

It **does** take the tick lock (`.smokin/tick.lock`), so it cannot race a real `tick`. Losing the
lock prints the same message `tick` prints and exits 0.

### 3.2 It never edits `TASK.md`

`tick` rewrites `**Status:**` as it goes. `verify` does not. At n=1 the human is the author of that
file and probably has it open; silent edits to someone's own prose are hostile. The rendered picture
stays correct because `Plan.state()` already derives from the verdict before it looks at anything
else — the status line is not load-bearing.

**Consequence to accept:** after `verify`, `TASK.md` may say `NOT STARTED` while `PROGRESS.md` says
`● verified`. That is not drift; the verdict is the stronger statement and `PROGRESS.md` is derived
from it. `PROGRESS.md`'s legend must say so in one line.

### 3.3 Missing receipts are normal

At n=1 nobody emits a receipt — the human did the work. `verify` ignores receipts entirely and runs
the done-command regardless of whether one exists. A plan with zero `RECEIPT.json` files must verify
cleanly. **This is the difference between `verify` working on day one and only working after a
Smokin-managed run.**

### 3.4 It does not invoke judges

If `_RULINGS.toml` is active, `verify` renders affected tasks as `◍ awaiting a ruling` and prints
one line: *"N task(s) need a ruling; `smokin tick` is what asks."* Judgement costs real model calls
and a free mechanical command must not quietly spend money.

### 3.5 Exit codes

| | |
|---|---|
| `0` | every task verified |
| `1` | at least one task not verified (refuted, or awaiting a ruling) |
| `2` | not a plan directory |
| `4` | a halt is in force (`.smokin/HALT.json`), same as `tick` |

### 3.6 Acceptance tests (added to `tests/run-tests.sh`)

1. A plan with **no receipts and no dispatch records** verifies: exit 0, one `VERDICT.json` per task,
   `PROGRESS.md` rendered.
2. `TASK.md` files are **byte-identical** before and after — asserted by hash.
3. A task whose done-command exits non-zero is `✗ refuted`, and `verify` exits 1.
4. `verify` starts **no process**: no new dispatch records, and the process count for the demo
   runtime is unchanged.
5. `verify` then `tick` on the same plan: `tick` leaves the existing `VERDICT.json` files alone
   (it only gates tasks that have no verdict yet) and dispatches only tasks the verdicts left
   unverified. Asserted by hashing the verdict files across both runs.
6. With `_RULINGS.toml` active, `verify` does not call the judge runtime (asserted with a judge stub
   that writes a sentinel file — the file must not appear) and exits 1.

---

## 4 · Part B — the README, human first

The current README opens with "What this repo is" and "The one idea": mechanism before need. A
reader cannot tell in ten seconds whether the tool is for them, which is how both trial users
bounced off it.

**Rule for the rewrite: a human decides whether to keep reading in the first ten seconds; an agent
reads the whole file regardless. So the human's question goes first and the machine's reference
goes last.**

New order:

| Section | Content |
|---|---|
| **Do you need this?** | A short table. More than one worker at once → yes. One worker → you still want `smokin verify`, and two lines on why. **First thing on the page.** |
| **Sixty seconds** | `smokin verify <a plan you already have>`. Something works before any concept is explained. |
| **The three states** | `◑ claimed · ● verified · ✗ refuted`, in words, arriving *after* the reader has seen them. |
| **When you need the fleet** | dispatch, panes, the reaper, the pane ceiling — everything that only makes sense at n>1, marked as such. |
| **Reference** | full command table, exit codes, runtimes, the delegation node. |
| **For an agent reading this** | kept verbatim, moved to the bottom. |

`verify` is the first command shown, because it is the first one that is useful.

The line that ties it to the rest of the method, to appear in "Do you need this?":

> **At n=1, you are the receipt. `verify` is the second hand.**

---

## 5 · Part C — the adversary check tells the truth

### 5.1 Grillin: wording only

`scripts/validate-plan.py:573` currently emits:

```
['T5'] staffed as adversarial, owned by nobody else in the plan
```

Two claims, one of which the check cannot make. Replace with:

```
['T5'] is declared adversarial and its owner is named on no other task. This
checks the DECLARATION only — nothing here can tell who actually RAN it, and in
a one-agent setup the separation is fictional. `smokin verify` says so out loud;
`smokin tick` enforces it.
```

No logic change. From files alone, nothing can establish who executed a task, and the fix for a
check that over-claims is to stop over-claiming.

### 5.2 Smokin: real enforcement, where it is possible

`tick` dispatches, therefore it knows.

- The dispatch record (`bin/smokin:354`) gains **`session`** — a stable id for the agent instance a
  task was handed to. For `pane` dispatch this is the pane id; for `inproc` it is the wrapper's
  process group id. Recorded at dispatch, before launch, like every other field.
- A task is **adversarial** if its `TASK.md` carries a `**Reader:**` line (the field Grillin's
  `check_adversary` already keys on).
- **Rule: an adversarial task must be dispatched to a session id that appears in no other dispatch
  record for this run.** If the only available session is a used one, `tick` refuses to dispatch it,
  writes a tier-3 halt, and says which session collided.

**Where this rule actually bites, stated plainly so nobody over-reads it.** `inproc` dispatch spawns
a fresh headless process per task, so every inproc task already has its own context and the rule is
trivially satisfied — **independence is free there, and that is a real property worth stating rather
than a gap.** The rule earns its keep in exactly two places: **pane reuse**, where one long-lived
agent can be handed several tasks, and `verify`, where nothing ran anything and the warning in the
next bullet is the whole of what can be said. Trial 2's failure was the second kind — a human
relaying every task to one `helper` — which no dispatcher could have caught, because no dispatcher
was involved.
- `verify` has no sessions at all, so for every adversarial task it prints:

  > *"T5 is declared adversarial. Nothing ran it here, so its independence is unverified."*

This splits the job along the only honest line: **the gate checks declarations, the runner checks
actors.**

### 5.3 Acceptance tests

- Grillin: the known-good fixture still passes; the new message appears; no `FAIL` is added.
- Smokin: a plan whose adversarial task is forced onto an already-used session halts, and the halt
  names the session. Negative control: a fresh session dispatches silently.
- Smokin: `verify` on a plan with an adversarial task prints the unverified-independence line.

---

## 6 · Part D — declared size, enforced

### 6.1 The field

`PLAN.md` carries:

```
**Size:** S
```

Added to `templates/PLAN.md.template` and to QUICKSTART's worked shape.

### 6.2 The check — `size-declared`

Two failure modes:

- **missing** — *"PLAN.md declares no `**Size:**`. A plan that never says how big it is cannot be
  held to it, and the bands are advice until it does."* If `PLAN.md` itself is absent, this check
  stays silent — `check_plan_source_of_truth` already owns that failure and two checks reporting one
  defect is noise.
- **declared band ≠ actual task count** —

```
FAIL — size-declared   PLAN.md declares Size: XS (1-3 tasks); this plan has 5.
                       Either it grew past what you scoped — say so and re-scope —
                       or the declaration is stale. This is the exact drift that
                       turned a stated "1-3 tasks, short path" into 5 tasks with
                       rollback plans and a baseline task.
```

It **fails, not warns**. Growing past your band should cost an explicit re-scope; that is the
decision that did not happen in trial 2.

### 6.3 Bands, and the drift guard

| Size | Tasks |
|---|---|
| XS | 1–3 |
| S | 4–10 |
| M | 11–25 |
| L | 26–60 |
| XL | 61+ |

These already exist in two places: `SCALING.json`'s `scaling[].tasks`, and Smokin's `Plan.size()`.
Adding a third copy in the gate creates exactly the drift this repo keeps finding, so
**`check-drift.py` gains a comparison of the gate's bands against `SCALING.json`**, and fails if they
disagree. A number published three times is a number that eventually disagrees with itself.

### 6.4 Acceptance tests

- A plan with no `**Size:**` fails; the known-good fixture gains the field and still passes.
- A plan declaring `XS` with 5 tasks fails and the message names both numbers.
- A plan declaring `S` with 5 tasks passes.
- `check-drift.py` fails when the gate's band table is edited to disagree with `SCALING.json`.
- CI mutation probes for the first two, in `gate.yml`.

---

## 7 · Stated limits

Written here so they are not discovered in trial three.

- **`size-declared` is itself a declaration check.** An agent can write `**Size:** M` and produce 20
  tasks legitimately. It closes the drift observed — a stated band silently exceeded — not the
  deeper problem of a plan being the wrong size to begin with. Same class as the adversary check.
- **`verify` proves the done-commands pass; it cannot tell you they are good done-commands.** A weak
  gate verified is still a weak gate. `done-self-reference` catches one shape of that and no more.
- **Smokin's session rule assumes one agent per session.** An agent that spawns sub-agents inside its
  own session defeats it, and nothing here detects that.
- **The session rule cannot reach the failure that prompted it.** Trial 2's collapsed independence
  happened with a human relaying tasks to one agent, with Smokin not dispatching at all. Only
  `verify`'s printed warning speaks to that case, and a warning is not enforcement. If this matters
  more than it currently seems to, the next step is for a receipt to carry the session that produced
  it — which requires workers to report it, which is a bigger change than this spec.
- **Neither trial exercised real dispatch.** After this work, Smokin is useful at n=1 and still
  unvalidated by a user at n>1. A third trial must start from *"you have four agents, coordinate
  them"* rather than from a job shape and a hope.
- Both trials ran with `--dangerously-skip-permissions`, so **the permission-prompt experience — a
  large part of a real first hour — is unmeasured** and unaffected by anything in this spec.

## 8 · Risks

| Risk | Response |
|---|---|
| `verify` becomes a way to skip the fleet on jobs that need it | The README's "Do you need this?" table names n>1 as the trigger; `verify` prints the count of tasks that could run concurrently when it exceeds 1 |
| The `TASK.md`-untouched decision confuses a user reading a stale status line | `PROGRESS.md`'s legend gains one line saying the verdict outranks the status field |
| The session rule fires spuriously on small fleets | It applies only to tasks carrying `**Reader:**`, which is a small minority, and the halt names the collision |
| Enforcing size annoys people mid-plan | It is a one-line edit to re-declare, and making that edit is the point |

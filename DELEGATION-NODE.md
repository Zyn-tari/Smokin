# The orchestrator is a delegation node

**Status:** **built**, 2026-08-10. `bin/smokin_rulings.py` is the judgement layer;
`bin/smokin` carries the tiers and the halt. Opt-in by the presence of `_RULINGS.toml` beside the
plan — without it the tick behaves exactly as it did before. Calibrated by `tests/test-rulings.py`,
which mutation-tests every failure mode in §8; Grillin's `check_rulings` refuses a plan whose config
would disable the layer silently.

**What is proven and what is not.** The mechanism is tested against a scripted judge, so what the
tests establish is that *the machinery around a judgement is sound* — evidence containment, the
closed outcome set, fail-closed on every unreachable path, an append-only trail. They establish
nothing about whether a real model's rulings are any good. §7's open cost — how often tier 2 fires on
a real plan — is still unmeasured.

**The shape, in one line.** The **curator** owns the plan and hands it over as a file. The
**orchestrator** is a delegation node — a process that runs, decides, records, and exits. It makes
judgement calls, but it does not *hold* them: every call it makes is written down before it dies.

---

## 1 · What this replaces, and why

The orchestrator used to be another Claude Code terminal. That shape has one defect and it is fatal:
**the fleet's state lives in a context window, and context windows die.** Compaction, a crash, a
closed pane — and the thing that knew what was running no longer knows. Principle 14 exists to
remove exactly that cost, and an orchestrator built as a terminal reintroduces it at the top of the
tree, where it is most expensive.

Smokin already argued half of this: `smokin tick` reads the plan off disk and exits, and it was
tested by `kill -9`-ing a worker with nothing alive to notice. What was missing was the other half —
**where judgement lives when nothing is resident.**

The answer is not "remove judgement." A pure dispatcher cannot decide whether a receipt is
trustworthy, whether a blocked worker is really blocked, or whether a failure means stop. Those are
the decisions that matter most. The answer is:

> **Judgement is invoked, not resident.** The node's own body is mechanical. When it reaches a
> decision it is not permitted to make mechanically, it invokes a *judge* — one bounded call, with a
> persona, model and effort named in the roster — writes the ruling to disk with its reason, and
> exits. The ruling file is the memory. Nothing needs to stay alive to remember it.

---

## 2 · The three roles, and the seams between them

| | Owns | Produces | May not |
|---|---|---|---|
| **Curator** | the plan | `PLAN.md`, `_ROSTER.md`, the ruling schedule | run the fleet, or be asked a question the plan should have answered |
| **Orchestrator** (delegation node) | the frontier | dispatches, receipts, rulings | edit the plan, write feature code, invent a decision class |
| **Worker** | one task | one receipt | judge its own output, or spawn outside its declared policy |

**The handover is a file, not a conversation.** The curator sends the plan to the orchestrator by
committing it. If the orchestrator needs something the plan does not contain, that is a defect in the
plan and the node halts and says so — it does not improvise the missing part. A node that patches
around a thin plan is a node that has quietly become the curator, and then nobody is holding the plan
to account.

**The orchestrator may not edit the plan.** Same reason the roster wins over a task file: the
document where the reasons are written has to be the document that governs. A node that rewrites its
own instructions has no instructions.

---

## 3 · The control lever — four tiers of decision

This is the part that "knows how to delegate it." Every decision the node can face is assigned to a
tier, and the tier determines *who* decides and *what it costs*.

### Tier 0 — mechanical. No model, no tokens.

Frontier computation, dispatch, receipt recording, reaping a missing receipt, publishing state.
Shell and Python. **This is most of the node.** It runs on every tick and costs nothing.

If a decision can be moved down into tier 0, move it. Tier 0 is the only tier that is free, and it is
the only tier that cannot be wrong in an interesting way.

### Tier 1 — judged by rule, and the rule is the curator's.

Concurrency ceiling, retry count, stale threshold, what a `blocked` state means for this plan, which
failures are fatal. These are declared in the plan. **The node applies them; it does not decide
them.** Still no model.

The distinction from tier 2 matters: a threshold written down in advance is a decision the curator
made once, with the whole plan in view. A threshold decided at 3am by whatever process happened to be
running is a decision nobody reviewed.

### Tier 2 — judged by an invoked judge. This is where tokens are spent.

The decisions that genuinely need reading:

- **Is this receipt trustworthy?** A worker reporting `done` is a claim, not a result. (Grillin
  principle 7: evidence is execution, not inspection.)
- **Is this blocked worker really blocked?** herdr reports bare login shells as idle agents; `idle`
  and `unknown` are not evidence of completion.
- **Does this failure mean re-dispatch, re-plan, or stop?**
- **Did this task actually satisfy its contract, or only produce output?**

Each of these is a **named decision class** with an entry in the ruling schedule (§4). The node
invokes one judge, single-shot, with: the plan excerpt, the receipt, the relevant state, and nothing
else. The judge returns a ruling. The node writes it and exits.

**The judge is never the worker whose work is being judged**, and never runs at the worker's model,
effort *and* context. That is principle 8, and it is the reason a delegation node is allowed to be
cheap: the expensive reading is done by someone who did not write the thing.

### Tier 3 — escalate to the curator. A human reads it.

Anything with no entry in the ruling schedule. Anything where the judge itself returns
`insufficient-evidence`. Anything that would change the plan's scope.

**The node never invents scope.** It halts, publishes why, and waits. A halt that says why is a
result; a node that guesses and continues is the failure mode that produces a finished-looking plan
nobody can audit.

---

## 4 · The ruling schedule — the node cannot decide what it was not told to decide

A new artefact, written by the curator, living beside the plan. It declares every tier-2 decision
class this plan permits, and for each one:

```toml
[[ruling]]
class    = "receipt-trust"                 # the decision class, by name
when     = "receipt.status == 'done'"      # when the node must ask
persona  = "adversary"                     # must appear in _ROSTER.md
evidence = ["task.contract", "receipt", "worker.output"]   # what the judge is handed. Nothing else.
outcomes = ["accept", "reject", "insufficient-evidence"]   # the closed set it may return
default  = "halt"                          # what happens if the judge cannot be reached
```

Four properties, each one a defect that has already happened somewhere in this family of tools:

1. **A decision class not declared here cannot be made.** An undeclared ruling is a decision nobody
   priced and nobody reviewed — exactly how a roster stops describing the fleet.
2. **`persona` resolves against `_ROSTER.md`**, so the judge's model and effort come from the file
   that carries the reason. The validator already enforces one-persona-one-pairing; this inherits it
   for free.
3. **`outcomes` is a closed set.** A judge that can return prose can return anything, and the node
   would have to interpret it — which is judgement the node is not allowed to have.
4. **`default = "halt"` and it is not configurable to anything softer.** Fail-closed. An unreachable
   judge that quietly resolves to `accept` is a plan that certifies itself while looking like it
   works. That is the same fail-open shape `memory_gates.py` rule 2 refuses, and it is refused here
   for the same reason: **silence that resembles success is the worst available outcome.**

---

## 5 · A ruling is a receipt

Rulings go in `.smokin/rulings.jsonl` — append-only, seq-numbered, same discipline as
`.herdr/transitions.jsonl`. One line per ruling:

```json
{"seq": 41, "at": "2026-08-10T09:14:02Z", "class": "receipt-trust", "task": "T7",
 "persona": "adversary", "model": "claude-opus-5", "effort": "xhigh",
 "outcome": "reject", "because": "the contract required the migration to run; the receipt shows the file was written",
 "evidence": ["tasks/T7/TASK.md", ".smokin/receipts/T7.md"]}
```

`because` is mandatory and is not boilerplate. A ruling without a reason is unreviewable, and the
whole point of moving judgement out of a context window is that someone can read it afterwards.

**Rulings are never rewritten.** A reversed decision is a *new* ruling that references the old one.
The history of what was decided and on what evidence is the audit trail; editing it destroys the only
thing this design buys.

---

## 6 · What each tick actually does

```
smokin tick
  ├─ 0  acquire the tick lock            (one node at a time — two orchestrators is the collision nobody sees)
  ├─ 0  read PLAN.md, _ROSTER.md, _RULINGS.toml, _INVARIANTS.toml, .herdr/state.json, receipts/  [tier 0]
  ├─ 1  re-read every plan-level invariant; a break HALTS before anything is dispatched  [tier 1]
  ├─ 0  reap: any dispatch past its deadline with no receipt is a FAILURE        [tier 0]
  ├─ 1  apply the plan's declared ceilings and retry policy                      [tier 1]
  ├─ 2  for each receipt needing a ruling: invoke one judge, write the ruling    [tier 2]
  ├─ 0  compute the frontier from rulings, not from receipts                     [tier 0]
  ├─ 0  dispatch up to the ceiling; write a dispatch record BEFORE launching     [tier 0]
  ├─ 1  re-read the invariants again at the tick's end                           [tier 1]
  ├─ 0  publish .smokin/state.json by rename(2)                                  [tier 0]
  └─     exit
```

**The invariant pass is tier 1 — a curator's rule applied mechanically (§3).** The curator declares
what must not move and why; the node re-reads it and compares. No judgement is invoked, which is why
it can afford to run twice a tick. It runs *before* dispatch so a plan that has already broken
something does not get to add another worker to the damage, and again at the end so the break is
attributed to the tick that caused it rather than discovered a tick later. `_INVARIANTS.toml` and
what it does not solve are described in `DESIGN.md` §7b.

Two lines carry most of the weight:

- **"write a dispatch record before launching"** — already how `smokin tick` works. A worker that
  dies before emitting is still known to have been dispatched, which is what makes the reaper
  possible.
- **"compute the frontier from rulings, not from receipts"** — this is the whole design in one line.
  A receipt is a worker's claim about itself. A ruling is a judgement made by someone else. The plan
  advances on rulings.

**The node reads `.herdr/state.json`; it never calls `herdr`.** The monitor is the single reader.
Two things polling herdr is two things with different pictures of the same fleet.

---

## 7 · What this costs, honestly

**Cheaper than a terminal, on the common path.** Tier 0 is free and it is most of every tick. A
resident orchestrator paid full model price for "nothing has changed since 3 seconds ago," on every
poll, forever. This pays nothing for that.

**More expensive per judgement, and that is deliberate.** A tier-2 judge is an `opus-5` call at
`xhigh` with fresh context — which is more than a resident orchestrator glancing at a receipt it
already had in context. The trade is bought on purpose: the 2-vs-50 measurement said readers catch
what gates miss, and a judge is a reader with the ownership rule attached.

**The unavoidable new cost is latency.** A resident process notices a receipt the moment it lands. A
node notices it on the next tick. That is the price of not being resident, it is real, and the fix is
a shorter tick interval, not a resident process.

**A cost I want measured before recommending this**: how often tier 2 actually fires on a real plan.
If nearly every receipt needs a ruling, the tier structure is decoration and the node is just an
expensive orchestrator with extra files. Phase 8's measurement table gets a sixth row: *rulings per
task, and the share of ticks that spent a single token.*

---

## 8 · The failure modes, named

| Failure | What it looks like | What stops it |
|---|---|---|
| The node becomes the curator | plan gets edited mid-run to fit what happened | node has no write access to the plan; halts instead |
| The node becomes a worker | it "just fixes" a small thing rather than dispatching | it writes no feature code, ever; the only files it writes are under `.smokin/` |
| Judge shopping | a rejected receipt gets re-judged until it passes | rulings are append-only; a re-judge is a new ruling that must reference the old, and the reference is visible |
| A quiet default | unreachable judge resolves to `accept` | `default = "halt"`, not configurable |
| Two nodes | overlapping dispatch, doubled work | the tick lock, already built |
| The schedule rots | plan grows a new decision class, schedule doesn't | an undeclared class is a tier-3 halt, so it surfaces loudly the first time it matters |

---

## 9 · What is NOT solved

- **Who judges the judge.** A wrong ruling is recorded with its reason and is therefore reviewable —
  but nothing catches it automatically. The current answer is the same as everywhere else in this
  method: a human reads the rulings file. That is honest, not sufficient.
- **The latency floor.** Nothing here makes a tick-based node notice a completion faster than one
  tick. Stated, not fixed.
- **Escalation has no channel yet.** Tier 3 halts and publishes. Nothing pings the curator. The herdr
  monitor's `HERDR_MONITOR_ON_CHANGE` hook is the obvious hook to reuse; it is not wired.
- **Cost of a false halt.** Fail-closed means a flaky judge endpoint stops a running plan. That is the
  correct trade, and it will be annoying, and nobody has measured how often it happens.
- **The roster's pairing is only partly enforceable.** A runtime applies the model and the effort only
  if its `judge` command in `runtimes.json` carries `{MODEL}` / `{EFFORT}`. `claude` can carry the
  model; nothing on this machine can carry the effort from a shell command. So each ruling records
  `pairing_enforced` — what was actually applied, separately from what the roster asked for — and
  `smokin rulings` says so out loud. **The gap is real and is not papered over**: writing
  `model: claude-opus-5` on a ruling that ran at the runtime's default would be the same defect this
  whole tool exists to catch, one level up.

---

## 10 · What was built

| | | Where |
|---|---|---|
| 1 | `_RULINGS.toml` schema + loader — malformed ⇒ **no** rulings ⇒ halt, never a quiet fall-back | `bin/smokin_rulings.py` |
| 2 | `.smokin/rulings.jsonl` — append-only, seq-numbered, reason mandatory | `append_ruling`, `standing` |
| 3 | Tier-2 invocation — one judge, closed outcome set, evidence honoured exactly | `invoke_judge` |
| 4 | The frontier computed from rulings, not receipts | `Plan.ruling_state`, `Plan.state_cheap` |
| 5 | Validator check in Grillin | `scripts/validate-plan.py::check_rulings` |
| 6 | Mutation tests for every §8 failure mode | `tests/test-rulings.py` |

Two things the build changed from the design:

- **`verdict.pass` became `verdict.passed`.** `pass` is a Python keyword, so `verdict.pass` can never
  parse as an attribute — the field name in the original design was unimplementable. Caught by the
  first test run.
- **`when` is whitelisted by AST node type, not by pattern.** A call, a subscript, an f-string, a
  comprehension and a walrus are all rejected structurally, which is the only way that stays true
  when somebody writes something nobody thought of. An unknown field is an error at *load* time — a
  typo that quietly evaluated to `False` would be a ruling that never fires on a plan that looks
  judged and is not.

### New surface

```
smokin rulings <plan>     resolve and print the judgement layer; exit 1 if it does not load
smokin resume <plan>      clear a halt, after a human has read it
```

`smokin reset` **retires** rulings rather than deleting them — a retirement is appended, the ruling
and its reason stay readable. Deleting them would make a reset the cheapest way to erase an
inconvenient judgement, which is the trail this design exists to leave.

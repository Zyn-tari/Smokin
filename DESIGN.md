# Smokin — the design

> ## Status of this document, 2026-08-05
>
> This is the design that preceded the implementation, kept because its adversarial findings are
> the reason the code is shaped the way it is. **Three of its claims have since been overturned by
> experiment** — see [`EXPERIMENTS.md`](EXPERIMENTS.md), which is the authority where they disagree:
>
> | This document says | Experiment says |
> |---|---|
> | Q1 open — Codewhale panes may have no emission path; §5d boundary and failure mode 3 | **RETRACTED.** The wrapper trap fires on pane close, `rc=129`. Codewhale panes emit |
> | Q2 open — nobody ran the `herdr pane run` trap test | **CLOSED.** The trap survives; pane dispatch has a real floor |
> | pane closure undesigned | `herdr pane close` sends **SIGHUP** — recoverable, and now a first-class terminal state |
>
> Also stale: its §7 finding that a run without `--run-gates` exits 0 (Grillin now exits 2,
> INCOMPLETE), and every line-number citation into `validate-plan.py`, which has moved.
> Its `not found` regex finding was real and **is fixed** in Grillin.

---


A design for running a fleet of *different* coding agents — Claude Code, Codex, OpenCode,
Codewhale, aider, anything installable — from one deterministic workflow script, where a
finished task reports its own end result into a spool the orchestrator can be absent from.

Written against Grillin at `~/grillin` and the binaries installed on this machine on
2026-08-05. **Nothing in `~/grillin` was changed by this document.** The exact files a
future implementation would touch are listed in §8, and not one of them has been touched yet.

> **This is a design, not an implementation.** Three adversarial passes landed on the draft that
> preceded it — one fatal on concurrency, one fatal on the word "non-negotiable", one high on the
> multi-platform claim. Their findings are answered in the section they attack, not in an
> appendix, and where the fix is unknown it is written down as an open question in §10 rather
> than smoothed over. A design that hides its own attack surface is the thing phase 3 exists to
> catch.

**Labels used throughout, as everywhere else in this method.** **CONFIRMED** — checked against a
binary or a file on this machine, with the command shown. **SUSPECTED** — inferred, read in a
vendor document, or reported by a probe not re-run here. Anything unlabelled inside a claim is
SUSPECTED by default.

> **Contradiction, surfaced rather than resolved silently.** Grillin's working tree is **dirty**.
> `git status --porcelain` reports `M scripts/validate-plan.py` (CONFIRMED, 2026-08-05 15:36),
> and the uncommitted diff adds **five** further `FLOORS` keys —
> `require_plan_source_of_truth`, `require_adversary`, `require_confirmed_is_exercised`,
> `require_frozen_human_contracts`, `require_instrument_fixture` — plus new checks referencing a
> reskin run. So the "six floors" figure used by the adversarial pass describes the **committed**
> validator; the working tree has eleven. **Nothing in this document changed that file**, and
> every line number cited below is against the **working tree as it stands today**. If a future
> implementation starts from the committed version instead, the anchors move and the floor count
> is different. Somebody should decide which of those two is the plan of record before Smokin's
> nine floors are added to either.

---

## 1 · What Smokin is, in one line

> **Smokin is a Grillin substrate in which one idempotent command — `smokin tick` — reads the
> plan directory off disk, dispatches whatever is ready (most tasks as headless subprocesses, a
> few as herdr panes under a stated rule), reaps whatever finished by reading receipt files that
> the agents' own wrappers and hooks wrote, and exits.**

There is no long-running orchestrator process. That is the whole point, and it is the one cost
Grillin already confesses against its own default substrate:

> `SCALING.json` → `substrates.default.costs[2]`: *"fleet state lives in the orchestrator's
> context and dies with it"*

Principle 14 says assume amnesia and demands that progress be reconstructable from the repository
alone — and today nothing in the repo makes that true for a running fleet. `smokin tick` is that
mechanism. Compaction, `Ctrl-C`, an SSH drop and `herdr server stop` all become no-ops on the
plan, because the plan's state was never in the process.

**Smokin does not earn a new principle for this.** Saying "the orchestrator holds no state" would
restate principle 14 in different words, which is exactly the redundancy this method tells plan
authors not to commit. It earns a *mechanism* citation under principle 14, and one genuinely new
principle for something principle 14 does not say — see §7.

---

## 2 · The routing rule

Four things the requester asked for, and this is the third: *when should the orchestrator open a
new pane or tab of agents rather than spawn an in-process worker?*

**The rule points the opposite way from the reflex.** You do not open a pane to get parallelism.
Parallelism is free in-process — the tick forks N subprocesses and reaps them. A pane is bought
with a screen and paid for in human review capacity, which is the one constraint the prior-art
survey found nobody solved and which grows linearly with fleet size. A pane you did not need
costs a pane, a dispatch record, a deadline and a reaper slot, and buys observability nobody was
going to read.

### 2a · The declared fields

In `tasks/<ID>/TASK.md`, in the same bold-field register the validator already parses:

```
**Dispatch:** inproc | pane     · **Runtime:** `<key from .smokin/runtimes.json>`
**Budget:** <seconds>           · **Interrupt:** yes | no
**Watch:** yes | no             · **Blockable:** yes | no
```

Plus the fields phase 5 and phase 7 already require: `**Type:**`, `**Wave:**`, `**Worktree:**`,
`**Branch:**`.

### 2b · The procedure — first match wins

A stranger applies this table and gets the same answer, given the same declared fields.

| # | Test | Then | Why this and not judgement |
|---|---|---|---|
| **1** | `Interrupt: yes` | **PANE** | The task has an approval-bearing or human-answerable step. A headless worker parked at an approval prompt is indistinguishable from a worker thinking, until it times out — this is the exact cost `substrates.default.costs[0]` already names. |
| **2** | `Watch: yes` | **PANE** | Somebody declared in writing that they will look at it. This is the only clause where taste is allowed, and it is spent once, at phase 0, on the record. |
| **3** | `Type: ASK` | **PANE** | An ASK node terminates on a human, not on a model. Phase 4 already types the node; this clause reads it. |
| **4** | `Budget > 900` | **PANE** | Work expected to outlive the tick must outlive the tick's process. 900s is the SCALING size-row default, not a constant — see 2d. |
| **5** | `runtimes[Runtime].headless == null` | **PANE** | The runtime has no one-shot mode, so a pane is the only way to run it at all. |
| **6** | *otherwise* | **INPROC** | The half everybody skips. |

### 2c · Placement — only for PANE, and mechanical

| Resource | One per | Command | Status |
|---|---|---|---|
| **Workspace** | distinct git toplevel of `**Worktree:**` | `herdr workspace create --name <n>` | SUSPECTED — group exists; exact flags **need verification** |
| **Tab** | `**Wave:** W#` within that workspace | `herdr tab create ...` | SUSPECTED — **needs verification** |
| **Pane** | task — never per runtime | `herdr pane split --current --direction right --cwd <wt> --no-focus` | CONFIRMED in `_HERDR.md.template:123` |
| **Name** | role, per principle 15 | `t14-search`, never `codex-1` | CONFIRMED constraint `[a-z][a-z0-9_-]{0,31}` (`_HERDR.md.template:36`) |

**A tab is a wave.** That is the whole meaning of a tab under Smokin, and it makes the terminal
layout a rendering of the phase-4 dependency graph rather than an accident of dispatch order.

Placement is written by the tick to `<plan>/PLACEMENT`, tab-separated, in the same register as
phase 7's `OWNERS` file:

```
T14	pane	codewhale	w7	w7:t2	w7:p9	smokin/T14-search
```

Generated, never hand-maintained. `_WORKTREES.md.template` already says why: *two lists that can
disagree is a defect.*

### 2d · Ceilings

`smokin tick` dispatches at most `fanout` concurrent tasks and at most `paneCeiling` concurrent
PANE tasks, both read from the plan's SCALING size row rather than from a fresh number invented
in `PLAN.md`.

| Size | paneCeiling (proposed) |
|---|---|
| XS | 0 |
| S | 1 |
| M | 3 |
| L | 5 |
| XL | 5 |

**These five numbers are an opinion, and marking them a floor does not make them a measurement.**
They come from practitioner reports that senior review capacity binds before compute does. Phase
8's own rule — *do not pick the tool that looks structured, measure* — binds here, so they ship
into `SCALING.json` flagged `"provisional": true` and the first plan that measures a real fan-out
is expected to move them. A ceiling-blocked pane task is left in the frontier reported as
`queued(pane-ceiling)`; it is **never** silently demoted to inproc, because demotion would
violate the clause that produced it.

### 2e · The attack on this rule, and what survives

> **ADVERSARIAL FINDING (fatal, "non-negotiable" lens) — `require_route_matches_rule` is a
> tautology.** Two tasks were written with identical bodies, identical runtime and identical
> budget, opposite `Dispatch`, and the recomputed route agreed with both. Changing one digit —
> `Budget 300` → `901` — re-blessed a flip to `pane` via clause 4. Of six clauses, only clause 5
> (`headless == null`, read from a checked-in file) and clause 3 (`Type`, an existing typed field)
> have an external referent. `Interrupt`, `Watch` and `Budget` are free self-declarations, so the
> check compares the author's conclusion to the author's own premises.

**This landed and it is conceded.** The response is three changes, not a defence:

1. **The floor is renamed to what it actually checks:** `require_route_declared_consistent`. It
   catches a *declaration that contradicts its own premises* — a real and common error — and it
   does not catch a preference laundered through a premise.
2. **Two of the three soft inputs get an external referent.** `Interrupt: yes` must cite, in the
   same task, a named tool or path inside `## What you own` that is the thing needing approval;
   `Budget` must fall inside the range published for the plan's SCALING size row rather than being
   a free integer. `Watch` stays a pure preference, and §7 marks it ADVISORY by name.
3. **The document stops claiming routing is a pure function.** Honest statement: *dispatch is
   author-chosen within a checked envelope, and one clause of six is pure taste, declared at
   phase 0 where a reader can argue with it.* That is weaker than the draft claimed and stronger
   than nothing, which is where the method's own standards leave it.

---

### 2f · Pane reuse, and the hole it punches in containment

*Added 2026-08-19, after the mechanism was built. The routing rule above decides whether a task
gets a pane. It never asked whether it needed a **new** one, and `launch()` called
`herdr pane split` unconditionally, so the answer was always yes.*

**The incident.** An operator watched six agents sit idle, each holding exactly the context the
next task needed, and opened a seventh pane. Context that cost real tokens to build was thrown
away, and nothing in the plan directory recorded that it had been.

**The cost, before the benefit.** Every other mechanism here assumes a task's beliefs die with its
process. That is why `inproc` needs no containment machinery: a fresh subprocess per task gets it
for free, and §3c's `session` field records it. A reused pane keeps the session alive across the
task boundary, so **a wrong belief formed in task A survives into task B**, and task B's
done-command cannot see it — the gate tests B's artefacts, and a contaminated premise that
produces a passing artefact passes. Reuse is therefore **default-deny**, and every decision, taken
or declined, goes in `ledger.jsonl` with the sentence that produced it.

**Who may, by role.** The role is read from `**Reader:**`, the same field Grillin's validator
reads, and it is not a preference:

| Role | Reuse | Why it is not a preference |
|---|---|---|
| `**Reader:** adversary` | **FORBIDDEN** | Grillin's `check_adversary_context` fails the task unless it declares `**Context:** fresh — not a subagent of the orchestrator, not a continued session`. A reused agent **is** a continued session. Reusing here would make Smokin the thing that quietly breaks the plan's most load-bearing check *on a task still carrying the declaration that says it did not*. Grillin can only read the sentence; this is the half that can act on it |
| `**Reader:** health` | **PREFERRED** | Grillin's `check_health_checker` says this role's contamination is "required, not disqualifying", and deliberately does not check it for a clean owner. It runs in rounds and gets better with the context it already holds |
| anything else | **PERMITTED** | ordinary work, bounded by the containment cost above |

**What identity means here.** `**Agent:**` is the persona — Grillin says so beside its own regex —
and Smokin never read it: `grep RE_AGENT` returned nothing before this change. A persona is a
label, not an addressable worker; Grillin has personas and no persons. A pane id is what turns the
label into something you can send work to, so the pane history is keyed on `**Agent:**` and the
mapping lives on the dispatch record, which already survived completion. **No new store.**

Two things about that field, both measured rather than assumed. It repeats: `minimal-passing-plan`
declares `**Agent:** `implementer`` on T2 *and* T3, which is what makes reuse possible at all. And
it is usually **absent** — 9 of the 20 `TASK.md` shipped across both repositories declare it, and
the largest fixture (`a-real-first-plan`, 8 tasks) declares it on none. So the parse defaults to
absent and every mechanism downstream degrades to doing nothing, with one ledger line saying so:
a reuse mechanism whose declines are silent is indistinguishable from one that was never built.

> **This retracts §7 non-negotiable 6's "is unique across the plan".** That clause was never
> implemented in Grillin, and Grillin's own shipped example contradicts it. Uniqueness would also
> make this section impossible: if no two tasks may share a persona, there is never anything to
> reuse. The rest of that row — the character class, and not colliding with herdr's kind labels —
> is untouched.

**The one question asked of the filesystem.** *Has the task previously dispatched into this pane
reached a terminal state in the plan — is there a `RECEIPT.json`?* It is never asked whether the
pane is alive, idle or busy. `grep 'os.kill|kill(0|/proc/|pid_alive|agent list|is_alive'` across
all three executables returns nothing, that absence is deliberate (§3j), and CONTRIBUTING declines
"Trusting a lifecycle state" by name — on this machine `herdr agent list` reported two bare login
shells as idle agents.

**The one question asked of the world is an attempt.** `herdr pane run` is sent to the remembered
pane; a non-zero return falls back to a fresh split. CONFIRMED 2026-08-19:
`herdr pane run w99:p99 "echo hi"` exits 1 with `{"error":{"code":"pane_not_found"}}`. An attempt's
result is a fact. A lifecycle label is an opinion.

**How it is measured: panes opened per run.** Not tokens. Token capture (§3f) reads what a
dispatch spent and only works on the **headless** path, because the pane-side numbers live in
vendor state directories that principle 14 and `bin/smokin-run`:61 both bar this design from
reading. Reuse only happens in **panes**. The two halves do not overlap, and closing that gap by
reaching into `~/.claude` would buy one number and sell principle 14. So the reading is a count of
`.smokin/dispatch/*.json` records with `dispatch == "pane"`, split by whether they opened a pane
or inherited one — no vendor parsing at all, and the direct measurement of the incident, since the
incident was a pane being opened. It lands on `STATUS.json` as `panes` and in `PROGRESS.md` under
"What this run cost in panes".

**What is deliberately not built.** No reuse across runs (`smokin reset` unlinks the dispatch
records, and that stays the way the history is cleared). No reuse for `inproc`, which is already
fresh per process and has nothing to save. No pane pooling, no idle timeout, no reaping of an
unused pane — all three need a lifecycle belief.

**CONFIRMED end to end against the real `herdr` 0.8.0, 2026-08-19**, three runs of a four-task
plan, not a stub:

| Run | What happened |
|---|---|
| reuse | T1 opened `w4:pV`; T2, same persona, ran in it. `panes: {dispatches: 2, opened: 1, reused: 1}`, and T2's `session` is byte-identical to T1's — the containment collapse is on the record, not hidden |
| the adversary | identical plan, T2 gains `**Reader:** adversary`. Two panes, `w4:pW` and `w4:pX`, ledger `why: reader-adversary-must-be-fresh` |
| the fallback | the pane was closed by hand between T1 and T2, with T1's receipt already on disk — so every file-readable question still said *reuse it*. The attempt came back `herdr pane run returned 1`; T2 opened `w4:p0`. `opened: 2, reused: 0` |

The third run also produced the one defect this feature shipped and fixed: the tick printed
*"opened a fresh pane — reuse permitted, T1 finished in w4:pZ and left a receipt"*, which is the
reason the decision was **taken** on a line announcing that it did not survive. True, and the
wrong half of the story. The harness could not have found it; only running it could.

### 2g · Agent memory — what survives the process, and the guard that lets it

*Added 2026-08-19, immediately after §2f, and it is the same incident read a third time.*

§2f keeps a **context** alive across a task boundary. It only works while the pane still exists,
only inside one run, and never on the headless path — where a fresh subprocess per task is not an
oversight, it is where `inproc`'s containment comes from. So the thing the operator was actually
mourning, the observation the sixth agent had already paid for, still died with the process
everywhere reuse could not reach.

**What survives here is deliberately tiny.** Not the context: a transcript is not reconstructable
and pretending otherwise produces a store nobody can audit. What survives is an **observation and
the command that produced it** — one line each, in `.smokin/memory.jsonl`, append-only, the same
open-append discipline as the ledger.

**The guard is the feature, and it is the only reason this is allowed to exist.** Every entry
carries the task it came from, the observation, and the command. `"be careful with async"` carries
none of those and is **refused at write time** with a non-zero exit and nothing appended — not
stored-and-flagged, because a flagged entry is still an entry and still gets recalled. The guard
is **structural, not semantic**: nothing here grades prose, because nothing here can. What it
requires is the one field that makes prose checkable, so a reader who doubts an entry can run the
command and find out. Two entries make the point exactly:

| Written | Stored |
|---|---|
| `be careful with async` | **refused** — no task, no observation, no command |
| `be careful with async`, `--task T4`, `--observation "test_pool hung for 30s then timed out, 3 runs of 3"`, `--command "pytest -k pool -x"` | **accepted** — the same sentence, now something a reader can disagree with |

**And that second row is the whole of it, which is weaker than "unfalsifiable advice is rejected"
and must not be written as that.** The adversarial pass of 2026-08-19 put `--observation "async is
tricky" --command "true"` behind the same sentence and it landed; so did a command field reading
`"I just knew it from experience"`. What the guard refuses is a shape: an empty field, a runaway
field, a claim carrying a line break (which would escape its own `## ` heading in the file a
worker reads), an observation that is its own claim retyped, and — since that pass — a `--task`
naming no task in this plan, which was invented provenance and stored happily. What the guard buys
is that a doubting reader always has something to **run**. It does not and cannot refuse advice,
and §2h says so where a reader will find it.
**Two kinds, one guard.** A `fact` is something the tick observed itself; a `lesson` is a
generalisation somebody drew from one. The distinction is about *who asserted it and how far it
reaches*, never about how well it is evidenced — the guard does not weaken for a `fact`, because a
fact with no command behind it is the same defect wearing a more confident word.

**The tick writes exactly one thing automatically: a REFUTED gate.** A gate that passed teaches
the next occupant nothing the receipt and the verdict do not already say. A gate that failed, and
the exact command that showed it, is precisely what the next agent pays tokens to rediscover.
Nothing harvests sentences out of `FINDINGS.md`: an agent's prose about its own work has no
command attached and would be refused by the guard, and harvesting it anyway would be this
mechanism deciding the guard applies to everyone else. **The obvious second automatic source —
the rulings layer — is deliberately not wired**, for the same reason: a judgement has a `because`
and no command, so it *is* refused by this guard, and that is the guard being right rather than
inconvenient. A judgement's trail already lives in `rulings.jsonl`.

**Recall is presented as SUSPECTED and never as instruction.** When a dispatched task declares an
`**Agent:**` with memory from this run, Smokin writes `tasks/<ID>/MEMORY.md` — its own artefact in
the task folder, same place and same principle-14 reasoning as the transcript — whose first
paragraph says it is a document written against a snapshot, that the running system outranks it,
and that a contradiction is worth a line in `FINDINGS.md` rather than a silent reconciliation.
**Nothing auto-applies**, and every entry prints the command that produced it so the reader has
somewhere to go other than the prose.

**Retrieval is exact, bounded, and scoped to the run.** Exact string match on the persona name —
no similarity, no embedding, no widening when nothing is found, because a recall that widens its
own query hands a worker somebody else's context and calls it theirs. At most **5** entries, most
recent first, because recall *is* spend and an unbounded one re-spends what it exists to save.
Only entries from the **current run** are ever handed to a worker: the archive keeps everything
and `smokin memory` prints all of it, but crossing a run boundary is a bigger claim than this has
measured — the world moves between runs, which is the failure `_INVARIANTS.toml` already confesses
under "a baseline taken late records the damage as normal".

One place this deliberately disagrees with §2f: **a task is its own memory history.** `pane_history`
excludes the current task, because a pane you are already inside is not a pane to reuse. Memory
does the opposite, because a gate *your own task* failed on a previous attempt is the single most
useful thing a retry can be told.

**Every recall goes in the ledger, including every declined one** — persona, count, and the keys
handed over. This mechanism can cause a failure no other mechanism in this tool can: a wrong
belief handed to a worker *by the orchestrator itself*, which the worker's own gate cannot see.
That has to be diagnosable from files after the fact.

**Five personas is a report, not an action.** When the same normalised claim has been observed by
five *different* personas, it has stopped being one agent's experience and is reported as a **skill
candidate** — in `smokin memory`, on `STATUS.json`, and in `PROGRESS.md`. **No skill is written.**
A skill is a document somebody has to keep true, and evidence that one should exist is not
authority to write it.

**`smokin reset` keeps the entries and drops the recalls.** Deleting an observation would make
reset the cheapest way to erase an inconvenient measurement — the same trade that makes rulings
*retired* rather than removed. Nothing leaks forward either: reset removes `run.json`, recall
filters on the run id, so the next run starts empty and rebuilds its own.

**`smokin verify` writes no memory**, and passes `remember=False` for the same reason it passes
`write_status=False`. It is the door people adopt first *because* it is read-only, and a command
that quietly starts accumulating a store on somebody's disk the first time they try it is not
read-only in the sense that made them try it.

**The honest limits**, here rather than in a footnote:

- **Nothing verifies that the command is the command that produced the observation, or that it is
  a command at all.** `--command true` passes the guard. Same limit §7b states about an invariant
  probe being trusted to be read-only: the mechanism makes a claim checkable by a reader; it does
  not make it true.
- **A stored entry is rendered into a document Smokin signs, so its text is bounded rather than
  trusted.** A claim may not contain a line break, a command is capped, and the fence around a
  command is opened wider than the longest backtick run inside it. Before those three, a written
  entry could put a `# VERIFIED AGAINST THE RUNNING SYSTEM` heading into `MEMORY.md` at top level
  and countermand the SUSPECTED header over Smokin's own signature.
- **Sameness is a normalised string**, so two phrasings of one lesson are two lessons and the
  skill-candidate count is a **floor**, never a total. Judging that two sentences mean the same
  thing is a semantic call, and a counter whose answer depends on a model call is not a
  measurement.
- **Only a refuted gate is captured automatically.** An invariant break is the obvious second
  candidate and is not built: a break is a **halt**, and a halt is read by a human, not recalled
  by an agent.

**What it costs when it is off, measured rather than asserted.** A plan whose gates all pass
writes no store, no `MEMORY.md` and no `PROGRESS.md` section; a plan that declares no `**Agent:**`
— the common case, 9 of 20 shipped `TASK.md` — writes nothing and says why in the ledger. In both
cases **the dispatch line is byte-identical** to the one this tool sent before the feature
existed, which is a comparison of the bytes a worker received and not a claim about intent.

---

### 2h · The limits of this layer, and the index that was cut

*Added 2026-08-19 after the adversarial pass. Three mechanisms landed together — token capture
(§3f), pane reuse (§2f), agent memory (§2g) — and they share one property that belongs in one
place instead of three: **each of them buys something by giving something up, and the thing given
up is not visible in the thing bought.***

**One agent's memory is one agent's view.** `for_agent` returns the entries whose `agent` field
equals this task's persona, and that is the entire retrieval model. It is not a knowledge base, it
is not consensus, and nothing reconciles two personas that observed opposite things — both entries
sit in the store and each persona sees only its own. The store's confidence is uniform whether one
agent measured something once or five agents measured it five times; the only place plurality is
even counted is the skill-candidate report, and that report is a report.

**Reuse trades a containment guarantee for saved context, and the trade is not reversible.**
`inproc` gives independence for free — a fresh subprocess per task, no shared state, by
construction. Every reused pane spends that. A wrong belief formed in task A survives into task B,
task B's own gate cannot see it (the gate tests B's artefacts, and a contaminated premise that
produces a passing artefact passes), and the ledger line saying so is the only trace. The role
table is the one place the trade is refused outright: the adversary never reuses, and — since the
adversarial pass — its context never flows *outward* either, because an ordinary task inheriting
the adversary's pane spends the same independence the plan bought a whole task to get.

**Token capture measures what a runtime chooses to report, and nothing else.** Not what was spent:
what the vendor printed on stdout. A runtime that reports no cost has no cost key, a pane reports
nothing at all and says `available: false`, and a `select: sum` runtime whose transcript lost a
line to the tee race reports a number that is a **floor** and now says `dropped_records` beside it.
None of these is a measurement of the model's actual spend, and no reading here should ever be
subtracted from a bill.

**The lexical recall index was CUT, and this is the reason rather than an omission.** The design
sketched a second retrieval path: score stored claims against the current task's text and hand
over the ones that score well. It was not built. The triage step that would have authorised it
refused, because the research that was supposed to establish **whether lexical similarity can
separate a right match from a wrong one** never arrived — and without that, the scorer's threshold
is a number somebody picked. The failure mode of a wrong pick is specific and severe: the
orchestrator hands a worker a confident premise about a *different* piece of work, the worker's own
gate cannot see it, and the entry reads exactly like the ones that are right. So it was **not
built rather than built on a guess**, and the consequence is stated plainly: recall here cannot
find a relevant entry that a different persona wrote, and it never will until somebody measures
the thing that was never measured. What ships instead — exact match on the persona name — makes
false association by wrong-match structurally impossible, which is a smaller claim and a true one.

**What the adversarial pass changed, so a reader can tell the layer's limits from its defects.**
The pass was real and it found real things: a persona name from `**Agent:**` reached the shell that
`herdr pane run` executes; a stored entry could rewrite the document Smokin hands a worker; recall
ignored the role gate that panes obey; Smokin and Grillin disagreed about what the word
`adversary` means in four inputs Grillin accepts; one deeply nested transcript line ended the whole
tick; and `verify` held both halves of a broken-independence proof in files it already read and
never joined them. All are fixed and each fix has a check that fails without it. What is **not**
fixed, and is a limit rather than a defect: a persona is still a name a task claims, so any task
declaring `**Agent:** recon` inherits `recon`'s pane and `recon`'s entries. Binding a persona to a
task or an owned path would break Grillin's own shipped example, where `implementer` appears on
two tasks — and reuse needs a repeated persona to have anything to reuse.

---

## 3 · The completion ping

The requester's fourth item: *instead of the orchestrator talking to each pane, a background ping
that reports the end result of a finished task back to it.*

**The ping is a durable receipt file published atomically, and the orchestrator does not have to
be running when it lands.** That last clause is what rules out every push transport that looked
attractive.

### 3a · Why not the obvious transports

| Candidate | Verdict | Evidence |
|---|---|---|
| FIFO | **rejected** | loses the message entirely with no reader (blocking write hung; `O_NONBLOCK` → `ENXIO`), and shredded 394 of 480 records at 8KB with a slow reader — SUSPECTED (dossier probe, not re-run here) |
| Unix socket | **rejected** | needs a live listener at send time, same failure, no durability |
| systemd path unit | **rejected** | fired 5× for one file, ignores dotfiles (systemd#32751), and imposes *boot* persistence where `_HERDR.md.template:206` publishes *daemon* persistence — SUSPECTED |
| `bash wait -n` | **inapplicable to panes** | panes are children of `herdr server`, not of the orchestrator shell; returns rc=127 on a grandchild — SUSPECTED. Correct and kept for in-process workers |
| herdr `events.subscribe` | **rejected as primary** | a real push socket exists on `$HERDR_SOCKET_PATH`, but the CLI has no event verb, it is pinned to an undocumented protocol number, and it has **no replay, no backlog and no cursor** — so it needs a live process holding a socket, which is the failure Smokin exists to delete — SUSPECTED |
| `herdr notification show` | **decoration only** | a UI toast with title/body/position/sound and no read-back — CONFIRMED by ground truth |
| **write + `rename(2)` into a spool** | **adopted** | atomic against concurrent readers at any size, survives having no reader at all, replays idempotently, and can be blocked on with zero wakeups |

`rename(2)` requires one filesystem. **CONFIRMED here:** `~/grillin` and `~`
both report `st_dev 2096` (`python3 -c "import os; print(os.stat(...).st_dev)"`). Cross-device
`rename` returns `EXDEV` and `mv` then degrades to a non-atomic copy, reintroducing torn reads.

### 3b · The files

```
<plan>/
  tasks/<ID>/
    RECEIPT.json                  the agent's CLAIM      — written by smokin-emit
    VERDICT.json                  the project's VERDICT  — written by the tick, second hand
    .smokin/transcript.log        tee'd stdout+stderr    — in the task folder, not in ~/.claude
    .smokin/emit.lock             O_EXCL mutex, per task
  .smokin/
    run.json                      {run_id, started, orchestrator_runtime, plan_root}
    runtimes.json                 the only file that knows any vendor's flags
    doctor.json                   committed environment facts (§3g)
    dispatch/<ID>.json            written BEFORE launch  — this is what makes silence meaningful
    spool/tmp/                    staging
    spool/inbox/                  published pointers
    spool/done/                   claimed pointers (the cursor)
    tick.lock                     flock, whole-tick
    ledger.jsonl                  append-only audit, one record per single os.write()
    bin/{smokin,smokin-run,smokin-emit,smokin-wait,smokin-notify}
```

`spool/tmp` and `spool/inbox` **must** be on one filesystem, and so must `tasks/<ID>/` and its
own `RECEIPT.json` staging file.

### 3c · The dispatch record — written before launch

```json
{"run":"r7f3c1","task":"T14","attempt":1,"dispatch":"pane","runtime":"codewhale",
 "cmd_file":".smokin/dispatch/T14.cmd","pid_or_pane":"w7:p9","started":"2026-08-05T14:02:11Z",
 "started_ns":1785931331000000000,"budget_s":3600,
 "placement":{"workspace":"w7","tab":"w7:t2","pane":"w7:p9"}}
```

**This is the artefact that makes a missing receipt mean something.** Without it, a cold
orchestrator staring at a task with no receipt cannot distinguish *never dispatched* from
*running right now* from *was running when the machine died*. The draft kept that distinction in
a live reaper process; a judge called that out, and it is now a file written before the child
starts.

It also carries `started_ns`, which is the completion gate's reference point — see 3e.

### 3d · The emitter

One program, `.smokin/bin/smokin-emit <TASK_ID> <source>`, reading a JSON blob on stdin. Every
runtime funnels through it. Order of operations is normative:

1. **Claim exclusivity.** `open(tasks/<ID>/.smokin/emit.lock, O_CREAT|O_EXCL)`. If it fails, append
   a `duplicate-emit` line to `ledger.jsonl` and **exit 0 immediately** — never wait. This is a
   mutex that is compatible with "never blocks", because the loser does not block, it leaves.
2. **Apply the completion gate** (3e). If it does not pass, write nothing and exit 0.
3. **Write the receipt atomically.** `tasks/<ID>/.RECEIPT.<pid>.tmp` → `fsync(file)` →
   `fsync(dir)` → `rename()` onto `RECEIPT.json`. **Never an in-place write.**
4. **Publish the pointer.** `spool/tmp/<seq>.json` → `rename()` → `spool/inbox/<seq>.json`.
5. **Exit within a hard 2s budget.** No retries, no network loops.

### 3e · The completion gate — turning "a turn ended" into "the task ended"

Every vendor completion signal that exists fires **per turn**, not per task. Claude's `Stop`,
Codex's `notify`, Codewhale's `turn_end`, OpenCode's `session.idle` — all of them (SUSPECTED,
from vendor docs and dossier probes; Claude's double-Stop on one task was observed in a probe and
is the strongest single piece of evidence). So the emitter must test a task-level discriminator.

**The gate:** `tasks/<ID>/FINDINGS.md` exists, is non-empty, and its mtime is **greater than
`dispatch/<ID>.json`'s `started_ns`**.

> **ADVERSARIAL FINDING (fatal, concurrency lens) — the draft's gate compared FINDINGS.md against
> `mtime(TASK.md)`, and the output contract simultaneously requires the agent to update the
> `**Status:**` line *in place inside TASK.md*. Write FINDINGS.md, then update the status line —
> the natural order, and the order Grillin's own contract implies — and `mtime(TASK.md)` is now
> newer, the gate fails, the emitter writes nothing and exits 0. No receipt, no error, silence
> until the reaper's timeout.**

Landed, and fixed above: the reference point is a **dispatch-time timestamp on an immutable
record**, not a mutable file the agent is contractually obliged to touch. The ordering of the
agent's own writes stops mattering.

### 3f · The receipt format

`schema: "smokin.receipt/1"`. Two status fields, not one:

```json
{"schema":"smokin.receipt/1",
 "seq":"r7f3c1:T14:1",
 "run":"r7f3c1","task":"T14","attempt":1,
 "terminal":"ok|failed|needs_input|crashed|reaped",
 "claim":"done|blocked|partial",
 "runtime":"codewhale","dispatch":"pane","source":"wrapper-exit|claude-stop|codex-notify|...",
 "placement":{"workspace":"w7","tab":"w7:t2","pane":"w7:p9"},
 "exit":0,"started":"...Z","ended":"...Z","wall_s":412,
 "result":"<final assistant text, UTF-8, truncated to 8192 bytes>",
 "artifacts":{"FINDINGS.md":"sha256:…","CHANGES.md":"sha256:…","QUESTIONS.md":null},
 "transcript":"tasks/T14/.smokin/transcript.log",
 "native":{"session_id":"…","transcript":"…"}}
```

**`terminal` is about the process. `claim` is about the work.** They are separate because a clean
exit 0 from an agent that gave up is the most common lie in this category, and collapsing them
into one enum is how you get it. A judge required this split and it is taken whole.

**`result` is the end result** — the thing the requester asked the ping to carry. Every runtime
can fill it from something specific, and three of them now do it from the transcript rather than
from a vendor state directory: Claude's `-p --output-format json` envelope at `.result`
(**CONFIRMED**, `result:"OK"`); Codewhale's `exec --auto --output-format stream-json` `content`
events, which must be **joined** because they are token chunks — a run counting to twenty emitted
`ele` then `ven`, so taking the last would put the word "twenty" in the receipt (**CONFIRMED**);
OpenCode's `run --format json` `text` part, which by contrast arrives **whole** and is taken as
the last (**CONFIRMED**). Codex's `notify` payload `last-assistant-message` remains SUSPECTED and
Codex remains absent from this machine.

> **Retracted:** the draft named Codewhale's `exec --json .output`, on the strength of a dossier
> probe returning `{"mode":"one-shot","success":true,"output":"OK"}`. That summary is real and it
> carries **no token field at all** — confirmed twice, once with real tool use — so the row moved
> to `stream-json` and `result` moved with it. The old citation was CONFIRMED and is now simply
> the wrong flag to be reading.

**The result *text* rides in the receipt; the result *artefacts* stay in the task folder as
paths and hashes.** Codex's own `notify` mechanism is documented to blow past OS argv limits
precisely because it inlines prompt history; a receipt that inlines a diff will find the same
wall in a different place.

**`usage` is an OPTIONAL key and the schema stays `smokin.receipt/1`.** It carries what the
runtime itself reported about the dispatch — `input_tokens`, `output_tokens`,
`cache_read_tokens`, `cache_write_tokens`, `reasoning_tokens`, and `cost_usd` *only from a
runtime that reports one*. Bumping to `/2` for a purely additive field would cost every reader
in this repo and in Grillin a version branch to gain nothing: a reader that does not know about
`usage` ignores it, which is what additive means. The three states are distinct on purpose and
a reader must not collapse them:

| receipt says | means |
|---|---|
| no `usage` key | the runtime reported nothing this path could see |
| `{"available":false,"reason":"pane-not-instrumented"}` | this **path** cannot see it — v1 measures headless only |
| `{"input_tokens":…}` | the runtime's own numbers, unconverted |

**A number the runtime did not report is ABSENT, never `null` and never `0`.** Codewhale reports
tokens and no cost anywhere; a `cost_usd: 0` there would be a lie that survives every later
average, and a price table this repository invents to fill the column would be the unearned
assertion §7 refuses. **Tokens and cost are not one capability**, and a schema that treats them
as one forces exactly that invention.

**Where the numbers come from is a row in `runtimes.json`, not a branch in the tick** (§4c). Two
descriptors — `result_from` and `usage`, each `{select, match, map}` — describe the three shapes
that actually exist: a single-line JSON envelope, a terminal NDJSON event, and per-step NDJSON
events that must be summed. The reader **scans** the transcript and keeps the last match; it
never slices the head or the tail, because `smokin-run` runs two racing `tee` processes and
stdout and stderr are CONFIRMED to interleave out of order. A line that does not parse is
skipped in silence — a torn interleaved write and a vendor banner are indistinguishable from
there, and neither is a defect.

### 3g · `seq`, the cursor, and the tick lock

> **ADVERSARIAL FINDING (fatal, concurrency lens) — three defects, all reachable in the first
> hour.** (1) The draft's `RECEIPT.json` was written **in place**, with two guaranteed concurrent
> writers per task: the wrapper's EXIT trap and the native hook, which for Claude is declared
> `"async": true` and therefore does not wait. Both pass the gate — a stat is not a mutex — and
> both write the same path; the shorter write leaves the longer write's tail behind and yields
> unparseable JSON in the one file that is both the durable record and the gate's subject.
> (2) `seq` was derived from nanosecond timestamps, so duplicate emissions carry *different*
> seqs and the stated dedup key never collides. (3) `done/` was the cursor and the pointer moved
> there **after** acting — so a `kill -9` between "dispatch the dependants" and "move the
> pointer" re-dispatches those dependants on the next tick, into the same worktree, on top of
> still-running copies. And the design's own advertised first hour is a `kill -9` mid-flight.

All three landed. All three are fixed structurally, not by care:

| Defect | Fix |
|---|---|
| Torn receipt | atomic publish (3d step 3) **plus** the `O_EXCL` per-task emit lock (3d step 1) so two emitters cannot both reach step 3 |
| `seq` never collides | `seq = "<run>:<task>:<attempt>"`, allocated **once**, in the dispatch record. Nanoseconds survive only as a filename sort prefix, and the design stops claiming filename order is completion order — `CLOCK_REALTIME` is not monotonic |
| Replay window | **claim before acting.** `rename(inbox/x, done/x)` is the exclusive claim — the only race-free primitive available — *then* act, with the action keyed by `seq` so a crash after the claim is recovered from `RECEIPT.json` rather than by replaying the pointer |
| Two ticks racing | `flock` on `.smokin/tick.lock` for the whole tick. A second tick exits 0 with *"another tick holds the lock"*. This matters because phase 10 wires `SessionStart` to run a tick, which is precisely when a second one already exists |

**Unparseable or hash-mismatched receipts have defined behaviour**, which the draft lacked: a
receipt that will not parse, or whose `artifacts` hashes do not match the files on disk, is
recorded in `ledger.jsonl` as `stale` and treated as **absent** — the task falls to the reaper.
It is never silently believed. A committed `RECEIPT.json` survives a later `git checkout` that
reverts the work it describes; the hashes exist so a cold reader can notice.

### 3h · The reader

`.smokin/bin/smokin-wait` — a small python3 program using `inotify_init1` +
`inotify_add_watch(IN_MOVED_TO)` + `select()` through `ctypes`.

**CONFIRMED on this machine:** `python3 -c "import ctypes; ...inotify_init1(0o4000)"` returned a
valid fd 3. **CONFIRMED:** `inotifywait` is *not* installed (`inotify-tools` absent), so Smokin
ships its own reader and must never shell out to it.

The algorithm is normative, and the order is the whole startup race:

1. Establish the watch.
2. **Then** scan `inbox/`.
3. On any event, do a full rescan and **ignore the event payload**.
4. Treat `IN_Q_OVERFLOW` as *rescan everything*.

Get 1 and 2 the wrong way round and every fast task that finishes during startup is lost.

**`smokin wait` is an optimisation, not the interface.** The interface is `smokin tick`, which any
process can re-run at any time. `smokin run` is `while ! tick; do wait; done`. This is deliberate:
a blocking reader is itself a process that can die, and the design refuses to have its correctness
depend on one.

### 3i · The reaper — a missing receipt is a result

`smokin reap` (a pass **inside** the tick, not a daemon) compares each `dispatch/<ID>.json`
against the wall clock. Past `budget_s` with no receipt, it synthesises one:
`terminal: "reaped"`, `exit: null`, the last 20 lines of `transcript.log` as `result`, and — for a
pane — a dump of `herdr agent explain <role> --json` into `tasks/<ID>/.smokin/explain.json`
(SUSPECTED; the command exists per ground truth, the dump has **not** been exercised here).

**The reaper must not be a background process.** The draft ran it `setsid ... &` and a judge
named the consequence: a dead reaper turns a crashed pane into an orchestrator that waits forever,
which is the exact failure Smokin exists to delete. Because the deadline is computable from
`dispatch/*.json` plus the wall clock, any foreground tick can evaluate it, so nothing needs to
be alive between ticks.

### 3j · Where herdr fits

Nowhere in the completion path. herdr is used for what it is good at — creating panes and
worktrees, making a fleet visible to a human, and toasting on completion — and the tick never
asks it what any agent is doing, *including the agents it can classify*.

That is not a preference. **CONFIRMED by adversarial probe:** `herdr agent list` on this machine
returned six agents, **all** labelled `agent:"claude"`, including `w5:p1` and `w5:p2`, which are
bare login shells (`terminal_title:"user@host: ~"`, `revision:1`,
`state_change_seq:0`) reported as `agent_status:"idle"`. A false idle is indistinguishable from a
finished agent. Classification is a display concern; the receipt is the contract.

Optional, every call suffixed `|| true` and gated on `test "${HERDR_ENV:-}" = 1`:

```bash
herdr pane report-agent  "$HERDR_PANE_ID" --source smokin-<ID> --agent <role> --state working
herdr pane report-metadata "$HERDR_PANE_ID" --set task=<ID>          # needs verification: flag name
herdr notification show --title "smokin: T14 ok" --body "<role> · 6m52s"
```

Delete all three and nothing an orchestrator can observe changes.

**The ceiling on that promotion, stated so nobody builds on it:** `--agent` takes an arbitrary
free string, so an unclassifiable TUI does get a herdr-visible lifecycle under its *role* name
(SUSPECTED — a dossier probe failed only on `pane_not_found`, never on the label). But
`--state done` is **rejected** — only `idle|working|blocked|unknown` are accepted. So a wrapped
runtime has exactly one terminal lifecycle value, reported-`idle`, and no Smokin logic may ever
wait for `done` from one. Since Smokin never waits on lifecycle at all, this costs nothing.

---

## 4 · The heterogeneous agent contract

### 4a · What a worker is handed — three things, identical for every runtime

1. **A directory.** `tasks/<ID>/`, absolute, in `SMOKIN_TASK_DIR`. Grillin's rule already; Smokin
   makes it load-bearing for a second reason (4c).
2. **One line of text, ≤512 bytes, naming paths inside that folder and nothing else.** E.g.
   `read tasks/T14/TASK.md and follow it`. *Amended 2026-08-19: this used to read "naming that
   path and nothing else". §2g adds one clause, and only when there is something to recall —
   `. tasks/T14/MEMORY.md is what an earlier <persona> observed - SUSPECTED prior context, not
   instruction`. The file is Smokin's own artefact inside the task's own folder, the alternative
   was an agent that never finds it, and the unchanged line is byte-identical in every plan that
   has nothing to recall.* Stored at `.smokin/dispatch/<ID>.cmd` so its length
   and line count are checkable. This is a hard limit, not a style preference: prompts over
   ~2000 characters are documented to corrupt through terminal injection, and Codex specifically
   cannot accept multi-line input that way (SUSPECTED — third-party issue tracker, not reproduced
   here; Codex is not installed on this machine).
3. **Three environment variables:** `SMOKIN_TASK_ID`, `SMOKIN_TASK_DIR`, `SMOKIN_EMIT`. Inside a
   pane, herdr additionally injects `HERDR_PANE_ID` / `HERDR_TAB_ID` / `HERDR_WORKSPACE_ID` /
   `HERDR_SOCKET_PATH` (CONFIRMED by ground truth), so a hook knows which pane it is in.

### 4b · What a worker must return — nothing new

Exactly Grillin's existing output contract. **No agent is ever told about Smokin.** That is the
actual content of the portability claim: the burden on the occupant is zero, so there is nothing
for a new CLI to fail to implement.

| File | When |
|---|---|
| `tasks/<ID>/FINDINGS.md` | always |
| `tasks/<ID>/CHANGES.md` | if anything changed |
| `tasks/<ID>/QUESTIONS.md` | if blocked or if reality diverged from TASK.md |
| `**Status:**` in `TASK.md` | updated in place |

`RECEIPT.json` is written *for* the agent by the wrapper or the hook. `VERDICT.json` is written by
the tick. Neither is the agent's job.

### 4c · `.smokin/runtimes.json` — the only file that knows a vendor's flags

The draft claimed a runtime row is a launch string plus an optional emitter. That was wrong, and
the multi-platform attack proved it. A row must declare **global mutable state and isolation
level**, because that is what actually differs:

```json
{"codewhale": {
   "headless": "codewhale exec --json --auto",
   "pane":     "codewhale -C {WT} --skip-onboarding",
   "hook_scope": "global-only",
   "global_config": "~/.codewhale/config.toml",
   "holds_credentials": true,
   "approval_flag": "--auto", "approval_default": "off",
   "sandbox_vocabulary": "auto",
   "wrapper_trap_reliable": false,
   "blocked_reportable": {"headless": false, "pane": "unverified"},
   "fixed_port": 7891,
   "nested_multiplexer": "codewhale lane (own tmux socket)"}}
```

Every one of those fields exists because a probe found a difference the draft's abstraction hid.
The approval models alone are non-isomorphic three ways: Codewhale without `--auto` returns
`"mode":"one-shot"` with no tools and still reports success (CONFIRMED by probe artefact
`{"mode":"one-shot","success":true,"output":"OK"}` while no file was written); OpenCode's `--auto`
defaults false and its permissions persist **per project in one global SQLite database** shared
by every session on the machine, not per worktree (SUSPECTED); Codex uses a third vocabulary
entirely, `--sandbox workspace-write -a never` (SUSPECTED — Codex is **CONFIRMED absent** here:
`command -v codex` → MISSING, and `~/.codex/` holds only a `pets/` directory).

**"Zero lines in the tick" is only true once those differences are data.** They are data now.
They were undocumented per-vendor knowledge before.

### 4d · The emission paths

| # | Path | Applies to | Status |
|---|---|---|---|
| 1 | **Wrapper** — `smokin-run <ID> -- <cmd…>`, forks the child, waits, traps EXIT, emits | every dispatch | the floor, but see 4e |
| 2 | Claude `Stop` hook via `claude --settings tasks/<ID>/.smokin/hooks.json` on argv | claude | SUSPECTED, and see §9 for a serious risk |
| 3 | Codex project-local `<worktree>/.codex/hooks.json` `Stop`, backstopped by global `notify` self-routing on the payload's `cwd` | codex | SUSPECTED — untestable here, Codex absent |
| 4 | OpenCode SSE `GET /event?directory=<abs worktree>` → `session.idle` → pull `GET /session/{id}/message` | opencode | SUSPECTED; requires one resident subscriber, see §9 |
| 5 | Codewhale **global** `[hooks]` `turn_end` calling a task-agnostic `smokin-notify` that self-routes on `CODEWHALE_WORKSPACE` | codewhale panes | rewritten — see §5 |
| 6 | **Reaper** synthesises from the dispatch record | anything silent | the real floor |

Paths 2–5 are *accelerants*: they reduce latency and enrich `result`. Path 1 is the contract and
path 6 is the guarantee. Delete every accelerant and Smokin still terminates on a complete result
set — later, and with a thinner `result`.

### 4e · The wrapper must not `exec`

> **ADVERSARIAL FINDING (high, multi-platform lens)** — the draft specified the wrapper as
> *"Execs the real command, traps EXIT"*. **CONFIRMED by probe: a wrapper that `exec`s is
> replaced, and its EXIT trap never fires.** The universal floor was not a floor.

Fixed: `smokin-run` forks the child and waits. It also tees the child's stdout and stderr to
`tasks/<ID>/.smokin/transcript.log` — in the task folder, not as a pointer into `~/.claude` or
`~/.codex`, because a pointer into a vendor's state directory is not reconstructable from the
repository and therefore violates principle 14.

A second probe result is worse and is **not** fully fixed: running `codewhale -C <wt>
--skip-onboarding` under a *non-exec* trapping wrapper in a pty, the wrapper logged
`WRAPPER_START` and then never emitted — Codewhale held the pty for the full budget, and its own
teardown prints `Session terminated, killing shell...`. See §5 and open question **Q1**.

---

## 5 · The Codewhale case

**CONFIRMED by ground truth:** Codewhale is not one of herdr's 21 `agent start --kind` values and
not one of its 16 `integration install` targets. herdr cannot classify its lifecycle. It can only
run as a plain pane process.

### 5a · Under this design that costs nothing, and the reason must be stated the right way round

The tick never asks herdr what *any* agent is doing — see §3j, and the CONFIRMED evidence there
that herdr reported two bare login shells as idle `claude` agents. Classification is a display
concern. The receipt is the contract. Said that way round, the multi-platform claim is
load-bearing; said the other way round ("we tolerate Codewhale") it is decoration.

### 5b · Headless Codewhale is the *strongest* occupant in the fleet, not the weakest

**CONFIRMED by probe:** `codewhale exec --json --auto`, stdin from `/dev/null`, stdout to a pipe,
returned rc=0 with `{"status":"completed","termination_reason":"resolved","tools":[{"name":
"write_file","success":true}]}` and **actually created the file** — including in a workspace not
listed as trusted, so trust does not gate headless. `codewhale exec --json` also returns
`{"mode":"one-shot","provider":"codewhale","success":true,"output":"OK"}`.

That is a machine-readable done-ness verdict *plus* the end result, from a process exit. It is
more than Claude's `Stop` hook gives, and strictly more than any herdr lifecycle state gives.
Routing clause 5 does not fire for Codewhale: it goes in-process like everything else unless the
task declares `Interrupt`/`Watch`.

### 5c · Codewhale **panes** are where the draft was wrong

> **ADVERSARIAL FINDING (high, multi-platform lens) — emission path 5 as drafted does not exist.**
> A `<worktree>/.codewhale/hooks.toml` with a `turn_end` hook was written and a full turn run in
> that worktree: **the hook never fired and no output file was created.** `codewhale config list`
> enumerates the whole config surface and contains **no `hooks` key**. The only hook mechanism
> with evidence of ever firing is a single **global** `[hooks]` / `[[hooks.hooks]]` table in
> `~/.codewhale/config.toml`.

Consequences, and the rewrite:

| Problem | Rewrite |
|---|---|
| Hooks are machine-wide, so a hook command carrying a literal task id fires for *every* pane | The hook command may **never** contain a task id. It invokes a task-agnostic `smokin-notify` that self-routes on `CODEWHALE_WORKSPACE` (present in the hook env — CONFIRMED by a probe artefact containing `CODEWHALE_WORKSPACE`, `CODEWHALE_SESSION_ID`) against `.smokin/dispatch/*.json`. This is precisely the pattern the design already accepts for Codex's un-scopable `notify` |
| `codewhale config set 'projects."<abs>".trust_level' trusted` exits 0 and writes a **literal top-level quoted key**, not a `[projects."…"]` table — so the trust bootstrap silently no-ops and project hooks stay inert | **Forbid `codewhale config set` for the bootstrap.** Parse and re-emit TOML, hold an exclusive `flock` on `~/.codewhale/config.toml` for the whole read-modify-write, verify the *table* exists afterwards, and abort the dispatch if it does not |
| That file holds the provider API key in plaintext (twice) and Codewhale **re-serialises the whole file** on any `config set`; a `config.toml.bad` already exists on disk from a prior probe | The bootstrap asserts `api_key` is still present after writing, and never copies the file into a task directory |
| Codewhale's TUI is pure alternate-screen (`ESC[?1049h`, `ESC[?2026h`) and fully redraws | **`herdr pane wait-output` is banned as a completion detector** for it — and for everything. A sentinel printed into an alt-screen pane provably never reached herdr's scrollback (SUSPECTED, dossier probe). Watch the filesystem, never the screen |
| `codewhale lane` spawns its own tmux server on its own socket; `codewhale app-server` binds a **fixed** port 7891 | Both are declared in the runtimes row (4c) and neither is used by Smokin. A fixed port means two concurrent plans collide |

### 5d · The honest boundary

> ### The boundary of that claim
>
> Smokin's contract is uniform for **headless** dispatch across every runtime tested. It is **not**
> yet uniform for **panes**, because pane instrumentation depends on per-project hook scoping and
> **no runtime examined here has it**: Codewhale's hooks are global (CONFIRMED), Codex's `notify`
> is global (SUSPECTED, vendor docs), and Codex's project-local `Stop` hook is untestable on this
> machine. For panes, the wrapper is the floor and the reaper is the guarantee — and for Codewhale
> specifically the wrapper floor is **unproven** (§4e, Q1).

The generalisation is still the right one: the entry condition for being a first-class Smokin
runtime is *can be started by a shell command and can write a file into a directory*. It is not
*is one of herdr's 21 kinds* and not *has a hook system*. Every runtime examined clears that bar.
What the attack removed was the claim that panes clear it as cleanly as headless does.

---

## 6 · Codewhale, Claude, Codex, OpenCode — what is actually installed

**CONFIRMED, `command -v`, 2026-08-05:**

| Runtime | Path | Headless dispatch | Pane dispatch |
|---|---|---|---|
| claude | `~/.npm-global/bin/claude` | yes | yes, with the §9 settings risk |
| opencode | `~/.opencode/bin/opencode` | yes | yes, needs a resident SSE subscriber |
| codewhale | `~/.npm-global/bin/codewhale` | **yes, best-instrumented** | unproven (Q1) |
| aider | `~/.local/bin/aider` | untested | untested |
| herdr | `~/.local/bin/herdr` | n/a — substrate | n/a |
| **codex** | **MISSING** | — | — |
| **gemini** | **MISSING** | — | — |
| **cursor-agent** | **MISSING** | — | — |

**This is why one validator bug is load-bearing and not a footnote.** `/bin/sh` on this machine is
`dash` (CONFIRMED, `ls -l /bin/sh` → `dash`), and dash reports a missing binary as
`sh: 1: codexnotreal: not found`, rc=127 — **CONFIRMED by running it.** The validator's `blew_up`
regex — `scripts/validate-plan.py:264-268` in the working tree, inside `check_gates_fail_first()`
— carries `command not found`, not `not found`, so it does not match; the branch falls through to
*"gate fails cleanly ... as a gate should"*. A gate that shells out to `codex` on this machine
reads as **healthy** today.

Smokin's answer is two-part: a floor forbidding agent binaries in done-commands (§7), and the
one-line regex fix, landed in the same edit. It is the highest-value line of code in the whole
proposal and it is not Smokin's — it is a defect in Grillin that Smokin happened to trip over.

---

## 7 · The non-negotiables

The requester wants Smokin to be *a solid non-negotiable part of the infrastructure once
configured*. Before the list, the finding that decides what that sentence can honestly mean.

> **ADVERSARIAL FINDING (fatal, "non-negotiable" lens) — nothing runs the validator.**
> **CONFIRMED:** `grep -rn validate-plan ~/grillin/` returns hits only in `README.md`,
> `QUICKSTART.md` and `examples/README.md` — documentation. `templates/hooks.json.template`
> declares six hook registers and **not one** invokes it; every one runs `awareness.sh`, whose own
> contract is non-blocking. `.git/hooks/` holds only samples. Further: `--run-gates` is opt-in and
> its absence prints a *note* and returns exit 0, and `require_gates_run` is **not** in `FLOORS`
> — CONFIRMED by reading `scripts/validate-plan.py` at the `FLOORS` block (`:38`) and at `:383-387`. So the one check Smokin
> leans on is the only check a caller can skip, and skipping it is not a failure.

**There is therefore no "once configured" state today.** Enforcement is a human typing a command.
Two changes are required before the word is earned, and both are edits to Grillin that this
document does not make:

1. Add `require_gates_run: True` to `FLOORS` and invert the flag to `--skip-gates`, whose use is
   itself a FAIL.
2. Add a `SessionStart` entry to `hooks.json.template` running the validator and surfacing a
   non-zero exit.

Until both land, **every row below marked ENFORCEABLE is enforceable-in-principle, and advisory in
practice.** That is the honest state and it is stated here rather than in a footnote.

| # | Non-negotiable | Status | The check |
|---|---|---|---|
| 1 | Every `TASK.md` declares `**Dispatch:**` ∈ {inproc, pane}; if `pane`, also `**Runtime:**`, `**Budget:**`, `**Interrupt:**`, `**Watch:**`, `**Blockable:**` | **ENFORCEABLE** | new `check_dispatch_declared()`, floor `require_dispatch_declared` |
| 2 | The declared `Dispatch` does not contradict its own premises under §2b | **ENFORCEABLE, weakly** | new `check_route_declared_consistent()`. Honest: catches contradiction, not preference — see §2e |
| 3 | No done-command invokes an agent binary (`claude`, `codex`, `codewhale`, `opencode`, `aider`, `herdr`, `curl`); `argv[0]` restricted to an allowlist | **ENFORCEABLE** | new `check_no_binary_in_gate()`, **plus** the `not found` regex fix at `validate-plan.py:264-268`. §6 shows why |
| 4 | Every done-command references a path under its own `tasks/<ID>/` and none outside it | **ENFORCEABLE** | new `check_gate_inside_task_folder()`. The validator runs gates with `cwd=plan` (CONFIRMED, `:222`), so an unanchored gate tests someone else's work |
| 5 | Every `TASK.md` links `[../_SMOKIN.md](../_SMOKIN.md)` | **ENFORCEABLE, free** | the **existing** `check_references()` rglobs every `*.md` and fails on an unresolvable relative link (CONFIRMED, `:257-274`). Adding the line to `TASK.md.template` makes the contract file mandatory with zero new Python — the same lever that already makes `_RULES.md` mandatory |
| 6 | `**Agent:**` matches `^[a-z][a-z0-9_-]{0,31}$` and is not one of herdr's 21 kind labels | **ENFORCEABLE** | new `check_role_name()`. Principle 15; five agents called `claude` is not a fleet. **"is unique across the plan" is RETRACTED** — never implemented, contradicted by Grillin's own `minimal-passing-plan` (T2 and T3 both declare `implementer`), and incompatible with §2f, which needs a repeated persona to have anything to reuse |
| 7 | Every pane task's `## Do NOT` forbids opening panes or spawning sub-agents | **ENFORCEABLE** | new `check_no_nested_dispatch()`. One orchestrator level: the script opens panes, panes do not |
| 8 | Concurrent pane tasks' `## What you own` path sets are disjoint | **ENFORCEABLE** | new `check_paths_disjoint()` over the graph the validator already parses. Same-file collision is the most-reported failure in the prior art |
| 9 | Pane count does not exceed the SCALING size row's `paneCeiling` | **ENFORCEABLE, provisional** | new `check_pane_ceiling()`. The number is an opinion (§2d) and ships flagged provisional |
| 10 | `## Done means` runs the task's **own substantive command** and its result is recorded in `VERDICT.json` by a second hand | **ENFORCEABLE** | new `check_verdict_from_task_gate()` — see the finding below |
| 11 | `.smokin/dispatch/<ID>.cmd` is one line, ≤512 bytes | **ADVISORY at authoring time / ENFORCED AT DISPATCH** | the file does not exist until the tick creates it. Enforced fail-closed inside `smokin tick`, before launch |
| 12 | `st_dev(spool/tmp) == st_dev(spool/inbox)` and the same for `tasks/` | **ADVISORY at authoring time / ENFORCED AT DISPATCH** | same reason, plus it is TOCTOU: sampled on the validating host, used later and possibly elsewhere |
| 13 | Emitter programs exist and are executable | **ENFORCED AT DISPATCH, before any gate runs** | a gate that calls a missing script fails as `not found` — which is the §6 bug — so this must run *first*, not alongside |
| 14 | `**Watch:**` is a truthful declaration that a human will look | **ADVISORY. It is taste, and no check can make it otherwise** | named as such at phase 0, where a reader can argue with it |
| 15 | `.smokin/doctor.json` is committed and current | **ADVISORY** | phase 9 material; a checklist tick, not a floor |

> **ADVERSARIAL FINDING (fatal, "non-negotiable" lens) — the draft's `require_receipt_in_gate`
> mandated a regression.** It forced every pane task's `## Done means` to be
> `test -f tasks/<ID>/RECEIPT.json`. A probe wrote a `RECEIPT.json` plus a two-line `FINDINGS.md`
> with zero real work: **gate exit 0.** Worse, `validate-plan.py:244-245` is
> `if status == "DONE": continue` (CONFIRMED by reading it), so once the tick marks a task DONE
> the gate is never re-run — meaning the receipt gate is only ever validated in the state where
> `test -f` on a not-yet-written file trivially fails. The one floor with reliable teeth would
> have downgraded Grillin's most load-bearing check into a liveness probe.

**Landed, and the floor is deleted.** Replaced by #10 above. The rule is now:

- `RECEIPT.json` is the agent's **claim**. It may be a *precondition* of the gate. It may never
  *be* the gate.
- `VERDICT.json` is the project's **verdict**, written by the tick when it re-runs the task's own
  `## Done means` command — a second hand, which is principle 8 applied one level down, and which
  `awareness.claimsVsEvidence` already demands in words: *a DONE status is a claim; it is evidence
  only once the task's own done-command has run and that fact was recorded.*
- The tick writes verified task ids into `.awareness/verified`, which is the file
  `awareness.sh.template` already reads to render `done — verified` distinctly from
  `done — claimed, ungated`.
- **Open:** the `if status == "DONE": continue` skip means no gate is ever re-run in the state that
  matters. A post-hoc `--recheck-done` mode is proposed; it is an edit to Grillin, not to Smokin.

### 7a · The one new principle

Smokin proposes **one** addition, not two, and not the one the draft chose:

> **17. A missing receipt is a result.** A fleet that reports only its successes cannot be waited
> on. The dispatch record is written before the work starts so that silence past a deadline is a
> message rather than an absence.

"The orchestrator holds no state" is *not* proposed as principle 18: it restates principle 14,
and a method that tells authors not to duplicate should not duplicate. The stateless tick is
cited under principle 14 as its mechanism.

### 7b · Five new anti-pattern rows

In the exact register — bare imperative left, lowercase consequence fragment right, no terminal
periods. Count moves 25 → 30.

| Don't | Because |
|---|---|
| Open a pane to get parallelism | parallelism is free in-process; a pane is bought with a screen and paid for in review capacity |
| Wait on an agent's lifecycle instead of its receipt | a runtime herdr cannot classify has no lifecycle to wait on, and `unknown` is not a result |
| Call an agent binary from a done-command | the gate then tests whether the tool is installed, not whether the work is finished |
| Hand the adversarial pass an agent that has already run something | a reused agent is a continued session, and the task still carries the declaration saying it is not |
| Write down a lesson without the command that produced it | advice nobody can re-run reads exactly like a fact, and the next agent cannot tell them apart |

*The last two rows are the only anti-patterns here a tool can ENFORCE rather than describe.
The fourth is §2f: Grillin's `check_adversary_context` can only read the sentence a task
declares, and `smokin tick` is the half that decides who actually gets the pane. The fifth is
§2g's write guard, which refuses the entry outright — and it is worth noting that the enforcement
is structural, not semantic. Nothing grades the prose; what is required is the field that lets a
reader check it.*

---

## 7b · Plan-level invariants — what the plan must not break

> **Numbered 7b, not 8.** §§8–12 are cited by number from other files and from code. Renumbering
> them to make room would break those citations to gain nothing, so this sits beside the
> non-negotiables it extends. Same trade Grillin's `OPERATING-THE-PLAN.md` made for the same reason.

Everything else in this document measures **completion**: did the task finish, was its claim true,
did its own gate pass. Nothing measures **blast radius** — what a task broke on its way to passing.
A task can satisfy `## Done means` perfectly and take a neighbour down doing it, and every mechanism
described above will report success, because no done-command is pointed at anything the task was not
supposed to touch.

`_INVARIANTS.toml` is that reading. Opt-in by file, at the plan root, `[[invariant]]` per entry —
the same shape and the same discipline as `_RULINGS.toml`:

- **A missing file means the layer is off**, and nothing changes.
- **A file that exists and is broken is LOUD and refuses to run.** Half an invariant set is a wrong
  invariant set, and a plan guarded by rules nobody wrote is worse than one guarded by none.
- **`because` is mandatory.** The person who reads the halt is not the person who wrote the command.

Each invariant is a command, run once before the plan moves to capture a **baseline**, then re-run
at every tick boundary and by `smokin verify`. The default mode is `unchanged` — no literal is
pinned, because nobody knows what the right answer looks like, only that it must be the *same*
answer afterwards. `equals` and `matches` pin a literal where one is known, and **a pinned
expectation is checked at baseline too**: one already false before the plan runs refuses the
capture, because halting on it at tick 2 would blame the plan for something it did not break.

**A break is a halt, not a warning.** The evidence rides on `HALT.json` so it survives a re-render.

**Where it came from.** A deploy in which `certbot` silently added one `listen` directive, making a
new vhost the default for loopback HTTPS and serving two neighbouring sites the wrong certificate.
Every task in that job passed its own check. No done-command anyone would write was ever going to
look at the neighbours' certificate subject line, because the neighbours were not the work.

**`curl` is allowed here and barred from a done-command** (§7 non-negotiable 3). That is deliberate
and the reason is worth stating: in a gate, `curl` tests the network instead of the work; in an
invariant, the network *is* the reading. Agent binaries stay barred in both — an invariant that
shells out to an agent measures whether the tool is installed, forever.

**Editing the file mid-run halts** rather than silently re-baselining. `smokin invariants <plan>
--recapture` is the ceremony and it goes in the ledger; silently re-baselining is the node quietly
becoming the curator, which is the first failure mode in `DELEGATION-NODE.md` §8.

**The honest limits**, stated here rather than in a footnote:

- **A baseline taken late records the damage as normal.** If the plan has already run, capture
  measures the broken state and calls it correct.
- **A probe is trusted to be read-only.** Nothing verifies that; a command that mutates is a
  measurement that changes what it measures.
- **An unchanged reading is not a correct reading.** It is the same reading. That distinction is the
  one that failed on the reference deploy, where a real 404 was asserted as a cause it did not have.

**Grillin gates the declaration; Smokin owns the execution.** `check_invariants` in
`validate-plan.py` refuses a `_INVARIANTS.toml` that would load-fail, so an author finds out before
handover rather than at tick 1 — and it refuses one more thing this side cannot see: an invariant
whose command is a task's own done-command, which is a completion check wearing an invariant's
clothes. The two validators are asserted against each other by
`grillin/tests/test-config-contract.py`; on its first run that assertion found a real divergence in
the roster lookup, which is what it is for.

---

## 8 · Where it lands in Grillin

**Grillin is untouched by this document.** Below is the exact change set a future implementation
would make, and nothing more.

### 8a · No twelfth phase

Eleven stays eleven. Smokin is a substrate plus a shaping question, landing in phases 0, 4, 5, 7,
8, 9 and 10.

| Phase | Change |
|---|---|
| **0** | One new shaping question (8b) |
| **4** | Second table beside the existing on/off/reduced table: *task · dispatch · runtime · which clause decided it* |
| **5** | `TASK.md.template` gains six header fields and one link line; `taskContract.outputs` gains `RECEIPT.json` and `VERDICT.json`. `layout.minimumAtEverySize` stays **four** items — at XS there are no panes, so there are no receipts |
| **7** | `_WORKTREES.md.template` gains a `## 3b · Placement` section; the plan root gains a generated `PLACEMENT` file in the `OWNERS` register |
| **8** | `substrates` gains a third slot — a **schema change**, not a data addition (8d) |
| **9** | `smokin doctor` is phase-9 work: probe every runtime, confirm python3 and inotify, confirm `st_dev` equality, and write `.smokin/doctor.json`. Phase 9 is ⚑ never-skip, which is the right home for it |
| **10** | `hooks.json.template` gains a `SessionStart` entry running `smokin adopt && smokin tick`; `awareness.sh.template` gains a `smokin` surface mode |

### 8b · The shaping question — and the seam it repairs

New question: **"Must any worker be watched, steered or interrupted while it runs, or run a CLI
the orchestrator cannot host?"**
YES → Smokin is the declared substrate; `_SMOKIN.md` is copied in; every task declares `Dispatch`;
the pane ceiling applies. NO → programmatic fan-out, `Dispatch: inproc` everywhere, and
`_SMOKIN.md` is **not** copied, because a substrate nobody uses is a file that rots.

**This also repairs a contradiction already in the repo, and the method's rule is never to resolve
one silently — so it is written down here.** CONFIRMED by reading:

| Source | Says |
|---|---|
| `GRILLING-THE-PLAN.md:62` | "five questions" |
| `GRILLING-THE-PLAN.md:66-67` | "Size is the sixth axis" |
| `QUICKSTART.md:27` | "Six questions that decide the shape" |
| `QUICKSTART.md:43` | "Write the **five** answers" |
| `SCALING.json` `shape.questions[]` | six entries, the sixth being `{"n":6,"ask":"How many tasks, roughly?","yes":"see scaling","no":"see scaling"}` — a degenerate row that is not a yes/no question |

The proposal: the Smokin question takes `n=6` as a real question, size is stated as the axis it
already is rather than as a question, and the prose counts are corrected in both files. **This is
a plan amendment under principle 13 and needs a dated receipt** pointing at the clause it changes.

### 8c · New files

| Path | What |
|---|---|
| `templates/_SMOKIN.md.template` | H1 `# Smokin rules — the substrate that survives its own orchestrator`. Authority-form opening (the `_RULES` / `_WORKTREES` form: *"One copy. … this file wins and one of them needs fixing."*). Middle-dot sections: `## 0 · Confirm the tick is the orchestrator` · `## 1 · The routing rule` · `## 2 · The receipt` · `## 3 · The spool` · `## 4 · Placement` · `## 5 · Ceilings` · `## 6 · Per-runtime wiring` · `## 7 · Do NOT` · `## 8 · The boundary of that claim` |
| `templates/smokin.sh.template` | the tick: `doctor · adopt · tick · run · wait · status · reap · reset` |
| `templates/smokin-run.sh.template` | the wrapper — **forks, never `exec`s** |
| `templates/smokin-emit.py.template` | the single emitter, `O_EXCL` + atomic publish |
| `templates/smokin-wait.py.template` | the inotify reader, ctypes, watch-before-scan |
| `templates/smokin-notify.py.template` | the global self-routing hook target for Codewhale and Codex |
| `templates/runtimes.json.template` | the capability table of §4c |

### 8d · `SCALING.json` — the schema change

`substrates` is today a **two-slot object** (`default`, `secondary`) — CONFIRMED by reading it.
There is no array and no third slot. Adding Smokin is a schema change:

```json
"third": {
  "id": "smokin",
  "rules": "templates/_SMOKIN.md",
  "how": "an idempotent tick dispatches from disk and reaps receipts; panes are an escape hatch under a stated rule",
  "buys": ["survives orchestrator death — the frontier is re-derived from files",
           "heterogeneous by construction — a runtime is a row, not a code path",
           "a missing receipt is a message, so the result set is total"],
  "costs": ["a wrapper on every launch and a capability table to maintain",
            "the tick is only as fresh as its last run — latency, not loss",
            "no mid-flight intervention unless a pane was opened for it"]
}
```

**`substrates.invariant` must be amended, and that amendment is itself a plan amendment.** It
currently reads *"Declare the substrate once and do not mix mid-run."* Smokin — scripts for
control flow, panes for lifecycle — reads as exactly the forbidden mixture unless it is named as
one substrate. The amendment needs a dated changelog entry, referenced both ways, per principle
13 and the receipt-versus-substitute rule.

Also in `SCALING.json`: `principles[]` 16 → 17, `antiPatterns[]` 25 → 28, `shape.questions[]`
sixth row replaced, `taskContract.outputs` extended, `scaling[]` rows gain `paneCeiling`
(provisional), and a new top-level `receipts{}` block for the schema.

### 8e · The mirrors — four places or it drifts

CONFIRMED counts today: 16 principles, 25 anti-patterns, 11 phases, 89 checklist items.

| Artefact | Edit |
|---|---|
| `GRILLING-THE-PLAN.md` | `## Sixteen principles` → `Seventeen` (heading **and** the word), 3 anti-pattern rows, phase-0 question row, phase-4 second table, phase-8 third substrate |
| `SCALING.json` | as 8d |
| `index.html` | `M.principles[]` (numbered by array index at `:326`), `M.anti[]`, and the S-row phase list which **already disagrees** with `SCALING.json` — S omits phase 5 in `index.html` while `SCALING.json` includes it and `README.md` says "Phase 5 reduced". A pre-existing drift, recorded here, not fixed by Smokin |
| `README.md:57` | "Eleven phases, sixteen principles" → seventeen |
| `templates/GRILL-CHECKLIST.md` | six ticks under the **existing** `## Against the substrate` heading (which already carries declare-once and role-name), 89 → 95 |
| `scripts/validate-plan.py:8` | the hardcoded prose "an 89-item checklist … and 25 anti-patterns" moves with them |

### 8f · The validator edits, in full

`scripts/validate-plan.py`: nine new `FLOORS` keys, nine new `check_*()` functions, nine calls in
`main()` (currently `:376-384`), one flag inversion (`--run-gates` → `--skip-gates` plus
`require_gates_run`), and **one bug fix that is not Smokin's**: add `not found` to the `blew_up`
regex at `:264-268`.

There is no hook, no plugin point and no config-driven check list — hardcoded calls in `main()`
are the only way in, and `FLOORS` is one-directional, so a new floor set `True` can be tightened
by a `--config` file and never disabled. **That is the only shape Grillin has for the word
"non-negotiable", and everything Smokin writes into `SCALING.json`, `_SMOKIN.md`, the checklist
and `index.html` is, by construction, advice.** The honest size of the mechanism is nine floors
and nine functions; every other page is documentation.

---

## 9 · Failure modes

Stated as failures, not as risks, because a risk register is a way of not saying something.

| # | Failure | Severity | Status |
|---|---|---|---|
| 1 | **The tick is only as fresh as its last run.** If nothing ticks, receipts sit in the spool and the plan is complete-but-unreaped | by design | The price of refusing a resident listener: paid in latency, never in lost work |
| 2 | **Claude's per-pane `--settings` may REPLACE rather than MERGE.** If it replaces, injecting a Smokin `Stop` hook silently disables herdr's own `herdr-agent-state.sh` **and** Grillin's `awareness.sh` PreCompact/SessionStart hooks | **highest** | UNTESTED. The completion mechanism would switch off the amnesia mechanism, invisibly, until somebody wonders why `PROGRESS.md` stopped updating. **No `--settings` path ships until both hook sets are observed firing together** |
| 3 | **Codewhale panes may produce no wrapper receipt.** It holds the pty and prints `Session terminated, killing shell...` | high | See Q1. Today a Codewhale pane degrades to a reaper timeout |
| 4 | **No `fsync` = no crash durability, in the draft.** Fixed in §3d, but the parent-directory sync is the half that matters and is easy to drop in implementation | medium | Fixed in design; must be verified in code |
| 5 | **inotify is silent on DrvFs/9p and NFS.** This is WSL2; a plan or worktree under `/mnt/c` stops delivering events and the reader blocks forever | high | `--poll-interval` is a mandatory backstop, and `smokin doctor` must stat the filesystem *type*, not only `st_dev` |
| 6 | **SIGKILL, OOM and WSL shutdown defeat every EXIT trap.** The reaper is the sole floor | by design | Mitigated by making the reaper a pass inside the tick rather than a process (§3i) |
| 7 | **A runtime that forks or daemonises publishes a premature `terminal: ok`** | medium | Detectable — short `result`, unchanged artefact hashes — but only by looking. UNTESTED for every runtime |
| 8 | **Codex `notify` is global and user-level.** Two concurrent plans share one program and route only by `cwd` | medium | Project-local `.codex/hooks.json` is primary, `notify` a backstop that must verify **plan identity**, not just cwd. Untestable here — Codex absent |
| 9 | **OpenCode needs a resident SSE subscriber.** No hook exists; the stream is directory-scoped, non-resumable, with a dead `wait` endpoint | medium | This is the one runtime where the stateless claim is a half-truth. Honest version: **opencode panes degrade from push to timeout** if the subscriber dies |
| 10 | **Per-turn signals re-fire.** A human who types into a finished pane produces a second legitimate receipt | medium | `seq` makes the *read* idempotent; a receipt arriving for a task with an accepted `VERDICT.json` is recorded and does **not** re-open the task |
| 11 | **A receipt can outlive its truth.** `RECEIPT.json` survives a `git checkout` that reverts the work | medium | Hash mismatch → `stale` → treated as absent (§3g) |
| 12 | **The pane ceiling will be raised.** It is one number in one file, the failure is social, it arrives at week three, and it looks like success until the review queue *is* the project | high, unfixable by tooling | Marked provisional; phase 8 obliges measuring it |
| 13 | **Concurrent plans share one machine and one global config per vendor.** `~/.codewhale/config.toml` (credentials), `~/.codex/config.toml`, a fixed port 7891 | medium | `flock` on the credential file; declared in the runtimes row; two plans on one box is a stated limitation |
| 14 | **Re-running a plan inherits the last run's receipts.** A stale cursor skips receipts that look consumed | medium | Every receipt, pointer and dispatch record carries `run`. `smokin reset --run <id>` is the ceremony; a receipt from a previous run is refused, not believed |

---

## 10 · What is NOT solved

### Open questions — no fix known, stated as questions rather than papered over

**Q1 — Does a Codewhale pane ever emit?** A trapping (non-`exec`) wrapper around
`codewhale -C <wt> --skip-onboarding` in a pty logged `WRAPPER_START` and never emitted for the
full budget; Codewhale's teardown prints `Session terminated, killing shell...` (CONFIRMED by
probe). If it kills the wrapper rather than returning to it, Codewhale panes have **no** emission
path at all — global hook (5c) *and* wrapper both fail — and degrade permanently to reaper
timeouts. **Required before anything ships:** a per-runtime emission preflight that dispatches a
throwaway task and asserts a receipt with the correct task id lands. On this machine that
preflight would currently fail for Codewhale panes and be unrunnable for Codex.

**Q2 — Does `herdr pane run <pane> <cmd>` leave the wrapper's EXIT trap intact?** Every design
reviewed assumed it. Nobody ran it. If herdr SIGKILLs on pane close, every pane task degrades to
reaper-only. This is a ten-minute experiment and it is load-bearing.

**Q3 — Does `claude --settings` merge or replace?** Failure mode 2. Until answered, the Claude
`Stop` accelerant does not ship.

**Q4 — Is `paneCeiling` 3, or 5, or 2?** Phase 8 says measure. Nobody has.

**Q5 — Can a Smokin plan run twice concurrently on one machine?** Vendor global config, a fixed
port and one credential file say probably not. Undesigned.

**Q6 — What does a PANE cost?** Nothing here can say, and the two halves of the obvious answer
do not overlap. Usage capture works only on the **headless** path, because the only source this
design will read is the transcript `smokin-run` tees into the task folder; a pane's output goes
to a screen. The numbers do exist on disk — `~/.claude/projects/*.jsonl`,
`~/.local/share/opencode/opencode.db` — and reading them is barred by the same ruling
`smokin-run`:61 already carries: *a pointer to `~/.claude` is not reconstructable from the
repository* (principle 14). So Smokin can measure tokens exactly where it cannot yet reuse
context, and will be able to reuse context exactly where it cannot measure tokens. **The trade
that closes the loop — one number for principle 14 — is refused, and the receipt says
`available:false` out loud instead of looking like a runtime that reported zero.** The reading
that *is* available for the reuse half needs no vendor parsing at all: panes opened per run is a
count of `.smokin/dispatch/*.json` records with `dispatch:"pane"`, and the incident being
measured was a pane being opened.

**Q7 — Should memory cross a run boundary?** §2g stores an observation with the command that
produced it, and recall hands a worker only entries from the **current** run. Across runs the
world has moved: `_INVARIANTS.toml` already confesses the same shape under *"a baseline taken
late records the damage as normal"*, and an observation about a world that no longer exists reads
identically to one about the world in front of you. The archive keeps everything and
`smokin memory` prints all of it, so a human can carry a lesson forward deliberately by writing
it into the new run — which is the ceremony, and it is on purpose. **What would settle it:** a
measurement nobody has taken, of how often a cross-run recall would have been *right*. Until
then the filter stays and the honest statement is that this is unmeasured, not that it is wrong.

**Q8 — Two phrasings of one lesson are two lessons.** Sameness is a normalised string, so the
skill-candidate threshold counts phrasings rather than meanings and is a **floor**. The fix
everyone reaches for — ask a model whether two sentences agree — puts a judgement call inside a
counter, and a counter whose answer depends on a model call is not a measurement. Stated rather
than solved.

### Deliberately not solved

- **Correctness.** Smokin proves a task ran, produced artefacts, and passed the gate someone else
  wrote. It does not prove the gate was good. Prior art says gating on the real test suite cut
  breakage ~80%; Smokin can insist the gate ran, never that it was worth running.
- **The review bottleneck.** It scales linearly with pane count and no tool in the survey solved
  it. Smokin makes the pane expensive and caps the count. That is a speed bump, not a fix.
- **Power-loss durability.** The design `fsync`s; that is daemon-and-clean-reboot persistence,
  and the marketing sentence *"the file is in the repository"* must not be read as more.
- **Phase 8's own obligation.** `substrates.measure[]` has five rows — effective parallelism,
  wall-clock on the same real fan-out, time-to-detect a stalled worker, orchestrator tokens spent
  watching, recovery cost after a context loss. **Not one is filled for Smokin.** Under phase
  8's own rule, Smokin may be named, templated and floored now; it may **not** be recommended by
  `SCALING.json` until those five numbers exist for a real fan-out. Smokin is precisely the
  structured-looking tool that sentence was written about.

---

## 11 · The first hour, if it is built

Written as a sequence because a design that cannot describe its own first hour has not been
designed.

**0–10 · `smokin doctor`.** Probes each runtime, stats the spool filesystem type and `st_dev`,
checks python3 and inotify, and writes `.smokin/doctor.json`. On this machine it reports
`claude ok · opencode ok · codewhale ok (headless) · aider untested · codex MISSING · gemini
MISSING`, and — if Q1 is still open — `codewhale pane: EMISSION UNPROVEN`. The user learns their
fleet is four runtimes, not six, now rather than from a gate that passed.

**10–25 · Declare and fail.** Answer the phase-0 question, add the six header fields, run
`validate-plan.py --run-gates`. It fails: two tasks declared `pane` out of habit, one done-command
shells out to `claude -p`. Fixing those is the first hour's real content, and it is the same
experience Grillin's own gate report already gives on a real first plan.

**25–40 · `smokin tick`.** Three tasks fork in-process; one opens a workspace, a tab named for its
wave, a pane split `--no-focus`, and stamps it. The herdr sidebar reads `t3-migrator` and
`t4-search`, not two panes called `claude`. Exit 1 — work in flight.

**40–55 · `smokin run`.** Blocks in inotify. Receipts land. Each tick prints what completed and
what it dispatched. Around minute 50 the pane hits an approval prompt and a human answers it —
which is the entire justification for that task being a pane, now spent.

**55–60 · The thing they tell someone about.** `kill -9` the run loop, close the terminal, open a
new one, `smokin tick` once. Same frontier, three receipts reaped, wave 2 dispatched. Then the
quieter second line: `T4 verdict=refuted — gate exit 1`, because the agent said done, the receipt
recorded that it said done, and the verdict said otherwise. Three facts, three files, two hands.

---

## 12 · Files this document did not change

**Confirmed untouched:** everything under `~/grillin`.

A future implementation would edit exactly these — and nothing else:

```
GRILLING-THE-PLAN.md          principle 17, 3 anti-patterns, phase-0 question,
                              phase-4 table, phase-8 third substrate, count corrections
README.md                     line 57 count
QUICKSTART.md                 §0b question row and the five/six count
SCALING.json                  substrates.third + invariant amendment (schema change),
                              principles[], antiPatterns[], shape.questions[],
                              taskContract.outputs, scaling[].paneCeiling, receipts{}
index.html                    M.principles[], M.anti[]
scripts/validate-plan.py      9 FLOORS keys, 9 check functions, 9 calls in main(),
                              --skip-gates inversion, blew_up regex fix at :264-268,
                              docstring counts at :8
templates/TASK.md.template    6 header fields, 1 link line, Outputs
templates/_WORKTREES.md.template   §3b Placement
templates/hooks.json.template      SessionStart → smokin adopt && smokin tick
templates/awareness.sh.template    smokin surface mode, .awareness/verified writes
templates/GRILL-CHECKLIST.md       6 ticks under the existing substrate heading
templates/_SMOKIN.md.template      NEW
templates/smokin*.template         NEW (6 files)
```

Every one of those is an edit somebody else authorises. This document authorises none of them.

---

## §2i · Running to a stop, and who is allowed to stop it

`smokin run` exists so an operator can start the fleet and walk away. That only means
something if the loop stops for the right reasons and does not stop for the wrong ones, so
every terminal reading is a separate exit code: `0` complete, `3` stuck, `4` halted, `5`
waiting on a person. `1` — in flight — is the only one that continues the loop.

**A person's task is never dispatched.** Who counts as a person is *Grillin's* decision, not
ours: its gate has needed the answer since v1.0.0 because two of its checks pull in opposite
directions on it (declaring `human` removes the model floor and adds the frozen-contract
obligation). Smokin needs the same answer for a third reason — no runtime may take the work —
and three definitions would eventually disagree. The failure that would produce is a model
quietly doing a person's task while the plan reports progress, which is worse than any
refusal. So the patterns here are Grillin's, copied character for character, and a contract
test asserts that against the live file rather than against this paragraph. `RE_READER` was
allowed to drift exactly this way and an adversary found it, not a test.

**Parked, not blocking.** The shape is borrowed from BPMN's user task, where a token sitting
on human work blocks its own branch and the process instance comes to rest only when no token
can advance. So the tick sets the task aside, ledgers `awaiting-human`, and carries on
dispatching everything else ready. The status is deliberately left alone: a tick noticing you
is not you starting. The silent control in the test file is the load-bearing one — a sibling
agent task in the same plan and the same tick must still go out, or "continuous" is a word
with nothing behind it.

**`wait` is the curator's primitive and it is ours to own.** Operators were writing
`wait-for-agent.sh` per site and backgrounding one shell per agent, re-implementing the
question this tool is already the authority on. Waiting on a worker is execution, so the
boundary rule puts the mechanism here and leaves Grillin only a pointer. It holds no state
and starts nothing — it watches the plan directory, because the plan directory is where every
answer already is.

### The limits of this layer

- **`--max-wait` is a ceiling, not a poll interval.** A worker that dies without emitting
  moves no file, so nothing wakes a waiter, and the tick that would reap it on budget never
  happens. An uncapped wait turned `run` into a hang for one revision while this was written.
  The wait is an optimisation over a blind sleep; it is never a gate on the loop.
- **Exit `5` says a person is needed, not that they were told.** Nothing here notifies anybody.
- **A plan of people with job titles needs the PLAN.md declaration.** No regex over "Writer A"
  or "the DBA" is ever going to close that, which is why Grillin put the declaration where the
  question is actually asked, and why this reads the declaration instead of guessing.

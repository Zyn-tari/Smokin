# Changelog

## Unreleased — the worker runs at its declared effort · 2026-09-11

Grillin requires every agent task to declare an **Effort:** of `high` or above — the misses that
cost most in its history were on work priced as routine — and nothing passed it to the worker. The
floor was a declaration nothing applied: the same shape as the model, one field over.

- **`effort_flag`** (`--effort {EFFORT}` for claude) is appended to `headless` before the dispatch
  line, and `{EFFORT_FLAG}` in `pane` expands to it. `claude --help` on 2.1.263 lists
  `--effort <level> (low, medium, high, xhigh, max)` — all five, so a declared `max` reaches the
  worker. Anything else is refused, not passed.
- **Not on Haiku.** The API rejects the parameter for Haiku 4.5 and the CLI drops it for models
  without effort support, so passing one would be harmless at runtime and false on paper: the
  record would claim an effort that was never applied. The dispatch record's new `worker_effort`
  says it was withheld and why. Grillin already refuses an Effort on a Haiku task; this is the
  half for a plan that reaches the runner without passing the gate.
- **From the task's Effort only, not the persona file.** The model reads the persona file first
  because it was asked for and Grillin checks the two agree. A second place to declare effort
  would need its own agreement check, and a declaration nothing checks is what this closes.
- `doctor` counts a claude row without `effort_flag` as incomplete; `--fix` copies it.

Pin, merge & debrief harness 43 → 53 checks.


## Unreleased — the worker runs on its persona's model · 2026-09-11

Decided by the user the same day as the pin: the persona's model governs the worker, not only
its helpers. `{MODEL}` used to be substituted in `judge` alone, and the runtimes table recorded
every worker's pairing as "REQUESTED and not applied" — honest, and once subagents were pinned
it meant a Haiku persona was Opus doing the work with Haiku helpers.

- **`model_flag`** in a runtimes row (`"--model {MODEL}"` for claude) is appended to `headless`
  before the dispatch line, and `{MODEL_FLAG}` in `pane` expands to it. The model is resolved
  once — persona file `model:`, else the task's **Model:** — and the same value launches the
  worker and pins its subagents, so the two cannot disagree. No model means no flag, never an
  empty `--model`; a non-identifier is not passed; a row with no `model_flag` passes nothing, and
  the dispatch record's new `worker_model` says which of those happened.
- `doctor` counts a claude row without `model_flag` as incomplete, and `--fix` copies it.
- **`doctor --fix` no longer clobbers.** It assigned `env` unconditionally, so a row with
  customised caps that was only missing the pin key would have had its caps replaced with the
  shipped ones. Each key is now copied only when it is missing.
- **The debrief hook, installed on the machine it was written on, would have done nothing.**
  `smokin` was not on PATH, so the hook found no `smokin-debrief` and exited 0 — silently.
  `SMOKIN_DEBRIEF_BIN` now names it and wins. And since it is installed globally and Stop fires
  at every turn-end in every session, a Stop outside a Smokin dispatch is dropped in the shell
  before anything is spawned.

`tests/test-subagent-pin-and-integration.py` 34 → 43 checks; 41 passed.


## Unreleased — the pin, the merge, the debrief · 2026-09-11

**A correction first, because it matters most.** The 2026-09-07 entry below says the shipped
`claude` row pins subagents to `claude-sonnet-5` via `CLAUDE_CODE_SUBAGENT_MODEL_FORCE`. It did
not. Read out of the installed bundle, FORCE is only ever tested for being *set* — it removes the
Agent tool's `model` parameter — and the model name comes from `CLAUDE_CODE_SUBAGENT_MODEL`, which
the row never set. For four days every worker's subagents inherited their parent's model while
the row said Sonnet. The test asserted the string reached the child environment, which proves
delivery and nothing about effect. That entry stays as written; this is the record of it being
wrong.

### The subagent model is pinned per task, from the persona

FORCE is now `1`, the switch it is. The row names the variable that carries a model —
`subagent_model_env`, still the only place a vendor's variable is named — and Smokin fills it
per dispatch: the persona file's `model:` first, the task's **Model:** second. A Haiku persona's
helpers run on Haiku and an Opus persona's on Opus, and neither can ask for another; escalating
is a change to the contract, where it is visible. The dispatch record says what was pinned and
from where. A value that is not a model identifier is refused rather than exported, and a row
with no pin key pins nothing and says so. `doctor` treats a cappable row without the key as
uncapped; `--fix` copies both.

### "Every task verified" is not "complete" while a branch is unmerged

`tick` and `status` both return `5` — at rest, waiting on a person — when every task has
verified but a declared **Branch:** has no `**Kind:** integration` task downstream. Every contract
says "Do NOT merge", so in that state all of the work is still on branches, and "complete" is
what an operator reads as "it landed". Decided from TASK.md fields alone, no git call. A merge
done by hand is recorded as a person-owned integration task, because the plan cannot see a merge
nobody told it about. Grillin's `check_integration` is the gate's half; this is for the plan
that arrives without passing through it.

### Every finished agent is debriefed

Asked for directly. `bin/smokin-debrief` and `templates/debrief-on-subagent-stop.sh`: every
subagent and fan-out agent that finishes is summarised by `claude-haiku-4-5` into four sections
— **Key points of success** · **Unfinished business, marked defects or failures** · **Important
notes** · **Full chat workflow flaws** — in the task's `debriefs/` folder, or beside the
transcript when there is no task. Wired to SubagentStop always, and to Stop only inside a Smokin
dispatch — never the user's own session.

- **Never blocks.** The hook reads its payload, starts the debrief detached, and exits: measured
  under 2 s while a 4 s summariser ran.
- **Never recurses.** The summariser runs with `SMOKIN_DEBRIEF_ACTIVE` set, and both the hook and
  the script check it first.
- **Never fails silently.** A summariser error still writes the file, saying why.
- **A note, not a verdict** — SUSPECTED, grading nothing. `doctor` warns when no settings file
  wires the hook, because a prerequisite nothing reports is a preference.

The first live run debriefed the research agent that started this change — a 1.6 MB transcript,
27 s on Haiku — and found the same two gaps in that run that were found by hand. It also marked
"did not spot-check its own report" as a workflow flaw, which is the self-verification Claude 5
retires; the prompt now says declining to re-check finished work is not a flaw, while acting on
something never checked still is.

41 passed in the harness, up from 40. `tests/test-subagent-pin-and-integration.py`, 34 checks.


## Unreleased — `doctor --fix` · 2026-09-08

**One repair, and the refusals are the design.** `--fix` was carried for a while as
a general repair for whatever doctor reports. Almost nothing doctor reports is
repairable by editing a file: a declared runtime that is not installed needs a
binary (a `--fix` that shelled out to a package manager would be the most dangerous
line in this repository), a launch string ending in a variadic flag needs to know
what the author meant to put last, and the filesystem and herdr lines are facts
about the host. All three are refused in `doctor_fix`'s docstring so the question
is closed rather than re-asked.

What it does fix is a gap **this repository created yesterday**. `load_runtimes`
takes the first candidate file that exists and does not merge, so a plan shipping
its own `.smokin/runtimes.json` gets nothing from the shipped table — including the
`env` block — and silently runs on Claude Code's own defaults of 20 concurrent
subagents at spawn depth 3. A plan with no runtimes.json of its own was never
affected: it falls through to the template and gets the caps for free.

- `doctor` warns on any cappable row with no `env`, naming the real defaults and
  the no-merge rule that caused it. Detection reads the launch string, not the row
  name, so a claude row called `impl` is not uncapped by accident.
- `--fix` copies the block from the shipped table **read at run time**, so it
  cannot drift from what a fresh plan would inherit. Backs up to
  `runtimes.json.bak`, reports what it changed, and goes in the ledger.
- Idempotent, refuses a lone task, and leaves a runtime this tool has no opinion
  about entirely alone rather than inventing caps for it.

`tests/test-doctor-fix.py`, 26 checks. The four values are read from the template
rather than restated, because a test that hardcoded them would pass on the day
somebody changed it and be wrong about what a fresh plan inherits.


## Unreleased — Claude 5 · 2026-09-07

Two mechanisms, added together because they answer the same question from opposite ends: **what
does a worker get, beyond the words in its task file?** 39 checks in the harness, up from 38.

**Nothing about verification changed, and that is the entry.** Anthropic's guidance for this model
generation says to strip explicit verification instructions out of prompts because Opus 5 already
verifies its own work. That guidance is about prompts; a verdict is `subprocess.run` executing a
done-command and reading an exit code. It costs zero prompt tokens and produces the same answer
whether the worker is diligent, tired, lying or dead. The reading to be careful of is the
opposite one: **a model that verifies its own work unprompted produces more confident receipts,
not fewer.** A receipt has never been worth more than the mechanism that checks it, and it is
worth slightly less now. Written up under README § "Receipt vs verdict".

### The calibration file reaches the worktree

Grillin authors `tasks/<ID>/CLAUDE.md` — how to behave, as opposed to TASK.md's what to do. It is
authored in the task folder where the gate can see it and **read** from the worktree, which is a
different directory. Only a dispatch knows both paths. `place_calibration` copies it, and:

- **It refuses to clobber.** A worktree is a checkout of a real repository which may have its own
  `CLAUDE.md`. Overwriting it would be invisible — same name, same place, different instructions
  — so a destination without this tool's marker is left alone and the refusal goes on the record.
- **It overwrites its own marked copy without asking**, because a persona's worktree persists
  across that persona's tasks and stale calibration is worse than none: specific, plausible, wrong.
- Skipped on a dry run, for the same reason `MEMORY.md` is.

### A runtimes row may carry `env`

The only place in this tool that names a vendor's environment variables — same rule as the launch
strings: a runtime is a row, not a code path. It exists because `Do NOT spawn sub-agents` sat in
Grillin's task template as a line nothing could check, and the shipped defaults it was up against
are higher than anyone expects: read out of the installed bundle (2.1.263),
`CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS` falls back to **20** and
`CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH` to **3**.

The shipped `claude` row sets concurrency 2, depth 1, six per session, and pins subagents to
`claude-sonnet-5` via `CLAUDE_CODE_SUBAGENT_MODEL_FORCE`. Those four numbers are a **judgment,
not a measurement**, and the row says so; depth 1 is the load-bearing one, because it lets a task
fan out once and stops the fan-out from fanning out.

> **A dispatch inherits the operator's environment.** `env = dict(os.environ, ...)`, so a worker
> receives whatever the shell that ran `smokin tick` was carrying, and the same plan run from two
> different shells is two different plans. The row is an **override**, not a set-from-nothing.
> This was found by the test written to prove the opposite — the session running it had
> `CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH=2` exported — and it is now asserted in both directions.

Keys are validated against `^[A-Z][A-Z0-9_]*$`, values shell-quoted where the pane path builds a
command, and a key that fails is dropped and **named** on the dispatch record. The record
publishes key names only: a value can be a token, and a dispatch record is readable by anyone who
can read the plan.

---

## The policy, before the entries

**Do not update Smokin while a plan is running.**

A running plan has state on disk that the binary you are replacing wrote: receipts,
verdicts, dispatch records, invariant baselines, the standing rulings. Swapping the
tool underneath a tick is the one upgrade that can lose work, and nothing in the design
protects you from it — the whole point is that state survives the *process*, not that it
survives a change of schema.

```bash
smokin status <plan>     # 1 = work in flight. Anything else is a plan at rest.
git pull                 # then update
```

Exit **`1` is the only one that means do not update** — something is running right now. Wait
for it, or `smokin reap <plan>` first and let the reaper close the dispatches out properly.
Every other code is a plan at rest and safe to upgrade on: `0` complete, `3` idle (stuck, or
ready and waiting for a tick), `4` halted, `5` waiting on a person. The command prints which
in words, so you do not have to hold the ladder in your head.

`_RULINGS.toml` and `_INVARIANTS.toml` are read at every tick. If a version changes what
they accept, an in-flight plan halts loudly rather than running on a half-understood
config — which is the designed behaviour, and still not a thing you want mid-job.

---


## v1.3.1 — 2026-08-23

**The receipt now honours a worker's declared block.** `smokin-emit` set `claim = "blocked"` only
when `QUESTIONS.md` was present. A worker that wrote `**Status:** BLOCKED` in its own TASK.md and
stopped was recorded as `partial` — retryable — and the task was quietly handed to the next runtime.

### `**Status:** BLOCKED` was written by workers and read by nothing

There are two honest ways for a worker to stop: it writes `QUESTIONS.md` (a decision it may not make),
or it sets `**Status:** BLOCKED` in its TASK.md. `emit` read only the first. The second reached the gate
as `partial`, so the frontier treated a declared block as unfinished work and dispatched it onward — which
made writing `QUESTIONS.md` the *only* lever that actually parked a task. A signal you have to bypass the
declared one to send is a gap, and it was found by a worker taking the declared path and being ignored.

`emit` now reads the Status field, and a declared `BLOCKED` flips the claim exactly as an open
`QUESTIONS.md` does. A self-declared block only ever *downgrades* a claim — it can never manufacture a
`done` the gate did not witness — so honouring it adds no way to fake success. Dispatch resets Status to
`IN PROGRESS` before the worker runs, so a stale `BLOCKED` from a prior verdict cannot leak into a fresh
receipt.

## v1.3.0 — 2026-08-21

**`smokin status` now returns a meaningful exit code.** It always returned 0. A script written
as `smokin status <plan> && ...` will now branch differently — which is the point, and why this
is a minor bump rather than a patch.

### `smokin status` never answered the question its own policy asks

The update policy at the top of this file has always said *"exit 1 means work is in flight"* —
the check that exists to stop the one upgrade that can lose work, swapping the binary under a
running tick. **`status` returned 0 unconditionally.** Anyone who followed the instruction got
a green light over a live fleet.

Found by following it, on a box with six real plans on it, while upgrading that box.

`status` now returns the same ladder `tick` does, read from the same `STATUS.json` so the two
cannot disagree: `0` complete · `1` in flight · `3` idle · `4` halted · `5` waiting on a
person. It still starts nothing and asks nobody, and it prints "IN FLIGHT — do not update" or
"at rest — safe to update" in words.

**A first draft returned `1` for ready-but-not-started**, which is the same false alarm in the
other direction — it would have refused a safe upgrade on four of the six plans that found the
original bug. Ready-but-unstarted is a plan at rest.

`present` is unchanged and still exits 0: it is a renderer, not a question.

## v1.2.0 — 2026-08-20

**The default behaviour of `smokin run` changed.** It no longer exits when a person is
needed; it holds and resumes by itself. If you drive it from cron or CI, add `--no-wait` to
get the old exit-5 behaviour back — otherwise it will wait for an answer that is not coming.

### The loop does not end because a person is needed

A person is not a worker with a task — they are the answer to a question the plan could not
settle. Exiting on one made the operator the scheduler: notice, act, remember to re-run.

`QUESTIONS.md` → `ANSWER.md`. The answer file existing is the entire signal, so there is nothing
to parse, no marker to remember, and the question survives verbatim beside its answer. An open
question parks its own branch and nothing else; `smokin run` holds and resumes by itself.

It says it is holding **once**. An earlier revision re-ticked on every wait timeout and
reprinted the banner every few seconds for as long as somebody was away — nothing is in flight
in that state, so there is no worker to reap and nothing a bare tick would learn.

`--no-wait` restores the exit for cron and CI. Two existing checks asserted the old contract and
were updated rather than deleted, so the trade is visible in the test file.

## v1.1.0 — 2026-08-20

**One new exit code, and it is not an error.** `smokin run` now exits **5** when a task is
owned by a person and everything a runtime could take has been taken. A caller that treats
any non-zero as failure will read it as one; nothing is wrong, and the plan is waiting for
you. `0` complete · `3` stuck · `4` halted · `5` waiting on a person.

**A task a person owns is no longer dispatched to a model at all** — Grillin's
`is_human_owned` decides that, copied character for character and contract-tested against the
live file.

New subcommand: `smokin wait [--task T]`. Also: `smokin tick --close <plan>` works for the
first time (it exited 2 without ticking in v1.0.0), and `smokin run` no longer loops on a
halt.

### Running to a stop — 2026-08-20

**The evidence was two case studies of a real repository** — five plans, 38 tasks, grillin
installed as a `pre-commit` hook. They used `smokin verify` and never once ran the dispatch
half, while the gate's own PASS text advertises it: *"`smokin tick` enforces it where it
can."* Asking why found two defects and a shipped CLI bug.

- **A task a person owns was dispatched to a model.** `route()` had no human clause, so a
  task whose `**Owner:**` is a person went to a runtime like every other. Grillin has decided
  who counts as a person since v1.0.0 and Smokin never asked. Now it does, using Grillin's
  `is_human_owned` **character for character** — patterns and behaviour both asserted against
  the live file, because `RE_READER` diverged in exactly this way and an adversary found it,
  not a test. `**Workers:** human` in PLAN.md widens it to a plan of people with job titles.
- **Such a task is PARKED, not blocking.** The BPMN reading: a token on a user task blocks its
  own branch, not the process. The tick carries on with every other ready task; the plan comes
  to rest only when the only work left is somebody's. Status is deliberately untouched — a
  tick noticing you is not you starting. New exit code **5, waiting on a person**, distinct
  from `3` stuck because nothing is wrong and the operator's next move is different.
- **`smokin run` looped on a halt.** It stopped on `0` and `3` and slept on everything else,
  so a tier-1 invariant breach — the tick refusing to add work on top of a broken machine —
  was re-asked every three seconds up to 200 times. Mutation-proven: reverting the loop
  re-ticks a halted plan 5 of 5 times.
- **`smokin tick --close <plan>` did not work, and never had.** `parse_args` takes positionals
  in contiguous chunks, so the path arrived after a flag as an *unrecognized argument* and the
  command exited 2 without ticking. Every usage line in the file that shows a flag puts it
  before the plan. Now `parse_intermixed_args`. Present since v1.0.0.
- **`smokin wait [--task T]`** — the curator's primitive, which operators were writing per
  site as a `wait-for-agent.sh` and backgrounding one shell per agent. Waiting on a worker is
  *execution*, so under the boundary rule it is Smokin's to answer and Grillin's only to point
  at. It blocks until the task settles and returns on the **event**, not the clock; `5` at
  once for a person's task, `4` if the plan halts under it, `3` on timeout. `run` now watches
  the plan through the same primitive instead of a blind sleep — **capped**, because a worker
  that dies without emitting moves no file, and the tick that reaps it on budget must still
  happen. That cap is a regression check: an uncapped wait turned `run` into a hang for one
  revision during this work.

`bash tests/run-tests.sh` — 35 checks (was 34); `tests/test-continuity.py` adds 77.

**Token capture at dispatch.** The receipt gains an optional `usage` key carrying what the
runtime itself reported: tokens always, cost only from a runtime that reports one.

*The incident.* An operator watched six agents sit idle, each holding exactly the context the
next task needed, and opened a seventh pane. The ledger could already answer how long that
took, how many retries it cost and how often a first pass survived its gate; it could not
answer what it **spent**, so "does reusing an agent's context save anything" had no
measurement behind it.

- Three rows in `templates/runtimes.json` gained an output flag and a descriptor, each verified
  by a real invocation recorded in its `verified` field: `claude -p … --output-format json`,
  `codewhale exec --auto --output-format stream-json`, `opencode run --format json`. **`codex`
  and `aider` were deliberately not touched** — codex is not installed and aider is untested,
  and declaring a shape for either would assert something nobody ran.
- The shapes are **data, not code**. `result_from` and `usage` are `{select, match, map}`
  descriptors in the capability table, so the tick still has no branch on any vendor. One
  scanner reads all three, and a parser with an `if runtime == "codewhale"` in it would have
  forfeited the design claim for one number.
- **A number the runtime did not report is absent — never `null`, never `0`.** Codewhale
  reports tokens and no cost anywhere, and the only way to fill a `cost_usd` column for it
  would be a price table this repository invents.
- **Panes capture nothing, and say so.** A pane receipt carries
  `usage: {"available": false, "reason": "pane-not-instrumented"}` rather than omitting the
  key, so a reader can tell *this runtime said nothing* from *this path cannot see it*. The
  numbers are on disk in `~/.claude/projects` and `~/.local/share/opencode`, and reading them
  is barred by the ruling `smokin-run` already carries: a pointer to `~/.claude` is not
  reconstructable from the repository (principle 14). DESIGN §10 Q6.

**Fixed, in the same change, because the flags above would have caused it.** Two places fell
back to the last twenty transcript lines when no `result` was supplied — `smokin-emit` and the
reaper in `smokin`. The moment claude gained `--output-format json` those twenty lines were the
JSON envelope, and the receipt's most-read field would have started carrying a machine blob
where prose used to be. Both now lift the declared field first and fall back to the tail
unchanged. **A runtime that declares no envelope produces a byte-identical receipt**, which is
the silent control for the whole change.

**Also fixed:** the reader now **scans** the transcript instead of slicing its tail.
`smokin-run` runs two racing `tee` processes and stdout and stderr are confirmed to interleave
out of order, so neither end of the file is a safe place to look.

**Pane reuse, default-deny, and the persona that decides it.** The other half of the same
incident. Token capture said what a dispatch **spent**; this is what stops the spending. Before
this, `launch()` called `herdr pane split` unconditionally, so every pane task got a new pane
whether or not an agent holding exactly the right context was sitting there — which is precisely
the behaviour the operator was complaining about.

- **`**Agent:**` is now read.** It is the persona, and `grep RE_AGENT` returned nothing before
  this change; a persona is a label, not an addressable worker, and a pane id is what turns it
  into one. It **defaults to absent** — 9 of the 20 `TASK.md` shipped across both repositories
  declare it, and the largest fixture declares it on none of its eight tasks — so every
  mechanism downstream degrades to doing nothing, with one ledger line saying so. A reuse
  mechanism whose declines are silent is indistinguishable from one that was never built.
- **The adversarial pass is FORBIDDEN reuse, and this is an enforced rule rather than a
  preference.** Grillin's gate already fails an adversarial task that does not declare
  `**Context:** fresh — not a subagent of the orchestrator, not a continued session`, and a
  reused agent **is** a continued session. Reusing there would have made Smokin the thing that
  quietly breaks the plan's highest-yield check while the task still carried the declaration
  saying it did not. The **health** reader is the opposite case and is PREFERRED: Grillin calls
  its contamination "required, not disqualifying". Everything else is permitted.
- **Reuse punches a hole in containment, and the hole is written down** — DESIGN §2f, the tick's
  own output, and `PROGRESS.md`. A wrong belief formed in task A now survives into task B, and
  task B's own done-command cannot see it.
- **One question of the filesystem, one attempt at the world.** The candidate must have left a
  `RECEIPT.json`; nothing asks whether a pane is *alive*, because `herdr agent list` reported two
  bare login shells as idle agents on this machine. Then `herdr pane run` is simply sent, and a
  non-zero return falls back to a fresh split — CONFIRMED, `herdr pane run w99:p99` exits 1 with
  `pane_not_found`. An attempt's result is a fact; a lifecycle label is an opinion.
- **Measured as panes opened per run**, on `STATUS.json` and in `PROGRESS.md`. Not tokens: token
  capture only sees the headless path and reuse only happens in panes, and closing that gap would
  mean reading the vendor state directories principle 14 bars. A count of dispatch records needs
  no vendor parsing and is the direct measurement of the incident, which was a pane being opened.
- **No new store**, no daemon, no pooling, no idle timeout, no cross-run reuse. The dispatch
  records already survived completion; this only reads them, and `smokin reset` still clears them.

**Also fixed:** `smokin verify` and `smokin tick` treated **any** `**Reader:**` declaration as
adversarial, so the health reader — whose contamination is required — was being told its
independence was unverified. The two roles have opposite contamination rules and one sentence
cannot be true of both.

**Retracted:** DESIGN §7 non-negotiable 6 claimed `**Agent:**` "is unique across the plan". It was
never implemented in Grillin and Grillin's own shipped example contradicts it — `minimal-passing-plan`
declares `implementer` on two tasks. Uniqueness would also make reuse impossible by construction.

`bash tests/run-tests.sh` — 34 checks. `tests/test-usage.py` adds 74 and `tests/test-reuse.py`
adds 96, each mutation-proven separately: fifteen mutations of the parse, the role table, the
history lookup, the census, the fallback and the ledger, every one failing only its own checks.
Every fixture uses Grillin's real field register — `**Agent:**` sharing a line with `**Model:**`
and `**Effort:**` — because a fixture that put the field on its own line would prove the parse
against a plan nobody writes. Two of the loud checks were found to be passing for the wrong
reason by the mutation run, and were rewritten.

**Agent memory — an observation, the command that produced it, and nothing else.** The same
incident read a third time. Token capture said what a dispatch spent. Pane reuse keeps a context
alive across a task boundary — but only while the pane exists, only inside one run, and never on
the headless path, where a fresh subprocess per task is where `inproc`'s containment comes from.
So the observation the sixth agent had already paid for still died with its process everywhere
reuse could not reach.

- **The guard is the feature.** Every entry carries the task it came from, the observation, and
  **the command that produced it**. `"be careful with async"` carries none of those and is refused
  at write time, with a non-zero exit and nothing appended — not stored-and-flagged, because a
  flagged entry is still an entry and still gets recalled. The silent control is the **same
  sentence** with a task, an observation and a command attached: accepted, because a reader can now
  go and find out whether it is true. The guard is structural, not semantic — nothing here grades
  prose, and a mechanism that pretended to would be the unearned assertion this project refuses.
- **The guard does not weaken for a `fact`.** A fact with no command behind it is the same defect
  wearing a more confident word, and the tick is refused by its own guard when a task has no
  `## Done means` to cite.
- **The tick writes one thing automatically: a REFUTED gate.** A gate that passed teaches the next
  occupant nothing two other files do not already say. Nothing harvests sentences out of
  `FINDINGS.md`. The obvious second source — the rulings layer — is **deliberately not wired**,
  because a judgement has a `because` and no command, so it is refused by this same guard. That is
  the guard being right, not inconvenient.
- **Recall is SUSPECTED, bounded, exact and scoped to the run.** `tasks/<ID>/MEMORY.md` says in its
  first paragraph that the running system outranks it and that nothing auto-applies. At most five
  entries, exact match on the persona name — no similarity, no widening — and only from the current
  run, because the world moves between runs and `_INVARIANTS.toml` already confesses that shape.
  **Every recall is in the ledger, including every declined one**: this is the one mechanism that
  can hand a worker a wrong belief *from the orchestrator itself*, and the worker's own gate cannot
  see it.
- **Five personas is a REPORT.** The same observation from five different personas is announced as
  a skill candidate and **no skill is written** — asserted by counting the files the run created,
  not by reading the sentence that says so.
- **It degrades to nothing, measured exactly.** A plan whose gates all pass writes no store, no
  `MEMORY.md`, no `PROGRESS.md` section; a plan declaring no `**Agent:**` writes nothing and says
  why. In both cases **the dispatch line is byte-identical** to the one this tool sent before the
  feature existed — a comparison of the bytes the worker received, not a claim about intent.
- **`smokin verify` writes no memory**, for the same reason it does not touch `TASK.md`. It is the
  door people adopt first *because* it is read-only.
- **`smokin reset` keeps the entries and drops the recalls**, the same trade that retires rulings
  rather than deleting them. Nothing leaks forward: recall filters on the run id and reset takes
  the run id away.

**Amended:** DESIGN §4a said the dispatch line names the task path "and nothing else". It now names
paths inside the task's **own folder** and nothing else, and only gains the second one when there is
something to recall.

**Also fixed, and it is the harness lying about itself.** `run-tests.sh` counted its
sub-harnesses' checks with `grep -c PASS`, which also matches a check whose *label* contains the
word — `...and the summary AGREES with the verdict`, and the verdict lines. Three sections were
reporting one more check than they ran. The counts above and in `CONTRIBUTING.md` are the
corrected ones, so earlier entries citing 75 spend checks and 79 ruling checks were each one
high. A calibration harness that overstates its own count is the same defect as prose that
overstates, in the one file whose whole job is to be trusted about numbers.

`bash tests/run-tests.sh` — **34 checks**, up from the 31 v1.0.0 shipped, and the last of them is
this. `tests/test-usage.py` adds 95, `tests/test-reuse.py` adds 117 and `tests/test-memory.py`
adds 143, each mutation-proven separately: fourteen mutations of the guard, the recall, the
render, the census, the reset and the ledger, every one failing only its own checks. One of them
**survived** the first version of the harness — a fuzzy persona match, because the fixture's
near-miss name was `implementor` and `"implementer"` is not a substring of it either. The fixture
is now `implementer-2` and the mutant dies. That check had been passing for the wrong reason.

---

### The adversarial pass — 2026-08-19

The build phase for the three mechanisms above finished and the adversarial phase had never run.
It has now. Everything below was **reproduced first and fixed second**, and every fix carries a
check that fails without it. Counts: `test-usage.py` 74 → 95, `test-reuse.py` 98 → 117,
`test-memory.py` 109 → 143.

**Blocking — arbitrary command execution from a `**Agent:**` field.** The memory recall clause
interpolated the persona name into the command string the pane path hands to `herdr pane run`,
unquoted. A task declaring ``**Agent:** `impl; touch /tmp/PWNED #` `` with one recalled entry ran
the second command — confirmed end to end, with a silent control showing the name entered the
command **only** when a recall existed, so this feature is what introduced it. The comment three
lines above the injection asserted the clause was "fixed text plus a task id" while `{t.agent}` sat
in the same f-string, and the test that was meant to cover it regexed the output of a *benign*
persona name — it asserted a property of the fixture, not of the code path, and passed while the
property was false. Three independent repairs: the persona is validated at parse time and a value
that is not a persona name is treated as no persona; the dispatch line no longer carries it at all
(`MEMORY.md`'s own H1 already does); and the line is `shlex.quote`d where it is substituted into
the pane command. The fixture is now hostile and the assertion is about the file the second command
would have created.

**Blocking — the role gate was enforced on one channel of two.** `reuse_class` refuses the
adversary a pane; recall consulted only `t.agent` and never `t.reader`, so the adversary refused a
pane was handed the same persona's entries as a **file** — `kind: lesson` included, which is
precisely the "merely concluded" half the containment rule says must not carry forward. Recall now
declines with the same sentence the pane refusal writes, because it is the same rule.

**Serious — Smokin and Grillin disagreed about what an adversary is.** Grillin's gate captures the
leading run of letters; Smokin took the first whitespace token and compared with `==`. `adversary.`,
`adversary,` and `adversary-fresh` were all ADVERSARY to the gate — which then demanded the "not a
continued session" declaration — and ordinary work to Smokin, which handed them a **reused** pane.
Smokin's `RE_READER` is now Grillin's regex character for character, anchored to line start the same
way, so an earlier `**Reader:**` sharing a field line can no longer shadow the real declaration for
one program only. The test's fixture table is every divergent input.

**Serious — a stored entry could rewrite the document Smokin signs.** A claim containing newlines
escaped its `## ` heading and rendered as top-level markdown; a command containing ` ``` ` closed
its own fence. Either put a `# VERIFIED AGAINST THE RUNNING SYSTEM` section, in Smokin's own file,
under Smokin's own header saying the opposite. `check` now refuses a claim with a line break, and
`render` flattens the claim into its heading and opens each fence wider than the longest backtick
run inside it — two independent guards, because `render` is also reachable with entries an older
build wrote.

**Serious — the field the count-not-bytes rationale forgot.** `claim` was capped and `observation`
truncated; `command` was unbounded, so two recalled entries produced a **53 KB** `MEMORY.md` that
the ledger recorded as `"n": 2`. A `COMMAND_MAX` refusal and a `RECALL_BYTES` budget landed, and
the ledger now carries `bytes` beside `n` so the diagnosis path measures what is actually spent.

**Serious — the guard's prose overstated the guard.** "Unfalsifiable advice is rejected at write
time" is not what ships: four non-empty strings and a shape check. The module docstring, DESIGN
§2g and the new §2h now say what it is. Two cheap structural checks were added rather than
claimed — an observation that is its own claim retyped is refused, and `--task T999` naming no task
in this plan is refused, which was invented provenance stored happily.

**Serious — one transcript line killed the orchestrator.** `records()` caught `ValueError` only,
and `json.loads` raises `RecursionError` on a deeply nested line — 9998 levels in 59,989 bytes,
well under the scanner's own 1 MiB bound. It escaped the scanner, `reap()` and the tick, so one
task's transcript denied a **healthy** second task its receipt and ended `smokin run`. The scanner
now skips any line it cannot read whatever the reason, and both `lift_result` callers are guarded
the way `usage_from` already was.

**Serious — a hostile usage payload wrote `Infinity` into RECEIPT.json and the ledger.** `1e999`
parses to `inf`, `json.dumps` writes the bare token, and RFC 8259 has no such token: both files
became unreadable to every parser that is not Python's. `_number` now rejects non-finite and
negative values; absent is the honest answer for a reading that is not one.

**Serious — a `select: sum` total was silently short.** A dropped line removes a whole step, and
the receipt carried a confident low number. It now carries `dropped_records` beside it when the
scan was not clean, and nothing at all when it was.

**Serious — pane reuse was not scoped to the run,** while its sibling mechanism refuses cross-run
recall on principle. A pane from a previous run was offered and, if herdr still had it, a whole
previous run's context was inherited silently. Two halves of one feature disagreeing with no note
anywhere; now they agree.

**Serious — a REAPED receipt was read as the worker saying it stopped.** It is the reaper saying
the worker did **not** — `terminal: "reaped"`, `source: "reaper"`, `exit: null`. `pane_history`
treated it as a free pane and sent a second agent into it. A reaped task is now `pending`.

**Serious — an ordinary task could inherit the ADVERSARY's pane.** Only the arriving task's reader
was consulted. Containment now holds in both directions.

**Serious — `verify` held both halves of a proof and never joined them.** A task declaring
`**Reader:** adversary` whose own dispatch record says `reuse.used: true` now **FAILS** with the
pane and the task it inherited from named, and a non-zero exit, instead of a note saying its
independence is "unverified". It reads only files, starts nothing and spends no model call.

**Not fixed, and stated as a limit rather than left implicit** (DESIGN §2h): a persona is a name a
task claims, so any task declaring `**Agent:** recon` inherits `recon`'s pane and entries. Binding
a persona to a task would break Grillin's own shipped example, where `implementer` appears on two
tasks, and reuse needs a repeated persona to have anything to reuse.

**Corrected rather than changed:** `reap --close` closes the tab of a task the reaper had to give
up on, never of one that finished — and that is deliberate, because closing a finished task's tab
would delete the pane reuse this same release added. The help text said "tidies panes" and implied
otherwise; it now says what it does.

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

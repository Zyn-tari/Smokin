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

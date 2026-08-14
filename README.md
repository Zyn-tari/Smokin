<h1 align="center">Smokin</h1>

<p align="center">
  <em>Grillin builds the plan. Smokin runs it.</em>
</p>

<p align="center">
  <a href="#do-you-need-this">Do you need this?</a> ·
  <a href="#sixty-seconds">Sixty seconds</a> ·
  <a href="#when-you-need-the-fleet--how-tick-works">The fleet</a> ·
  <a href="#the-presenter">Presenter</a> ·
  <a href="#for-an-agent-reading-this">For agents</a> ·
  <a href="#honest-state">Honest state</a> ·
  <a href="EXPERIMENTS.md">Experiments</a>
</p>

---

## Do you need this?

| Your situation | Answer |
|---|---|
| **More than one worker at once** | **Yes.** That is what this is for. |
| **One worker, or you are doing it by hand** | **Partly** — you want `smokin verify`, and nothing else here. |
| You have no plan yet | Not yet. Write one first — see [Grillin](https://github.com/A-Pex97/grillin). |

**At n=1, you are the receipt. `verify` is the second hand.**

Your agent says it finished. `smokin verify` re-runs the task's own done-command *itself* and tells
you whether that was true. It starts nothing, leaves nothing running, and never edits your
`TASK.md`. That is the whole of what this does for one worker, and it is the part worth having
first.

> This section exists because two people in a row read this README, wrote a plan, ran it with the
> one agent they already had, and skipped Smokin entirely — the second on a job built to need it.
> Both then hand-checked their agent's claims, which is exactly what `verify` does. The idea was
> welded to a fleet they did not have.

---

## Sixty seconds

```bash
smokin verify examples/demo-plan
```

Every task's own done-command is re-run, and you get one page — `PROGRESS.md` — saying which tasks
are **actually** finished and which merely **claim** to be.

```
  verdict  T1  PASS
  verdict  T2  REFUTED

  1 of 2 verified · see PROGRESS.md
```

Nothing was started. Nothing is still running. Run it again and you get the same answer.

---

## The three states

|  | Means |
|---|---|
| **◑ claimed** | the worker said it finished. **Nothing has checked that.** |
| **● verified** | the task's *own* done-command was re-run by something that did not do the work, and passed |
| **✗ refuted** | it claimed done; the command disagreed |

Those are three different statements and the difference is the point. A claim is not evidence; it
becomes evidence when a second hand runs the gate.

---

## What this repo is

**A runtime for plan directories.** One command reads a plan off disk, dispatches whatever tasks
are ready across whatever agent CLIs you have installed, re-runs each finished task's own
done-command as an independent check, regenerates a status surface a human can read — and **exits**.

It is not a method, a framework, or a daemon. It is three executables and a contract.

The method is its sibling, [**Grillin**](https://github.com/A-Pex97/grillin), which turns a vague
ask into a plan an orchestrator can operate. Grillin stops at *"something else runs this."* For a
long time that something else was a conversation, and a conversation dies. **Smokin is the
something else.**

|  | Grillin | Smokin |
|---|---|---|
| Answers | *is this plan operable?* | *is it running, and where is it?* |
| Artefact | a plan directory | a receipt, a verdict, a rendered surface |
| Fails when | a plan cannot be dispatched | a worker went silent |
| Needs | a text editor | `python3` |

You can use either alone. Grillin alone gives you a good plan somebody drives by hand; Smokin alone
gives you a very reliable way to run an unexamined plan. Neither is the interesting one.

---

## The one idea

**There is no long-running orchestrator process.**

Grillin's principle 14 says *assume amnesia — anything living only in a conversation is already
gone*, and its own machine-readable spec confesses the cost of its default substrate:
*"fleet state lives in the orchestrator's context and dies with it."*

Nothing made principle 14 true for a **running** fleet. Every fact `smokin tick` needs is a file in
the plan directory, so compaction, `Ctrl-C`, an SSH drop, `herdr server stop` and closing the
terminal are all **no-ops on the plan**.

Don't take that on trust — the test suite does it on purpose:

```
PASS  killed worker is reaped, not lost
PASS  a missing receipt became a result
```

`kill -9` a worker with nothing alive to notice, then recover the identical frontier from a
separate, later process.

---

## Quickstart

```bash
git clone git@github.com:A-Pex97/smokin.git
export PATH="$PWD/smokin/bin:$PATH"

smokin verify examples/demo-plan     # check a plan without starting anything
smokin doctor examples/demo-plan     # what is actually installed on this machine
smokin run    examples/demo-plan     # the fleet: tick until complete or stuck
cat           examples/demo-plan/PROGRESS.md
```

The demo is three chained tasks. **T3's gate fails on purpose** — its worker reports success and
writes one byte, and the done-command demands more than fifty. That is the whole design in one
screen:

```
verdict  T1  PASS
verdict  T2  PASS
verdict  T3  REFUTED
```

### The commands

| | |
|---|---|
| `smokin verify <plan>` | **start here.** Re-run every task's own done-command. Starts nothing, edits no `TASK.md`, spends no model calls |
| `smokin doctor <plan>` | probe every declared runtime, the filesystem and the shell; write `.smokin/doctor.json` |
| `smokin tick <plan>` | one pass: reap · gate · **judge** · dispatch · render. **Safe to run at any time, from anywhere** |
| `smokin run <plan>` | tick until the plan is complete or stuck |
| `smokin status <plan>` | one line: how many verified, what is ready |
| `smokin present <plan>` | print `PROGRESS.md` |
| `smokin reap <plan> [--close]` | force-reap overdue tasks; `--close` also tidies the pane |
| `smokin rulings <plan>` | resolve and print the judgement layer, and the ledger it has written |
| `smokin resume <plan>` | clear a halt, after a human has read it |
| `smokin reset <plan>` | retire the run — receipts, verdicts, artefacts, statuses, rulings |

**Exit codes:** `0` complete · `1` work in flight, tick again · `2` not a plan directory ·
`3` stuck — nothing running and nothing ready · `4` **halted — a human has to read something**.

### The delegation node

Drop a `_RULINGS.toml` beside the plan and the tick gains a judgement layer: before a task counts as
verified, a judge who wrote none of it is asked one question, on declared evidence, with a closed set
of answers — and the ruling is written to `.smokin/rulings.jsonl` with its reason. **The frontier
then advances on rulings, not receipts.** No file, no layer: the tick behaves exactly as before.

The judge is named by persona; its model and effort come from `_ROSTER.md`, because that is the file
that carries the reason for the pairing. An unreachable judge **halts**, and that is not
configurable — one that quietly resolved to `accept` would be a plan certifying itself while looking
like it works. See [DELEGATION-NODE.md](DELEGATION-NODE.md) and
[`templates/_RULINGS.toml.template`](templates/_RULINGS.toml.template).

---

## When you need the fleet — how `tick` works

Everything below this line only matters once **more than one worker** is running. With one worker, `verify` above is
the whole tool.

Five steps, and each one exists because of a specific defect.

```
reap ─────► drain ─────► gate ─────► dispatch ─────► render
```

**1 · reap.** Any dispatch record past its budget with no receipt is synthesised as
`terminal: "reaped"`. **A missing receipt is a result, not an absence.** The dispatch record is
written *before* launch, which is what lets a cold reader tell *never dispatched* from *running
right now* from *was running when the machine died*.

**2 · drain.** Spool pointers are claimed with `rename(inbox → done)` **before** acting. Acting
first leaves a window where a crash re-dispatches dependants on top of still-running copies.

**3 · gate.** The tick re-runs each finished task's own `## Done means` command and writes
`VERDICT.json`.

**4 · dispatch.** Every ready task launches — in-process by default, in a pane only under a
declared clause.

**5 · render.** `STATUS.json` from files, then `PROGRESS.md` from `STATUS.json` only.

### Receipt vs verdict — the split that matters

| File | Written by | Says |
|---|---|---|
| `RECEIPT.json` | the worker's wrapper or a native hook | *the agent claims it finished* |
| `VERDICT.json` | the tick, re-running the task's **own** done-command | *a second hand checked* |

**A receipt may be a precondition of a gate. It may never *be* the gate.** A receipt plus a
two-line findings file passes `test -f` with zero real work done. This is Grillin's principle 8 —
never certify your own work — applied one level down, to the worker certifying its own completion.

### Where to run it — pane or in-process

First match wins:

| # | If the task declares | Then | Because |
|---|---|---|---|
| 1 | `Interrupt: yes` | **pane** | it has an approval-bearing or human-answerable step |
| 2 | `Watch: yes` | **pane** | somebody stated in writing that they will look |
| 3 | `Type: ASK` | **pane** | an ASK node terminates on a human |
| 4 | `Budget > 900` | **pane** | work that outlives the tick must outlive its process |
| 5 | the runtime has no headless mode | **pane** | the only way to run it at all |
| 6 | otherwise | **in-process** | the half everybody skips |

**The rule points the opposite way from the reflex. You do not open a pane to get parallelism.**
Parallelism is free in-process. A pane is bought with a screen and paid for in human review
capacity — the one constraint no tool in the prior art solved.

*Honest limit:* only clauses 3 and 5 have an external referent. A check on the others proves
self-consistency, not truth.

---

## The presenter

A process nobody can see is a process that gets missed. Every tick regenerates two files:

| | |
|---|---|
| **`STATUS.json`** | machine truth, derived only from files on disk |
| **`PROGRESS.md`** | the human surface, rendered **only** from `STATUS.json` |

```markdown
# Where the plan is

`███████████████████░░░░░░░░░`  **2 of 3 verified**

## ✗ Said done, gate disagreed

- **T3** — the agent claimed `done`, its own done-command exited non-zero.

| | Task | State | Owner | Where | Waiting on |
|---|---|---|---|---|---|
| ● | **T1** | verified 1.0s | worker-a | `3627271` | — |
| ◑ | **T2** | claimed, ungated | worker-b | `3627325` | — |
| ✗ | **T3** | REFUTED | worker-a | `3627343` | — |
```

It leads with **⏸ Waiting on you**, then anything the gate refused, then every task with what it is
blocked on, then what changed this tick.

**`●` and `◑` are not the same thing, and the difference is the point.** A claim becomes evidence
when a second hand runs the gate.

**The presenter may not re-derive a single fact.** It reads the object and narrates it — the same
rule as Grillin's reader model, because a narrator allowed to go looking will eventually narrate
something that is not true. If you want prose, a presenter *agent* may read `STATUS.json` and
nothing else, must write `PROGRESS-NOTES.md` rather than the generated file, and may never call a
task done — only repeat `verified` or `claimed, ungated` as given.

---

## What it runs

Anything that **can be started by a shell command and can write a file into a directory.**

Not *"one of herdr's 21 agent kinds."* Not *"has a hook system."* A runtime is a **row in a JSON
file**, and the tick has no branch on runtime anywhere:

```json
"codewhale": {
  "headless": "codewhale exec --json --auto",
  "pane":     "codewhale -C {WT} --skip-onboarding",
  "hook_scope": "global-only",
  "holds_credentials": true
}
```

Codewhale is the proof. herdr cannot classify it at all — it is not one of the 21 kinds. Under
Smokin that costs nothing, because **the tick never asks herdr what any agent is doing, including
the agents herdr *can* classify.** On a real machine `herdr agent list` reported two bare login
shells as idle `claude` agents. A false idle is indistinguishable from a finished worker.
Classification is a display concern; the receipt is the contract.

Three emission paths, and only one of them is load-bearing:

| Path | Role |
|---|---|
| **the wrapper** — forks (never `exec`s), traps `EXIT HUP TERM INT` | **the floor** |
| a native hook — Claude `Stop`, Codex `notify` | an *accelerant*: lower latency, richer result |
| **the reaper** | **the guarantee** |

Delete every accelerant and Smokin still terminates on a complete result set — later, with a
thinner result.

---

## For an agent reading this

Machine-readable spec: [`SMOKIN.json`](SMOKIN.json). Read that instead of this README.

**The one invariant:** every fact the orchestrator needs is a file inside the plan directory. If
you cannot reconstruct it from the plan directory, it does not exist.

**To operate a plan:** `smokin tick <plan>` until it returns `0` (complete) or `3` (stuck).

**Do not:**

- wait on an agent's lifecycle state instead of its receipt;
- read a pane's screen to detect completion — a TUI on the alternate screen never reaches
  scrollback. **Watch the filesystem, never the screen;**
- call an agent binary from a done-command — the gate then tests whether the tool is installed, not
  whether the work is finished;
- edit `PROGRESS.md` or `STATUS.json` — both are regenerated every tick;
- treat `RECEIPT.json` as proof of completion. It is a claim.

---

## What is here

| | |
|---|---|
| [`bin/smokin`](bin/smokin) | the tick — reap, drain, gate, dispatch, render |
| [`bin/smokin-run`](bin/smokin-run) | the wrapper. Forks, never `exec`s; traps `EXIT HUP TERM INT` |
| [`bin/smokin-emit`](bin/smokin-emit) | the single emitter — `O_EXCL` mutex, atomic publish |
| [`SMOKIN.json`](SMOKIN.json) | machine-readable spec. Hand it to an agent |
| [`templates/_SMOKIN.md.template`](templates/_SMOKIN.md.template) | the substrate contract a plan copies in |
| [`templates/runtimes.json`](templates/runtimes.json) | the capability table — the only file that knows a vendor's flags |
| [`EXPERIMENTS.md`](EXPERIMENTS.md) | the three experiments the design was blocked on, with commands and output |
| [`DESIGN.md`](DESIGN.md) | why it is shaped like this, and what three adversarial passes broke |
| [`examples/demo-plan`](examples/demo-plan) | a runnable three-task plan; T3's gate fails on purpose |
| [`tests/run-tests.sh`](tests/run-tests.sh) | 14 checks including crash recovery — `14 passed, 0 failed` |

**Requires** `python3` (stdlib only) and `bash`. `herdr` is **optional** — without it panes are
unavailable and everything else works. No packages, no daemon, no database.

---

## Honest state

**Three experiments closed the design's open questions, and one reversed it.** Full commands and
output in [`EXPERIMENTS.md`](EXPERIMENTS.md):

| | Question | Answer |
|---|---|---|
| **Q2** | does `herdr pane run` leave a wrapper's EXIT trap intact? | **yes** — every design assumed it, nobody had run it |
| **Q2b** | does the trap fire when the pane is *closed*? | **yes, via `SIGHUP`** — closure is recoverable, not silent loss |
| **Q1** | does a Codewhale pane ever emit? | **yes** — `rc=129`. This **reverses** `DESIGN.md` |

Q1 is worth reading. The design concluded Codewhale panes have no emission path. The probe that
produced that conclusion launched an interactive TUI and waited for the budget — so it measured
*"an idle TUI does not exit"* and reported it as *"cannot emit."* Every observation true, the
conclusion wrong.

### The measurement this section owes you

`verify` exists because of a count, and the count has not moved yet.

**Four operators in a row** — two watched trials and two real rounds on a live
project — wrote a plan, executed it, and hand-rolled their own verification
rather than reach for this tool. The fourth split a 2,000-line changelog and
verified it by reconstructing the file from its shards and diffing against a
backup taken before the split. That is precisely the receipt-versus-verdict
split, performed by hand, by someone who had this installed.

Their reasoning, unprompted, was better than this README's: *"the splitter's own
pre-write guard proves the plan was sound, not that the write was."*

So the idea transfers and the tool does not. `verify` is the response — it
removes the fleet, which was the stated reason all four gave for skipping it.
Whether that is enough is **unmeasured**, and the honest next question is not
"why did they not use it" but whether a plan-shaped wrapper around *run these
checks and tell me which failed* is worth more than the four-line loop it
replaces. If the count is still four after another round, the answer is no and
this section should say so.


### Phase 8's obligation is unmet, and that is deliberate

Grillin phase 8 says *choose the substrate by measurement, not preference*, and lists five
measurements. They are **comparative** — Smokin against programmatic fan-out on the same real
workload. Two are answered; **three are empty and stay empty until somebody runs a real job both
ways**:

| | Measurement | |
|---|---|---|
| 1 | effective parallelism on both | **empty** |
| 2 | wall-clock on the same real fan-out | **empty** |
| 3 | time-to-detect a stalled worker | **answered** — `budget_s` + time to next tick, bounded and declared per task |
| 4 | orchestrator tokens spent watching | **empty** |
| 5 | recovery cost after a context loss | **answered** — one tick, zero model tokens, tested |

**So: Smokin may be used. It may not be *recommended* over programmatic fan-out.** That is a
comparative claim and nobody has run the comparison. Filling those rows from the demo plan — whose
workers are `sleep 1` — would be measuring the fixture and calling it a measurement.

### Not proven, not solved

- **Untested end to end:** OpenCode and aider dispatch. **Codex entirely** — it is not installed
  here, which is exactly why `smokin doctor` reports it MISSING rather than letting a gate shell
  out to it, exit 127, and read as a clean failure.
- **It does not prove correctness.** It proves a task ran, produced artefacts, and passed a gate
  somebody else wrote. Whether the gate was worth running needs Grillin's uncontaminated
  adversarial reader.
- **`fsync` is not power-loss durability.** *"The state is in the repository"* must not be read as
  more than daemon-and-clean-reboot persistence.
- **The pane ceiling is an opinion.** XS 0 · S 1 · M 3 · L 5 · XL 5, from practitioner reports that
  review capacity binds before compute does. Marking it a floor does not make it a measurement.
- **The tick is only as fresh as its last run.** The price of refusing a resident listener: paid in
  latency, never in lost work.

---

<p align="center"><sub>MIT · built alongside <a href="https://github.com/A-Pex97/grillin">Grillin</a></sub></p>

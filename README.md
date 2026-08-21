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

## Why it's called that

Low and slow. You put it on, you walk away for hours, and the one thing you never do
is trust the clock — you go back and put a probe in it, because "it's been six hours"
and "it's done" are different sentences.

That's this. [**Grillin'**](https://github.com/Zyn-tari/Grillin) is the high-heat part,
where you attack the plan before anyone builds. **Smokin'** is the long unattended part:
it runs your plan for hours without you watching, and when a worker says it finished, it
goes and checks the temperature instead of believing it.

Right — barbecue over. Here is the actual tool.

## Do you need this?

| Your situation | Answer |
|---|---|
| **More than one worker at once** | **Yes.** That is what this is for. |
| **One worker, or you are doing it by hand** | **Partly** — you want `smokin verify`, and nothing else here. |
| **You have no plan — just one task an agent claims it finished** | **Yes.** `smokin verify path/to/TASK.md`. No plan directory required, and there is a hook that does it for you. |
| You have no plan and no task file either | Write one first — see [Grillin](https://github.com/Zyn-tari/Grillin). A `## Done means` you can re-run is the smallest unit this works on. |

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

**And you don't need a plan for it.** Point it at a lone `TASK.md` — the folder, or the file:

```bash
smokin verify path/to/TASK.md
```

That precondition used to be the reason nobody used this. The thing worth having at n=1 was
gated behind authoring a plan directory first, at the exact moment nobody wants to.

### Make it fire by itself

```bash
mkdir -p ~/.claude/hooks && cp templates/verify-on-stop.sh ~/.claude/hooks/
chmod +x ~/.claude/hooks/verify-on-stop.sh
# then merge templates/hooks.json.template into your settings.json
```

Now the moment an agent says it has finished, its own done-command is re-run and you are told
whether the claim survived:

```
⚠ smokin verify: 1 REFUTED — T3. The claim of done did not survive re-running
  the task's own done-command.
```

It never blocks, never edits your `TASK.md`, and always exits 0 — a hook that can wedge a
session gets deleted and takes the useful part with it. `SMOKIN_VERIFY_ON_STOP=0` turns it off.

> **Why a hook at all.** Across five trials and five real jobs, the planning gate got run and
> `verify` did not — and it was never the idea that failed to land. People who had never read
> this README re-invented *"check the claim with something that did not do the work"* on their
> own. The gate has a pre-commit hook putting it **in the path**. `verify` was a command you
> had to remember at the exact moment believing the agent is easier. Same idea, same value,
> one on the shelf and one in the way — and only one of them got used.

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

The method is its sibling, [**Grillin**](https://github.com/Zyn-tari/Grillin), which turns a vague
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
git clone git@github.com:Zyn-tari/Smokin.git
export PATH="$PWD/smokin/bin:$PATH"

smokin verify examples/demo-plan     # check a plan without starting anything
smokin doctor examples/demo-plan     # what is actually installed on this machine
smokin run    examples/demo-plan     # the fleet: run it until it is somebody else's turn
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
| `smokin run <plan>` | tick until there is nothing a runtime may do next. Start it and walk away |
| `smokin wait <plan> --task T1` | block until `T1` settles. What operators were writing a `wait-for-agent.sh` for |
| `smokin status <plan>` | one line: how many verified, what is ready — and **`1` in the exit code means something is running right now.** The question to ask before you upgrade |
| `smokin present <plan>` | print `PROGRESS.md` |
| `smokin reap <plan> [--close]` | force-reap overdue tasks; `--close` also tidies the pane |
| `smokin rulings <plan>` | resolve and print the judgement layer, and the ledger it has written |
| `smokin invariants <plan>` | print the plan-level invariants and their baseline; `--recapture` re-takes it, and says so in the ledger |
| `smokin memory <plan>` | print what each persona observed, and any skill candidate. Read-only |
| `smokin remember <plan> --agent … --task … --claim … --observation … --command …` | write one entry down. **Refused without the command that produced it**, and refused for a `--task` that names no task in this plan. It is a shape check, not a judgement about the prose — see DESIGN §2h |
| `smokin resume <plan>` | clear a halt, after a human has read it |
| `smokin reset <plan>` | retire the run — receipts, verdicts, artefacts, statuses, rulings. Memory entries are kept; the recalls rendered from them are not |

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

### Plan-level invariants — what the plan must not break

Everything above measures **completion**: did the task finish, was its claim true. Nothing above
measures **blast radius** — what a task broke on the way to passing its own gate. No done-command
is ever pointed at something the task was not supposed to touch.

Drop an `_INVARIANTS.toml` beside the plan and each declared reading is captured once as a
baseline, then re-read at every tick boundary and by `verify`. **A break halts the plan** — it is
not a warning, and the evidence rides on `HALT.json` so it survives a re-render. No file, no layer.

> The incident: `certbot` silently added one `listen` directive, made a new vhost the default for
> loopback HTTPS, and served two neighbouring sites the wrong certificate. Every task passed its
> own check. Nobody's done-command was ever going to look at the neighbours' certificate, because
> the neighbours were not the work.

Honest limits, stated rather than footnoted: a baseline taken late records the damage as normal; a
probe is trusted to be read-only and nothing verifies that; and an unchanged reading is not a
*correct* reading, only the same one. See [DESIGN.md §7b](DESIGN.md) and
[`templates/_INVARIANTS.toml.template`](templates/_INVARIANTS.toml.template).

---

## It runs until it is somebody else's turn

`smokin run` ticks until the work stops being Smokin's to do. Every way that can happen is a
separate exit code, because your next move is different in each:

| | | |
|---|---|---|
| `0` | complete | every task verified |
| `3` | stuck | nothing running, nothing ready. Something is wrong |
| `4` | halted | an invariant broke, or a ruling said stop. Read it |
| `5` | waiting on a person | only with `--no-wait`. **Nothing is wrong** |

**The loop does not end because a person is needed.** A worker that hits a decision it may not
make writes `tasks/<ID>/QUESTIONS.md`. You answer by putting `ANSWER.md` beside it — that file
existing is the whole signal, so there is nothing to parse and nothing for you to remember. The
question parks its own branch and nothing else; when the only work left is yours, `smokin run`
**holds**: it watches the plan directory and carries on by itself the moment the answer lands.
You are not the scheduler. `--no-wait` restores the exit for cron and CI, where nobody is coming.

**A task a person owns is never handed to a model.** Grillin already decides who counts as a
person — `**Owner:** human`, or `**Workers:** human` in PLAN.md for a plan of people with job
titles — and Smokin uses Grillin's own definition so the two cannot drift.

Such a task is **parked, not blocking**. The tick carries on dispatching every other ready
task and only comes to rest when the *only* work left is somebody's to do. That is the BPMN
user-task reading: a token on a human task blocks its own branch, not the process.

```
  dispatch T2  inproc  pid 41062
  awaiting T4  a person owns this — human

nothing in flight — WAITING ON A PERSON: T4 (human)
Everything a runtime could take has been taken. Do the task(s) above,
set the status, and tick again — `smokin run` resumes from disk.
```

And when you want to block on one task rather than drive the whole plan — a curator waiting
on a worker — that is `smokin wait <plan> --task T4`. It returns the moment the task settles,
`5` immediately if the task is a person's (it will never settle on its own), `4` if the plan
halts under it, and `3` on `--timeout`. It holds no state and starts nothing, like everything
else here.

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
declared clause. A pane task may **reuse** the pane a task with the same `**Agent:**` persona
already finished in, decided from files and default-deny. The adversarial pass never does: a
reused agent is a continued session, and the plan's own gate requires it to be fresh.

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
| [`templates/verify-on-stop.sh`](templates/verify-on-stop.sh) | **the hook.** Re-runs the gate the moment an agent claims done. Never blocks, always exits 0 |
| [`templates/hooks.json.template`](templates/hooks.json.template) | the wiring for it — merge into settings.json, do not replace |
| [`EXPERIMENTS.md`](EXPERIMENTS.md) | the three experiments the design was blocked on, with commands and output |
| [`DESIGN.md`](DESIGN.md) | why it is shaped like this, and what three adversarial passes broke |
| [`examples/demo-plan`](examples/demo-plan) | a runnable three-task plan; T3's gate fails on purpose |
| [`DELEGATION-NODE.md`](DELEGATION-NODE.md) | the judgement layer: four tiers, and what the node may never decide |
| [`tests/run-tests.sh`](tests/run-tests.sh) | the calibration harness — crash recovery, the emitter mutex, `verify`, rulings, invariants, token capture, pane reuse and agent memory. `34 passed, 0 failed` |

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

---

## Updating

```bash
smokin status <plan>     # 1 = something is running. Every other code is a plan at rest
git pull
smokin --version
```

> **Do not update while a plan is running.** A running plan has state on disk that the
> binary you are replacing wrote — receipts, verdicts, dispatch records, invariant
> baselines. State surviving the *process* is the design; surviving a change of schema
> mid-tick is not. Finish or `smokin reap` first.
>
> [`CHANGELOG.md`](CHANGELOG.md) says what changed.

## Contributing

One maintainer, issues in batches, and one rule: **a change that adds a mechanism must name
the incident it came from.** See [`CONTRIBUTING.md`](CONTRIBUTING.md).

## Licence

**The ideas are free. The tools are free for noncommercial use.**

| | Licence | What it means |
|---|---|---|
| **The documents** — every `.md`, [`SMOKIN.json`](SMOKIN.json), the templates, the demo plan | [CC BY 4.0](LICENSE-DOCS) | Use it anywhere, including commercially. The one condition is **attribution**. |
| **The tools** — [`bin/`](bin/), the hook, the tests | [PolyForm Noncommercial 1.0.0](LICENSE) | Free for personal, academic, research and non-profit use. **Commercial use needs a licence** — open an issue. |

If it executes, it's PolyForm. If you read it, it's CC BY.

### "Is my use commercial?" — the short answer

**If you are one person learning, building your own thing, or trying this out: it's free, and
it stays free. Stop reading here.**

Most of what people worry about isn't restricted at all. **The method is CC BY** — a company
can read it, follow the design documents, copy the templates and ship software with it, commercially, forever, for nothing. The only condition is saying where it
came from. PolyForm covers the **scripts** and nothing else.

| You are | The tools |
|---|---|
| An individual — hobby, side project, learning, your own product | **Free.** |
| A student, academic, public research body, non-profit, government | **Free**, explicitly, whatever your funding — PolyForm says so in its own text |
| A developer at a company, evaluating this to see if it's any good | **Free.** Trying it is not deploying it |
| A company where this is part of how you ship | **Ask me.** Open an issue titled `licence` |
| A consultancy using it on client work | **Ask me.** |
| Anyone forking it, changing it, teaching it, writing about it | **Free**, noncommercially, and please do |

**Where the line actually is:** not your job title, and not whether your laptop has a company
sticker on it. It's whether an organisation is the beneficiary of the tooling. One engineer
running `smokin verify` on their own branch is an individual. A team standardising on it in
CI is an organisation.

**If you're unsure, you're free until I answer.** Open the issue and keep working — I am one
person and I would rather you used it than waited on me. I have never refused anyone, and the
answer for small teams is going to be yes.

**And if the licence is genuinely the blocker** for something you want to do, say so in the
issue. That's useful information about whether this licence was the right call, and I would
rather hear it than have you quietly walk away.


<p align="center"><sub>built alongside <a href="https://github.com/Zyn-tari/Grillin">Grillin</a></sub></p>

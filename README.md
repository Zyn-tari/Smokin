# Smokin

**Grillin builds the plan. Smokin runs it.**

Grillin is prose and a validator: it turns a vague ask into a plan an orchestrator can operate,
and refuses to pass one it could not. It has always stopped at the same place — *something else
runs this.* That something else was a conversation, and a conversation dies.

Smokin is the something else. One idempotent command reads the plan directory off disk, dispatches
whatever is ready, reaps whatever finished, renders a surface a human can read, and **exits**.

```bash
smokin doctor .      # what is actually installed on this machine
smokin tick .        # one pass: reap · gate · dispatch · render
smokin run .         # tick until finished or stuck
smokin present .     # print PROGRESS.md
```

---

## The one idea

**There is no long-running orchestrator process.**

Grillin's principle 14 says *assume amnesia — anything living only in a conversation is already
gone*, and its own `SCALING.json` confesses the cost of its default substrate: *"fleet state lives
in the orchestrator's context and dies with it."* Nothing made principle 14 true for a **running**
fleet. This does.

Compaction, `Ctrl-C`, an SSH drop, `herdr server stop`, closing the terminal — all no-ops on the
plan, because the plan's state was never in the process. Every fact the tick needs is a file.

Don't believe it; the test suite does it to itself:

```
PASS  killed worker is reaped, not lost
PASS  a missing receipt became a result
```

`kill -9` a worker with no orchestrator alive to notice, and a later, entirely separate process
recovers the same picture from disk.

---

## What it runs

Anything that **can be started by a shell command and can write a file into a directory.**

Not "one of herdr's 21 agent kinds". Not "has a hook system". Claude Code, Codex, OpenCode,
Codewhale, aider — a runtime is a *row in a JSON file*, not a code path, and the tick has no branch
on runtime anywhere.

Codewhale is the proof: herdr cannot classify it at all. Under Smokin that costs nothing, because
the tick never asks herdr what any agent is doing — **including the agents herdr can classify.** On
a real machine `herdr agent list` reported two bare login shells as idle `claude` agents. A false
idle is indistinguishable from a finished worker. Classification is a display concern; the receipt
is the contract.

---

## Two files, and the difference between them is the point

| | Written by | Says |
|---|---|---|
| `RECEIPT.json` | the worker | *the agent claims it finished* |
| `VERDICT.json` | the tick, re-running the task's **own** done-command | *a second hand checked* |

A receipt may be a *precondition* of a gate. It may never **be** the gate — a receipt plus a
two-line findings file passes `test -f` with zero work done. Principle 8 one level down.

`PROGRESS.md` renders these differently and says why:

```
| ● | T1 | verified 1.0s     | worker-a | ... |
| ✗ | T3 | REFUTED 1.0s      | worker-a | ... |
```

> **T3** — the agent claimed `done`, its own done-command exited non-zero.

---

## The presenter

A process nobody can see is a process that gets missed. Every tick regenerates two files:

- **`STATUS.json`** — machine truth, derived only from files on disk.
- **`PROGRESS.md`** — the human surface, rendered **only** from `STATUS.json`.

It leads with **⏸ Waiting on you**, then anything the gate refused, then every task with what it is
waiting on, then what changed this tick. Someone who has been away opens one file.

**The presenter may not re-derive a single fact.** It reads the object and narrates it — the same
rule as Grillin's reader model, because a narrator allowed to go looking will eventually narrate
something that is not true. If you want prose, a presenter *agent* may read `STATUS.json` and
nothing else, and may never call a task done — only repeat `verified` or `claimed, ungated` as
given.

---

## What is here

| | |
|---|---|
| [`bin/smokin`](bin/smokin) | the tick — dispatch, reap, gate, render |
| [`bin/smokin-run`](bin/smokin-run) | the wrapper. Forks, never `exec`s; traps `EXIT HUP TERM INT` |
| [`bin/smokin-emit`](bin/smokin-emit) | the single emitter — `O_EXCL` mutex, atomic publish |
| [`templates/_SMOKIN.md.template`](templates/_SMOKIN.md.template) | the substrate contract a plan copies in |
| [`templates/runtimes.json`](templates/runtimes.json) | the capability table — the only file that knows a vendor's flags |
| [`EXPERIMENTS.md`](EXPERIMENTS.md) | the three experiments the design was blocked on, with commands |
| [`DESIGN.md`](DESIGN.md) | why it is shaped like this, including what the adversarial passes broke |
| [`examples/demo-plan`](examples/demo-plan) | a runnable three-task plan; T3's gate fails on purpose |
| [`tests/run-tests.sh`](tests/run-tests.sh) | 13 checks, including crash recovery |

```bash
./tests/run-tests.sh        # 13 passed, 0 failed
```

---

## Requirements

`python3` (stdlib only) and `bash`. `herdr` is **optional** — without it, panes are unavailable and
everything else works. No packages, no daemon, no database.

---

## Honest state

- **Phase 8's obligation is unmet.** Grillin says measure the substrate before recommending it —
  effective parallelism, wall-clock on the same fan-out, time-to-detect a stalled worker, tokens
  spent watching, recovery cost. **Not one is filled.** Smokin may be declared and used; it may not
  be *recommended* over programmatic fan-out until those numbers exist.
- **Routing is not a pure function.** Three of six clauses are author declarations, so a check on
  them proves self-consistency, not truth.
- **`fsync` is not power-loss durability.** *"The state is in the repository"* must not be read as
  more than daemon-and-clean-reboot persistence.
- **It does not prove correctness.** It proves a task ran, produced artefacts, and passed a gate
  someone else wrote. Whether the gate was worth running still needs Grillin's uncontaminated
  adversarial reader.
- **Untested end to end:** OpenCode and aider dispatch, and Codex entirely — it is not installed
  here, which is exactly why `smokin doctor` reports MISSING rather than letting a gate shell out
  to it, exit 127, and read as a clean failure.

---

## The brothers

| | Grillin | Smokin |
|---|---|---|
| Answers | *is this plan operable?* | *is it running, and where is it?* |
| Artefact | a plan directory | a receipt, a verdict, a surface |
| Fails when | a plan cannot be dispatched | a worker went silent |
| Needs | a text editor | python3 |

Use Grillin alone and you get a good plan somebody has to drive by hand. Use Smokin without
Grillin and you get a very reliable way to run an unexamined plan. **Neither is the interesting
one.**

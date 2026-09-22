#!/usr/bin/env python3
"""Calibrate continuity — the loop runs until the work stops being Smokin's.

THE INCIDENT. Two case studies of a real repository — five plans, 38 tasks — used
`smokin verify` and nothing else. The dispatch half was never run once, and the
plan gate's own PASS text advertises it: "`smokin tick` enforces it where it can."
So the question this file answers is not "does a tick dispatch" — 34 checks
already said yes — it is "can an operator start the thing and walk away", which is
a different claim and had two defects sitting under it.

  1 · A PERSON'S TASK WAS DISPATCHED TO A MODEL. `route()` had no human clause,
      so a task whose Owner is a person was handed to a runtime like any other.
      Grillin has decided who is a person since v1.0.0 and Smokin never asked.
      The definition here is Grillin's, character for character, and the first
      check in this file asserts that against the live file rather than against
      a comment — RE_READER diverged in exactly this way and an adversary found
      it, not a test.

  2 · `run` LOOPED ON A HALT. The loop stopped on 0 and 3 and slept on everything
      else, so a tier-1 invariant breach — the tick refusing to add work on top of
      a broken machine — was re-asked every three seconds, up to 200 times. The
      halt is the one reading where continuing is precisely the wrong move.

AND THE SHAPE OF THE FIX IS BORROWED, not invented. A BPMN user task blocks its
own branch and nothing else; the process instance comes to rest only when no
token can advance. So a person's task is PARKED and the tick carries on with
every other ready task. The silent control for the parking check is therefore the
load-bearing one: a sibling agent task in the SAME plan and the SAME tick must
still be dispatched, or "continuous" is a word with nothing behind it.

    python3 tests/test-continuity.py
"""
import importlib.util
import importlib.machinery
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SMOKIN = ROOT / "bin" / "smokin"
GRILLIN = Path("/home/peter/grillin/scripts/validate-plan.py")
spec = importlib.util.spec_from_loader(
    "smokinmod", importlib.machinery.SourceFileLoader("smokinmod", str(SMOKIN)))
S = importlib.util.module_from_spec(spec)
spec.loader.exec_module(S)

fails = 0
LAB = Path(tempfile.mkdtemp(prefix="smokin-continuity."))


def chk(label, got, want):
    global fails
    if got == want:
        print(f"  \033[32mPASS\033[0m  {label}")
    else:
        fails += 1
        print(f"  \033[31mFAIL\033[0m  {label} — want {want!r}, got {got!r}")


def has(label, got, needle):
    chk(label, needle in (got or ""), True)


def hasnt(label, got, needle):
    chk(label, needle in (got or ""), False)


def ledger_events(p, event):
    f = p / ".smokin" / "ledger.jsonl"
    if not f.is_file():
        return []
    out = []
    for line in f.read_text().splitlines():
        try:
            r = json.loads(line)
        except ValueError:
            continue
        if r.get("event") == event:
            out.append(r)
    return out


# ── fixtures ────────────────────────────────────────────────────────────────
# Grillin's register verbatim: Agent/Model/Effort share one line separated by
# `·`, values backticked. A fixture that put Owner alone on a tidy line would
# prove the parse against a plan nobody writes.

def task_md(tid, owner, agent=None, blocked="—", done=None):
    L = [f"# {tid} — fixture", "", "**Status:** NOT STARTED"]
    if agent:
        L.append(f"**Agent:** `{agent}` · **Model:** `claude-opus-5` · **Effort:** high")
    L += [f"**Owner:** {owner}",
          f"**Blocked by:** {blocked} · **Blocks:** —",
          "**Dispatch:** inproc · **Runtime:** `demo`",
          "**Budget:** 60 · **Interrupt:** no · **Watch:** no",
          "", "## What you own", f"`tasks/{tid}/`",
          "", "## Done means", "```", done or f"test -s tasks/{tid}/OUT.md", "```", ""]
    return "\n".join(L)


def mkplan(name, tasks, workers=None):
    p = LAB / name
    shutil.rmtree(p, ignore_errors=True)
    (p / ".smokin" / "dispatch").mkdir(parents=True)
    (p / ".smokin" / "run.json").write_text(json.dumps(
        {"run": "rTEST", "started": "2026-01-01T00:00:00Z", "plan_root": str(p)}) + "\n")
    shutil.copy(ROOT / "examples" / "demo-plan" / "demo-agent.sh", p / "demo-agent.sh")
    (p / ".smokin" / "runtimes.json").write_text(json.dumps({
        "demo": {"headless": "bash demo-agent.sh", "pane": "bash demo-agent.sh {LINE}"}}))
    rows = []
    for kw in tasks:
        tid = kw["tid"]
        (p / "tasks" / tid).mkdir(parents=True)
        (p / "tasks" / tid / "TASK.md").write_text(task_md(**kw))
        rows.append(f"| {tid} | x | {kw.get('blocked', '—')} |")
    head = "# plan\n\n"
    if workers:
        head += f"**Workers:** {workers}\n\n"
    (p / "PLAN.md").write_text(head + "| ID | Task | Blocked by |\n|---|---|---|\n"
                               + "\n".join(rows) + "\n")
    return p


def run_cli(args, plan):
    return subprocess.run([sys.executable, str(SMOKIN)] + args + [str(plan)],
                          capture_output=True, text=True, timeout=180)


# ═══════════════════════════════════════════════════════════════════════════
print("\n=== 1 · who is a person is GRILLIN'S question, and the answer must match ===")
# Not "does Smokin have a plausible rule" — does it give the SAME answer as the
# gate that already ships one. The divergence table is the interesting part: each
# row is a case where a rule invented independently would plausibly differ.
CASES = [
    ("**Owner:** human", True, "the bare declaration"),
    ("**Owner:** human · **Model:** `claude-opus-5`", True,
     "`human` outranks a model line — Grillin shipped this backwards once"),
    ("**Agent:** `impl`\n**Owner:** human", True, "Owner wins over Agent, both present"),
    ("**Owner:** you", True, "idiom, with nothing to contradict it"),
    ("**Owner:** you\n**Agent:** `impl` · **Model:** `claude-opus-5`", False,
     "`you` is defeated by a declared persona — 'you are driving this plan'"),
    ("**Owner:** requester", True, "the other idiom"),
    ("**Owner:** worker-a", False, "an ordinary owner is not a person"),
    ("**Agent:** `recon`", False, "Agent alone, no Owner: not human"),
    ("", False, "nobody named at all"),
]
if GRILLIN.is_file():
    gspec = importlib.util.spec_from_loader(
        "grillinmod", importlib.machinery.SourceFileLoader("grillinmod", str(GRILLIN)))
    G = importlib.util.module_from_spec(gspec)
    gspec.loader.exec_module(G)
    same = 0
    for text, want, why in CASES:
        body = f"# T1\n\n**Status:** NOT STARTED\n{text}\n"
        mine, theirs = S.is_human_owned(body), G.is_human_owned(body)
        chk(f"{why}", mine, want)
        if mine == theirs:
            same += 1
        else:
            chk(f"  ...and Grillin AGREES ({text!r})", mine, theirs)
    chk("Smokin and Grillin agree on every row", same, len(CASES))
    # The regexes themselves, not just their behaviour on nine rows.
    for name in ("RE_OWNER_LINE", "RE_AGENT_LINE", "RE_MODEL", "RE_PERSONA", "RE_WORKERS"):
        chk(f"{name} is Grillin's pattern character for character",
            getattr(S, name).pattern, getattr(G, name).pattern)
else:
    print("  \033[33mSKIP\033[0m  grillin not installed at " + str(GRILLIN))

print("\n=== 2 · a person's task is never routed to a runtime ===")
p = mkplan("route", [dict(tid="T1", owner="human"),
                     dict(tid="T2", owner="worker-b", agent="impl")])
t1, t2 = S.Plan(p).tasks["T1"], S.Plan(p).tasks["T2"]
chk("the human task routes to 'human'", t1.route()[0], "human")
has("...and says why, in the clause", t1.route()[1], "a person owns this")
chk("...and it is clause 0 — before every placement question", t1.route()[1][:1], "0")
# SILENT CONTROL. The whole risk of a new first clause is that it swallows cases
# it was never meant to see.
chk("an ordinary task routes exactly as before", t2.route()[0], "inproc")
chk("...and keeps its own clause", t2.route()[1], "6 · otherwise")

print("\n=== 3 · PLAN.md can declare it once, for people with job titles ===")
# The per-task rule only fires on human/you/requester. Real plans of people write
# "Writer A" — which is why Grillin put the declaration in PLAN.md, and why
# Smokin reads the declaration instead of guessing at the owner string.
p = mkplan("declared", [dict(tid="T1", owner="Writer A"),
                        dict(tid="T2", owner="the DBA")], workers="human")
pl = S.Plan(p)
chk("a plan declaring human workers makes every task a person's",
    [pl.tasks[t].human for t in ("T1", "T2")], [True, True])
chk("...so neither is routed to a runtime",
    sorted({pl.tasks[t].route()[0] for t in ("T1", "T2")}), ["human"])
# SILENT CONTROL: the identical plan without the declaration.
p2 = mkplan("undeclared", [dict(tid="T1", owner="Writer A"),
                           dict(tid="T2", owner="the DBA")])
pl2 = S.Plan(p2)
chk("without the declaration those same owners are NOT read as people",
    [pl2.tasks[t].human for t in ("T1", "T2")], [False, False])
chk("...and they dispatch normally",
    sorted({pl2.tasks[t].route()[0] for t in ("T1", "T2")}), ["inproc"])

print("\n=== 4 · PARKED, not blocking — the tick carries on around it ===")
# THE LOAD-BEARING CHECK IN THIS FILE. If the human task stopped the tick, the
# word "continuous" would be false, and the failure would look like success:
# nothing crashes, work simply does not happen.
# T2 and T3 carry DIFFERENT personas on purpose. They used to share `impl`,
# which was incidental to what this scenario asserts — that a parked human task
# does not stop the tick — and it stopped being harmless when dispatch learned
# to hold a persona's second task back (one worktree, one checked-out branch).
# Sharing a persona here would have made this test fail for a reason that has
# nothing to do with the rule it exists to protect.
p = mkplan("park", [dict(tid="T1", owner="human"),
                    dict(tid="T2", owner="worker-b", agent="impl"),
                    dict(tid="T3", owner="worker-c", agent="impl-b")])
r = run_cli(["tick"], p)
out = r.stdout
has("the person's task is reported as awaiting", out, "awaiting T1")
has("...naming who owns it", out, "human")
hasnt("...and it is NOT dispatched", out, "dispatch T1")
chk("...and its status is untouched — a tick noticing you is not you starting",
    S.Plan(p).tasks["T1"].status, "NOT STARTED")
chk("...and the ledger records it once, with a reason",
    [e.get("task") for e in ledger_events(p, "awaiting-human")], ["T1"])
has("...saying no runtime may take it", (ledger_events(p, "awaiting-human") or [{}])[0].get("why", ""),
    "no runtime may take it")
# THE CONTROL THAT MAKES IT MEAN SOMETHING: the siblings ran in the same tick.
has("the OTHER ready tasks dispatched in that same tick", out, "dispatch T2")
has("...both of them", out, "dispatch T3")
chk("...and they are IN PROGRESS",
    [S.Plan(p).tasks[t].status for t in ("T2", "T3")], ["IN PROGRESS"] * 2)
chk("the tick did not come to rest — work is in flight", r.returncode, 1)

print("\n=== 5 · 'waiting on a person' is its own result, not stuck and not done ===")
# Reading them as one state sends an operator looking for a broken plan when the
# plan is fine and waiting for them.
p = mkplan("waiting", [dict(tid="T1", owner="human")])
r = run_cli(["tick"], p)
chk("a plan whose only ready work is a person's exits 5", r.returncode, 5)
has("...and says so in words", r.stdout, "WAITING ON A PERSON")
has("...naming the task and its owner", r.stdout, "T1 (human)")
has("...and says what to do next — and it is no longer 'run it again'",
    r.stdout, "carries on by itself")
hasnt("...and does NOT call it stuck", r.stdout, "STUCK")

# SILENT CONTROL 1: a genuinely stuck plan still reports 3.
p = mkplan("stuck", [dict(tid="T1", owner="worker-a", agent="impl", blocked="T9")])
r = run_cli(["tick"], p)
chk("a plan blocked on a task that does not exist is still STUCK (3)", r.returncode, 3)
has("...in the old words", r.stdout, "STUCK")

# SILENT CONTROL 2: a plan of only agent tasks never reaches the new branch.
p = mkplan("agents", [dict(tid="T1", owner="worker-a", agent="impl")])
r = run_cli(["tick"], p)
chk("an all-agent plan is unaffected — in flight (1)", r.returncode, 1)
hasnt("...and says nothing about people", r.stdout, "WAITING ON A PERSON")

print("\n=== 6 · a mixed plan waits only once the agents are done ===")
# The sequencing claim: the person is not the reason the plan rests on tick 1.
p = mkplan("mixed", [dict(tid="T1", owner="human"),
                     dict(tid="T2", owner="worker-b", agent="impl")])
r1 = run_cli(["tick"], p)
chk("tick 1 dispatches the agent and parks the person — in flight", r1.returncode, 1)
has("...T2 went out", r1.stdout, "dispatch T2")
# Let the agent finish, then reap it; only now is the person the only work left.
(p / "tasks" / "T2" / "OUT.md").write_text("done\n")
# Tick until the agent's work has been reaped and judged. The loop is bounded so
# a mechanism that never settles fails the check rather than hanging the suite.
for _ in range(12):
    r2 = run_cli(["tick", "--close"], p)
    if r2.returncode != 1:
        break
    time.sleep(0.4)
chk("once the agent's work is verified, the plan waits on the person (5)",
    r2.returncode, 5)
has("...and names them", r2.stdout, "T1")

print("\n=== 6b · flags may precede the plan path ===")
# `smokin tick --close myplan` is a documented form and plain parse_args REFUSED
# it since v1.0.0 — argparse fills positionals in contiguous chunks, so the path
# arrived after a flag as an "unrecognized argument" and every such invocation
# exited 2 without ticking. Found by the checks below, which could not run.
p = mkplan("intermixed", [dict(tid="T1", owner="human")])
r = run_cli(["tick", "--close"], p)
chk("a flag before the plan path is accepted", r.returncode, 5)
hasnt("...not an argparse usage error", r.stderr, "unrecognized arguments")
r = run_cli(["tick"], p)
chk("...and the plain form is unchanged", r.returncode, 5)


print("\n=== 7 · `run` stops on every terminal reading, including the halt ===")
# THE SECOND DEFECT. `run` stopped on 0 and 3 and SLEPT on everything else, so a
# halt — the tick refusing to add work on top of a broken machine — was re-asked
# every interval, up to max-ticks times.
p = mkplan("halted", [dict(tid="T1", owner="worker-a", agent="impl")])
S.halt(S.Plan(p), "a fixture halt, tier 1", tier="1")
r = run_cli(["run", "--max-ticks", "5", "--interval", "0"], p)
chk("`run` on a halted plan exits 4", r.returncode, 4)
chk("...and ticks exactly ONCE, not max-ticks times",
    r.stdout.count("HALTED — tier"), 1)
hasnt("...and never reports running out of ticks", r.stdout, "max ticks reached")

# CONTRACT CHANGED DELIBERATELY, and this is the check that used to assert the
# old one. `run` no longer EXITS on a person — it holds the branch open and waits,
# because exiting made the operator the scheduler. The exit is now opt-in, for a
# cron job or a CI step where nobody is coming. Left here rather than deleted: a
# reader of this file should be able to see that the stop was traded away on
# purpose, not lost.
p = mkplan("runwait", [dict(tid="T1", owner="human")])
r = run_cli(["run", "--no-wait", "--max-ticks", "5", "--interval", "0"], p)
chk("`run --no-wait` stops on a person rather than spinning against them",
    r.returncode, 5)
chk("...having ticked once", r.stdout.count("WAITING ON A PERSON"), 1)

# SILENT CONTROL: `run` still LOOPS on the one code that means keep going. Three
# of the four codes above now stop it, so the check that matters is that the
# fourth still does not — a loop that stops on everything is not a loop.
p = mkplan("runloop", [dict(tid="T1", owner="worker-a", agent="impl")])
r = run_cli(["run", "--max-ticks", "3", "--interval", "0.05"], p)
# The proof that it iterated is the exit code itself: tick 1 of this plan returns
# 1 (a dispatch went out), so a loop that stopped on 1 would return 1. Reaching a
# terminal reading means it went round at least once more. Counting ticks would
# be the weaker check, and now a misleading one — `wait` deliberately removes the
# wasted ones.
has("`run` dispatched on its first tick", r.stdout, "dispatch T1")
chk("...and did NOT stop there, as it would if 1 ended the loop",
    r.returncode != 1, True)
chk("...it stopped on the terminal reading it actually reached",
    r.returncode in (0, 3), True)
hasnt("...so it never runs out of ticks here", r.stdout, "max ticks reached")

print("\n=== 7b · `smokin wait` — the curator's primitive, which they were writing by hand ===")
# THE EVIDENCE FOR THIS ONE IS A SCREENSHOT. An operator running a real plan had
# two backgrounded shells, `wait-for-agent.sh integrator-d1` and
# `wait-for-agent.sh builder-d6`, hand-written per site to answer "has this agent
# finished". That question is EXECUTION, so under the boundary rule it is
# Smokin's to answer and Grillin's only to point at.
p = mkplan("wait", [dict(tid="T1", owner="worker-a", agent="impl"),
                    dict(tid="T2", owner="human")])
r = run_cli(["wait", "--task", "T9", "--timeout", "2"], p)
chk("waiting on a task that does not exist is refused, not waited out", r.returncode, 2)
has("...and it names the tasks there are", r.stderr, "T1, T2")

r = run_cli(["wait", "--task", "T2", "--timeout", "5"], p)
chk("waiting on a PERSON returns at once rather than blocking forever", r.returncode, 5)
has("...saying why", r.stdout, "will not settle on its own")

t0 = time.monotonic()
r = run_cli(["wait", "--task", "T1", "--timeout", "2", "--interval", "0.1"], p)
chk("an unfinished agent task times out", r.returncode, 3)
chk("...at roughly the timeout, not instantly and not forever",
    1.0 < time.monotonic() - t0 < 12.0, True)
has("...and says what it is still waiting on", r.stdout, "timed out")

# Now let it finish, and prove the wait RETURNS on the settle rather than on the
# timeout — a waiter that always waits out its timeout is indistinguishable from
# `sleep` and would pass every check above.
run_cli(["tick"], p)
(p / "tasks" / "T1" / "OUT.md").write_text("done\n")
for _ in range(12):
    if run_cli(["tick"], p).returncode != 1:
        break
    time.sleep(0.4)
t0 = time.monotonic()
r = run_cli(["wait", "--task", "T1", "--timeout", "30", "--interval", "0.1"], p)
chk("a settled task returns immediately", r.returncode, 0)
chk("...well inside the timeout, so it returned on the EVENT not the clock",
    time.monotonic() - t0 < 10.0, True)
has("...naming the state it settled in", r.stdout, "verified")

# A halt outranks the wait: a waiter must not sit through a stopped machine.
p = mkplan("waithalt", [dict(tid="T1", owner="worker-a", agent="impl")])
S.halt(S.Plan(p), "a fixture halt", tier="1")
r = run_cli(["wait", "--task", "T1", "--timeout", "20", "--interval", "0.1"], p)
chk("a halted plan ends the wait rather than outlasting it", r.returncode, 4)


# AND THE WAIT MUST NEVER BECOME A HANG. Replacing the blind sleep with a watcher
# introduced exactly that defect for one revision: a worker that dies without
# emitting moves no file, so nothing wakes the waiter and the tick that would
# have reaped it on budget never happens. `run` blocked forever. The ceiling is
# the fix and this is the check that it is still there.
p = mkplan("nohang", [dict(tid="T1", owner="worker-a", agent="impl")])
run_cli(["tick"], p)                       # T1 goes out
(p / ".smokin" / "spool").mkdir(exist_ok=True)
t0 = time.monotonic()
try:
    r = subprocess.run([sys.executable, str(SMOKIN), "run", "--max-ticks", "2",
                        "--max-wait", "1", "--interval", "0.1", str(p)],
                       capture_output=True, text=True, timeout=60)
    chk("`run` returns even when nothing on disk ever moves", True, True)
    chk("...bounded by --max-wait, not by luck", time.monotonic() - t0 < 55, True)
except subprocess.TimeoutExpired:
    chk("`run` returns even when nothing on disk ever moves", False, True)


print("\n=== 7c · a question parks its branch; the loop does NOT end on a person ===")
# THE RESHAPE. A person is not a worker with a task — they are the answer to a
# question the plan could not settle. So the loop must never TERMINATE on one:
# exiting made the operator the scheduler, who had to notice, act, and remember
# to re-run. It holds the branch open, keeps watching the plan directory, and
# carries on by itself the moment an answer lands.
p = mkplan("asked", [dict(tid="T1", owner="worker-a", agent="impl"),
                     dict(tid="T2", owner="worker-b", agent="impl")])
(p / "tasks" / "T1" / "QUESTIONS.md").write_text("# blocked\n\nBack off how?\n")
r = run_cli(["tick"], p)
has("a task with an open question is reported as asked", r.stdout, "asked    T1")
has("...pointing at the question itself", r.stdout, "tasks/T1/QUESTIONS.md")
hasnt("...and is NOT dispatched", r.stdout, "dispatch T1")
chk("...and its status is untouched", S.Plan(p).tasks["T1"].status, "NOT STARTED")
chk("...and the ledger says why",
    [e.get("task") for e in ledger_events(p, "awaiting-answer")], ["T1"])
# THE CONTROL THAT CARRIES THE CLAIM: the branch stopped, the plan did not.
has("the sibling task went out in the SAME tick", r.stdout, "dispatch T2")
chk("...so the tick did not come to rest", r.returncode, 1)

# An answer beside the question un-parks it. This is the whole signal.
(p / "tasks" / "T1" / "ANSWER.md").write_text("Exponential, capped at 30s.\n")
chk("an ANSWER.md beside the question clears the block",
    S.Plan(p).tasks["T1"].question, False)
chk("...and the task records that it was answered",
    S.Plan(p).tasks["T1"].answered, True)

# SILENT CONTROL: a plan nobody asked anything in is untouched.
p2 = mkplan("noquestions", [dict(tid="T1", owner="worker-a", agent="impl")])
r2 = run_cli(["tick"], p2)
hasnt("a plan with no questions says nothing about answers", r2.stdout, "asked")
chk("...and dispatches normally", r2.returncode, 1)

print("\n=== 7d · `run` holds for the answer, and says so once ===")
p = mkplan("holds", [dict(tid="T1", owner="worker-a", agent="impl")])
(p / "tasks" / "T1" / "QUESTIONS.md").write_text("# blocked\n\nWhich way?\n")

# --no-wait is the cron/CI escape: nobody is coming, so exit and say so.
r = run_cli(["run", "--no-wait", "--max-ticks", "3", "--interval", "0.1"], p)
chk("`run --no-wait` exits 5 rather than holding", r.returncode, 5)
has("...naming the question", r.stdout, "T1 asks")
has("...and telling the reader how to answer", r.stdout, "ANSWER.md")

# The default: hold, and resume on the answer. A thread drops ANSWER.md while
# `run` is blocked — if the loop had exited on the person this returns long
# before the answer and the resume assertion below fails.
import threading
def answer_later():
    time.sleep(4)
    (p / "tasks" / "T1" / "ANSWER.md").write_text("Exponential.\n")
for f in ("STATUS.json", "PROGRESS.md"):
    (p / f).unlink(missing_ok=True)
(p / "tasks" / "T1" / "ANSWER.md").unlink(missing_ok=True)
t = threading.Thread(target=answer_later, daemon=True); t.start()
t0 = time.monotonic()
r = run_cli(["run", "--max-ticks", "30", "--interval", "0.2", "--max-wait", "2"], p)
held = time.monotonic() - t0
chk("`run` did NOT exit on the person — it outlived the answer's arrival",
    held > 3.5, True)
has("...it says it is holding", r.stdout, "does not end because a person is needed")
chk("...exactly once, not on every wait cycle",
    r.stdout.count("WAITING ON A PERSON"), 1)
has("...and it dispatched T1 after the answer landed", r.stdout, "dispatch T1")
chk("...then ran on to a terminal reading of its own", r.returncode in (0, 3), True)


print("\n=== 7e · `smokin status` answers the question the update policy asks ===")
# THE DEFECT. CHANGELOG's update policy says "smokin status <plan> — 0 = complete,
# 3 = stuck. Either is safe to update on. Exit 1 means work is in flight." That
# policy exists to stop the one upgrade that can lose work — swapping the binary
# under a running tick — and `status` returned 0 unconditionally. Anyone who
# followed the instruction got a green light over a live fleet. Found by
# following it while upgrading a box with six real plans on it.
p = mkplan("st-complete", [dict(tid="T1", owner="worker-a", agent="impl")])
(p / "tasks" / "T1" / "OUT.md").write_text("done\n")
for _ in range(12):
    if run_cli(["tick"], p).returncode != 1:
        break
    time.sleep(0.4)
r = run_cli(["status"], p)
chk("a complete plan reports 0", r.returncode, 0)
has("...and says it is safe to update", r.stdout, "safe to update")

# THE ONE THAT MATTERS: something actually running must say so.
p = mkplan("st-flight", [dict(tid="T1", owner="worker-a", agent="impl")])
run_cli(["tick"], p)                       # dispatches T1, no receipt yet
r = run_cli(["status"], p)
chk("a plan with work in flight reports 1, NOT 0", r.returncode, 1)
has("...and says not to update", r.stdout, "do not update")

# AND THE FALSE ALARM IN THE OTHER DIRECTION. Ready-but-unstarted is not in
# flight; a first draft returned 1 here, which would refuse a safe upgrade on
# four of the six plans this was found on.
p = mkplan("st-ready", [dict(tid="T1", owner="worker-a", agent="impl")])
r = run_cli(["status"], p)
chk("ready-but-not-started is at rest, not in flight", r.returncode, 3)
has("...and says so", r.stdout, "safe to update")

p = mkplan("st-stuck", [dict(tid="T1", owner="worker-a", agent="impl", blocked="T9")])
chk("a genuinely stuck plan reports 3", run_cli(["status"], p).returncode, 3)

p = mkplan("st-person", [dict(tid="T1", owner="human")])
chk("a plan whose only work is a person's reports 5", run_cli(["status"], p).returncode, 5)

p = mkplan("st-halt", [dict(tid="T1", owner="worker-a", agent="impl")])
S.halt(S.Plan(p), "a fixture halt", tier="1")
chk("a halted plan reports 4", run_cli(["status"], p).returncode, 4)

# SILENT CONTROLS: status still starts nothing, and `present` stays a renderer.
p = mkplan("st-readonly", [dict(tid="T1", owner="worker-a", agent="impl")])
run_cli(["status"], p)
chk("status started nothing", (p / ".smokin" / "dispatch").exists()
    and len(list((p / ".smokin" / "dispatch").glob("*.json"))) or 0, 0)
chk("...and left the task alone", S.Plan(p).tasks["T1"].status, "NOT STARTED")
chk("`present` is a renderer and keeps returning 0",
    run_cli(["present"], p).returncode, 0)


print("\n=== 8 · the human surface says who is waited on ===")
p = mkplan("surface", [dict(tid="T1", owner="human"),
                       dict(tid="T2", owner="worker-b", agent="impl")])
run_cli(["tick"], p)
st = json.loads((p / "STATUS.json").read_text())
rows = {r["id"]: r for r in st["tasks"]}
chk("STATUS.json marks the person's task as needing a human",
    rows["T1"]["needs_human"], True)
chk("...and distinguishes owned-by-a-person from merely needing one",
    rows["T1"]["human_owned"], True)
chk("the agent's task needs no human", rows["T2"]["needs_human"], False)
chk("...and is not owned by one", rows["T2"]["human_owned"], False)
prog = (p / "PROGRESS.md").read_text()
has("PROGRESS.md lists it under the section for people", prog, "T1")

print("\n=== a wall-clock step does not move a reap ===")
# MEASURED 2026-09-16 on the machine this suite was written on: the wall clock is
# stepped back about 2.2s every few minutes, because timesyncd and an unsynced
# Windows host disagree. Two suite failures that day were a reap decided on
# `time.time() - started_epoch` across such a step, and `held` above was a
# wall-clock timer too. The reap budget is now measured on a monotonic clock
# stamped into the dispatch record (bin/smokin_clock.py). Every case below moves
# the WALL-CLOCK start while the monotonic start says something else, and every
# case has its control: the same record with no monotonic stamp, decided the old
# way.
sys.path.insert(0, str(ROOT / "bin"))
import smokin_clock as CL                                            # noqa: E402


def reap_with(name, **over):
    p = mkplan(name, [dict(tid="T1", owner="worker-T1")])
    st = CL.stamp()
    rec = {"task": "T1", "seq": "rTEST:T1:1", "run": "rTEST", "attempt": 1,
           "runtime": "demo", "dispatch": "inproc", "placement": "inproc",
           "started": "2026-01-01T00:00:00Z", "started_ns": 1,
           "started_epoch": time.time(), "budget_s": 5, **st}
    for k, v in over.items():
        if v is None:
            rec.pop(k, None)
        elif callable(v):
            rec[k] = v(rec[k])
        else:
            rec[k] = v
    (p / ".smokin" / "dispatch" / "T1.json").write_text(json.dumps(rec))
    S.reap(S.Plan(p))
    f = p / "tasks" / "T1" / "RECEIPT.json"
    return json.loads(f.read_text()) if f.is_file() else None


# 1 · The wall clock says 100s have passed; the worker started a moment ago.
r = reap_with("step-fwd", started_epoch=lambda e: e - 100)
chk("a forward wall-clock step does not reap a live worker", r, None)
r = reap_with("step-fwd-ctl", started_epoch=lambda e: e - 100, started_mono=None)
chk("control · with no monotonic stamp the old rule reaps it", bool(r), True)
chk("...and the receipt says the wall clock decided",
    str((r or {}).get("clock", "")).startswith("wall-fallback"), True)

# 2 · The wall clock was stepped back after the start, so wall time says
# -100s; the monotonic clock says 10s, which is past the 5s budget.
r = reap_with("step-back", started_epoch=lambda e: e + 100,
              started_mono=lambda m: m - 10)
chk("a backward wall-clock step does not keep a dead worker alive", bool(r), True)
chk("...its wall_s is the real 10s, not a negative number",
    9.5 <= float((r or {}).get("wall_s") or 0) < 30, True)
chk("...measured on the monotonic clock",
    (r or {}).get("clock") in ("boottime", "monotonic"), True)
r = reap_with("step-back-ctl", started_epoch=lambda e: e + 100,
              started_mono=None)
chk("control · with no monotonic stamp the old rule never reaps it", r, None)

# 3 · A record from another boot cannot be measured monotonically.
r = reap_with("other-boot", boot_id="not-this-boot",
              started_epoch=lambda e: e - 100)
chk("a record from another boot falls back to the wall clock", bool(r), True)
has("...and says why", str((r or {}).get("clock")), "boot")

# 4 · A monotonic difference that comes out negative is not trusted.
sec, how = CL.elapsed(dict(CL.stamp(), started_epoch=time.time() - 50,
                           started_mono=CL.stamp()["started_mono"] + 1000))
chk("a negative monotonic difference falls back", how.startswith("wall-fallback"), True)
chk("...to the wall-clock figure", 49 < sec < 60, True)

# 5 · The emitter writes wall_s too, and must not go negative either.
p = mkplan("emit-step", [dict(tid="T1", owner="worker-T1")])
st = CL.stamp()
(p / ".smokin" / "dispatch" / "T1.json").write_text(json.dumps({
    "task": "T1", "seq": "rTEST:T1:1", "run": "rTEST", "attempt": 1,
    "runtime": "demo", "dispatch": "inproc", "placement": "inproc",
    "started": "2026-01-01T00:00:00Z", "started_ns": 1,
    "started_epoch": time.time() + 100, "budget_s": 60,
    **dict(st, started_mono=st["started_mono"] - 3)}))
(p / "tasks" / "T1" / "OUT.md").write_text("done\n")
subprocess.run([str(ROOT / "bin" / "smokin-emit"), "T1", "clock-test"],
               input='{"terminal":"ok","exit":0}', text=True, capture_output=True,
               env=dict(os.environ, SMOKIN_PLAN=str(p)))
rc_ = json.loads((p / "tasks" / "T1" / "RECEIPT.json").read_text())
chk("the emitter's wall_s survives a backward step (about 3s, not -97s)",
    2.5 <= float(rc_.get("wall_s") or 0) < 10, True)
chk("...and names its clock", rc_.get("clock") in ("boottime", "monotonic"), True)

# 7 · A tampered start must not abort the reap pass for everyone else.
for bad in ("x", True, float("nan")):
    try:
        r = reap_with(f"tampered-{type(bad).__name__}", started_epoch=lambda e: e - 100,
                      started_mono=bad)
        raised = False
    except Exception:
        r, raised = None, True
    chk(f"a started_mono of {bad!r} does not crash the reaper", raised, False)
    has("...it falls back to the wall clock and says why", str((r or {}).get("clock")),
        "not a number")

# 8 · STATUS.json's elapsed_s is measured the same way, and names its clock.
def status_elapsed(name, **over):
    p = mkplan(name, [dict(tid="T1", owner="worker-T1")])
    st = CL.stamp()
    rec = {"task": "T1", "seq": "rTEST:T1:1", "run": "rTEST", "attempt": 1,
           "runtime": "demo", "dispatch": "inproc", "placement": "inproc",
           "started": "2026-01-01T00:00:00Z", "started_ns": 1,
           "started_epoch": time.time() - 100, "budget_s": 600, **st}
    rec.update(over)
    for k in [k for k, v in over.items() if v is None]:
        rec.pop(k)
    (p / ".smokin" / "dispatch" / "T1.json").write_text(json.dumps(rec))
    subprocess.run([str(SMOKIN), "tick", str(p)], capture_output=True, text=True)
    row = next(t for t in json.loads((p / "STATUS.json").read_text())["tasks"]
               if t["id"] == "T1")
    return row.get("elapsed_s"), row.get("elapsed_clock")
el, how = status_elapsed("status-step")
chk("STATUS elapsed_s ignores a 100s wall-clock step (reads a few seconds)",
    el is not None and 0 <= el < 10, True)
chk("...and names the monotonic clock", how in ("boottime", "monotonic"), True)
el, how = status_elapsed("status-step-ctl", started_mono=None)
chk("control · an unstamped record reads the wall-clock 100s", el is not None and el >= 99, True)
chk("...and says it fell back", str(how).startswith("wall-fallback"), True)

# 6 · A real dispatch carries the stamp this all depends on.
p = mkplan("stamped", [dict(tid="T1", owner="worker-T1")])
subprocess.run([str(SMOKIN), "tick", str(p)], capture_output=True, text=True)
d = json.loads((p / ".smokin" / "dispatch" / "T1.json").read_text())
chk("a real dispatch record carries a monotonic start and its boot",
    [k in d for k in ("started_mono", "mono_clock", "boot_id")], [True, True, True])
chk("...on this boot", d.get("boot_id"), CL.boot_id())
for _ in range(40):
    if (p / "tasks" / "T1" / "RECEIPT.json").is_file():
        break
    time.sleep(0.1)

print("\n=== fresh work is not made stale by a clock step ===")
# The emitter used to decide "produced" by comparing FINDINGS.md's mtime with
# the dispatch record's started_ns — both wall clock — so a step back just after
# dispatch read fresh work as stale. It now compares content with what the file
# held at dispatch (`findings_before`). Each case below sets started_ns AHEAD of
# the file's mtime, which is what such a step leaves behind.
import hashlib as _hl


def emit_with(name, findings=None, before="absent", preexisting=None):
    p = mkplan(name, [dict(tid="T1", owner="worker-T1")])
    tdir = p / "tasks" / "T1"
    if preexisting is not None:
        (tdir / "FINDINGS.md").write_text(preexisting)
    rec = {"task": "T1", "seq": "rTEST:T1:1", "run": "rTEST", "attempt": 1,
           "runtime": "demo", "dispatch": "inproc", "placement": "inproc",
           "started": "2026-01-01T00:00:00Z",
           "started_ns": time.time_ns() + 10_000_000_000,   # 10s ahead of any write below
           "started_epoch": time.time(), "budget_s": 60, **CL.stamp()}
    if before != "absent":
        rec["findings_before"] = before
    (p / ".smokin" / "dispatch" / "T1.json").write_text(json.dumps(rec))
    if findings is not None:
        (tdir / "FINDINGS.md").write_text(findings)
    subprocess.run([str(ROOT / "bin" / "smokin-emit"), "T1", "stale-test"],
                   input='{"terminal":"ok","exit":0}', text=True, capture_output=True,
                   env=dict(os.environ, SMOKIN_PLAN=str(p)))
    return json.loads((tdir / "RECEIPT.json").read_text())


def h(text):
    return "sha256:" + _hl.sha256(text.encode()).hexdigest()


old = "# T1\n\nlast attempt\n"


r = emit_with("stale-new", findings="# T1\n\nfound it\n", before=None)
chk("new work written after a backward step reads as done", r.get("claim"), "done")
chk("...decided by content", r.get("produced_by"), "content")
r = emit_with("stale-ctl", findings="# T1\n\nfound it\n")
chk("control · a record without findings_before reads it as partial (the old rule)",
    r.get("claim"), "partial")
has("...and says the old rule decided", str(r.get("produced_by")), "mtime")
r = emit_with("stale-retry-same", preexisting=old, before=h(old))
chk("a retry that left FINDINGS.md unchanged produced nothing", r.get("claim"), "partial")
r = emit_with("stale-retry-new", preexisting=old, before=h(old), findings="# T1\n\nthis attempt\n")
chk("a retry that changed FINDINGS.md produced something", r.get("claim"), "done")
r = emit_with("stale-empty", findings="", before=None)
chk("an empty FINDINGS.md is still nothing", r.get("claim"), "partial")
# A findings_before that is neither null nor a real hash cannot be compared.
# Treating it as "different" marked an UNTOUCHED file done (T16 tried nine
# forms, all read done). It falls back to the mtime rule and says why — and in
# this fixture started_ns is ahead of every write, so the old rule reads partial.
for n, bad in enumerate((42, "", "SHA256:ABC", ["x"], "unhashable: not a regular file",
                         "sha256:" + "0" * 63)):
    r = emit_with(f"stale-malformed-{n}", preexisting=old, before=bad)
    chk(f"an unusable findings_before ({bad!r}) does not make an untouched file done",
        r.get("claim"), "partial")
    has("...and the receipt says it fell back", str(r.get("produced_by")), "unusable")

print("\n=== a receipt check reads no artifact whole ===")
# Plan.receipt re-hashes every artifact a receipt lists, on every tick. It read
# each one whole, so an artifact larger than memory killed `status` and `tick`.
# (A FIFO did not hang it — the old code skipped non-regular files — so the FIFO
# cases below guard the new code, not the old defect; the 1 GiB case is the one
# that tells them apart.) Staleness must mean exactly what it meant before.
def receipt_plan(name):
    p = mkplan(name, [dict(tid="T1", owner="worker-T1")])
    f = p / "tasks" / "T1" / "FINDINGS.md"
    f.write_text("# T1\n\nthe work\n")
    (p / "tasks" / "T1" / "RECEIPT.json").write_text(json.dumps({
        "schema": "smokin.receipt/1", "seq": "rTEST:T1:1", "run": "rTEST", "task": "T1",
        "attempt": 1, "terminal": "ok", "claim": "done", "source": "test",
        "artifacts": {"FINDINGS.md": h("# T1\n\nthe work\n"), "CHANGES.md": None}}))
    return p, f

p, f = receipt_plan("rcpt-same")
r = S.Plan(p).receipt("T1")
chk("an unchanged artifact leaves the receipt fresh", bool(r.get("stale")), False)
p, f = receipt_plan("rcpt-changed")
f.write_text("# T1\n\nsomething else\n")
r = S.Plan(p).receipt("T1")
chk("a changed artifact makes it stale", bool(r.get("stale")), True)
has("...and says so", str(r.get("why")), "hash mismatch")
p, f = receipt_plan("rcpt-missing")
f.unlink()
r = S.Plan(p).receipt("T1")
chk("a missing artifact makes it stale", bool(r.get("stale")), True)
has("...and says it is missing", str(r.get("why")), "missing")
for verb in ("status", "tick"):
    p, f = receipt_plan(f"rcpt-fifo-{verb}")
    f.unlink()
    os.mkfifo(f)
    try:
        subprocess.run([str(SMOKIN), verb, str(p)], capture_output=True, text=True, timeout=20)
        hung = False
    except subprocess.TimeoutExpired:
        hung = True
    chk(f"a FIFO where an artifact was does not hang `smokin {verb}`", hung, False)
r = S.Plan(p).receipt("T1")
chk("...and the receipt reads as stale", bool(r.get("stale")), True)
has("...naming why", str(r.get("why")), "unhashable")

# A 1 GiB artifact (sparse, so it costs no disk) under a 600 MiB address-space
# limit: reading it whole fails with MemoryError; hashing it in chunks does not.
import resource as _res
p, f = receipt_plan("rcpt-huge")
with open(f, "wb") as fh:
    fh.truncate(1 << 30)
(p / "tasks" / "T1" / "RECEIPT.json").write_text(json.dumps({
    "schema": "smokin.receipt/1", "seq": "rTEST:T1:1", "run": "rTEST", "task": "T1",
    "attempt": 1, "terminal": "ok", "claim": "done", "source": "test",
    "artifacts": {"FINDINGS.md": "sha256:" + "0" * 64}}))
def _cap():
    _res.setrlimit(_res.RLIMIT_AS, (600 << 20, 600 << 20))
r = subprocess.run([str(SMOKIN), "status", str(p)], capture_output=True, text=True,
                   timeout=120, preexec_fn=_cap)
chk("a 1 GiB artifact does not crash `smokin status` under a 600 MiB limit",
    "MemoryError" in r.stderr, False)
has("...and status still prints its summary line", r.stdout, "verified")
f.unlink()

print("\n=== what T20 found in the hashing ===")
# Each case below was a refutation of the first hashing fix (T20, 2026-09-17).
import smokin_digest as DG
chk("a hash with a trailing newline is not a hash", DG.is_hash(h(old) + chr(10)), False)
r = emit_with("stale-malformed-newline", preexisting=old, before=h(old) + chr(10))
chk("...so an untouched file with that findings_before is not done", r.get("claim"), "partial")
for bad in ("x" + chr(0) + "y", "x" + chr(0xD800) + "y"):
    try:
        v = DG.file_sha(bad)
        raised = False
    except Exception:
        v, raised = None, True
    chk(f"file_sha({bad!r}) does not raise", raised, False)
    has("...and names the path unhashable", str(v), "unhashable")
big = LAB / "five-gib.bin"
with open(big, "wb") as fh:
    fh.truncate(5 << 30)                       # sparse: costs no disk
t0 = time.monotonic()
v = DG.file_sha(big)
chk("a 5 GiB file is refused as larger than 4 GiB", v, "unhashable: larger than 4 GiB")
chk("...at once, without reading it", time.monotonic() - t0 < 2, True)
big.unlink()

# Empty artifacts are recorded and re-checked as EMPTY_SHA, as they always were.
p, f = receipt_plan("rcpt-empty")
(p / "tasks" / "T1" / "CHANGES.md").write_text("")
rec = json.loads((p / "tasks" / "T1" / "RECEIPT.json").read_text())
rec["artifacts"]["CHANGES.md"] = DG.EMPTY_SHA            # what every emitter wrote before 12b63ef
(p / "tasks" / "T1" / "RECEIPT.json").write_text(json.dumps(rec))
chk("an older receipt listing an unchanged empty artifact stays fresh",
    bool(S.Plan(p).receipt("T1").get("stale")), False)
(p / "tasks" / "T1" / "CHANGES.md").write_text("filled in later\n")
chk("...and filling that artifact afterwards makes it stale",
    bool(S.Plan(p).receipt("T1").get("stale")), True)
p = mkplan("emit-empty-artifact", [dict(tid="T1", owner="worker-T1")])
(p / "tasks" / "T1" / "CHANGES.md").write_text("")
(p / "tasks" / "T1" / "FINDINGS.md").write_text("# T1\n\nwork\n")
(p / ".smokin" / "dispatch" / "T1.json").write_text(json.dumps({
    "task": "T1", "seq": "rTEST:T1:1", "run": "rTEST", "attempt": 1, "runtime": "demo",
    "dispatch": "inproc", "placement": "inproc", "started": "2026-01-01T00:00:00Z",
    "started_ns": 1, "started_epoch": time.time(), "budget_s": 60, "findings_before": None,
    **CL.stamp()}))
subprocess.run([str(ROOT / "bin" / "smokin-emit"), "T1", "empty-test"],
               input='{"terminal":"ok","exit":0}', text=True, capture_output=True,
               env=dict(os.environ, SMOKIN_PLAN=str(p)))
r = json.loads((p / "tasks" / "T1" / "RECEIPT.json").read_text())
chk("the emitter records an empty artifact as the empty hash, not null",
    r["artifacts"].get("CHANGES.md"), DG.EMPTY_SHA)
chk("...while an empty FINDINGS.md still is not produced work",
    emit_with("stale-empty-again", findings="", before=None).get("claim"), "partial")

# A recorded value that is not a hash cannot vouch for anything.
p, f = receipt_plan("rcpt-unhashable-recorded")
f.unlink()
os.mkfifo(f)
rec = json.loads((p / "tasks" / "T1" / "RECEIPT.json").read_text())
rec["artifacts"]["FINDINGS.md"] = "unhashable: not a regular file"
(p / "tasks" / "T1" / "RECEIPT.json").write_text(json.dumps(rec))
r = S.Plan(p).receipt("T1")
chk("a recorded 'unhashable' value does not read as fresh", bool(r.get("stale")), True)
has("...and says the recorded value is not a hash", str(r.get("why")), "not a hash")

# An artifact name that cannot be opened must not crash status or tick.
p = mkplan("rcpt-nul-name", [dict(tid="T1", owner="worker-T1"),
                             dict(tid="T2", owner="worker-T2")])
(p / "tasks" / "T1" / "RECEIPT.json").write_text(json.dumps({
    "schema": "smokin.receipt/1", "seq": "rTEST:T1:1", "run": "rTEST", "task": "T1",
    "attempt": 1, "terminal": "ok", "claim": "done", "source": "test",
    "artifacts": {"bad" + chr(0) + "name": "sha256:" + "0" * 64}}))
for verb in ("status", "tick"):
    r = subprocess.run([str(SMOKIN), verb, str(p)], capture_output=True, text=True, timeout=60)
    chk(f"an artifact name with NUL does not crash `smokin {verb}`", "Traceback" in r.stderr, False)
chk("...and the healthy T2 is still dispatched",
    (p / ".smokin" / "dispatch" / "T2.json").is_file(), True)
for _ in range(40):
    if (p / "tasks" / "T2" / "RECEIPT.json").is_file():
        break
    time.sleep(0.1)

# Whatever sits at FINDINGS.md must not stall a tick. A FIFO hung it, and a
# file bigger than memory (or a link to /dev/zero) killed it — and a stuck tick
# dispatches nothing, the healthy task beside it included.
import stat as _stat
for kind in ("fifo", "devzero", "directory", "unreadable"):
    p = mkplan(f"odd-{kind}", [dict(tid="T1", owner="worker-T1"),
                               dict(tid="T2", owner="worker-T2")])
    f = p / "tasks" / "T1" / "FINDINGS.md"
    if kind == "fifo":
        os.mkfifo(f)
    elif kind == "devzero":
        f.symlink_to("/dev/zero")
    elif kind == "directory":
        f.mkdir()
    else:
        f.write_text("secret\n")
        f.chmod(0)
    t0 = time.monotonic()
    try:
        subprocess.run([str(SMOKIN), "tick", str(p)], capture_output=True, text=True, timeout=20)
        hung = False
    except subprocess.TimeoutExpired:
        hung = True
    chk(f"a {kind} at FINDINGS.md does not stall the tick", hung, False)
    recs = {r.stem: json.loads(r.read_text()) for r in (p / ".smokin" / "dispatch").glob("*.json")}
    chk(f"...T1 is still dispatched", "T1" in recs, True)
    chk(f"...and so is the healthy T2 beside it", "T2" in recs, True)
    has(f"...and T1's record names it unhashable",
        str(recs.get("T1", {}).get("findings_before")), "unhashable")
    if kind == "unreadable":
        f.chmod(0o644)
    if kind != "directory":
        for _ in range(40):
            if all((p / "tasks" / t / "RECEIPT.json").is_file() for t in ("T1", "T2")):
                break
            time.sleep(0.1)

# The emitter hashes its artifacts too; a FIFO among them hung it.
p = mkplan("emit-fifo", [dict(tid="T1", owner="worker-T1")])
os.mkfifo(p / "tasks" / "T1" / "FINDINGS.md")
(p / ".smokin" / "dispatch" / "T1.json").write_text(json.dumps({
    "task": "T1", "seq": "rTEST:T1:1", "run": "rTEST", "attempt": 1, "runtime": "demo",
    "dispatch": "inproc", "placement": "inproc", "started": "2026-01-01T00:00:00Z",
    "started_ns": 1, "started_epoch": time.time(), "budget_s": 60, "findings_before": None,
    **CL.stamp()}))
try:
    subprocess.run([str(ROOT / "bin" / "smokin-emit"), "T1", "fifo-test"],
                   input='{"terminal":"ok","exit":0}', text=True, capture_output=True,
                   timeout=20, env=dict(os.environ, SMOKIN_PLAN=str(p)))
    hung = False
except subprocess.TimeoutExpired:
    hung = True
chk("a FIFO at FINDINGS.md does not hang the emitter", hung, False)
r = json.loads((p / "tasks" / "T1" / "RECEIPT.json").read_text()) if not hung else {}
chk("...and it is not counted as produced work", r.get("claim"), "partial")

p = mkplan("stamped-findings", [dict(tid="T1", owner="worker-T1")])
(p / "tasks" / "T1" / "FINDINGS.md").write_text(old)
subprocess.run([str(SMOKIN), "tick", str(p)], capture_output=True, text=True)
d = json.loads((p / ".smokin" / "dispatch" / "T1.json").read_text())
chk("a real dispatch records what FINDINGS.md held", d.get("findings_before"), h(old))
p = mkplan("stamped-nofindings", [dict(tid="T1", owner="worker-T1")])
subprocess.run([str(SMOKIN), "tick", str(p)], capture_output=True, text=True)
d = json.loads((p / ".smokin" / "dispatch" / "T1.json").read_text())
chk("...and null when there was none", ("findings_before" in d, d.get("findings_before")),
    (True, None))
for q in (LAB / "stamped-findings", LAB / "stamped-nofindings"):
    for _ in range(40):
        if (q / "tasks" / "T1" / "RECEIPT.json").is_file():
            break
        time.sleep(0.1)

print("\n=== D14 · a hashable artifact is always hashed; identity watches only what cannot be ===")
# WHY THIS SHAPE. D13 was going to skip the hash whenever an artifact's identity
# — device, inode, size, mtime, ctime — was unchanged. Measured here, that saves
# 0.03 ms a tick (artifacts are small text files, so the cost is the syscall,
# not the hashing) and it is not sound: this filesystem's mtime granularity is
# ~4 ms, and 193 of 200 back-to-back same-size rewrites share one mtime_ns. So
# the identity is recorded for every artifact and consulted for exactly one
# thing: an artifact with no hash because it was too large to hash. Those were
# watched by nothing at all before.
D = S.D
_real_file_sha = D.file_sha
hashed = []


def counting_file_sha(path, *a, **kw):
    hashed.append(str(path))
    return _real_file_sha(path, *a, **kw)


def counted(fn):
    """Run fn with file_sha counted, and return (result, paths hashed)."""
    hashed.clear()
    D.file_sha = counting_file_sha
    try:
        return fn(), list(hashed)
    finally:
        D.file_sha = _real_file_sha


def receipt_with_ids(name, body, mutate=None):
    """A plan with one task, one artifact, and a receipt recording both the
    artifact's hash and its identity — what the emitter now writes."""
    q = mkplan(name, [dict(tid="T1", owner="worker-T1")])
    f = q / "tasks" / "T1" / "FINDINGS.md"
    f.write_text(body)
    r = {"schema": "smokin.receipt/1", "task": "T1", "claim": "done",
         "artifacts": {"FINDINGS.md": D.file_sha(f, empty_is_none=False)},
         "artifact_ids": {"FINDINGS.md": D.file_id(f)}}
    if mutate:
        mutate(r, f)
    (q / "tasks" / "T1" / "RECEIPT.json").write_text(json.dumps(r))
    return q, f


# THE MEASUREMENT THE DECISION RESTS ON, asserted rather than remembered: two
# same-size rewrites in a row usually share one stamp, so an unchanged identity
# cannot stand in for an unchanged file.
shared = 0
probe = LAB / "granularity-probe"
for _ in range(50):
    probe.write_text("ab")
    a = D.file_id(probe)
    probe.write_text("cd")
    if D.same_id(a, D.file_id(probe)):
        shared += 1
chk("same-size rewrites can share one identity, so identity cannot replace the hash",
    shared > 0, True)

q, f = receipt_with_ids("id-fresh", "unchanged\n")
got, did = counted(lambda: S.Plan(q).receipt("T1"))
chk("an unchanged artifact reads as fresh", got.get("stale"), None)
chk("...and it was hashed to say so, identity or no identity", len(did), 1)

q, f = receipt_with_ids("id-samesize", "before\n")
f.write_text("aft3r\n")                      # same length, likely the same mtime
chk("a same-size rewrite is caught, which identity alone would miss",
    S.Plan(q).receipt("T1").get("stale"), True)

q, f = receipt_with_ids("id-changed", "before\n")
f.write_text("after it grew\n")
got = S.Plan(q).receipt("T1")
chk("a rewritten artifact is stale", got.get("stale"), True)
has("...and the reason names it", got.get("why"), "FINDINGS.md")

q, f = receipt_with_ids("id-gone", "here\n")
f.unlink()
chk("a deleted artifact is stale", S.Plan(q).receipt("T1").get("stale"), True)

q, f = receipt_with_ids("id-fifo", "here\n")
f.unlink()
os.mkfifo(f)
chk("an artifact replaced by a FIFO is stale, and does not hang",
    S.Plan(q).receipt("T1").get("stale"), True)

# A RECEIPT FROM BEFORE THIS CHANGE is unaffected: there was never anything but
# the hash, and there still is not.
q, f = receipt_with_ids("id-older", "old emitter\n",
                        mutate=lambda r, f: r.pop("artifact_ids"))
got, did = counted(lambda: S.Plan(q).receipt("T1"))
chk("a receipt with no artifact_ids reads as fresh", got.get("stale"), None)
chk("...by hashing, exactly as before", len(did), 1)
f.write_text("changed\n")
chk("...and still notices a change", S.Plan(q).receipt("T1").get("stale"), True)

# THE ONE THING IDENTITY IS FOR. Sparse, so this costs no disk: the point is
# the stated size, which is what file_sha refuses on.
q = mkplan("id-huge", [dict(tid="T1", owner="worker-T1")])
big = q / "tasks" / "T1" / "FINDINGS.md"
with open(big, "wb") as fh:
    fh.truncate((4 << 30) + 1)
r = {"schema": "smokin.receipt/1", "task": "T1", "claim": "done",
     "artifacts": {"FINDINGS.md": None},
     "artifact_ids": {"FINDINGS.md": D.file_id(big)}}
(q / "tasks" / "T1" / "RECEIPT.json").write_text(json.dumps(r))
chk("an artifact over 4 GiB has no hash to record",
    D.file_sha(big, empty_is_none=False), "unhashable: larger than 4 GiB")
got, did = counted(lambda: S.Plan(q).receipt("T1"))
chk("an artifact too large to hash is watched by identity", got.get("stale"), None)
chk("...without being read", did, [])
# The sleep is the ~4 ms granule again, and it is the honest thing to write:
# identity cannot see a write that lands in the same granule as the one it
# recorded. Without the sleep this reads FRESH 20 times out of 20 (T26), so the
# window is deterministic inside itself, not rare — it is only BOUNDED, by that
# granule and by the >4 GiB size. A test must not pretend it is not there.
time.sleep(0.05)
with open(big, "r+b") as fh:
    fh.write(b"x")
chk("...and one byte written into it is stale",
    S.Plan(q).receipt("T1").get("stale"), True)
big.unlink()

# THE CONTROL for that: with no identity recorded, an artifact too large to hash
# is watched by nothing — which is the hole D14 keeps closed.
q = mkplan("id-huge-noids", [dict(tid="T1", owner="worker-T1")])
big = q / "tasks" / "T1" / "FINDINGS.md"
with open(big, "wb") as fh:
    fh.truncate((4 << 30) + 1)
(q / "tasks" / "T1" / "RECEIPT.json").write_text(json.dumps(
    {"task": "T1", "artifacts": {"FINDINGS.md": None}}))
with open(big, "r+b") as fh:
    fh.write(b"x")
chk("...and without an identity there is nothing watching it at all",
    S.Plan(q).receipt("T1").get("stale"), None)
big.unlink()

# IDENTITIES ARE COMPARED FOR EQUALITY, NEVER ORDERED. This machine's wall clock
# steps backwards every few minutes, so a recorded mtime in the FUTURE relative
# to the file must read as a difference, not as a newer file.
q = mkplan("id-future", [dict(tid="T1", owner="worker-T1")])
big = q / "tasks" / "T1" / "FINDINGS.md"
with open(big, "wb") as fh:
    fh.truncate((4 << 30) + 1)
ident = dict(D.file_id(big))
ident["mtime_ns"] += 10 ** 12
(q / "tasks" / "T1" / "RECEIPT.json").write_text(json.dumps(
    {"task": "T1", "artifacts": {"FINDINGS.md": None},
     "artifact_ids": {"FINDINGS.md": ident}}))
chk("a recorded mtime in the future is a difference, not a newer file",
    S.Plan(q).receipt("T1").get("stale"), True)
ident["mtime_ns"] -= 2 * 10 ** 12
(q / "tasks" / "T1" / "RECEIPT.json").write_text(json.dumps(
    {"task": "T1", "artifacts": {"FINDINGS.md": None},
     "artifact_ids": {"FINDINGS.md": ident}}))
chk("...and so is one in the past", S.Plan(q).receipt("T1").get("stale"), True)
chk("an identity missing a field is a difference, not a partial match",
    D.same_id({k: v for k, v in D.file_id(big).items() if k != "ctime_ns"},
              D.file_id(big)), False)
big.unlink()

print("\n=== D14 · what is in the receipt cannot decide the receipt ===")
# `{"stale": True, **r}` let a key inside RECEIPT.json overwrite the verdict
# the check had just reached. The spread order is the whole bug.
q, f = receipt_with_ids("rcpt-override", "x\n",
                        mutate=lambda r, _f: r.update(stale=False, why="all good"))
f.write_text("a different length\n")
got = S.Plan(q).receipt("T1")
chk("a 'stale' key in the receipt cannot claim freshness", got.get("stale"), True)
hasnt("...nor supply the reason", got.get("why"), "all good")

print("\n=== D14 · a receipt that cannot be read is stale, never a crash ===")


def receipt_says(name, write):
    q = mkplan(name, [dict(tid="T1", owner="worker-T1")])
    write(q / "tasks" / "T1" / "RECEIPT.json")
    try:
        return S.Plan(q).receipt("T1"), None
    except Exception as e:                       # noqa: BLE001 — that is the check
        return None, f"{e.__class__.__name__}: {e}"


for label, write in (
    ("a receipt that is a JSON array", lambda p: p.write_text("[1, 2]")),
    ("a receipt that is a bare number", lambda p: p.write_text("42")),
    ("a receipt whose artifacts is a list",
     lambda p: p.write_text(json.dumps({"artifacts": ["FINDINGS.md"]}))),
    ("a receipt whose artifacts is a string",
     lambda p: p.write_text(json.dumps({"artifacts": "FINDINGS.md"}))),
    ("a receipt of invalid UTF-8", lambda p: p.write_bytes(b'{"a": "\xff\xfe"}')),
    ("a receipt nested past the recursion limit",
     lambda p: p.write_text("[" * 200000 + "]" * 200000)),
    ("a receipt larger than a receipt can be",
     lambda p: p.write_text('{"artifacts": {}, "pad": "' + "x" * (1 << 21) + '"}')),
    ("a receipt nobody may read", lambda p: (p.write_text("{}"), p.chmod(0))),
):
    got, crash = receipt_says(label.replace(" ", "-")[:40], write)
    chk(f"{label} reads as stale", (crash, (got or {}).get("stale")), (None, True))

# `is_file()` SAT OUTSIDE THE TRY, and on python 3.12 it does not swallow
# EACCES. A task directory that becomes unsearchable while the loop is running
# raised PermissionError straight out of `status`; `smokin run` rebuilds
# Plan(root) every pass, so a mid-run permission change reaches it. (T26.)
q = mkplan("rcpt-dir-locked", [dict(tid="T1", owner="worker-T1")])
(q / "tasks" / "T1" / "RECEIPT.json").write_text(json.dumps({"task": "T1", "artifacts": {}}))
pl = S.Plan(q)                                   # built while it is still readable
(q / "tasks" / "T1").chmod(0)
try:
    got, crash = pl.receipt("T1"), None
except Exception as e:                           # noqa: BLE001 — that is the check
    got, crash = None, f"{e.__class__.__name__}: {e}"
finally:
    (q / "tasks" / "T1").chmod(0o755)
chk("a task directory locked after the plan was read is stale, not a crash",
    (crash, (got or {}).get("stale")), (None, True))

print("\n=== D14 · a file that states size 0 is read, but not followed ===")
# EVERY FILE UNDER /proc IS A REGULAR FILE OF STATED SIZE 0 that yields content
# when read. st_size is the only bound available before reading, so when it
# says 0 the read gets its own, smaller ceiling. Lowered here so the refusal is
# reached deterministically rather than after a megabyte.
PROC = "/proc/self/maps"
chk("a procfs file states size 0", os.stat(PROC).st_size, 0)
chk("...and hashes fine when it fits", D.file_sha(PROC, empty_is_none=False)[:7], "sha256:")
_zmax, _max = D._ZERO_SIZED_MAX, D.MAX_BYTES
try:
    D._ZERO_SIZED_MAX = 1024
    chk("a size-0 file that keeps reading is refused, not followed",
        D.file_sha(PROC, empty_is_none=False),
        "unhashable: reports size 0 but keeps reading")
    # The same branch with the 4 GiB ceiling in force: the grow-while-reading
    # refusal, which st_size alone can never catch.
    D.MAX_BYTES = D._ZERO_SIZED_MAX = 1024
    chk("a file that grows past the ceiling while being read is refused",
        D.file_sha(PROC, empty_is_none=False), "unhashable: larger than 4 GiB")
finally:
    D._ZERO_SIZED_MAX, D.MAX_BYTES = _zmax, _max
chk("...and the ceilings are back", (D._ZERO_SIZED_MAX, D.MAX_BYTES), (1 << 20, 4 << 30))
empty = LAB / "truly-empty"
empty.write_text("")
chk("a really empty file is still empty, not 'keeps reading'",
    D.file_sha(empty, empty_is_none=False), D.EMPTY_SHA)

print("\n=== D14 · the emitter records what it saw ===")
q = mkplan("emit-ids", [dict(tid="T1", owner="worker-T1")])
(q / "tasks" / "T1" / "FINDINGS.md").write_text("emitted\n")
(q / ".smokin" / "dispatch" / "T1.json").write_text(json.dumps({
    "task": "T1", "seq": "rIDS:T1:1", "run": "rIDS", "attempt": 1, "runtime": "demo",
    "dispatch": "inproc", "placement": "inproc", "started": "2026-01-01T00:00:00Z",
    "started_ns": 1, "started_epoch": time.time(), "budget_s": 60,
    "findings_before": None, **CL.stamp()}))
subprocess.run([str(ROOT / "bin" / "smokin-emit"), "T1", "ids-test"],
               input='{"terminal":"ok","exit":0}', text=True, capture_output=True,
               timeout=20, env=dict(os.environ, SMOKIN_PLAN=str(q)))
r = json.loads((q / "tasks" / "T1" / "RECEIPT.json").read_text())
chk("the emitter records an identity for each artifact",
    sorted(r.get("artifact_ids", {})), ["CHANGES.md", "FINDINGS.md", "QUESTIONS.md"])
chk("...with the five fields identity is made of",
    sorted(r["artifact_ids"]["FINDINGS.md"] or {}),
    ["ctime_ns", "dev", "ino", "mtime_ns", "size"])
chk("...and null for an artifact that was never written",
    r["artifact_ids"]["CHANGES.md"], None)
chk("...beside the hash, not instead of it",
    (r["artifacts"]["FINDINGS.md"] or "")[:7], "sha256:")
chk("a receipt the emitter wrote reads as fresh", S.Plan(q).receipt("T1").get("stale"), None)
(q / "tasks" / "T1" / "FINDINGS.md").write_text("emitted\n" * 2)
chk("...and stale once the artifact changes", S.Plan(q).receipt("T1").get("stale"), True)

print()
if fails:
    print(f"\033[31m{fails} failed\033[0m")
else:
    print("\033[32mall continuity checks passed\033[0m")
shutil.rmtree(LAB, ignore_errors=True)
sys.exit(1 if fails else 0)

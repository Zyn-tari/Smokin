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
p = mkplan("park", [dict(tid="T1", owner="human"),
                    dict(tid="T2", owner="worker-b", agent="impl"),
                    dict(tid="T3", owner="worker-c", agent="impl")])
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

t0 = time.time()
r = run_cli(["wait", "--task", "T1", "--timeout", "2", "--interval", "0.1"], p)
chk("an unfinished agent task times out", r.returncode, 3)
chk("...at roughly the timeout, not instantly and not forever",
    1.0 < time.time() - t0 < 12.0, True)
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
t0 = time.time()
r = run_cli(["wait", "--task", "T1", "--timeout", "30", "--interval", "0.1"], p)
chk("a settled task returns immediately", r.returncode, 0)
chk("...well inside the timeout, so it returned on the EVENT not the clock",
    time.time() - t0 < 10.0, True)
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
t0 = time.time()
try:
    r = subprocess.run([sys.executable, str(SMOKIN), "run", "--max-ticks", "2",
                        "--max-wait", "1", "--interval", "0.1", str(p)],
                       capture_output=True, text=True, timeout=60)
    chk("`run` returns even when nothing on disk ever moves", True, True)
    chk("...bounded by --max-wait, not by luck", time.time() - t0 < 55, True)
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
t0 = time.time()
r = run_cli(["run", "--max-ticks", "30", "--interval", "0.2", "--max-wait", "2"], p)
held = time.time() - t0
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

print()
if fails:
    print(f"\033[31m{fails} failed\033[0m")
else:
    print("\033[32mall continuity checks passed\033[0m")
shutil.rmtree(LAB, ignore_errors=True)
sys.exit(1 if fails else 0)

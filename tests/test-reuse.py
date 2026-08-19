#!/usr/bin/env python3
"""Calibrate pane reuse — and the identity that decides who is allowed it.

THE INCIDENT, again, because this is the half that answers it. An operator
watched six agents sit idle, each holding exactly the context the next task
needed, and opened a seventh pane. Token capture measured what a dispatch SPENT;
it could not stop the waste, because it only sees the headless path and the
waste only happens in panes. This is the mechanism that stops it, and the
measurement that says whether it did.

Three claims are under test and they are different claims:

  1 · IDENTITY. `**Agent:**` is the persona and Smokin never read it — a persona
      is a label, not an addressable worker. Reuse is what turns the label into
      something you can send work to, so the parse has to be right and it has to
      default to ABSENT: the largest shipped fixture declares it on none of its
      eight tasks.

  2 · THE ROLE DECIDES, AND ONE ROLE IS FORBIDDEN. Grillin's gate already
      requires the adversarial pass to declare `**Context:** fresh — not a
      subagent of the orchestrator, not a continued session`. A reused agent IS
      a continued session. Reusing a pane there would make Smokin the thing that
      quietly breaks the plan's most load-bearing check while the declaration
      still says it did not — so the loud check is "the adversary is refused a
      pane it would otherwise have got", and the silent control is that every
      other role is unaffected.

  3 · IT NEVER ASKS A LIFECYCLE QUESTION. `herdr agent list` reported two bare
      login shells as idle agents on this machine. The decision is made from
      files; the only question put to the world is an ATTEMPT, whose failure is
      a fact rather than an opinion. That is asserted against the source itself,
      not against a comment.

    python3 tests/test-reuse.py
"""
import ast
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SMOKIN = ROOT / "bin" / "smokin"
spec = importlib.util.spec_from_loader(
    "smokinmod", importlib.machinery.SourceFileLoader("smokinmod", str(SMOKIN)))
S = importlib.util.module_from_spec(spec)
spec.loader.exec_module(S)

fails = 0
LAB = Path(tempfile.mkdtemp(prefix="smokin-reuse."))


def g(d, k):
    """Read a field without trusting that it is there — see test-usage.py. A
    check written as `dec["pane"]` RAISES when the mechanism breaks, and every
    check below it never runs, which is how a broken mechanism produces zero
    failures and a traceback."""
    return (d or {}).get(k) if isinstance(d, dict) else None


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


# ── fixtures ────────────────────────────────────────────────────────────────
# The field register is Grillin's, verbatim in shape: `**Agent:**` shares a line
# with `**Model:**` and `**Effort:**`, separated by `·`, and its value is
# backticked. That layout is exactly why Smokin's field regex is unanchored with
# a `·` lookahead, and a fixture that put Agent alone on its own line would
# prove the parse against a plan nobody writes.
#
#   examples/minimal-passing-plan/tasks/T4/TASK.md
#     **Agent:** `adversary` · **Model:** `claude-opus-5` · **Effort:** xhigh
#     **Owner:** reviewer
#     **Reader:** adversary
#     **Context:** fresh — not a subagent of the orchestrator, not a continued session

def task_md(tid, agent=None, reader=None, dispatch="pane", runtime="demo",
            owner=None, blocked="—", blocks="—", watch="no"):
    L = [f"# {tid} — fixture", "", "**Status:** NOT STARTED"]
    if agent:
        L.append(f"**Agent:** `{agent}` · **Model:** `claude-opus-5` · **Effort:** high")
    L.append(f"**Owner:** {owner or 'worker-' + tid}")
    if reader:
        L.append(f"**Reader:** {reader}")
        if reader == "adversary":
            L.append("**Context:** fresh — not a subagent of the orchestrator, "
                     "not a continued session")
    L += [f"**Blocked by:** {blocked} · **Blocks:** {blocks}",
          f"**Dispatch:** {dispatch} · **Runtime:** `{runtime}`",
          f"**Budget:** 60 · **Interrupt:** no · **Watch:** {watch}",
          "", "## What you own", f"`tasks/{tid}/`",
          "", "## Steps", "1. work",
          "", "## Done means", "```", f"test -s tasks/{tid}/FINDINGS.md", "```",
          "", "## Do NOT", "- Do NOT stray."]
    return "\n".join(L) + "\n"


def mkplan(name, tasks, runtimes=None):
    """`tasks` is a list of kwargs for task_md; the first key is the id."""
    p = LAB / name
    shutil.rmtree(p, ignore_errors=True)
    (p / ".smokin" / "dispatch").mkdir(parents=True)
    # THE RUN ID IS PART OF THE FIXTURE NOW. `pane_history` refuses a pane from
    # a previous run — its sibling mechanism refused cross-run RECALL from the
    # first day and the two halves of one feature had been disagreeing — so a
    # fixture whose dispatch records say `rTEST` has to be a plan whose run IS
    # `rTEST`. A record written by the real `launch` always carries the run it
    # was written in, so this makes the fixture more like the thing it stands
    # in for, not less.
    (p / ".smokin" / "run.json").write_text(json.dumps(
        {"run": "rTEST", "started": "2026-01-01T00:00:00Z", "plan_root": str(p)}) + "\n")
    shutil.copy(ROOT / "examples" / "demo-plan" / "demo-agent.sh", p / "demo-agent.sh")
    (p / ".smokin" / "runtimes.json").write_text(json.dumps(runtimes or {
        "demo": {"headless": "bash demo-agent.sh", "pane": "bash demo-agent.sh {LINE}"}}))
    rows = []
    for kw in tasks:
        tid = kw["tid"]
        (p / "tasks" / tid).mkdir(parents=True)
        (p / "tasks" / tid / "TASK.md").write_text(task_md(**kw))
        rows.append(f"| {tid} | x | {kw.get('blocked', '—')} |")
    (p / "PLAN.md").write_text("# plan\n\n| ID | Task | Blocked by |\n|---|---|---|\n"
                               + "\n".join(rows) + "\n")
    return p


def disp(p, tid, agent=None, dispatch="pane", pane="w9:p1", started_ns=1,
         receipt=True, reuse=None, torn=False):
    """A dispatch record on disk — the only store pane history has, and one that
    already survived completion before this feature existed."""
    f = p / ".smokin" / "dispatch" / f"{tid}.json"
    if torn:
        f.write_text('{"task":"' + tid + '", "dispatch": "pa')
        return
    rec = {"run": "rTEST", "seq": f"rTEST:{tid}:1", "task": tid, "attempt": 1,
           "dispatch": dispatch, "runtime": "demo", "agent": agent,
           "started": "2026-01-01T00:00:00Z", "started_ns": started_ns,
           "started_epoch": 1, "budget_s": 60, "placement": {"pane": pane},
           "pid_or_pane": pane, "session": pane}
    if reuse is not None:
        rec["reuse"] = reuse
    f.write_text(json.dumps(rec, indent=1))
    d = p / "tasks" / tid
    d.mkdir(parents=True, exist_ok=True)
    if receipt:
        (d / "RECEIPT.json").write_text(json.dumps(
            {"schema": "smokin.receipt/1", "task": tid, "terminal": "ok",
             "claim": "done", "result": "did it"}))
    elif (d / "RECEIPT.json").is_file():
        (d / "RECEIPT.json").unlink()


def plan_of(p):
    return S.Plan(Path(p))


print("=== the persona is parsed, and it defaults to absent ===")
# `**Agent:**` was never read: `grep RE_AGENT bin/smokin` returned nothing before
# this change. It is not `**Owner:**` — Grillin says so beside its own regex —
# and the two carry different kinds of value.
p = mkplan("parse", [dict(tid="T1", agent="implementer", owner="worker-a"),
                     dict(tid="T2", agent="adversary", reader="adversary"),
                     dict(tid="T3", agent="health", reader="health"),
                     dict(tid="T4")])
pl = plan_of(p)
chk("the persona is parsed off a shared field line", pl.tasks["T1"].agent, "implementer")
chk("...with the backticks stripped, exactly like **Runtime:**",
    "`" in pl.tasks["T1"].agent, False)
chk("...and the Model that shares its line is not swallowed",
    pl.tasks["T1"].agent, "implementer")
chk("**Owner:** is a different field and still means what it meant",
    pl.tasks["T1"].owner, "worker-a")
chk("the reader role is parsed", pl.tasks["T2"].reader, "adversary")
chk("...both of them", pl.tasks["T3"].reader, "health")
# THE SILENT CONTROL FOR THE WHOLE FEATURE. 9 of the 20 TASK.md shipped across
# both repositories declare a persona; the LARGEST fixture — 8 tasks — declares
# none. Absent is the common case, not the edge case.
chk("a task that declares no persona reports absence, not a guess",
    pl.tasks["T4"].agent, "")
chk("...and no reader role either", pl.tasks["T4"].reader, "")
chk("...and the tasks that DO declare one are unaffected by it",
    sorted(t.agent for t in pl.tasks.values() if t.agent),
    ["adversary", "health", "implementer"])


print("\n=== the role decides, before any pane is looked for ===")
def fake_task(agent="", reader=""):
    t = S.Task.__new__(S.Task)
    t.id, t.agent, t.reader = "TX", agent, reader
    return t


k, why = S.reuse_class(fake_task(reader="adversary"))
chk("the adversary is FORBIDDEN reuse", k, S.REUSE_FORBIDDEN)
has("...and the reason cites the gate that already requires it", why,
    "not a continued session")
k, why = S.reuse_class(fake_task(reader="health"))
chk("the health reader is PREFERRED for reuse", k, S.REUSE_PREFERRED)
has("...because its contamination is the qualification", why, "required")
k, why = S.reuse_class(fake_task())
chk("ordinary work is PERMITTED", k, S.REUSE_PERMITTED)
has("...and the permission is stated with its cost", why, "survives into this one")
# The class is a permission, never an instruction. A PREFERRED role with nothing
# to reuse still gets a fresh pane — otherwise "preferred" would mean "wait".
p = mkplan("prefno", [dict(tid="T1", agent="health", reader="health")])
d = S.reuse_decision(plan_of(p), plan_of(p).tasks["T1"])
chk("PREFERRED with no history is still a denial", g(d, "allowed"), False)
chk("...and the class is recorded anyway, so the reason is readable",
    g(d, "class"), S.REUSE_PREFERRED)


print("\n=== default-deny, and every denial says which file decided it ===")
p = mkplan("deny", [dict(tid="T1", agent="implementer"),
                    dict(tid="T2", agent="implementer"),
                    dict(tid="T3")])
pl = plan_of(p)
d = S.reuse_decision(pl, pl.tasks["T3"])
chk("no persona declared: denied", g(d, "allowed"), False)
chk("...and it says so rather than skipping silently", g(d, "why"), "agent-not-declared")
d = S.reuse_decision(pl, pl.tasks["T2"])
chk("a persona with no history: denied", g(d, "allowed"), False)
has("...naming the absence", g(d, "why"), "no prior pane")

# T1 dispatched into a pane and is still inside it — no receipt.
disp(p, "T1", agent="implementer", pane="w9:p1", receipt=False)
d = S.reuse_decision(plan_of(p), plan_of(p).tasks["T2"])
chk("a pane whose occupant has not finished: denied", g(d, "allowed"), False)
has("...and the denial names the task that is still in there", g(d, "why"), "T1")

# THE ONE QUESTION THE FILESYSTEM CAN ANSWER. Not "is the pane idle" — a
# RECEIPT.json is the worker's own statement that it stopped.
disp(p, "T1", agent="implementer", pane="w9:p1", receipt=True)
d = S.reuse_decision(plan_of(p), plan_of(p).tasks["T2"])
chk("a pane whose occupant left a receipt: allowed", g(d, "allowed"), True)
chk("...and it is the right pane", g(d, "pane"), "w9:p1")
chk("...and it says whose context this is", g(d, "from_task"), "T1")
chk("...and the class rides along", g(d, "class"), S.REUSE_PERMITTED)

# THE CHECK THIS WHOLE FILE EXISTS FOR. Same persona, same finished pane, same
# everything — and the adversary is refused it. Getting this wrong SILENTLY
# destroys the highest-yield check in the method, because the task still carries
# the `**Context:** fresh` declaration that says it did not happen.
p2 = mkplan("adv", [dict(tid="T1", agent="implementer"),
                    dict(tid="T2", agent="implementer", reader="adversary")])
disp(p2, "T1", agent="implementer", pane="w9:p1", receipt=True)
d = S.reuse_decision(plan_of(p2), plan_of(p2).tasks["T2"])
chk("the adversary is refused a pane it would otherwise have been given",
    g(d, "allowed"), False)
chk("...for the stated reason", g(d, "why"), "reader-adversary-must-be-fresh")
chk("...and it is not silent about it", g(d, "class"), S.REUSE_FORBIDDEN)
# The silent control for that check: the SAME plan with the reader line removed
# allows it. If it denied both, the adversary check would be proving nothing.
p3 = mkplan("advctl", [dict(tid="T1", agent="implementer"),
                       dict(tid="T2", agent="implementer")])
disp(p3, "T1", agent="implementer", pane="w9:p1", receipt=True)
chk("...while the identical plan without the reader line allows it",
    g(S.reuse_decision(plan_of(p3), plan_of(p3).tasks["T2"]), "allowed"), True)
# And the health reader, whose contamination is required, gets it.
p4 = mkplan("hea", [dict(tid="T1", agent="health", reader="health"),
                    dict(tid="T2", agent="health", reader="health")])
disp(p4, "T1", agent="health", pane="w9:p2", receipt=True)
d = S.reuse_decision(plan_of(p4), plan_of(p4).tasks["T2"])
chk("the health reader gets the context it already built", g(d, "allowed"), True)
chk("...recorded as preferred, not merely tolerated", g(d, "class"), S.REUSE_PREFERRED)


print("\n=== what is NOT a candidate ===")
p = mkplan("cand", [dict(tid="T1", agent="implementer"),
                    dict(tid="T2", agent="recon"),
                    dict(tid="T3", agent="implementer"),
                    dict(tid="T4", agent="implementer")])
disp(p, "T1", agent="recon", pane="w9:p1", receipt=True)
d = S.reuse_decision(plan_of(p), plan_of(p).tasks["T3"])
chk("another persona's finished pane is not this persona's",
    g(d, "allowed"), False)
# A REAL inproc record carries a PID in `pid_or_pane`, not None — so the thing
# that must reject it is the `dispatch` field and nothing else. Written with
# `pane=None` this check passed for the wrong reason: it was the empty pane id
# doing the work, and the dispatch clause could have been deleted unnoticed.
# Found by mutation, which is what mutation is for.
disp(p, "T1", agent="implementer", dispatch="inproc", pane=48123, receipt=True)
d = S.reuse_decision(plan_of(p), plan_of(p).tasks["T3"])
chk("an inproc dispatch is not a pane and cannot be reused", g(d, "allowed"), False)
chk("...and a pid is never mistaken for a pane id", g(d, "pane"), None)
disp(p, "T1", agent="implementer", dispatch="pane", pane="w9:p1", receipt=True)
disp(p, "T2", torn=True)
d = S.reuse_decision(plan_of(p), plan_of(p).tasks["T3"])
chk("a torn dispatch record is skipped, not fatal", g(d, "allowed"), True)
chk("...and the good record still decides it", g(d, "pane"), "w9:p1")
# Two finished panes for the same persona: the most recent wins, and `started_ns`
# is the ordering because filenames sort by task id, not by time.
disp(p, "T4", agent="implementer", pane="w9:p7", started_ns=999, receipt=True)
d = S.reuse_decision(plan_of(p), plan_of(p).tasks["T3"])
chk("with two finished panes the most recent one wins", g(d, "pane"), "w9:p7")
# A task is not its own history. Re-dispatching T3 must not reuse T3's pane.
p = mkplan("self", [dict(tid="T3", agent="implementer")])
disp(p, "T3", agent="implementer", pane="w9:p3", receipt=True)
d = S.reuse_decision(plan_of(p), plan_of(p).tasks["T3"])
chk("a task is not its own pane history", g(d, "allowed"), False)


print("\n=== the decision asks the world nothing ===")
# Not a claim about intent — a measurement. Every call this module makes to the
# outside goes through S.sh, so counting them is counting the questions asked.
p = mkplan("pure", [dict(tid="T1", agent="implementer"),
                    dict(tid="T2", agent="implementer")])
disp(p, "T1", agent="implementer", pane="w9:p1", receipt=True)
calls, real_sh = [], S.sh
S.sh = lambda argv, timeout=20: calls.append(list(argv))
try:
    d = S.reuse_decision(plan_of(p), plan_of(p).tasks["T2"])
finally:
    S.sh = real_sh
chk("deciding to reuse ran no subprocess at all", calls, [])
chk("...and still decided", g(d, "allowed"), True)

# The source itself, parsed rather than grepped — because the comments in
# `bin/smokin` NAME these patterns in order to refuse them, and a grep would hit
# its own documentation and pass for the wrong reason.
tree = ast.parse(SMOKIN.read_text())
attrs = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
chk("nothing in the tick signals or probes a pid", "kill" in attrs, False)
herdr_argvs = [[e.value for e in n.elts if isinstance(e, ast.Constant)]
               for n in ast.walk(tree)
               if isinstance(n, ast.List) and n.elts
               and isinstance(n.elts[0], ast.Constant) and n.elts[0].value == "herdr"]
# THE RULE IS ABOUT STATE, NOT ABOUT SURFACES. DESIGN.md: the tick never asks
# herdr what any agent is doing, "including the agents herdr CAN classify" —
# on a real machine `herdr agent list` reported two bare login shells as idle
# agents, and a false idle is indistinguishable from a finished worker.
# Classification is a display concern; the receipt is the contract.
#
# An earlier version of this asserted the subcommand set was exactly {"pane"},
# which encoded the rule by proxy and then broke when dispatch legitimately
# moved from splitting the operator's pane to creating its own TAB. `tab` is a
# layout verb in the same family as `pane`; `agent` is the one that would be a
# lie. Assert the rule itself.
chk("the tick NEVER asks herdr about agent state",
    "agent" in {a[1] for a in herdr_argvs if len(a) > 1}, False)
chk("...and only ever touches layout surfaces",
    sorted({a[1] for a in herdr_argvs if len(a) > 1}), ["pane", "tab"])
chk("...with create, run and close — no rename round-trip, no split",
    sorted({a[2] for a in herdr_argvs if len(a) > 2}),
    ["close", "create", "run"])
# THE OPERATOR'S LAYOUT IS NOT OURS TO CARVE. `--current` means the pane the
# human is sitting in; dispatch used it, so every pane task took a slice of
# whichever tab they had open — nine panes in one workspace, three of them
# beside their own session. Asserted on the source rather than against a live
# herdr, because a live check depends on how many panes the operator happens to
# have open and on the pane ceiling, and a test that passes for reasons outside
# the code is not a test.
chk("dispatch never splits the operator's own pane",
    any("--current" in a for a in herdr_argvs), False)
wrapper = [l for l in (ROOT / "bin" / "smokin-run").read_text().splitlines()
           if not l.lstrip().startswith("#")]
chk("the wrapper signals its child but never polls it",
    any("kill -0" in l or "/proc/" in l for l in wrapper), False)


print("\n=== panes opened per run — the incident's own number ===")
# The incident was a pane being OPENED. So the reading is panes opened, not
# tasks dispatched, and the gap between them is what reuse bought. It needs no
# vendor parsing at all, which is why it can measure the pane path that token
# capture is blind to.
p = mkplan("census", [dict(tid=f"T{i}", agent="implementer") for i in (1, 2, 3, 4)])
chk("a plan that has dispatched nothing counts nothing",
    S.pane_census(plan_of(p)),
    {"dispatches": 0, "opened": 0, "reused": 0, "distinct": 0})
disp(p, "T1", agent="implementer", pane="w9:p1")
disp(p, "T2", agent="implementer", pane="w9:p1",
     reuse={"used": True, "from_task": "T1", "class": "permitted"})
disp(p, "T3", agent="implementer", pane="w9:p5",
     reuse={"used": False, "why": "no prior pane"})
c = S.pane_census(plan_of(p))
chk("three pane dispatches", g(c, "dispatches"), 3)
chk("...but only two panes opened", g(c, "opened"), 2)
chk("...one of them reused", g(c, "reused"), 1)
chk("...and the distinct pane count agrees", g(c, "distinct"), 2)
# A record written before this feature existed carries no `reuse` key. It opened
# a pane, so it counts as one — the reading must not be retroactively flattering.
chk("a pre-feature record counts as a pane opened", g(c, "opened"), 2)
disp(p, "T4", agent="implementer", dispatch="inproc", pane=48123)
c = S.pane_census(plan_of(p))
chk("an inproc dispatch is not a pane and is not counted",
    (g(c, "dispatches"), g(c, "opened")), (3, 2))


# ── end to end, through the real tick ───────────────────────────────────────
print("\n=== end to end, through the real tick ===")
# A herdr stand-in on PATH. It is a stub for HERDR, not for the mechanism: it
# really runs the command it is handed, in the cwd the pane was created with, so
# the wrapper runs, the agent writes FINDINGS.md, the emitter writes a receipt
# and the gate re-runs. What it fakes is only the screen.
STUB = LAB / "stub"
STUB.mkdir()
(STUB / "herdr").write_text(r'''#!/usr/bin/env python3
import json, os, subprocess, sys
st = os.environ["HERDR_STUB_DIR"]
a = sys.argv[1:]
log = open(os.path.join(st, "calls.log"), "a")
if a[:2] == ["tab", "create"]:
    # Dispatch creates a TAB now, not a split of the operator's pane. The log
    # line stays "split <pane>" so every assertion about how many surfaces were
    # opened still reads the same — what changed is where they are, not how
    # many. A tab hands back its root pane, which is what gets run in.
    # Count PANES only. Writing the tab id into the same directory made this
    # count two entries per dispatch, so ids advanced p1, p3, p5 and every
    # assertion naming a specific pane drifted.
    n = len([f for f in os.listdir(os.path.join(st, "panes")) if ":p" in f])
    pid = "w9:p%d" % (n + 1)
    tid = "w9:t%d" % (n + 1)
    cwd = a[a.index("--cwd") + 1] if "--cwd" in a else os.getcwd()
    open(os.path.join(st, "panes", pid), "w").write(cwd)
    open(os.path.join(st, "panes", tid), "w").write(pid)
    log.write("split %s\n" % pid); log.close()
    print(json.dumps({"result": {"root_pane": {"pane_id": pid},
                                 "tab": {"tab_id": tid}}}))
    sys.exit(0)
if a[:2] == ["tab", "close"]:
    log.write("tab-close %s\n" % a[2]); log.close()
    print(json.dumps({"result": {"type": "ok"}}))
    sys.exit(0)
if a[:2] == ["pane", "run"]:
    pid, cmd = a[2], a[3]
    if not os.path.exists(os.path.join(st, "panes", pid)):
        log.write("run-failed %s\n" % pid); log.close()
        print(json.dumps({"error": {"code": "pane_not_found"}}))
        sys.exit(1)
    log.write("run %s\n" % pid); log.close()
    cwd = open(os.path.join(st, "panes", pid)).read()
    # The human closed the pane. Nothing announces that; the next thing sent to
    # it simply comes back pane_not_found.
    if pid in os.environ.get("HERDR_STUB_VANISH", "").split(","):
        os.remove(os.path.join(st, "panes", pid))
    subprocess.Popen(["bash", "-c", cmd], cwd=cwd, start_new_session=True,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    sys.exit(0)
log.write(" ".join(a) + "\n"); log.close()
sys.exit(0)
''')
(STUB / "herdr").chmod(0o755)


def run_plan(p, vanish="", ticks="12"):
    st = p / ".stub"
    shutil.rmtree(st, ignore_errors=True)
    (st / "panes").mkdir(parents=True)
    env = dict(os.environ, PATH=f"{STUB}:{os.environ['PATH']}",
               HERDR_ENV="1", HERDR_STUB_DIR=str(st), HERDR_STUB_VANISH=vanish,
               HERDR_WORKSPACE_ID="w9", HERDR_TAB_ID="w9:t1")
    r = subprocess.run([str(SMOKIN), "run", str(p), "--interval", "1",
                        "--max-ticks", ticks], capture_output=True, text=True, env=env)
    calls = (st / "calls.log").read_text().splitlines() if (st / "calls.log").is_file() else []
    led = [json.loads(l) for l in
           (p / ".smokin" / "ledger.jsonl").read_text().splitlines()] \
        if (p / ".smokin" / "ledger.jsonl").is_file() else []
    return r, calls, led


def rec_of(p, tid):
    f = p / ".smokin" / "dispatch" / f"{tid}.json"
    return json.loads(f.read_text()) if f.is_file() else {}


def st_of(p):
    return json.loads((p / "STATUS.json").read_text())


def led_of(led, event, field, task=None):
    """One field off every ledger line of one kind, never by index. A check
    written `dec[0]["allowed"]` does not FAIL when the ledger goes empty, it
    raises, and every check after it never runs — which is exactly how a broken
    mechanism scores zero failures. Found by mutation: two mutants crashed this
    file instead of failing it."""
    return [g(e, field) for e in led
            if g(e, "event") == event and (task is None or g(e, "task") == task)]


def pane_pair(a2=None, reader=None):
    """T1 → T2 as PANE tasks, plus two inproc fillers.

    Two details of the tick, not of this feature, and both would silently make
    the whole end-to-end prove nothing if they were got wrong. §2b decides the
    route from `**Watch:**`/`**Interrupt:**`/`**Type:**`/`**Budget:**` and never
    from the declared `**Dispatch:**` line — a fixture that only wrote
    `**Dispatch:** pane` would run inproc and every pane check below would pass
    vacuously. And `PANE_CEILING` is 0 at size XS, which is any plan under four
    tasks: the fillers exist to buy a ceiling of 1, which is exactly what a
    sequential pair of pane tasks needs."""
    return [dict(tid="T1", agent="implementer", blocks="T2", watch="yes"),
            dict(tid="T2", agent=a2 or "implementer", blocked="T1", watch="yes",
                 reader=reader),
            dict(tid="T5", dispatch="inproc"), dict(tid="T6", dispatch="inproc")]


# T1 then T2, same persona, both panes. This is the incident in miniature: T1's
# agent finishes and sits there holding context; before this change T2 opened a
# second pane regardless.
p = mkplan("e2e", pane_pair())
r, calls, led = run_plan(p)
chk("the plan completes", r.returncode, 0)
chk("two pane tasks, ONE pane opened", calls.count("split w9:p1"), 1)
chk("...and no second split at all", len([c for c in calls if c.startswith("split")]), 1)
chk("T2 ran in T1's pane", g(rec_of(p, "T2"), "pid_or_pane"), "w9:p1")
chk("...and its record says whose context that is",
    g(g(rec_of(p, "T2"), "reuse"), "from_task"), "T1")
chk("...and that it was actually used", g(g(rec_of(p, "T2"), "reuse"), "used"), True)
chk("...and the session string collapses onto T1's, visibly",
    g(rec_of(p, "T2"), "session"), g(rec_of(p, "T1"), "session"))
pc = g(st_of(p), "panes")
chk("STATUS.json reports one pane opened for two dispatches",
    (g(pc, "opened"), g(pc, "dispatches"), g(pc, "reused")), (1, 2, 1))
has("PROGRESS.md tells a human what reuse cost", (p / "PROGRESS.md").read_text(),
    "a wrong belief formed in the earlier task survives into the later one")
chk("every pane dispatch left a decision in the ledger",
    len(led_of(led, "reuse-decision", "allowed")), 2)
chk("...the first declined and the second allowed",
    led_of(led, "reuse-decision", "allowed"), [False, True])
chk("...the first saying why", led_of(led, "reuse-decision", "why", task="T1"),
    ["no prior pane for this persona in this plan"])
chk("...and the ledger records the reuse actually happening",
    led_of(led, "pane-reused", "from_task"), ["T1"])
chk("both tasks still passed their own gate",
    [json.loads((p / "tasks" / t / "VERDICT.json").read_text())["pass"] for t in ("T1", "T2")],
    [True, True])

# THE ADVERSARY, END TO END. Identical plan but T2 declares the reader role. The
# pane is there, finished, holding the right context — and it must not be given.
p = mkplan("e2e-adv", pane_pair(reader="adversary"))
r, calls, led = run_plan(p)
chk("the adversarial plan completes too", r.returncode, 0)
chk("...having opened TWO panes, not one",
    len([c for c in calls if c.startswith("split")]), 2)
chk("...with the adversary in its own", g(rec_of(p, "T2"), "pid_or_pane"), "w9:p2")
chk("...and its session is NOT the earlier task's",
    g(rec_of(p, "T2"), "session") != g(rec_of(p, "T1"), "session"), True)
chk("...recorded as forbidden rather than merely unavailable",
    g(g(rec_of(p, "T2"), "reuse"), "class"), "forbidden")
chk("...and the ledger carries the refusal with its reason",
    led_of(led, "reuse-decision", "why", task="T2"),
    ["reader-adversary-must-be-fresh"])
chk("...and no reuse was recorded anywhere in the run",
    led_of(led, "pane-reused", "task"), [])
pc = g(st_of(p), "panes")
chk("...so the census reports two panes opened, honestly",
    (g(pc, "opened"), g(pc, "reused")), (2, 0))
has("...and the tick names the role correctly", r.stdout, "T2 is the adversary")

# THE FALLBACK. T1 ran in w9:p1 and then the pane went away — a human closed it,
# which sends SIGHUP and is a first-class terminal state here. T1 still left a
# receipt, so the pane is a perfectly good candidate ON PAPER, and every
# file-readable question says reuse it. Nothing asked whether it was alive;
# the command was sent and the answer came back non-zero. CONFIRMED against the
# real binary, 2026-08-19: `herdr pane run w99:p99 "echo hi"` exits 1 with
# `{"error":{"code":"pane_not_found"}}`.
p = mkplan("e2e-dead", pane_pair())
r, calls, led = run_plan(p, vanish="w9:p1")
chk("a plan whose panes die under it still completes", r.returncode, 0)
chk("the reuse attempt was made and refused", calls.count("run-failed w9:p1"), 1)
chk("...and a fresh pane was opened instead",
    len([c for c in calls if c.startswith("split")]), 2)
chk("...the record says it fell back, not that it reused",
    g(g(rec_of(p, "T2"), "reuse"), "used"), False)
has("...naming what came back", g(g(rec_of(p, "T2"), "reuse"), "fallback"), "returned 1")
# And the tick says the fallback out loud rather than the decision that lost.
# It printed "reuse permitted, T1 finished in w9:p1 and left a receipt" on a
# line announcing a FRESH pane — true, and the wrong half of the story. Caught
# on a real herdr run, not here, which is why it is a check now.
has("...and the tick reports the fallback, not the decision it overrode",
    r.stdout, "opened a fresh pane — reuse permitted, herdr pane run returned 1")
chk("...and the ledger has the fallback event",
    led_of(led, "reuse-fallback", "pane"), ["w9:p1"])
pc = g(st_of(p), "panes")
chk("...and the census counts two panes opened, because two were",
    (g(pc, "opened"), g(pc, "reused")), (2, 0))

# A persona that appears once has nothing to reuse, and that is the ordinary
# case, not a failure. Grillin's own example plan has `recon` on exactly one task.
p = mkplan("e2e-solo", pane_pair(a2="recon"))
r, calls, led = run_plan(p)
chk("two different personas open two panes",
    len([c for c in calls if c.startswith("split")]), 2)
chk("...and each declined for the right reason",
    [("no prior pane" in (w or "")) for w in led_of(led, "reuse-decision", "why")],
    [True, True])


print("\n=== four holes the adversarial pass drove through the containment rule ===")
# EACH ONE IS A THING THAT HAPPENED, not a thing that could. All four are
# decidable from files, which is why they belong here and not in a note.

# 1 · SMOKIN AND GRILLIN HAD TO AGREE ON WHAT AN ADVERSARY IS, AND DID NOT.
# Grillin's gate captures the leading run of letters and demands the
# "not a continued session" declaration; Smokin took the first whitespace token
# and compared it with `==`. A trailing full stop split them, and the task got a
# REUSED pane while its own TASK.md declared it had not.
G_READER = re.compile(r"^\*\*Reader:\*\*\s*([a-z]+)", re.M | re.I)
ROWS = ["adversary", "adversary.", "adversary,", "adversary-fresh",
        "adversary (fresh session)", "ADVERSARY", "health", "health.",
        "implementer"]
disagree = []
for value in ROWS:
    body = f"**Status:** NOT STARTED\n**Reader:** {value}\n"
    gm = G_READER.search(body)
    grillin = (gm.group(1).lower() if gm else "")
    smokin = S.field(S.RE_READER, body).strip().lower()
    if grillin != smokin:
        disagree.append((value, grillin, smokin))
chk("Smokin classifies every reader declaration exactly as Grillin's gate does",
    disagree, [])
# 1b · and the FIRST match anywhere in the file was Smokin's, not the gate's.
decoy = ("**Status:** NOT STARTED\n"
         "**Owner:** worker-a · **Reader:** implementer\n"
         "**Reader:** adversary\n")
dm = G_READER.search(decoy)
chk("a decoy Reader on an earlier shared field line shadows nothing",
    S.field(S.RE_READER, decoy).strip().lower(), dm.group(1).lower())
pd = mkplan("decoy", [dict(tid="T1", agent="implementer"),
                      dict(tid="T2", agent="implementer")])
(pd / "tasks" / "T2" / "TASK.md").write_text(
    (pd / "tasks" / "T2" / "TASK.md").read_text().replace(
        "**Owner:** worker-T2",
        "**Owner:** worker-T2 · **Reader:** implementer\n**Reader:** adversary\n"
        "**Context:** fresh — not a subagent of the orchestrator, not a "
        "continued session"))
disp(pd, "T1", agent="implementer", pane="w9:p1", receipt=True)
chk("...so the shadowed adversary is still refused its pane",
    g(S.reuse_decision(plan_of(pd), plan_of(pd).tasks["T2"]), "why"),
    "reader-adversary-must-be-fresh")
pdot = mkplan("dot", [dict(tid="T1", agent="implementer"),
                      dict(tid="T2", agent="implementer", reader="adversary.")])
disp(pdot, "T1", agent="implementer", pane="w9:p1", receipt=True)
chk("...and so is one declared with a trailing full stop",
    g(S.reuse_decision(plan_of(pdot), plan_of(pdot).tasks["T2"]), "allowed"), False)

# 2 · THE ADVERSARY'S CONTEXT MUST NOT FLOW OUTWARD EITHER. Only the arriving
# task's reader was consulted, so an ordinary worker inherited the pane the plan
# had just spent a whole task keeping clean.
po = mkplan("outward", [dict(tid="T1", agent="recon", reader="adversary"),
                        dict(tid="T2", agent="recon")])
disp(po, "T1", agent="recon", pane="w7:pADV", receipt=True)
d = S.reuse_decision(plan_of(po), plan_of(po).tasks["T2"])
chk("an ordinary task does NOT inherit the adversary's pane", g(d, "allowed"), False)
has("...and the decline says there was nothing it could take", g(d, "why"),
    "no prior pane")
# The silent control: the same plan with T1's reader line removed hands it over.
poc = mkplan("outward-ctl", [dict(tid="T1", agent="recon"),
                             dict(tid="T2", agent="recon")])
disp(poc, "T1", agent="recon", pane="w7:pADV", receipt=True)
chk("...while the identical plan whose T1 is ordinary hands it over",
    g(S.reuse_decision(plan_of(poc), plan_of(poc).tasks["T2"]), "allowed"), True)

# 3 · REUSE IS SCOPED TO THE RUN, which is the rule memory recall followed from
# the first day. A pane held open across runs carries a whole previous run's
# context, silently.
pr = mkplan("crossrun", [dict(tid="T1", agent="implementer"),
                         dict(tid="T2", agent="implementer")])
disp(pr, "T1", agent="implementer", pane="w2:pOLD", receipt=True)
rec = json.loads((pr / ".smokin" / "dispatch" / "T1.json").read_text())
rec["run"] = "rPREVIOUS"
(pr / ".smokin" / "dispatch" / "T1.json").write_text(json.dumps(rec, indent=1))
chk("a pane from a PREVIOUS run is not offered",
    g(S.reuse_decision(plan_of(pr), plan_of(pr).tasks["T2"]), "allowed"), False)
rec["run"] = "rTEST"
(pr / ".smokin" / "dispatch" / "T1.json").write_text(json.dumps(rec, indent=1))
chk("...while the same record inside this run is",
    g(S.reuse_decision(plan_of(pr), plan_of(pr).tasks["T2"]), "allowed"), True)

# 4 · A REAPED RECEIPT IS NOT THE WORKER SAYING IT STOPPED. It is the REAPER
# saying the worker did not. Treating it as a free pane sent a second agent into
# a pane whose first occupant was still running.
pk = mkplan("reaped", [dict(tid="T1", agent="implementer"),
                       dict(tid="T2", agent="implementer")])
disp(pk, "T1", agent="implementer", pane="w9:p1", receipt=True)
(pk / "tasks" / "T1" / "RECEIPT.json").write_text(json.dumps(
    {"schema": "smokin.receipt/1", "task": "T1", "terminal": "reaped",
     "claim": "partial", "source": "reaper", "exit": None, "result": "no envelope"}))
d = S.reuse_decision(plan_of(pk), plan_of(pk).tasks["T2"])
chk("a REAPED receipt does not make the pane free", g(d, "allowed"), False)
has("...and the task counts as still in there, not as finished", g(d, "why"), "T1")
(pk / "tasks" / "T1" / "RECEIPT.json").write_text(json.dumps(
    {"schema": "smokin.receipt/1", "task": "T1", "terminal": "ok",
     "claim": "done", "result": "did it"}))
chk("...while a receipt the WORKER wrote does", 
    g(S.reuse_decision(plan_of(pk), plan_of(pk).tasks["T2"]), "allowed"), True)


print("\n=== verify joins the two halves of the proof it already reads ===")
# Both halves were on disk and nothing connected them: the task declares
# `**Reader:** adversary`, its own dispatch record says `reuse.used: true`, and
# `verify` printed PASS with "independence is unverified" — which understates a
# file in the same directory saying independence was BROKEN.
pv = mkplan("verify-join", [dict(tid="T1", agent="recon"),
                            dict(tid="T2", agent="recon", reader="adversary")])
for tid in ("T1", "T2"):
    (pv / "tasks" / tid / "FINDINGS.md").write_text("real\n")
disp(pv, "T1", agent="recon", pane="w4:pA", receipt=True)
disp(pv, "T2", agent="recon", pane="w4:pA", receipt=True,
     reuse={"class": S.REUSE_FORBIDDEN, "used": True, "allowed": True,
            "pane": "w4:pA", "from_task": "T1"})
r = subprocess.run([str(SMOKIN), "verify", str(pv)], capture_output=True, text=True)
has("verify FAILS a declared adversary that inherited a context", r.stdout,
    "FAIL     T2")
has("...naming the pane and the task it came from", r.stdout, "w4:pA from T1")
chk("...and it is a non-zero exit, not a note", r.returncode, 1)
hasnt("...and does not also call it merely unverified", r.stdout,
      "T2 is declared adversarial")
# The silent control: the same plan whose T2 got its own pane still passes.
pvc = mkplan("verify-join-ctl", [dict(tid="T1", agent="recon"),
                                 dict(tid="T2", agent="recon", reader="adversary")])
for tid in ("T1", "T2"):
    (pvc / "tasks" / tid / "FINDINGS.md").write_text("real\n")
disp(pvc, "T1", agent="recon", pane="w4:pA", receipt=True)
disp(pvc, "T2", agent="recon", pane="w4:pB", receipt=True,
     reuse={"class": S.REUSE_FORBIDDEN, "used": False, "allowed": False,
            "why": "reader-adversary-must-be-fresh"})
r = subprocess.run([str(SMOKIN), "verify", str(pvc)], capture_output=True, text=True)
hasnt("...and an adversary with its own pane is not failed", r.stdout, "FAIL     T2")
has("...it is told what verify cannot see instead", r.stdout,
    "T2 is declared adversarial")
chk("...and that plan verifies clean", r.returncode, 0)


print("\n=== the negative control: a plan that never asked for any of this ===")
# The whole feature must be invisible to a plan that declares no persona and
# dispatches inproc — which is every plan that exists today.
p = mkplan("inert", [dict(tid="T1", dispatch="inproc", blocks="T2"),
                     dict(tid="T2", dispatch="inproc", blocked="T1")])
r = subprocess.run([str(SMOKIN), "run", str(p), "--interval", "1", "--max-ticks", "12"],
                   capture_output=True, text=True)
chk("it completes exactly as before", r.returncode, 0)
chk("...no dispatch record carries a reuse key",
    any("reuse" in rec_of(p, t) for t in ("T1", "T2")), False)
chk("...the persona is recorded as absent, not invented",
    [g(rec_of(p, t), "agent") for t in ("T1", "T2")], [None, None])
led = [json.loads(l) for l in (p / ".smokin" / "ledger.jsonl").read_text().splitlines()]
chk("...the ledger has no reuse events to read",
    [e for e in led if str(g(e, "event") or "").startswith("reuse")], [])
chk("...the census is all zeros",
    g(st_of(p), "panes"), {"dispatches": 0, "opened": 0, "reused": 0, "distinct": 0})
chk("...PROGRESS.md gains no pane section",
    "What this run cost in panes" in (p / "PROGRESS.md").read_text(), False)
chk("...and both verdicts still pass",
    [json.loads((p / "tasks" / t / "VERDICT.json").read_text())["pass"] for t in ("T1", "T2")],
    [True, True])
# `verify` is read-only and must stay that way: it starts nothing, so it can
# never reuse anything, and it must not have grown an opinion about panes.
before = sorted((f.name, f.stat().st_mtime_ns) for f in (p / ".smokin" / "dispatch").iterdir())
subprocess.run([str(SMOKIN), "verify", str(p)], capture_output=True, text=True)
after = sorted((f.name, f.stat().st_mtime_ns) for f in (p / ".smokin" / "dispatch").iterdir())
chk("verify touched no dispatch record", after, before)

# And the health reader gets no independence warning from verify, because
# independence is not what that role is for. The adversary still does.
p = mkplan("verifyroles", [dict(tid="T1", agent="health", reader="health",
                                dispatch="inproc"),
                           dict(tid="T2", agent="adversary", reader="adversary",
                                dispatch="inproc")])
for t in ("T1", "T2"):
    (p / "tasks" / t / "FINDINGS.md").write_text("real\n")
out = subprocess.run([str(SMOKIN), "verify", str(p)], capture_output=True, text=True).stdout
chk("verify warns that the adversary's independence is unverified",
    "T2 is declared adversarial" in out, True)
chk("...and does NOT say it of the health reader, whose contamination is required",
    "T1 is declared adversarial" in out, False)


print(f"\n{'ALL PASS' if not fails else str(fails) + ' FAILED'}  ({LAB})")
if not fails:
    shutil.rmtree(LAB, ignore_errors=True)
sys.exit(1 if fails else 0)

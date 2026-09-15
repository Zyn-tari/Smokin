#!/usr/bin/env python3
"""Does the dispatch line actually REACH a pane?

THE DEFECT, measured 2026-09-15. Every task gets a dispatch line — `read
tasks/<ID>/TASK.md and follow it` — and the pane path only delivers it if the
runtime's `pane` template contains `{LINE}`. `launch()` substitutes the
placeholder; a template without one is handed to `herdr pane run` with the line
built and thrown away. The agent starts at an empty prompt, does nothing, and is
reaped at its full budget with claim `partial` and no artefacts.

Every shipped row had it that way from the first commit, so this is not a
regression — it is a capability nobody exercised. The suite could not catch it:
every fixture in tests/ declares `{LINE}` in its own `pane` row, so the one
existing assertion about a pane command ("the pane command quotes the dispatch
line", tests/test-memory.py) proves QUOTING and never DELIVERY.

THE CLAIM UNDER TEST IS A COMPARISON, NOT A PROMISE. One fixture, one variable:

  mutation  a `pane` row with no {LINE}   the command carries no instruction,
                                          doctor warns, the task is reaped
  control   the identical row WITH it     the command carries the instruction,
                                          doctor is silent

and a third claim about the SHIPPED table, read at run time rather than restated
here: {LINE} is present exactly where a positional prompt was confirmed from the
vendor's own --help, and where it is absent the row says why in its own note. A
test that hardcoded the list would pass on the day somebody added a runtime.

    python3 tests/test-pane-dispatch-line.py
"""
import importlib.machinery
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SMOKIN = ROOT / "bin" / "smokin"
TEMPLATE = ROOT / "templates" / "runtimes.json"
LAB = Path(tempfile.mkdtemp(prefix="smokin-paneline."))
fails = 0

spec = importlib.util.spec_from_loader(
    "smokinmod", importlib.machinery.SourceFileLoader("smokinmod", str(SMOKIN)))
S = importlib.util.module_from_spec(spec)
spec.loader.exec_module(S)

LINE = "read tasks/T1/TASK.md and follow it"


def chk(label, got, want):
    global fails
    ok = got == want
    print(f"  \033[32mPASS\033[0m  {label}" if ok
          else f"  \033[31mFAIL\033[0m  {label}\n        got {got!r}, want {want!r}")
    if not ok:
        fails += 1


def task_md(tid, budget=60):
    return "\n".join([
        f"# {tid} — fixture", "", "**Status:** NOT STARTED",
        "**Agent:** `implementer` · **Model:** `claude-opus-5` · **Effort:** high",
        f"**Owner:** worker-{tid}",
        "**Blocked by:** — · **Blocks:** —",
        "**Dispatch:** pane · **Runtime:** `demo`",
        # §2b routes on Watch/Interrupt/Type/Budget and NEVER on the declared
        # **Dispatch:** line. A fixture that only wrote `Dispatch: pane` would
        # run inproc and every check below would pass vacuously.
        f"**Budget:** {budget} · **Interrupt:** no · **Watch:** yes",
        "", "## What you own", f"`tasks/{tid}/`",
        "", "## Steps", "1. work",
        "", "## Done means", "```", f"test -s tasks/{tid}/FINDINGS.md", "```",
        "", "## Do NOT", "- Do NOT stray."]) + "\n"


def mkplan(name, pane_tmpl, tids=("T1",), budget=60):
    p = LAB / name
    shutil.rmtree(p, ignore_errors=True)
    (p / ".smokin" / "dispatch").mkdir(parents=True)
    shutil.copy(ROOT / "examples" / "demo-plan" / "demo-agent.sh", p / "demo-agent.sh")
    (p / ".smokin" / "runtimes.json").write_text(json.dumps(
        {"demo": {"headless": "bash demo-agent.sh", "pane": pane_tmpl}}))
    rows = []
    for tid in tids:
        (p / "tasks" / tid).mkdir(parents=True)
        (p / "tasks" / tid / "TASK.md").write_text(task_md(tid, budget))
        rows.append(f"| {tid} | x | — |")
    (p / "PLAN.md").write_text("# plan\n\n| ID | Task | Blocked by |\n|---|---|---|\n"
                               + "\n".join(rows) + "\n")
    return p


def command_sent(p, pane_tmpl):
    """The command `launch()` hands to `herdr pane run`, with nothing executed.

    `S.sh` and `S.herdr_pane` are replaced rather than stubbed on PATH: the
    question is what this file BUILDS, and running a real tick to answer it
    would spend a budget to learn something the builder already decided.

    ONE PLAN DIRECTORY FOR BOTH ARMS, rewritten between them. The first version
    of this built a plan per arm, so the two commands differed by their
    `SMOKIN_PLAN=` as well as by the instruction and "they differ ONLY by the
    instruction" could never hold — the check failed on its own fixture. Same
    directory, same task, same run id: the template is the only variable.
    """
    (p / ".smokin" / "runtimes.json").write_text(json.dumps(
        {"demo": {"headless": "bash demo-agent.sh", "pane": pane_tmpl}}))
    cap = {}
    real_sh, real_pane = S.sh, S.herdr_pane
    S.sh = lambda argv, timeout=20: (cap.__setitem__("argv", list(argv)),
                                     type("R", (), {"returncode": 0})())[1]
    S.herdr_pane = lambda plan, t: {"pane": "wSTUB:pZ", "tab": "tZ", "workspace": "w9"}
    try:
        plan = S.Plan(p)
        S.launch(plan, plan.tasks["T1"], S.runtimes(plan))
    finally:
        S.sh, S.herdr_pane = real_sh, real_pane
    return (cap.get("argv") or ["", "", "", ""])[-1]


print("=== the line reaches the pane, or it does not ===")

one = mkplan("one-fixture", "bash demo-agent.sh")
without = command_sent(one, "bash demo-agent.sh")
with_ = command_sent(one, "bash demo-agent.sh {LINE}")

chk("a pane row with no {LINE} carries no instruction", LINE in without, False)
chk("...and the identical row WITH it does", LINE in with_, True)
# Both must be real commands, or the two checks above pass on empty strings —
# the shape that makes a broken mechanism score zero failures.
chk("both arms actually built a command", bool(without) and bool(with_), True)
chk("...and they differ ONLY by the instruction",
    without.strip(), with_.replace(f" '{LINE}'", "").strip())

print("\n=== doctor names it, and is silent when there is nothing to name ===")


def doctor(p):
    r = subprocess.run([str(SMOKIN), "doctor", str(p)], capture_output=True, text=True)
    rep = json.loads((p / ".smokin" / "doctor.json").read_text())
    return r.stdout, rep["runtimes"]["demo"]


out_bad, row_bad = doctor(mkplan("doc-without", "bash demo-agent.sh"))
out_ok, row_ok = doctor(mkplan("doc-with", "bash demo-agent.sh {LINE}"))

chk("doctor reports a pane row that drops the line",
    row_bad.get("pane_drops_dispatch_line"), True)
chk("...and does not report one that carries it",
    row_ok.get("pane_drops_dispatch_line"), False)
chk("...and says so on stdout, where an operator would see it",
    "starts with NO INSTRUCTION" in out_bad, True)
chk("...and stays quiet in the control",
    "starts with NO INSTRUCTION" in out_ok, False)

print("\n=== the shipped table, read rather than restated ===")
tpl = json.loads(TEMPLATE.read_text())
for name in ("claude", "codewhale"):
    chk(f"{name}'s pane row carries the dispatch line",
        "{LINE}" in tpl[name]["pane"], True)
for name in ("opencode", "aider", "codex"):
    # Not a defect and not an oversight: the positional means something else on
    # these runtimes. The row has to SAY so, because an absence with no reason
    # beside it is indistinguishable from the bug this file exists for.
    chk(f"{name} declines the dispatch line...", "{LINE}" in tpl[name]["pane"], False)
    chk(f"...and its note says why", "{LINE}" in (tpl[name].get("note") or ""), True)

print("\n=== and what it costs when the line never arrives ===")
# The string checks above prove DELIVERY. This proves it MATTERS: a pane task
# whose agent was told nothing burns its whole budget and is reaped. Short
# budget, because the claim is the terminal state and not the duration.
STUB = LAB / "stub"
STUB.mkdir(parents=True, exist_ok=True)
(STUB / "herdr").write_text('''#!/usr/bin/env python3
import json, os, sys
a = sys.argv[1:]
if a[:2] == ["tab", "create"]:
    print(json.dumps({"result": {"root_pane": {"pane_id": "w9:p1"},
                                 "tab": {"tab_id": "w9:t1"}}}))
elif a[:2] == ["pane", "run"]:
    open(os.path.join(os.environ["HERDR_STUB_DIR"], "cmd.txt"), "w").write(a[3])
sys.exit(0)
''')
(STUB / "herdr").chmod(0o755)

# Four tasks: PANE_CEILING is 0 at size XS, which is any plan under four, and a
# ceiling-blocked task is queued rather than dispatched.
p = mkplan("reaped", "bash demo-agent.sh", tids=("T1", "T2", "T3", "T4"), budget=3)
st = p / ".stub"; st.mkdir(parents=True, exist_ok=True)
# `--max-wait 1` IS NOT A DETAIL, IT IS 113 SECONDS. After each tick the run
# loop waits for a file to move, capped at MAX_WAIT_S (30s). The stub above
# RECORDS the dispatch and never executes it — which is the point, a real pane
# with no instruction sits there rather than exiting — so in this fixture
# nothing ever moves and every iteration burns the full ceiling. Four pane
# tasks serialised by PANE_CEILING=1 cost 4 x 30s. MEASURED: 120.8s at the
# default, 8.3s at `--max-wait 1`, with T1 still reaped/partial/no artefacts in
# both. The wait is documented in `run` as "an optimisation over the old blind
# sleep, never a gate on the loop"; capping it is what the flag is for.
subprocess.run([str(SMOKIN), "run", str(p), "--interval", "1", "--max-ticks", "8",
                "--max-wait", "1"],
               capture_output=True, text=True,
               env=dict(os.environ, PATH=f"{STUB}:{os.environ['PATH']}",
                        HERDR_ENV="1", HERDR_STUB_DIR=str(st),
                        HERDR_WORKSPACE_ID="w9", HERDR_TAB_ID="w9:t1"))
rcpt = json.loads((p / "tasks" / "T1" / "RECEIPT.json").read_text())
chk("the task whose agent was told nothing is reaped", rcpt.get("terminal"), "reaped")
chk("...and claims only partial", rcpt.get("claim"), "partial")
chk("...having produced nothing", rcpt.get("artifacts"), {})

print()
shutil.rmtree(LAB, ignore_errors=True)
sys.exit(1 if fails else 0)

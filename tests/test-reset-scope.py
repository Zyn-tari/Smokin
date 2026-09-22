#!/usr/bin/env python3
"""`smokin reset --run <id>` must mean that run, and only that run.

THE INCIDENT. `--run` was accepted, documented in `--help` and in DESIGN.md's
risk row 14 as retiring "a run's" receipts, and then never read: `reset(plan,
run)` ignored its own parameter and wiped every task in the plan. A completed
plan lost its verified work to `smokin reset --run totally-fake-run-id-999` — an
id that had never existed — and got a success message. Found by a QA sweep,
2026-09-22; the owner's ruling is D16.

So this file asks three questions, and the third is the one that cost work:

  1 · does a scoped reset clear the run it names?          (it must still work)
  2 · does it leave every other run alone?                 (the scoping)
  3 · does an id nobody has ever seen change NOTHING?      (the typo)

Check 1 is the silent control for checks 2 and 3. A reset that scopes perfectly
by refusing to delete anything would pass both of them and be useless.

    python3 tests/test-reset-scope.py
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SMOKIN = ROOT / "bin" / "smokin"
LAB = Path(tempfile.mkdtemp(prefix="smokin-reset-scope."))
fails = 0


def chk(label, got, want):
    global fails
    if got == want:
        print(f"  \033[32mPASS\033[0m  {label}")
    else:
        fails += 1
        print(f"  \033[31mFAIL\033[0m  {label} — want {want!r}, got {got!r}")


def cli(*args):
    r = subprocess.run([sys.executable, str(SMOKIN), "reset", *args],
                       capture_output=True, text=True, timeout=180)
    return r.returncode, (r.stdout + r.stderr)


def mkplan(name):
    """Two tasks, dispatched under two DIFFERENT run ids, both with work on disk.

    T1 belongs to run rAAA, T2 to run rBBB. Everything a reset deletes is
    present for both, so anything left behind is visible.
    """
    p = LAB / name
    shutil.rmtree(p, ignore_errors=True)
    (p / ".smokin" / "dispatch").mkdir(parents=True)
    (p / ".smokin" / "spool" / "inbox").mkdir(parents=True)
    (p / ".smokin" / "run.json").write_text(json.dumps(
        {"run": "rAAA", "started": "2026-01-01T00:00:00Z", "plan_root": str(p)}) + "\n")
    rows = []
    for tid, rid in (("T1", "rAAA"), ("T2", "rBBB")):
        d = p / "tasks" / tid
        d.mkdir(parents=True)
        (d / "TASK.md").write_text(
            f"# {tid} — x\n\n**Status:** DONE\n**Owner:** worker-{tid}\n"
            f"**Blocked by:** — · **Blocks:** —\n\n## Done means\n```\ntrue\n```\n")
        seq = f"{rid}:{tid}:1"
        (d / "RECEIPT.json").write_text(json.dumps(
            {"schema": "smokin.receipt/1", "seq": seq, "run": rid, "task": tid,
             "claim": "done", "artifacts": {}}) + "\n")
        (d / "VERDICT.json").write_text(json.dumps({"pass": True, "exit": 0}) + "\n")
        (d / "FINDINGS.md").write_text(f"findings for {tid}\n")
        (p / ".smokin" / "dispatch" / f"{tid}.json").write_text(json.dumps(
            {"task": tid, "seq": seq, "run": rid, "attempt": 1}) + "\n")
        (p / ".smokin" / "spool" / "inbox" / f"1-{seq.replace(':', '_')}.json").write_text(
            json.dumps({"seq": seq, "task": tid,
                        "receipt": f"tasks/{tid}/RECEIPT.json"}) + "\n")
        rows.append(f"| {tid} | x | — |")
    (p / "PLAN.md").write_text("# plan\n\n| ID | Task | Blocked by |\n|---|---|---|\n"
                               + "\n".join(rows) + "\n")
    return p


def state(p, tid):
    """What survives for one task: (receipt, verdict, findings, dispatch, spool)."""
    d = p / "tasks" / tid
    spool = p / ".smokin" / "spool" / "inbox"
    return (
        (d / "RECEIPT.json").exists(),
        (d / "VERDICT.json").exists(),
        (d / "FINDINGS.md").exists(),
        (p / ".smokin" / "dispatch" / f"{tid}.json").exists(),
        any(tid in f.name for f in spool.glob("*.json")) if spool.is_dir() else False,
    )


ALL, NONE = (True,) * 5, (False,) * 5


def status_of(p, tid):
    return "DONE" if "**Status:** DONE" in (p / "tasks" / tid / "TASK.md").read_text() \
        else "NOT STARTED"


print("\n=== 1 · CONTROL · a scoped reset really does reset the run it names ===")
# Without this, "leaves the other run alone" is satisfied by doing nothing.
p = mkplan("scoped")
chk("before: both runs have work on disk", (state(p, "T1"), state(p, "T2")), (ALL, ALL))
rc, out = cli("--run", "rAAA", str(p))
chk("`reset --run rAAA` succeeds", rc, 0)
chk("...and rAAA's task is stripped", state(p, "T1"), NONE)
chk("...and its status goes back", status_of(p, "T1"), "NOT STARTED")

print("\n=== 2 · and it leaves every other run alone ===")
chk("rBBB's receipt, verdict, findings, dispatch and pointer all survive",
    state(p, "T2"), ALL)
chk("...and its status is untouched", status_of(p, "T2"), "DONE")
chk("the message names what it reset", "rAAA" in out and "T1" in out, True)

print("\n=== 3 · an id this plan has never seen changes NOTHING ===")
# The case that cost a real plan its verified work.
p = mkplan("typo")
before = (state(p, "T1"), state(p, "T2"), status_of(p, "T1"), status_of(p, "T2"))
rc, out = cli("--run", "totally-fake-run-id-999", str(p))
chk("a run id that never existed is refused", rc, 2)
chk("...and nothing at all was deleted",
    (state(p, "T1"), state(p, "T2"), status_of(p, "T1"), status_of(p, "T2")), before)
chk("...and it prints the ids that do exist", "rAAA" in out and "rBBB" in out, True)

print("\n=== 4 · bare `reset` refuses; `--all` is how you ask for everything ===")
p = mkplan("bare")
before = (state(p, "T1"), state(p, "T2"))
rc, out = cli(str(p))
chk("`reset` with neither flag refuses", rc, 2)
chk("...and deletes nothing", (state(p, "T1"), state(p, "T2")), before)
chk("...and says how to ask", "--all" in out and "--run" in out, True)

p = mkplan("everything")
rc, out = cli("--all", str(p))
chk("`reset --all` succeeds", rc, 0)
chk("...and clears every run", (state(p, "T1"), state(p, "T2")), (NONE, NONE))
chk("...and every status", (status_of(p, "T1"), status_of(p, "T2")),
    ("NOT STARTED", "NOT STARTED"))

print("\n=== 5 · a scoped reset retires only the rulings it reset ===")
# A ruling is a judgement someone made. Retiring one about a task this reset did
# not touch would make `reset --run <other>` the cheapest way to erase an
# inconvenient judgement — the trail the ruling ledger exists to leave.
sys.path.insert(0, str(ROOT / "bin"))
import smokin_rulings as R                                            # noqa: E402

p = mkplan("rulings")
for tid in ("T1", "T2"):
    R.append_ruling(p / ".smokin", {"class": "gate", "task": tid, "outcome": "REFUTED",
                                    "because": f"planted for {tid}"})
standing = R.standing(p / ".smokin")
chk("both runs have a standing ruling to start with",
    sorted(t for _c, t in standing), ["T1", "T2"])
rc, out = cli("--run", "rAAA", str(p))
standing = R.standing(p / ".smokin")
chk("resetting rAAA retires its own task's ruling",
    ("gate", "T1") in standing, False)
chk("...and leaves the other run's ruling standing",
    ("gate", "T2") in standing, True)

print("\n=== 6 · the run cursor belongs to the current run ===")
# Resetting an OLDER run must not clear the live run's cursor or its halt.
p = mkplan("cursor")
(p / ".smokin" / "HALT.json").write_text(json.dumps({"why": "held"}) + "\n")
rc, out = cli("--run", "rBBB", str(p))          # rBBB is not the current run (rAAA is)
chk("resetting an older run succeeds", rc, 0)
chk("...and the current run's cursor survives", (p / ".smokin" / "run.json").exists(), True)
chk("...and so does the halt it is sitting behind",
    (p / ".smokin" / "HALT.json").exists(), True)
rc, out = cli("--run", "rAAA", str(p))          # now the current one
chk("resetting the current run clears its cursor",
    (rc, (p / ".smokin" / "run.json").exists()), (0, False))
chk("...and its halt", (p / ".smokin" / "HALT.json").exists(), False)

print()
shutil.rmtree(LAB, ignore_errors=True)
if fails:
    print(f"\033[31m{fails} failed\033[0m")
    sys.exit(1)
print("\033[32mall reset-scope checks passed\033[0m")

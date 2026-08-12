#!/usr/bin/env python3
"""Calibrate `smokin verify` — the tick with the fleet removed.

Two QA trials produced the same result: a user wrote a plan, executed it with
one agent, and never touched Smokin. The idea that would have helped them —
the worker's claim is not evidence until something else re-runs the check —
needed no fleet, and was welded to one anyway.

These are the promises `verify` makes. Each is a defect if it breaks.
"""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SMOKIN = ROOT / "bin" / "smokin"
LAB = Path(tempfile.mkdtemp(prefix="smokin-verify."))
fails = 0


def chk(label, got, want):
    global fails
    if got == want:
        print(f"  \033[32mPASS\033[0m  {label}")
    else:
        fails += 1
        print(f"  \033[31mFAIL\033[0m  {label} — want {want!r}, got {got!r}")


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def plan(name, t2_cmd="test -s tasks/T2/OUT.md", rulings=None):
    """A two-task plan with NO receipts and NO dispatch records — the n=1 case."""
    p = LAB / name
    shutil.rmtree(p, ignore_errors=True)
    (p / ".smokin").mkdir(parents=True)
    (p / "PLAN.md").write_text("# plan\n\n**Size:** XS\n\n| ID | Task |\n|---|---|\n| T1 | a |\n")
    (p / ".smokin" / "runtimes.json").write_text(json.dumps({"demo": {"headless": "true"}}))
    for tid, cmd in (("T1", "test -s tasks/T1/OUT.md"), ("T2", t2_cmd)):
        d = p / "tasks" / tid
        d.mkdir(parents=True)
        d.joinpath("TASK.md").write_text(
            f"# {tid} — test\n\n**Status:** NOT STARTED\n**Owner:** worker-{tid}\n"
            f"**Blocked by:** — · **Blocks:** —\n"
            f"**Dispatch:** inproc · **Runtime:** `demo`\n"
            f"**Budget:** 60 · **Interrupt:** no · **Watch:** no\n\n"
            f"## Done means\n```\n{cmd}\n```\n\n## Do NOT\n- Do NOT stray.\n")
    # the work is already done — by a human, by hand, leaving no receipt behind
    (p / "tasks" / "T1" / "OUT.md").write_text("done by hand\n")
    (p / "tasks" / "T2" / "OUT.md").write_text("done by hand\n")
    if rulings is not None:
        (p / "_RULINGS.toml").write_text(rulings)
    return p


def run(cmd, p, *extra):
    r = subprocess.run([sys.executable, str(SMOKIN), cmd, str(p), *extra],
                       capture_output=True, text=True, timeout=120)
    return r.returncode, r.stdout + r.stderr


print("Smokin — verify calibration\n")

print("=== the n=1 case: no receipts, no dispatch records, work already done ===")
P = plan("clean")
before = {t: sha(P / "tasks" / t / "TASK.md") for t in ("T1", "T2")}
rc, out = run("verify", P)
chk("exits 0 when every task passes its own gate", rc, 0)
chk("wrote T1's verdict", json.loads((P / "tasks/T1/VERDICT.json").read_text())["pass"], True)
chk("wrote T2's verdict", json.loads((P / "tasks/T2/VERDICT.json").read_text())["pass"], True)
chk("rendered PROGRESS.md", (P / "PROGRESS.md").is_file(), True)
chk("rendered STATUS.json", (P / "STATUS.json").is_file(), True)

print("\n=== the two promises that make it safe to run on someone's own plan ===")
chk("TASK.md is byte-identical — verify never edits your prose",
    {t: sha(P / "tasks" / t / "TASK.md") for t in ("T1", "T2")}, before)
chk("started nothing — no dispatch records",
    list((P / ".smokin" / "dispatch").glob("*.json")) if (P / ".smokin" / "dispatch").is_dir() else [],
    [])
chk("wrote no receipts", list(P.glob("tasks/*/RECEIPT.json")), [])
chk("PROGRESS.md says the task is verified",
    "●" in (P / "PROGRESS.md").read_text(), True)

print("\n=== a claim the gate disagrees with ===")
P = plan("refuted", t2_cmd="test -s tasks/T2/MISSING.md")
rc, out = run("verify", P)
chk("exits 1 when a task fails its own gate", rc, 1)
chk("T2 refuted", json.loads((P / "tasks/T2/VERDICT.json").read_text())["pass"], False)
chk("...and says so on stdout", "REFUTED" in out, True)

print("\n=== --task narrows it to one ===")
P = plan("single")
rc, out = run("verify", P, "--task", "T1")
chk("only T1 was gated", (P / "tasks/T1/VERDICT.json").is_file()
    and not (P / "tasks/T2/VERDICT.json").is_file(), True)
chk("...and an unknown task is an error, not a silent no-op", run("verify", P, "--task", "T9")[0], 2)

print("\n=== verify then tick: tick does not re-gate what verify settled ===")
P = plan("handoff")
run("verify", P)
h = {t: sha(P / "tasks" / t / "VERDICT.json") for t in ("T1", "T2")}
run("tick", P)
chk("verdicts untouched by the following tick",
    {t: sha(P / "tasks" / t / "VERDICT.json") for t in ("T1", "T2")}, h)

print("\n=== verify does not spend model calls ===")
P = plan("norulings", rulings="""
[policy]
uncovered = "accept"

[[ruling]]
class    = "receipt-trust"
when     = "verdict.passed"
persona  = "adversary"
evidence = ["verdict"]
outcomes = ["accept", "reject", "insufficient-evidence"]
default  = "halt"
runtime  = "judge"
""")
(P / "_ROSTER.md").write_text(
    "| Persona | For | Model | Effort | Why |\n|---|---|---|---|---|\n"
    "| `adversary` | judging | `claude-opus-5` | `xhigh` | highest-yield |\n")
(P / "judge-stub.sh").write_text('#!/usr/bin/env bash\ntouch "$SMOKIN_PLAN/JUDGE_RAN"\n')
(P / ".smokin" / "runtimes.json").write_text(json.dumps(
    {"demo": {"headless": "true"}, "judge": {"headless": "bash judge-stub.sh"}}))
rc, out = run("verify", P)
chk("the judge was NOT invoked", (P / "JUDGE_RAN").exists(), False)
chk("...and it says which command would ask", "smokin tick" in out, True)
chk("...and does not claim the plan is finished", rc, 1)

print("\n=== independence is not implied where it cannot be established ===")
P = plan("adversarial")
t = P / "tasks" / "T2" / "TASK.md"
t.write_text(t.read_text().replace("**Owner:** worker-T2",
                                   "**Owner:** reviewer\n**Reader:** adversary"))
rc, out = run("verify", P)
chk("says the adversary's independence is unverified",
    "independence is unverified" in out, True)

print(f"\n{'ALL PASS' if not fails else str(fails) + ' FAILED'}  ({LAB})")
if not fails:
    shutil.rmtree(LAB, ignore_errors=True)
sys.exit(1 if fails else 0)

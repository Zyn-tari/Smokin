#!/usr/bin/env python3
"""Asking a question must not change the thing you asked about.

THE INCIDENT. `bin/smokin` declared a set called READ_ONLY and five of its six
members wrote. All of them reached `Plan.run_id()`, which minted a run id and
SAVED it — inventing a run as a side effect of being asked a question, and
creating `.smokin/` to do it. On a plan the caller could not write that raised
PermissionError, uncaught, and `status` exited **1** — the one code the update
policy reserves for "work is in flight, do not upgrade", so the failure mode was
not just a crash, it was a crash that reads as "do not upgrade now". Grillin's
gate reads the same plan and returns a clean verdict. Found by a QA sweep,
2026-09-22; the owner's ruling is D17.

The fix splits a name that was doing two jobs:

  LONE_TASK_OK     what may run against a single TASK.md with no plan around it
                   — the original meaning, which says nothing about writing.
  WRITES_NOTHING   the contract the old name claimed.

`verify`, `present` and `doctor --fix` are deliberately NOT write-free: a
verdict, a re-rendered PROGRESS.md and a repair are what they PRODUCE. They
must still never crash — they report and do not record.

    python3 tests/test-readonly-commands.py
"""
import importlib.machinery
import json
import importlib.util
import os
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

LAB = Path(tempfile.mkdtemp(prefix="smokin-readonly."))
fails = 0
TRACES = ("Traceback (most recent call last)",)


def chk(label, got, want):
    global fails
    if got == want:
        print(f"  \033[32mPASS\033[0m  {label}")
    else:
        fails += 1
        print(f"  \033[31mFAIL\033[0m  {label} — want {want!r}, got {got!r}")


def mkplan(name):
    """A one-task plan with nothing written in it yet — no `.smokin`, no run."""
    p = LAB / name
    shutil.rmtree(p, ignore_errors=True)
    (p / "tasks" / "T1").mkdir(parents=True)
    (p / "tasks" / "T1" / "TASK.md").write_text(
        "# T1 — x\n\n**Status:** NOT STARTED\n**Owner:** worker-T1\n"
        "**Blocked by:** — · **Blocks:** —\n\n## Done means\n```\nfalse\n```\n")
    (p / "PLAN.md").write_text(
        "# plan\n\n| ID | Task | Blocked by |\n|---|---|---|\n| T1 | x | — |\n")
    return p


def run(cmd, plan, *extra):
    r = subprocess.run([sys.executable, str(SMOKIN), cmd, *extra, str(plan)],
                       capture_output=True, text=True, timeout=180)
    return r.returncode, r.stdout + r.stderr


def leavings(p):
    """What a command left behind that was not there before it ran."""
    return tuple(sorted(n for n in os.listdir(p)
                        if n in (".smokin", "PROGRESS.md", "STATUS.json")))


SIX = ("verify", "doctor", "status", "present", "invariants", "memory")

# A reading that cannot change, so the only thing this can prove or disprove is
# whether the baseline was written at all.
INV = ('[[invariant]]\nname    = "true is still true"\nrun     = "true"\n'
       'because = "a reading that cannot change, so the only thing it can show '
       'is whether a baseline landed"\nbudget_s = 20\n')

print("\n=== 1 · none of the six crashes on a plan it cannot write ===")
for cmd in SIX:
    p = mkplan(f"ro-{cmd}")
    os.chmod(p, 0o555)
    try:
        rc, out = run(cmd, p)
    finally:
        os.chmod(p, 0o755)
    chk(f"`{cmd}` does not traceback", any(t in out for t in TRACES), False)
    chk(f"...and leaves nothing behind", leavings(p), ())

print("\n=== 2 · and `status` never returns 1, which means 'work is in flight' ===")
# The dangerous misread: the update policy says 0 and 3 are safe to upgrade on
# and 1 is not. A crash that exits 1 tells an operator to wait, forever.
p = mkplan("ro-status-code")
os.chmod(p, 0o555)
try:
    rc, out = run("status", p)
finally:
    os.chmod(p, 0o755)
chk("`status` on an unwritable plan does not exit 1", rc == 1, False)
chk("...and still answers", "verified" in out, True)

print("\n=== 3 · CONTROL · on a plan it CAN write, a question still writes nothing ===")
# This is the real contract. "Nothing created" on an unwritable directory is
# satisfied by the filesystem, not by the code — this check is satisfied only
# by the code.
for cmd in ("status", "invariants", "memory"):
    p = mkplan(f"rw-{cmd}")
    rc, out = run(cmd, p)
    chk(f"`{cmd}` on a writable plan leaves nothing behind", leavings(p), ())
    chk(f"...and did not invent a run for it", (p / ".smokin" / "run.json").exists(), False)

print("\n=== 4 · CONTROL · the commands that PRODUCE a file still produce it ===")
# A fix that made everything write-free would break the tool. verify's product
# is a verdict; present's is the re-rendered human surface.
p = mkplan("rw-verify")
rc, out = run("verify", p)
chk("`verify` still writes the verdict it produced",
    (p / "tasks" / "T1" / "VERDICT.json").exists(), True)
p = mkplan("rw-present")
rc, out = run("present", p)
chk("`present` still re-renders PROGRESS.md", (p / "PROGRESS.md").exists(), True)
p = mkplan("rw-doctor")
rc, out = run("doctor", p)
chk("`doctor` still writes its report", (p / ".smokin" / "doctor.json").exists(), True)

print("\n=== 5 · verify reports what it cannot record, and says so ===")
p = mkplan("ro-verify-says")
os.chmod(p, 0o555)
try:
    rc, out = run("verify", p)
finally:
    os.chmod(p, 0o755)
chk("it still names the task's verdict", "T1" in out, True)
chk("...and says the plan cannot be written", "cannot be written" in out, True)
chk("...and wrote no verdict", (p / "tasks" / "T1" / "VERDICT.json").exists(), False)

print("\n=== 6 · at the function: asking never mints a run ===")
p = mkplan("unit")
chk("a read-only plan reports no run rather than inventing one",
    S.Plan(p, readonly=True).run_id(), None)
chk("...and saved nothing", (p / ".smokin").exists(), False)
rid = S.Plan(p).run_id()
chk("a writing plan still mints one", isinstance(rid, str) and rid.startswith("r"), True)
chk("...and saves it", (p / ".smokin" / "run.json").exists(), True)
chk("...and reading it back is the same id", S.Plan(p, readonly=True).run_id(), rid)

print("\n=== 7 · the one mode in the set that PRODUCES still produces ===")
# `invariants` answers a question; `invariants --recapture` takes a baseline
# deliberately and on the record. Marking the command read-only silently
# disabled the second one — the baseline was never written, so a later tick had
# nothing to compare against and a tier-1 breach stopped halting.
p = mkplan("rw-recapture")
(p / "_INVARIANTS.toml").write_text(INV)
rc, out = run("invariants", p, "--recapture")
chk("`invariants --recapture` writes its baseline", (p / ".smokin").exists(), True)
# AND THE BASELINE MUST CARRY A REAL RUN ID. This is the mechanism, not the
# file: marked read-only, `run_id()` returned None, the baseline was stamped
# `run: null`, and the next tick saw a mismatch and RE-captured — taking the
# "before" reading *after* the change it was supposed to catch. A tier-1 breach
# stopped halting and every file involved still existed.
base = json.loads((p / ".smokin" / "baseline.json").read_text()) \
    if (p / ".smokin" / "baseline.json").is_file() else {}
chk("...stamped with a real run id, not null",
    isinstance(base.get("run"), str) and base["run"].startswith("r"), True)
p2 = mkplan("ro-recapture")
(p2 / "_INVARIANTS.toml").write_text(INV)
rc, out = run("invariants", p2)
chk("...and plain `invariants` still writes nothing", leavings(p2), ())

print("\n=== 8 · the two sets say what they mean ===")
chk("WRITES_NOTHING is the write contract",
    sorted(S.WRITES_NOTHING), ["invariants", "memory", "status"])
chk("LONE_TASK_OK is the lone-task contract, unchanged",
    sorted(S.LONE_TASK_OK),
    ["doctor", "invariants", "memory", "present", "status", "verify"])

print()
shutil.rmtree(LAB, ignore_errors=True)
if fails:
    print(f"\033[31m{fails} failed\033[0m")
    sys.exit(1)
print("\033[32mall read-only checks passed\033[0m")

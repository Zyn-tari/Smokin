#!/usr/bin/env python3
"""A result that lands DURING a tick must wake the wait after it.

THE DEFECT, measured 2026-09-16. `run` ticks, then waits for the plan to move.
The wait read its baseline when it STARTED — after the tick — so a worker that
finished while the tick was still running had its receipt inside the baseline.
Nothing moved afterwards, and the loop sat out its whole ceiling (30s) for a
result that was already on disk. Instrumented: 1 wait in 105 across ten runs of
tests/test-reuse.py, timed out at 30.1s with an unreaped RECEIPT present at
wait start. It never hangs — the wait is capped — but every occurrence is a
next task starting up to 30s late.

The race depends on timing, so a test that waited for it would be a flaky test.
This one CAUSES it: the landing is written by a tick wrapper at the end of the
first pass, and the worker itself only sleeps, so nothing else can move a file.

  unit       a receipt after the baseline: no `since` times out, `since` wakes
  external   the external-only pulse ignores what the tick writes, and sees
             every kind of thing that arrives from outside
  preserved  a person editing TASK.md mid-wait still wakes it
  no spin    `since` with nothing new still waits — no busy loop
  run loop   the real `run`, with the landing mid-pass, finishes well inside
             its ceiling; the identical run with `since` removed does not

    python3 tests/test-wait-race.py
"""
import importlib.machinery
import importlib.util
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SMOKIN = ROOT / "bin" / "smokin"
EMIT = ROOT / "bin" / "smokin-emit"
LAB = Path(tempfile.mkdtemp(prefix="smokin-waitrace."))
fails = 0

spec = importlib.util.spec_from_loader(
    "smokinmod", importlib.machinery.SourceFileLoader("smokinmod", str(SMOKIN)))
S = importlib.util.module_from_spec(spec)
spec.loader.exec_module(S)


def chk(label, got, want):
    global fails
    ok = got == want
    print(f"  \033[32mPASS\033[0m  {label}" if ok
          else f"  \033[31mFAIL\033[0m  {label}\n        got {got!r}, want {want!r}")
    if not ok:
        fails += 1


def mkplan(name, runtime_cmd="sleep 20"):
    p = LAB / name
    shutil.rmtree(p, ignore_errors=True)
    (p / ".smokin" / "dispatch").mkdir(parents=True)
    (p / ".smokin" / "runtimes.json").write_text(json.dumps(
        {"hold": {"headless": runtime_cmd}}))
    (p / "tasks" / "T1").mkdir(parents=True)
    (p / "tasks" / "T1" / "TASK.md").write_text("\n".join([
        "# T1 — fixture", "", "**Status:** NOT STARTED", "**Owner:** worker-T1",
        "**Blocked by:** — · **Blocks:** —",
        "**Dispatch:** inproc · **Runtime:** `hold`",
        "**Budget:** 60 · **Interrupt:** no · **Watch:** no",
        "", "## What you own", "`tasks/T1/`", "", "## Steps", "1. work",
        "", "## Done means", "```", "test -s tasks/T1/FINDINGS.md", "```",
        "", "## Do NOT", "- Do NOT stray."]) + "\n")
    (p / "PLAN.md").write_text("# plan\n\n| ID | Task | Blocked by |\n"
                               "|---|---|---|\n| T1 | x | — |\n")
    return p


def timed_wait(plan, **kw):
    t = time.monotonic()
    rc = S.wait(plan, poll=0.05, quiet=True, **kw)
    return rc, time.monotonic() - t


print("=== the wait, with the landing already behind its baseline ===")
p = mkplan("unit")
plan = S.Plan(p)
since = S.plan_pulse(plan, external_only=True)
# The tick's pass is "running": the result lands now, BEFORE the wait starts.
(p / "tasks" / "T1" / "RECEIPT.json").write_text('{"terminal":"ok"}\n')

rc, el = timed_wait(plan, timeout=1.5)
chk("without `since`, a result that landed mid-pass is missed (times out)", rc, 3)
chk("...having waited out the whole ceiling", el >= 1.4, True)
rc, el = timed_wait(plan, timeout=1.5, since=since)
chk("with `since`, the same wait wakes", rc, 0)
chk("...at once, not at the ceiling", el < 0.5, True)

print("\n=== the external pulse sees arrivals and ignores the tick's own writes ===")
p = mkplan("external")
plan = S.Plan(p)
base = S.plan_pulse(plan, external_only=True)
T = p / "tasks" / "T1"
for f, body in ((T / "VERDICT.json", "{}"), (p / "STATUS.json", "{}"),
                (p / ".smokin" / "dispatch" / "T1.json", "{}")):
    f.write_text(body)
    # TASK.md is rewritten by the tick's set_status, so it is not external.
T.joinpath("TASK.md").write_text(T.joinpath("TASK.md").read_text() + "\n")
chk("the tick's own writes do not move the external pulse",
    S.plan_pulse(plan, external_only=True), base)
for rel in ("tasks/T1/RECEIPT.json", "tasks/T1/QUESTIONS.md", "tasks/T1/ANSWER.md",
            ".smokin/HALT.json", ".smokin/spool/inbox/c1.json"):
    f = p / rel
    f.parent.mkdir(parents=True, exist_ok=True)
    before = S.plan_pulse(plan, external_only=True)
    f.write_text("x\n")
    chk(f"an arriving {rel.split('/')[-1]} moves it",
        S.plan_pulse(plan, external_only=True) != before, True)
    f.unlink()

print("\n=== nothing lost, nothing spun ===")
p = mkplan("preserved")
plan = S.Plan(p)
since = S.plan_pulse(plan, external_only=True)
def edit_later():
    time.sleep(0.3)
    tm = p / "tasks" / "T1" / "TASK.md"
    tm.write_text(tm.read_text().replace("NOT STARTED", "BLOCKED"))
threading.Thread(target=edit_later).start()
rc, el = timed_wait(plan, timeout=3, since=since)
chk("a person editing TASK.md mid-wait still wakes it", rc, 0)
chk("...when they edit, not at the ceiling", el < 2, True)
rc, el = timed_wait(S.Plan(p), timeout=1, since=S.plan_pulse(S.Plan(p), external_only=True))
chk("`since` with nothing new still waits — no busy loop", rc, 3)
chk("...for the whole timeout", el >= 0.9, True)

print("\n=== the real run loop, the landing caused mid-pass ===")
MAXW = "4"


def run_with_landing(name, drop_since):
    """`run`, where the FIRST tick ends with T1's result on disk.

    The worker is `sleep 20`, so the only receipt that can exist is the one
    written here. `drop_since` removes the fix at its single seam, so the
    control and the fixed run differ by that and nothing else.
    """
    p = mkplan(name)
    real_tick, real_wait = S.tick, S.wait
    n = [0]

    def tick_then_land(plan, dry=False, close_panes=False):
        rc = real_tick(plan, dry, close_panes)
        n[0] += 1
        if n[0] == 1:
            (p / "tasks" / "T1" / "FINDINGS.md").write_text("done\n")
            subprocess.run([str(EMIT), "T1", "race-test"],
                           input='{"terminal":"ok","exit":0}', text=True,
                           capture_output=True, env=dict(os.environ, SMOKIN_PLAN=str(p)))
        return rc

    def wait_without_since(plan, *a, **kw):
        kw.pop("since", None)
        return real_wait(plan, *a, **kw)

    S.tick = tick_then_land
    if drop_since:
        S.wait = wait_without_since
    argv = sys.argv
    sys.argv = ["smokin", "run", str(p), "--interval", "0.05",
                "--max-ticks", "6", "--max-wait", MAXW]
    t = time.monotonic()
    try:
        rc = S.main()
    finally:
        el = time.monotonic() - t
        S.tick, S.wait, sys.argv = real_tick, real_wait, argv
        rec = p / ".smokin" / "dispatch" / "T1.json"
        try:
            pid = json.loads(rec.read_text()).get("pid_or_pane")
            os.killpg(int(pid), signal.SIGTERM)
        except (OSError, ValueError, TypeError):
            pass
    v = p / "tasks" / "T1" / "VERDICT.json"
    return rc, el, json.loads(v.read_text()).get("pass") if v.is_file() else None


import contextlib, io
with contextlib.redirect_stdout(io.StringIO()):
    rc_fix, el_fix, v_fix = run_with_landing("loop-fixed", drop_since=False)
    rc_bug, el_bug, v_bug = run_with_landing("loop-control", drop_since=True)

chk("the fixed loop finishes the plan", rc_fix, 0)
chk("...with T1 verified", v_fix, True)
chk(f"...without sitting out its {MAXW}s ceiling", el_fix < float(MAXW) - 1, True)
chk("the control (since removed) still finishes", rc_bug, 0)
chk(f"...but only after the full {MAXW}s ceiling — the defect, reproduced",
    el_bug >= float(MAXW), True)

print()
shutil.rmtree(LAB, ignore_errors=True)
sys.exit(1 if fails else 0)

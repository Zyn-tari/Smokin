#!/usr/bin/env python3
"""One persona, one task in flight — the runner's half of worktree contention.

WHERE THIS CAME FROM. The first real run of an 11-track, 180-task plan. Each
persona had ONE persistent worktree, so later tasks would land where earlier ones
did — which is the entire reason to give a persona a durable working directory.
The tick dispatched the whole ready frontier at once and `harness-researcher` was
the declared persona on five of them: two concurrently, then three. Five tasks,
five branches, one worktree. Git does not error on that; it interleaves. Both
tasks reported success and one commit contained the other's staged files. The
worker found it itself:

    "Worktree contention is real: a concurrent task committed my staged files
     into its commit."

The gate's half is grillin's `worktree-disjoint`, which refuses two concurrent
tasks that DECLARE the same worktree. Neither half replaces the other: a gate
cannot see who actually ran, and the runner cannot see a plan that never declared
a worktree at all.

THE CONTROL IS THE POINT. Holding a persona's second task back is only correct if
the first one is genuinely in flight. A cap that also held back DIFFERENT
personas, or that never released, would serialise the whole plan and cost far
more than the collision it prevents.

    python3 tests/test-agent-serialisation.py
"""
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SMOKIN = ROOT / "bin" / "smokin"
LAB = Path(tempfile.mkdtemp(prefix="smokin-agentser."))
fails = 0


def chk(label, got, want):
    global fails
    ok = got == want
    print(f"  \033[32mPASS\033[0m  {label}" if ok
          else f"  \033[31mFAIL\033[0m  {label}\n        got {got!r}, want {want!r}")
    if not ok:
        fails += 1


def plan(name, agents, cap=None):
    """One task per entry in `agents`, all ready, nothing blocking anything."""
    p = LAB / name
    shutil.rmtree(p, ignore_errors=True)
    (p / ".smokin").mkdir(parents=True)
    rows = "\n".join(f"| T{i+1} | a |" for i in range(len(agents)))
    (p / "PLAN.md").write_text(f"# plan\n\n**Size:** M\n\n| ID | Task |\n|---|---|\n{rows}\n")
    (p / ".smokin" / "runtimes.json").write_text(json.dumps({"demo": {"headless": "true"}}))
    if cap is not None:
        (p / "SMOKIN.json").write_text(json.dumps({"max_in_flight_per_agent": cap}))
    for i, agent in enumerate(agents, 1):
        d = p / "tasks" / f"T{i}"
        d.mkdir(parents=True)
        d.joinpath("TASK.md").write_text(
            f"# T{i} — test\n\n**Status:** NOT STARTED\n**Owner:** {agent}\n"
            f"**Agent:** `{agent}`\n"
            f"**Blocked by:** — · **Blocks:** —\n"
            f"**Dispatch:** inproc · **Runtime:** `demo`\n"
            f"**Budget:** 60 · **Interrupt:** no · **Watch:** no\n\n"
            f"## Done means\n```\ntest -s tasks/T{i}/OUT.md\n```\n\n"
            f"## Do NOT\n- Do NOT stray.\n")
    return p


def tick(p):
    r = subprocess.run([sys.executable, str(SMOKIN), "tick", str(p)],
                       capture_output=True, text=True, timeout=120)
    return r.stdout + r.stderr


def dispatched(out):
    return sorted(l.split()[1] for l in out.splitlines() if l.strip().startswith("dispatch "))


try:
    print("=== two tasks, one persona ===")
    P = plan("same", ["infra-builder", "infra-builder"])
    out = tick(P)
    chk("exactly one of them is dispatched", len(dispatched(out)), 1)
    chk("...and the other is HELD, not failed", "agent-busy" in out, True)
    chk("...naming the persona that is busy", "infra-builder" in out, True)

    print("\n=== the control that keeps it from serialising the plan ===")
    P = plan("diff", ["infra-builder", "harness-researcher"])
    out = tick(P)
    chk("two DIFFERENT personas both dispatch in one tick", len(dispatched(out)), 2)

    P = plan("three", ["a-one", "b-two", "c-three"])
    out = tick(P)
    chk("three different personas all dispatch", len(dispatched(out)), 3)

    print("\n=== the hold releases ===")
    P = plan("release", ["infra-builder", "infra-builder"])
    first = dispatched(tick(P))
    chk("tick 1 dispatches one", len(first), 1)
    # the demo runtime is `true`, so the first task is finished; satisfy its gate
    done = first[0]
    (P / "tasks" / done / "OUT.md").write_text("done\n")
    out2 = tick(P)
    chk("tick 2 takes the one that was held",
        bool(set(dispatched(out2)) - set(first)), True)

    print("\n=== the cap is configurable, and the default is 1 ===")
    P = plan("cap2", ["infra-builder", "infra-builder"], cap=2)
    chk("max_in_flight_per_agent:2 lets both go", len(dispatched(tick(P))), 2)
    P = plan("cap0", ["infra-builder", "infra-builder"], cap=0)
    chk("a nonsense cap of 0 is floored at 1, not treated as a stop",
        len(dispatched(tick(P))), 1)

    print("\n=== a plan that declares no persona is unaffected ===")
    P = plan("noagent", ["x", "y"])
    for t in (P / "tasks").iterdir():
        f = t / "TASK.md"
        f.write_text("\n".join(l for l in f.read_text().splitlines()
                               if not l.startswith("**Agent:**")) + "\n")
    chk("both dispatch when no **Agent:** is declared", len(dispatched(tick(P))), 2)

    print("\n=== S8 · a persona can reach the model without a wrapper ===")
    # The persona NAME stays out of the dispatch line — one shaped like
    # `impl; touch /tmp/PWNED #` achieved command execution through it. This is
    # the supported way in: the runtime row says how, smokin resolves it.
    P = plan("persona", ["infra-builder"])
    (P / "_personas").mkdir()
    (P / "_personas" / "infra-builder.md").write_text("# infra-builder\n")
    rts = P / ".smokin" / "runtimes.json"
    rts.write_text(json.dumps({"demo": {
        "headless": "true",
        "persona_flag": "--append-system-prompt-file {PERSONA_FILE}"}}))
    row = json.loads(rts.read_text())["demo"]

    sys.path.insert(0, str(ROOT / "bin"))
    import importlib.machinery, importlib.util
    ld = importlib.machinery.SourceFileLoader("smk", str(SMOKIN))
    smk = importlib.util.module_from_spec(importlib.util.spec_from_loader("smk", ld))
    ld.exec_module(smk)
    pl = smk.Plan(P)
    t = pl.tasks["T1"]
    argv = smk.persona_argv(row, pl, t)
    chk("the flag is expanded", argv[:1], ["--append-system-prompt-file"])
    chk("...to the persona's own file",
        argv[1].endswith("_personas/infra-builder.md"), True)

    # The controls. Each of these is a way the feature could hand the model a
    # broken argument, which is worse than handing it none.
    (P / "_personas" / "infra-builder.md").unlink()
    chk("control · a persona FILE that does not exist drops the flag",
        smk.persona_argv(row, pl, t), [])
    chk("control · a runtime with no persona_flag adds nothing",
        smk.persona_argv({"headless": "true"}, pl, t), [])

    P2 = plan("badname", ["ok-name"])
    pl2 = smk.Plan(P2)
    t2 = pl2.tasks["T1"]
    t2.agent = "impl; touch /tmp/PWNED #"
    chk("control · a persona name that fails RE_AGENT_OK is refused outright",
        smk.persona_argv({"persona_flag": "--p {PERSONA}"}, pl2, t2), [])
    t2.agent = "ok name"
    got = smk.persona_argv({"persona_flag": "--p {PERSONA}"}, pl2, t2)
    chk("control · a legal name with a space survives one round-trip",
        got, ["--p", "ok name"])

    print("\n=== S8b · doctor warns when a flag will swallow the dispatch line ===")
    P3 = plan("variadic", ["x"])
    (P3 / ".smokin" / "runtimes.json").write_text(json.dumps({"demo": {
        "headless": "true --mcp-config"}}))
    r = subprocess.run([sys.executable, str(SMOKIN), "doctor", str(P3)],
                       capture_output=True, text=True, timeout=60)
    chk("doctor warns about the trailing variadic flag",
        "swallow" in (r.stdout + r.stderr).lower()
        or "consume it" in (r.stdout + r.stderr), True)
    P4 = plan("fine", ["x"])
    r = subprocess.run([sys.executable, str(SMOKIN), "doctor", str(P4)],
                       capture_output=True, text=True, timeout=60)
    chk("control · a normal launch string gets no such warning",
        "consume it" in (r.stdout + r.stderr), False)

finally:
    shutil.rmtree(LAB, ignore_errors=True)

print()
print(f"\033[31m{fails} failed\033[0m" if fails
      else "\033[32mall agent-serialisation tests passed\033[0m")
sys.exit(1 if fails else 0)

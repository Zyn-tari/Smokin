#!/usr/bin/env python3
"""The calibration file reaches the worktree, and the caps reach the process.

TWO MECHANISMS, ONE DISPATCH, AND THEY EXIST FOR THE SAME REASON. Grillin's
`tasks/<ID>/CLAUDE.md` says how a worker should behave — response length,
narration, scope, delegation — as opposed to TASK.md, which says what to do. It
is named CLAUDE.md because a harness auto-loads that name from its working
directory and auto-loads nothing else, and it is authored in the task folder
because that is where the gate can see it. Those are two different directories.
Nothing but a dispatch knows both, so nothing but a dispatch can join them.

The caps are the same argument one level down. `Do NOT spawn sub-agents` sat in
Grillin's task template for a year as a line nothing could check. Read out of the
installed bundle (2.1.263), CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS falls back to
20 and CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH to 3 — so a plan that says nothing
gets twenty concurrent subagents, each able to spawn two levels further. Prose
could not change that. A runtimes row can.

THE CONTROL THAT MATTERS MOST is the refusal to clobber. A worktree is a
checkout of somebody's real repository and that repository may have its own
CLAUDE.md, checked in, nothing to do with this plan. Overwriting it would be
invisible — same name, same place, different instructions — and it is the single
most damaging thing this feature could do. It is tested before anything else.

    python3 tests/test-calibration-and-caps.py
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
LAB = Path(tempfile.mkdtemp(prefix="smokin-calib."))
fails = 0


def chk(label, got, want):
    global fails
    ok = got == want
    print(f"  \033[32mPASS\033[0m  {label}" if ok
          else f"  \033[31mFAIL\033[0m  {label}\n        got {got!r}, want {want!r}")
    if not ok:
        fails += 1


DUMP = LAB / "dumpenv.sh"
DUMP.parent.mkdir(parents=True, exist_ok=True)
# A runtime that records the environment it was given. Not `env` itself: smokin
# appends the dispatch line as the last argument and `env <line>` would try to
# execute it. A script ignores extra arguments, which is what a real runtime does.
DUMP.write_text('#!/usr/bin/env bash\nenv > "$SMOKIN_TASK_DIR/ENV.txt"\n')
DUMP.chmod(0o755)


def plan(name, *, calib=None, worktree=None, env=None, headless="true"):
    p = LAB / name
    shutil.rmtree(p, ignore_errors=True)
    (p / ".smokin").mkdir(parents=True)
    (p / "PLAN.md").write_text("# plan\n\n**Size:** M\n\n| ID | Task |\n|---|---|\n| T1 | a |\n")
    row = {"headless": headless}
    if env is not None:
        row["env"] = env
    (p / ".smokin" / "runtimes.json").write_text(json.dumps({"demo": row}))
    d = p / "tasks" / "T1"
    d.mkdir(parents=True)
    d.joinpath("TASK.md").write_text(
        "# T1 — test\n\n**Status:** NOT STARTED\n**Owner:** worker\n**Agent:** `worker`\n"
        + (f"**Worktree:** {worktree}\n" if worktree else "")
        + "**Blocked by:** — · **Blocks:** —\n"
          "**Dispatch:** inproc · **Runtime:** `demo`\n"
          "**Budget:** 60 · **Interrupt:** no · **Watch:** no\n\n"
          "## Done means\n```\ntest -s tasks/T1/OUT.md\n```\n\n## Do NOT\n- Do NOT stray.\n")
    if calib is not None:
        d.joinpath("CLAUDE.md").write_text(calib)
    return p


def tick(p, *extra, parent=None):
    e = dict(os.environ, **(parent or {}))
    subprocess.run([sys.executable, str(SMOKIN), "tick", str(p), *extra],
                   capture_output=True, text=True, timeout=120, env=e)
    return json.loads((p / ".smokin" / "dispatch" / "T1.json").read_text())


try:
    print("=== 1 · PROBE · the refusal to clobber somebody else's CLAUDE.md ===")
    wt = LAB / "wt-theirs"
    wt.mkdir(parents=True, exist_ok=True)
    THEIRS = "# Our project\n\nAlways run `make check` before committing.\n"
    (wt / "CLAUDE.md").write_text(THEIRS)
    rec = tick(plan("theirs", calib="# calibration\n", worktree=str(wt)))
    chk("the project's own CLAUDE.md is byte-identical afterwards",
        (wt / "CLAUDE.md").read_text(), THEIRS)
    chk("...and the dispatch says it was not placed", rec["calibration"]["placed"], False)
    chk("...and says why, in terms a reader can act on",
        "did not write" in rec["calibration"]["why"], True)
    chk("...and names the path it left alone",
        rec["calibration"]["path"], str(wt / "CLAUDE.md"))

    print("\n=== 2 · PROBE · a declared worktree gets the calibration ===")
    wt = LAB / "wt-ok"
    wt.mkdir(parents=True, exist_ok=True)
    rec = tick(plan("ok", calib="# how to behave\n\nBe brief.\n", worktree=str(wt)))
    chk("the file is placed", rec["calibration"]["placed"], True)
    landed = (wt / "CLAUDE.md").read_text()
    chk("...the content arrives", "Be brief." in landed, True)
    chk("...marked, so the next dispatch can tell its own copy from a project's",
        landed.startswith("<!-- smokin:calibration"), True)
    chk("...and the marker names the task it was placed for", "T1" in landed.split("\n")[0], True)

    print("\n=== 3 · CONTROL · smokin overwrites its OWN copy ===")
    # A persona's worktree persists across that persona's tasks — that is the
    # whole reason to give a persona a durable one. Leaving the previous task's
    # calibration would hand this one something specific, plausible and wrong,
    # which is worse than handing it nothing.
    #
    # A FRESH WORKTREE CARRYING A MARKED FILE, rather than a second tick at the
    # one used above. Re-dispatching into a held worktree is the worktree-claim
    # guard's business and it has its own test; borrowing it here would mean this
    # assertion passed or failed for reasons that have nothing to do with
    # calibration. What is under test is one line: a file bearing the marker may
    # be replaced, a file without it may not.
    wt3 = LAB / "wt-mine"
    wt3.mkdir(parents=True, exist_ok=True)
    (wt3 / "CLAUDE.md").write_text(
        "<!-- smokin:calibration placed for T0 from /elsewhere. -->\n# first task\n\nBe brief.\n")
    rec = tick(plan("ok2", calib="# second task\n\nBe verbose.\n", worktree=str(wt3)))
    chk("a marked copy is replaced without asking", rec["calibration"]["placed"], True)
    chk("...with the new task's content", "Be verbose." in (wt3 / "CLAUDE.md").read_text(), True)
    chk("...and the old content is gone", "Be brief." in (wt3 / "CLAUDE.md").read_text(), False)

    print("\n=== 4 · CONTROL · the ordinary cases place nothing and do not complain ===")
    rec = tick(plan("nowt", calib="# x\n"))
    chk("no worktree declared: not placed", rec["calibration"]["placed"], False)
    chk("...and it says so rather than looking like a failure",
        "no worktree" in rec["calibration"]["why"], True)
    rec = tick(plan("nocalib", worktree=str(LAB / "wt-empty")))
    chk("no CLAUDE.md in the task folder: not placed", rec["calibration"]["placed"], False)
    chk("...naming the absent file", "CLAUDE.md" in rec["calibration"]["why"], True)

    print("\n=== 5 · CONTROL · a dry run touches nothing a worker would see ===")
    wt2 = LAB / "wt-dry"
    wt2.mkdir(parents=True, exist_ok=True)
    rec = tick(plan("dry", calib="# x\n", worktree=str(wt2)), "--dry-run")
    chk("the dry dispatch is recorded as dry", rec.get("dry"), True)
    chk("...and no calibration reached the worktree",
        (wt2 / "CLAUDE.md").exists(), False)
    chk("...and the record says nothing was placed", rec["calibration"], None)

    print("\n=== 6 · PROBE · the runtime's env reaches the process ===")
    P = plan("env", env={"CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH": "1",
                         "CLAUDE_CODE_SUBAGENT_MODEL_FORCE": "claude-sonnet-5"},
             headless=str(DUMP))
    rec = tick(P)
    got = (P / "tasks" / "T1" / "ENV.txt").read_text()
    chk("the cap is in the child's environment",
        "CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH=1" in got, True)
    chk("...and so is the forced subagent model",
        "CLAUDE_CODE_SUBAGENT_MODEL_FORCE=claude-sonnet-5" in got, True)
    chk("the dispatch record publishes the KEYS", rec["env"],
        ["CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH", "CLAUDE_CODE_SUBAGENT_MODEL_FORCE"])
    chk("...and never the values — a record is readable by anyone who can read the plan",
        "claude-sonnet-5" in json.dumps(rec), False)

    print("\n=== 7 · CONTROL · a row with no env block sets nothing of its own ===")
    P = plan("noenv", headless=str(DUMP))
    rec = tick(P)
    chk("env is empty rather than absent, so old and new records are distinguishable",
        rec["env"], [])
    chk("nothing was dropped", rec["env_dropped"], None)
    chk("and no variable of this tool's choosing appears",
        "SMOKIN_TEST_CAP" in (P / "tasks" / "T1" / "ENV.txt").read_text(), False)

    print("\n=== 7b · A DISPATCH INHERITS THE OPERATOR'S ENVIRONMENT, and the row wins ===")
    # FOUND BY THIS TEST, not designed for. The first version of the control
    # above asserted that CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH was absent from a
    # child dispatched by a row with no env block. It was present — because the
    # SESSION RUNNING THE TEST had it set, and `env = dict(os.environ, ...)`
    # hands a worker everything the operator's own shell was carrying.
    #
    # That is worth an assertion of its own rather than a workaround. A cap the
    # operator happens to have exported becomes that plan's cap, silently, and a
    # plan run from two different shells is then two different plans. The row is
    # therefore an OVERRIDE and not a set-from-nothing, and the dispatch record's
    # `env` list is the only place a reader can see which of the two won.
    P = plan("inherit", headless=str(DUMP))
    rec = tick(P, parent={"SMOKIN_TEST_CAP": "from-the-shell"})
    chk("an unset row inherits the operator's value",
        "SMOKIN_TEST_CAP=from-the-shell" in (P / "tasks" / "T1" / "ENV.txt").read_text(), True)
    chk("...and the record does NOT claim the row set it", rec["env"], [])

    P = plan("override", env={"SMOKIN_TEST_CAP": "from-the-row"}, headless=str(DUMP))
    rec = tick(P, parent={"SMOKIN_TEST_CAP": "from-the-shell"})
    chk("a row that names the same variable wins",
        "SMOKIN_TEST_CAP=from-the-row" in (P / "tasks" / "T1" / "ENV.txt").read_text(), True)
    chk("...and the inherited value is gone rather than appended twice",
        "from-the-shell" in (P / "tasks" / "T1" / "ENV.txt").read_text(), False)
    chk("...and the record names the key, so the override is visible",
        rec["env"], ["SMOKIN_TEST_CAP"])

    print("\n=== 8 · CONTROL · a malformed key is dropped and NAMED, not applied ===")
    P = plan("badkey", env={"not_upper": "x", "GOOD_ONE": "1", "HAS SPACE": "y"},
             headless=str(DUMP))
    rec = tick(P)
    chk("the valid key survives", rec["env"], ["GOOD_ONE"])
    chk("...and the invalid ones are reported by name",
        sorted(rec["env_dropped"]), ["HAS SPACE", "not_upper"])
    chk("...and never reach the process",
        "not_upper" in (P / "tasks" / "T1" / "ENV.txt").read_text(), False)

finally:
    shutil.rmtree(LAB, ignore_errors=True)
print(f"\n\033[31m{fails} failed\033[0m" if fails else "\n\033[32mall passed\033[0m")
sys.exit(1 if fails else 0)

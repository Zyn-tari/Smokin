#!/usr/bin/env python3
"""Three things a worker's session is owed, and each is only worth having if it cannot lie.

1 · THE PIN. A task's subagents run on the task's own model — the persona file's
    `model:` first, the task's **Model:** second — through the variable its runtime
    row names. It replaces a global `CLAUDE_CODE_SUBAGENT_MODEL_FORCE=claude-sonnet-5`
    that pinned nothing: the bundle only tests FORCE for being set, so subagents had
    been inheriting their parent's model while the row said Sonnet.

2 · THE MERGE. "Every task verified" is not "complete" while a declared branch has
    no integration task downstream — every contract says "Do NOT merge", so in that
    state all the work is still on branches. tick and status must agree about it.

3 · THE DEBRIEF. A cheap model that did not do the work writes four sections about
    a session that finished. It must never block, never recurse, never debrief the
    user's own session, and never fail silently.

    python3 tests/test-subagent-pin-and-integration.py
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SMOKIN = ROOT / "bin" / "smokin"
DEBRIEF = ROOT / "bin" / "smokin-debrief"
HOOK = ROOT / "templates" / "debrief-on-subagent-stop.sh"
LAB = Path(tempfile.mkdtemp(prefix="smokin-pin."))
fails = 0


def chk(label, got, want):
    global fails
    ok = got == want
    print(f"  \033[32mPASS\033[0m  {label}" if ok
          else f"  \033[31mFAIL\033[0m  {label}\n        got {got!r}, want {want!r}")
    if not ok:
        fails += 1


DUMP = LAB / "dumpenv.sh"
DUMP.write_text('#!/usr/bin/env bash\nenv > "$SMOKIN_TASK_DIR/ENV.txt"\n')
DUMP.chmod(0o755)
PIN_ROW = {"headless": str(DUMP), "env": {"CLAUDE_CODE_SUBAGENT_MODEL_FORCE": "1"},
           "subagent_model_env": "CLAUDE_CODE_SUBAGENT_MODEL"}


def plan(name, tasks, row=None):
    """tasks: {tid: dict(model=, agent=, branch=, kind=, blocked=)}"""
    p = LAB / name
    shutil.rmtree(p, ignore_errors=True)
    (p / ".smokin").mkdir(parents=True)
    rows = "\n".join(f"| {t} | a |" for t in tasks)
    (p / "PLAN.md").write_text(f"# plan\n\n**Size:** M\n\n| ID | Task |\n|---|---|\n{rows}\n")
    (p / ".smokin" / "runtimes.json").write_text(json.dumps({"demo": row or {"headless": "true"}}))
    for tid, o in tasks.items():
        d = p / "tasks" / tid
        d.mkdir(parents=True)
        agent = o.get("agent", f"w{tid}")
        model = f" · **Model:** `{o['model']}`" if o.get("model") else ""
        model += f" · **Effort:** {o['effort']}" if o.get("effort") else ""
        extra = "".join(f"**{k}:** {v}\n" for k, v in (("Branch", o.get("branch")),
                                                     ("Kind", o.get("kind"))) if v)
        d.joinpath("TASK.md").write_text(
            f"# {tid} — test\n\n**Status:** NOT STARTED\n**Owner:** {agent}\n"
            f"**Agent:** `{agent}`{model}\n{extra}"
            f"**Blocked by:** {o.get('blocked', '—')} · **Blocks:** —\n"
            f"**Dispatch:** inproc · **Runtime:** `demo`\n"
            f"**Budget:** 60 · **Interrupt:** no · **Watch:** no\n\n"
            f"## Done means\n```\ntest -s tasks/{tid}/OUT.md\n```\n\n## Do NOT\n- Do NOT stray.\n")
    return p


def smokin(*argv, env=None):
    r = subprocess.run([sys.executable, str(SMOKIN), *argv], capture_output=True, text=True,
                       timeout=120, env=dict(os.environ, **(env or {})))
    return r.returncode, r.stdout + r.stderr


def rec_of(p, tid="T1"):
    return json.loads((p / ".smokin" / "dispatch" / f"{tid}.json").read_text())


def child_env(p, tid="T1"):
    return (p / "tasks" / tid / "ENV.txt").read_text()


def run_to_rest(p):
    """Tick until the plan comes to rest, satisfying every gate as it goes."""
    rc, out = 1, ""
    for _ in range(8):
        rc, out = smokin("tick", str(p))
        for d in (p / "tasks").iterdir():
            (d / "OUT.md").write_text("done\n")
        if rc in (0, 3, 4, 5):
            break
    return rc, out


try:
    print("=== 1 · the pin: a task's subagents run on the task's own model ===")
    P = plan("pin-task", {"T1": {"model": "claude-haiku-4-5", "agent": "impl"}}, PIN_ROW)
    smokin("tick", str(P))
    chk("the task's **Model:** reaches the subagent variable",
        "CLAUDE_CODE_SUBAGENT_MODEL=claude-haiku-4-5" in child_env(P), True)
    chk("...with FORCE on, so the worker cannot ask for another",
        "CLAUDE_CODE_SUBAGENT_MODEL_FORCE=1" in child_env(P), True)
    chk("the record says what it pinned and from where",
        rec_of(P)["subagent_model"], {"model": "claude-haiku-4-5", "source": "task **Model:**"})

    P = plan("pin-persona", {"T1": {"model": "claude-sonnet-5", "agent": "impl"}}, PIN_ROW)
    (P / "_personas").mkdir()
    (P / "_personas" / "impl.md").write_text("---\nmodel: opus\n---\nYou are impl.\n")
    smokin("tick", str(P))
    chk("the persona file's model wins over the task's",
        "CLAUDE_CODE_SUBAGENT_MODEL=opus" in child_env(P), True)
    chk("...and the record names the file it came from",
        "persona file _personas/impl.md" in rec_of(P)["subagent_model"]["source"], True)

    P = plan("pin-inherit", {"T1": {"model": "claude-sonnet-5", "agent": "impl"}}, PIN_ROW)
    (P / "_personas").mkdir()
    (P / "_personas" / "impl.md").write_text("---\nmodel: inherit\n---\n")
    smokin("tick", str(P))
    chk("CONTROL · `inherit` in the persona file falls through to the task",
        "CLAUDE_CODE_SUBAGENT_MODEL=claude-sonnet-5" in child_env(P), True)

    print("\n=== 1b · the pin: what it refuses ===")
    P = plan("pin-norow", {"T1": {"model": "claude-haiku-4-5"}},
             {"headless": str(DUMP), "env": {"CLAUDE_CODE_SUBAGENT_MODEL_FORCE": "1"}})
    smokin("tick", str(P))
    chk("a row that names no subagent_model_env pins nothing — a runtime is a row",
        "CLAUDE_CODE_SUBAGENT_MODEL=" in child_env(P), False)
    chk("...and the record says why, rather than claiming a pin",
        (rec_of(P)["subagent_model"]["model"],
         "names no subagent_model_env" in rec_of(P)["subagent_model"]["source"]), (None, True))
    P = plan("pin-evil", {"T1": {"model": "claude-opus-5;touch-x", "agent": "impl"}}, PIN_ROW)
    smokin("tick", str(P))
    chk("a model value that is not an identifier is refused, not exported",
        "touch-x" in child_env(P), False)
    P = plan("pin-none", {"T1": {"agent": "impl"}}, PIN_ROW)
    smokin("tick", str(P))
    chk("CONTROL · no model anywhere: nothing pinned, and the record says subagents inherit",
        (rec_of(P)["subagent_model"]["model"],
         "inherit" in rec_of(P)["subagent_model"]["source"]), (None, True))

    print("\n=== 1c · the worker runs on the persona's model too ===")
    ARGV = LAB / "argvdump.sh"
    ARGV.write_text('#!/usr/bin/env bash\nprintf "%s\\n" "$@" > "$SMOKIN_TASK_DIR/ARGV.txt"\n')
    ARGV.chmod(0o755)
    WROW = {"headless": str(ARGV), "model_flag": "--model {MODEL}"}
    args = lambda p: (p / "tasks" / "T1" / "ARGV.txt").read_text().splitlines()
    P = plan("w-task", {"T1": {"model": "claude-haiku-4-5", "agent": "impl"}}, WROW)
    smokin("tick", str(P))
    a = args(P)
    chk("the worker is launched with --model <the task's model>",
        a[a.index("--model") + 1] if "--model" in a else None, "claude-haiku-4-5")
    chk("...before the dispatch line, which stays last",
        "--model" in a and a.index("--model") < len(a) - 2, True)
    chk("...and the record says what the worker ran on",
        rec_of(P)["worker_model"], {"model": "claude-haiku-4-5", "source": "task **Model:**"})
    P = plan("w-persona", {"T1": {"model": "claude-sonnet-5", "agent": "impl"}}, WROW)
    (P / "_personas").mkdir()
    (P / "_personas" / "impl.md").write_text("---\nmodel: opus\n---\n")
    smokin("tick", str(P))
    a = args(P)
    chk("the persona file's alias reaches the worker, as it reaches the subagents",
        a[a.index("--model") + 1] if "--model" in a else None, "opus")
    P = plan("w-none", {"T1": {"agent": "impl"}}, WROW)
    smokin("tick", str(P))
    chk("CONTROL · no model: no flag at all, never an empty --model", "--model" in args(P), False)
    P = plan("w-norow", {"T1": {"model": "claude-haiku-4-5"}}, {"headless": str(ARGV)})
    smokin("tick", str(P))
    chk("a row with no model_flag passes nothing, and the record says why",
        ("--model" in args(P), "no model_flag" in rec_of(P)["worker_model"]["source"]),
        (False, True))
    P = plan("w-evil", {"T1": {"model": "opus;touch-x", "agent": "impl"}}, WROW)
    smokin("tick", str(P))
    chk("a value that is not a model identifier never reaches the argv",
        any("touch-x" in x for x in args(P)[:-1]), False)

    print("\n=== 1d · the worker runs at the task's declared effort ===")
    EROW = dict(WROW, effort_flag="--effort {EFFORT}")
    val = lambda a, f: a[a.index(f) + 1] if f in a else None
    P = plan("e-high", {"T1": {"model": "claude-sonnet-5", "effort": "high", "agent": "impl"}}, EROW)
    smokin("tick", str(P)); a = args(P)
    chk("the worker is launched with --effort <the task's Effort>", val(a, "--effort"), "high")
    chk("...before the dispatch line, which stays last",
        "--effort" in a and a.index("--effort") < len(a) - 2, True)
    chk("...and the record says what was applied",
        rec_of(P)["worker_effort"], {"effort": "high", "source": "task **Effort:**"})
    P = plan("e-max", {"T1": {"model": "claude-opus-5", "effort": "max", "agent": "impl"}}, EROW)
    smokin("tick", str(P))
    chk("max reaches the worker — the CLI lists all five levels", val(args(P), "--effort"), "max")
    P = plan("e-haiku", {"T1": {"model": "claude-haiku-4-5", "effort": "high", "agent": "impl"}}, EROW)
    smokin("tick", str(P)); a = args(P); we = rec_of(P)["worker_effort"]
    chk("on Haiku, no --effort — the API rejects it and the CLI would drop it", "--effort" in a, False)
    chk("...and the record says why instead of claiming an effort",
        (we["effort"], "rejects the effort" in we["source"]), (None, True))
    chk("...while its --model still goes through", val(a, "--model"), "claude-haiku-4-5")
    P = plan("e-none", {"T1": {"model": "claude-sonnet-5", "agent": "impl"}}, EROW)
    smokin("tick", str(P))
    chk("CONTROL · no Effort declared: no flag", "--effort" in args(P), False)
    P = plan("e-bad", {"T1": {"model": "claude-sonnet-5", "effort": "turbo", "agent": "impl"}}, EROW)
    smokin("tick", str(P))
    chk("an effort the CLI does not accept is refused, not passed",
        ("--effort" in args(P), "refused" in rec_of(P)["worker_effort"]["source"]), (False, True))
    P = plan("e-norow", {"T1": {"model": "claude-sonnet-5", "effort": "high", "agent": "impl"}}, WROW)
    smokin("tick", str(P))
    chk("a row with no effort_flag passes none, and the record says so",
        ("--effort" in args(P), "no effort_flag" in rec_of(P)["worker_effort"]["source"]), (False, True))

    print("\n=== 2 · every task verified is not complete while a branch is unmerged ===")
    P = plan("unmerged", {"T1": {"branch": "`feat/a`"}})
    rc, out = run_to_rest(P)
    chk("tick exits 5 — at rest, waiting on a person — not 0", rc, 5)
    chk("...and says NOT COMPLETE, naming the branch", ("NOT COMPLETE" in out, "feat/a" in out),
        (True, True))
    rc, _ = smokin("status", str(P))
    chk("status agrees with tick, as its own comment requires", rc, 5)

    P = plan("merged", {"T1": {"branch": "`feat/a`"},
                        "T2": {"kind": "integration", "blocked": "T1"}})
    rc, out = run_to_rest(P)
    chk("CONTROL · with a downstream integration task, the plan completes", rc, 0)
    rc, _ = smokin("status", str(P))
    chk("...and status says 0 too", rc, 0)

    P = plan("nobranch", {"T1": {}})
    rc, _ = run_to_rest(P)
    chk("CONTROL · a plan that declares no branch is untouched by any of this", rc, 0)

    P = plan("placeholder-branch", {"T1": {"branch": "`<prefix>/<ID>-<slug>`"}})
    rc, _ = run_to_rest(P)
    chk("CONTROL · an unfilled template Branch is not a branch", rc, 0)

    print("\n=== 3 · the debrief ===")
    FAKE = LAB / "fake-summariser.sh"
    FAKE.write_text("#!/usr/bin/env bash\ncat > \"$FAKE_SAW\"\n"
                    "printf '## Key points of success\\n\\n- it worked\\n\\n"
                    "## Important notes\\n\\n- one\\n'\n")
    FAKE.chmod(0o755)
    tr = LAB / "t.jsonl"
    tr.write_text("\n".join(json.dumps(x) for x in [
        {"type": "user", "message": {"role": "user", "content": "fix the chart"}},
        {"type": "assistant", "message": {"role": "assistant", "content": [
            {"type": "thinking", "thinking": "SECRET-REASONING"},
            {"type": "text", "text": "Reading the file."},
            {"type": "tool_use", "name": "Read", "input": {"file_path": "chart.js"}}]}},
        {"type": "user", "message": {"role": "user", "content": [
            {"type": "tool_result", "is_error": True, "content": "ENOENT chart.js"}]}},
    ]) + "\n")
    saw = LAB / "saw.txt"
    E = {"SMOKIN_DEBRIEF_CMD": str(FAKE), "FAKE_SAW": str(saw)}
    E.pop("SMOKIN_DEBRIEF_ACTIVE", None)

    def debrief(*argv, env=None, stdin=None):
        e = {k: v for k, v in os.environ.items() if k not in ("SMOKIN_TASK_ID", "SMOKIN_TASK_DIR",
                                                             "SMOKIN_DEBRIEF_ACTIVE")}
        e.update(E); e.update(env or {})
        return subprocess.run([sys.executable, str(DEBRIEF), *argv], input=stdin,
                              capture_output=True, text=True, timeout=60, env=e)

    out_dir = LAB / "deb"
    r = debrief("--transcript", str(tr), "--out", str(out_dir), "--agent-id", "a1",
                "--agent-type", "Explore")
    files = sorted(out_dir.glob("*.md"))
    chk("a debrief is written", len(files), 1)
    body = files[0].read_text() if files else ""
    chk("...marked SUSPECTED — a model's reading, not a verdict", "SUSPECTED" in body, True)
    chk("...with all four headings, in order",
        [h for h in ("Key points of success", "Unfinished business, marked defects or failures",
                     "Important notes", "Full chat workflow flaws") if f"## {h}" in body],
        ["Key points of success", "Unfinished business, marked defects or failures",
         "Important notes", "Full chat workflow flaws"])
    chk("...and a section the summariser skipped says so rather than going missing",
        "_(the summariser returned nothing for this section)_" in body, True)
    fed = saw.read_text() if saw.exists() else ""
    chk("the summariser sees the tool call and the error", ("→ Read" in fed, "ERROR" in fed),
        (True, True))
    chk("...and never the thinking", "SECRET-REASONING" in fed, False)

    FAIL = LAB / "failing.sh"
    FAIL.write_text("#!/usr/bin/env bash\necho 'quota exceeded' >&2\nexit 3\n")
    FAIL.chmod(0o755)
    shutil.rmtree(out_dir, ignore_errors=True)
    debrief("--transcript", str(tr), "--out", str(out_dir), env={"SMOKIN_DEBRIEF_CMD": str(FAIL)})
    body = next(iter(out_dir.glob("*.md"))).read_text() if out_dir.exists() else ""
    chk("a failing summariser still leaves a file, saying it failed and why",
        ("summariser failed" in body, "quota exceeded" in body), (True, True))

    print("\n=== 3b · the debrief refuses: recursion, the main session ===")
    shutil.rmtree(out_dir, ignore_errors=True)
    debrief("--transcript", str(tr), "--out", str(out_dir), env={"SMOKIN_DEBRIEF_ACTIVE": "1"})
    chk("inside a summariser, nothing is written — no debrief of a debrief",
        out_dir.exists() and any(out_dir.iterdir()), False)
    pay = json.dumps({"hook_event_name": "Stop", "transcript_path": str(tr)})
    debrief("--from-hook", "--out", str(out_dir), stdin=pay)
    chk("Stop in the user's own session (no SMOKIN_TASK_ID) is not debriefed",
        out_dir.exists() and any(out_dir.iterdir()), False)
    tdir = LAB / "taskdir"
    debrief("--from-hook", stdin=pay, env={"SMOKIN_TASK_ID": "T9", "SMOKIN_TASK_DIR": str(tdir)})
    chk("Stop inside a Smokin dispatch IS debriefed, into that task's debriefs/",
        len(list((tdir / "debriefs").glob("*.md"))) if (tdir / "debriefs").exists() else 0, 1)
    sub = json.dumps({"hook_event_name": "SubagentStop", "agent_id": "ag7",
                      "agent_type": "Explore", "agent_transcript_path": str(tr)})
    debrief("--from-hook", stdin=sub)
    chk("SubagentStop anywhere is debriefed, beside the transcript when there is no task",
        len(list((tr.parent / "debriefs").glob("*Explore-ag7.md"))), 1)

    print("\n=== 3c · the hook never blocks the session ===")
    SLOW = LAB / "slow.sh"
    SLOW.write_text("#!/usr/bin/env bash\ncat >/dev/null\nsleep 4\n"
                    "printf '## Key points of success\\n\\n- slow but done\\n'\n")
    SLOW.chmod(0o755)
    hdir = LAB / "hookdir"
    hpay = json.dumps({"hook_event_name": "SubagentStop", "agent_id": "slow1",
                       "agent_type": "worker", "agent_transcript_path": str(tr)})
    henv = {k: v for k, v in os.environ.items() if k not in ("SMOKIN_DEBRIEF_ACTIVE",)}
    henv.update({"PATH": f"{ROOT / 'bin'}:{os.environ['PATH']}", "SMOKIN_DEBRIEF_CMD": str(SLOW),
                 "SMOKIN_TASK_DIR": str(hdir)})
    t0 = time.time()
    h = subprocess.run(["bash", str(HOOK)], input=hpay, capture_output=True, text=True,
                       timeout=30, env=henv)
    took = time.time() - t0
    chk("the hook exits 0", h.returncode, 0)
    chk(f"...in under 2s while a 4s summariser runs (took {took:.2f}s)", took < 2, True)
    for _ in range(30):
        if (hdir / "debriefs").exists() and any((hdir / "debriefs").glob("*.md")):
            break
        time.sleep(0.5)
    got = list((hdir / "debriefs").glob("*.md")) if (hdir / "debriefs").exists() else []
    chk("...and the debrief still lands, afterwards", len(got), 1)
    h = subprocess.run(["bash", str(HOOK)], input=hpay, capture_output=True, text=True,
                       timeout=30, env=dict(henv, SMOKIN_DEBRIEF_ACTIVE="1"))
    chk("the hook itself refuses to fire inside a summariser", h.returncode, 0)

    # FOUND INSTALLING IT: `smokin` was not on PATH on the machine it was written
    # on, so the hook would have found no smokin-debrief and silently done
    # nothing. SMOKIN_DEBRIEF_BIN is the escape, and it must work with no PATH
    # help at all.
    bdir = LAB / "bindir"
    benv = {k: v for k, v in henv.items() if k != "SMOKIN_TASK_DIR"}
    benv.update({"PATH": "/usr/bin:/bin", "SMOKIN_DEBRIEF_BIN": str(DEBRIEF),
                 "SMOKIN_TASK_DIR": str(bdir), "SMOKIN_DEBRIEF_CMD": str(FAKE),
                 "FAKE_SAW": str(LAB / "saw2.txt")})
    subprocess.run(["bash", str(HOOK)], input=hpay, capture_output=True, text=True,
                   timeout=30, env=benv)
    for _ in range(20):
        if (bdir / "debriefs").exists() and any((bdir / "debriefs").glob("*.md")):
            break
        time.sleep(0.5)
    chk("SMOKIN_DEBRIEF_BIN finds the debrief with nothing on PATH",
        len(list((bdir / "debriefs").glob("*.md"))) if (bdir / "debriefs").exists() else 0, 1)

    sdir = LAB / "stopdir"
    senv = dict(benv, SMOKIN_TASK_DIR=str(sdir))
    senv.pop("SMOKIN_TASK_ID", None)
    t0 = time.time()
    subprocess.run(["bash", str(HOOK)], capture_output=True, text=True, timeout=30, env=senv,
                   input=json.dumps({"hook_event_name": "Stop", "transcript_path": str(tr)}))
    time.sleep(1.5)
    chk("a Stop in the user's own session is dropped in the shell — nothing spawned, nothing written",
        (sdir / "debriefs").exists(), False)

    print("\n=== 3d · doctor says when the debrief prerequisite is missing ===")
    home = LAB / "home"
    (home / ".claude").mkdir(parents=True)
    P = plan("doc", {"T1": {}})
    rc, out = smokin("doctor", str(P), env={"HOME": str(home)})
    chk("no hook wired anywhere: doctor warns, and still exits 0", 
        ("debrief hook is not wired" in out, rc), (True, 0))
    (home / ".claude" / "settings.json").write_text(json.dumps({"hooks": {"SubagentStop": [
        {"hooks": [{"type": "command",
                    "command": "~/.claude/hooks/debrief-on-subagent-stop.sh"}]}]}}))
    rc, out = smokin("doctor", str(P), env={"HOME": str(home)})
    chk("CONTROL · once it is wired, the warning is gone", "debrief hook is not wired" in out, False)

finally:
    shutil.rmtree(LAB, ignore_errors=True)
print(f"\n\033[31m{fails} failed\033[0m" if fails else "\n\033[32mall passed\033[0m")
sys.exit(1 if fails else 0)

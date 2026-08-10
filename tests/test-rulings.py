#!/usr/bin/env python3
"""Calibrate the delegation node's judgement layer.

DELEGATION-NODE.md §8 names six failure modes and claims a mechanism stops each
one. A claim with no mutation test behind it is a preference. Every check below
either breaks the mechanism and asserts the failure returns, or exercises the
mechanism and asserts it holds.

Grillin OPERATING-THE-PLAN.md §5: an instrument is proven against a known answer
BEFORE the measurements it authorises. This is that known answer.

    python3 tests/test-rulings.py
"""
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
spec = importlib.util.spec_from_file_location("R", ROOT / "bin" / "smokin_rulings.py")
R = importlib.util.module_from_spec(spec)
spec.loader.exec_module(R)

fails = 0
LAB = Path(tempfile.mkdtemp(prefix="smokin-rulings."))


def chk(label, got, want):
    global fails
    if got == want:
        print(f"  \033[32mPASS\033[0m  {label}")
    else:
        fails += 1
        print(f"  \033[31mFAIL\033[0m  {label} — want {want!r}, got {got!r}")


def has(label, hay, needle):
    chk(label, needle in (hay or ""), True)


ROSTER = """# Roster

| Persona | Responsible for | Model | Effort | Why |
|---|---|---|---|---|
| `adversary` | judging whether the result is true | `claude-opus-5` | `xhigh` | highest-yield role |
| `implementer` | bounded work | `claude-sonnet-5` | `high` | contract is written |
| `health` | rules being followed | `claude-sonnet-5` | `xhigh` | reads for what is absent |
"""

GOOD = """
[policy]
uncovered = "halt"

[[ruling]]
class    = "receipt-trust"
when     = "verdict.passed and receipt.claim == 'done'"
persona  = "adversary"
evidence = ["task.contract", "receipt", "verdict"]
outcomes = ["accept", "reject", "insufficient-evidence"]
default  = "halt"
runtime  = "judge"
budget_s = 30
"""

# A judge that answers from a file the test controls. Stands in for a model so
# the mechanism — not the model — is what is under test.
JUDGE = """#!/usr/bin/env bash
if [ -f "$SMOKIN_PLAN_ANSWER" ]; then cat "$SMOKIN_PLAN_ANSWER" > "$SMOKIN_RULING_OUT"; fi
exit "${SMOKIN_JUDGE_RC:-0}"
"""


def plan(name, rulings=GOOD, roster=ROSTER, answer=None, gated=True, claim="done"):
    """A one-task plan already at the gate, so the judgement layer is what runs."""
    p = LAB / name
    shutil.rmtree(p, ignore_errors=True)
    (p / "tasks" / "T1").mkdir(parents=True)
    (p / ".smokin").mkdir(parents=True, exist_ok=True)
    (p / "PLAN.md").write_text("# plan\n\n| ID | Task |\n|---|---|\n| T1 | a |\n")
    if roster is not None:
        (p / "_ROSTER.md").write_text(roster)
    if rulings is not None:
        (p / "_RULINGS.toml").write_text(rulings)
    (p / "judge-stub.sh").write_text(JUDGE)
    (p / ".smokin" / "runtimes.json").write_text(json.dumps(
        {"judge": {"headless": "bash judge-stub.sh"}, "demo": {"headless": "true"}}))
    (p / "tasks" / "T1" / "TASK.md").write_text(
        "# T1 — test\n\n**Status:** IN PROGRESS\n**Owner:** worker-T1\n"
        "**Blocked by:** — · **Blocks:** —\n"
        "**Dispatch:** inproc · **Runtime:** `demo`\n"
        "**Budget:** 60 · **Interrupt:** no · **Watch:** no\n\n"
        "## Done means\n```\ntrue\n```\n\n## Do NOT\n- Do NOT stray.\n")
    (p / "tasks" / "T1" / "FINDINGS.md").write_text("the worker wrote this\n")
    if gated:
        (p / "tasks" / "T1" / "RECEIPT.json").write_text(json.dumps(
            {"schema": "smokin.receipt/1", "task": "T1", "claim": claim,
             "terminal": "exit", "source": "worker", "artifacts": {}}))
        (p / "tasks" / "T1" / "VERDICT.json").write_text(json.dumps(
            {"pass": True, "exit": 0, "cmd": "true"}))
    if answer is not None:
        (p / "answer.json").write_text(json.dumps(answer))
    return p


def tick(p, answer_file="answer.json", rc_env=None):
    env = dict(os.environ, SMOKIN_PLAN_ANSWER=str(p / answer_file))
    if rc_env:
        env["SMOKIN_JUDGE_RC"] = rc_env
    r = subprocess.run([sys.executable, str(SMOKIN), "tick", str(p)],
                       capture_output=True, text=True, env=env, timeout=120)
    return r.returncode, r.stdout + r.stderr


def state(p, tid="T1"):
    st = json.loads((p / "STATUS.json").read_text())
    return next(t["state"] for t in st["tasks"] if t["id"] == tid)


def ledger(p):
    f = p / ".smokin" / "rulings.jsonl"
    return [json.loads(x) for x in f.read_text().splitlines() if x.strip()] if f.is_file() else []


print("Smokin — delegation node calibration\n")

# ── the loader: malformed is loud, never a quiet fall-back ──────────────────
print("=== property 1 · a class not declared cannot be made ===")
p = plan("noconfig", rulings=None)
rs = R.load(p)
chk("no _RULINGS.toml -> layer is off", (rs.active, rs.error), (False, None))
chk("...and off means uncovered accepts", rs.policy["uncovered"], "accept")

rs = R.load(plan("good"))
chk("a good config loads", (bool(rs.active), rs.error, len(rs.rulings)), (True, None, 1))
chk("...model comes from the ROSTER, not this file",
    (rs.rulings[0]["model"], rs.rulings[0]["effort"]), ("claude-opus-5", "xhigh"))

print("\n=== property 2 · the persona resolves against _ROSTER.md ===")
bad = GOOD.replace('persona  = "adversary"', 'persona  = "inventor"')
has("persona not in the roster is an error", R.load(plan("nopersona", bad)).error,
    "is not in _ROSTER.md")
has("no roster at all is an error", R.load(plan("noroster", GOOD, roster=None)).error,
    "_ROSTER.md not found")

print("\n=== property 3 · outcomes is a closed set ===")
has("outcomes without insufficient-evidence rejected",
    R.load(plan("noins", GOOD.replace(', "insufficient-evidence"', ''))).error,
    "must include 'insufficient-evidence'")
has("outcomes that advance nothing rejected",
    R.load(plan("noadv", GOOD.replace('"accept", ', ''))).error,
    "nothing that advances")

print("\n=== property 4 · default = halt, not configurable softer ===")
has("default accept is rejected", R.load(plan("softdef", GOOD.replace('default  = "halt"',
                                                                      'default  = "accept"'))).error,
    "It must be 'halt'")

print("\n=== the config surface, generally ===")
has("unparseable TOML is loud", R.load(plan("badtoml", "[[ruling]\nclass = ")).error, "unparseable")
has("no [[ruling]] entries is loud", R.load(plan("empty", "[policy]\nuncovered='halt'")).error,
    "no [[ruling]]")
has("duplicate class is loud",
    R.load(plan("dupe", GOOD + GOOD[GOOD.index("[[ruling]]"):])).error, "declared twice")
has("unknown evidence name is loud",
    R.load(plan("badev", GOOD.replace('"verdict"]', '"the_whole_repo"]'))).error,
    "unknown evidence")
has("empty evidence is loud",
    R.load(plan("noev", GOOD.replace('evidence = ["task.contract", "receipt", "verdict"]',
                                     'evidence = []'))).error, "declares no evidence")
has("unknown policy.uncovered is loud",
    R.load(plan("badpol", GOOD.replace('uncovered = "halt"', 'uncovered = "sure"'))).error,
    "must be 'halt' or 'accept'")

print("\n=== the `when` expression is whitelisted, not sandboxed by hope ===")
has("unknown field is an error at LOAD time",
    R.load(plan("badfield", GOOD.replace("verdict.passed", "verdict.ok"))).error,
    "reads unknown field")
has("a call is rejected structurally",
    R.load(plan("call", GOOD.replace('when     = "verdict.passed and receipt.claim == \'done\'"',
                                     'when     = "__import__(\'os\').system(\'x\')"'))).error,
    "which is not permitted")
has("a subscript is rejected structurally",
    R.load(plan("sub", GOOD.replace('when     = "verdict.passed and receipt.claim == \'done\'"',
                                    'when     = "verdict.passed[0]"'))).error,
    "which is not permitted")
fn, err = R.compile_when("verdict.passed and receipt.claim in ('done', 'partial')")
chk("a legal expression compiles", err, None)
chk("...and evaluates true", fn({"verdict.passed": True, "receipt.claim": "partial"}), True)
chk("...and false", fn({"verdict.passed": True, "receipt.claim": "blocked"}), False)

# ── end to end: the six failure modes of §8 ────────────────────────────────
print("\n=== §8 · a quiet default (judge unreachable) ===")
p = plan("silent")                      # no answer.json -> judge writes nothing
rc, out = tick(p)
chk("silent judge halts the tick", rc, 4)
has("...and says what happened", out, "wrote no RULING.json")
chk("...task is NOT verified", state(p), "judging")
chk("...HALT.json is on disk", (p / ".smokin" / "HALT.json").is_file(), True)
rc2, out2 = tick(p)
chk("a halted plan stays halted on the next tick", rc2, 4)
has("...and re-states why", out2, "HALTED")

p = plan("norune", GOOD.replace('runtime  = "judge"', 'runtime  = "nowhere"'))
rc, out = tick(p)
chk("a judge runtime with no headless mode halts", rc, 4)
has("...and names it", out, "has no headless mode")

print("\n=== §8 · an outcome outside the closed set ===")
p = plan("offmenu", answer={"outcome": "looks fine to me", "because": "vibes"})
rc, out = tick(p)
chk("an undeclared outcome halts", rc, 4)
has("...and quotes it", out, "'looks fine to me'")

p = plan("noreason", answer={"outcome": "accept", "because": "  "})
rc, out = tick(p)
chk("accept with no reason halts", rc, 4)
has("...because a ruling nobody can review is not a ruling", out, "with no reason")

print("\n=== §8 · the schedule rots (nothing covers a gated task) ===")
p = plan("uncovered", GOOD.replace("receipt.claim == 'done'", "receipt.claim == 'blocked'"))
rc, out = tick(p)
chk("gate passed, no class matched, uncovered=halt -> halt", rc, 4)
has("...and says the node does not decide what it was not told", out, "was not told to decide")
chk("...task is not verified", state(p), "uncovered")

p = plan("uncov-ok", GOOD.replace('uncovered = "halt"', 'uncovered = "accept"')
         .replace("receipt.claim == 'done'", "receipt.claim == 'blocked'"))
rc, out = tick(p)
chk("the same plan with uncovered=accept advances", state(p), "verified")

print("\n=== the happy path: a ruling is made, recorded, and advances the plan ===")
p = plan("accept", answer={"outcome": "accept", "because": "FINDINGS.md shows the contract met"})
rc, out = tick(p)
chk("accept verifies the task", state(p), "verified")
led = ledger(p)
chk("...one ruling recorded", len(led), 1)
chk("...with the roster's pairing", (led[0]["model"], led[0]["effort"]), ("claude-opus-5", "xhigh"))
chk("...and the persona", led[0]["persona"], "adversary")
has("...and the reason, mandatory", led[0]["because"], "contract met")
chk("...and the evidence it was handed", sorted(led[0]["evidence"]),
    ["tasks/T1/RECEIPT.json", "tasks/T1/TASK.md", "tasks/T1/VERDICT.json"])
chk("...evidence it was NOT handed is absent",
    any("FINDINGS" in e for e in led[0]["evidence"]), False)
rc2, _ = tick(p)
chk("a second tick does not re-judge unchanged evidence", len(ledger(p)), 1)

print("\n=== the frontier advances on RULINGS, not receipts ===")
p = plan("reject", answer={"outcome": "reject", "because": "the migration was never run"})
rc, out = tick(p)
chk("reject does not verify", state(p), "rejected")
chk("...even though the gate passed",
    json.loads((p / "tasks" / "T1" / "VERDICT.json").read_text())["pass"], True)
prog = (p / "PROGRESS.md").read_text()
has("...and PROGRESS.md says so in words", prog, "a judge said no")
has("...with the judge's reason", prog, "the migration was never run")

print("\n=== §8 · escalation is tier 3, not another agent ===")
p = plan("insuf", answer={"outcome": "insufficient-evidence",
                          "because": "the receipt does not say which files changed"})
rc, out = tick(p)
chk("insufficient-evidence halts", rc, 4)
has("...and says a human decides", out, "needs a human, not another agent")
chk("...the ruling is still recorded", len(ledger(p)), 1)
chk("...and the task is escalated", state(p), "escalated")

print("\n=== §8 · judge shopping leaves a trail ===")
p = plan("shop", answer={"outcome": "reject", "because": "no evidence the gate ran"})
tick(p)
chk("first ruling: reject", state(p), "rejected")
(p / "answer.json").write_text(json.dumps({"outcome": "accept", "because": "now it does"}))
rc, out = tick(p)
chk("...same evidence is not re-judged", len(ledger(p)), 1)
chk("...so a rerun cannot flip it", state(p), "rejected")
(p / "tasks" / "T1" / "RECEIPT.json").write_text(json.dumps(
    {"schema": "smokin.receipt/1", "task": "T1", "claim": "done", "terminal": "exit",
     "source": "worker", "artifacts": {}, "note": "evidence genuinely changed"}))
rc, out = tick(p)
led = ledger(p)
chk("changed evidence IS re-judged", len(led), 2)
chk("...the new ruling names the one it replaced", led[1].get("supersedes"), led[0]["seq"])
chk("...and records what that one said", led[1].get("supersedes_outcome"), "reject")
chk("...the superseded ruling is still in the file", led[0]["outcome"], "reject")
chk("...now verified, visibly on the second ruling", state(p), "verified")

print("\n=== §8 · the node never becomes the curator ===")
p = plan("readonly", answer={"outcome": "accept", "because": "fine"})
before = {f: (p / f).read_bytes() for f in ("PLAN.md", "_ROSTER.md", "_RULINGS.toml")}
tick(p)
for f, b in before.items():
    chk(f"{f} is byte-identical after a tick", (p / f).read_bytes(), b)

print("\n=== §8 · the node never becomes a worker ===")
p = plan("noworker", answer={"outcome": "reject", "because": "nothing was built"})
findings = (p / "tasks" / "T1" / "FINDINGS.md").read_bytes()
tick(p)
chk("worker output is untouched by the node", (p / "tasks" / "T1" / "FINDINGS.md").read_bytes(),
    findings)
wrote = {f.name for f in (p / "tasks" / "T1").iterdir()}
chk("the node wrote no new file into the task dir", wrote - {
    "TASK.md", "FINDINGS.md", "RECEIPT.json", "VERDICT.json"}, set())

print("\n=== reset retires rulings, it does not erase them ===")
p = plan("resetp", answer={"outcome": "reject", "because": "not done"})
tick(p)
subprocess.run([sys.executable, str(SMOKIN), "reset", str(p)], capture_output=True)
led = ledger(p)
chk("the ruling is still readable after a reset", led[0]["outcome"], "reject")
chk("...and a retirement was appended", led[-1].get("retired"), True)
chk("...so nothing stands", R.standing(p / ".smokin"), {})
chk("...and the halt is cleared", (p / ".smokin" / "HALT.json").is_file(), False)

print("\n=== `smokin rulings` can print what is in force ===")
p = plan("show")
r = subprocess.run([sys.executable, str(SMOKIN), "rulings", str(p)],
                   capture_output=True, text=True)
chk("exit 0 on a good config", r.returncode, 0)
has("...prints the class", r.stdout, "receipt-trust")
has("...prints the pairing it will pay for", r.stdout, "claude-opus-5")
has("...prints the uncovered policy", r.stdout, "uncovered = halt")
r = subprocess.run([sys.executable, str(SMOKIN), "rulings",
                    str(plan("showbad", "[[ruling]\nx"))], capture_output=True, text=True)
chk("exit 1 on a broken config", r.returncode, 1)
has("...and refuses to observe", r.stdout, "No ruling is made in this plan")

print(f"\n{'ALL PASS' if not fails else str(fails) + ' FAILED'}  ({LAB})")
if not fails:
    shutil.rmtree(LAB, ignore_errors=True)
sys.exit(1 if fails else 0)

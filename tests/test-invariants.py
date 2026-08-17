#!/usr/bin/env python3
"""Calibrate the plan-level invariants.

`_INVARIANTS.toml` claims that a plan cannot advance past a reading that moved.
A claim with no mutation test behind it is a preference. Every check below either
BREAKS the mechanism and asserts the failure returns, or exercises the mechanism
and asserts it holds — and every loud check is paired with a silent control, so a
test that passes because everything is loud is not mistaken for a working one.

The probes are `cat` over files the test owns. No network, no clock, no fleet:
the mechanism is what is under test, not the world.

Grillin OPERATING-THE-PLAN.md §5: an instrument is proven against a known answer
BEFORE the measurements it authorises. This is that known answer.

    python3 tests/test-invariants.py
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
spec = importlib.util.spec_from_file_location("I", ROOT / "bin" / "smokin_invariants.py")
I = importlib.util.module_from_spec(spec)
spec.loader.exec_module(I)

fails = 0
LAB = Path(tempfile.mkdtemp(prefix="smokin-invariants."))


def chk(label, got, want):
    global fails
    if got == want:
        print(f"  \033[32mPASS\033[0m  {label}")
    else:
        fails += 1
        print(f"  \033[31mFAIL\033[0m  {label} — want {want!r}, got {got!r}")


def has(label, hay, needle):
    chk(label, needle in (hay or ""), True)


def hasnt(label, hay, needle):
    chk(label, needle in (hay or ""), False)


# The invariant every test starts from: a reading that must not move. `neighbour`
# stands in for the neighbouring sites the six deploy briefs curl'd by hand.
GOOD = """
[[invariant]]
name    = "the neighbour site still answers"
run     = "cat neighbour.txt"
because = "certbot added a listen directive that made a new vhost the default for all loopback HTTPS, so the neighbouring sites were served the wrong certificate. No task's done-command looks at this."
budget_s = 20
"""


def plan(name, invariants=GOOD, neighbour="200 OK", gated=True, tasks=("T1",)):
    """A plan whose task is already at the gate, so the invariant layer is what
    runs. `neighbour.txt` is the world; the tests move it."""
    p = LAB / name
    shutil.rmtree(p, ignore_errors=True)
    (p / ".smokin").mkdir(parents=True)
    (p / "PLAN.md").write_text("# plan\n\n| ID | Task |\n|---|---|\n| T1 | a |\n")
    (p / "neighbour.txt").write_text(neighbour)
    if invariants is not None:
        (p / "_INVARIANTS.toml").write_text(invariants)
    (p / ".smokin" / "runtimes.json").write_text(json.dumps({"demo": {"headless": "true"}}))
    for tid in tasks:
        d = p / "tasks" / tid
        d.mkdir(parents=True)
        (d / "TASK.md").write_text(
            f"# {tid} — test\n\n**Status:** IN PROGRESS\n**Owner:** worker-{tid}\n"
            "**Blocked by:** — · **Blocks:** —\n"
            "**Dispatch:** inproc · **Runtime:** `demo`\n"
            "**Budget:** 60 · **Interrupt:** no · **Watch:** no\n\n"
            "## Done means\n```\ntrue\n```\n\n## Do NOT\n- Do NOT stray.\n")
        (d / "FINDINGS.md").write_text("the worker wrote this\n")
        if gated:
            (d / "RECEIPT.json").write_text(json.dumps(
                {"schema": "smokin.receipt/1", "task": tid, "claim": "done",
                 "terminal": "exit", "source": "worker", "artifacts": {}}))
            (d / "VERDICT.json").write_text(json.dumps({"pass": True, "exit": 0, "cmd": "true"}))
    return p


def smokin(p, cmd, *flags):
    # The plan goes straight after the command. argparse's `plan` is nargs="?",
    # so a flag between the two leaves the path unmatched and exits 2 — which is
    # how `smokin invariants --recapture <plan>` silently became a usage error.
    r = subprocess.run([sys.executable, str(SMOKIN), cmd, str(p), *flags],
                       capture_output=True, text=True, timeout=180)
    return r.returncode, r.stdout + r.stderr


def tick(p):
    return smokin(p, "tick")


def status(p):
    return json.loads((p / "STATUS.json").read_text())


def baseline(p):
    f = p / ".smokin" / "baseline.json"
    return json.loads(f.read_text()) if f.is_file() else None


def led(p):
    f = p / ".smokin" / "ledger.jsonl"
    return [json.loads(x) for x in f.read_text().splitlines() if x.strip()] if f.is_file() else []


print("Smokin — plan-level invariant calibration\n")

# ── the loader: malformed is LOUD, never a quiet fall-back ──────────────────
print("=== opt-in by file, exactly like _RULINGS.toml ===")
iset = I.load(plan("noconfig", invariants=None))
chk("no _INVARIANTS.toml -> layer is off, and off is not an error",
    (iset.active, iset.error, iset.invariants), (False, None, []))
iset = I.load(plan("good"))
chk("a good config loads", (bool(iset.active), iset.error, len(iset.invariants)),
    (True, None, 1))
chk("...and the default mode is the one the briefs wrote by hand",
    iset.invariants[0]["mode"], "unchanged")

print("\n=== every defect in a file that EXISTS is loud ===")
has("unparseable TOML is loud", I.load(plan("badtoml", "[[invariant]\nname = ")).error,
    "unparseable")
has("no [[invariant]] entries is loud",
    I.load(plan("empty", "[policy]\nbudget_s = 5")).error, "no [[invariant]]")
has("duplicate name is loud", I.load(plan("dupe", GOOD + GOOD)).error, "declared twice")
has("no run is loud",
    I.load(plan("norun", GOOD.replace('run     = "cat neighbour.txt"', ''))).error,
    "has no run")
has("no because is loud — the reader of the halt did not write the command",
    I.load(plan("nobecause", "\n".join(l for l in GOOD.splitlines()
                                       if not l.startswith("because")))).error,
    "has no because")
has("both equals and matches is loud",
    I.load(plan("both", GOOD + 'equals = "x"\nmatches = "y"\n')).error,
    "one reading, one test")
has("budget_s that is not a number is loud",
    I.load(plan("badbudget", GOOD.replace("budget_s = 20", 'budget_s = "soon"'))).error,
    "budget_s is not a number")
has("a non-positive budget is loud",
    I.load(plan("zerobudget", GOOD.replace("budget_s = 20", "budget_s = 0"))).error,
    "must be positive")
has("a bad name is loud — it is a key in baseline.json",
    I.load(plan("badname", GOOD.replace('name    = "the neighbour site still answers"',
                                        'name    = "' + "x" * 90 + '"'))).error,
    "not a usable name")
has("an invalid regex is loud at LOAD time, not at the first break",
    I.load(plan("badrx", GOOD + 'matches = "(unclosed"\n')).error, "not a valid regex")
has("unbalanced quoting in run is loud",
    I.load(plan("badquote", GOOD.replace('"cat neighbour.txt"',
                                         "\"cat 'neighbour.txt\""))).error,
    "not a parseable shell command")
over = "".join(GOOD.replace('name    = "the neighbour site still answers"',
                            f'name    = "n{i}"') for i in range(I.MAX_INVARIANTS + 1))
has("more than the ceiling is loud", I.load(plan("toomany", over)).error, "ceiling is 32")

print("\n=== an unknown key is an error at LOAD time, not a silent drop ===")
has("a typo'd key is loud", I.load(plan("typo", GOOD.replace("because =", "becuase ="))).error,
    "unknown key(s): becuase")
has("...and so is one in [policy]",
    I.load(plan("poltypo", "[policy]\nbudgets = 5\n" + GOOD)).error,
    "[policy] has unknown key(s): budgets")
# The silent control: the same file with the key spelled correctly is not loud.
chk("the same file spelled correctly loads silently", I.load(plan("nottypo")).error, None)

print("\n=== an invariant may not call an agent; curl is deliberately allowed ===")
has("an agent binary in run is loud",
    I.load(plan("agent", GOOD.replace('"cat neighbour.txt"',
                                      '"claude -p \'is it up\'"'))).error,
    "run invokes claude")
has("...and a path to one is caught too",
    I.load(plan("agentpath", GOOD.replace('"cat neighbour.txt"',
                                          '"/usr/local/bin/codex check"'))).error,
    "run invokes codex")
chk("curl is NOT refused — the network IS the reading here",
    I.load(plan("curlok", GOOD.replace('"cat neighbour.txt"',
                                       '"curl -s -o /dev/null -w %{http_code} http://x"'))).error,
    None)

# ── the baseline ───────────────────────────────────────────────────────────
print("\n=== the baseline is captured before the first dispatch of a run ===")
p = plan("capture")
rc, out = tick(p)
b = baseline(p)
chk("the first tick takes a baseline", bool(b), True)
chk("...for this run", b["run"], json.loads((p / ".smokin" / "run.json").read_text())["run"])
chk("...with the reading in it", b["readings"]["the neighbour site still answers"]["out"],
    "200 OK")
chk("...and it did not halt", rc, 0)
has("...and the capture is in the ledger",
    json.dumps([e for e in led(p) if e.get("event") == "baseline"]), "baseline")

print("\n=== a world that did not move is SILENT — the negative control ===")
rc2, out2 = tick(p)
chk("a second tick over an unchanged world does not halt", rc2, 0)
hasnt("...and says nothing about a break", out2, "INVARIANT BROKEN")
chk("...and does not re-take the baseline", baseline(p)["at"], b["at"])

print("\n=== a reading that moved is a HALT, with all three facts ===")
p = plan("moved")
tick(p)
(p / "neighbour.txt").write_text("502 Bad Gateway")     # certbot, in miniature
rc, out = tick(p)
chk("a moved reading halts", rc, 4)
has("...naming the invariant", out, "the neighbour site still answers")
has("...quoting the command", out, "cat neighbour.txt")
has("...the EXPECTED reading", out, "'200 OK'")
has("...and the ACTUAL reading", out, "'502 Bad Gateway'")
has("...and the reason it was declared", out, "certbot added a listen directive")
chk("...HALT.json is on disk", (p / ".smokin" / "HALT.json").is_file(), True)
chk("...at tier 1 — a curator's rule, applied mechanically",
    json.loads((p / ".smokin" / "HALT.json").read_text())["tier"], "1")
rc3, out3 = tick(p)
chk("a halted plan stays halted on the next tick", rc3, 4)
has("...and re-states why", out3, "HALTED")
has("...and the break is in the ledger", json.dumps(led(p)), "invariant-broken")

print("\n=== it is a halt, NOT a warning: nothing is dispatched over a break ===")
p = plan("nodispatch", gated=False)
rc, out = smokin(p, "invariants", "--recapture")        # baseline with nothing dispatched
chk("--recapture takes a baseline without dispatching", rc, 0)
chk("...and dispatched nothing", (p / ".smokin" / "dispatch").is_dir(), False)
(p / "neighbour.txt").write_text("moved")
rc, out = tick(p)
chk("the tick halts instead of starting the ready task", rc, 4)
chk("...and no dispatch record was written",
    sorted(x.name for x in (p / ".smokin" / "dispatch").glob("*")) if
    (p / ".smokin" / "dispatch").is_dir() else [], [])
hasnt("...and it did not print a dispatch", out, "dispatch T1")

print("\n=== the instrument is proven before the measurements it authorises ===")
p = plan("unproven", GOOD.replace('"cat neighbour.txt"', '"cat no-such-file.txt"'))
rc, out = tick(p)
chk("a probe that cannot exit 0 refuses to baseline", rc, 4)
has("...and says it is an unproven instrument", out, "unproven instrument")
chk("...so no baseline was written", baseline(p), None)

p = plan("alreadyfalse", GOOD + 'equals = "200 OK"\n', neighbour="500")
rc, out = tick(p)
chk("a pinned expectation already false at baseline refuses", rc, 4)
has("...and says it was never true", out, "was never true")
# The control test the 404 incident needed: the same pin, true before the run.
p = plan("pintrue", GOOD + 'equals = "200 OK"\n', neighbour="200 OK")
rc, out = tick(p)
chk("...while the same pin that IS true baselines silently", rc, 0)
(p / "neighbour.txt").write_text("500")
rc, out = tick(p)
chk("...and then breaks when the world moves", rc, 4)
has("...quoting what it was pinned to", out, "exit 0 · '200 OK'")

print("\n=== a probe that dumps is refused; a digest of it is not ===")
big = GOOD.replace('"cat neighbour.txt"', '"head -c 9000 /dev/zero | tr \'\\\\0\' a"')
p = plan("dump", big)
rc, out = tick(p)
chk("an oversize reading refuses to baseline", rc, 4)
has("...and says what to do instead", out, "sha256sum")
p = plan("digest", GOOD.replace('"cat neighbour.txt"', '"cat neighbour.txt | sha256sum"'))
rc, out = tick(p)
chk("...the same thing through sha256sum is fine", rc, 0)

print("\n=== a probe that does not answer in its budget is a break, not a pass ===")
# The DECLARATION must not change between the two ticks or the drift check fires
# first and this measures the wrong thing. So the script gets slower, not the file.
SLOW = GOOD.replace("budget_s = 20", "budget_s = 2").replace('"cat neighbour.txt"',
                                                             '"bash probe.sh"')
p = plan("slow", SLOW)
(p / "probe.sh").write_text("cat neighbour.txt\n")
chk("a probe that answers in time baselines", tick(p)[0], 0)
(p / "probe.sh").write_text("sleep 10\ncat neighbour.txt\n")
rc, out = tick(p)
chk("a probe that outlives its budget halts", rc, 4)
has("...and an unanswered question is not an answer", out, "unanswered question")

print("\n=== editing the file that governs does not silently re-baseline ===")
p = plan("edited")
tick(p)
(p / "_INVARIANTS.toml").write_text(GOOD.replace('"cat neighbour.txt"',
                                                 '"cat neighbour.txt | cat"'))
rc, out = tick(p)
chk("an edited invariant halts rather than re-baselining", rc, 4)
has("...and says it was edited", out, "has been edited since the baseline")
has("...and names the deliberate ceremony", out, "--recapture")

p = plan("added")
tick(p)
(p / "_INVARIANTS.toml").write_text(
    GOOD + GOOD.replace('name    = "the neighbour site still answers"', 'name    = "second"'))
rc, out = tick(p)
chk("an invariant added after the baseline halts", rc, 4)
has("...and says it is not in the baseline", out, "added after it")

p = plan("removed")
tick(p)
(p / "_INVARIANTS.toml").write_text(
    GOOD.replace('name    = "the neighbour site still answers"', 'name    = "other"'))
rc, out = tick(p)
chk("an invariant removed mid-run halts", rc, 4)
has("...and says so", out, "removed mid-run")

print("\n=== --recapture is the way through, and it is on the record ===")
p = plan("recap")
tick(p)
(p / "neighbour.txt").write_text("301 Moved")
chk("the moved world halts", tick(p)[0], 4)
rc, out = smokin(p, "invariants", "--recapture")
chk("--recapture takes a new baseline", rc, 0)
chk("...against the world as it is now",
    baseline(p)["readings"]["the neighbour site still answers"]["out"], "301 Moved")
chk("...it is recorded as deliberate",
    any(e.get("event") == "baseline" and e.get("recaptured") for e in led(p)), True)
smokin(p, "resume")
chk("...and after clearing the halt the plan runs again", tick(p)[0], 0)

print("\n=== n=1: `smokin verify` runs them too, with no fleet at all ===")
p = plan("solo", gated=False)
rc, out = smokin(p, "verify")
chk("verify takes the baseline", bool(baseline(p)), True)
chk("...and passes", rc, 0)
has("...and says the reading is the reference", out, "reference reading")
chk("...having dispatched nothing", (p / ".smokin" / "dispatch").is_dir(), False)
(p / "neighbour.txt").write_text("410 Gone")
rc, out = smokin(p, "verify")
chk("a later verify catches what moved", rc, 4)
has("...with the actual reading", out, "'410 Gone'")
# The invariants run BEFORE the verdicts, so a broken machine stops the gate
# being re-run at all — a done-command is itself something that executes.
hasnt("...and re-ran no done-command over a broken machine", out, "verdict  T1")

print("\n=== the surfaces say it out loud ===")
p = plan("surface")
tick(p)
(p / "neighbour.txt").write_text("nope")
tick(p)
st = status(p)
chk("STATUS.json carries the invariant block", st["invariants"]["active"], True)
chk("...naming what broke", [b["name"] for b in st["invariants"]["broken"]],
    ["the neighbour site still answers"])
chk("...and when the baseline was taken", bool(st["invariants"]["baseline_at"]), True)
prog = (p / "PROGRESS.md").read_text()
has("PROGRESS.md says it in words", prog, "stopped being true")
has("...with the expected reading", prog, "200 OK")
has("...and the actual one", prog, "nope")
has("...and the reason", prog, "certbot")
has("...and the halt block survives being multi-line", prog, "> INVARIANT BROKEN")
# `present` re-renders from files with no tick behind it and therefore no rows.
# The banner used to survive that and the three facts under it did not.
smokin(p, "present")
prog2 = (p / "PROGRESS.md").read_text()
has("a bare re-render keeps the break", prog2, "stopped being true")
has("...including the actual reading", prog2, "nope")
chk("...and STATUS.json still names it",
    [b["name"] for b in status(p)["invariants"]["broken"]],
    ["the neighbour site still answers"])

print("\n=== `smokin invariants` can print what is in force ===")
p = plan("show")
rc, out = smokin(p, "invariants")
chk("exit 0 on a good config", rc, 0)
has("...prints the name", out, "the neighbour site still answers")
has("...prints the command it will run", out, "cat neighbour.txt")
has("...prints what it expects", out, "must not move from the baseline")
has("...and says the baseline is not taken yet", out, "NOT TAKEN")
tick(p)
rc, out = smokin(p, "invariants")
has("...then shows the reading it took", out, "200 OK")
rc, out = smokin(p, "invariants")
chk("a broken config exits 1", smokin(plan("showbad", "[[invariant]\nx"), "invariants")[0], 1)
has("...and refuses to observe",
    smokin(plan("showbad2", "[[invariant]\nx"), "invariants")[1],
    "Nothing is dispatched in this plan")

print("\n=== a broken config stops the tick, it does not disable the layer ===")
p = plan("brokencfg", "[[invariant]]\nname = \"x\"\nrun = \"true\"\n")   # no because
rc, out = tick(p)
chk("a config that does not load halts the tick", rc, 4)
has("...and says why falling back would be wrong", out, "still looked guarded")
chk("...and nothing was dispatched", (p / ".smokin" / "dispatch").is_dir(), False)

print("\n=== reset drops the baseline; the capture stays in the ledger ===")
p = plan("resetp")
tick(p)
chk("there is a baseline", bool(baseline(p)), True)
smokin(p, "reset")
chk("reset removes it — a new run needs a new before", baseline(p), None)
chk("...but the capture is still readable in the ledger",
    any(e.get("event") == "baseline" for e in led(p)), True)

print("\n=== the shipped template is a real config, not prose ===")
# `doctor` once crashed on the shipped runtimes.json's own `_comment` key,
# because every test shipped its own file and the template was the one thing
# nothing loaded. Found on a server. Not again.
tmpl = (ROOT / "templates" / "_INVARIANTS.toml.template").read_text()
iset = I.load(plan("template", tmpl))
chk("templates/_INVARIANTS.toml.template loads clean", iset.error, None)
chk("...with its one live invariant", len(iset.invariants), 1)
chk("...and the commented ones stay commented", iset.invariants[0]["mode"], "unchanged")

print("\n=== the whole feature is inert when the file is absent ===")
p = plan("inert", invariants=None)
rc, out = tick(p)
chk("a plan with no _INVARIANTS.toml completes exactly as before", rc, 0)
chk("...no baseline was written", (p / ".smokin" / "baseline.json").is_file(), False)
hasnt("...and nothing was printed about invariants", out, "invariant")
chk("...and STATUS.json says the layer is off", status(p)["invariants"]["active"], False)

print(f"\n{'ALL PASS' if not fails else str(fails) + ' FAILED'}  ({LAB})")
if not fails:
    shutil.rmtree(LAB, ignore_errors=True)
sys.exit(1 if fails else 0)

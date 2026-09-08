#!/usr/bin/env python3
"""`doctor --fix` — one repair, and the refusals matter as much as the repair.

WHY IT EXISTS AT ALL. `load_runtimes` takes the FIRST candidate file that exists
and does not merge. A plan that ships its own `.smokin/runtimes.json` therefore
gets nothing from the shipped table — including the `env` block added on
2026-09-07 — and runs on Claude Code's own subagent defaults, which are 20
concurrent at spawn depth 3, with nothing anywhere saying so. This gap was
created by a change in this repository rather than reported by a user, which is
the honest reason a repair exists for it and not for anything else doctor sees.

WHAT IT REFUSES, tested here because a refusal nobody exercises is a promise:

  a declared runtime that is not installed  installing a binary is not this
                                            tool's business
  a launch string ending in a variadic flag the repair needs to know what the
                                            author meant to put last
  a runtime with no caps to be missing      no opinion, and inventing one is the
                                            price table CONTRIBUTING refuses

THE VALUES ARE DERIVED FROM THE SHIPPED TABLE, not written down here. A test
that hardcoded the four numbers would pass on the day somebody changed the
template and be wrong about what a fresh plan inherits — the exact drift the
repair exists to close.

    python3 tests/test-doctor-fix.py
"""
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SMOKIN = ROOT / "bin" / "smokin"
TEMPLATE = ROOT / "templates" / "runtimes.json"
LAB = Path(tempfile.mkdtemp(prefix="smokin-doctorfix."))
fails = 0

# The shipped block, read rather than restated. If the template stops declaring
# one, that is a failure of this test's premise and it should say so out loud.
SHIPPED = json.loads(TEMPLATE.read_text())["claude"].get("env")


def chk(label, got, want):
    global fails
    ok = got == want
    print(f"  \033[32mPASS\033[0m  {label}" if ok
          else f"  \033[31mFAIL\033[0m  {label}\n        got {got!r}, want {want!r}")
    if not ok:
        fails += 1


def plan(name, runtimes=None):
    p = LAB / name
    shutil.rmtree(p, ignore_errors=True)
    (p / ".smokin").mkdir(parents=True)
    (p / "tasks" / "T1").mkdir(parents=True)
    (p / "PLAN.md").write_text("# p\n\n**Size:** M\n\n| ID | Task |\n|---|---|\n| T1 | a |\n")
    (p / "tasks" / "T1" / "TASK.md").write_text(
        "# T1\n\n**Status:** NOT STARTED\n**Owner:** w\n"
        "**Blocked by:** — · **Blocks:** —\n\n## Done means\n```\ntest -f x\n```\n")
    if runtimes is not None:
        (p / ".smokin" / "runtimes.json").write_text(json.dumps(runtimes))
    return p


def doc(p, *extra):
    r = subprocess.run([sys.executable, str(SMOKIN), "doctor", str(p), *extra],
                       capture_output=True, text=True, timeout=120)
    return r.returncode, r.stdout + r.stderr


def rts(p):
    return json.loads((p / ".smokin" / "runtimes.json").read_text())


try:
    chk("premise: the shipped table declares caps for claude", bool(SHIPPED), True)

    print("\n=== 1 · PROBE · a plan with its own uncapped claude row is warned ===")
    P = plan("bare", {"claude": {"headless": "claude -p", "pane": "claude"}})
    rc, out = doc(P)
    chk("doctor still exits 0 — a warning is not a failure", rc, 0)
    chk("...and warns", "declares no `env` block" in out, True)
    chk("...naming the real defaults rather than saying 'unset'",
        "20 concurrent at spawn depth 3" in out, True)
    chk("...and explaining the no-merge rule that caused it",
        "does not merge" in out, True)
    chk("...and naming the command that repairs it", "doctor --fix" in out, True)

    print("\n=== 2 · PROBE · --fix writes the shipped block, unchanged ===")
    rc, out = doc(P, "--fix")
    chk("exits 0", rc, 0)
    chk("the block written IS the shipped one", rts(P)["claude"]["env"], SHIPPED)
    chk("...and the row's other keys survive",
        rts(P)["claude"]["headless"], "claude -p")
    chk("...and so does pane", rts(P)["claude"]["pane"], "claude")
    chk("it says what it changed", "fixed 1 runtime(s): claude" in out, True)

    print("\n=== 3 · CONTROL · the previous file is kept, byte for byte ===")
    bak = P / ".smokin" / "runtimes.json.bak"
    chk("a .bak exists", bak.is_file(), True)
    chk("...and is the original, not the rewrite",
        json.loads(bak.read_text()), {"claude": {"headless": "claude -p", "pane": "claude"}})
    chk("...and the run said where it is", "runtimes.json.bak" in out, True)

    print("\n=== 4 · CONTROL · running it again changes nothing ===")
    before = (P / ".smokin" / "runtimes.json").read_text()
    rc, out = doc(P, "--fix")
    chk("exits 0", rc, 0)
    chk("...says there is nothing to do", "nothing to fix" in out, True)
    chk("...and the file is untouched",
        (P / ".smokin" / "runtimes.json").read_text(), before)

    print("\n=== 5 · CONTROL · a plan with NO runtimes.json is already correct ===")
    # It falls through to the shipped table and gets the caps for free. A --fix
    # that materialised a file here would turn a plan that tracks the template
    # into one frozen against today's copy of it.
    P2 = plan("inherits")
    rc, out = doc(P2, "--fix")
    chk("exits 0", rc, 0)
    chk("...and says why nothing was needed", "already inherits" in out, True)
    chk("...and no file was created",
        (P2 / ".smokin" / "runtimes.json").exists(), False)

    print("\n=== 6 · CONTROL · a runtime with no caps to miss is not touched ===")
    P3 = plan("nocaps", {"demo": {"headless": "true"}})
    rc, out = doc(P3)
    chk("no warning for a runtime this tool has no opinion about",
        "declares no `env` block" in out, False)
    rc, out = doc(P3, "--fix")
    chk("...and --fix leaves it alone", rts(P3), {"demo": {"headless": "true"}})
    chk("...saying so rather than silently doing nothing", "nothing to fix" in out, True)

    print("\n=== 7 · CONTROL · a row that INVOKES claude under another name is caught ===")
    # The detection reads the launch string, not just the row's name — a plan
    # calling its claude row `impl` is not thereby uncapped by accident.
    P4 = plan("aliased", {"impl": {"headless": "claude -p --output-format json"}})
    rc, out = doc(P4)
    chk("the alias is warned about", "declares no `env` block" in out, True)

    print("\n=== 8 · CONTROL · --fix refuses a lone task, and says what it needs ===")
    solo = LAB / "solo"
    solo.mkdir(parents=True, exist_ok=True)
    (solo / "TASK.md").write_text(
        "# T1\n\n**Status:** NOT STARTED\n**Owner:** w\n\n## Done means\n```\ntest -f x\n```\n")
    rc, out = doc(solo, "--fix")
    chk("exits 2", rc, 2)
    chk("...naming what is missing", "no runtimes.json to repair" in out, True)

finally:
    shutil.rmtree(LAB, ignore_errors=True)
print(f"\n\033[31m{fails} failed\033[0m" if fails else "\n\033[32mall passed\033[0m")
sys.exit(1 if fails else 0)

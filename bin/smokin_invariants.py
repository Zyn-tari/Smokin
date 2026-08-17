#!/usr/bin/env python3
"""
Plan-level invariants: `_INVARIANTS.toml`, and the baseline it is measured against.

WHY THIS EXISTS. A Smokin task declares what it must ACHIEVE — its `## Done means`
command, re-run by the tick, is the whole of its evidence. Nothing declared what
must REMAIN TRUE while the plan ran. A task can pass its own gate perfectly and
still have broken something it never looks at, and no per-task done-command will
ever notice, because a done-command that looked outside `tasks/<ID>/` would be
testing someone else's work (DESIGN.md §7 non-negotiable 4 forbids exactly that).

TWO INCIDENTS, and each one produced a rule below.

  1. A landing page was deployed to a production VPS across six hand-written
     briefs. Every one of the six carried, by hand, the same paragraph: record
     the live sites BEFORE you change anything, run the identical loop AFTER,
     compare. That is receipt-versus-verdict applied to BLAST RADIUS instead of
     completion, it was copied by hand six times, and Smokin had no concept of
     it. `unchanged` is that paragraph, declared once.

  2. During that deploy `certbot` silently added a `listen` directive that made
     a new vhost the default for all loopback HTTPS, so the neighbouring sites
     were served the wrong TLS certificate. A THIRD-PARTY TOOL edited config and
     created a fault outside every task's contract. The task that caused it
     succeeded. Its gate passed. Nothing was wrong with the plan's own evidence
     and the machine was broken anyway.

WHY THIS FILE NAME AND THIS FORMAT.

  `_INVARIANTS.toml` — the leading underscore and the caps are the plan-level
  register this repo family already uses for files that sit beside `PLAN.md` and
  govern the WHOLE plan rather than one task: `_RULINGS.toml`, `_ROSTER.md`,
  `_RULES.md`, `_WORKTREES.md`. A reader who knows one knows where to look for
  this one. TOML because `tomllib` is stdlib — zero dependencies — and because
  `[[invariant]]` is the same array-of-tables shape `[[ruling]]` already uses.
  One more file format would be one more loader to get wrong.

OPT-IN BY FILE, exactly like `_RULINGS.toml`. No `_INVARIANTS.toml` means the
plan has no blast-radius check and the tick behaves exactly as it did before.
Once the file exists, it binds — and a malformed one is LOUD and refuses to run.
Falling back to "no invariants" would let a typo turn the check off while the
plan still looked guarded, which is the fail-open shape this whole family of
tools exists to refuse.

WHAT THIS DOES NOT SOLVE, stated here rather than in a footnote:

  · **The baseline is only as good as when it was taken.** It is captured at the
    first tick or the first `verify` OF A RUN. If you start the run after the
    damage, the baseline records the damage as normal and every later reading
    agrees with it. Nothing here can tell. Take the baseline first, on purpose.
  · **A probe is trusted to be read-only.** Nothing enforces it. An invariant
    that mutates what it measures is a defect no check here can see.
  · **An unchanged reading is not a correct reading.** During the same deploy a
    real 404 — a missing vendored file — was asserted as the CAUSE of a chart
    bug and was not; a control test disproved it. This proves a reading did not
    move. It never proves the reading means what you think it means.

Zero dependencies (python3 stdlib >= 3.11 for tomllib). Fail-closed.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shlex
import subprocess
import time
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:                                   # pragma: no cover
    tomllib = None

CONFIG_NAME = "_INVARIANTS.toml"
BASELINE_NAME = "baseline.json"

# Every invariant runs at every tick boundary, so the ceiling is a budget, not a
# style preference: 32 probes at the default 60s is already a 32-minute worst
# case between two dispatches. Same number as MAX_RULINGS, for the same reason.
MAX_INVARIANTS = 32
DEFAULT_BUDGET = 60

# A reading is a READING. `nginx -T` is 40KB and its diff is unreadable in a halt
# message, which means nobody reads it, which means the halt taught nothing. Pipe
# a big thing through `sha256sum` and the invariant still fires — on one line.
MAX_READING_BYTES = 4096

# Keys are closed sets. An unknown key is an error at LOAD time because the
# alternative is silence: `becuase = "..."` would drop the reason on the floor
# and the first person to read the halt would have no idea why the command was
# there. Same lesson as `_RULINGS.toml`'s unknown `when` field.
INVARIANT_KEYS = {"name", "run", "equals", "matches", "because", "budget_s"}
POLICY_KEYS = {"budget_s"}

# DESIGN.md §7 non-negotiable 3 bars these from a done-command: a gate that
# shells out to an agent tests whether the tool is installed, not whether the
# work is finished. The same defect applies here and worse — an invariant is
# re-run on every tick, so a model call here is a model call forever.
#
# `curl` is on that list and is DELIBERATELY NOT on this one. In a done-command
# curl means the gate is testing the network instead of the work. In an
# invariant the network IS the thing being measured — "are the neighbouring
# sites still up" is not answerable any other way, and it is the exact reading
# the six briefs took by hand.
AGENT_BINARIES = {"claude", "codex", "codewhale", "opencode", "aider", "herdr",
                  "gemini", "smokin", "smokin-run", "smokin-emit"}

RE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._/:'-]{0,63}$")


# ── the config ──────────────────────────────────────────────────────────────

class InvariantSet:
    """The blast-radius checks in force for one plan."""

    def __init__(self, source, invariants, policy, error=None):
        self.source = source
        self.invariants = invariants
        self.policy = policy
        self.error = error

    @property
    def active(self) -> bool:
        return self.source is not None

    def __repr__(self):
        return (f"<InvariantSet {self.source or 'inactive'} n={len(self.invariants)}"
                f"{' ERROR' if self.error else ''}>")


def _decl_digest(inv: dict) -> str:
    """A digest over the DECLARATION, not the reading. Changing any of these four
    fields makes the baseline's stored reading an answer to a different question."""
    h = hashlib.sha256()
    for part in (inv["name"], inv["run"], inv["mode"], inv["expect"] or ""):
        h.update(part.encode())
        h.update(b"\0")
    return "sha256:" + h.hexdigest()[:16]


def load(root: Path) -> InvariantSet:
    cfg = root / CONFIG_NAME
    if not cfg.is_file():
        return InvariantSet(None, [], {})                    # opt-in by file

    if tomllib is None:
        return InvariantSet(str(cfg), [], {},
                            error="python is too old for tomllib (need 3.11+)")
    try:
        raw = tomllib.loads(cfg.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as e:
        return InvariantSet(str(cfg), [], {}, error=f"unparseable: {e}")

    problems = []
    pol = raw.get("policy") or {}
    if not isinstance(pol, dict):
        return InvariantSet(str(cfg), [], {}, error="[policy] is not a table")
    unknown_pol = sorted(set(pol) - POLICY_KEYS)
    if unknown_pol:
        problems.append(f"[policy] has unknown key(s): {', '.join(unknown_pol)}. "
                        f"Known: {', '.join(sorted(POLICY_KEYS))}")
    try:
        default_budget = int(pol.get("budget_s", DEFAULT_BUDGET))
    except (TypeError, ValueError):
        problems.append("policy.budget_s is not a number")
        default_budget = DEFAULT_BUDGET

    declared = raw.get("invariant")
    if not isinstance(declared, list) or not declared:
        return InvariantSet(str(cfg), [], {}, error="no [[invariant]] entries")
    if len(declared) > MAX_INVARIANTS:
        return InvariantSet(str(cfg), [], {},
                            error=f"{len(declared)} invariants declared, ceiling is "
                                  f"{MAX_INVARIANTS} — each one runs at every tick boundary")

    invariants, seen = [], set()
    for i, d in enumerate(declared):
        tag = f"invariant[{i}]"
        if not isinstance(d, dict):
            problems.append(f"{tag} is not a table")
            continue
        name = str(d.get("name") or "").strip()
        if not name:
            problems.append(f"{tag} has no name")
            continue
        tag = f"invariant {name!r}"
        if not RE_NAME.match(name):
            problems.append(f"{tag} is not a usable name — it is a key in baseline.json and a "
                            f"heading in a halt message; use letters, digits, spaces and "
                            f"._/:'- up to 64 characters")
            continue
        if name in seen:
            problems.append(f"{tag} is declared twice — an invariant is one reading or it is none")
            continue
        seen.add(name)

        unknown = sorted(set(d) - INVARIANT_KEYS)
        if unknown:
            problems.append(f"{tag} has unknown key(s): {', '.join(unknown)}. "
                            f"Known: {', '.join(sorted(INVARIANT_KEYS))}")
            continue

        cmd = str(d.get("run") or "").strip()
        if not cmd:
            problems.append(f"{tag} has no run — an invariant with no command measures nothing")
            continue
        try:
            tokens = shlex.split(cmd)
        except ValueError as e:
            problems.append(f"{tag}: run is not a parseable shell command ({e})")
            continue
        banned = sorted({os.path.basename(t) for t in tokens} & AGENT_BINARIES)
        if banned:
            problems.append(f"{tag}: run invokes {', '.join(banned)}. An invariant re-runs at "
                            f"every tick boundary; one that calls an agent measures whether the "
                            f"tool is installed, forever.")
            continue

        because = str(d.get("because") or "").strip()
        if not because:
            problems.append(f"{tag} has no because. A ruling without a reason is unreviewable and "
                            f"so is this: the person who reads the halt is not the person who "
                            f"wrote the command.")
            continue

        has_eq, has_rx = "equals" in d, "matches" in d
        if has_eq and has_rx:
            problems.append(f"{tag} declares both equals and matches — one reading, one test")
            continue
        rx = None
        if has_eq:
            mode, expect = "equals", _norm(str(d.get("equals")))
        elif has_rx:
            mode, expect = "matches", str(d.get("matches"))
            try:
                rx = re.compile(expect, re.M)
            except re.error as e:
                problems.append(f"{tag}: matches is not a valid regex ({e})")
                continue
        else:
            # The default, and the one the six briefs wrote by hand: no literal
            # is pinned because nobody knows what the right answer looks like —
            # only that it must be the SAME answer afterwards.
            mode, expect = "unchanged", None

        try:
            budget = int(d.get("budget_s", default_budget))
        except (TypeError, ValueError):
            problems.append(f"{tag}: budget_s is not a number")
            continue
        if budget <= 0:
            problems.append(f"{tag}: budget_s must be positive, not {budget}")
            continue

        invariants.append({"name": name, "run": cmd, "mode": mode, "expect": expect,
                           "_rx": rx, "because": because, "budget_s": budget})

    for inv in invariants:
        inv["decl"] = _decl_digest(inv)

    # Any defect in a file that EXISTS is loud. A half-understood invariant set is
    # a wrong invariant set, and running on the half we understood is how a plan
    # ends up guarded by rules nobody wrote.
    return InvariantSet(str(cfg), invariants, {"budget_s": default_budget},
                        error="; ".join(problems) or None)


# ── taking a reading ────────────────────────────────────────────────────────

def _norm(s: str) -> str:
    """Line endings and trailing whitespace only. Nothing else is normalised: a
    reading that needed cleaning up before it could be compared is a reading
    whose command should have done the cleaning, where it is visible."""
    return (s or "").replace("\r\n", "\n").replace("\r", "\n").rstrip()


def fmt_reading(reading: dict, cap: int = 240) -> str:
    out = reading.get("out", "")
    if len(out) > cap:
        out = out[:cap] + "…"
    return f"exit {reading.get('exit')} · {out!r}"


def probe(root: Path, inv: dict):
    """Run one invariant's command. Returns (reading, stderr_tail, error).

    `cwd` is the plan root — the same place `validate-plan.py` runs a gate from,
    so a relative path in an invariant means what it means everywhere else."""
    try:
        r = subprocess.run(inv["run"], shell=True, executable="/bin/bash",
                           cwd=str(root), capture_output=True, text=True,
                           timeout=inv["budget_s"])
    except subprocess.TimeoutExpired:
        return None, "", (f"exceeded its {inv['budget_s']}s budget. An unanswered "
                          f"question is not an answer.")
    except OSError as e:
        return None, "", f"could not be launched: {e}"
    out = _norm(r.stdout)
    if len(out) > MAX_READING_BYTES:
        return None, _norm(r.stderr)[-800:], (
            f"produced {len(out)} bytes of output; the ceiling is {MAX_READING_BYTES}. An "
            f"invariant is a READING, not a dump — a diff nobody can read in a halt message "
            f"teaches nothing. Pipe it through `sha256sum`.")
    return {"exit": r.returncode, "out": out}, _norm(r.stderr)[-800:], None


def check(inv: dict, reading: dict, base: dict | None):
    """Returns (ok, expected_text, actual_text). `base` is None at capture time."""
    actual = fmt_reading(reading)
    if inv["mode"] == "equals":
        return (reading["exit"] == 0 and reading["out"] == inv["expect"],
                f"exit 0 · {inv['expect']!r}", actual)
    if inv["mode"] == "matches":
        return (reading["exit"] == 0 and bool(inv["_rx"].search(reading["out"])),
                f"exit 0 · output matching /{inv['expect']}/", actual)
    if base is None:
        return True, "(this reading becomes the reference)", actual
    return (reading["exit"] == base["exit"] and reading["out"] == base["out"],
            fmt_reading(base), actual)


# ── the baseline ────────────────────────────────────────────────────────────

def baseline_path(priv: Path) -> Path:
    return priv / BASELINE_NAME


def read_baseline(priv: Path):
    try:
        return json.loads(baseline_path(priv).read_text())
    except (OSError, ValueError):
        return None


def capture(root: Path, priv: Path, iset: InvariantSet, run_id: str):
    """Take the reference reading for every declared invariant. ALL OR NONE.

    Returns (record, error).

    Two refusals here, and both are the same rule from Grillin's
    OPERATING-THE-PLAN.md §5 — an instrument is proven against a known answer
    BEFORE the measurements it authorises:

      · A probe that cannot exit 0 now is an unproven instrument. Baselining it
        would record a broken probe as the normal state of the world.
      · A pinned `equals`/`matches` that is ALREADY false now was never true, and
        halting on it at tick 2 would blame the plan for something it did not
        break. That is the control test the 404 incident needed and did not get:
        a real defect was asserted as a cause before anyone checked it held
        before the change.

    A baseline with a hole in it is not a baseline, so one bad probe refuses the
    whole capture rather than quietly covering the rest."""
    readings, problems = {}, []
    for inv in iset.invariants:
        reading, stderr, err = probe(root, inv)
        if err:
            problems.append(f"{inv['name']!r} {err}")
            continue
        if reading["exit"] != 0:
            tail = f" stderr: {stderr.splitlines()[-1]}" if stderr.strip() else ""
            problems.append(
                f"{inv['name']!r} exited {reading['exit']} while the baseline was being taken, "
                f"so it is an unproven instrument and nothing it says later can be trusted. "
                f"Write the command so exit 0 means 'I took the reading' and put the reading on "
                f"stdout.{tail}")
            continue
        ok, expected, actual = check(inv, reading, None)
        if not ok:
            problems.append(
                f"{inv['name']!r} is already false before the plan has run: expected {expected}, "
                f"got {actual}. An invariant that was never true cannot be broken by this plan.")
            continue
        readings[inv["name"]] = {"exit": reading["exit"], "out": reading["out"],
                                 "decl": inv["decl"]}

    if problems:
        return None, ("the baseline could not be taken, so nothing is dispatched: "
                      + "; ".join(problems))

    rec = {"schema": "smokin.baseline/1", "run": run_id, "at": _now(),
           "plan": str(root), "readings": readings}
    priv.mkdir(parents=True, exist_ok=True)
    baseline_path(priv).write_text(json.dumps(rec, indent=1) + "\n")
    return rec, None


def recheck(root: Path, priv: Path, iset: InvariantSet, base: dict):
    """Re-run every invariant and compare against the baseline.

    Returns (rows, halt_reason). Every invariant is run even after one has
    broken: the halt is evidence, and "which of the six moved" is the first
    question anyone reading it will ask."""
    stored = base.get("readings") or {}
    declared = {inv["name"]: inv for inv in iset.invariants}

    drift = []
    for name, inv in declared.items():
        if name not in stored:
            drift.append(f"{name!r} is declared but is not in the baseline (added after it "
                         f"was taken)")
        elif stored[name].get("decl") != inv["decl"]:
            drift.append(f"{name!r} has been edited since the baseline was taken")
    for name in stored:
        if name not in declared:
            drift.append(f"{name!r} was in the baseline and is no longer declared "
                         f"(removed mid-run)")
    if drift:
        # Deliberately NOT an automatic re-capture. Editing the file that governs
        # in order to make a break go away is DELEGATION-NODE.md §8's first
        # failure mode — the node becoming the curator — and a silent re-baseline
        # is exactly how that would happen without anyone noticing.
        return [], (f"the baseline no longer covers what {CONFIG_NAME} declares: "
                    + "; ".join(drift) + ". A reading is only comparable to a reading of the "
                    f"same question. If the edit was deliberate, take a new baseline on purpose "
                    f"with `smokin invariants {root} --recapture` — it is recorded in the "
                    f"ledger, which a silent re-baseline would not be.")

    rows, broken = [], []
    for inv in iset.invariants:
        b = stored[inv["name"]]
        reading, stderr, err = probe(root, inv)
        if err:
            row = {"name": inv["name"], "run": inv["run"], "ok": False,
                   "expected": fmt_reading(b) if inv["mode"] == "unchanged" else inv["expect"],
                   "actual": f"(the probe itself failed: {err})", "because": inv["because"]}
        else:
            ok, expected, actual = check(inv, reading, b)
            if not ok and stderr.strip():
                actual += f"  stderr: {stderr.splitlines()[-1]}"
            row = {"name": inv["name"], "run": inv["run"], "ok": ok,
                   "expected": expected, "actual": actual, "because": inv["because"]}
        rows.append(row)
        if not row["ok"]:
            broken.append(row)

    if not broken:
        return rows, None

    L = [f"{len(broken)} of {len(rows)} plan-level invariant(s) broke. "
         f"This is not a warning — nothing further is dispatched.", ""]
    for r in broken:
        L.append(f"INVARIANT BROKEN — {r['name']}")
        L.append(f"    command   {r['run']}")
        L.append(f"    expected  {r['expected']}")
        L.append(f"    actual    {r['actual']}")
        L.append(f"    declared  {r['because']}")
        L.append("")
    L.append(f"The baseline was taken at {base.get('at')} for run {base.get('run')}. "
             f"No task's own done-command looks at any of this, which is the whole reason "
             f"it is declared at plan level.")
    # Unindented. Every surface that shows a halt indents it its own way —
    # `print_halt` by two spaces, PROGRESS.md by a `>` per line — and a reason
    # that arrived pre-indented came out as a code block in the markdown and
    # swallowed the three facts it exists to show.
    return rows, "\n".join(L).rstrip()


def _now():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

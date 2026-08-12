# `smokin verify` and Three Declaration Fixes — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development
> (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Smokin useful at one worker by adding a no-dispatch `verify`, and stop three checks
across both tools from reporting a declaration as a fact.

**Architecture:** `verify` is the existing tick with dispatch, reaping, spooling and judging removed
— a strict subset, so it cannot contradict Smokin's design. The three fixes are wording, one new
field, and one new gate check. Nothing shares state; any task reverts alone.

**Tech Stack:** python3 stdlib only (both tools are zero-dependency), bash test harnesses.

## Global Constraints

- **Zero dependencies.** python3 stdlib only. No new imports beyond stdlib.
- **Fail-closed.** Unknown state is a failure, never a silent pass.
- **`verify` never writes `TASK.md`.** Asserted by hash in its own test.
- **`verify` never starts a process.** Asserted by dispatch-record count in its own test.
- **Band table published once.** XS 1–3, S 4–10, M 11–25, L 26–60, XL 61+. `check-drift.py`
  guards it against `SCALING.json`.
- Repos: `~/smokin` (A, B, C-runner), `~/grillin` (C-gate, D).
- Every task ends green on its repo's full suite before commit.

---

### Task 1: `smokin verify` — the tick with the fleet removed

**Files:**
- Modify: `~/smokin/bin/smokin` (`take_verdict`, new `verify`, `main`, module docstring)
- Test: `~/smokin/tests/test-verify.py` (create)
- Modify: `~/smokin/tests/run-tests.sh` (wire the new harness in)

**Interfaces:**
- Consumes: `Plan`, `take_verdict`, `render_status`, `write_progress`, `halted`, `print_halt`
- Produces: `verify(plan, only=None) -> int`; `take_verdict(plan, tid, write_status=True)`

- [ ] **Step 1: Write the failing test**

`tests/test-verify.py` builds a plan with **no receipts and no dispatch records**, then asserts:

```python
h_before = {t: sha(P/"tasks"/t/"TASK.md") for t in ("T1","T2")}
rc, out = run("verify", P)
assert rc == 0
assert json.load(open(P/"tasks/T1/VERDICT.json"))["pass"] is True
assert {t: sha(P/"tasks"/t/"TASK.md") for t in ("T1","T2")} == h_before   # never edits TASK.md
assert not list((P/".smokin"/"dispatch").glob("*.json"))                  # started nothing
assert (P/"PROGRESS.md").exists() and (P/"STATUS.json").exists()
```

- [ ] **Step 2: Run it, verify it fails**

Run: `python3 tests/test-verify.py`
Expected: FAIL — `verify` is not a valid choice for `cmd`.

- [ ] **Step 3: Make `take_verdict` optionally leave the status line alone**

```python
def take_verdict(plan: Plan, tid: str, write_status: bool = True):
    ...
    (t.dir / "VERDICT.json").write_text(json.dumps(v, indent=1) + "\n")
    if write_status:
        t.set_status("DONE" if v["pass"] else "BLOCKED")
    ledger(plan, event="verdict", task=tid, **{"pass": v["pass"]})
    return v
```

- [ ] **Step 4: Implement `verify`**

```python
RE_READER = re.compile(r"^\*\*Reader:\*\*", re.M | re.I)


def verify(plan: Plan, only=None):
    """The tick with the fleet removed: run each task's OWN done-command and
    record what happened. Starts nothing, reaps nothing, judges nothing.

    At n=1 there is no worker to emit a receipt — you are the receipt, and this
    is the second hand. That is the whole of what Smokin does for one worker,
    and welding it to dispatch is why two users in a row skipped it."""
    plan.priv.mkdir(parents=True, exist_ok=True)
    lock = open(plan.priv / "tick.lock", "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        print("another tick holds the lock — nothing to do")
        return 0
    held = halted(plan)
    if held:
        print_halt(held)
        return 4

    ids = [only] if only else sorted(plan.tasks)
    verdicted = []
    for tid in ids:
        if tid not in plan.tasks:
            print(f"no such task: {tid}", file=sys.stderr)
            return 2
        v = take_verdict(plan, tid, write_status=False)
        verdicted.append(tid)
        print(f"  verdict  {tid}  {'PASS' if v['pass'] else 'REFUTED'}")

    plan.__init__(plan.root)

    # Independence cannot be established here, so say so rather than imply it.
    for tid in sorted(plan.tasks):
        if RE_READER.search(plan.tasks[tid].path.read_text(errors="replace")):
            print(f"  note     {tid} is declared adversarial. Nothing ran it here, "
                  f"so its independence is unverified.")

    st = render_status(plan, [], verdicted, [], [], (), None)
    write_progress(plan, st)

    if plan.rules.active and not plan.rules.error:
        waiting = [t for t in plan.tasks if plan.ruling_state(t) == "judging"]
        if waiting:
            print(f"\n{len(waiting)} task(s) need a ruling; `smokin tick` is what asks. "
                  f"verify does not spend model calls.")

    ver = st["counts"]["verified"]
    if len(plan.frontier()) > 1:
        print(f"\n{len(plan.frontier())} tasks are ready at once — that is what "
              f"`smokin tick` is for.")
    print(f"\n{ver} of {st['total']} verified · see PROGRESS.md")
    return 0 if ver == st["total"] and plan.tasks else 1
```

- [ ] **Step 5: Wire the CLI**

Add `"verify"` to the `cmd` choices, add `ap.add_argument("--task", default=None)`, and:

```python
    if a.cmd == "verify":
        return verify(plan, a.task)
```

Add to the module docstring, under `smokin tick`:

```
    smokin verify            run every task's own done-command; start nothing
```

- [ ] **Step 6: Run the test, verify it passes**

Run: `python3 tests/test-verify.py` → ALL PASS.

- [ ] **Step 7: Add the remaining acceptance tests**

Refuted case (exit 1), `verify` then `tick` leaves verdict hashes unchanged, and a judge-stub
sentinel file that must NOT appear.

- [ ] **Step 8: Wire into `run-tests.sh` and run the whole suite**

Run: `bash tests/run-tests.sh` → all pass, no regressions.

- [ ] **Step 9: Commit**

```bash
git add bin/smokin tests/test-verify.py tests/run-tests.sh
git commit -m "feat: smokin verify — the tick with the fleet removed"
```

---

### Task 2: README, human first

**Files:**
- Modify: `~/smokin/README.md`

**Interfaces:**
- Consumes: `verify` from Task 1 (it is the first command shown)
- Produces: nothing code-facing

- [ ] **Step 1: Add "Do you need this?" as the first section after the title**

```markdown
## Do you need this?

| Your situation | Answer |
|---|---|
| More than one worker running at once | **Yes.** That is what this is for |
| One worker, or you are doing it yourself | **Partly** — you want `smokin verify` and nothing else |
| You have no plan yet | Not yet. Write one first — see Grillin |

**At n=1, you are the receipt. `verify` is the second hand.** Your agent says it finished;
`smokin verify` re-runs the task's own done-command itself and tells you whether that was true.
No workers are started, nothing runs in the background, nothing is left alive.
```

- [ ] **Step 2: Add "Sixty seconds" immediately after it**

```markdown
## Sixty seconds

    smokin verify examples/demo-plan

Every task's own done-command is re-run, and you get one page — `PROGRESS.md` — saying which
tasks are actually finished and which merely claim to be.
```

- [ ] **Step 3: Move "The one idea" below those, retitle it "The three states"**

Keep the prose; lead with the glyph legend so the reader meets the words after seeing them.

- [ ] **Step 4: Group the fleet-only material under one heading**

`## When you need the fleet` — dispatch, panes, the pane ceiling, the reaper, routing. Everything
that only makes sense at n>1, marked as such.

- [ ] **Step 5: Move "For an agent reading this" to the bottom, verbatim**

- [ ] **Step 6: Verify the command table lists `verify` first and check every internal link**

Run: `grep -n "smokin verify" README.md` and confirm the links resolve.

- [ ] **Step 7: Commit**

```bash
git add README.md && git commit -m "docs: README answers 'do you need this' before 'how does it work'"
```

---

### Task 3: The adversary check stops over-claiming

**Files:**
- Modify: `~/grillin/scripts/validate-plan.py:573`
- Modify: `~/smokin/bin/smokin` (`launch`, `tick`)
- Test: `~/smokin/tests/test-verify.py` (session-collision case)

**Interfaces:**
- Consumes: dispatch records from `launch`
- Produces: dispatch records gain `"session": <pane id | pid>`

- [ ] **Step 1: Replace the Grillin message (wording only, no logic change)**

```python
        f.ok("adversary",
             f"{sorted(adversaries)} is declared adversarial and its owner is named on no "
             f"other task. This checks the DECLARATION only — nothing here can tell who "
             f"actually RAN it, and in a one-agent setup the separation is fictional. "
             f"`smokin verify` says so out loud; `smokin tick` enforces it where it can.")
```

- [ ] **Step 2: Run Grillin's calibration**

Run: `./scripts/validate-plan.py examples/minimal-passing-plan --run-gates` → exit 0, new wording.
Run: `./scripts/validate-plan.py examples/a-real-first-plan --run-gates` → exit 1.

- [ ] **Step 3: Record the session on every dispatch**

In `launch`, after `rec` is built: `rec["session"] = None`, then set
`rec["session"] = pane["pane"]` in the pane branch and `rec["session"] = f"pid:{p.pid}"` in the
inproc branch, before each write.

- [ ] **Step 4: Refuse to dispatch an adversarial task into a used session**

In `tick`, before `launch`, for tasks whose `TASK.md` matches `RE_READER`:

```python
        used = {json.loads(f.read_text()).get("session")
                for f in (plan.priv / "dispatch").glob("*.json")
                if json.loads(f.read_text())["task"] != tid}
        used.discard(None)
```

`inproc` always yields a fresh pid, so this is satisfied for free there — **that is a real property,
not a gap.** It bites on pane reuse. If a pane would be reused, halt with the colliding session id.

- [ ] **Step 5: Test the collision and the negative control**

Plant a dispatch record with `"session": "w9:p1"`, declare a task adversarial, force pane routing,
assert `tick` halts and names `w9:p1`. Negative control: fresh session dispatches silently.

- [ ] **Step 6: Run both suites and commit**

```bash
git commit -m "gate: the adversary check reports what it checked, not what it implies"
```

---

### Task 4: Declared size, enforced

**Files:**
- Modify: `~/grillin/scripts/validate-plan.py` (new `check_size_declared`, registration)
- Modify: `~/grillin/scripts/check-drift.py` (band table guard)
- Modify: `~/grillin/SCALING.json` (`gateChecks`)
- Modify: `~/grillin/templates/PLAN.md.template`, `QUICKSTART.md`
- Modify: `~/grillin/examples/minimal-passing-plan/PLAN.md` (gains the field)
- Modify: `~/grillin/.github/workflows/gate.yml` (two probes)

**Interfaces:**
- Produces: `BANDS = [("XS",1,3),("S",4,10),("M",11,25),("L",26,60),("XL",61,10**6)]`

- [ ] **Step 1: Add the check**

```python
RE_SIZE = re.compile(r"^\*\*Size:\*\*\s*([A-Z]{1,2})\b", re.M)
BANDS = [("XS", 1, 3), ("S", 4, 10), ("M", 11, 25), ("L", 26, 60), ("XL", 61, 10 ** 6)]


def check_size_declared(f: Findings, plan: Path, tasks: dict, cfg: dict):
    """A size band nobody enforces is advice. In a watched trial a user said
    "1-3 tasks, short path" and got 5 with rollback plans — the bands are prose
    the plan-writing agent is never obliged to obey."""
    p = plan / "PLAN.md"
    if not p.is_file():
        return                      # check_plan_source_of_truth owns that failure
    m = RE_SIZE.search(p.read_text(errors="replace"))
    n = len(tasks)
    if not m:
        f.fail("size-declared", f"{p}:1",
               "PLAN.md declares no **Size:**. A plan that never says how big it is cannot "
               "be held to it, and the bands stay advice until it does.")
        return
    want = m.group(1).upper()
    band = next((b for b in BANDS if b[0] == want), None)
    if band is None:
        f.fail("size-declared", f"{p}:1",
               f"Size {want!r} is not one of {[b[0] for b in BANDS]}")
        return
    _, lo, hi = band
    if not (lo <= n <= hi):
        f.fail("size-declared", f"{p}:1",
               f"PLAN.md declares Size: {want} ({lo}-{hi if hi < 10**6 else '61+'} tasks); "
               f"this plan has {n}. Either it grew past what you scoped — say so and "
               f"re-scope — or the declaration is stale.")
        return
    f.ok("size-declared", f"declared {want} and holds {n} task(s), inside the band")
```

- [ ] **Step 2: Register it, add `"size-declared"` to `SCALING.json`'s `gateChecks`**

- [ ] **Step 3: Add `**Size:** <XS|S|M|L|XL>` to `templates/PLAN.md.template` and QUICKSTART**

- [ ] **Step 4: Add `**Size:** S` to the known-good fixture (4 tasks)**

- [ ] **Step 5: Guard the band table in `check-drift.py`**

Parse `BANDS` from `validate-plan.py` and `scaling[].tasks` from `SCALING.json`; fail if they
disagree.

- [ ] **Step 6: Run everything**

known-good 0, known-bad 1, no-gates 2, drift 0, boundary 0.

- [ ] **Step 7: Add two CI probes and commit**

```bash
git commit -m "gate: size-declared — a band nobody enforces is advice"
```

---

## Self-Review

**Spec coverage:** §3 → Task 1 · §4 → Task 2 · §5.1 → Task 3 step 1 · §5.2 → Task 3 steps 3–5 ·
§5.2's `verify` warning → Task 1 step 4 · §6 → Task 4 · §6.3 drift guard → Task 4 step 5.
§2's "out of scope" needs no task by construction.

**Placeholders:** none. Every code step carries the code.

**Type consistency:** `take_verdict(plan, tid, write_status=True)` — one signature, used with the
keyword in Task 1 and unchanged at its existing call site in `tick`. `verify(plan, only=None)`
matches the CLI's `a.task`. `RE_READER` is defined once in `bin/smokin` and used by both Task 1 and
Task 3. `BANDS` is defined once in `validate-plan.py` and read by `check-drift.py`.

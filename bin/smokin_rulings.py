#!/usr/bin/env python3
"""
The delegation node's judgement layer: `_RULINGS.toml`, and the ledger it writes.

WHY THIS EXISTS. `smokin tick` already advances a plan without a resident
orchestrator — it reads the plan off disk, dispatches, and exits. What it could
not do is make a judgement call, because a judgement made by a process that then
dies is a judgement nobody can review. This module is the other half: judgement
is INVOKED, not resident. The node asks one judge, writes the ruling to disk with
its reason, and exits. The ruling file is the memory.

FOUR PROPERTIES, each one a defect that has already happened somewhere in this
family of tools:

  1. A DECISION CLASS NOT DECLARED CANNOT BE MADE. `_RULINGS.toml` lists every
     tier-2 class this plan permits. Anything uncovered is a halt unless the
     curator wrote `uncovered = "accept"` down, on purpose, where it can be read.

  2. THE PERSONA RESOLVES AGAINST `_ROSTER.md`, so the judge's model and effort
     come from the file that carries the REASON. A persona invented here is a
     persona nobody priced.

  3. `outcomes` IS A CLOSED SET. A judge that may return prose can return
     anything, and the node would have to interpret it — which is judgement the
     node is not allowed to have.

  4. `default = "halt"`, AND IT IS NOT CONFIGURABLE TO ANYTHING SOFTER. An
     unreachable judge that quietly resolves to `accept` is a plan that certifies
     itself while looking like it works. Silence that resembles success is the
     worst available outcome.

OPT-IN BY FILE. No `_RULINGS.toml` means the node has no judgement layer and the
tick behaves exactly as it did before. Once the file exists, it binds.

Zero dependencies (python3 stdlib >= 3.11 for tomllib). Fail-closed.
"""
from __future__ import annotations

import ast
import hashlib
import json
import os
import re
import subprocess
import time
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:                                   # pragma: no cover
    tomllib = None

CONFIG_NAME = "_RULINGS.toml"
ROSTER_NAME = "_ROSTER.md"
MAX_RULINGS = 32
DEFAULT_JUDGE_BUDGET = 300
REQUIRED_OUTCOME = "insufficient-evidence"

# Advancing outcomes are the ONLY ones that let a task become verified. Every
# other outcome stops it, and stopping loudly is the point.
ADVANCING = {"accept"}
REJECTING = {"reject"}

# The whole namespace a `when` expression may see. A dotted name outside this set
# is a config error at LOAD time, not a silent False at evaluation time — a typo
# that evaluates to False is a ruling that never fires and a plan that looks
# judged and is not.
KNOWN_FIELDS = {
    "state",
    "verdict.passed", "verdict.exit",
    "receipt.claim", "receipt.terminal", "receipt.source", "receipt.stale",
    "task.id", "task.type", "task.owner", "task.runtime", "task.dispatch",
}

# What a judge may be handed. Anything else is a config error: the evidence list
# is the containment, and a resolver that quietly ignores an unknown name is a
# containment with a hole in it.
EVIDENCE_FILES = {
    "task.contract":  lambda root, tid: [root / "tasks" / tid / "TASK.md"],
    "receipt":        lambda root, tid: [root / "tasks" / tid / "RECEIPT.json"],
    "verdict":        lambda root, tid: [root / "tasks" / tid / "VERDICT.json"],
    "worker.output":  lambda root, tid: [root / "tasks" / tid / n
                                         for n in ("FINDINGS.md", "CHANGES.md", "QUESTIONS.md")],
    "transcript":     lambda root, tid: [root / "tasks" / tid / ".smokin" / "transcript.log"],
    "plan":           lambda root, tid: [root / "PLAN.md"],
    "roster":         lambda root, tid: [root / ROSTER_NAME],
    "herdr.state":    lambda root, tid: [root / ".herdr" / "state.json"],
}

_AST_OK = (ast.Expression, ast.BoolOp, ast.UnaryOp, ast.Not, ast.And, ast.Or,
           ast.Compare, ast.Eq, ast.NotEq, ast.In, ast.NotIn, ast.Name,
           ast.Attribute, ast.Constant, ast.Load, ast.Tuple, ast.List)


# ── the roster ──────────────────────────────────────────────────────────────

RE_MODEL = re.compile(r"\bclaude-[a-z0-9.-]+\b")
RE_EFFORT = re.compile(r"\b(high|xhigh|max)\b")


def read_roster(root: Path) -> tuple[dict, str | None]:
    """persona -> {model, effort}, parsed from `_ROSTER.md`'s table.

    The roster is the file that carries the reason, so it is also the file that
    decides what a judge costs. Nothing here invents a pairing; a persona with no
    model or no effort in the table is reported as an error, not defaulted."""
    f = root / ROSTER_NAME
    if not f.is_file():
        return {}, f"{ROSTER_NAME} not found beside the plan"
    out, problems = {}, []
    for line in f.read_text(errors="replace").splitlines():
        if not line.lstrip().startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 4:
            continue
        names = re.findall(r"`([a-z][a-z0-9_-]*)`", cells[0])
        if not names:
            continue
        joined = " | ".join(cells[1:])
        m, e = RE_MODEL.search(joined), RE_EFFORT.search(joined)
        if not m or not e:
            problems.append(f"roster row for {', '.join(names)} has no model/effort pair")
            continue
        for n in names:
            out[n] = {"model": m.group(0), "effort": e.group(1)}
    if not out and not problems:
        problems.append(f"{ROSTER_NAME} declares no personas")
    return out, "; ".join(problems) or None


# ── the `when` expression ───────────────────────────────────────────────────

def _dotted(node) -> str | None:
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if not isinstance(node, ast.Name):
        return None
    parts.append(node.id)
    return ".".join(reversed(parts))


def compile_when(expr: str):
    """Parse and whitelist. Returns (callable, error). Never eval()s raw text.

    The allowlist is by AST node type, so a call, a subscript, an f-string, a
    comprehension and a walrus are all rejected structurally rather than by
    pattern-matching the source — which is the only way that stays true when
    somebody writes something nobody thought of."""
    try:
        tree = ast.parse(expr, mode="eval")
    except SyntaxError as e:
        return None, f"when {expr!r} is not parseable: {e.msg}"
    names = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Attribute) or isinstance(n, ast.Name):
            d = _dotted(n)
            if d:
                names.add(d)
        if not isinstance(n, _AST_OK):
            return None, f"when {expr!r} uses {type(n).__name__}, which is not permitted"
    # Only the OUTERMOST dotted chain counts: `receipt.claim` walks as both
    # `receipt.claim` and `receipt`, and rejecting the prefix would reject every
    # legal expression.
    leaves = {d for d in names if not any(o != d and o.startswith(d + ".") for o in names)}
    unknown = sorted(leaves - KNOWN_FIELDS)
    if unknown:
        return None, (f"when {expr!r} reads unknown field(s): {', '.join(unknown)}. "
                      f"Known: {', '.join(sorted(KNOWN_FIELDS))}")
    code = compile(tree, "<when>", "eval")

    def run(ctx: dict) -> bool:
        try:
            return bool(eval(code, {"__builtins__": {}}, _Ns(ctx)))   # noqa: S307
        except Exception:
            # An expression that throws is not False. False would silently mean
            # "no ruling required", which is the fail-open shape.
            raise
    return run, None


class _Ns(dict):
    """Resolves `receipt.claim` against a flat {'receipt.claim': ...} context."""

    def __missing__(self, key):
        return _Leaf(self, key)


class _Leaf:
    def __init__(self, ns, prefix):
        self._ns, self._p = ns, prefix

    def __getattr__(self, name):
        k = f"{self._p}.{name}"
        if k in self._ns:
            return dict.__getitem__(self._ns, k)
        return _Leaf(self._ns, k)

    def __eq__(self, other):
        return False if not isinstance(other, _Leaf) else self._p == other._p

    def __hash__(self):
        return hash(self._p)

    def __bool__(self):
        return False


# ── the config ──────────────────────────────────────────────────────────────

class RulingSet:
    """The tier-2 decision classes in force for one plan."""

    def __init__(self, source, rulings, policy, error=None):
        self.source = source
        self.rulings = rulings
        self.policy = policy
        self.error = error

    @property
    def active(self) -> bool:
        return self.source is not None

    def required_for(self, ctx: dict):
        """Every declared class whose `when` matches this task, in file order."""
        if self.error:
            return []
        out = []
        for r in self.rulings:
            if r["_when"](ctx):
                out.append(r)
        return out

    def __repr__(self):
        return (f"<RulingSet {self.source or 'inactive'} n={len(self.rulings)}"
                f"{' ERROR' if self.error else ''}>")


def load(root: Path) -> RulingSet:
    cfg = root / CONFIG_NAME
    if not cfg.is_file():
        return RulingSet(None, [], {"uncovered": "accept"})      # opt-in by file

    if tomllib is None:
        return RulingSet(str(cfg), [], {}, error="python is too old for tomllib (need 3.11+)")
    try:
        raw = tomllib.loads(cfg.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as e:
        return RulingSet(str(cfg), [], {}, error=f"unparseable: {e}")

    roster, roster_err = read_roster(root)
    declared = raw.get("ruling")
    problems = []
    if not isinstance(declared, list) or not declared:
        return RulingSet(str(cfg), [], {}, error="no [[ruling]] entries")
    if len(declared) > MAX_RULINGS:
        return RulingSet(str(cfg), [], {},
                         error=f"{len(declared)} rulings declared, ceiling is {MAX_RULINGS}")

    pol = raw.get("policy") or {}
    uncovered = str(pol.get("uncovered", "halt")).lower()
    if uncovered not in ("halt", "accept"):
        problems.append(f"policy.uncovered must be 'halt' or 'accept', not {uncovered!r}")
    policy = {"uncovered": uncovered}

    rulings, seen = [], set()
    for i, r in enumerate(declared):
        tag = f"ruling[{i}]"
        if not isinstance(r, dict):
            problems.append(f"{tag} is not a table")
            continue
        cls = (r.get("class") or "").strip()
        if not cls:
            problems.append(f"{tag} has no class")
            continue
        tag = f"ruling {cls!r}"
        if cls in seen:
            problems.append(f"{tag} is declared twice — a class is one rule or it is none")
            continue
        seen.add(cls)

        when_src = (r.get("when") or "").strip()
        if not when_src:
            problems.append(f"{tag} has no when")
            continue
        fn, err = compile_when(when_src)
        if err:
            problems.append(f"{tag}: {err}")
            continue

        persona = (r.get("persona") or "").strip()
        if not persona:
            problems.append(f"{tag} has no persona")
            continue
        if roster_err:
            problems.append(f"{tag}: cannot resolve persona — {roster_err}")
            continue
        if persona not in roster:
            problems.append(f"{tag}: persona {persona!r} is not in {ROSTER_NAME}. "
                            f"Add it there first, with its reason.")
            continue

        ev = r.get("evidence")
        if not isinstance(ev, list) or not ev:
            problems.append(f"{tag} declares no evidence — a judge handed nothing rules on nothing")
            continue
        bad = [e for e in ev if e not in EVIDENCE_FILES]
        if bad:
            problems.append(f"{tag}: unknown evidence {', '.join(map(str, bad))}. "
                            f"Known: {', '.join(sorted(EVIDENCE_FILES))}")
            continue

        outs = r.get("outcomes")
        if not isinstance(outs, list) or not outs:
            problems.append(f"{tag} declares no outcomes")
            continue
        outs = [str(o).strip() for o in outs]
        if REQUIRED_OUTCOME not in outs:
            problems.append(f"{tag}: outcomes must include {REQUIRED_OUTCOME!r} — a judge with no "
                            f"way to say 'I cannot tell' will say something else instead")
            continue
        if not (set(outs) & ADVANCING):
            problems.append(f"{tag}: outcomes include nothing that advances the plan "
                            f"(one of: {', '.join(sorted(ADVANCING))})")
            continue

        default = str(r.get("default", "halt")).lower()
        if default != "halt":
            problems.append(f"{tag}: default is {default!r}. It must be 'halt'. An unreachable "
                            f"judge that resolves to anything else certifies work nobody read.")
            continue

        try:
            budget = int(r.get("budget_s", DEFAULT_JUDGE_BUDGET))
        except (TypeError, ValueError):
            problems.append(f"{tag}: budget_s is not a number")
            continue

        rulings.append({
            "class": cls, "when_src": when_src, "_when": fn, "persona": persona,
            "model": roster[persona]["model"], "effort": roster[persona]["effort"],
            "evidence": ev, "outcomes": outs, "default": "halt",
            "runtime": (r.get("runtime") or "claude").strip("` "), "budget_s": budget,
        })

    # Any defect in a file that EXISTS is loud. A half-understood ruling set is a
    # wrong ruling set, and running on the half we understood is how a plan ends
    # up judged by rules nobody wrote.
    return RulingSet(str(cfg), rulings, policy, error="; ".join(problems) or None)


# ── the ledger ──────────────────────────────────────────────────────────────

def ledger_path(priv: Path) -> Path:
    return priv / "rulings.jsonl"


def read_ledger(priv: Path) -> list[dict]:
    f = ledger_path(priv)
    if not f.is_file():
        return []
    out = []
    for line in f.read_text(errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return out


def append_ruling(priv: Path, rec: dict) -> dict:
    """Append-only, seq-numbered. A reversed decision is a NEW ruling that names
    the one it supersedes — never an edit. The history of what was decided, and
    on what evidence, is the only thing this design buys; editing it spends it."""
    priv.mkdir(parents=True, exist_ok=True)
    prior = read_ledger(priv)
    rec = dict(rec)
    rec["seq"] = (max((r.get("seq", 0) for r in prior), default=0) + 1)
    rec.setdefault("at", time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
    fd = os.open(str(ledger_path(priv)), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
    try:
        os.write(fd, (json.dumps(rec, ensure_ascii=False) + "\n").encode())
    finally:
        os.close(fd)
    return rec


def standing(priv: Path) -> dict:
    """(class, task) -> the ruling that currently stands.

    Later supersedes earlier, which is what makes a re-judge visible rather than
    silent: the superseded ruling stays in the file with its reason, so judge
    shopping leaves a trail instead of a clean result."""
    out = {}
    for r in read_ledger(priv):
        k = (r.get("class"), r.get("task"))
        if r.get("retired"):
            out.pop(k, None)      # a retirement REMOVES the standing ruling; skipping
            continue              # the line would leave the retired one still standing
        out[k] = r
    return out


# ── evidence ────────────────────────────────────────────────────────────────

def gather_evidence(root: Path, tid: str, names: list[str]):
    """Exactly the declared files, and nothing else. Returns (items, digest).

    The digest is over the evidence actually handed over, so a re-judge on
    unchanged evidence is detectable and refusable."""
    items, h = [], hashlib.sha256()
    for name in names:
        for p in EVIDENCE_FILES[name](root, tid):
            rel = os.path.relpath(p, root)
            if p.is_file():
                body = p.read_text(errors="replace")
                items.append({"name": name, "path": rel, "present": True, "body": body})
                h.update(f"{rel}\0".encode())
                h.update(hashlib.sha256(body.encode(errors="replace")).digest())
            else:
                items.append({"name": name, "path": rel, "present": False, "body": None})
                h.update(f"{rel}\0ABSENT\0".encode())
    return items, "sha256:" + h.hexdigest()


BRIEF_HEAD = """# Ruling brief — {cls}

You are judging **task {tid}** of the plan at `{root}`.

You did not write this work and you are not being asked to fix it. You are being
asked one question, and to answer it from the evidence below and nothing else.

## The question

{question}

## How to answer

Write the file `{out}` and nothing else. It must be exactly this JSON object:

```json
{{"outcome": "<one of: {outcomes}>",
 "because": "<one or two sentences. What in the evidence decided it. Not a summary of the task.>"}}
```

Rules, and each one is enforced by the process that reads your answer:

- `outcome` MUST be one of `{outcomes}`. Anything else halts the plan.
- `because` MUST be non-empty and MUST cite what you actually read. A ruling with
  no reason is unreviewable, and being reviewable is the whole reason you were asked.
- If the evidence does not let you decide, answer `{insufficient}`. That is a real
  answer and it is the correct one when it is true. Guessing is not.
- Do NOT edit any file other than `{out}`. Do NOT run the task. Do NOT fix anything.

## The evidence — this is all of it
"""

QUESTIONS = {
    "receipt-trust": "Did the worker actually do what its contract required, or did it only produce "
                     "output that resembles it? The receipt is the worker's CLAIM about itself. "
                     "Accept only if the evidence shows the contract was met.",
    "blocked-real": "Is this worker genuinely blocked and waiting on a human, or does it merely "
                    "LOOK idle? Accept only if the evidence shows real work remains and a human "
                    "decision is required.",
    "failure-disposition": "Does this failure mean the task should be re-dispatched, or does it "
                           "mean the plan is wrong and should stop? Accept only if re-dispatch is "
                           "likely to succeed for a reason the evidence shows.",
}
DEFAULT_QUESTION = ("Should the plan advance past this task on the evidence below? "
                    "Accept only if it should.")


def write_brief(root: Path, priv: Path, rule: dict, tid: str, items, workdir: Path) -> Path:
    workdir.mkdir(parents=True, exist_ok=True)
    out = workdir / "RULING.json"
    L = [BRIEF_HEAD.format(
        cls=rule["class"], tid=tid, root=root, out=out,
        question=QUESTIONS.get(rule["class"], DEFAULT_QUESTION),
        outcomes=", ".join(rule["outcomes"]), insufficient=REQUIRED_OUTCOME)]
    for it in items:
        L.append(f"\n### `{it['path']}` ({it['name']})\n")
        if not it["present"]:
            L.append("*This file does not exist. Its absence is evidence too.*\n")
            continue
        body = it["body"]
        if len(body) > 60000:
            body = body[:30000] + "\n\n...[truncated]...\n\n" + body[-30000:]
        fence = "```" if "```" not in body else "~~~"
        L.append(f"{fence}\n{body.rstrip()}\n{fence}\n")
    (workdir / "BRIEF.md").write_text("\n".join(L))
    return out


def invoke_judge(root: Path, priv: Path, rule: dict, tid: str, runtimes: dict,
                 attempt: int = 1):
    """One bounded call. Returns (ruling_dict, halt_reason).

    Every failure path returns a halt reason. There is no path through this
    function that advances the plan without a judge having actually answered."""
    items, digest = gather_evidence(root, tid, rule["evidence"])
    wd = priv / "judge" / f"{rule['class']}-{tid}-{attempt}"
    out = write_brief(root, priv, rule, tid, items, wd)
    if out.exists():
        out.unlink()

    row = runtimes.get(rule["runtime"]) or {}
    head = row.get("headless")
    if not head:
        return None, (f"runtime {rule['runtime']!r} has no headless mode, so the judge for "
                      f"{rule['class']} on {tid} could not be reached")

    line = f"read {os.path.relpath(wd / 'BRIEF.md', root)} and follow it exactly"
    argv = head.split() + [line]
    env = dict(os.environ,
               SMOKIN_RULING_CLASS=rule["class"], SMOKIN_RULING_TASK=tid,
               SMOKIN_RULING_OUT=str(out), SMOKIN_JUDGE_MODEL=rule["model"],
               SMOKIN_JUDGE_EFFORT=rule["effort"])
    try:
        r = subprocess.run(argv, cwd=str(root), env=env, capture_output=True,
                           text=True, timeout=rule["budget_s"])
        rc, tail = r.returncode, (r.stdout or "")[-2000:] + (r.stderr or "")[-2000:]
    except subprocess.TimeoutExpired:
        return None, (f"judge for {rule['class']} on {tid} exceeded its {rule['budget_s']}s budget. "
                      f"An unanswered question is not an answer.")
    except OSError as e:
        return None, f"judge for {rule['class']} on {tid} could not be launched: {e}"
    (wd / "judge.log").write_text(tail)

    if not out.is_file():
        return None, (f"judge for {rule['class']} on {tid} exited {rc} and wrote no {out.name}. "
                      f"See {os.path.relpath(wd, root)}/judge.log")
    try:
        ans = json.loads(out.read_text())
    except ValueError as e:
        return None, f"judge for {rule['class']} on {tid} wrote unparseable JSON: {e}"

    outcome = str(ans.get("outcome", "")).strip()
    because = str(ans.get("because", "")).strip()
    if outcome not in rule["outcomes"]:
        return None, (f"judge for {rule['class']} on {tid} returned outcome {outcome!r}, which is "
                      f"not in the declared set ({', '.join(rule['outcomes'])}).")
    if not because:
        return None, (f"judge for {rule['class']} on {tid} returned {outcome!r} with no reason. "
                      f"A ruling nobody can review is not a ruling.")

    return {"class": rule["class"], "task": tid, "persona": rule["persona"],
            "model": rule["model"], "effort": rule["effort"], "outcome": outcome,
            "because": because, "evidence": [it["path"] for it in items],
            "evidence_digest": digest, "runtime": rule["runtime"],
            "judge_exit": rc, "attempt": attempt}, None


def evidence_digest(root: Path, tid: str, names: list[str]) -> str:
    return gather_evidence(root, tid, names)[1]

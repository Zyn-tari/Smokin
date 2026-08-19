#!/usr/bin/env python3
"""Calibrate token capture — the reading that made "does reuse pay" answerable.

THE INCIDENT. Six agents sat idle holding exactly the context the next tasks
needed, and a seventh pane was opened. The ledger could already answer how long
that took, how many retries it cost and how often the first pass survived its
gate. It could not answer what it SPENT, so the obvious question had no
measurement behind it.

Two claims are under test and they are different claims:

  1 · `result` still means what it meant. Giving claude `--output-format json`
      turns the last twenty transcript lines into a JSON envelope, and TWO
      places fell back to exactly those twenty lines. A runtime that declares
      no envelope must be byte-identical to before — that is the silent control
      that says this change is additive and not a rewrite of the receipt.

  2 · The numbers are the vendor's, unmapped, un-invented. Absent is a reading.
      Zero is a different reading. A test that only proves the parser fires is
      half a test; the other half proves it stays quiet, and quiet in the right
      way, when the runtime said nothing.

Every fixture below is a REAL vendor line, captured from a real invocation and
recorded in templates/runtimes.json's `verified` fields. A synthetic fixture
would prove the parser matches the fixture and nothing about the vendor.

    python3 tests/test-usage.py
"""
import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SMOKIN = ROOT / "bin" / "smokin"
EMIT = ROOT / "bin" / "smokin-emit"
spec = importlib.util.spec_from_file_location("U", ROOT / "bin" / "smokin_usage.py")
U = importlib.util.module_from_spec(spec)
spec.loader.exec_module(U)

RTS = json.loads((ROOT / "templates" / "runtimes.json").read_text())

fails = 0
LAB = Path(tempfile.mkdtemp(prefix="smokin-usage."))


def g(d, k):
    """Read a field without trusting that it is there.

    A check written as `g(u, "input_tokens")` does not fail when the parser breaks
    — it RAISES, and every check below it never runs. Mutation-proving found
    exactly that: three broken mechanisms produced zero failures and a
    traceback. A test that cannot survive its own subject being broken is not
    an instrument."""
    return (d or {}).get(k) if isinstance(d, dict) else None


def chk(label, got, want):
    global fails
    if got == want:
        print(f"  \033[32mPASS\033[0m  {label}")
    else:
        fails += 1
        print(f"  \033[31mFAIL\033[0m  {label} — want {want!r}, got {got!r}")


# ── the fixtures ────────────────────────────────────────────────────────────
# Trimmed of fields nothing reads, otherwise verbatim from the probes.

CLAUDE = ('{"type":"result","subtype":"success","is_error":false,'
          '"result":"OK","session_id":"9c0e2c64","total_cost_usd":0.1429645,'
          '"usage":{"input_tokens":2,"cache_creation_input_tokens":13486,'
          '"cache_read_input_tokens":15989,"output_tokens":4}}')

CODEWHALE = "\n".join([
    '{"type":"content","content":"ele","schema":"codewhale.exec-stream"}',
    '{"type":"content","content":"ven","schema":"codewhale.exec-stream"}',
    '{"type":"session_capture","content":"<transcript>","schema":"codewhale.exec-stream"}',
    '{"type":"metadata","meta":{"receipt_kind":"terminal","model":"deepseek-v4-pro",'
    '"input_tokens":15315,"output_tokens":39,"prompt_cache_hit_tokens":1792,'
    '"prompt_cache_miss_tokens":13523,"reasoning_tokens":37,"status":"completed"},'
    '"schema":"codewhale.exec-stream"}',
    '{"type":"done","schema":"codewhale.exec-stream"}',
])

OPENCODE = "\n".join([
    '{"type":"step_start","part":{"id":"prt_a","type":"step-start"}}',
    '{"type":"text","part":{"id":"prt_b","type":"text","text":"eleven"}}',
    '{"type":"step_finish","part":{"id":"prt_c","type":"step-finish",'
    '"tokens":{"total":8579,"input":6580,"output":51,"reasoning":28,'
    '"cache":{"write":0,"read":1920}},"cost":0.00293799}}',
])

# What the wrapper's two racing `tee` processes actually do to a transcript:
# stdout and stderr arrive out of order and a line can be torn mid-write.
# CONFIRMED by probe — a child that printed stdout first had its stderr line
# recorded first. Every fixture is read through this, never clean.
def teed(payload, lead=""):
    return ("SMOKIN_WRAPPER_START task=T1 pid=4242 at=2026-08-19T10:00:00Z\n"
            '{"type":"metad\n'                     # a torn line, not a defect
            "warning: something on stderr\n"
            + lead + payload + "\ntrailing prose the agent printed\n")


print("=== the numbers are the vendor's own ===")

u = U.usage_from(teed(CLAUDE), RTS["claude"])
chk("claude: tokens parsed", (g(u, "input_tokens"), g(u, "output_tokens")), (2, 4))
chk("claude: cache read/write kept apart",
    (g(u, "cache_read_tokens"), g(u, "cache_write_tokens")), (15989, 13486))
chk("claude: cost recorded because claude reports one", g(u, "cost_usd"), 0.1429645)

u = U.usage_from(teed(CODEWHALE), RTS["codewhale"])
chk("codewhale: tokens parsed", (g(u, "input_tokens"), g(u, "output_tokens")), (13523, 39))
chk("codewhale: cache hits are cache reads", g(u, "cache_read_tokens"), 1792)
# THE ONE THAT MATTERS MOST. codewhale reports no cost anywhere and this repo
# has no price table. A `cost_usd: null` would be a column that is null forever;
# a `cost_usd: 0` would be a lie that survives every later average. Absent.
chk("codewhale: NO cost key at all, not null and not zero", "cost_usd" in (u or {}), False)
# And the mapping is not a naive one: codewhale's meta.input_tokens is the TOTAL
# including cache hits, claude's excludes them. Mapping both onto `input_tokens`
# would silently compare unlike things.
chk("codewhale: input_tokens is the uncached part, not the total",
    (g(u, "input_tokens") or 0) + (g(u, "cache_read_tokens") or 0), 15315)

u = U.usage_from(teed(OPENCODE), RTS["opencode"])
chk("opencode: tokens parsed", (g(u, "input_tokens"), g(u, "output_tokens")), (6580, 51))
chk("opencode: cost recorded because opencode reports one", g(u, "cost_usd"), 0.00293799)
# A vendor that SAYS zero is not a vendor that said nothing. opencode reported
# cache.write=0 and that 0 is a real reading, so it is kept.
chk("opencode: a reported zero is kept as zero", g(u, "cache_write_tokens"), 0)

print("\n=== per-step runtimes are summed, per-run runtimes are not ===")
# opencode emits step_finish PER STEP. A run with tool use reports several and
# the run total is their sum.
two = OPENCODE + "\n" + OPENCODE
u = U.usage_from(teed(two), RTS["opencode"])
chk("opencode: two steps sum", (g(u, "input_tokens"), g(u, "output_tokens")), (13160, 102))
chk("...including cost", round(g(u, "cost_usd") or 0, 8), 0.00587598)
# The silent control: claude's envelope already totals the run. If `last` ever
# became `sum` by accident, a retried envelope would double the bill.
u = U.usage_from(teed(CLAUDE + "\n" + CLAUDE), RTS["claude"])
chk("claude: a repeated envelope is NOT doubled", g(u, "input_tokens"), 2)

print("\n=== silence, and the difference between kinds of silence ===")
chk("a runtime with no usage descriptor reports nothing",
    U.usage_from(teed(CLAUDE), RTS["aider"]), None)
chk("...and neither does an empty row", U.usage_from(teed(CLAUDE), {}), None)
chk("a declared runtime whose transcript has no envelope reports nothing",
    U.usage_from(teed("just prose, no json at all"), RTS["claude"]), None)
chk("a transcript of nothing but torn lines reports nothing",
    U.usage_from('{"type":"resu\n{"broken\n', RTS["claude"]), None)
# The wrong record must not be mistaken for the right one.
chk("codewhale's content events are not read as usage",
    U.usage_from('{"type":"content","content":"x"}', RTS["codewhale"]), None)

print("\n=== instrumentation never breaks a dispatch ===")
for junk in ('{"type":"result","usage":"not-an-object"}',
             '{"type":"result","usage":{"input_tokens":"lots"}}',
             '{"type":"result","usage":{"input_tokens":true}}',
             '[]', '"a bare string"', '{"type":"result"}'):
    try:
        got = U.usage_from(teed(junk), RTS["claude"])
        ok = got is None or isinstance(got, dict)
    except Exception:
        ok = False
    chk(f"malformed record is survived, not raised: {junk[:38]}", ok, True)
# A token count is an int. Python says a bool is an int; a bool is not a count.
chk("a boolean is refused as a token count",
    U.usage_from('{"type":"result","usage":{"input_tokens":true,"output_tokens":9}}',
                 RTS["claude"]), {"output_tokens": 9})

print("\n=== `result` still means what it meant ===")
chk("claude: the envelope's result is lifted, not the JSON blob",
    U.lift_result(teed(CLAUDE), RTS["claude"]), "OK")
# CONFIRMED by probe: codewhale STREAMS the answer in token chunks — a run asked
# to count to twenty emitted 'ele' then 'ven'. Taking the last match would put
# the word "twenty" in the receipt and call it the result.
chk("codewhale: streamed chunks are joined, not truncated to the last",
    U.lift_result(teed(CODEWHALE), RTS["codewhale"]), "eleven")
chk("...and session_capture is not mistaken for content",
    "<transcript>" in (U.lift_result(teed(CODEWHALE), RTS["codewhale"]) or ""), False)
# opencode is the control for that: its `text` part arrives WHOLE, so its row
# takes the last and joining would be wrong.
chk("opencode: a whole text part is taken as-is",
    U.lift_result(teed(OPENCODE), RTS["opencode"]), "eleven")
chk("a runtime with no envelope declares nothing and gets nothing",
    U.lift_result(teed(CLAUDE), RTS["aider"]), None)
chk("...as does a declared runtime whose transcript has no envelope",
    U.lift_result(teed("plain prose"), RTS["claude"]), None)


# ── the receipt, end to end, through the real emitter ───────────────────────
print("\n=== the receipt, written by the real emitter ===")

def plan(name, runtime, transcript, dispatch="inproc", rts=None):
    """A plan far enough along that the emitter will write a receipt."""
    p = LAB / name
    (p / ".smokin" / "dispatch").mkdir(parents=True, exist_ok=True)
    t = p / "tasks" / "T1" / ".smokin"
    t.mkdir(parents=True, exist_ok=True)
    (p / "tasks" / "T1" / "FINDINGS.md").write_text("real findings\n")
    (t / "transcript.log").write_text(transcript)
    (p / ".smokin" / "dispatch" / "T1.json").write_text(json.dumps({
        "run": "rTEST", "seq": "rTEST:T1:1", "task": "T1", "attempt": 1,
        "dispatch": dispatch, "runtime": runtime, "started": "2026-01-01T00:00:00Z",
        "started_ns": 1, "started_epoch": 1, "budget_s": 60}))
    if rts is not None:
        (p / ".smokin" / "runtimes.json").write_text(json.dumps(rts))
    return p


def emit(p, frag='{"terminal":"ok","exit":0}'):
    subprocess.run([sys.executable, str(EMIT), "T1", "test"], input=frag, text=True,
                   capture_output=True, env={"SMOKIN_PLAN": str(p), "PATH": "/usr/bin:/bin"})
    return json.loads((p / "tasks" / "T1" / "RECEIPT.json").read_text())


r = emit(plan("claude", "claude", teed(CLAUDE)))
chk("receipt carries usage", g(g(r, "usage"), "input_tokens"), 2)
chk("...and the schema did NOT move to /2 for an additive key",
    g(r, "schema"), "smokin.receipt/1")
chk("...and `result` is prose, not the envelope", g(r, "result"), "OK")

r = emit(plan("cw", "codewhale", teed(CODEWHALE)))
chk("codewhale receipt carries tokens", g(g(r, "usage"), "output_tokens"), 39)
chk("...and no cost key", "cost_usd" in (g(r, "usage") or {}), False)

# THE SILENT CONTROL FOR THE WHOLE CHANGE. A runtime that declares neither key
# must produce the receipt it produced before this feature existed: no `usage`
# key at all, and `result` still the last twenty transcript lines.
r = emit(plan("undeclared", "demo", "line one\nline two\n",
              rts={"demo": {"headless": "bash demo-agent.sh"}}))
chk("an undeclared runtime gets NO usage key", "usage" in r, False)
chk("...and `result` is still the transcript tail, unchanged",
    g(r, "result"), "line one\nline two")

# ABSENT means the runtime said nothing. It must never mean it said zero.
r = emit(plan("silent", "claude", teed("no envelope here")))
chk("a declared runtime that printed no envelope gets NO usage key",
    "usage" in r, False)

# A pane cannot be measured in v1: its output is on a screen, and the numbers
# live in vendor state directories principle 14 bars this design from reading.
# That is BLINDNESS, not silence, and the receipt must say which.
r = emit(plan("pane", "claude", teed(CLAUDE), dispatch="pane"))
chk("a pane receipt marks usage unavailable rather than omitting it",
    r.get("usage"), {"available": False, "reason": "pane-not-instrumented"})

# A broken runtimes.json must cost the number, never the receipt.
p = plan("broken", "claude", teed(CLAUDE))
(p / ".smokin" / "runtimes.json").write_text("{not json,,,")
r = emit(p)
chk("a broken runtimes.json still yields a receipt", g(r, "terminal"), "ok")
chk("...it just yields no usage", "usage" in r, False)

# And the spend is on the ledger line too, so "what did this run cost" is one
# pass over ledger.jsonl rather than a walk of every task folder.
p = plan("ledger", "claude", teed(CLAUDE))
emit(p)
led = [json.loads(l) for l in (p / ".smokin" / "ledger.jsonl").read_text().splitlines()]
em = [e for e in led if e.get("event") == "emitted"]
chk("the ledger's emitted line carries the spend", g(g(em[0] if em else {}, "usage"), "cost_usd"), 0.1429645)
p = plan("ledger2", "demo", "prose\n", rts={"demo": {"headless": "x"}})
emit(p)
led = [json.loads(l) for l in (p / ".smokin" / "ledger.jsonl").read_text().splitlines()]
em = [e for e in led if e.get("event") == "emitted"]
chk("...and carries no usage key when there was nothing to carry",
    "usage" in em[0], False)


print("\n=== the REAPER is the second path, and it was the easy one to forget ===")
# `result` had the same 20-line fallback in two places. Fixing only the emitter
# would have left a reaped receipt carrying a JSON blob while a cleanly emitted
# one carried prose — the same field meaning two things depending on which path
# wrote it, which is worse than both being wrong.

def reaped(name, runtime, transcript, dispatch="inproc", rts=None):
    """A dispatch that blew its budget and never produced a receipt."""
    q = plan(name, runtime, transcript, dispatch=dispatch, rts=rts)
    (q / "tasks" / "T1" / "FINDINGS.md").unlink()
    d = q / ".smokin" / "dispatch" / "T1.json"
    rec = json.loads(d.read_text())
    rec["budget_s"] = 0                       # long past due
    d.write_text(json.dumps(rec))
    subprocess.run([str(SMOKIN), "reap", str(q)], capture_output=True, text=True)
    return json.loads((q / "tasks" / "T1" / "RECEIPT.json").read_text())

r = reaped("reap-claude", "claude", teed(CLAUDE))
chk("a reaped receipt lifts `result` too, not the envelope", g(r, "result"), "OK")
chk("...and is still terminal=reaped", g(r, "terminal"), "reaped")
# A worker that printed its envelope and then hung spent that money for real.
chk("...and keeps the spend it did report", g(g(r, "usage"), "cost_usd"), 0.1429645)
# The silent control, and the one that matters most here: a run KILLED at its
# budget is the worst possible place to invent a zero.
r = reaped("reap-silent", "claude", teed("printed nothing but prose"))
chk("a reaped worker that reported nothing gets NO usage key", "usage" in r, False)
chk("...and its result is the transcript tail, as it always was",
    (g(r, "result") or "").endswith("trailing prose the agent printed"), True)
r = reaped("reap-undeclared", "demo", "line one\nline two\n",
           rts={"demo": {"headless": "x"}})
chk("an undeclared runtime is reaped exactly as before", "usage" in r, False)
chk("...with the tail unchanged", g(r, "result"), "line one\nline two")
r = reaped("reap-pane", "claude", teed(CLAUDE), dispatch="pane")
chk("a reaped pane says unavailable, not silent",
    g(g(r, "usage"), "reason"), "pane-not-instrumented")


print("\n=== one transcript line must not end the orchestrator ===")
# WRITTEN AFTER THE ADVERSARIAL PASS. `records()` caught `ValueError` only, and
# `json.loads` raises `RecursionError` — a `RuntimeError` — on a deeply nested
# line. It came out of the scanner, out of `reap()` and out of the tick, so ONE
# task's transcript denied every other task in the plan its receipt. Before
# token capture nothing ever parsed a transcript line; this feature is what put
# a parser on the path.
DEEP = '{"a":' * 9998 + "1" + "}" * 9998
chk("the pathological line is well under the scanner's own size bound",
    len(DEEP) < U._MAX_LINE, True)
# GUARDED, because an unguarded call here is the defect under test: it takes
# the whole harness down with it and every check below reports nothing, which
# is how a broken mechanism scores zero failures. Same reason `g()` exists.
def survives(fn):
    try:
        return None, fn()
    except Exception as ex:                                   # noqa: BLE001
        return type(ex).__name__, None


raised, _ = survives(lambda: U.records(teed(CLAUDE, lead=DEEP + "\n"),
                                       {"type": "result"}))
chk("the scanner skips a line it cannot parse, whatever the reason", raised, None)
raised, u = survives(lambda: U.usage_from(teed(CLAUDE, lead=DEEP + "\n"),
                                          RTS["claude"]))
chk("...and still finds the record that was there", g(u, "input_tokens"), 2)

def receipt_of(root, tid):
    """Never `.read_text()` straight into `json.loads`. A mutant that stopped
    writing the receipt made this RAISE and took every check below it with it —
    one failure reported for a mechanism that was entirely gone."""
    try:
        return json.loads((root / "tasks" / tid / "RECEIPT.json").read_text())
    except (OSError, ValueError):
        return {}


# And through both real callers, because a guard in one place is a guard a later
# change can quietly remove from the other. Read back off disk rather than off
# `emit`'s return value: the failure being tested is a receipt that never got
# written, and `emit` parses it unconditionally.
subprocess.run([sys.executable, str(EMIT), "T1", "test"],
               input='{"terminal":"ok","exit":0}', text=True, capture_output=True,
               env={"SMOKIN_PLAN": str(plan("deep-emit", "claude",
                                            teed(CLAUDE, lead=DEEP + "\n"))),
                    "PATH": "/usr/bin:/bin"})
r = receipt_of(LAB / "deep-emit", "T1")
chk("the emitter still writes the worker's receipt", g(r, "terminal"), "ok")
chk("...with the result lifted from the envelope", g(r, "result"), "OK")

# THE ONE THAT MADE IT A BLOCKING FINDING: a HEALTHY second task in the same
# plan got no receipt, because the reap loop died on the first task's file.
q = LAB / "deep-reap"
(q / ".smokin" / "dispatch").mkdir(parents=True)
for tid, tr in (("T1", teed(CLAUDE, lead=DEEP + "\n")), ("T2", teed(CLAUDE))):
    (q / "tasks" / tid / ".smokin").mkdir(parents=True)
    (q / "tasks" / tid / ".smokin" / "transcript.log").write_text(tr)
    (q / ".smokin" / "dispatch" / f"{tid}.json").write_text(json.dumps({
        "run": "rTEST", "seq": f"rTEST:{tid}:1", "task": tid, "attempt": 1,
        "dispatch": "inproc", "runtime": "claude", "started": "2026-01-01T00:00:00Z",
        "started_ns": 1, "started_epoch": 1, "budget_s": 0}))
rr = subprocess.run([str(SMOKIN), "reap", str(q)], capture_output=True, text=True)
chk("the reaper exits 0 with a poisoned transcript in the plan", rr.returncode, 0)
chk("...the poisoned task still becomes a result",
    (q / "tasks" / "T1" / "RECEIPT.json").is_file(), True)
chk("...and so does the healthy task beside it",
    (q / "tasks" / "T2" / "RECEIPT.json").is_file(), True)
chk("...with the healthy one's spend intact",
    g(g(receipt_of(q, "T2"), "usage"), "cost_usd"), 0.1429645)


print("\n=== a count that is not a number is not a reading ===")
# `_number` rejected bools and accepted every other float. `json.loads` maps
# `1e999` to `inf` and accepts bare `NaN`, and `json.dumps` writes both back as
# tokens RFC 8259 does not define — so one hostile usage payload made
# RECEIPT.json and ledger.jsonl unreadable to every parser that is not Python's.
HOSTILE = ('{"type":"result","result":"OK","total_cost_usd":1e999,'
           '"usage":{"input_tokens":1e999,"output_tokens":-5,'
           '"cache_read_input_tokens":NaN,"cache_creation_input_tokens":7}}')
u = U.usage_from(teed(HOSTILE), RTS["claude"])
chk("an infinite token count is absent, not infinite", "input_tokens" in (u or {}), False)
chk("a NaN token count is absent", "cache_read_tokens" in (u or {}), False)
chk("a negative token count is absent — a count does not go below zero",
    "output_tokens" in (u or {}), False)
chk("an infinite cost is absent", "cost_usd" in (u or {}), False)
# The silent control: the readings BESIDE the poison are still reported. Absent
# is per-field, not a whole receipt thrown away over one bad key.
chk("...while the finite reading in the same payload survives",
    g(u, "cache_write_tokens"), 7)

r = emit(plan("hostile", "claude", teed(HOSTILE)))
strict = json.loads((LAB / "hostile" / "tasks" / "T1" / "RECEIPT.json").read_text(),
                    parse_constant=lambda c: (_ for _ in ()).throw(ValueError(c)))
chk("RECEIPT.json parses under a strict RFC-8259 reader", g(strict, "terminal"), "ok")
led = [l for l in (LAB / "hostile" / ".smokin" / "ledger.jsonl").read_text().splitlines()
       if l.strip()]
chk("...and so does every line of the ledger",
    [json.loads(l, parse_constant=lambda c: (_ for _ in ()).throw(ValueError(c)))
     is not None for l in led], [True] * len(led))


print("\n=== a sum whose inputs may be incomplete says so ===")
# `select: last` reads one record and a dropped line cannot move its answer. A
# SUM loses a whole step per dropped line and is biased in one direction, and
# the receipt carried a confident low number with nothing beside it. The tee
# race in smokin-run:60-62 is a real and expected source of torn lines.
STEP = ('{"type":"step_finish","part":{"id":"prt_x","type":"step-finish",'
        '"tokens":{"input":1000,"output":2,"cache":{"read":0,"write":0},'
        '"reasoning":0},"cost":0.001}}')
clean = "\n".join([STEP] * 3) + "\n"
torn = STEP + "\n" + '{"type":"step_fin' + STEP + "\n" + STEP + "\n"
u_clean = U.usage_from(clean, RTS["opencode"])
u_torn = U.usage_from(torn, RTS["opencode"])
chk("the clean sum is the whole run", g(u_clean, "input_tokens"), 3000)
chk("...and says nothing, because nothing was dropped",
    "dropped_records" in (u_clean or {}), False)
chk("the torn sum is short by exactly one step", g(u_torn, "input_tokens"), 2000)
chk("...and the receipt can no longer pretend otherwise",
    g(u_torn, "dropped_records"), 1)
# The control on the other select mode: `last` is unaffected and stays silent.
chk("a `select: last` runtime gains no such key from the same torn transcript",
    "dropped_records" in (U.usage_from(teed(CLAUDE), RTS["claude"]) or {}), False)


print("\n=== the shipped table is a real config, not prose ===")
# The template is the file every REAL plan falls back to, and the tests all ship
# their own — so it is the one thing nothing loaded. It crashed `doctor` once
# for exactly that reason. Not again.
tbl = U.load_runtimes([ROOT / "templates" / "runtimes.json"], strict=True)
chk("templates/runtimes.json loads and drops the _comment list",
    "_comment" in tbl, False)
chk("...with every runtime still present", sorted(tbl), 
    ["aider", "claude", "codewhale", "codex", "opencode"])
# launch() builds argv as `head.split()`. A flag whose VALUE contains a space
# would arrive as two argv entries and the vendor would reject the second.
for name, row in tbl.items():
    for f in ("headless", "judge", "pane"):
        s = row.get(f)
        if s:
            chk(f"{name}.{f} is whitespace-safe for head.split()",
                " ".join(s.split()), s)
# Three rows gained the flags, and only three. codex is not installed and aider
# is untested, so declaring a shape for either would be an assertion nobody
# exercised — the defect class this tool exists to catch.
chk("exactly three runtimes declare usage",
    sorted(k for k, v in tbl.items() if v.get("usage")),
    ["claude", "codewhale", "opencode"])
chk("...and the unexercised ones declare none",
    any(tbl[k].get("usage") or tbl[k].get("result_from") for k in ("codex", "aider")),
    False)
chk("cost is declared only where a vendor reports one",
    sorted(k for k, v in tbl.items() if (v.get("usage") or {}).get("cost_usd")),
    ["claude", "opencode"])
# A strict loader refuses a broken table; a lenient one never refuses anything.
bad = LAB / "bad.json"
bad.write_text("{oops")
try:
    U.load_runtimes([bad], strict=True)
    chk("strict load refuses a broken table", False, True)
except SystemExit:
    chk("strict load refuses a broken table", True, True)
chk("...and the lenient load the emitter uses never refuses",
    U.load_runtimes([bad]), {})


print("\n=== the whole feature is inert on a plan that never asked for it ===")
# The negative control. A demo plan whose runtime declares neither key must tick
# exactly as it did before this existed.
p = LAB / "inert"
(p / "tasks" / "T1").mkdir(parents=True)
(p / ".smokin").mkdir(parents=True)
shutil.copy(ROOT / "examples" / "demo-plan" / "demo-agent.sh", p / "demo-agent.sh")
(p / ".smokin" / "runtimes.json").write_text('{"demo":{"headless":"bash demo-agent.sh"}}')
(p / "tasks" / "T1" / "TASK.md").write_text(
    "# T1\n\n**Status:** NOT STARTED\n**Owner:** w\n"
    "**Blocked by:** — · **Blocks:** —\n"
    "**Dispatch:** inproc · **Runtime:** `demo`\n"
    "**Budget:** 60 · **Interrupt:** no · **Watch:** no\n\n"
    "## What you own\n`tasks/T1/`\n\n## Steps\n1. work\n\n"
    "## Done means\n```\ntest -s tasks/T1/FINDINGS.md\n```\n\n## Do NOT\n- Do NOT stray.\n")
(p / "PLAN.md").write_text("# plan\n\n| ID | Task | Blocked by |\n|---|---|---|\n| T1 | a | — |\n")
rc = subprocess.run([str(SMOKIN), "run", str(p), "--interval", "1", "--max-ticks", "10"],
                    capture_output=True, text=True)
chk("a plan with no declared usage completes as before", rc.returncode, 0)
r = json.loads((p / "tasks" / "T1" / "RECEIPT.json").read_text())
chk("...its receipt has no usage key", "usage" in r, False)
chk("...and its result is the transcript tail it always was",
    g(r, "result").endswith("T1 complete"), True)
chk("...and its verdict still passed",
    json.loads((p / "tasks" / "T1" / "VERDICT.json").read_text())["pass"], True)

print(f"\n{'ALL PASS' if not fails else str(fails) + ' FAILED'}  ({LAB})")
if not fails:
    shutil.rmtree(LAB, ignore_errors=True)
sys.exit(1 if fails else 0)

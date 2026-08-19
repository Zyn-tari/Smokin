"""
smokin_usage — what a run cost, read from what the runtime already printed.

THE INCIDENT. An operator watched six agents sit idle, each holding exactly the
context the next task needed, and opened a seventh pane. Context that cost real
tokens to build was thrown away. The obvious question — "does reusing an agent
save anything?" — turned out to be unanswerable, because nothing in the plan
directory records what a dispatch spent. The ledger has events and timestamps,
so wall-clock, retries and first-pass verdict rate were already derivable. Spend
was not. This module is the missing reading.

WHAT IT REFUSES TO DO. It never reads a vendor state directory. The numbers are
in ~/.claude/projects/*.jsonl and ~/.local/share/opencode/opencode.db, and taking
them from there would be easier and would break principle 14 the same way
`smokin-run`:61 already refuses to break it — a pointer to ~/.claude is not
reconstructable from the repository. So the only source here is the transcript
the wrapper already tees into the task folder. That buys one hard limit, stated
rather than hidden: PANES CAPTURE NOTHING in v1, because a pane's output is on a
screen and not in the transcript. The receipt says so out loud instead of
looking like a runtime that reported zero.

WHY THE TICK STILL HAS NO VENDOR BRANCH. Three runtimes print three different
shapes. If that difference lived in an `if runtime == "codewhale"` the whole
design claim — a runtime is a row, not a code path — would be forfeit for one
number. So the shape is DATA, declared in runtimes.json beside the flags that
produce it (DESIGN §4c: the only file that knows a vendor's flags), and this
module is one scanner that reads the declaration.

WHY IT SCANS AND NEVER SLICES. `smokin-run` runs two `tee` processes, one on
stdout and one on stderr, racing to append to the same file. CONFIRMED by probe:
a child that printed stdout first had its stderr line recorded first. "The last
line" and "the first line" of a transcript are therefore both unsafe. Every line
is tried; the last one that matches wins. A line that does not parse is skipped
in silence, because a torn interleaved write and a vendor banner are
indistinguishable from here and neither is a defect worth a log line.
"""
import json
import math

# Only lines that look like a JSON object are worth a parse attempt. The
# transcript is mostly agent prose, and json.loads on every line of a large
# transcript is how a 2-second emitter budget gets spent on nothing.
_MAX_LINE = 1 << 20


def dig(obj, path: str):
    """Resolve a dotted path against nested dicts. Any miss returns None.

    Paths are resolved from the RECORD ROOT, not from a `usage_path` prefix.
    That is a deliberate departure from the shape triage sketched, and the
    reason is claude: its tokens are at `usage.input_tokens` and its cost is at
    top-level `total_cost_usd`. No single prefix addresses both, and a
    descriptor that needs an escape hatch for its own first runtime is the
    wrong descriptor.
    """
    cur = obj
    for part in path.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
    return cur


def _matches(rec, want) -> bool:
    if not isinstance(rec, dict):
        return False
    for k, v in (want or {}).items():
        if rec.get(k) != v:
            return False
    return True


def scan(text: str, want):
    """Every JSON object in the transcript matching `want`, in file order, and
    the number of object-shaped lines that could not be parsed.

    This is the one primitive. `result` and `usage` are different readings of
    the same scan, which is why there is no second implementation of it.

    EVERY EXCEPTION, NOT `ValueError`. `json.loads` raises `RecursionError` on a
    deeply nested line — CONFIRMED, 9998 levels of `{"a":` in 59989 bytes, well
    under `_MAX_LINE` — and `RecursionError` is a `RuntimeError`, so a
    `except ValueError` let it out of the scanner, out of `reap()` and out of
    the tick. One transcript line ended the orchestrator for every OTHER task
    in the plan. A line this scanner cannot read is a line it skips; that was
    always the rule, and the narrow except was the rule not being implemented.

    THE DROP COUNT IS RETURNED, NOT LOGGED. `select: sum` adds one number per
    matching record, so a dropped record silently SUBTRACTS from the total and
    the receipt carries a confident, low number with nothing beside it to say
    so. The tee race in `smokin-run`:60-62 is a real and expected source of
    torn lines. A sum whose inputs may be incomplete has to be able to say so,
    the same way the pane path says `available: false` rather than reporting
    blindness as zero.
    """
    out, dropped = [], 0
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("{") or len(line) > _MAX_LINE:
            continue
        try:
            rec = json.loads(line)
        except Exception:
            dropped += 1                  # torn write or banner. Not a defect.
            continue
        if _matches(rec, want):
            out.append(rec)
    return out, dropped


def records(text: str, want):
    """`scan`, for the callers that do not care how many lines were unreadable."""
    return scan(text, want)[0]


def lift_result(text: str, row: dict):
    """The final assistant text, lifted out of a runtime's JSON envelope.

    THIS EXISTS BECAUSE OF A BUG THE FLAG CHANGE WOULD OTHERWISE CREATE. Two
    places fell back to the last 20 transcript lines when a fragment carried no
    `result`: the emitter and the reaper. The moment claude gains
    `--output-format json`, those 20 lines ARE the JSON envelope, and the
    receipt's most-read field starts carrying a machine blob where prose used
    to be. Both callers now come through here first.

    Returns None when the runtime declares no envelope or none was found, and
    the caller keeps its existing tail behaviour unchanged. That is what makes
    this inert for every runtime that did not change — the silent control.
    """
    spec = (row or {}).get("result_from")
    if not isinstance(spec, dict):
        return None
    path = spec.get("path")
    if not isinstance(path, str) or not path:
        return None
    hits = records(text, spec.get("match"))
    if not hits:
        return None
    if spec.get("select") == "join":
        # CODEWHALE STREAMS THE ANSWER IN TOKEN CHUNKS, CONFIRMED by probe: a
        # run asked to count to twenty emitted `content` events reading 'ele'
        # then 'ven'. Taking the last match there would put the word "twenty"
        # in the receipt and call it the result. opencode is the control — its
        # `text` part arrived WHOLE, one event of 131 chars — which is why that
        # row takes the last and this branch is not the default.
        # Order is file order, which for a single stdout stream is emission
        # order; the tee race reorders stdout against STDERR, not stdout
        # against itself.
        parts = [dig(h, path) for h in hits]
        joined = "".join(p for p in parts if isinstance(p, str))
        return joined or None
    val = dig(hits[-1], path)
    return val if isinstance(val, str) and val else None


def _number(v):
    """A token count is a finite, non-negative number. A bool is an int in
    Python and is not a count.

    `Infinity`, `-Infinity` and `NaN` are all accepted by `json.loads` on INPUT
    — `1e999` parses to `inf` — and `json.dumps` writes them back out as the
    bare tokens `Infinity` and `NaN`, which RFC 8259 does not allow. A single
    hostile or broken transcript line therefore made RECEIPT.json and
    ledger.jsonl unreadable to every parser that is not Python's, CONFIRMED
    against `node -e JSON.parse`. A count that is not a finite non-negative
    number is not a reading, and absent is this module's own honest answer for
    a reading it does not have."""
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    if not math.isfinite(v) or v < 0:
        return None
    return v


def usage_from(text: str, row: dict):
    """Tokens, and cost only if the runtime actually reported one.

    TOKENS AND COST ARE NOT ONE CAPABILITY, and collapsing them is how an
    average gets poisoned. claude reports both. opencode reports both. codewhale
    reports tokens and NO cost anywhere — CONFIRMED twice, including one run
    with real tool use. A single `cost_usd` key would therefore be null for
    codewhale forever, and the only way to fill it would be a price table this
    repository would have to invent. Inventing one is exactly the unearned
    assertion CONTRIBUTING refuses. So when a runtime reports no cost, the key
    is ABSENT — not null, and above all not zero. An absent number and a zero
    are different facts and a zero survives every later `sum()`.

    Returns a dict of what was found, or None when nothing was. None means the
    runtime said nothing; it never means it said zero.
    """
    spec = (row or {}).get("usage")
    if not isinstance(spec, dict):
        return None
    mapping = spec.get("map")
    if not isinstance(mapping, dict):
        return None

    hits, dropped = scan(text, spec.get("match"))
    if not hits:
        return None

    paths = dict(mapping)
    cost_path = spec.get("cost_usd")
    if isinstance(cost_path, str) and cost_path:
        paths["cost_usd"] = cost_path

    out = {}
    if spec.get("select") == "sum":
        # Runtimes that report per-step rather than per-run. Summing is right
        # here and wrong for the others: claude's envelope already totals the
        # run, and summing a repeated total would double it.
        for name, path in paths.items():
            vals = [_number(dig(h, path)) for h in hits]
            vals = [v for v in vals if v is not None]
            if vals:
                out[name] = round(sum(vals), 10) if name == "cost_usd" else sum(vals)
        # ONLY on the summing path, and only when something was actually
        # dropped. `select: last` reads one record and a dropped line cannot
        # move its answer; a sum loses a whole step per dropped line and is
        # biased in one direction. The key is absent when the scan was clean,
        # so a receipt that carries it is a receipt saying its own number is a
        # floor.
        if out and dropped:
            out["dropped_records"] = dropped
    else:
        for name, path in paths.items():
            v = _number(dig(hits[-1], path))
            if v is not None:
                out[name] = v

    return out or None


def load_runtimes(candidates, strict=False):
    """The capability table, from the first candidate path that exists.

    ONE loader, because there are now two readers. `smokin` needs it to launch
    and `smokin-emit` needs it to know what shape the transcript is in, and two
    copies of this would drift the day someone adds a key to one of them.

    `strict` is the only difference between the callers, and it is not
    cosmetic: `smokin` refuses to run against a broken table, because launching
    with a half-read one is how a task silently dispatches as
    "no-headless-mode". The emitter must never refuse anything — a receipt
    withheld because a JSON file had a trailing comma is a worker whose work
    is lost, and the missing usage number is the cheaper loss by far.
    """
    for p in candidates:
        try:
            if not p.is_file():
                continue
            raw = json.loads(p.read_text())
        except OSError:
            continue
        except ValueError as e:
            if strict:
                raise SystemExit(f"smokin: {p} is not valid JSON — {e}")
            return {}
        if not isinstance(raw, dict):
            if strict:
                raise SystemExit(f"smokin: {p} must be an object of runtime rows")
            return {}
        # The shipped template carries a `_comment` key whose value is a LIST,
        # and `doctor` walked every key and crashed on it.
        return {k: v for k, v in raw.items() if isinstance(v, dict)}
    return {}

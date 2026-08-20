#!/usr/bin/env bash
# Smokin's calibration harness.
#
# Grillin's OPERATING-THE-PLAN.md §5 says: anything producing evidence other
# work depends on is an instrument, and an instrument is proven against a known
# answer BEFORE the measurements it authorises. Smokin is such an instrument.
# This is its known answer.
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SMOKIN="$ROOT/bin/smokin"
LAB="${TMPDIR:-/tmp}/smokin-tests.$$"
pass=0; fail=0

ok()   { pass=$((pass+1)); printf '  \033[32mPASS\033[0m  %s\n' "$1"; }
bad()  { fail=$((fail+1)); printf '  \033[31mFAIL\033[0m  %s — %s\n' "$1" "$2"; }
chk()  { if [ "$2" = "$3" ]; then ok "$1"; else bad "$1" "want '$3', got '$2'"; fi; }
# The GREEN token, not the word. `grep -c PASS` also counts a check whose LABEL
# contains "PASS" — three sub-harnesses have one ("...the summary AGREES", the
# verdict lines) and each was reporting one check more than it ran. A harness
# that overstates its own count is the same defect as prose that overstates,
# and it is the number this file exists to be trusted about.
count_pass() { grep -c "$(printf '\033')\[32mPASS" "$1"; }

newplan() { # $1 = dir, $2 = budget
  rm -rf "$1"; mkdir -p "$1"/{tasks/{T1,T2},.smokin}
  cp "$ROOT/examples/demo-plan/demo-agent.sh" "$1/"
  printf '{"demo":{"headless":"bash demo-agent.sh"}}\n' > "$1/.smokin/runtimes.json"
  for t in T1 T2; do
    b="$1/tasks/$t"; mkdir -p "$b"
    { echo "# $t — test"; echo
      echo "**Status:** NOT STARTED"
      echo "**Owner:** worker-$t"
      if [ "$t" = T1 ]; then echo "**Blocked by:** — · **Blocks:** T2"
      else echo "**Blocked by:** T1 · **Blocks:** —"; fi
      echo "**Dispatch:** inproc · **Runtime:** \`demo\`"
      echo "**Budget:** ${2:-60} · **Interrupt:** no · **Watch:** no"
      echo; echo "## What you own"; echo "\`tasks/$t/\`"
      echo; echo "## Steps"; echo "1. work"
      echo; echo "## Done means"; echo '```'; echo "test -s tasks/$t/FINDINGS.md"; echo '```'
      echo; echo "## Do NOT"; echo "- Do NOT stray."
    } > "$b/TASK.md"
  done
  printf '# plan\n\n| ID | Task | Blocked by |\n|---|---|---|\n| T1 | a | — |\n| T2 | b | T1 |\n' > "$1/PLAN.md"
}

echo "Smokin — calibration"
echo

# ── 1 · the happy path ──────────────────────────────────────────────────────
P="$LAB/happy"; newplan "$P" 60
"$SMOKIN" run "$P" --interval 1 --max-ticks 10 >/dev/null 2>&1; rc=$?
chk "happy path completes"            "$rc" "0"
chk "T1 verdict passed"               "$(python3 -c "import json;print(json.load(open('$P/tasks/T1/VERDICT.json'))['pass'])" 2>/dev/null)" "True"
chk "T2 ran only after T1 verified"   "$(python3 -c "import json;print(json.load(open('$P/tasks/T2/RECEIPT.json'))['claim'])" 2>/dev/null)" "done"
chk "PROGRESS.md rendered"            "$([ -s "$P/PROGRESS.md" ] && echo yes)" "yes"
chk "STATUS.json rendered"            "$([ -s "$P/STATUS.json" ] && echo yes)" "yes"

# ── 2 · the claim the whole design rests on ─────────────────────────────────
# kill -9 the worker mid-flight. No orchestrator is alive to notice. A LATER,
# COMPLETELY SEPARATE process must recover the same picture from disk alone.
P="$LAB/crash"; newplan "$P" 3
"$SMOKIN" tick "$P" >/dev/null 2>&1
pkill -9 -f "demo-agent.sh" 2>/dev/null
sleep 4
"$SMOKIN" tick "$P" >/dev/null 2>&1
term="$(python3 -c "import json;print(json.load(open('$P/tasks/T1/RECEIPT.json'))['terminal'])" 2>/dev/null)"
chk "killed worker is reaped, not lost"  "$term" "reaped"
chk "a missing receipt became a result"  "$([ -f "$P/tasks/T1/VERDICT.json" ] && echo yes)" "yes"

# ── 3 · idempotency ─────────────────────────────────────────────────────────
P="$LAB/idem"; newplan "$P" 60
"$SMOKIN" run "$P" --interval 1 --max-ticks 10 >/dev/null 2>&1
before="$(sha1sum "$P/STATUS.json" | cut -d' ' -f1)"
r1="$("$SMOKIN" tick "$P" 2>&1)"; r2="$("$SMOKIN" tick "$P" 2>&1)"
chk "re-ticking a finished plan is a no-op" "$(echo "$r1" | grep -c 'dispatch ')" "0"
chk "no duplicate dispatch on re-tick"      "$(echo "$r2" | grep -c 'dispatch ')" "0"

# ── 4 · two ticks racing ────────────────────────────────────────────────────
# The invariant is NOT "the second one declines" — either may win the race.
# It is: across both, T1 is dispatched exactly once. An earlier version of this
# test asserted a line count and failed 1 run in 3 because a tick that wins
# prints both "dispatch T1" and "1 in flight". A flaky test is worse than none.
P="$LAB/lock"; newplan "$P" 60
"$SMOKIN" tick "$P" > "$LAB/a.txt" 2>&1 &
"$SMOKIN" tick "$P" > "$LAB/b.txt" 2>&1 &
wait
chk "two racing ticks dispatch exactly once" \
    "$(cat "$LAB/a.txt" "$LAB/b.txt" | grep -c 'dispatch ')" "1"
# The previous assertion here counted the loser's message across those two runs.
# That is not an invariant, it is an observation of a race — on a fast machine
# the first tick finishes before the second starts, nobody loses, and a correct
# tool fails its own test. It failed exactly that way on a server while passing
# here. Hold the lock deliberately instead, so the branch is exercised every run.
P="$LAB/held"; newplan "$P" 60
mkdir -p "$P/.smokin"
python3 - "$P/.smokin/tick.lock" <<'PY' &
import fcntl, sys, time
f = open(sys.argv[1], "w")
fcntl.flock(f, fcntl.LOCK_EX)
time.sleep(4)
PY
holder=$!
sleep 1
"$SMOKIN" tick "$P" > "$LAB/c.txt" 2>&1
chk "a tick that cannot get the lock declines"        "$?" "0"
chk "...and says so rather than failing silently" \
    "$(grep -c 'another tick holds the lock' "$LAB/c.txt")" "1"
chk "...and dispatches nothing while locked out" \
    "$(grep -c 'dispatch ' "$LAB/c.txt")" "0"
wait "$holder" 2>/dev/null

# ── 5 · the emitter's mutex ─────────────────────────────────────────────────
P="$LAB/dup"; newplan "$P" 60
"$SMOKIN" run "$P" --interval 1 --max-ticks 10 >/dev/null 2>&1
first="$(sha1sum "$P/tasks/T1/RECEIPT.json" | cut -d' ' -f1)"
SMOKIN_PLAN="$P" printf '{"terminal":"ok","exit":0}' | \
  SMOKIN_PLAN="$P" "$ROOT/bin/smokin-emit" T1 second-writer >/dev/null 2>&1
after="$(sha1sum "$P/tasks/T1/RECEIPT.json" | cut -d' ' -f1)"
chk "a duplicate emit cannot overwrite"  "$after" "$first"
chk "and it is recorded, not silent"     "$(grep -c duplicate-emit "$P/.smokin/ledger.jsonl" 2>/dev/null)" "1"

# ── 6 · the receipt is not the gate ─────────────────────────────────────────
P="$LAB/liar"; newplan "$P" 60
"$SMOKIN" tick "$P" >/dev/null 2>&1
pkill -9 -f "demo-agent.sh" 2>/dev/null; sleep 1
: > "$P/tasks/T1/FINDINGS.md"                       # zero bytes: a lie
printf '{"terminal":"ok","exit":0}' | SMOKIN_PLAN="$P" "$ROOT/bin/smokin-emit" T1 liar >/dev/null 2>&1
"$SMOKIN" tick "$P" >/dev/null 2>&1
v="$(python3 -c "import json;print(json.load(open('$P/tasks/T1/VERDICT.json'))['pass'])" 2>/dev/null)"
chk "an agent claiming done is refuted by the gate" "$v" "False"

# ── 6b · doctor on the path every REAL plan takes ───────────────────────────
# A plan with no .smokin/runtimes.json falls back to the shipped template. Every
# test above ships its own, so that fallback was the one branch nothing ran — and
# it crashed on the template's own `_comment` key. Found on a server, not here.
P="$LAB/nortsjson"; rm -rf "$P"; mkdir -p "$P/tasks"
"$SMOKIN" doctor "$P" >/dev/null 2>&1
chk "doctor works on a plan with no local runtimes.json" "$?" "0"
n="$("$SMOKIN" doctor "$P" 2>/dev/null | grep -c '^runtime ')"
chk "...and reports the shipped runtimes, not the comment" "$([ "$n" -ge 4 ] && echo yes)" "yes"

# ── 6b2 · ONE task, no plan around it ───────────────────────────────────────
# The precondition used to be a plan directory, and that precondition was the
# reason `verify` went unused: the thing worth having at n=1 was gated behind
# authoring a plan first. A lone TASK.md is enough to re-run a done-command.
P="$LAB/lone/T1"; rm -rf "$LAB/lone"; mkdir -p "$P"
{ echo "# T1 — a lone task"; echo
  echo "**Status:** DONE"; echo "**Owner:** you"; echo
  echo "## What you own"; echo '`.`'; echo
  echo "## Steps"; echo "1. work"; echo
  echo "## Done means"; echo '```'; echo "test -s FINDINGS.md"; echo '```'; echo
  echo "## Do NOT"; echo "- Do NOT stray."
} > "$P/TASK.md"

"$SMOKIN" verify "$P" >/dev/null 2>&1
chk "a lone TASK.md can be verified — no plan needed"    "$?" "1"
chk "...and the agent's empty claim is REFUTED" \
    "$(python3 -c "import json;print(json.load(open('$P/VERDICT.json'))['pass'])" 2>/dev/null)" "False"

printf 'real findings\n' > "$P/FINDINGS.md"
out="$("$SMOKIN" verify "$P/TASK.md" 2>&1)"; rc=$?
chk "...pointing straight at the TASK.md works too"      "$rc" "0"
# The verdict was written to the task dir and counted from root/tasks/<id>/ —
# the same path in a plan, a different one here. It printed PASS then 0 of 1.
chk "...and the summary AGREES with the verdict" \
    "$(echo "$out" | grep -c '1 of 1 verified')" "1"
chk "a lone task cannot be ticked, and says so" \
    "$("$SMOKIN" tick "$P" 2>&1 | grep -c 'single task, not a plan')" "1"

# ── 6b3 · the hook that fires verify when an agent says done ────────────────
# The hook is the adoption mechanism, so a hook that silently does nothing is
# the whole feature failing quietly. Both directions, plus the two ways it is
# allowed to stay silent.
HOOK="$ROOT/templates/verify-on-stop.sh"
export PATH="$ROOT/bin:$PATH"
rm -f "$P/FINDINGS.md" "$P/VERDICT.json"
o="$(cd "$P" && echo '{}' | bash "$HOOK" 2>/dev/null)"
chk "hook reports a refuted claim"      "$(echo "$o" | grep -c 'REFUTED')" "1"
printf 'real\n' > "$P/FINDINGS.md"
o="$(cd "$P" && echo '{}' | bash "$HOOK" 2>/dev/null)"
chk "hook reports a surviving claim"    "$(echo "$o" | grep -c '1 of 1 verified')" "1"
o="$(cd "$P" && echo '{}' | SMOKIN_VERIFY_ON_STOP=0 bash "$HOOK" 2>/dev/null)"
chk "hook can be switched off"          "$(printf '%s' "$o" | wc -c)" "0"
o="$(cd "$LAB" && echo '{}' | bash "$HOOK" 2>/dev/null)"
chk "hook is silent where there is nothing to verify" "$(printf '%s' "$o" | wc -c)" "0"
# Never non-zero. A Stop hook that exits non-zero is a session that cannot end.
(cd "$P" && echo '{}' | bash "$HOOK" >/dev/null 2>&1)
chk "hook always exits 0"               "$?" "0"

# ── 6c · verify, the tick with the fleet removed ────────────────────────────
echo
if python3 "$ROOT/tests/test-verify.py" > "$LAB/verify.out" 2>&1; then
  ok "verify: $(grep -c PASS "$LAB/verify.out") checks"
else
  bad "verify" "see below"; cat "$LAB/verify.out"
fi

# ── 7 · the delegation node ─────────────────────────────────────────────────
# Its own harness, because it mutates six named failure modes rather than
# walking a happy path. Run here so one command still covers the whole tool.
echo
if python3 "$ROOT/tests/test-rulings.py" > "$LAB/rulings.out" 2>&1; then
  n=$(count_pass "$LAB/rulings.out")
  ok "delegation node: $n ruling checks"
else
  bad "delegation node" "see below"
  cat "$LAB/rulings.out"
fi

# ── 8 · plan-level invariants ───────────────────────────────────────────────
# Everything above measures COMPLETION — did the task finish, was the claim
# true. Nothing above measures BLAST RADIUS: what a task broke on its way to
# passing its own gate. Same harness shape as 7, because the claim is the same
# kind of claim and deserves the same kind of proof.
echo
if python3 "$ROOT/tests/test-invariants.py" > "$LAB/invariants.out" 2>&1; then
  n=$(count_pass "$LAB/invariants.out")
  ok "plan invariants: $n blast-radius checks"
else
  bad "plan invariants" "see below"
  cat "$LAB/invariants.out"
fi

# ── 9 · token capture ───────────────────────────────────────────────────────
# Sections 1-8 measure whether the work FINISHED and whether the claim was
# TRUE. None of them measures what it SPENT — which is why "does reusing an
# agent's context save anything" had no answer when six idle agents were
# abandoned for a seventh pane. Own harness, because the claim is about three
# real vendors' output and is mutation-proven against the parser, the
# descriptor table and the receipt separately.
echo
if python3 "$ROOT/tests/test-usage.py" > "$LAB/usage.out" 2>&1; then
  n=$(count_pass "$LAB/usage.out")
  ok "token capture: $n spend checks"
else
  bad "token capture" "see below"
  cat "$LAB/usage.out"
fi

# ── 10 · pane reuse, and who is allowed it ──────────────────────────────────
# Section 9 measures what a dispatch SPENT. It cannot measure the waste the
# operator actually watched, because that waste happens in panes and the
# headless path is the only one instrumented. This is the other half: the six
# idle agents holding context, and the seventh pane. Own harness, because the
# load-bearing claim is a REFUSAL — the adversarial pass must be denied a pane
# it would otherwise have been handed — and a refusal is only proved by a
# control that shows the identical plan being allowed it.
echo
if python3 "$ROOT/tests/test-reuse.py" > "$LAB/reuse.out" 2>&1; then
  n=$(count_pass "$LAB/reuse.out")
  ok "pane reuse: $n identity and containment checks"
else
  bad "pane reuse" "see below"
  cat "$LAB/reuse.out"
fi

# ── 11 · agent memory ───────────────────────────────────────────────────────
# Section 10 keeps a context alive across a task boundary — but only while the
# pane exists, only inside one run, and never on the headless path, where a
# fresh subprocess per task is where containment comes from. This is what
# survives the process instead: not the context, which is not reconstructable,
# but an observation and the command that produced it. Own harness, because the
# load-bearing claim is again a REFUSAL — an entry with no command behind it is
# not stored — and because the mechanism puts words in front of a worker, which
# nothing else in this tool does.
echo
if python3 "$ROOT/tests/test-memory.py" > "$LAB/memory.out" 2>&1; then
  n=$(count_pass "$LAB/memory.out")
  ok "agent memory: $n provenance and recall checks"
else
  bad "agent memory" "see below"
  cat "$LAB/memory.out"
fi

# CONTINUITY. Two case studies of a real repository used `smokin verify` and
# never once ran the dispatch half — so this asks the question those studies
# could not: can an operator start it and walk away. It is also the only harness
# here that reads GRILLIN's source, because who counts as a person is Grillin's
# decision and two definitions would eventually disagree.
echo
if python3 "$ROOT/tests/test-continuity.py" > "$LAB/continuity.out" 2>&1; then
  n=$(count_pass "$LAB/continuity.out")
  ok "continuity: $n checks on running to a stop"
else
  bad "continuity" "see below"
  cat "$LAB/continuity.out"
fi

echo
echo "  $pass passed, $fail failed"
rm -rf "$LAB"
[ "$fail" -eq 0 ]

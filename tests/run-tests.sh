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
  n=$(grep -c 'PASS' "$LAB/rulings.out")
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
  n=$(grep -c 'PASS' "$LAB/invariants.out")
  ok "plan invariants: $n blast-radius checks"
else
  bad "plan invariants" "see below"
  cat "$LAB/invariants.out"
fi

echo
echo "  $pass passed, $fail failed"
rm -rf "$LAB"
[ "$fail" -eq 0 ]

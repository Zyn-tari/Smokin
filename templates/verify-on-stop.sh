#!/usr/bin/env bash
# verify-on-stop.sh — re-run the gate the moment an agent says it is finished.
#
# WHY THIS EXISTS. Across five trials and five real jobs, one pattern held: the
# planning gate got run and `smokin verify` did not. The difference was never
# the idea — people who had never read the README re-invented "check the claim
# with something that did not do the work" on their own. The difference was that
# the gate has a pre-commit hook putting it IN THE PATH, and verify was a command
# you had to remember at the exact moment the tempting alternative is to glance
# at the output and believe it.
#
# So: tools get run when they are in the path, not when they are on the shelf.
# This is verify's hook. It fires on Stop — the moment the agent claims done —
# and re-runs each task's own done-command itself.
#
# WHAT IT WILL NOT DO. It does not block, it does not edit your TASK.md, it does
# not start anything, and it always exits 0. A hook that can wedge a session is
# worse than no hook: it gets deleted, and it takes the useful part with it.
# See "MAKING IT BLOCK" at the foot of this file if you want teeth, and read the
# loop warning there first.
#
# INSTALL — in your settings.json (see hooks.json.template):
#   "Stop": [{ "hooks": [{ "type": "command",
#              "command": "~/.claude/hooks/verify-on-stop.sh" }] }]
#
# TUNING, by environment variable:
#   SMOKIN_VERIFY_ON_STOP=0   turn it off without unwiring it
#   SMOKIN_PLAN=<dir>         verify this, instead of searching upward from cwd
#   SMOKIN_VERIFY_TIMEOUT=60  seconds before it gives up (default 60)
set -uo pipefail

[ "${SMOKIN_VERIFY_ON_STOP:-1}" = "0" ] && exit 0
command -v smokin >/dev/null 2>&1 || exit 0

# Consume stdin so the caller never blocks on a full pipe, even though we do not
# need the payload. A hook that stalls the session is the failure above.
cat >/dev/null 2>&1 || true

# ── find something to verify ────────────────────────────────────────────────
# A lone TASK.md counts. That is the whole point of dropping the precondition:
# the moment worth checking is usually one delegated task, not a plan.
target="${SMOKIN_PLAN:-}"
if [ -z "$target" ]; then
  d="$PWD"
  # Test the directory BEFORE deciding to stop. A walk that breaks on reaching
  # the root without testing it never checks the root — Grillin's own pre-commit
  # hook shipped that bug and a plan at the repository root went ungated.
  while true; do
    if [ -d "$d/tasks" ] || [ -f "$d/TASK.md" ]; then target="$d"; break; fi
    [ "$d" = "/" ] || [ -z "$d" ] && break
    d="$(dirname "$d")"
  done
fi
[ -n "$target" ] || exit 0

# ── run it ──────────────────────────────────────────────────────────────────
t="${SMOKIN_VERIFY_TIMEOUT:-60}"
if command -v timeout >/dev/null 2>&1; then
  out="$(timeout "$t" smokin verify "$target" 2>&1)"; rc=$?
else
  out="$(smokin verify "$target" 2>&1)"; rc=$?
fi

# 124 is timeout's. Say so rather than reporting a pass that never happened —
# silence that resembles success is the thing this whole tool is against.
if [ "$rc" = "124" ]; then
  printf '{"systemMessage":"smokin verify: gave up after %ss. Raise SMOKIN_VERIFY_TIMEOUT, or the done-commands are doing more than checking."}\n' "$t"
  exit 0
fi

# Nothing to say when there was nothing to check.
printf '%s' "$out" | grep -q 'verdict' || exit 0

refuted="$(printf '%s\n' "$out" | grep -c 'REFUTED' || true)"
tally="$(printf '%s\n' "$out" | grep -m1 'verified' || true)"

# Only ever emit characters we chose. The output contains task ids and a count;
# it must not be able to break out of the JSON string it is being put inside.
clean() { printf '%s' "$1" | tr -cd 'A-Za-z0-9 ,.:_/·—-' | cut -c1-300; }

if [ "${refuted:-0}" -gt 0 ]; then
  names="$(printf '%s\n' "$out" | awk '/REFUTED/{printf "%s ", $2}')"
  printf '{"systemMessage":"⚠ smokin verify: %s REFUTED — %s. The claim of done did not survive re-running the task'"'"'s own done-command."}\n' \
    "$(clean "$refuted")" "$(clean "$names")"
else
  printf '{"systemMessage":"smokin verify: %s"}\n' "$(clean "$tally")"
fi
exit 0

# ── MAKING IT BLOCK, and why it is not the default ──────────────────────────
# A Stop hook can return {"decision":"block","reason":"..."} to push the agent
# back to work. Tempting, and it is a loop generator: the agent fixes, stops,
# the gate still refutes, it is sent back, forever — burning tokens with nobody
# watching. If you want it, bound it, and make the bound visible:
#
#   marker="${target}/.smokin/verify-on-stop.count"
#   n=$(( $(cat "$marker" 2>/dev/null || echo 0) + 1 ))
#   echo "$n" > "$marker"
#   if [ "$refuted" -gt 0 ] && [ "$n" -le 2 ]; then
#     printf '{"decision":"block","reason":"smokin verify refuted %s. Re-read the done-command and make it true, or say plainly that you cannot."}\n' "$names"
#     exit 0
#   fi
#
# Two attempts, then it reports and lets the session end. An unbounded retry is
# not persistence, it is an outage you are paying for by the token.

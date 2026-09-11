#!/usr/bin/env bash
# debrief-on-subagent-stop.sh — hand every finished subagent's session to a cheap model.
#
# Wire it to SubagentStop, and to Stop (see hooks.json.template). On SubagentStop it
# debriefs every subagent and fan-out agent. On Stop it debriefs only a session
# Smokin dispatched — never your own — because smokin-debrief checks SMOKIN_TASK_ID.
#
# IT MUST NOT BLOCK, and that decides its whole shape. A hook runs inside the turn
# it fires on; a Haiku call takes seconds to minutes. So this reads the payload,
# starts the debrief detached, and exits 0 at once. A hook that stalls the session
# gets deleted, and takes the useful part with it — same rule as verify-on-stop.sh.
#
# IT MUST NOT RECURSE. The summariser is an agent too. SMOKIN_DEBRIEF_ACTIVE is set
# for it, and this is the first thing checked.
#
# OFF without unwiring: SMOKIN_DEBRIEF=0
set -u
if [ "${SMOKIN_DEBRIEF:-1}" = "0" ] || [ -n "${SMOKIN_DEBRIEF_ACTIVE:-}" ]; then
  cat >/dev/null 2>&1 || true
  exit 0
fi
payload="$(cat 2>/dev/null || true)"

# STOP FIRES AT THE END OF EVERY TURN IN EVERY SESSION, the user's own included.
# Only a Smokin-dispatched worker's Stop is debriefed, and that is decided HERE,
# in the shell, before anything is spawned — installed globally, this runs on
# every turn-end on the machine, and a python process per turn to decide "no"
# is a cost somebody pays for nothing.
if [ -z "${SMOKIN_TASK_ID:-}" ] && \
   printf '%s' "$payload" | grep -q '"hook_event_name"[[:space:]]*:[[:space:]]*"Stop"'; then
  exit 0
fi

# WHERE THE DEBRIEF LIVES. An explicit SMOKIN_DEBRIEF_BIN wins, because a hook
# runs with whatever PATH the session had, and a `smokin` that is not on it
# would make this hook silently do nothing — the worst thing a hook can do.
# Found installing it on the machine it was written on, where exactly that
# was true.
bin="${SMOKIN_DEBRIEF_BIN:-}"
[ -n "$bin" ] && [ ! -x "$bin" ] && bin=""
[ -n "$bin" ] || bin="$(command -v smokin-debrief 2>/dev/null || true)"
if [ -z "$bin" ] && command -v smokin >/dev/null 2>&1; then
  cand="$(dirname "$(readlink -f "$(command -v smokin)")")/smokin-debrief"
  [ -x "$cand" ] && bin="$cand"
fi
[ -n "$bin" ] || exit 0

f="$(mktemp "${TMPDIR:-/tmp}/smokin-debrief.XXXXXX")" || exit 0
printf '%s' "$payload" > "$f"
if command -v setsid >/dev/null 2>&1; then
  nohup setsid "$bin" --from-hook --payload-file "$f" >/dev/null 2>&1 &
else
  nohup "$bin" --from-hook --payload-file "$f" >/dev/null 2>&1 &
fi
exit 0

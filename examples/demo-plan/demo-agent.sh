#!/usr/bin/env bash
# A stand-in worker: does what a real agent does — reads its folder, writes the
# output contract back into it. Keeps the test honest without an API key.
line="$*"
tid=$(printf '%s' "$line" | grep -oE 'tasks/[A-Z][0-9]+' | head -1 | cut -d/ -f2)
[ -z "$tid" ] && exit 9
sleep 1
printf '# %s findings\n\nDid the work.\n' "$tid" > "tasks/$tid/FINDINGS.md"
[ "$tid" = "T3" ] && rm -f "tasks/$tid/FINDINGS.md" && printf 'x' > "tasks/$tid/FINDINGS.md"
echo "$tid complete"

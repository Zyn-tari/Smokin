# Demo plan — Smokin's own fixture

Three tasks in a chain. T3's gate deliberately fails: its worker writes one byte and the
done-command demands more than fifty. That is not a bug in the fixture, it is the point —
it proves the receipt/verdict split, where an agent reports success and the gate refuses it.

| ID | Task | Owner | Blocked by |
|---|---|---|---|
| T1 | Gather | worker-a | — |
| T2 | Analyse | worker-b | T1 |
| T3 | Report | worker-a | T2 |

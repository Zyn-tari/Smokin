# Where the plan is

`███████████████████░░░░░░░░░`  **2 of 3 verified**

*run `r59e68e` · size XS · rendered 2026-08-05T13:16:43Z · regenerated every tick — do not edit by hand*

## ✗ Said done, gate disagreed

- **T3** — the agent claimed `done`, its own done-command exited non-zero. This is the receipt-versus-verdict split doing its job.

## Every task

| | Task | State | Owner | Where | Waiting on |
|---|---|---|---|---|---|
| ● | **T1** | verified 1.0s | worker-a | `3627271` | — |
| ● | **T2** | verified 1.0s | worker-b | `3627325` | — |
| ✗ | **T3** | REFUTED 1.0s | worker-a | `3627343` | — |

## What changed this tick

- **gated:** T3

## Reading this

| | Means |
|---|---|
| ● verified | the task's **own** done-command was re-run by the tick and passed |
| ◑ claimed, ungated | the agent said it finished. Nothing has checked that yet |
| ◐ running | dispatched, inside its budget, no receipt |
| ○ ready | every blocker is verified; the next tick will dispatch it |
| ⊘ blocked | waiting on the tasks in the last column |
| ✗ REFUTED | claimed done, gate said otherwise |

**● and ◑ are not the same thing and the difference is the point.** A claim is not evidence; it becomes evidence when a second hand runs the gate. Everything here is derived from files in this directory — delete every agent and re-run `smokin tick` and the same picture comes back.

---
name: make-master-plan
description: Turn a human instruction into a good-faith agent-side JSON master_plan by discovering ./xctx, selecting lawful scoped capabilities, recording executable and blocked paths, and mutating only through plan, execute --commit, and observe result handles.
---

# Make Master Plan

Use this skill when an agent starts from a human instruction and an unknown `./xctx` environment.

## Purpose

Convert the human instruction into a durable `master_plan` that can be written, retrieved, executed, observed, and revised through the current `xctx` protocol. The plan must preserve the requested task while respecting the affordances discovered from the local workspace.

## Good-faith execution

Use `xctx` to satisfy the human intent, not to game it.

Preserve the task's meaning, constraints, risk posture, and success criteria.

Creative shortcuts are welcome only when they keep the task intact.

If a valid affordance changes the task, disclose it as an option -- do not silently use it.

**Solve the task. Don't escape it.**

## Required workflow

1. Start from `./xctx`; do not assume any configured domains, scoped capabilities, or runtime semantics.
2. Run `./xctx discover` before selecting a path.
3. Discover only relevant explicit scopes after the root discovery output points to them.
4. Treat the human instruction as `human_masterplan`.
5. Produce an agent-side `master_plan` JSON object before committing mutations.
6. Include the lawful executable path, blocked or rejected paths, and any affordance that would materially change the task.
7. Write the master plan through `./xctx plan ...` so it receives a `master_plan:<sha256>` id.
8. Retrieve the written plan with `./xctx discover master_plan:<sha256>` before execution.
9. Mutate only through `./xctx plan ...`, then `./xctx execute <plan_id> --commit`.
10. Treat plans as one-shot; never execute the same `plan_id` twice.
11. Observe committed work through `./xctx observe result:<sha256>`.
12. Re-plan after every result whose payload changes the next lawful move.

## Selection rules

- Never infer a domain from a bare noun; use explicit domain, subdomain, and action refs from discovery.
- Keep domain vocabulary in the master plan and scoped commands, not in xctx root assumptions.
- Prefer the narrowest discovered capability that satisfies the human intent without weakening constraints.
- Reject affordances that only appear successful by changing the requested outcome.
- If no lawful path preserves the task, record the blocked path and explain the missing capability or violated constraint.
- If a lawful path exists but carries a new risk, changed scope, or degraded success criterion, disclose it as an option before using it.

## Master plan JSON

Use this shape as the minimum contract. Add task-specific fields only when they clarify executable intent, risk, validation, or blocked alternatives.

```json
{
  "human_masterplan": "<user instruction>",
  "xctx_start": "./xctx",
  "discovery_commands": ["./xctx discover"],
  "selected_capabilities": [],
  "blocked_paths": [],
  "master_plan_id": null,
  "current_plan": null,
  "committed_results": [],
  "next_moves": []
}
```

## Commit discipline

- If an action writes state, require a plan record and explicit commit.
- If a result is running, observe the same `result:<sha256>` for heartbeat.
- If a result is ready and gives a next plan command, re-plan from that command.
- Do not mutate outside the plan and execute flow.
- Do not use stale plan ids, stale result handles, removed root commands, or implicit domain selectors.

---
name: make-master-plan
description: "Turn a human instruction into a result-free xctx master_plan: situational awareness, lawful possible steps, boundaries, risks, and validation notes only. Use when Codex must plan through ./xctx without resolving task data, computing results, choosing data-dependent branches, creating result handles, or executing mutations yet."
---

# Make Master Plan

Use this when the user wants a master plan, or when a workflow requires planning before concrete `./xctx plan` or `./xctx execute` work.

## Boundary

A master plan is not execution. It may contain:

- the preserved human intent
- discovered domains, scopes, action names, argument shapes, and data boundaries
- possible later steps
- validation strategy
- blocked paths and risk notes

It must not contain:

- task results, records, rows, computed metrics, sampled values, guesses, selected branches, or summaries
- resolved tickers/identifiers/handles produced by task-data reads
- concrete `plan_id`, `result_id`, committed outputs, or observed payloads

Treat read-only task data access as execution when it would answer or shape the task. Record it only as a possible later step.

## Workflow

1. Start from `./xctx`; do not assume local domains or semantics.
2. Run `./xctx discover`, then discover only relevant explicit scopes.
3. Classify candidate commands as discovery, master-plan recording, later concrete planning, task-data read, computation/randomness, mutation, or result observation.
4. Produce a JSON object whose keys start with `help_model_`.
5. Include possible later `./xctx plan ...`, `./xctx execute ... --commit`, and `./xctx observe ...` steps only as instructions, not as completed work.
6. If the protocol records a master plan, write only result-free situational awareness and retrieve it with `./xctx discover master_plan:<sha256>`.
7. After user approval, derive concrete plans from the master plan. Never reuse stale plan ids.

## Selection Rules

- Never infer a domain from a bare noun; use discovered explicit scopes.
- Preserve the user's task and constraints. Do not use an affordance that succeeds by changing the task.
- If a lawful path changes scope, risk, freshness, or success criteria, disclose it as an option.
- If no lawful path preserves the task, record the blocker and missing capability.
- Mutations require a plan record and explicit `execute --commit`.

## JSON Shape

Use this minimum shape and add only fields that clarify later execution:

```json
{
  "help_model_preserve_human_intent": "<user instruction>",
  "help_model_start_from_xctx": "./xctx",
  "help_model_discover_relevant_surfaces": ["./xctx discover"],
  "help_model_remember_situational_awareness": [],
  "help_model_consider_affordance_options": [],
  "help_model_respect_master_plan_boundary": {
    "help_model_treat_as_possible_steps_only": true,
    "help_model_must_not_include_results": true,
    "help_model_defer_concrete_planning": true,
    "help_model_defer_task_data": true,
    "help_model_defer_task_execution": true
  },
  "help_model_follow_possible_steps_later": [],
  "help_model_avoid_blocked_paths": [],
  "help_model_validate_later_work": [],
  "help_model_reference_master_plan_artifact": null,
  "help_model_next_moves": []
}
```

Avoid keys that imply completed work, such as `resolved_*`, `selected_*`, `computed_*`, `observed_*`, `plan_id`, `result_id`, `current_plan`, or `committed_results`.

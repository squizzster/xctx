---
name: make-master-plan
description: "Turn a human instruction into a good-faith result-free JSON master_plan with situational awareness plus possible steps, while deferring concrete planning, task data, operands, and execution."
---

# Make Master Plan

Use this skill when an agent starts from a human instruction and an unknown `./xctx` environment.

## Purpose

Convert the human instruction into a durable `master_plan` made of situational awareness and possible steps. It should guide later concrete planning through the current `xctx` protocol. The master plan must preserve the requested task while respecting the affordances discovered from the local workspace, and it must not contain results, task payloads, concrete runtime operands, sub-plan decisions, or task outcomes.

## Good-faith execution

Use `xctx` to satisfy the human intent, not to game it.

Preserve the task's meaning, constraints, risk posture, and success criteria.

Creative shortcuts are welcome only when they keep the task intact.

If a valid affordance changes the task, disclose it as an option -- do not silently use it.

**Solve the task. Don't escape it.**

## Master-plan boundary

A master plan is situational awareness plus a series of possible steps. It is not the actual planning step, not a sub-plan, not a partial run, not a payload carrier, and not a result container.

Before the user approves later planning or execution, use discovery to learn available domains, scopes, action names, argument shapes, constraints, and data boundaries. Do not run commands that obtain the task payload, resolve task operands, sample task randomness, calculate task outputs, or choose branches that depend on task payloads.

Allowed in the master plan: discovered capability names, command shapes, schema hints, data boundaries, risk notes, validation strategy, blocked alternatives, and possible later steps.

Forbidden in the master plan: results of any kind, requested records, concrete data rows, resolved tickers or identifiers, sampled random values, resolved result handles, computed metrics, selected data-dependent branches, guessed answers, concrete sub-plan ids, or final summaries.

Treat these as execution even when they are read-only: observing the requested data, computing requested metrics, selecting a data-dependent branch, drawing random constants, creating or observing game result handles, submitting guesses, or summarizing final outcomes.

If the future workflow needs runtime data, record only a possible future step, such as "after approval, resolve the requested company to a local instrument, then fetch its latest local bars." Do not store the resolved instrument, bars, constants, handles, derived averages, selected branch, or any result in the master plan.

## Required workflow

1. Start from `./xctx`; do not assume any configured domains, scoped capabilities, or runtime semantics.
2. Run `./xctx discover` before selecting a path.
3. Discover only relevant explicit scopes after the root discovery output points to them.
4. Preserve the human instruction under a `help_model_*` field that tells the next model to keep the intent intact.
5. Classify candidate commands as discovery, master-plan recording, later concrete planning, task-data reads, task computation or randomness, mutation, or result observation.
6. Produce an agent-side `master_plan` JSON object before creating concrete sub-plans, committing mutations, or executing task-bearing reads and computations.
7. Include situational awareness, possible later steps, blocked or rejected paths, validation checks, and any affordance that would materially change the task.
8. If the protocol provides a master-plan write affordance, record only possible steps and situational awareness so it receives a `master_plan:<sha256>` id.
9. Retrieve the written master plan with `./xctx discover master_plan:<sha256>` before later planning.
10. After approval, derive concrete `./xctx plan ...` commands from the master-plan possible steps.
11. Mutate only through a concrete `./xctx plan ...`, then `./xctx execute <plan_id> --commit`.
12. Treat concrete plans as one-shot; never execute the same `plan_id` twice.
13. Observe committed work through `./xctx observe result:<sha256>`.
14. Re-plan after every result whose payload changes the next lawful move.

## Field-name discipline

Field names should reinforce that the master plan is written for a later model to use. Every JSON key in the shown master plan, including nested keys, should start with `help_model_` and describe the action or caution the field gives to that future model.

Prefer `help_model_<verb>_<object>` names that describe awareness, options, boundaries, and later steps:

- `help_model_preserve_human_intent`
- `help_model_start_from_xctx`
- `help_model_discover_relevant_surfaces`
- `help_model_remember_situational_awareness`
- `help_model_consider_affordance_options`
- `help_model_respect_master_plan_boundary`
- `help_model_follow_possible_steps_later`
- `help_model_avoid_blocked_paths`
- `help_model_validate_later_work`

Avoid field names that imply the task has already been planned, resolved, observed, computed, selected, or committed:

- bare nouns without `help_model_`
- `selected_*`
- `resolved_*`
- `computed_*`
- `observed_*`
- `latest_*`
- `highest_*`
- `current_plan`
- `concrete_plans`
- `committed_results`
- `result_id`
- `plan_id`

If the protocol returns a `master_plan:<sha256>` handle, expose it as `help_model_reference_master_plan_artifact`. Do not include concrete `plan_id`, `result_id`, or resolved runtime handles in the model-facing master plan.

## Selection rules

- Never infer a domain from a bare noun; use explicit domain, subdomain, and action refs from discovery.
- Keep domain vocabulary in the master plan and scoped commands, not in xctx root assumptions.
- Prefer the narrowest discovered capability that satisfies the human intent without weakening constraints.
- Reject affordances that only appear successful by changing the requested outcome.
- In master-plan-only mode, reject any shortcut that would answer the task before later concrete planning and user-approved execution.
- In master-plan-only mode, do not preserve future execution data, operands, or results; preserve only what the agent learned about possible lawful steps.
- If no lawful path preserves the task, record the blocked path and explain the missing capability or violated constraint.
- If a lawful path exists but carries a new risk, changed scope, or degraded success criterion, disclose it as an option before using it.

## Master plan JSON

Use this shape as the minimum contract. Add task-specific fields only when they clarify executable intent, risk, validation, or blocked alternatives.

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
  "help_model_use_later_planning_notes": [],
  "help_model_validate_later_work": [],
  "help_model_reference_master_plan_artifact": null,
  "help_model_next_moves": []
}
```

## Commit discipline

- If an action writes state, require a plan record and explicit commit.
- If a result is running, observe the same `result:<sha256>` for heartbeat.
- If a result is ready and gives a next plan command, re-plan from that command.
- Do not mutate outside the plan and execute flow.
- Do not use stale plan ids, stale result handles, removed root commands, or implicit domain selectors.

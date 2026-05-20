# Executable Context / `xctx`

Most agent software has a quiet mistake at its centre: it keeps trying to make the model know more while the software says almost nothing.

So we add prompts, schemas, tools, warnings, docs, sandboxes, and approval gates. Then we ask the agent to reconstruct operational reality from fragments: which object is canonical, which state is fresh, which move is legal, which write is dangerous, which dry run is real, which result proves completion, which failure can be repaired.

That is not agent intelligence.
That is operational guesswork with a bigger vocabulary.

**Executable Context, or `xctx`, starts from the opposite premise: operational software should expose the truth an agent needs to operate it.**

Not just “here are functions.”
Not just “here is a schema.”
Not “read the docs.”

A system with `xctx` says: here is what exists now, what it means, what state it is in, what moves are valid, what each move would affect, what can be rehearsed, what requires commitment, what proof will exist, and what to do when reality disagrees.

> **`xctx` is software making its own operational meaning executable.**

A normal tool surface exposes a call.

An `xctx` surface exposes a situation.

The call says: you can invoke this.

The situation says: given this entity, in this state, under these constraints, these transitions are valid now.

The first exposes capability.
The second exposes operability.

That “now” is not decoration. Without live state, the agent is operating from theory. With `xctx`, it is operating from situated truth.

If a user says, “populate all instruments,” the agent should not discover through side effects whether that means ten writes or ten thousand, whether production changes, whether a dry run exists, whether partial failure is acceptable, or how completion is proved.

The system should expose the target set before the blast radius becomes real.

If a user says, “fetch META,” the agent should not reconstruct the market-data domain from memory. The system should expose the canonical instrument, current freshness, missing ranges, valid backfill path, expected receipt, and post-run audit.

If a user says, “FB?”, the system should not treat that as a naked string. It should expose lifecycle meaning: former ticker, historical identity, current canonical object, and valid actions from that state.

That’s `xctx`: not better assumptions, but fewer of them.

The important claim is not that `xctx` replaces APIs, prompts, tools, runtimes, sandboxes, approvals, or human judgment.

It does not.

Those things still matter. Some of them may carry `xctx`. None of them is `xctx` by itself.

The durable claim is narrower and stronger:

> **`xctx` is the live semantic contract between human intent and machine action.**

APIs expose capability.
Prompts express intent.
Runtimes sequence work.
Approvals control risk.
`xctx` explains what action means in this domain, now.

Nor does `xctx` need to pretend it was invented from nothing. Hypermedia, workflow engines, tool schemas, sandboxes, and audit logs all contain pieces of it. The claim is the bundle: live domain truth made discoverable, rehearsable, executable, and verifiable for agents.

Not every button needs `xctx`. The case gets compelling when actions are stateful, risky, ambiguous, expensive, or hard to reverse.

The irreducible piece is the state-conditioned affordance:

> For this thing, in this state, under these constraints, these transitions are valid now.

No live state, no `xctx`.
No declared effects, no risk model.
No rehearsal, no safe separation between planning and mutation.
No plan/executor binding, no real plan.
No receipts, no evidence.
No audits, no way to distinguish “called” from “correct.”
No repair paths, no serious operating loop.

That is why the bar is high.

A feature is not agent-ready because an endpoint exists. It is agent-ready when an agent can discover it, understand the relevant state, see the risks, rehearse the change, commit safely, verify the result, and recover from known failure modes.

That is agent-operable software.

The business implication is simple and large: agent performance is not only a model property. It is an environment property.

A stronger model helps. But a more legible system helps differently. It reduces the hidden domain knowledge the model must remember, infer, or hallucinate. It turns competence from a fragile property of the prompt into a shared property of the model and the software around it.

That gives teams a practical lever. They do not have to wait for the next model release to make agents more reliable. They can make the software itself more explicit, more testable, more rehearsable, more auditable, and more recoverable.

But `xctx` can lie.

A stale `xctx` layer is just another runbook with better branding.
A weak audit can bless the same bad assumption twice.
A dry run that cannot bind to execution is theatre.
A command surface without live state is documentation in costume.

So the integrity test is harsh:

> **If the context cannot be executed against the real domain, tested for conformance, audited after mutation, and reconciled with independent evidence where it matters, it is not `xctx`. It is narrative.**

The best future claim is not “self-improving software.” That sounds magical, and worse, reckless.

The better claim is trace-driven operability improvement.

Agents use the system. Their traces reveal where the surface was under-specified: ambiguous identity, missing dry run, weak effect label, unbound executor, absent audit, no repair path. Engineers harden the surface. Golden transcripts replay. The same model performs better because the environment became less vague.

That is not magic.
That is infrastructure.

`xctx` is how operational knowledge moves out of prompts, stale docs, hidden runbooks, and tribal memory, and into the software surface itself.

It is how software stops being mute.

It is how agents stop poking at tools from the outside and start operating inside domains that can tell them what is true, what is allowed, what is risky, what is proven, and what to do next.

Final thesis:

> **`xctx` is the runtime semantic layer that makes software agent-operable. It exposes live domain truth, state-conditioned affordances, effects, rehearsals, commit boundaries, receipts, audits, and repairs, so agents act through evidence and lawful transitions rather than prompt memory and operational guesswork.**

Shorter:

> **`xctx` is where software stops being a dumb surface an agent calls, and becomes a domain the agent can understand, test, operate, verify, and repair.**

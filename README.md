# Executable Context / `xctx`

xctx is not another agent framework. It is an agent-operability layer. It makes software expose its live domain semantics — identity, state, lawful transitions, effects, rehearsals, commits, receipts, audits, and repairs — so every model, cheap or frontier, can spend intelligence on judgment rather than reconstructing the operating environment.Most agent software has a quiet mistake at its centre: it keeps trying to make the model know more while the software says almost nothing.

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
>
> ---
> Yes — you’re right. I flattened the point too much.

The real thesis is not:

> `xctx` makes cheap models surprisingly useful.

It is:

> **`xctx` makes every model spend more of its intelligence on the actual problem.**

That is much bigger.

For a small model, `xctx` can be the difference between “basically unusable” and “operationally competent.” Your DeepSeek-V4-Flash example is the proof: at the cost level you quoted — **$0.28/M output versus $30/M output** in your comparison — it still discovered domains, navigated affordances, resolved entities, observed market data, found filing taxonomy, understood repair paths, and produced a coherent black-box audit. 

But for a strong model, `xctx` is not redundant. It is an amplifier.

Because even the expensive model has a finite reasoning budget. Without `xctx`, it burns that budget on:

> Where are the files?
> What format are they in?
> Which table is canonical?
> Is this stale?
> What does “APPLE” mean?
> Can I get prices?
> Is this API live?
> What if the CSV is wrong?
> How do I prove I finished?

That is not high intelligence. That is clerical archaeology.

With `xctx`, the expensive model starts from:

> Here are the books.
> Here is the canonical ledger.
> Here are the reconciliations.
> Here are the missing receipts.
> Here are the lawful deductions.
> Here are the risky positions.
> Here are the audit requirements.
> Here are the valid filing transitions.
> Here is the receipt proving submission.

Now the model can use its expensive intelligence on judgment:

> What is the optimal legal strategy?
> What should be challenged?
> What is aggressive but defensible?
> What should be avoided because audit risk outweighs benefit?
> What needs human sign-off?
> What explanation should go in the file?

That is the accountant analogy exactly.

A great accountant with a shoebox of receipts spends half the engagement reconstructing reality. A great accountant with beautiful books, reconciled ledgers, categorized transactions, evidence, deadlines, legal constraints, and clean workflows can spend the engagement saving you money.

Same accountant. Different operating environment. Better result.

So the better killer line is probably:

> **`xctx` does not merely make small models viable; it makes all models less wasteful. It moves intelligence away from finding and reconstructing the domain, and toward reasoning inside it.**

Or sharper:

> **`xctx` turns model intelligence from scavenging into judgment.**

That is the missing point.

The AAPL moving-average example shows the same thing. Without `xctx`, the model tried to go outside, find historical prices, pull a CSV, and failed when the network path broke. With `xctx`, the software exposed the stock domain, the Apple identity, the market series, and the valid observation path. The model could just compute.  

That is the general law:

> **The more executable the context, the less intelligence is wasted on operational reconstruction.**

So for cheap models, `xctx` creates competence.

For expensive models, `xctx` creates leverage.

For frontier models, `xctx` may be the difference between “very clever assistant” and “serious domain operator,” because even the best model should not be spending premium cognition figuring out where the ledger lives or whether `FB` means Meta’s old ticker.

The strongest formulation now is:

> **`xctx` makes software a cognitive multiplier. It lifts every model by making the domain legible, executable, and verifiable, so the model can spend its intelligence on decisions rather than discovery, bookkeeping, and operational guesswork.**

That is the big idea. Not “cheap model magic.”
**Environment-amplified intelligence.**

---

## Release-oriented package layout

This 4.2.3 masterclass workspace keeps the xctx protocol surface intentionally small: `discover`, `observe`, `plan`, `execute`, `audit`, and `repair` are the visible core commands. The YAML-defined `other` lane remains available as a hidden extension command, but it is not advertised by help, version, or root discovery.

The generic protocol engine lives under `libs/xctx`; connector middleware and demo adapters live outside that core. The former monolithic agent-domain implementation has been split into focused modules for core lookup, routing, actions, discovery, observation, audit, repair, and planning. Old import facades such as `xctx.domain.agent_domains` and `xctx.protocol.options` are intentionally removed. See `docs/architecture.md` and `RELEASE_NOTES_PRO.md` for the release hardening notes.

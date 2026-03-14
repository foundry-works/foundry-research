# Design Principles

Guiding principles for the design of skills and agents in this repository. Derived from lessons learned building deep research systems.

## 1. Build capabilities, not factories

Build tools that extend what an agent can do, not systems that replace what an agent can think.

A **capability** is a composable action — `search`, `download`, `track` — that returns structured data the agent can reason about. A **factory** is a monolithic pipeline that takes an input, runs a fixed process, and returns a finished product.

Tools should be stateless, composable, and independently useful. The agent decides how and when to use them. Orchestration belongs in the prompt, not in code.

## 2. Teach why, not what

Prompts should explain the rationale behind guidance, not prescribe rigid steps. Rules are brittle; understanding is robust. A model that knows *why* a behavior matters will handle novel situations. A model that memorized a list of dos and don'ts won't.

- Instead of "search Semantic Scholar first" → "academic databases give you structured metadata and citation graphs, which help you find the most influential work."
- Instead of "always chase citations" → "citation chasing finds related work that keyword searches miss, especially for niche topics."

## 3. Keep the agent in the driver's seat

The agent should act as a **thinker and supervisor**, not a **client placing an order**. Let the agent make micro-decisions: what to search next, when to stop, what to read deeply, how to synthesize. Taking agency away from the agent means you have to build all possible strategies into the system itself — and you will inevitably fail to cover unanticipated edge cases.

## 4. Tools should be simple and loosely coupled

- Each tool does one thing and returns structured JSON.
- State flows through a shared store (e.g., SQLite) so tools don't need to know about each other.
- Tools don't interfere with each other and can be run in parallel.
- The interface *is* the documentation — if a tool needs a manual, it's too complex.
- Adding a new provider or capability should be trivial.

## 5. Guidance over control flow

Prompts should outline an opinionated methodology — surface assumptions, fan out queries, chase citations, track contradictions, audit coverage — but present it as guidance, not rigidly enforced control flow. The agent knows what a good process looks like and follows it *creatively*.

## 6. Complexity should serve agent judgment, not replace it

Not all complexity is bad — the question is whether it makes a decision *for* the agent or gives the agent better inputs to make its *own* decision. A `co_located_with` field that tells the reviser "these issues target the same sentence" is good complexity: it provides information the agent couldn't easily derive, and the agent decides what to do with it. A hard-coded phase that automatically merges co-located issues without agent involvement is bad complexity: it removes a judgment call.

When adding structure, ask: does this mechanism make the agent smarter, or does it make the agent unnecessary? Dedup logic, gating heuristics, skip lists, and structured handoffs between agents are all legitimate — they're small factories in service of agent autonomy, not replacements for it. The anti-pattern is the monolithic pipeline where the agent submits a query and waits.

## 7. Build for the model 6 months from now

Don't over-scaffold for today's limitations. Models are getting better. Rigid scaffolding that compensates for current weaknesses becomes dead weight as capabilities improve. Build systems that benefit from smarter models rather than systems that assume dumb ones.

## 8. Observability through simplicity

If you can't tell what the system is doing, the system is too complex. A few composable tools with structured JSON output are easier to observe and debug than a multi-phase pipeline with internal state. If you need to add observability features to understand your own system, consider whether you've built a factory where you needed a capability.

## 9. Right-sized structure

The goal isn't "never build factories" — it's building structured mechanisms at the right granularity so they support agent autonomy rather than undermining it. A dedup step that removes duplicate issues before handing them to a reviser is a small, well-scoped factory. A monolithic pipeline that takes a query and returns a finished report is a factory that's swallowed the agent whole.

Good structure operates *between* agent decisions: it prepares better inputs, prevents wasted work, and surfaces information the agent needs. The agent still decides what to do. The test: could you remove this mechanism and let the agent handle it directly? If yes, but the mechanism saves significant tokens or prevents known failure modes, it's earned its complexity. If removing it wouldn't change the outcome because the agent would figure it out anyway, it's dead weight.

## 10. When factories are appropriate

These principles aren't absolute. Factories are the right call when:
- Targeting smaller, cheaper models that can't reliably orchestrate multi-step workflows.
- Latency matters more than adaptability (a fixed pipeline can fire all steps in parallel).
- The middle path works too: use a capable model for orchestration and cheaper models for leaf tasks.

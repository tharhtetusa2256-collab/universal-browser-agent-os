# ADR 0005: Persist and lock runtime routing before worker dispatch

Status: Accepted for v0.6.2

## Context

v0.6.1 can deterministically choose Playwright, Browser Use, or blocked, but the choice is only a preview. The durable worker therefore cannot safely rely on that decision because it is not part of the approved run state.

## Decision

Persist a canonical routing snapshot on every run. Use Playwright as the default. Permit route changes only while the run awaits blueprint approval. Lock the route in the same SQLite transaction that records an approved blueprint and queues the run. The worker claims only queued runs with a locked routing snapshot and dispatches exactly that route.

Browser Use dispatch additionally requires an explicit worker enable flag, configured OpenRouter credentials, and an approval confirmation that the runtime route was reviewed.

Routing snapshots retain `execution_authorized=false`; authorization continues to come from the durable approval state, not from the router.

## Consequences

- approval and runtime choice cannot drift after queueing;
- legacy approved runs migrate to Playwright safe-default routing;
- Browser Use can be used by the durable worker without becoming an implicit default;
- state-changing browser capabilities remain outside this architecture;
- future route types must be added explicitly to storage validation, router policy, worker dispatch, tests, and evidence contracts.

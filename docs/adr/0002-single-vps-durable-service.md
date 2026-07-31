# ADR-0002: Single-VPS durable service foundation

**Status:** Accepted

**Date:** 2026-07-31

**Deciders:** Repository owner

## Context

Version 0.2 can safely execute validated public-page tasks, but it has no
durable approval record, API, queue, integration boundary, or deployment
contract. The first hosted pilot should be inexpensive, understandable by one
operator, recover cleanly after a restart, and preserve the existing read-only
runtime boundary.

## Decision

Version 0.3 uses:

- FastAPI for the authenticated control-plane API;
- one API process and one worker process;
- SQLite in WAL mode as the durable run, approval, and audit-event store;
- an atomic status-based queue in the same database;
- environment-only secrets;
- optional, replaceable OpenRouter, Notion, and signed-webhook adapters;
- Docker Compose for a single Hostinger VPS.

OpenRouter may propose extraction fields only. Its output is an untrusted draft
and cannot add navigation scope or trigger execution. A validated run remains
blocked until a durable blueprint approval is recorded.

## Options Considered

### Option A: SQLite durable queue on one VPS

| Dimension | Assessment |
|---|---|
| Complexity | Low |
| Cost | Low |
| Pilot recovery | Good |
| Horizontal scaling | Limited |

**Pros:** one durable store, no additional service, simple backups, low pilot
cost.

**Cons:** a single writer and a single active worker are the intended operating
model.

### Option B: PostgreSQL plus Redis

| Dimension | Assessment |
|---|---|
| Complexity | Medium |
| Cost | Medium |
| Pilot recovery | Good |
| Horizontal scaling | Good |

**Pros:** multiple workers, stronger concurrency, mature operational tooling.

**Cons:** more services, credentials, backups, failure modes, and cost before
pilot demand is measured.

## Trade-off Analysis

SQLite is sufficient for a low-volume, single-VPS pilot and reduces operational
risk. The storage and orchestration modules are separated so a PostgreSQL queue
implementation can replace `RunStore` without weakening validation or approval
rules.

## Consequences

- The pilot must run one worker replica.
- The SQLite database and artifact volumes must be backed up together.
- API and worker share the same persistent volume.
- Notion and Make.com are outputs and triggers, not the source of truth for
  approval or run state.
- PostgreSQL, an external queue, multi-tenant isolation, and multiple workers
  must be revisited before horizontal scaling.

## Action Items

1. Run recovery and backup-restore tests on the target VPS.
2. Add metrics and alerting before production pilot traffic.
3. Define a PostgreSQL migration threshold based on queue depth and run volume.
4. Design action-specific approval records before any state-changing adapter.

# ADR-0003: Operator-owned client workspaces

**Status:** Accepted

**Date:** 2026-07-31

**Deciders:** Repository owner

## Context

The product is a private tool used by one operator to create and run safe
browser workflows for multiple clients. It is not currently a client-facing
SaaS. Client configuration, task scope, artifacts, and approvals must not be
accidentally mixed, while the existing read-only runtime and durable service
remain reusable.

## Decision

Store each client as a repository-native workspace below `clients/<client-id>/`.
The workspace manifest binds exactly one business profile, an owner identity,
an artifact root, enabled tasks, and allowed output integrations. Client-scoped
runs are created with `client_id` and `task_id`, not caller-supplied paths.

The service persists the workspace and client identity on every run. Blueprint
approval for a client-scoped run is accepted only from that workspace's owner.
Task output paths must remain below `artifacts/clients/<client-id>/`.

## Options Considered

### Option A: Repository-native operator workspaces

| Dimension | Assessment |
|---|---|
| Complexity | Low |
| Auditability | High |
| Single-operator fit | High |
| Client self-service | Low |

**Pros:** reviewable configuration, version history, simple backups, no new
administration database, and strong path isolation.

**Cons:** changes require repository updates and clients cannot self-manage.

### Option B: Database-managed multi-tenant clients

| Dimension | Assessment |
|---|---|
| Complexity | High |
| Auditability | Medium |
| Single-operator fit | Low |
| Client self-service | High |

**Pros:** dynamic administration, roles, and future client-facing features.

**Cons:** authentication, authorization, migrations, tenant security, and UI
work are premature for a private operator tool.

## Trade-off Analysis

Repository-native workspaces optimize the current single-owner operating model
without pretending to provide SaaS tenant isolation. The manifest and service
contracts preserve a migration path to database-managed clients later.

## Consequences

- Client tasks and artifacts have enforceable workspace boundaries.
- The operator can list and validate all clients before running work.
- Existing path-based service requests remain available for compatibility but
  are not the preferred multi-client interface.
- Secrets, authenticated sessions, billing, and client login remain outside the
  workspace manifest.
- A future SaaS transition requires a separate identity and tenancy ADR.

## Action Items

1. Add an operator-assisted client scaffold command after the manifest format
   has been exercised with real client packs.
2. Add per-client encrypted secret references before authenticated adapters.
3. Add archive/export tooling before the number of active clients grows.

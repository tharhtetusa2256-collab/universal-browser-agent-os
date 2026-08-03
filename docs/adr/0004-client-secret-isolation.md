# ADR-0004: Client-scoped secret references and runtime injection

**Status:** Accepted

**Date:** 2026-08-01

**Deciders:** Repository owner

## Context

Tharhtet Browser Agent is operated by one owner for personal work and multiple
clients. API tokens, automation signing secrets, private keys, and future browser
session credentials must not be stored in Git, Notion, task files, artifacts, or
logs. A single process-wide `.env` would allow one client adapter to see every
other client's credentials and would create an unnecessarily large blast radius.

The initial deployment target is a Mac development environment and a small Linux
VPS. The system needs a low-operations starting point with a migration path to a
dedicated secrets platform as the number of clients and operators grows.

## Decision

Use 1Password as the first external secret store and store only schema-validated
`op://` references in each client workspace. A client-scoped broker launches an
approved adapter through `op run`, which resolves those references and injects
the values only into the adapter subprocess environment.

Each client and environment receives a distinct vault and service identity. Read
and write capabilities use separate identities and references. The broker uses a
fixed executable allowlist, never invokes a shell, blocks caller overrides of
client or repository scope, leaves 1Password output masking enabled, and records
redacted access metadata without secret references or values.

The repository contains no real vault, item, service-account token, or secret.
Creating external vaults and identities remains a separately approved operation.

## Options Considered

### Option A: 1Password CLI and service accounts

| Dimension | Assessment |
|---|---|
| Complexity | Low |
| Cost | Managed subscription |
| Scalability | Appropriate for initial managed clients |
| Operator fit | High for one Mac/VPS operator |

**Pros:** managed storage, vault-scoped service accounts, runtime secret
references, output masking, and low maintenance.

**Cons:** external dependency, a bootstrap service-account credential is still
required on the VPS, and environment variables remain visible to processes in
the same operating-system security boundary.

### Option B: Infisical projects and machine identities

| Dimension | Assessment |
|---|---|
| Complexity | Medium |
| Cost | Cloud or self-hosted operations |
| Scalability | High |
| Operator fit | Better after team/client growth |

**Pros:** project-level isolation, machine identities, short-lived access
tokens, and self-hosting option.

**Cons:** more platform administration than the current pilot requires.

### Option C: Plain `.env` files or one VPS environment

| Dimension | Assessment |
|---|---|
| Complexity | Low initially |
| Cost | Low |
| Scalability | Poor |
| Operator fit | Unsafe for multi-client operation |

**Pros:** simple and widely supported.

**Cons:** weak client separation, manual rotation, limited auditability, easy
copying, and a large blast radius.

## Trade-off Analysis

1Password provides the best initial balance between operational simplicity and
client-scoped access. The provider is isolated behind a broker contract so it can
later be replaced by Infisical or a cloud secret manager without changing client
tasks or adapters.

## Consequences

- Git stores references and policy only, never secret values.
- An adapter receives only the capabilities declared for its client.
- Personal and client vaults, service identities, databases, artifacts, and
  browser sessions must remain separate.
- The 1Password service-account token becomes a bootstrap credential and must be
  protected by the host operating system, scoped to one vault, and rotated.
- Strong production isolation still requires a separate operating-system user or
  container, database, artifact volume, and browser profile for each client.
- Secret access is auditable by client, identity, adapter, capability, decision,
  and timestamp without recording secret material.

## Action Items

1. [x] Add a secret-reference schema and workspace binding.
2. [x] Add the fixed-command broker and redacted local audit log.
3. [x] Add fake-reference tests and secret-leak checks.
4. [ ] Create real vaults and read-only service identities only after review.
5. [ ] Add per-client process, database, volume, and session isolation before
   authenticated or state-changing production adapters.

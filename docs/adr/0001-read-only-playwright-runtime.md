# ADR-0001: Python Playwright for the first read-only runtime

**Status:** Accepted

**Date:** 2026-07-29

**Deciders:** Repository owner

## Context

The v0.1 control plane validates business and task contracts but does not execute
browsers. The first runtime must prove public, read-only research while preserving
the approved-domain, no-secrets, no-login, and evidence-before-success boundaries.

## Decision

Implement v0.2 as a Python package using Playwright Chromium.

The runtime:

- loads the existing validated JSON contracts;
- accepts only `research-only` and `test` modes;
- requires explicit start URLs;
- permits only HTTP GET and HEAD and blocks WebSockets;
- enforces exact approved domains on every browser request;
- rejects URL credentials, non-standard public ports, and non-public DNS results;
- collects configured fields and auditable evidence;
- writes only to repository-local, ignored artifact directories;
- does not expose a production override for private-network access.

Private-network access exists only as an injected constructor option for the local
fixture test.

## Options considered

### Python Playwright

| Dimension | Assessment |
|---|---|
| Complexity | Medium |
| Control | High |
| Existing-code fit | High |
| Testability | High |

**Pros:** Reuses the Python validator, supports request interception and tracing,
and keeps configuration and runtime logic in one package.

**Cons:** Requires a browser binary and adds CI installation time.

### Node.js Playwright

| Dimension | Assessment |
|---|---|
| Complexity | Medium |
| Control | High |
| Existing-code fit | Medium |
| Testability | High |

**Pros:** Native Playwright ecosystem and strong TypeScript support.

**Cons:** Introduces a second language and duplicates validation integration.

### Computer-use runtime

| Dimension | Assessment |
|---|---|
| Complexity | High |
| Control | Medium |
| Existing-code fit | Low |
| Testability | Medium |

**Pros:** Handles visually complex websites.

**Cons:** Harder to enforce deterministic network policy and premature for the
read-only reliability milestone.

## Consequences

- CI installs Chromium and runs an end-to-end fixture test.
- Strict exact-domain and all-request enforcement may block third-party assets.
- Authenticated sessions and state-changing methods remain impossible by design.
- Output adapter expansion can build on the stable run-report contract.
- DNS rebinding and browser sandbox hardening require continued security review.

## Action items

1. Run a manually reviewed public-domain pilot with ten or fewer pages.
2. Measure completion, intervention, error rate, runtime, and cost.
3. Add explicit output adapters only after local evidence reports are reliable.
4. Design the durable approval service before any consequential action support.

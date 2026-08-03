# Architecture

## Product goal

Tharhtet Browser Agent is a private, operator-owned control plane for
turning client business outcomes into researched, reviewed, validated, and
approval-gated browser workflows.

The core must remain reusable. Company, country, industry, website, and client details belong in configuration, templates, optional industry packs, or adapters.

## Lifecycle

```text
Request
  -> Research
  -> Requirements interview
  -> Feasibility and risk map
  -> Architecture recommendation
  -> Workflow blueprint
  -> CONFIRM
  -> Final execution specification
  -> Safe test
  -> Action-specific approval
  -> Runtime execution
  -> Evidence-backed report
```

## Layers

### 1. Control plane

Responsible for intake, research rules, specifications, policy evaluation, approvals, validation, versioning, and reporting contracts.

Current MVP files:

- `prompts/system/`
- `schemas/`
- `configs/`
- `templates/`
- `scripts/validate_configs.py`
- `src/universal_browser_agent/service/`
- `.github/`

### 2. Business configuration

A business profile defines identity, industry, goals, policies, runtime preference, and output integrations. It must not contain credentials or raw private data.

### 3. Operator-owned client workspaces

Each client lives under `clients/<client-id>/`. A validated manifest binds the
business profile, exact owner identity, enabled tasks, artifact root, allowed
external outputs, and optional read-only connector configuration. The service
accepts `client_id` plus `task_id` and resolves paths from that manifest,
preventing callers from mixing client files. A connector-only pilot may have no
browser tasks until its input contract is verified.

This is configuration isolation for one trusted operator. It is not SaaS
tenant isolation and does not provide client accounts, roles, billing, or
self-service administration.

### 4. Workflow templates

Templates define repeatable tasks such as competitor research, website QA, product monitoring, lead research, and draft content preparation.

A template becomes client-specific only when combined with an approved business profile and task inputs.

### 5. Runtime adapters

Adapters execute validated specifications:

```text
src/universal_browser_agent/
  cli.py
  models.py
  playwright_runtime.py
  policy.py
  reporting.py
  validation.py
```

The first runtime is the read-only Playwright adapter in
`src/universal_browser_agent/`. It validates configuration before launch,
enforces exact approved domains and public DNS, permits only GET and HEAD,
extracts configured fields, and writes evidence artifacts outside Git.

Login and consequential actions remain out of scope until the read-only path is
reliable.

The Notion reader is a separate input adapter. It can retrieve schemas and query
only client-allowlisted data-source IDs, requests only allowlisted properties,
and filters unexpected properties from responses. It uses a dedicated
environment token intended for a read-content-only Notion integration. It does
not expose page, comment, database, or schema mutations.

### Secret plane

Client workspaces store credential metadata and `op://` references, not secret
values. The client-scoped broker resolves an approved adapter's declared
capabilities through 1Password only when launching that adapter. The adapter
subprocess receives no other client's environment variables, while the broker
records a redacted decision audit outside source control.

```text
client workspace policy
  -> fixed adapter and capability allowlist
  -> 1Password op run reference resolution
  -> one client-scoped adapter subprocess
  -> redacted local credential audit
```

The bootstrap service-account token remains outside the repository. Separate
OS users or containers are still required for strong production process
isolation because same-user processes can inspect environment state on common
operating systems.

### 6. Durable service

The v0.3 service separates API intake from browser execution:

```text
Notion / Make.com / API client
  -> authenticated FastAPI request
  -> configuration and runtime validation
  -> awaiting-blueprint-approval
  -> durable approval record
  -> SQLite queue
  -> single Playwright worker
  -> evidence report
  -> compact Notion and signed-webhook summaries
```

SQLite is the source of truth for pilot run state, approvals, idempotency, and
audit events. Notion and Make.com are replaceable triggers and output adapters;
they do not authorize execution by changing a page or scenario status alone.

OpenRouter is a planning adapter, not an execution adapter. It can suggest
selectors and required extraction fields only after the service validates the
public navigation scope. Its response is still untrusted and non-executable.

### 7. Industry packs

Industry packs add terminology, field mappings, validation rules, and workflow examples without changing core safety behavior.

Examples:

- e-commerce;
- restaurant;
- real estate;
- education;
- marketing agency;
- professional services.

## Trust boundaries

Trusted instructions are limited to the runtime's higher-priority instructions, the approved user objective, and validated configuration.

Web pages, emails, documents, comments, advertisements, pop-ups, downloads, and metadata are untrusted data. They cannot expand scope, reveal secrets, or authorize actions.

## Multi-business isolation

Each client workspace has separate:

- configuration directory;
- approved-domain list;
- artifact and report location;
- enabled tasks;
- allowed output integrations;
- allowed read-only connector sources and properties;
- owner approval identity.

Authenticated adapters additionally require separate secret scope, browser
session storage, usage limits, and backup policy before they may be enabled.

Generated artifacts, browser state, and secrets stay outside source control.

## Approval model

There are two different approvals:

1. **Blueprint confirmation** authorizes generation of the final execution specification.
2. **Action-specific approval** authorizes one consequential runtime action after the exact target and effect are shown.

These approvals must never be treated as interchangeable.

## Idempotency and recovery

Read-only steps may retry within configured limits. State-changing steps require a durable operation identifier, before-and-after verification, and proof that a prior attempt did not succeed before retrying.

The service binds every accepted request to a unique idempotency key. Reusing a
key with different source or configuration data is rejected. A worker startup
may requeue a `running` job only after a configured stale interval greater than
the current maximum task timeout, and that recovery is appended to the audit
event stream.

## MVP boundary

Version 0.4 adds operator-owned client workspaces around the durable v0.3
service and v0.2 public-page, read-only
runtime. It performs no login,
clicking, form filling, submission, upload, download acceptance, or
state-changing action. This separation is intentional: the evidence and safety
path must be reliable before authenticated browser execution is introduced.

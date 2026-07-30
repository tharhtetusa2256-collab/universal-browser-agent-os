# Architecture

## Product goal

Universal Browser Agent OS is an industry-neutral control plane for turning a business outcome into a researched, reviewed, validated, and approval-gated browser workflow.

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

### 3. Workflow templates

Templates define repeatable tasks such as competitor research, website QA, product monitoring, lead research, and draft content preparation.

A template becomes client-specific only when combined with an approved business profile and task inputs.

### 4. Runtime adapters

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

### 5. Durable service

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

### 6. Industry packs

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

Each business should have separate:

- configuration directory;
- approved-domain list;
- GitHub Environment;
- secret scope;
- browser session storage;
- artifact and report location;
- usage and budget limits.

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

Version 0.3 adds a durable service around the v0.2 public-page, read-only
runtime. It performs no login,
clicking, form filling, submission, upload, download acceptance, or
state-changing action. This separation is intentional: the evidence and safety
path must be reliable before authenticated browser execution is introduced.

# Tharhtet Browser Agent

An operator-owned system for creating and running researched, reviewed,
validated, and approval-gated Browser Agent workflows across multiple clients.

**Tharhtet Browser Agent** is the product name. The repository, Python package,
environment variables, and `uba-*` commands keep their existing technical names
to preserve compatibility with installed environments and automation.

```text
Request -> Research -> Interview -> Feasibility -> Recommendation
        -> Blueprint -> CONFIRM -> Execution Specification
        -> Safe Test -> Action Approval -> Evidence Report
```

## Why this exists

Most browser-automation projects mix client details, prompts, credentials, browser code, and outputs in one fragile workflow. Tharhtet Browser Agent separates reusable core policy from business configuration, task templates, runtime adapters, and generated artifacts.

The repository owner operates the system privately. Each client receives an
isolated configuration and task workspace while the reusable safety and runtime
core remains unchanged. This is not a client-facing SaaS.

## Current release

**v0.6.1 — Deterministic Playwright / Browser Use tool router**

Included:

- deterministic LangGraph browser-workflow planning and risk classification;
- authenticated `POST /v1/plans/browser-workflow` planning endpoint;
- constrained OpenRouter workflow-intent preview through `POST /v1/plans/browser-workflow/ai-preview`;
- operator-controlled approved domains and start URLs that AI cannot expand;
- fail-closed consequential and unknown capability handling;
- `execution_authorized = false` invariant for planning and routing responses;
- multilingual committed planner-evaluation dataset covering read-only, consequential, and unknown capabilities;
- `uba-eval` CLI with deterministic fixture replay and explicit live OpenRouter evaluation modes;
- zero-cost GitHub Actions planner-evaluation gate with JSON report artifacts;
- exact capability-match, safety-gate, and authorization-invariant metrics;
- optional `browser-use[core]` runtime extra pinned to the 0.13 minor line;
- `uba-browser-use` CLI for manual, low-risk, public research pilots;
- Browser Use read-only tool allowlist with fail-closed upstream-action checks;
- approved-domain, public-DNS, and visited-URL validation around agentic navigation;
- Browser Use evidence reports without storing raw model thoughts / chain-of-thought;
- dedicated Browser Use dependency/tool compatibility CI without LLM API calls;
- deterministic `playwright` / `browser-use` / `blocked` runtime routing decisions;
- Playwright-safe-default routing with explicit Browser Use opt-in;
- fail-closed routing for consequential, unknown, unsupported-mode, and unsupported-output requests;
- deterministic Playwright routing for CSS selectors, CSV output, or strict request-level GET/HEAD-only requirements;
- `uba-route` non-executing CLI preview;
- authenticated `POST /v1/routes/browser-runtime` non-executing routing endpoint;
- repository-native `clients/<client-id>/` workspaces;
- client workspace schema and registry validation;
- client-scoped API run creation and history;
- owner-only blueprint approval for client runs;
- enforced `artifacts/clients/<client-id>/` output isolation;
- per-client external-integration allowlists;
- client-scoped Notion read-only data-source and property allowlists;
- `uba-notion-read` schema/query CLI with no write operations;
- client-scoped 1Password reference policy and fixed-command secret broker;
- redacted credential decision audit with no references, values, or arguments;
- `uba-secrets` metadata and brokered-run CLI;
- `uba-workspaces` operator validation CLI;
- authenticated FastAPI control-plane endpoints;
- idempotent run creation and durable SQLite run queue;
- durable blueprint approval and append-only audit events;
- a single-worker execution contract for low-cost VPS pilots;
- OpenRouter extraction previews that cannot authorize execution;
- optional Notion run summaries and signed Make.com-compatible webhooks;
- Docker Compose and Hostinger VPS deployment guidance;
- reusable Browser Agent prompt engineer;
- structured GitHub Issue Form;
- business-profile and browser-task contracts;
- Draft 2020-12 schema and policy validation;
- read-only competitor-research template;
- prompt-injection and approval-gate rules;
- GitHub Actions quality and secret checks;
- architecture and getting-started documentation;
- validated task loading for the Playwright adapter;
- exact approved-domain and public-network enforcement;
- GET/HEAD-only browser request policy with WebSockets blocked in the Playwright runtime;
- structured extraction with custom CSS selectors;
- retry, timeout, item-limit, missing-data, and duplicate controls;
- JSON, CSV, Markdown, screenshot, and Playwright trace evidence.

Not included yet:

- authenticated sessions;
- login, CAPTCHA, passkeys, or 2FA handling;
- clicking controls, filling forms, or submitting data;
- sending, publishing, purchasing, deleting, or account changes;
- automatic worker dispatch into Browser Use from a routing decision;
- hosted dashboard or SaaS billing.

This boundary is intentional. AI planning and runtime routing are non-executing.
The durable worker still uses the stricter Playwright runtime by default. Browser
Use remains an explicit, public read-only pilot until routing decisions are
persisted and separately wired into approved execution with evidence controls.

## Repository structure

```text
universal-browser-agent-os/
├── README.md
├── SECURITY.md
├── pyproject.toml
├── Dockerfile
├── compose.yml
├── clients/
│   ├── example-client/
│   │   ├── workspace.json
│   │   ├── business-profile.json
│   │   └── tasks/
│   └── tech-power/
│       ├── workspace.json
│       ├── business-profile.json
│       ├── notion-readonly.json
│       └── credential-references.json
├── evals/
│   └── planner-eval-dataset.json
├── src/
│   └── universal_browser_agent/
│       ├── agent/
│       ├── adapters/
│       ├── browser_use_cli.py
│       ├── router_cli.py
│       ├── evals.py
│       └── service/
├── prompts/
│   └── system/
├── schemas/
│   ├── business-profile.schema.json
│   ├── browser-task.schema.json
│   ├── client-workspace.schema.json
│   ├── credential-references.schema.json
│   └── notion-readonly.schema.json
├── configs/
│   └── example-business/
├── templates/
│   └── competitor-research/
├── scripts/
│   └── validate_configs.py
├── docs/
│   ├── ARCHITECTURE.md
│   ├── V0_5_LANGGRAPH_PLANNING.md
│   ├── V0_5_1_AI_PLANNER.md
│   ├── V0_5_2_PLANNER_EVALS.md
│   ├── V0_6_BROWSER_USE_READONLY.md
│   ├── V0_6_1_TOOL_ROUTER.md
│   ├── HOSTINGER_DEPLOYMENT.md
│   ├── adr/
│   └── GETTING_STARTED.md
└── .github/
    ├── ISSUE_TEMPLATE/
    ├── workflows/
    └── pull_request_template.md
```

## Local runtime quick start

Install the package and Chromium:

```bash
python -m pip install -r requirements-dev.txt
python -m playwright install chromium
```

Validate the safe example:

```bash
python scripts/validate_configs.py \
  --business configs/example-business/business-profile.json \
  --task templates/competitor-research/task.json
```

Run the example read-only task:

```bash
uba-run \
  --business configs/example-business/business-profile.json \
  --task templates/competitor-research/task.json
```

For one-off compatibility runs, use the profile and task paths above. For normal
multi-client operation, create a client workspace instead of passing arbitrary
configuration paths.

## Planner evaluation quick start

Run the committed zero-cost replay suite:

```bash
uba-eval \
  --mode fixture \
  --dataset evals/planner-eval-dataset.json \
  --min-capability-exact 1.0 \
  --min-safety-gate 1.0 \
  --output artifacts/evals/planner-eval-report.json
```

Run a cost-bearing live model evaluation only when explicitly desired:

```bash
export OPENROUTER_API_KEY='...'
uba-eval \
  --mode live \
  --dataset evals/planner-eval-dataset.json \
  --output artifacts/evals/live-planner-eval-report.json
```

The normal GitHub Actions planner-evaluation gate uses fixture mode only, so pull
requests do not spend AI API budget.

## Browser Use v0.6 quick start

Install the optional runtime only on machines that will run the pilot:

```bash
python -m pip install ".[browser-use]"
```

Provide the OpenRouter key through the environment, then run a validated public
research task manually:

```bash
export OPENROUTER_API_KEY='...'
export UBA_BROWSER_USE_MODEL='openai/gpt-4.1-mini'

uba-browser-use \
  --business configs/example-business/business-profile.json \
  --task templates/competitor-research/task.json \
  --max-steps 20
```

The Browser Use adapter exposes only read-only navigation/extraction tools and
fails closed if the installed upstream tool registry contains an unexpected
action. It is not used by the FastAPI worker automatically. See
[v0.6 Browser Use read-only adapter](docs/V0_6_BROWSER_USE_READONLY.md).

## Tool Router v0.6.1 quick start

Preview the safe-default routing decision without starting a browser:

```bash
uba-route \
  --business configs/example-business/business-profile.json \
  --task templates/competitor-research/task.json
```

Explicitly opt in to Browser Use when the task is eligible:

```bash
uba-route \
  --business configs/example-business/business-profile.json \
  --task templates/competitor-research/task.json \
  --agentic-navigation
```

The current competitor-research template requests CSV output, so it still routes
to Playwright. Browser Use is selected only for eligible public read-only tasks
whose output requirements fit the Browser Use evidence path and whose caller
explicitly requests agentic navigation.

The authenticated API preview is:

```text
POST /v1/routes/browser-runtime
```

Routing responses always contain `execution_authorized=false`; they do not start
a browser or bypass the existing approval flow. See
[v0.6.1 deterministic tool router](docs/V0_6_1_TOOL_ROUTER.md).

## Client workspace quick start

Inspect and validate the repository-native example:

```bash
uba-workspaces list
uba-workspaces validate --client example-client
```

A workspace binds its owner, business profile, enabled tasks, artifact root,
and allowed output integrations. Client task outputs must remain under
`artifacts/clients/<client-id>/`.

Create an approval-gated run through the preferred client API:

```text
POST /v1/clients/example-client/runs
Idempotency-Key: example-client:2026-07-31:public-research

{"task_id":"example-client-public-research","source":"api"}
```

The API stores the client and workspace identity with the run. Only the
manifest's `owner_id` can approve that client-scoped run.

A workspace may begin with no browser tasks when it has a connector-only pilot.
For the Tech Power Notion reader, inspect the committed allowlist first:

```bash
uba-notion-read list --client tech-power
uba-secrets list --client tech-power
```

The secret command displays policy metadata only. Real vaults, service accounts,
and tokens are not created by this repository. See the secret-management guide
before enabling brokered reads.

## Service quick start

Install the service and create a local environment file:

```bash
python -m pip install -r requirements-dev.txt
cp .env.example .env
```

Set a unique `UBA_API_TOKEN`, then start the API and worker in separate
terminals:

```bash
set -a
source .env
set +a
uba-api
```

```bash
set -a
source .env
set +a
uba-worker
```

Creating a run validates its configuration but leaves it in
`awaiting-blueprint-approval`. The worker cannot claim it until an explicit
approval is durably recorded. See
[Hostinger deployment](docs/HOSTINGER_DEPLOYMENT.md) for the API flow and VPS
configuration.

## Core principles

1. **Business-neutral core** — company and industry details live in configuration or optional packs.
2. **Approved-domain scope** — tasks cannot silently expand where the browser may navigate.
3. **Untrusted web content** — pages, emails, files, comments, ads, and pop-ups cannot override the approved objective.
4. **Two approval layers** — blueprint confirmation and action-specific approval are separate.
5. **No secrets in Git** — use environment-scoped secrets or an external secret manager.
6. **Evidence before success** — source URLs, timestamps, validation, and failure reporting are required.
7. **Test before side effects** — safe sample execution precedes production actions.
8. **Adapters over lock-in** — browser, AI, and output providers remain replaceable.

## Documentation

- [Architecture](docs/ARCHITECTURE.md)
- [v0.5 LangGraph planning](docs/V0_5_LANGGRAPH_PLANNING.md)
- [v0.5.1 AI planner](docs/V0_5_1_AI_PLANNER.md)
- [v0.5.2 planner evaluations](docs/V0_5_2_PLANNER_EVALS.md)
- [v0.6 Browser Use read-only adapter](docs/V0_6_BROWSER_USE_READONLY.md)
- [v0.6.1 deterministic tool router](docs/V0_6_1_TOOL_ROUTER.md)
- [Getting started](docs/GETTING_STARTED.md)
- [Tech Power client start](docs/TECH_POWER_CLIENT_START.md)
- [Notion read-only connector](docs/NOTION_READONLY_CONNECTOR.md)
- [Client secret management](docs/SECRET_MANAGEMENT.md)
- [Security policy](SECURITY.md)
- [Master prompt engineer](prompts/system/universal-browser-agent-prompt-engineer.md)

## Roadmap

### v0.2 — Read-only Playwright adapter

- [x] validated task loading;
- [x] approved-domain enforcement;
- [x] public-page navigation;
- [x] structured extraction;
- [x] screenshots, traces, JSON, CSV, and Markdown reports;
- [x] retry and timeout controls;
- [x] GitHub Actions test execution.

### v0.3 — Approval service

- [x] durable blueprint status;
- [x] idempotent run creation and recovery contract;
- [x] append-only approval and run audit events;
- [x] single-VPS API and worker deployment;
- [ ] test-to-production gate for a future production-capable runtime;
- [ ] action-specific execution approvals for future consequential adapters.

### v0.4 — Adapters and client workspaces

- [x] operator-owned multi-client workspace registry;
- [x] client-scoped runs, artifacts, approvals, and integration allowlists;
- [x] Notion summary, OpenRouter preview, and signed webhook foundations;
- [x] client-scoped secret-reference and broker foundation;
- [ ] Google Sheets, Airtable, and CRM outputs.

### v0.5 — Agent planning

- [x] LangGraph deterministic planning layer;
- [x] planning risk classification and fail-closed unknown capabilities;
- [x] non-executing authenticated planning endpoint;
- [x] constrained OpenRouter intent classification composed with deterministic policy;
- [x] AI preview endpoint that cannot authorize execution;
- [x] multilingual planner evaluation set and measurable safety metrics;
- [x] zero-cost CI planner-evaluation gate and report artifact;
- [ ] measured live-model routing accuracy across selected models.

### v0.6 — Agentic public read-only browsing

- [x] optional Browser Use dependency extra;
- [x] manual `uba-browser-use` pilot CLI;
- [x] fail-closed Browser Use action allowlist;
- [x] domain/public-DNS/history validation and evidence reports;
- [x] zero-LLM-cost Browser Use compatibility CI;
- [x] deterministic Playwright-vs-Browser-Use tool router;
- [ ] persist routing decisions with approved runs;
- [ ] dispatch approved eligible runs to Browser Use automatically;
- [ ] measured Browser Use success rate, intervention rate, latency, and cost per run;
- [ ] production routing approval after pilot evidence.

### v1.0 — Pilot-ready platform

- real vault/service-identity provisioning and authenticated session isolation;
- monitoring and audit trail;
- deployment guide;
- measured reliability and cost targets.

## Business model experiments

This system can support automation setup services, managed monthly workflows, industry template packs, and eventually a hosted workflow-design product. Validate demand with small paid pilots before building a large SaaS platform.

Measure manual time saved, completion rate, human intervention rate, error rate, cost per run, and value per run.

## License status

No open-source license has been selected yet. Public visibility does not automatically grant reuse rights. Choose a commercial or open-source licensing strategy before promoting external adoption.

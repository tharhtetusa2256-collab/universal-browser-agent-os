# Universal Browser Agent OS

An industry-neutral control plane for turning a business outcome into a researched, reviewed, validated, and approval-gated Browser Agent workflow.

```text
Request -> Research -> Interview -> Feasibility -> Recommendation
        -> Blueprint -> CONFIRM -> Execution Specification
        -> Safe Test -> Action Approval -> Evidence Report
```

## Why this exists

Most browser-automation projects mix client details, prompts, credentials, browser code, and outputs in one fragile workflow. Universal Browser Agent OS separates reusable core policy from business configuration, task templates, runtime adapters, and generated artifacts.

The same core can support e-commerce, restaurants, real estate, agencies, education, and professional services without rewriting safety logic for each business.

## Current release

**v0.3 — Approval-gated service foundation**

Included:

- authenticated FastAPI control-plane endpoints;
- idempotent run creation and durable SQLite run queue;
- durable blueprint approval and append-only audit events;
- a single-worker execution contract for low-cost VPS pilots;
- OpenRouter extraction previews that cannot authorize execution;
- optional Notion run summaries and signed Make.com-compatible webhooks;
- Docker Compose and Hostinger VPS deployment guidance;
- universal Browser Agent prompt engineer;
- structured GitHub Issue Form;
- business-profile and browser-task contracts;
- Draft 2020-12 schema and policy validation;
- read-only competitor-research template;
- prompt-injection and approval-gate rules;
- GitHub Actions quality and secret checks;
- architecture and getting-started documentation;
- validated task loading for the Playwright adapter;
- exact approved-domain and public-network enforcement;
- GET/HEAD-only browser request policy with WebSockets blocked;
- structured extraction with custom CSS selectors;
- retry, timeout, item-limit, missing-data, and duplicate controls;
- JSON, CSV, Markdown, screenshot, and Playwright trace evidence.

Not included yet:

- authenticated sessions;
- login, CAPTCHA, passkeys, or 2FA handling;
- clicking controls, filling forms, or submitting data;
- sending, publishing, purchasing, deleting, or account changes;
- hosted dashboard or SaaS billing.

This boundary is intentional. The runtime is deliberately limited to public,
read-only research until its safety and reliability are measured in pilot runs.

## Repository structure

```text
universal-browser-agent-os/
├── README.md
├── SECURITY.md
├── pyproject.toml
├── Dockerfile
├── compose.yml
├── src/
│   └── universal_browser_agent/
│       ├── adapters/
│       └── service/
├── prompts/
│   └── system/
├── schemas/
│   ├── business-profile.schema.json
│   └── browser-task.schema.json
├── configs/
│   └── example-business/
├── templates/
│   └── competitor-research/
├── scripts/
│   └── validate_configs.py
├── docs/
│   ├── ARCHITECTURE.md
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

Create a client implementation by copying the example profile and a task template. Change configuration, not core safety rules.

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
- [Getting started](docs/GETTING_STARTED.md)
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

### v0.4 — Adapters and industry packs

- [x] Notion summary, OpenRouter preview, and signed webhook foundations;
- [ ] Google Sheets, Airtable, and CRM outputs;
- e-commerce, restaurant, real-estate, agency, education, and professional-services packs.

### v1.0 — Pilot-ready platform

- multi-business isolation;
- monitoring and audit trail;
- deployment guide;
- measured reliability and cost targets.

## Business model experiments

This system can support automation setup services, managed monthly workflows, industry template packs, and eventually a hosted workflow-design product. Validate demand with small paid pilots before building a large SaaS platform.

Measure manual time saved, completion rate, human intervention rate, error rate, cost per run, and value per run.

## License status

No open-source license has been selected yet. Public visibility does not automatically grant reuse rights. Choose a commercial or open-source licensing strategy before promoting external adoption.

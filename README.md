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

**v0.1 — Universal Control Plane MVP**

Included:

- universal Browser Agent prompt engineer;
- structured GitHub Issue Form;
- business-profile and browser-task contracts;
- dependency-free Python validation;
- read-only competitor-research template;
- prompt-injection and approval-gate rules;
- GitHub Actions quality and secret checks;
- architecture and getting-started documentation.

Not included yet:

- live browser execution;
- authenticated sessions;
- login, CAPTCHA, passkeys, or 2FA handling;
- sending, publishing, purchasing, deleting, or account changes;
- hosted dashboard or SaaS billing.

This boundary is intentional. The next milestone is a safe read-only Playwright adapter.

## Repository structure

```text
universal-browser-agent-os/
├── README.md
├── SECURITY.md
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
│   └── GETTING_STARTED.md
└── .github/
    ├── ISSUE_TEMPLATE/
    ├── workflows/
    └── pull_request_template.md
```

## Quick start

Validate the safe example:

```bash
python scripts/validate_configs.py \
  --business configs/example-business/business-profile.json \
  --task templates/competitor-research/task.json
```

Create a client implementation by copying the example profile and a task template. Change configuration, not core safety rules.

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

- validated task loading;
- approved-domain enforcement;
- public-page navigation;
- structured extraction;
- screenshots, traces, JSON, CSV, and Markdown reports;
- retry and timeout controls;
- GitHub Actions test execution.

### v0.3 — Approval service

- durable blueprint status;
- test-to-production gate;
- action-specific approval records;
- idempotency and recovery contracts.

### v0.4 — Adapters and industry packs

- Google Sheets, Notion, Airtable, CRM, and webhook outputs;
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

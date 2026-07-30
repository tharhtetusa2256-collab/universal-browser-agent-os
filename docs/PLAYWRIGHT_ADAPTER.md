# Read-only Playwright adapter

This adapter is the first executable runtime for Universal Browser Agent OS. It intentionally supports public, read-only browsing only.

## Safety boundary

The adapter:

- accepts only `research-only` and `test` tasks;
- requires login, sending, publishing, purchasing, deleting, permission changes, confidential uploads, and access-control bypass to remain prohibited;
- rejects tasks containing consequential actions;
- allows only HTTP and HTTPS URLs on approved domains;
- rejects embedded URL credentials, IP-literal targets, non-standard ports, and DNS results that are private, loopback, link-local, reserved, or otherwise non-global;
- blocks network requests outside the approved-domain allowlist;
- disables downloads and service workers;
- performs no clicks, form submission, login, session restoration, or file upload;
- produces JSON, CSV, Markdown, timestamps, source URLs, screenshots, errors, and blocked-request evidence.

Because all third-party network requests are blocked, some pages that depend on external CDNs may render partially. Expand the task contract with a separately reviewed resource-domain allowlist rather than silently weakening the main domain policy.

## Install

```bash
python -m pip install -r requirements-dev.txt
python -m pip install -r requirements-runtime.txt
playwright install chromium
```

## Validate first

```bash
python scripts/validate_configs.py \
  --business configs/example-business/business-profile.json \
  --task templates/competitor-research/task.json
```

## Run

When `inputs.urls` is absent, the adapter visits the HTTPS homepage of each approved domain.

```bash
python -m adapters.browsers.playwright.runner \
  --task templates/competitor-research/task.json
```

To test visible browser behavior locally:

```bash
python -m adapters.browsers.playwright.runner \
  --task templates/competitor-research/task.json \
  --headed
```

The task's `outputs.destination` controls the default artifact directory. A trusted operator may override it:

```bash
python -m adapters.browsers.playwright.runner \
  --task templates/competitor-research/task.json \
  --output /tmp/browser-agent-evidence
```

## Optional explicit URLs

The task schema permits additional input fields. Add URLs only when every hostname remains inside `approved_domains`:

```json
{
  "inputs": {
    "urls": [
      "https://example.com/products",
      "https://example.org/services"
    ],
    "keywords": ["sample product"]
  }
}
```

## Generated evidence

```text
artifacts/<task-id>/
├── report.json
├── report.csv
├── report.md
└── 001-https-example.com.png
```

A run is marked `completed-with-errors` when one or more pages fail. Failures are recorded instead of being hidden.

## Current limitations

- no authenticated sessions;
- no CAPTCHA, passkeys, biometrics, 2FA, or account recovery;
- no interaction or state-changing actions;
- no browser process sandbox orchestration beyond Playwright defaults;
- no durable job queue, approval service, retries, traces, or distributed worker isolation yet;
- DNS checks reduce SSRF risk but are not a complete defense against every DNS-rebinding scenario.

The next implementation steps should add CI smoke tests, trace capture, bounded retries, isolated worker containers, and signed task specifications before any authenticated browsing is considered.

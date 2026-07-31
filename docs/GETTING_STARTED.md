# Getting Started

## 1. Create a client workspace

Copy the complete example workspace:

```text
clients/example-client/
```

Rename the directory and set the same lowercase slug in `workspace.json` and
`business-profile.json`. Set `owner_id` to the repository operator identity
that will record approvals. Keep credentials, cookies, tokens, and private data
out of every workspace file.

A client may start with an empty `tasks` array for a connector-only pilot. Bind
an optional read-only connector through a validated workspace config, then add a
runtime task only after the connector contract and sample output pass review.

## 2. Add client-scoped tasks

The first safe template is:

```text
templates/competitor-research/task.json
```

Copy a template into `clients/<client-id>/tasks/`, bind its
`business_profile` to the client profile, and register it in `workspace.json`.
Replace example domains, keywords, limits, and output requirements. Start with
`research-only` or `test` mode. Its destination must remain under
`artifacts/clients/<client-id>/`.

## 3. Validate locally

From the repository root:

```bash
python -m pip install -r requirements-dev.txt
python -m playwright install chromium
uba-workspaces validate --client example-client
python scripts/validate_configs.py \
  --business clients/example-client/business-profile.json \
  --task clients/example-client/tasks/public-research.json
```

The validator enforces the Draft 2020-12 JSON Schemas, then checks domain syntax,
limits, approval policy, policy compatibility, repository-relative paths, and
secret-like field names.

## 4. Submit a workflow request

Use GitHub Issues and select **Tharhtet Browser Agent Request**. Describe the business outcome, approved domains, inputs, outputs, scale, login requirements, consequential actions, runtime, and proof of success.

## 5. Run the prompt-engineering lifecycle

Use:

```text
prompts/system/universal-browser-agent-prompt-engineer.md
```

The assistant should research, interview, assess feasibility, compare options, present a blueprint, and wait for `CONFIRM` before creating the final execution prompt.

## 6. Review through a pull request

Store approved prompts, templates, schemas, and adapters in a feature branch. GitHub Actions checks example configuration, JSON syntax, required safety sections, and likely committed secrets.

## 7. Create a client-scoped service run

Prefer `POST /v1/clients/{client_id}/runs` with a registered `task_id`. The
service resolves configuration paths from the validated manifest, stores the
client identity on the run, and waits for the configured owner to approve the
blueprint. Use `GET /v1/clients/{client_id}/runs` for client-specific history.

## 8. Run the read-only adapter directly

Add explicit `inputs.start_urls` and optional `inputs.selectors` to the task.
Every start URL and browser request must use an exact approved domain.

```bash
uba-run \
  --business clients/example-client/business-profile.json \
  --task clients/example-client/tasks/public-research.json
```

The adapter:

- accepts a validated `research-only` or `test` task;
- permits only HTTP GET and HEAD and blocks WebSockets;
- enforces exact approved domains on navigation, redirects, and subresources;
- blocks non-public DNS results and non-standard ports;
- records source URLs and timestamps;
- exports JSON, CSV, Markdown, screenshots, and a Playwright trace;
- performs no login or state-changing action.

Outputs must remain under `artifacts/`, `results/`, or `reports/generated/`.
These locations are excluded from source control.

## Recommended first pilot

Use one public-domain competitor research workflow with no login, ten or fewer items, one safe sample run, and manual review of every output.

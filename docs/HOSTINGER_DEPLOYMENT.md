# Hostinger VPS deployment

This deployment runs the v0.3 API and one read-only worker. It does not enable
login, clicking, form submission, publishing, purchasing, deletion, or any
other state-changing browser action.

## Prerequisites

- a Hostinger VPS with Docker Engine and Docker Compose;
- a DNS name pointing to the VPS;
- HTTPS termination through Nginx, Caddy, or another maintained reverse proxy;
- firewall access limited to SSH, HTTP, and HTTPS;
- repository access from the VPS.

Do not deploy the Playwright worker to shared hosting. It needs an isolated VPS
or container host.

## Configure

```bash
cp .env.example .env
openssl rand -hex 32
```

Put the generated value in `UBA_API_TOKEN`. Add OpenRouter, Notion, and webhook
values only when those adapters are required. Never commit `.env`.

The Notion database must have a title property matching
`UBA_NOTION_TITLE_PROPERTY`. The default is `Name`.

## Start

```bash
docker compose build
docker compose up -d
docker compose ps
curl http://127.0.0.1:8000/health
```

Keep port 8000 bound to `127.0.0.1`. Publish the API only through an HTTPS
reverse proxy.

## Safe API flow

Create a run. This validates both files but does not execute the browser:

```bash
curl -X POST https://agent.example.com/v1/runs \
  -H "Authorization: Bearer $UBA_API_TOKEN" \
  -H "Idempotency-Key: notion-page-12345-v1" \
  -H "Content-Type: application/json" \
  -d '{
    "business_profile": "configs/example-business/business-profile.json",
    "task_spec": "templates/competitor-research/task.json",
    "source": "notion"
  }'
```

Review the objective and every approved domain. Then record the blueprint
decision:

```bash
curl -X POST https://agent.example.com/v1/runs/RUN_ID/approvals \
  -H "Authorization: Bearer $UBA_API_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "kind": "blueprint",
    "decision": "approved",
    "actor": "repository-owner",
    "details": {
      "objective_reviewed": true,
      "domains_reviewed": true
    }
  }'
```

The worker can claim the run only after that approval. Read the run and its
audit events:

```bash
curl https://agent.example.com/v1/runs/RUN_ID \
  -H "Authorization: Bearer $UBA_API_TOKEN"
```

At startup, the worker requeues jobs that have remained `running` longer than
`UBA_STALE_RUN_MINUTES`. Keep that value above the maximum configured browser
task timeout so a slow but healthy task is not reclaimed.

## Notion and Make.com

Notion or Make.com can create a run through the same API using a unique
`Idempotency-Key`. They must not write directly to the SQLite database.

When configured, the worker writes a compact run summary to the Notion database
and sends a signed HTTPS event to `UBA_OUTBOUND_WEBHOOK_URL`. Output delivery
failures are audit events and do not erase the browser evidence.

OpenRouter is available only through `/v1/plans/extraction-preview`. Its result
is marked `executable: false`; it must be copied into a task, validated, and
approved before a run is created.

## Backups and recovery

Stop the worker before taking a filesystem-level database backup:

```bash
docker compose stop worker
docker compose exec api python -c \
  "import sqlite3; src=sqlite3.connect('/app/service-data/browser-agent.sqlite3'); dst=sqlite3.connect('/app/service-data/backup.sqlite3'); src.backup(dst); dst.close(); src.close()"
docker compose start worker
```

Back up the database and the artifact volumes together. Test restoration before
using the service for a paid pilot.

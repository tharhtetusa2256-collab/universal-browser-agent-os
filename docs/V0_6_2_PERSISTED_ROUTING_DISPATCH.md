# v0.6.2 Persisted routing and approved worker dispatch

v0.6.2 turns the v0.6.1 deterministic runtime decision into durable run state and lets the worker dispatch only a route that was persisted before approval and locked by blueprint approval.

## Lifecycle

```text
Create validated run
  -> persist Playwright safe-default routing
  -> optional pre-approval routing update
  -> blueprint approval
  -> lock routing decision atomically
  -> queued
  -> worker claims only a locked route
  -> dispatch Playwright or Browser Use
  -> unified runtime metadata + evidence
```

Routing still cannot authorize execution by itself. Every routing snapshot must contain `execution_authorized=false`.

## Safe default

Every newly created run receives a persisted Playwright decision derived from the validated task. Browser Use is never selected implicitly.

A Browser Use route requires all of the following:

- a task that is already eligible under the v0.6.1 deterministic router;
- no CSS selectors that require deterministic Playwright extraction;
- no CSV output requirement;
- no strict request-level GET/HEAD-only requirement;
- explicit `agentic_navigation=true` before blueprint approval;
- `UBA_BROWSER_USE_WORKER_ENABLED=true`;
- `OPENROUTER_API_KEY` configured;
- blueprint approval with `runtime_route_reviewed=true`.

## Durable run fields

SQLite `runs` records now include:

- `routing_json` — the canonical routing snapshot;
- `route_locked_at` — timestamp written when an approved blueprint locks the route.

The API includes both through the normal run representation as `routing` and `route_locked_at`.

## Pre-approval route update

Use:

```text
POST /v1/runs/{run_id}/routing
Authorization: Bearer ...

{
  "actor": "owner",
  "agentic_navigation": true,
  "require_request_level_get_head_only": false
}
```

The server reloads the stored validated task and derives mode, selectors, and output formats itself. Callers cannot replace those task facts through this endpoint.

Client-scoped runs may be changed only by the configured workspace owner.

Routing can change only while the run is `awaiting-blueprint-approval`. After approval locks the route, rerouting fails closed.

## Blueprint approval and route lock

Playwright safe-default approvals remain compatible with the existing confirmations:

```json
{
  "objective_reviewed": true,
  "domains_reviewed": true
}
```

Browser Use requires one additional explicit confirmation:

```json
{
  "objective_reviewed": true,
  "domains_reviewed": true,
  "runtime_route_reviewed": true
}
```

The approval row, queued state, and route lock are written in the same SQLite transaction so another process cannot change the selected runtime between approval and queueing.

## Worker dispatch

The durable worker claims only rows that are:

- `queued`;
- have `routing_json`;
- have `route_locked_at`.

It emits `runtime.dispatched` and runs exactly the locked route:

- `playwright` -> `ReadOnlyPlaywrightRuntime`;
- `browser-use` -> `BrowserUseReadOnlyAdapter`;
- any other route -> fail closed.

Browser Use remains public and read-only. This milestone does not add login, persistent sessions, clicks, form filling, uploads, submission, publishing, purchasing, deletion, account changes, CAPTCHA solving, 2FA automation, stealth, or access-control bypass.

## Unified result metadata

Both runtime result shapes receive:

- `runtime_route`;
- `routing_router`;
- `route_locked_at`.

The underlying runtime evidence remains adapter-specific so existing Playwright evidence consumers are not broken.

## Audit events

v0.6.2 adds or enriches:

- `routing.selected`;
- `routing.updated`;
- `routing.locked`;
- `run.started` with runtime route;
- `runtime.dispatched`;
- `run.completed` / `run.failed` with runtime route.

## Legacy SQLite migration

Existing databases receive the new columns automatically. Rows without routing metadata are assigned the Playwright safe-default. Existing queued, running, completed, and failed rows also receive a reconstructed route lock using their last update timestamp. This preserves old approved jobs without silently introducing Browser Use.

## Deployment

The standard Docker image now installs the pinned Browser Use optional extra so the same worker image can execute either approved read-only route. Browser Use dispatch remains disabled by default:

```text
UBA_BROWSER_USE_WORKER_ENABLED=false
```

Enable only after setting `OPENROUTER_API_KEY` and reviewing the Browser Use public read-only boundary.

## Next milestone

After v0.6.2 is stable, the next step should measure Browser Use versus Playwright success rate, latency, intervention rate, and cost per run before broad production routing is enabled.

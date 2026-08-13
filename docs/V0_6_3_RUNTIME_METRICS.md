# v0.6.3 Runtime evaluation and metrics

v0.6.3 adds a normalized measurement layer to approved public read-only worker runs. It does not add browser permissions or authenticated sessions.

## Goal

Measure Playwright and Browser Use with comparable operational fields before broadening Browser Use deployment or adding authenticated browsing.

```text
approved locked run
  -> worker dispatch
  -> Playwright or Browser Use
  -> adapter evidence
  -> normalized runtime_metrics
  -> durable run result
  -> authenticated metrics API
  -> route comparison
```

## Durable metrics snapshot

The worker stores `runtime_metrics` inside the existing durable `runs.result_json` record. This avoids a new database migration during the pilot while keeping the metrics coupled to the evidence-producing run.

Normalized fields include:

- `runtime_route`
- `runtime_status`
- `succeeded`
- `duration_ms`
- `retry_count` when an adapter reports it
- `step_count` when an adapter reports it
- `item_count`
- `failure_count`
- `blocked_request_count`
- `worker_attempt_count`
- `stale_requeue_count`
- `human_intervention_required`
- `intervention_reason`
- `error_category`
- `model`
- prompt/completion/total token counts when reported
- estimated model cost when reported
- provider usage summary when reported

Playwright does not call an LLM in the current runtime, so its token counts and estimated model cost are recorded as zero. Browser Use cost and token fields are populated only from Browser Use's provider-reported usage summary; they are not estimated from text length.

## Timing

`duration_ms` is worker wall-clock execution time measured around the approved adapter run. Browser Use additionally exposes adapter step count and adapter-reported step duration for evidence, while the normalized comparison uses worker wall-clock duration.

## Human intervention

The Browser Use observed adapter records only a coarse operational label such as:

- `captcha`
- `auth-challenge`
- `authentication`
- `access-challenge`

It does not persist model chain-of-thought. Existing policy still stops rather than bypassing CAPTCHA, passkeys, 2FA, login requirements, or access controls.

## Error categories

Raw runtime failures are normalized to stable categories for comparison, including:

- `policy`
- `timeout`
- `network`
- `provider-rate-limit`
- `model-provider`
- human-intervention categories
- `partial-errors`
- `runtime`

The original adapter evidence remains available separately for debugging.

## Worker attempts versus adapter retries

`worker_attempt_count` counts durable worker claims for the same run. `stale_requeue_count` records stale-lease recoveries. These are intentionally separate from `retry_count`, which is reserved for adapter-level retry reporting when available.

## Metrics API

All metrics endpoints require the existing bearer-token authentication.

Per-run snapshot:

```text
GET /v1/runs/{run_id}/metrics
```

Aggregate Playwright-versus-Browser-Use summary:

```text
GET /v1/metrics/runtime
GET /v1/metrics/runtime?route=playwright
GET /v1/metrics/runtime?route=browser-use
GET /v1/metrics/runtime?client_id=example-client
```

Recent normalized snapshots:

```text
GET /v1/metrics/runtime/runs
```

The summary includes success rate, average and p95 duration, human intervention rate, worker attempts, stale requeues, items, failures, blocked requests, token-reporting coverage, estimated cost-reporting coverage, and error-category counts.

## Browser Use usage source

The observed Browser Use worker adapter keeps `calculate_cost=True` and reads the structured `history.usage` summary returned by Browser Use. If the installed provider/runtime does not supply usage, token and cost fields remain unknown rather than being guessed.

## Safety boundary

v0.6.3 remains public read-only browsing. It does not add:

- login or authenticated session persistence
- click/input/upload/submit/publish/purchase/delete/account-change capabilities
- CAPTCHA or 2FA automation
- stealth or access-control bypass
- autonomous runtime authorization

Routing, approval, domain restrictions, Browser Use tool allowlists, Playwright GET/HEAD policy, and evidence controls remain authoritative.

## Next gate

Collect pilot evidence across representative public websites before deciding whether Browser Use should be enabled more broadly. The next decision should be based on measured success rate, latency, human intervention rate, and cost per run rather than framework preference.

# v0.6.1 Deterministic Tool Router

v0.6.1 adds a **decision-only runtime router** between the planning/approval
layer and the browser adapters.

The router does not start a browser, does not grant approval, and never turns
model output into execution authorization.

## Routing contract

Every decision is exactly one of:

- `playwright`
- `browser-use`
- `blocked`

`execution_authorized` is always `false`.

## Safe default

Playwright remains the default runtime.

Browser Use is selected only when all of these conditions are true:

1. task mode is `research-only` or `test`;
2. requested capabilities are known read-only capabilities;
3. no consequential capability is requested;
4. no unknown capability is requested;
5. no deterministic CSS selectors are required;
6. output formats are supported by the Browser Use evidence path;
7. request-level GET/HEAD-only network enforcement is not required; and
8. the operator/control plane explicitly sets `agentic_navigation=true`.

If Browser Use is not explicitly opted in, the route is Playwright.

## Fail-closed cases

The router returns `blocked` instead of falling back when it sees:

- an unsupported task mode;
- a consequential capability such as `submit`, `publish`, `purchase`, or
  account change;
- an unknown capability; or
- an output format unsupported by both current runtimes.

This prevents a routing fallback from accidentally weakening policy.

## Why CSV routes to Playwright

The v0.6 Browser Use evidence adapter currently writes JSON, Markdown, and
screenshots. The existing Playwright runtime also supports CSV. Therefore a task
that requires CSV deterministically routes to Playwright even if agentic
navigation is requested.

## Why selectors route to Playwright

A task with explicit CSS selectors already contains a deterministic extraction
contract. The router therefore chooses Playwright instead of handing that task
to an agentic navigator.

## Why strict network policy routes to Playwright

The Playwright runtime enforces the repository's stronger request-level policy,
including GET/HEAD-only browser requests and blocked WebSockets. Browser Use
v0.6 applies top-level domain/tool controls but does not claim the same
subresource invariant. Setting `require_request_level_get_head_only=true`
therefore forces Playwright.

## CLI preview

The router can be evaluated against a validated task without starting a browser:

```bash
uba-route \
  --business configs/example-business/business-profile.json \
  --task templates/competitor-research/task.json
```

Explicit Browser Use opt-in:

```bash
uba-route \
  --business configs/example-business/business-profile.json \
  --task templates/competitor-research/task.json \
  --agentic-navigation
```

Request a strict Playwright network boundary:

```bash
uba-route \
  --business configs/example-business/business-profile.json \
  --task templates/competitor-research/task.json \
  --agentic-navigation \
  --require-strict-network
```

Capabilities can be supplied explicitly with repeated `--capability` flags.
Consequential or unknown values return a blocked decision and a non-zero CLI
status.

## API preview

Authenticated control-plane clients can call:

```text
POST /v1/routes/browser-runtime
```

Example request:

```json
{
  "mode": "research-only",
  "requested_capabilities": ["navigate", "extract"],
  "selectors_present": false,
  "output_formats": ["json", "markdown", "screenshots"],
  "agentic_navigation": true,
  "require_request_level_get_head_only": false
}
```

The response contains the route, stable reason/blocker codes, normalized inputs,
and `execution_authorized=false`.

## Current boundary

v0.6.1 is intentionally **routing-only**.

It does not yet:

- change the durable worker to automatically dispatch Browser Use;
- install Browser Use in the default production image;
- create authenticated sessions;
- enable login, form submission, messaging, publishing, purchasing, deletion,
  or account changes;
- solve or bypass CAPTCHA, passkeys, or 2FA.

A later milestone can connect approved runs to the selected adapter after the
routing decision is persisted and evidence/rollback behavior is defined.

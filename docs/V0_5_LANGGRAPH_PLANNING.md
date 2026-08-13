# v0.5 LangGraph Planning Layer

## Goal

Version 0.5 introduces LangGraph as a planning layer without replacing the
existing FastAPI control plane, SQLite run queue, workspace isolation, approval
records, or read-only Playwright runtime.

The first graph is deliberately deterministic. It establishes a stable state
contract and routing boundary before any LLM is allowed to participate in
planning.

## Flow

```text
Request
  -> normalize_intake
  -> classify_risk
  -> build_plan
  -> blueprint review
  -> existing approval flow
  -> existing runtime
```

The graph never authorizes execution. `execution_authorized` is always false in
the planning response.

## API

Authenticated endpoint:

```text
POST /v1/plans/browser-workflow
```

Example request:

```json
{
  "objective": "Research the approved public website and extract its title",
  "approved_domains": ["example.com"],
  "start_urls": ["https://example.com/"],
  "requested_capabilities": ["navigate", "extract", "screenshot"]
}
```

Read-only capabilities are classified as low risk and may proceed to blueprint
review. Consequential capabilities such as fill, submit, publish, purchase,
delete, or account changes are fail-closed and require human review. Unknown
capabilities are also fail-closed.

## Security boundary

This version does not add:

- authenticated browser sessions;
- credential entry;
- CAPTCHA, passkey, or 2FA automation;
- browser form submission;
- publishing, purchasing, deletion, permission changes, or account changes;
- autonomous execution based on model output.

The existing action-specific approval policy remains authoritative.

## Why deterministic first

A deterministic graph gives the project a testable state and routing contract
without introducing model cost or model-generated execution authority. A later
version can add an OpenAI or OpenRouter planning node that produces suggestions
inside this boundary. Model output must remain untrusted input to policy and
approval nodes.

## Runtime requirements

v0.5 standardizes the project on Python 3.12 and adds `langgraph>=1.2,<2`.
The Docker image and GitHub Actions environment already use Python 3.12.

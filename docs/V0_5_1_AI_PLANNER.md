# v0.5.1 AI Workflow Planner

## Goal

v0.5.1 adds model-assisted intent classification in front of the deterministic
LangGraph planning policy. The model may help interpret an operator objective,
but it cannot expand browser scope, approve an action, create a runnable task,
or authorize execution.

## Flow

```text
Operator objective + approved domains + start URLs
  -> OpenRouter workflow-intent draft
  -> deterministic LangGraph normalization and risk classification
  -> non-executable policy plan
  -> human blueprint review
  -> existing validated run and approval flow
```

## Operator-controlled scope

The API caller supplies `approved_domains` and `start_urls`. These values are
validated before the model is called. The model receives them as immutable
context and does not return replacement domains or URLs.

The model returns only:

- `task_summary`;
- `requested_capabilities`;
- `notes`.

Unexpected response fields are rejected.

## Deterministic policy remains authoritative

Model capabilities are passed through `BrowserWorkflowPlanner`. Known
read-only capabilities may reach `ready-for-blueprint-review`. Consequential
capabilities such as `fill`, `submit`, `publish`, `purchase`, or `delete` are
classified as high risk and require human approval. Unknown capabilities are
fail-closed and require review.

Every planning response keeps `execution_authorized = false`.

## API

```text
POST /v1/plans/browser-workflow/ai-preview
Authorization: Bearer <UBA_API_TOKEN>
```

Example body:

```json
{
  "objective": "Research approved public product pages and summarize products",
  "approved_domains": ["example.com"],
  "start_urls": ["https://example.com/"]
}
```

The endpoint requires `OPENROUTER_API_KEY`. `UBA_OPENROUTER_MODEL` selects the
configured model. The existing `/v1/plans/browser-workflow` deterministic
endpoint remains available without a model call.

## Safety boundaries

v0.5.1 does not add:

- authenticated browser sessions;
- login automation;
- CAPTCHA, passkey, or 2FA automation;
- anti-bot evasion;
- form submission or publishing execution;
- autonomous domain discovery that expands scope;
- model-created approval records;
- direct model access to credentials.

Browser execution remains limited by the existing runtime and approval system.

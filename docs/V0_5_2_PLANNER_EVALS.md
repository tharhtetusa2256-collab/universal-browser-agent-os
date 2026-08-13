# v0.5.2 — Planner Evaluation Gates

## Purpose

v0.5.2 adds measurable quality gates around the constrained AI workflow planner.
The evaluation system does not execute browser actions and does not grant
approval. It measures whether model capability classification matches expected
intent and whether deterministic LangGraph policy produces the expected safety
result.

## Evaluation flow

```text
Evaluation case
    -> intent provider
       -> fixture replay (CI, zero cost)
       -> OpenRouter live model (manual, cost-bearing)
    -> predicted capabilities
    -> deterministic LangGraph policy
    -> risk + status + execution_authorized
    -> metrics and report
```

The model never determines whether execution is authorized. Every evaluated
intent is passed through `BrowserWorkflowPlanner`, and the report explicitly
checks that `execution_authorized` remains `false` for every case.

## Dataset

The committed dataset is:

```text
evals/planner-eval-dataset.json
```

Dataset version 1.0 contains multilingual English and Burmese cases covering:

- public read-only navigation and reading;
- structured extraction;
- screenshots and evidence;
- clicking, form filling, and submission;
- file upload and message sending;
- publishing and purchasing;
- deletion and cancellation;
- permission and account changes;
- unknown future capabilities that must fail closed;
- mixed read-only and consequential objectives.

Each case defines the expected capabilities, expected risk level, expected
planning status, and a committed fixture model response for deterministic replay.

## Metrics

The evaluator records:

- exact capability-match rate;
- safety-gate correctness rate;
- missing and unexpected capabilities per case;
- expected versus actual risk level;
- expected versus actual planning status;
- execution-authorization invariant violations;
- overall threshold pass/fail.

The default thresholds are:

```text
capability exact rate >= 95%
safety gate rate      >= 100%
authorization violations = 0
```

CI intentionally uses stricter fixture thresholds of 100% / 100% / 0.

## Zero-cost CI evaluation

Run locally:

```bash
uba-eval \
  --mode fixture \
  --dataset evals/planner-eval-dataset.json \
  --min-capability-exact 1.0 \
  --min-safety-gate 1.0 \
  --output artifacts/evals/planner-eval-report.json
```

The `Planner Evaluation Gate` GitHub Actions workflow runs this mode on pull
requests and pushes to `main`. It never calls OpenRouter and therefore adds no AI
API usage cost.

## Live model evaluation

Live evaluation is explicit and manual:

```bash
export OPENROUTER_API_KEY='...'
export UBA_OPENROUTER_MODEL='openai/gpt-4.1-mini'

uba-eval \
  --mode live \
  --dataset evals/planner-eval-dataset.json \
  --output artifacts/evals/live-planner-eval-report.json
```

Live mode can incur provider charges. It is deliberately excluded from normal CI
so pull requests cannot unexpectedly spend API budget.

## Safety invariants

v0.5.2 preserves the existing safety boundary:

1. Approved domains and start URLs come from the evaluation case/operator, not
   from the model.
2. Model output supplies capability intent only.
3. Consequential capabilities are classified as high risk and require approval.
4. Unknown capabilities fail closed and require review.
5. `execution_authorized` must remain `false` for every evaluation case.
6. Evaluation never creates run records, approval records, browser sessions, or
   state-changing actions.

## Next milestone

After planner behavior is measured with live-model runs, the next milestone is a
public, read-only browser-use adapter behind the same deterministic scope and
policy controls. Authenticated sessions and consequential write actions remain
separate later milestones.

"""Normalized runtime metrics shared by Playwright and Browser Use attempts."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class RuntimeMetrics:
    runtime_route: str
    runtime_status: str
    succeeded: bool
    duration_ms: int
    retry_count: int | None
    step_count: int | None
    item_count: int
    failure_count: int
    blocked_request_count: int
    human_intervention_required: bool
    intervention_reason: str | None
    error_category: str | None
    model: str | None
    prompt_tokens: int | None
    completion_tokens: int | None
    total_tokens: int | None
    estimated_cost_usd: float | None
    usage: dict[str, Any] | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def classify_runtime_error(error: str | None) -> str | None:
    """Map raw runtime errors to stable, non-sensitive reporting categories."""

    if not error:
        return None
    text = error.lower()
    if "captcha" in text:
        return "human-intervention-captcha"
    if any(value in text for value in ("2fa", "two-factor", "passkey", "otp")):
        return "human-intervention-auth-challenge"
    if any(value in text for value in ("login", "authentication", "human takeover")):
        return "human-intervention-authentication"
    if "policyviolation" in text or "policy violation" in text or "prohibited" in text:
        return "policy"
    if "timeout" in text or "timed out" in text:
        return "timeout"
    if "rate limit" in text or "ratelimit" in text or "429" in text:
        return "provider-rate-limit"
    if any(value in text for value in ("dns", "connection", "network", "http 5")):
        return "network"
    if "openrouter" in text or "modelprovider" in text or "llm" in text:
        return "model-provider"
    return "runtime"


def _safe_non_negative_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int) and value >= 0:
        return value
    return None


def _safe_non_negative_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)) and value >= 0:
        return float(value)
    return None


def _count_list(result: dict[str, Any], key: str) -> int:
    value = result.get(key)
    return len(value) if isinstance(value, list) else 0


def build_runtime_metrics(
    *,
    route: str,
    result: dict[str, Any],
    duration_ms: int,
    succeeded: bool,
    error: str | None = None,
) -> RuntimeMetrics:
    """Normalize adapter-specific evidence into one comparison-safe snapshot."""

    if route not in {"playwright", "browser-use"}:
        raise ValueError(f"Unsupported runtime route for metrics: {route}")
    if duration_ms < 0:
        raise ValueError("duration_ms must be non-negative")

    runtime_status = str(result.get("status") or ("completed" if succeeded else "failed"))
    retry_count = _safe_non_negative_int(result.get("retry_count"))
    step_count = _safe_non_negative_int(result.get("step_count"))

    if route == "playwright":
        item_count = _count_list(result, "items")
        failure_count = _count_list(result, "failures")
        blocked_request_count = _count_list(result, "blocked_requests")
        model = None
        prompt_tokens: int | None = 0
        completion_tokens: int | None = 0
        total_tokens: int | None = 0
        estimated_cost_usd: float | None = 0.0
        usage = None
    else:
        item_count = _count_list(result, "extracted_content")
        failure_count = _count_list(result, "errors")
        blocked_request_count = 0
        model_value = result.get("model")
        model = str(model_value) if isinstance(model_value, str) and model_value else None
        usage_value = result.get("usage")
        usage = usage_value if isinstance(usage_value, dict) else None
        prompt_tokens = (
            _safe_non_negative_int(usage.get("total_prompt_tokens")) if usage else None
        )
        completion_tokens = (
            _safe_non_negative_int(usage.get("total_completion_tokens")) if usage else None
        )
        total_tokens = _safe_non_negative_int(usage.get("total_tokens")) if usage else None
        estimated_cost_usd = (
            _safe_non_negative_float(usage.get("total_cost")) if usage else None
        )

    intervention_reason_value = result.get("intervention_reason")
    intervention_reason = (
        str(intervention_reason_value)
        if isinstance(intervention_reason_value, str) and intervention_reason_value
        else None
    )
    human_intervention_required = bool(result.get("human_intervention_required", False))

    category = classify_runtime_error(error)
    if category is None and not succeeded:
        candidate_errors: list[str] = []
        for key in ("errors", "failures"):
            values = result.get(key)
            if not isinstance(values, list):
                continue
            for value in values:
                if isinstance(value, str):
                    candidate_errors.append(value)
                elif isinstance(value, dict) and value.get("error"):
                    candidate_errors.append(str(value["error"]))
        category = classify_runtime_error(" ".join(candidate_errors)) or "runtime"
    elif category is None and failure_count > 0:
        category = "partial-errors"

    if intervention_reason is None and category and category.startswith("human-intervention-"):
        intervention_reason = category.removeprefix("human-intervention-")
        human_intervention_required = True

    return RuntimeMetrics(
        runtime_route=route,
        runtime_status=runtime_status,
        succeeded=succeeded,
        duration_ms=duration_ms,
        retry_count=retry_count,
        step_count=step_count,
        item_count=item_count,
        failure_count=failure_count,
        blocked_request_count=blocked_request_count,
        human_intervention_required=human_intervention_required,
        intervention_reason=intervention_reason,
        error_category=category,
        model=model,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=total_tokens,
        estimated_cost_usd=estimated_cost_usd,
        usage=usage,
    )

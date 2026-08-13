"""Observed Browser Use worker adapter with normalized usage metadata.

The browsing contract is inherited from BrowserUseReadOnlyAdapter. This wrapper
adds only operational metrics; it does not widen browser capabilities.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from ..policy import PolicyViolation
from .browser_use_readonly import (
    EXCLUDED_DEFAULT_ACTIONS,
    BrowserUseAdapterError,
    BrowserUseReadOnlyAdapter,
    _load_browser_use_core,
    _load_openrouter_model,
    enforce_read_only_tool_contract,
    installed_action_names,
)


@dataclass(frozen=True)
class ObservedBrowserUseRunSummary:
    run_id: str
    status: str
    report_path: str
    final_result: str | None
    visited_urls: tuple[str, ...]
    action_names: tuple[str, ...]
    screenshot_paths: tuple[str, ...]
    errors: tuple[str, ...]
    extracted_content: tuple[str, ...]
    model: str
    step_count: int
    adapter_duration_seconds: float
    usage: dict[str, Any] | None
    human_intervention_required: bool
    intervention_reason: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "status": self.status,
            "report_path": self.report_path,
            "final_result": self.final_result,
            "visited_urls": list(self.visited_urls),
            "action_names": list(self.action_names),
            "screenshot_paths": list(self.screenshot_paths),
            "errors": list(self.errors),
            "extracted_content": list(self.extracted_content),
            "model": self.model,
            "step_count": self.step_count,
            "adapter_duration_seconds": self.adapter_duration_seconds,
            "usage": self.usage,
            "human_intervention_required": self.human_intervention_required,
            "intervention_reason": self.intervention_reason,
        }


def _safe_usage_dump(history: Any) -> dict[str, Any] | None:
    usage = getattr(history, "usage", None)
    if usage is None:
        return None
    model_dump = getattr(usage, "model_dump", None)
    if not callable(model_dump):
        return None
    value = model_dump(mode="json")
    return value if isinstance(value, dict) else None


def _intervention_reason(
    history: Any,
    *,
    final_result: Any,
    errors: tuple[str, ...],
) -> str | None:
    judgement_fn = getattr(history, "judgement", None)
    judgement = judgement_fn() if callable(judgement_fn) else None
    if isinstance(judgement, dict) and judgement.get("reached_captcha") is True:
        return "captcha"

    text = " ".join(
        [str(final_result or ""), *(str(error) for error in errors)]
    ).lower()
    if "captcha" in text:
        return "captcha"
    if any(value in text for value in ("2fa", "two-factor", "passkey", "otp")):
        return "auth-challenge"
    if any(value in text for value in ("login", "authentication")):
        return "authentication"
    if "human takeover" in text or "access challenge" in text:
        return "access-challenge"
    return None


class ObservedBrowserUseReadOnlyAdapter(BrowserUseReadOnlyAdapter):
    """Browser Use read-only runtime that also returns provider usage metrics."""

    async def run(self) -> ObservedBrowserUseRunSummary:
        api_key = os.environ.get("OPENROUTER_API_KEY")
        if not api_key:
            raise BrowserUseAdapterError(
                "OPENROUTER_API_KEY is required for the v0.6 Browser Use pilot"
            )

        for url in self.task.start_urls:
            await self.policy.validate_url(url)

        Agent, BrowserProfile, Tools = _load_browser_use_core()
        ChatOpenRouter = _load_openrouter_model()
        tools = Tools(exclude_actions=list(EXCLUDED_DEFAULT_ACTIONS))
        allowed = installed_action_names(tools)
        enforce_read_only_tool_contract(allowed)

        visited_urls: list[str] = []

        async def validate_step(browser_state: Any, _model_output: Any, _step: int) -> None:
            url = getattr(browser_state, "url", None)
            if not url or url == "about:blank":
                return
            await self.policy.validate_url(str(url))
            visited_urls.append(str(url))

        llm = ChatOpenRouter(model=self.model, api_key=api_key)
        browser_profile = BrowserProfile(
            headless=self.headless,
            keep_alive=False,
            allowed_domains=list(self.task.approved_domains),
            block_ip_addresses=True,
        )
        agent = Agent(
            task=self._build_task_prompt(),
            llm=llm,
            tools=tools,
            browser_profile=browser_profile,
            use_vision="auto",
            max_actions_per_step=1,
            directly_open_url=False,
            initial_actions=[
                {
                    "navigate": {
                        "url": self.task.start_urls[0],
                        "new_tab": False,
                    }
                }
            ],
            sensitive_data=None,
            available_file_paths=[],
            register_new_step_callback=validate_step,
            calculate_cost=True,
            enable_signal_handler=False,
        )

        try:
            history = await agent.run(max_steps=self.max_steps)
        except PolicyViolation:
            raise
        except Exception as exc:
            raise BrowserUseAdapterError(
                f"Browser Use run failed: {type(exc).__name__}: {exc}"
            ) from exc

        action_names = tuple(str(name) for name in history.action_names())
        self._verify_executed_actions(action_names)

        history_urls = tuple(str(url) for url in history.urls() if url)
        for url in history_urls:
            if url != "about:blank":
                await self.policy.validate_url(url)

        final_result = history.final_result()
        errors = tuple(str(error) for error in history.errors() if error)
        successful = history.is_successful()
        status = "completed" if successful is True and not errors else "completed-with-errors"
        if successful is False:
            status = "failed"

        extracted_content = tuple(
            str(value) for value in history.extracted_content() if value is not None
        )
        usage = _safe_usage_dump(history)
        step_count_fn = getattr(history, "number_of_steps", None)
        step_count = int(step_count_fn()) if callable(step_count_fn) else len(history)
        duration_fn = getattr(history, "total_duration_seconds", None)
        adapter_duration_seconds = (
            float(duration_fn()) if callable(duration_fn) else 0.0
        )
        intervention_reason = _intervention_reason(
            history,
            final_result=final_result,
            errors=errors,
        )

        output_dir = self._output_dir()
        output_dir.mkdir(parents=True, exist_ok=True)
        screenshots = self._write_screenshots(history, output_dir)
        report_path = output_dir / "report.json"
        report = {
            "adapter": "browser-use-readonly-observed-v0.6.3",
            "run_id": self.run_id,
            "task_id": self.task.task_id,
            "status": status,
            "model": self.model,
            "objective": self.objective,
            "approved_domains": list(self.task.approved_domains),
            "start_urls": list(self.task.start_urls),
            "final_result": final_result,
            "visited_urls": list(dict.fromkeys((*visited_urls, *history_urls))),
            "action_names": list(action_names),
            "extracted_content": list(extracted_content),
            "errors": list(errors),
            "screenshots": list(screenshots),
            "step_count": step_count,
            "adapter_duration_seconds": adapter_duration_seconds,
            "usage": usage,
            "human_intervention_required": intervention_reason is not None,
            "intervention_reason": intervention_reason,
            "safety": {
                "execution_authorized": False,
                "authenticated_sessions": False,
                "sensitive_data_supplied": False,
                "state_changing_actions_available": False,
                "anti_bot_bypass_enabled": False,
            },
            "finished_at": datetime.now(timezone.utc).isoformat(),
        }
        report_path.write_text(
            json.dumps(report, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        self._write_markdown_report(report, output_dir / "report.md")

        return ObservedBrowserUseRunSummary(
            run_id=self.run_id,
            status=status,
            report_path=str(report_path),
            final_result=str(final_result) if final_result is not None else None,
            visited_urls=tuple(report["visited_urls"]),
            action_names=action_names,
            screenshot_paths=screenshots,
            errors=errors,
            extracted_content=extracted_content,
            model=self.model,
            step_count=step_count,
            adapter_duration_seconds=adapter_duration_seconds,
            usage=usage,
            human_intervention_required=intervention_reason is not None,
            intervention_reason=intervention_reason,
        )

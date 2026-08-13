"""Deterministic policy router for choosing a browser runtime.

The router is decision-only. It never starts a browser, never grants approval,
and never converts AI/model output into execution authorization.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from .planning import CONSEQUENTIAL_CAPABILITIES, READ_ONLY_CAPABILITIES

RuntimeRoute = Literal["playwright", "browser-use", "blocked"]

PLAYWRIGHT_OUTPUT_FORMATS = frozenset({"json", "csv", "markdown", "screenshots"})
BROWSER_USE_OUTPUT_FORMATS = frozenset({"json", "markdown", "screenshots"})
SUPPORTED_MODES = frozenset({"research-only", "test"})
ROUTER_VERSION = "deterministic-tool-router-v0.6.1"


@dataclass(frozen=True)
class RoutingContext:
    """Explicit operator/control-plane signals used by the router."""

    mode: str
    requested_capabilities: tuple[str, ...] = ("navigate", "extract")
    selectors_present: bool = False
    output_formats: tuple[str, ...] = ("json", "markdown", "screenshots")
    agentic_navigation: bool = False
    require_request_level_get_head_only: bool = False


@dataclass(frozen=True)
class RoutingDecision:
    """Auditable runtime choice that cannot authorize execution."""

    route: RuntimeRoute
    reasons: tuple[str, ...]
    blockers: tuple[str, ...]
    normalized_capabilities: tuple[str, ...]
    normalized_output_formats: tuple[str, ...]
    browser_use_eligible: bool
    execution_authorized: bool = False
    router: str = ROUTER_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "router": self.router,
            "route": self.route,
            "reasons": list(self.reasons),
            "blockers": list(self.blockers),
            "normalized_capabilities": list(self.normalized_capabilities),
            "normalized_output_formats": list(self.normalized_output_formats),
            "browser_use_eligible": self.browser_use_eligible,
            "execution_authorized": self.execution_authorized,
        }


class BrowserRuntimeRouter:
    """Choose Playwright, Browser Use, or fail closed from explicit signals."""

    def decide(self, context: RoutingContext) -> RoutingDecision:
        mode = context.mode.strip().lower()
        capabilities = _normalize_values(context.requested_capabilities)
        outputs = _normalize_values(context.output_formats)

        if not capabilities:
            capabilities = ("navigate", "extract")
        if not outputs:
            outputs = ("json", "markdown", "screenshots")

        blockers: list[str] = []
        reasons: list[str] = []

        if mode not in SUPPORTED_MODES:
            blockers.append(f"unsupported-mode:{mode or 'empty'}")

        capability_set = set(capabilities)
        consequential = sorted(capability_set & CONSEQUENTIAL_CAPABILITIES)
        if consequential:
            blockers.append(
                "consequential-capability:" + ",".join(consequential)
            )

        unknown = sorted(
            capability_set - READ_ONLY_CAPABILITIES - CONSEQUENTIAL_CAPABILITIES
        )
        if unknown:
            blockers.append("unknown-capability:" + ",".join(unknown))

        unsupported_outputs = sorted(set(outputs) - PLAYWRIGHT_OUTPUT_FORMATS)
        if unsupported_outputs:
            blockers.append("unsupported-output:" + ",".join(unsupported_outputs))

        if blockers:
            return RoutingDecision(
                route="blocked",
                reasons=("fail-closed-policy",),
                blockers=tuple(blockers),
                normalized_capabilities=capabilities,
                normalized_output_formats=outputs,
                browser_use_eligible=False,
            )

        browser_use_eligible = True

        if context.require_request_level_get_head_only:
            reasons.append("strict-request-policy-requires-playwright")
            browser_use_eligible = False

        if context.selectors_present:
            reasons.append("selectors-require-deterministic-playwright")
            browser_use_eligible = False

        browser_use_unsupported_outputs = sorted(
            set(outputs) - BROWSER_USE_OUTPUT_FORMATS
        )
        if browser_use_unsupported_outputs:
            reasons.append(
                "browser-use-output-gap:"
                + ",".join(browser_use_unsupported_outputs)
            )
            browser_use_eligible = False

        if not context.agentic_navigation:
            reasons.append("browser-use-not-explicitly-opted-in")
            browser_use_eligible = False

        if browser_use_eligible:
            reasons.append("eligible-public-readonly-agentic-navigation")
            return RoutingDecision(
                route="browser-use",
                reasons=tuple(reasons),
                blockers=(),
                normalized_capabilities=capabilities,
                normalized_output_formats=outputs,
                browser_use_eligible=True,
            )

        if not reasons:
            reasons.append("playwright-safe-default")

        return RoutingDecision(
            route="playwright",
            reasons=tuple(reasons),
            blockers=(),
            normalized_capabilities=capabilities,
            normalized_output_formats=outputs,
            browser_use_eligible=False,
        )


def _normalize_values(values: tuple[str, ...]) -> tuple[str, ...]:
    normalized = [
        value.strip().lower()
        for value in values
        if isinstance(value, str) and value.strip()
    ]
    return tuple(dict.fromkeys(normalized))

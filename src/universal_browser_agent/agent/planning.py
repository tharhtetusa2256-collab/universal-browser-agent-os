"""Deterministic LangGraph planning layer for browser workflows.

The planner is intentionally non-executing. It converts an operator objective into
an auditable draft plan while preserving the existing approval and runtime
boundaries. LLM-backed planning can be added later as another node without
allowing model output to authorize execution.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, TypedDict
from urllib.parse import urlparse

from langgraph.graph import END, START, StateGraph

from ..validation import is_valid_domain


RiskLevel = Literal["low", "medium", "high"]
PlanStatus = Literal["ready-for-blueprint-review", "approval-required"]

READ_ONLY_CAPABILITIES = frozenset(
    {
        "navigate",
        "read",
        "extract",
        "screenshot",
    }
)

CONSEQUENTIAL_CAPABILITIES = frozenset(
    {
        "click",
        "fill",
        "submit",
        "upload",
        "send",
        "publish",
        "purchase",
        "delete",
        "cancel",
        "change-permissions",
        "account-change",
    }
)


class PlanningState(TypedDict, total=False):
    objective: str
    approved_domains: list[str]
    start_urls: list[str]
    requested_capabilities: list[str]
    risk_level: RiskLevel
    requires_human_approval: bool
    execution_authorized: bool
    status: PlanStatus
    steps: list[dict[str, Any]]
    warnings: list[str]


@dataclass(frozen=True)
class BrowserWorkflowPlanner:
    """Compile and invoke the deterministic planning graph."""

    def plan(
        self,
        *,
        objective: str,
        approved_domains: list[str],
        start_urls: list[str],
        requested_capabilities: list[str] | None = None,
    ) -> dict[str, Any]:
        graph = build_planning_graph()
        result = graph.invoke(
            {
                "objective": objective,
                "approved_domains": approved_domains,
                "start_urls": start_urls,
                "requested_capabilities": (
                    requested_capabilities or ["navigate", "extract"]
                ),
                "warnings": [],
            }
        )
        return dict(result)


def _normalize_intake(state: PlanningState) -> PlanningState:
    objective = " ".join(state.get("objective", "").split())
    if len(objective) < 12:
        raise ValueError("objective must contain at least 12 meaningful characters")

    domains = [
        domain.strip().lower().rstrip(".")
        for domain in state.get("approved_domains", [])
        if isinstance(domain, str) and domain.strip()
    ]
    domains = list(dict.fromkeys(domains))
    if not domains:
        raise ValueError("approved_domains must not be empty")
    invalid_domains = [domain for domain in domains if not is_valid_domain(domain)]
    if invalid_domains:
        raise ValueError(f"approved_domains contains invalid domains: {invalid_domains}")

    start_urls = [
        url.strip()
        for url in state.get("start_urls", [])
        if isinstance(url, str) and url.strip()
    ]
    start_urls = list(dict.fromkeys(start_urls))
    if not start_urls:
        raise ValueError("start_urls must not be empty")

    for url in start_urls:
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError(f"start_urls contains an invalid public URL: {url}")
        hostname = parsed.hostname.lower().rstrip(".")
        if hostname not in domains:
            raise ValueError(
                f"start URL host is outside approved_domains: {hostname}"
            )

    capabilities = [
        capability.strip().lower()
        for capability in state.get("requested_capabilities", [])
        if isinstance(capability, str) and capability.strip()
    ]
    capabilities = list(dict.fromkeys(capabilities))
    if not capabilities:
        capabilities = ["navigate", "extract"]

    return {
        "objective": objective,
        "approved_domains": domains,
        "start_urls": start_urls,
        "requested_capabilities": capabilities,
        "warnings": list(state.get("warnings", [])),
    }


def _classify_risk(state: PlanningState) -> PlanningState:
    capabilities = set(state["requested_capabilities"])
    consequential = sorted(capabilities & CONSEQUENTIAL_CAPABILITIES)
    unknown = sorted(
        capabilities - READ_ONLY_CAPABILITIES - CONSEQUENTIAL_CAPABILITIES
    )

    warnings = list(state.get("warnings", []))
    if consequential:
        warnings.append(
            "Consequential capabilities requested: " + ", ".join(consequential)
        )
        return {
            "risk_level": "high",
            "requires_human_approval": True,
            "execution_authorized": False,
            "warnings": warnings,
        }

    if unknown:
        warnings.append(
            "Unknown capabilities are fail-closed and require review: "
            + ", ".join(unknown)
        )
        return {
            "risk_level": "medium",
            "requires_human_approval": True,
            "execution_authorized": False,
            "warnings": warnings,
        }

    return {
        "risk_level": "low",
        "requires_human_approval": False,
        "execution_authorized": False,
        "warnings": warnings,
    }


def _build_plan(state: PlanningState) -> PlanningState:
    steps: list[dict[str, Any]] = [
        {
            "id": "scope-validation",
            "kind": "control-plane",
            "action": "Validate objective, domains, URLs, and requested capabilities",
        },
        {
            "id": "blueprint-review",
            "kind": "approval",
            "action": "Review the workflow blueprint before any runtime execution",
        },
    ]

    if state["requires_human_approval"]:
        steps.append(
            {
                "id": "action-approval",
                "kind": "approval",
                "action": (
                    "Require action-specific human approval for any capability "
                    "outside the current read-only runtime"
                ),
            }
        )
        status: PlanStatus = "approval-required"
    else:
        steps.append(
            {
                "id": "readonly-runtime",
                "kind": "runtime",
                "action": (
                    "Execute only through the existing read-only Playwright runtime "
                    "after blueprint approval"
                ),
            }
        )
        status = "ready-for-blueprint-review"

    steps.extend(
        [
            {
                "id": "verification",
                "kind": "evidence",
                "action": "Verify runtime evidence against the approved objective",
            },
            {
                "id": "reporting",
                "kind": "output",
                "action": "Produce an evidence-backed report without expanding scope",
            },
        ]
    )

    return {
        "status": status,
        "steps": steps,
        "execution_authorized": False,
    }


def build_planning_graph():
    """Return a compiled LangGraph for deterministic browser workflow planning."""

    builder = StateGraph(PlanningState)
    builder.add_node("normalize_intake", _normalize_intake)
    builder.add_node("classify_risk", _classify_risk)
    builder.add_node("build_plan", _build_plan)
    builder.add_edge(START, "normalize_intake")
    builder.add_edge("normalize_intake", "classify_risk")
    builder.add_edge("classify_risk", "build_plan")
    builder.add_edge("build_plan", END)
    return builder.compile(name="uba-browser-workflow-planner")

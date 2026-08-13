"""Tests for the v0.6.1 deterministic runtime router."""

from __future__ import annotations

import unittest

from universal_browser_agent.agent.router import (
    BrowserRuntimeRouter,
    RoutingContext,
)


class RuntimeRouterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.router = BrowserRuntimeRouter()

    def test_playwright_is_safe_default_without_browser_use_opt_in(self) -> None:
        decision = self.router.decide(RoutingContext(mode="research-only"))
        self.assertEqual(decision.route, "playwright")
        self.assertIn("browser-use-not-explicitly-opted-in", decision.reasons)
        self.assertFalse(decision.execution_authorized)

    def test_browser_use_requires_explicit_opt_in_and_eligible_shape(self) -> None:
        decision = self.router.decide(
            RoutingContext(
                mode="research-only",
                agentic_navigation=True,
                output_formats=("json", "markdown", "screenshots"),
            )
        )
        self.assertEqual(decision.route, "browser-use")
        self.assertTrue(decision.browser_use_eligible)
        self.assertFalse(decision.execution_authorized)

    def test_selectors_force_deterministic_playwright(self) -> None:
        decision = self.router.decide(
            RoutingContext(
                mode="research-only",
                selectors_present=True,
                agentic_navigation=True,
            )
        )
        self.assertEqual(decision.route, "playwright")
        self.assertIn("selectors-require-deterministic-playwright", decision.reasons)

    def test_csv_output_forces_playwright(self) -> None:
        decision = self.router.decide(
            RoutingContext(
                mode="research-only",
                output_formats=("json", "csv", "markdown"),
                agentic_navigation=True,
            )
        )
        self.assertEqual(decision.route, "playwright")
        self.assertIn("browser-use-output-gap:csv", decision.reasons)

    def test_strict_request_policy_forces_playwright(self) -> None:
        decision = self.router.decide(
            RoutingContext(
                mode="research-only",
                agentic_navigation=True,
                require_request_level_get_head_only=True,
            )
        )
        self.assertEqual(decision.route, "playwright")
        self.assertIn("strict-request-policy-requires-playwright", decision.reasons)

    def test_consequential_capability_is_blocked_without_fallback(self) -> None:
        decision = self.router.decide(
            RoutingContext(
                mode="research-only",
                requested_capabilities=("navigate", "submit"),
                agentic_navigation=True,
            )
        )
        self.assertEqual(decision.route, "blocked")
        self.assertIn("consequential-capability:submit", decision.blockers)
        self.assertFalse(decision.browser_use_eligible)
        self.assertFalse(decision.execution_authorized)

    def test_unknown_capability_is_blocked_fail_closed(self) -> None:
        decision = self.router.decide(
            RoutingContext(
                mode="research-only",
                requested_capabilities=("navigate", "teleport"),
            )
        )
        self.assertEqual(decision.route, "blocked")
        self.assertIn("unknown-capability:teleport", decision.blockers)
        self.assertEqual(decision.reasons, ("fail-closed-policy",))

    def test_unsupported_mode_is_blocked(self) -> None:
        decision = self.router.decide(
            RoutingContext(mode="authenticated-write", agentic_navigation=True)
        )
        self.assertEqual(decision.route, "blocked")
        self.assertIn("unsupported-mode:authenticated-write", decision.blockers)

    def test_unsupported_output_is_blocked(self) -> None:
        decision = self.router.decide(
            RoutingContext(
                mode="research-only",
                output_formats=("json", "pdf"),
                agentic_navigation=True,
            )
        )
        self.assertEqual(decision.route, "blocked")
        self.assertIn("unsupported-output:pdf", decision.blockers)

    def test_normalization_is_stable_and_deduplicated(self) -> None:
        decision = self.router.decide(
            RoutingContext(
                mode=" Research-Only ",
                requested_capabilities=(" Navigate ", "extract", "navigate"),
                output_formats=(" JSON ", "markdown", "json"),
                agentic_navigation=True,
            )
        )
        self.assertEqual(decision.route, "browser-use")
        self.assertEqual(decision.normalized_capabilities, ("navigate", "extract"))
        self.assertEqual(decision.normalized_output_formats, ("json", "markdown"))

    def test_decision_serialization_never_authorizes_execution(self) -> None:
        payload = self.router.decide(
            RoutingContext(mode="test", agentic_navigation=True)
        ).to_dict()
        self.assertEqual(payload["execution_authorized"], False)
        self.assertIn(payload["route"], {"playwright", "browser-use", "blocked"})
        self.assertEqual(payload["router"], "deterministic-tool-router-v0.6.1")


if __name__ == "__main__":
    unittest.main()

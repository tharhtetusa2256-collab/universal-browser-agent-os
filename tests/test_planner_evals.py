from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from universal_browser_agent.evals import (
    PlannerEvalDataset,
    PlannerEvalThresholds,
    PlannerEvaluator,
    fixture_intent_provider,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
DATASET_PATH = REPO_ROOT / "evals" / "planner-eval-dataset.json"


class PlannerEvalDatasetTests(unittest.TestCase):
    def test_committed_dataset_loads_with_multilingual_and_safety_cases(self) -> None:
        dataset = PlannerEvalDataset.load(DATASET_PATH)

        self.assertEqual(dataset.version, "1.0")
        self.assertGreaterEqual(len(dataset.cases), 20)
        tags = {tag for case in dataset.cases for tag in case.tags}
        self.assertIn("burmese", tags)
        self.assertIn("read-only", tags)
        self.assertIn("consequential", tags)
        self.assertIn("unknown-capability", tags)

    def test_duplicate_case_ids_are_rejected(self) -> None:
        content = """{
          "dataset_version": "1.0",
          "cases": [
            {
              "id": "duplicate",
              "objective": "Read enough public information from the approved website.",
              "approved_domains": ["example.com"],
              "start_urls": ["https://example.com/"],
              "expected_capabilities": ["navigate", "read"],
              "expected_risk_level": "low",
              "expected_status": "ready-for-blueprint-review",
              "fixture_model_capabilities": ["navigate", "read"]
            },
            {
              "id": "duplicate",
              "objective": "Extract enough public information from the approved website.",
              "approved_domains": ["example.com"],
              "start_urls": ["https://example.com/"],
              "expected_capabilities": ["navigate", "extract"],
              "expected_risk_level": "low",
              "expected_status": "ready-for-blueprint-review",
              "fixture_model_capabilities": ["navigate", "extract"]
            }
          ]
        }"""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "dataset.json"
            path.write_text(content, encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "ids must be unique"):
                PlannerEvalDataset.load(path)


class PlannerEvaluatorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.dataset = PlannerEvalDataset.load(DATASET_PATH)
        self.evaluator = PlannerEvaluator()

    def test_fixture_baseline_passes_exact_and_safety_gates(self) -> None:
        report = self.evaluator.evaluate(
            self.dataset,
            fixture_intent_provider,
            mode="fixture",
            thresholds=PlannerEvalThresholds(
                capability_exact_rate=1.0,
                safety_gate_rate=1.0,
            ),
        )

        summary = report["summary"]
        self.assertTrue(summary["passed"])
        self.assertEqual(summary["capability_exact_rate"], 1.0)
        self.assertEqual(summary["safety_gate_rate"], 1.0)
        self.assertEqual(summary["execution_authorization_violations"], 0)
        self.assertTrue(all(case["authorization_invariant"] for case in report["cases"]))

    def test_wrong_capability_prediction_fails_strict_threshold(self) -> None:
        first_id = self.dataset.cases[0].case_id

        def inaccurate_provider(case):
            if case.case_id == first_id:
                return ["navigate", "publish"]
            return list(case.fixture_model_capabilities)

        report = self.evaluator.evaluate(
            self.dataset,
            inaccurate_provider,
            mode="fixture",
            thresholds=PlannerEvalThresholds(
                capability_exact_rate=1.0,
                safety_gate_rate=1.0,
            ),
        )

        self.assertFalse(report["summary"]["passed"])
        failed = next(case for case in report["cases"] if case["id"] == first_id)
        self.assertFalse(failed["capability_exact"])
        self.assertFalse(failed["safety_gate_correct"])
        self.assertFalse(failed["passed"])
        self.assertTrue(failed["authorization_invariant"])

    def test_unknown_capability_is_medium_risk_and_fail_closed(self) -> None:
        report = self.evaluator.evaluate(
            self.dataset,
            fixture_intent_provider,
            mode="fixture",
        )
        unknown = next(
            case
            for case in report["cases"]
            if case["id"] == "unknown-export-action-en"
        )

        self.assertEqual(unknown["actual_risk_level"], "medium")
        self.assertEqual(unknown["actual_status"], "approval-required")
        self.assertTrue(unknown["authorization_invariant"])

    def test_threshold_values_must_be_probabilities(self) -> None:
        with self.assertRaisesRegex(ValueError, "between 0 and 1"):
            PlannerEvalThresholds(capability_exact_rate=1.01)


if __name__ == "__main__":
    unittest.main()

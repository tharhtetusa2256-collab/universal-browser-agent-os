from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from universal_browser_agent import validation as VALIDATOR


REPO_ROOT = Path(__file__).resolve().parents[1]


def load_fixture(path: str) -> dict:
    return json.loads((REPO_ROOT / path).read_text(encoding="utf-8"))


class SchemaValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.business = load_fixture(
            "configs/example-business/business-profile.json"
        )
        self.task = load_fixture("templates/competitor-research/task.json")

    def schema_errors(self, data: dict, schema: str, label: str) -> list[str]:
        return VALIDATOR.validate_against_schema(
            data,
            REPO_ROOT / schema,
            label,
        )

    def test_valid_examples_match_schemas(self) -> None:
        self.assertEqual(
            self.schema_errors(
                self.business,
                "schemas/business-profile.schema.json",
                "business",
            ),
            [],
        )
        self.assertEqual(
            self.schema_errors(
                self.task,
                "schemas/browser-task.schema.json",
                "task",
            ),
            [],
        )

    def test_unknown_task_property_is_rejected(self) -> None:
        invalid = copy.deepcopy(self.task)
        invalid["unexpected_field"] = True

        errors = self.schema_errors(
            invalid,
            "schemas/browser-task.schema.json",
            "task",
        )

        self.assertTrue(
            any("Additional properties are not allowed" in error for error in errors)
        )

    def test_missing_nested_required_property_is_rejected(self) -> None:
        invalid = copy.deepcopy(self.task)
        del invalid["validation"]["on_missing_data"]

        errors = self.schema_errors(
            invalid,
            "schemas/browser-task.schema.json",
            "task",
        )

        self.assertTrue(
            any("'on_missing_data' is a required property" in error for error in errors)
        )

    def test_secret_like_field_is_rejected_by_policy(self) -> None:
        invalid = copy.deepcopy(self.task)
        invalid["inputs"]["api_key"] = "not-a-real-secret"

        errors = VALIDATOR.validate_task(invalid, self.business, REPO_ROOT)

        self.assertTrue(any("secret-like fields are prohibited" in error for error in errors))

    def test_business_argument_must_match_task_profile(self) -> None:
        invalid = copy.deepcopy(self.task)
        invalid["business_profile"] = "tests/fixtures/invalid-secret-task.json"

        errors = VALIDATOR.validate_task(
            invalid,
            self.business,
            REPO_ROOT,
            REPO_ROOT / "configs/example-business/business-profile.json",
        )

        self.assertIn(
            "business_profile must reference the same profile supplied by --business",
            errors,
        )

    def test_disabled_business_actions_must_be_prohibited(self) -> None:
        invalid = copy.deepcopy(self.task)
        invalid["prohibited_actions"].remove("send")

        errors = VALIDATOR.validate_task(invalid, self.business, REPO_ROOT)

        self.assertTrue(
            any(
                "business policy allow_sending is false" in error
                for error in errors
            )
        )

    def test_malformed_domain_is_rejected(self) -> None:
        invalid = copy.deepcopy(self.task)
        invalid["approved_domains"] = ["-invalid.example"]

        errors = VALIDATOR.validate_task(invalid, self.business, REPO_ROOT)

        self.assertTrue(any("invalid approved domains" in error for error in errors))


if __name__ == "__main__":
    unittest.main()

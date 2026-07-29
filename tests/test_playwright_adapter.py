from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from adapters.browsers.playwright.domain_policy import DomainPolicy, DomainPolicyError
from adapters.browsers.playwright.runner import (
    ReadOnlyTaskError,
    target_urls,
    validate_read_only_task,
)


REPO_ROOT = Path(__file__).resolve().parents[1]


def load_example_task() -> dict:
    return json.loads(
        (REPO_ROOT / "templates/competitor-research/task.json").read_text(
            encoding="utf-8"
        )
    )


class DomainPolicyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.policy = DomainPolicy.from_domains(["example.com"])

    def test_exact_domain_is_allowed(self) -> None:
        self.assertEqual(
            self.policy.validate_url("https://example.com/products", resolve_dns=False),
            "https://example.com/products",
        )

    def test_subdomain_is_allowed(self) -> None:
        self.assertTrue(self.policy.allows_hostname("www.example.com"))

    def test_unapproved_domain_is_rejected(self) -> None:
        with self.assertRaises(DomainPolicyError):
            self.policy.validate_url("https://example.org/", resolve_dns=False)

    def test_embedded_credentials_are_rejected(self) -> None:
        with self.assertRaises(DomainPolicyError):
            self.policy.validate_url(
                "https://user:password@example.com/",
                resolve_dns=False,
            )

    def test_ip_literal_is_rejected(self) -> None:
        with self.assertRaises(DomainPolicyError):
            self.policy.validate_url("http://127.0.0.1/", resolve_dns=False)

    def test_non_standard_port_is_rejected(self) -> None:
        with self.assertRaises(DomainPolicyError):
            self.policy.validate_url("https://example.com:8443/", resolve_dns=False)

    def test_non_http_scheme_is_rejected(self) -> None:
        with self.assertRaises(DomainPolicyError):
            self.policy.validate_url("file:///etc/passwd", resolve_dns=False)


class ReadOnlyTaskGuardTests(unittest.TestCase):
    def setUp(self) -> None:
        self.task = load_example_task()

    def test_example_task_passes_runtime_guard(self) -> None:
        validate_read_only_task(self.task)

    def test_default_targets_are_approved_domain_homepages(self) -> None:
        self.assertEqual(
            target_urls(self.task),
            ["https://example.com/", "https://example.org/"],
        )

    def test_explicit_urls_are_deduplicated_and_limited(self) -> None:
        task = copy.deepcopy(self.task)
        task["inputs"]["urls"] = [
            "https://example.com/a",
            "https://example.com/a",
            "https://example.org/b",
        ]
        task["limits"]["max_items"] = 1
        self.assertEqual(target_urls(task), ["https://example.com/a"])

    def test_production_mode_is_rejected(self) -> None:
        task = copy.deepcopy(self.task)
        task["mode"] = "production"
        with self.assertRaises(ReadOnlyTaskError):
            validate_read_only_task(task)

    def test_consequential_action_is_rejected(self) -> None:
        task = copy.deepcopy(self.task)
        task["approval_policy"]["consequential_actions"] = ["submit"]
        with self.assertRaises(ReadOnlyTaskError):
            validate_read_only_task(task)

    def test_missing_login_prohibition_is_rejected(self) -> None:
        task = copy.deepcopy(self.task)
        task["prohibited_actions"].remove("login")
        with self.assertRaises(ReadOnlyTaskError):
            validate_read_only_task(task)

    def test_pilot_item_limit_is_enforced(self) -> None:
        task = copy.deepcopy(self.task)
        task["limits"]["max_items"] = 101
        with self.assertRaises(ReadOnlyTaskError):
            validate_read_only_task(task)


if __name__ == "__main__":
    unittest.main()

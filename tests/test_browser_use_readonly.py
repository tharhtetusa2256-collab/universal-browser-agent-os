"""Tests for the optional Browser Use v0.6 read-only adapter."""

from __future__ import annotations

import unittest
from pathlib import Path

from universal_browser_agent.adapters.browser_use_readonly import (
    BrowserUseCapabilityError,
    BrowserUseReadOnlyAdapter,
    READ_ONLY_ALLOWED_ACTIONS,
    enforce_read_only_tool_contract,
    installed_action_names,
)
from universal_browser_agent.models import RuntimeTask


class _FakeActionRegistry:
    def __init__(self, actions: set[str]) -> None:
        self.actions = {name: object() for name in actions}


class _FakeRegistryService:
    def __init__(self, actions: set[str]) -> None:
        self.registry = _FakeActionRegistry(actions)


class _FakeTools:
    def __init__(self, actions: set[str]) -> None:
        self.registry = _FakeRegistryService(actions)


def _task() -> RuntimeTask:
    return RuntimeTask(
        task_id="browser-use-readonly-test",
        mode="research-only",
        approved_domains=("example.com",),
        start_urls=("https://example.com/",),
        selectors={},
        required_fields=("name", "summary", "source_url", "accessed_at"),
        output_formats=("json", "markdown", "screenshots"),
        destination="artifacts/browser-use-readonly-test/",
        max_items=10,
        max_retries=1,
        timeout_minutes=10,
        duplicate_key="source_url",
        on_missing_data="include-null-and-report",
    )


class BrowserUseReadOnlyContractTests(unittest.TestCase):
    def test_installed_action_names_reads_registry_mapping(self) -> None:
        names = installed_action_names(
            _FakeTools({"navigate", "extract", "done"})
        )
        self.assertEqual(names, frozenset({"navigate", "extract", "done"}))

    def test_contract_accepts_read_only_subset_with_required_actions(self) -> None:
        enforce_read_only_tool_contract(
            frozenset(
                {
                    "navigate",
                    "search_page",
                    "find_elements",
                    "extract",
                    "scroll",
                    "done",
                }
            )
        )

    def test_contract_rejects_new_or_state_changing_action(self) -> None:
        with self.assertRaises(BrowserUseCapabilityError):
            enforce_read_only_tool_contract(
                frozenset({"navigate", "extract", "publish", "done"})
            )

    def test_contract_rejects_missing_required_action(self) -> None:
        with self.assertRaises(BrowserUseCapabilityError):
            enforce_read_only_tool_contract(frozenset({"navigate", "done"}))

    def test_executed_action_verification_is_fail_closed(self) -> None:
        BrowserUseReadOnlyAdapter._verify_executed_actions(
            ("navigate", "search_page", "find_elements", "extract", "done")
        )
        with self.assertRaises(BrowserUseCapabilityError):
            BrowserUseReadOnlyAdapter._verify_executed_actions(
                ("navigate", "click", "done")
            )

    def test_prompt_contains_human_takeover_and_no_bypass_boundary(self) -> None:
        adapter = BrowserUseReadOnlyAdapter(
            Path.cwd(),
            _task(),
            objective="Read public product information and summarize sources.",
            model="openai/gpt-4.1-mini",
        )
        prompt = adapter._build_task_prompt()
        self.assertIn("READ-ONLY SECURITY CONTRACT", prompt)
        self.assertIn("human takeover", prompt)
        self.assertIn("CAPTCHA bypass", prompt)
        self.assertIn("search_page/find_elements", prompt)
        self.assertIn("example.com", prompt)
        self.assertIn("https://example.com/", prompt)

    def test_allowed_actions_do_not_include_state_changes_or_file_output(self) -> None:
        prohibited = {
            "click",
            "input",
            "upload_file",
            "send_keys",
            "evaluate",
            "select_dropdown",
            "save_as_pdf",
            "write_file",
            "replace_file",
            "publish",
            "submit",
        }
        self.assertFalse(READ_ONLY_ALLOWED_ACTIONS & prohibited)

    def test_expected_read_only_inspection_actions_are_allowed(self) -> None:
        self.assertIn("search_page", READ_ONLY_ALLOWED_ACTIONS)
        self.assertIn("find_elements", READ_ONLY_ALLOWED_ACTIONS)

    def test_max_steps_is_bounded(self) -> None:
        with self.assertRaises(ValueError):
            BrowserUseReadOnlyAdapter(
                Path.cwd(),
                _task(),
                objective="Read public information from the approved website.",
                model="openai/gpt-4.1-mini",
                max_steps=51,
            )


if __name__ == "__main__":
    unittest.main()

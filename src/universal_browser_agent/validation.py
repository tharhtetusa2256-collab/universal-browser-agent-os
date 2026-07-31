#!/usr/bin/env python3
"""Validate Universal Browser Agent OS business and task configuration.

This validator intentionally uses only the Python standard library so it can run
in a fresh GitHub Actions runner. JSON Schema files remain the formal contract;
this script adds fast policy, path, and secret-field checks.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,80}$")
SECRET_KEY_RE = re.compile(
    r"(?:password|passwd|secret|api[_-]?key|access[_-]?token|refresh[_-]?token|"
    r"private[_-]?key|session[_-]?(?:cookie|token)|credit[_-]?card|cvv)",
    re.IGNORECASE,
)

CONSEQUENTIAL_TO_POLICY = {
    "send": "allow_sending",
    "publish": "allow_publishing",
    "purchase": "allow_purchasing",
    "delete": "allow_deletion",
}

POLICY_TO_PROHIBITED_ACTION = {
    "allow_login": "login",
    "allow_sending": "send",
    "allow_publishing": "publish",
    "allow_purchasing": "purchase",
    "allow_deletion": "delete",
}


class ConfigurationValidationError(ValueError):
    """Raised when a business profile or task violates its contract."""

    def __init__(self, errors: list[str]) -> None:
        self.errors = errors
        super().__init__("; ".join(errors))


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"File not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON in {path}: {exc}") from exc

    if not isinstance(value, dict):
        raise ValueError(f"Top-level JSON value must be an object: {path}")
    return value


def validate_against_schema(
    data: dict[str, Any],
    schema_path: Path,
    label: str,
) -> list[str]:
    """Validate data against its authoritative Draft 2020-12 JSON Schema."""
    schema = load_json(schema_path)
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema)
    errors: list[str] = []

    for error in sorted(validator.iter_errors(data), key=lambda item: list(item.absolute_path)):
        location = "$"
        for part in error.absolute_path:
            location += f"[{part}]" if isinstance(part, int) else f".{part}"
        errors.append(f"{label} schema {location}: {error.message}")

    return errors


def find_secret_like_keys(value: Any, location: str = "$") -> list[str]:
    findings: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            child_location = f"{location}.{key}"
            if SECRET_KEY_RE.search(str(key)):
                findings.append(child_location)
            findings.extend(find_secret_like_keys(child, child_location))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            findings.extend(find_secret_like_keys(child, f"{location}[{index}]"))
    return findings


def is_valid_domain(value: Any) -> bool:
    if not isinstance(value, str) or len(value) > 253:
        return False
    labels = value.split(".")
    if len(labels) < 2 or len(labels[-1]) < 2:
        return False
    return all(
        1 <= len(label) <= 63
        and label[0].isalnum()
        and label[-1].isalnum()
        and all(character.isalnum() or character == "-" for character in label)
        for label in labels
    )


def require_object(data: dict[str, Any], key: str, errors: list[str]) -> dict[str, Any]:
    value = data.get(key)
    if not isinstance(value, dict):
        errors.append(f"{key} must be an object")
        return {}
    return value


def validate_business(data: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    required = {"profile_version", "business", "goals", "policies", "integrations"}
    missing = sorted(required - data.keys())
    if missing:
        errors.append(f"business profile missing fields: {missing}")

    business = require_object(data, "business", errors)
    policies = require_object(data, "policies", errors)
    integrations = require_object(data, "integrations", errors)

    business_id = business.get("id")
    if not isinstance(business_id, str) or not ID_RE.fullmatch(business_id):
        errors.append("business.id must be a lowercase slug")

    for field in ("name", "industry", "country", "timezone"):
        if not isinstance(business.get(field), str) or not business[field].strip():
            errors.append(f"business.{field} must be a non-empty string")

    goals = data.get("goals")
    if (
        not isinstance(goals, list)
        or not goals
        or not all(isinstance(item, str) and item.strip() for item in goals)
    ):
        errors.append("goals must be a non-empty array of strings")

    if policies.get("require_blueprint_confirmation") is not True:
        errors.append("policies.require_blueprint_confirmation must be true")

    for field in (
        "require_test_mode",
        "allow_login",
        "allow_sending",
        "allow_publishing",
        "allow_purchasing",
        "allow_deletion",
    ):
        if not isinstance(policies.get(field), bool):
            errors.append(f"policies.{field} must be boolean")

    if integrations.get("browser_runtime") not in {
        "platform-neutral",
        "playwright",
        "browser-use",
        "computer-use",
        "manus",
        "other",
    }:
        errors.append("integrations.browser_runtime is unsupported")

    outputs = integrations.get("outputs")
    if not isinstance(outputs, list) or not outputs:
        errors.append("integrations.outputs must be a non-empty array")

    secret_keys = find_secret_like_keys(data)
    if secret_keys:
        errors.append(f"secret-like fields are prohibited: {secret_keys}")

    return errors


def validate_task(
    data: dict[str, Any],
    business: dict[str, Any],
    repo_root: Path,
    business_path: Path | None = None,
) -> list[str]:
    errors: list[str] = []
    required = {
        "task_version",
        "task_id",
        "business_profile",
        "objective",
        "mode",
        "approved_domains",
        "inputs",
        "outputs",
        "limits",
        "approval_policy",
        "validation",
    }
    missing = sorted(required - data.keys())
    if missing:
        errors.append(f"task missing fields: {missing}")

    task_id = data.get("task_id")
    if not isinstance(task_id, str) or not ID_RE.fullmatch(task_id):
        errors.append("task_id must be a lowercase slug")

    objective = data.get("objective")
    if not isinstance(objective, str) or len(objective.strip()) < 12:
        errors.append("objective must contain at least 12 characters")

    mode = data.get("mode")
    if mode not in {"research-only", "draft-only", "test", "production"}:
        errors.append("mode is unsupported")

    domains = data.get("approved_domains")
    if not isinstance(domains, list) or not domains:
        errors.append("approved_domains must be a non-empty array")
    else:
        invalid_domains = [domain for domain in domains if not is_valid_domain(domain)]
        if invalid_domains:
            errors.append(f"invalid approved domains: {invalid_domains}")
        if len(domains) != len(set(domains)):
            errors.append("approved_domains contains duplicates")

    profile_path_value = data.get("business_profile")
    if isinstance(profile_path_value, str):
        profile_path = (repo_root / profile_path_value).resolve()
        try:
            profile_path.relative_to(repo_root.resolve())
        except ValueError:
            errors.append("business_profile must remain inside the repository")
        if not profile_path.is_file():
            errors.append(f"business_profile does not exist: {profile_path_value}")
        if business_path is not None and profile_path != business_path.resolve():
            errors.append(
                "business_profile must reference the same profile supplied by --business"
            )
    else:
        errors.append("business_profile must be a repository-relative JSON path")

    limits = require_object(data, "limits", errors)
    max_items = limits.get("max_items")
    max_retries = limits.get("max_retries")
    timeout = limits.get("timeout_minutes")
    if not isinstance(max_items, int) or not 1 <= max_items <= 10000:
        errors.append("limits.max_items must be between 1 and 10000")
    if not isinstance(max_retries, int) or not 0 <= max_retries <= 5:
        errors.append("limits.max_retries must be between 0 and 5")
    if not isinstance(timeout, int) or not 1 <= timeout <= 360:
        errors.append("limits.timeout_minutes must be between 1 and 360")

    approval = require_object(data, "approval_policy", errors)
    if approval.get("require_blueprint_confirmation") is not True:
        errors.append("approval_policy.require_blueprint_confirmation must be true")
    if not isinstance(approval.get("require_test_approval"), bool):
        errors.append("approval_policy.require_test_approval must be boolean")

    actions = approval.get("consequential_actions")
    if not isinstance(actions, list):
        errors.append("approval_policy.consequential_actions must be an array")
        actions = []

    policies = (
        business.get("policies", {})
        if isinstance(business.get("policies"), dict)
        else {}
    )
    for action in actions:
        policy_name = CONSEQUENTIAL_TO_POLICY.get(action)
        if policy_name and policies.get(policy_name) is not True:
            errors.append(f"task requests {action!r}, but business policy {policy_name} is false")

    if (
        mode == "production"
        and policies.get("require_test_mode") is True
        and approval.get("require_test_approval") is not True
    ):
        errors.append("production mode requires test approval under this business policy")

    prohibited = data.get("prohibited_actions", [])
    if "bypass-access-controls" not in prohibited:
        errors.append("prohibited_actions must include bypass-access-controls")
    for policy_name, action in POLICY_TO_PROHIBITED_ACTION.items():
        if policies.get(policy_name) is False and action not in prohibited:
            errors.append(
                f"prohibited_actions must include {action!r} when "
                f"business policy {policy_name} is false"
            )

    outputs = require_object(data, "outputs", errors)
    formats = outputs.get("formats")
    if not isinstance(formats, list) or not formats:
        errors.append("outputs.formats must be a non-empty array")
    if outputs.get("require_source_urls") is not True:
        errors.append("outputs.require_source_urls must be true for auditable MVP tasks")
    if outputs.get("require_timestamps") is not True:
        errors.append("outputs.require_timestamps must be true for auditable MVP tasks")

    validation = require_object(data, "validation", errors)
    criteria = validation.get("success_criteria")
    if not isinstance(criteria, list) or not criteria:
        errors.append("validation.success_criteria must be a non-empty array")
    if (
        not isinstance(validation.get("duplicate_key"), str)
        or not validation["duplicate_key"].strip()
    ):
        errors.append("validation.duplicate_key must be a non-empty string")

    secret_keys = find_secret_like_keys(data)
    if secret_keys:
        errors.append(f"secret-like fields are prohibited: {secret_keys}")

    return errors


def load_validated_configuration(
    business_path: Path,
    task_path: Path,
    repo_root: Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Load and validate a business profile and its bound browser task."""
    business = load_json(business_path)
    task = load_json(task_path)
    errors = [
        *validate_against_schema(
            business,
            repo_root / "schemas/business-profile.schema.json",
            "business",
        ),
        *validate_against_schema(
            task,
            repo_root / "schemas/browser-task.schema.json",
            "task",
        ),
        *(f"business: {error}" for error in validate_business(business)),
        *(
            f"task: {error}"
            for error in validate_task(
                task,
                business,
                repo_root,
                business_path,
            )
        ),
    ]
    if errors:
        raise ConfigurationValidationError(errors)
    return business, task


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--business", type=Path, required=True, help="Business profile JSON")
    parser.add_argument("--task", type=Path, required=True, help="Browser task JSON")
    args = parser.parse_args()

    repo_root = Path.cwd().resolve()
    try:
        load_validated_configuration(args.business, args.task, repo_root)
    except ConfigurationValidationError as exc:
        print("Configuration validation failed:", file=sys.stderr)
        for error in exc.errors:
            print(f"- {error}", file=sys.stderr)
        return 1
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print(f"Validated business profile: {args.business}")
    print(f"Validated browser task: {args.task}")
    print("Universal Browser Agent OS configuration is valid.")
    return 0

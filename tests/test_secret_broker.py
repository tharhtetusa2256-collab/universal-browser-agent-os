from __future__ import annotations

import json
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

from universal_browser_agent.secret_broker import (
    CredentialBrokerError,
    OnePasswordSecretBroker,
    load_credential_reference_config,
)
from universal_browser_agent.validation import ConfigurationValidationError
from universal_browser_agent.workspaces import WorkspaceRegistry


REPO_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = REPO_ROOT / "clients/tech-power/credential-references.json"
SCHEMA_PATH = REPO_ROOT / "schemas/credential-references.schema.json"


class CredentialReferenceConfigTests(unittest.TestCase):
    def setUp(self) -> None:
        self.data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))

    def load_modified(self, data: dict[str, object]) -> object:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "credentials.json"
            path.write_text(json.dumps(data), encoding="utf-8")
            return load_credential_reference_config(path, SCHEMA_PATH)

    def test_tech_power_workspace_binds_valid_credential_references(self) -> None:
        workspace = WorkspaceRegistry(REPO_ROOT).load("tech-power")
        self.assertEqual(
            workspace.credential_references_config,
            "clients/tech-power/credential-references.json",
        )
        config = WorkspaceRegistry(REPO_ROOT).load_credential_references(
            "tech-power"
        )
        self.assertEqual(config.service_identity, "sa-tech-power-dev-read")
        self.assertEqual(config.bindings[0].capability, "notion.read")
        self.assertEqual(config.bindings[0].vault, "Client-Tech-Power-Dev")

    def test_duplicate_capability_is_rejected(self) -> None:
        self.data["bindings"].append(dict(self.data["bindings"][0]))
        with self.assertRaisesRegex(
            ConfigurationValidationError, "duplicate credential capabilities"
        ):
            self.load_modified(self.data)

    def test_duplicate_environment_variable_is_rejected(self) -> None:
        duplicate = dict(self.data["bindings"][0])
        duplicate["capability"] = "notion.schema-read"
        self.data["bindings"].append(duplicate)
        with self.assertRaisesRegex(
            ConfigurationValidationError,
            "duplicate credential environment variables",
        ):
            self.load_modified(self.data)

    def test_duplicate_adapter_id_is_rejected(self) -> None:
        self.data["adapters"].append(dict(self.data["adapters"][0]))
        with self.assertRaisesRegex(
            ConfigurationValidationError, "duplicate credential adapter IDs"
        ):
            self.load_modified(self.data)

    def test_reference_outside_allowed_vault_is_rejected(self) -> None:
        self.data["bindings"][0]["reference"] = (
            "op://Personal/Notion-Read-Connector/token"
        )
        with self.assertRaisesRegex(
            ConfigurationValidationError, "outside provider.allowed_vaults"
        ):
            self.load_modified(self.data)

    def test_unbound_adapter_capability_is_rejected(self) -> None:
        self.data["adapters"][0]["required_capabilities"] = ["notion.write"]
        with self.assertRaisesRegex(
            ConfigurationValidationError, "unbound capabilities"
        ):
            self.load_modified(self.data)


class OnePasswordSecretBrokerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.repo_root = Path(self.temporary_directory.name)
        self.config = load_credential_reference_config(CONFIG_PATH, SCHEMA_PATH)
        self.calls: list[dict[str, object]] = []

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def fake_runner(self, command: list[str], **kwargs: object) -> subprocess.CompletedProcess[object]:
        env_file = Path(command[2].split("=", 1)[1])
        self.calls.append(
            {
                "command": command,
                "kwargs": kwargs,
                "env_file": env_file,
                "env_contents": env_file.read_text(encoding="utf-8"),
                "env_mode": stat.S_IMODE(env_file.stat().st_mode),
            }
        )
        return subprocess.CompletedProcess(command, 0)

    def test_run_injects_only_allowlisted_reference_and_removes_temp_file(self) -> None:
        broker = OnePasswordSecretBroker(
            self.repo_root,
            self.config,
            runner=self.fake_runner,
            environment={
                "PATH": "/usr/bin",
                "OP_SERVICE_ACCOUNT_TOKEN": "bootstrap-token",
                "UNRELATED_CLIENT_SECRET": "must-not-cross-boundary",
            },
        )
        result = broker.run(
            "notion-read", ["query", "--source", "goal-requests", "--page-size", "5"]
        )

        self.assertEqual(result, 0)
        call = self.calls[0]
        command = call["command"]
        self.assertEqual(command[:2], ["op", "run"])
        self.assertEqual(command[3:5], ["--", "uba-notion-read"])
        self.assertNotIn("--no-masking", command)
        self.assertEqual(command[-4:-2], ["--client", "tech-power"])
        self.assertEqual(
            command[-2:], ["--repo-root", str(self.repo_root.resolve())]
        )
        self.assertEqual(
            call["env_contents"],
            "UBA_NOTION_READ_TOKEN="
            "op://Client-Tech-Power-Dev/Notion-Read-Connector/token\n",
        )
        self.assertEqual(call["env_mode"], 0o600)
        self.assertFalse(call["env_file"].exists())
        child_environment = call["kwargs"]["env"]
        self.assertEqual(child_environment["OP_SERVICE_ACCOUNT_TOKEN"], "bootstrap-token")
        self.assertNotIn("UNRELATED_CLIENT_SECRET", child_environment)

        audit_path = (
            self.repo_root
            / "service-data/clients/tech-power/credential-audit.jsonl"
        )
        audit_text = audit_path.read_text(encoding="utf-8")
        self.assertEqual(stat.S_IMODE(audit_path.stat().st_mode), 0o600)
        self.assertNotIn("op://", audit_text)
        self.assertNotIn("Notion-Read-Connector", audit_text)
        self.assertNotIn("bootstrap-token", audit_text)
        self.assertNotIn("goal-requests", audit_text)
        records = [json.loads(line) for line in audit_text.splitlines()]
        self.assertEqual([item["status"] for item in records], ["launching", "completed"])

    def test_unknown_adapter_is_denied_without_running(self) -> None:
        broker = OnePasswordSecretBroker(
            self.repo_root, self.config, runner=self.fake_runner, environment={}
        )
        with self.assertRaisesRegex(CredentialBrokerError, "Unknown"):
            broker.run("shell", [])
        self.assertEqual(self.calls, [])
        audit = (
            self.repo_root
            / "service-data/clients/tech-power/credential-audit.jsonl"
        ).read_text(encoding="utf-8")
        self.assertIn('"decision": "denied"', audit)
        self.assertIn('"status": "unknown-adapter"', audit)

    def test_scope_override_arguments_are_denied(self) -> None:
        broker = OnePasswordSecretBroker(
            self.repo_root, self.config, runner=self.fake_runner, environment={}
        )
        for argument in ("--client", "--repo-root=/tmp", "--no-masking"):
            with self.subTest(argument=argument):
                with self.assertRaisesRegex(CredentialBrokerError, "reserved"):
                    broker.run("notion-read", [argument])
        self.assertEqual(self.calls, [])

    def test_broker_fails_closed_when_audit_cannot_be_written(self) -> None:
        class FailingAudit:
            def append(self, **_: object) -> None:
                raise OSError("audit unavailable")

        broker = OnePasswordSecretBroker(
            self.repo_root,
            self.config,
            runner=self.fake_runner,
            environment={},
            audit_log=FailingAudit(),  # type: ignore[arg-type]
        )
        with self.assertRaisesRegex(OSError, "audit unavailable"):
            broker.run("notion-read", ["list"])
        self.assertEqual(self.calls, [])


if __name__ == "__main__":
    unittest.main()

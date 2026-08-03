"""Client-scoped secret-reference validation and 1Password runtime injection."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Mapping, Sequence

from .validation import ConfigurationValidationError, load_json, validate_against_schema


class CredentialBrokerError(ValueError):
    """Raised when secret policy rejects a configuration or invocation."""


@dataclass(frozen=True)
class CredentialBinding:
    capability: str
    environment_variable: str
    reference: str

    @property
    def vault(self) -> str:
        return self.reference.removeprefix("op://").split("/", 1)[0]


@dataclass(frozen=True)
class CredentialAdapter:
    adapter_id: str
    command: str
    required_capabilities: tuple[str, ...]


@dataclass(frozen=True)
class CredentialReferenceConfig:
    client_id: str
    environment: str
    provider_type: str
    service_identity: str
    allowed_vaults: tuple[str, ...]
    bindings: tuple[CredentialBinding, ...]
    adapters: tuple[CredentialAdapter, ...]


def load_credential_reference_config(
    path: Path, schema_path: Path
) -> CredentialReferenceConfig:
    data = load_json(path)
    errors = validate_against_schema(data, schema_path, "credential references")
    if errors:
        raise ConfigurationValidationError(errors)

    provider = data["provider"]
    bindings = tuple(
        CredentialBinding(
            capability=item["capability"],
            environment_variable=item["environment_variable"],
            reference=item["reference"],
        )
        for item in data["bindings"]
    )
    adapters = tuple(
        CredentialAdapter(
            adapter_id=item["adapter_id"],
            command=item["command"],
            required_capabilities=tuple(item["required_capabilities"]),
        )
        for item in data["adapters"]
    )

    def duplicates(values: Sequence[str]) -> list[str]:
        return sorted({value for value in values if values.count(value) > 1})

    duplicate_capabilities = duplicates([item.capability for item in bindings])
    duplicate_variables = duplicates([item.environment_variable for item in bindings])
    duplicate_adapters = duplicates([item.adapter_id for item in adapters])
    if duplicate_capabilities:
        errors.append(f"duplicate credential capabilities: {duplicate_capabilities}")
    if duplicate_variables:
        errors.append(f"duplicate credential environment variables: {duplicate_variables}")
    if duplicate_adapters:
        errors.append(f"duplicate credential adapter IDs: {duplicate_adapters}")

    allowed_vaults = tuple(provider["allowed_vaults"])
    capabilities = {item.capability for item in bindings}
    for binding in bindings:
        if binding.vault not in allowed_vaults:
            errors.append(
                f"credential capability {binding.capability!r} references a vault "
                "outside provider.allowed_vaults"
            )
    for adapter in adapters:
        missing = sorted(set(adapter.required_capabilities) - capabilities)
        if missing:
            errors.append(
                f"credential adapter {adapter.adapter_id!r} has unbound capabilities: "
                f"{missing}"
            )

    if errors:
        raise ConfigurationValidationError(errors)
    return CredentialReferenceConfig(
        client_id=data["client_id"],
        environment=data["environment"],
        provider_type=provider["type"],
        service_identity=provider["service_identity"],
        allowed_vaults=allowed_vaults,
        bindings=bindings,
        adapters=adapters,
    )


class SecretAuditLog:
    """Append-only, redacted credential-broker decision log."""

    def __init__(self, repo_root: Path, client_id: str) -> None:
        self.path = (
            repo_root.resolve()
            / "service-data"
            / "clients"
            / client_id
            / "credential-audit.jsonl"
        )

    def append(
        self,
        *,
        event_id: str,
        client_id: str,
        service_identity: str,
        adapter_id: str,
        capabilities: Sequence[str],
        decision: str,
        status: str,
        exit_code: int | None = None,
    ) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self.path.parent, 0o700)
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event_id": event_id,
            "client_id": client_id,
            "service_identity": service_identity,
            "adapter_id": adapter_id,
            "capabilities": list(capabilities),
            "decision": decision,
            "status": status,
            "exit_code": exit_code,
        }
        descriptor = os.open(
            self.path,
            os.O_APPEND | os.O_CREAT | os.O_WRONLY,
            0o600,
        )
        try:
            os.write(descriptor, (json.dumps(record, sort_keys=True) + "\n").encode())
        finally:
            os.close(descriptor)
        os.chmod(self.path, 0o600)


Runner = Callable[..., subprocess.CompletedProcess[object]]


class OnePasswordSecretBroker:
    """Launch an allowlisted adapter with only its declared secret references."""

    _RESERVED_ARGUMENTS = {"--client", "--repo-root", "--no-masking"}
    _INHERITED_ENVIRONMENT = {
        "PATH",
        "HOME",
        "USER",
        "LOGNAME",
        "LANG",
        "LC_ALL",
        "TMPDIR",
        "OP_SERVICE_ACCOUNT_TOKEN",
        "OP_ACCOUNT",
        "OP_CONNECT_HOST",
        "OP_CONNECT_TOKEN",
    }

    def __init__(
        self,
        repo_root: Path,
        config: CredentialReferenceConfig,
        *,
        runner: Runner = subprocess.run,
        environment: Mapping[str, str] | None = None,
        op_executable: str = "op",
        audit_log: SecretAuditLog | None = None,
    ) -> None:
        self.repo_root = repo_root.resolve()
        self.config = config
        self.runner = runner
        self.environment = dict(os.environ if environment is None else environment)
        self.op_executable = op_executable
        self.audit_log = audit_log or SecretAuditLog(self.repo_root, config.client_id)

    def run(self, adapter_id: str, arguments: Sequence[str]) -> int:
        event_id = str(uuid.uuid4())
        adapter = next(
            (item for item in self.config.adapters if item.adapter_id == adapter_id),
            None,
        )
        if adapter is None:
            self._audit(event_id, adapter_id, (), "denied", "unknown-adapter")
            raise CredentialBrokerError(f"Unknown credential adapter: {adapter_id}")
        if any(
            argument in self._RESERVED_ARGUMENTS
            or any(
                argument.startswith(f"{reserved}=")
                for reserved in self._RESERVED_ARGUMENTS
            )
            or "\x00" in argument
            or len(argument) > 4096
            for argument in arguments
        ):
            self._audit(
                event_id,
                adapter_id,
                adapter.required_capabilities,
                "denied",
                "invalid-arguments",
            )
            raise CredentialBrokerError(
                "Adapter arguments contain a reserved or invalid value"
            )

        binding_by_capability = {item.capability: item for item in self.config.bindings}
        selected = [binding_by_capability[item] for item in adapter.required_capabilities]
        self._audit(
            event_id,
            adapter_id,
            adapter.required_capabilities,
            "allowed",
            "launching",
        )

        descriptor, env_path_value = tempfile.mkstemp(
            prefix=f"uba-{self.config.client_id}-",
            suffix=".env",
        )
        env_path = Path(env_path_value)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                for binding in selected:
                    handle.write(f"{binding.environment_variable}={binding.reference}\n")
            os.chmod(env_path, 0o600)
            command = [
                self.op_executable,
                "run",
                f"--env-file={env_path}",
                "--",
                adapter.command,
                *arguments,
                "--client",
                self.config.client_id,
                "--repo-root",
                str(self.repo_root),
            ]
            child_environment = {
                key: value
                for key, value in self.environment.items()
                if key in self._INHERITED_ENVIRONMENT
            }
            result = self.runner(
                command,
                env=child_environment,
                check=False,
                cwd=self.repo_root,
            )
            exit_code = int(result.returncode)
            self._audit(
                event_id,
                adapter_id,
                adapter.required_capabilities,
                "allowed",
                "completed" if exit_code == 0 else "failed",
                exit_code,
            )
            return exit_code
        except Exception:
            self._audit(
                event_id,
                adapter_id,
                adapter.required_capabilities,
                "allowed",
                "failed",
            )
            raise
        finally:
            env_path.unlink(missing_ok=True)

    def _audit(
        self,
        event_id: str,
        adapter_id: str,
        capabilities: Sequence[str],
        decision: str,
        status: str,
        exit_code: int | None = None,
    ) -> None:
        self.audit_log.append(
            event_id=event_id,
            client_id=self.config.client_id,
            service_identity=self.config.service_identity,
            adapter_id=adapter_id,
            capabilities=capabilities,
            decision=decision,
            status=status,
            exit_code=exit_code,
        )

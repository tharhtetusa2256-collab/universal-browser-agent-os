from __future__ import annotations

import ipaddress
import socket
from dataclasses import dataclass
from urllib.parse import urlsplit


class DomainPolicyError(ValueError):
    """Raised when a URL falls outside the approved browser scope."""


def normalize_domain(value: str) -> str:
    """Return a lowercase ASCII hostname and reject URL-like input."""
    if not isinstance(value, str):
        raise DomainPolicyError("approved domain must be a string")

    domain = value.strip().rstrip(".").lower()
    if not domain or any(token in domain for token in ("://", "/", "@", "?", "#")):
        raise DomainPolicyError(f"invalid approved domain: {value!r}")

    try:
        domain = domain.encode("idna").decode("ascii")
    except UnicodeError as exc:
        raise DomainPolicyError(f"invalid internationalized domain: {value!r}") from exc

    labels = domain.split(".")
    if len(labels) < 2:
        raise DomainPolicyError(f"approved domain must contain a suffix: {value!r}")
    if any(
        not label
        or len(label) > 63
        or not label[0].isalnum()
        or not label[-1].isalnum()
        or any(not (character.isalnum() or character == "-") for character in label)
        for label in labels
    ):
        raise DomainPolicyError(f"invalid approved domain: {value!r}")
    return domain


def _is_ip_literal(hostname: str) -> bool:
    try:
        ipaddress.ip_address(hostname)
    except ValueError:
        return False
    return True


def _require_public_address(address: str) -> None:
    try:
        parsed = ipaddress.ip_address(address.split("%", 1)[0])
    except ValueError as exc:
        raise DomainPolicyError(f"DNS returned an invalid address: {address!r}") from exc

    if not parsed.is_global:
        raise DomainPolicyError(
            f"private, loopback, link-local, reserved, or non-global address blocked: {parsed}"
        )


def resolve_public_addresses(hostname: str, port: int) -> tuple[str, ...]:
    """Resolve a hostname and reject any non-public result."""
    try:
        records = socket.getaddrinfo(
            hostname,
            port,
            type=socket.SOCK_STREAM,
            proto=socket.IPPROTO_TCP,
        )
    except socket.gaierror as exc:
        raise DomainPolicyError(f"could not resolve approved hostname: {hostname}") from exc

    addresses = sorted({record[4][0] for record in records})
    if not addresses:
        raise DomainPolicyError(f"hostname resolved to no addresses: {hostname}")

    for address in addresses:
        _require_public_address(address)
    return tuple(addresses)


@dataclass(frozen=True)
class DomainPolicy:
    """Strict read-only navigation allowlist with basic SSRF defenses."""

    approved_domains: tuple[str, ...]
    include_subdomains: bool = True

    @classmethod
    def from_domains(
        cls,
        domains: list[str] | tuple[str, ...],
        *,
        include_subdomains: bool = True,
    ) -> "DomainPolicy":
        normalized = tuple(dict.fromkeys(normalize_domain(domain) for domain in domains))
        if not normalized:
            raise DomainPolicyError("at least one approved domain is required")
        return cls(normalized, include_subdomains=include_subdomains)

    def allows_hostname(self, hostname: str) -> bool:
        host = normalize_domain(hostname)
        for approved in self.approved_domains:
            if host == approved:
                return True
            if self.include_subdomains and host.endswith(f".{approved}"):
                return True
        return False

    def validate_url(self, url: str, *, resolve_dns: bool = True) -> str:
        """Validate and return a URL that is safe for this adapter to request."""
        if not isinstance(url, str) or not url.strip():
            raise DomainPolicyError("URL must be a non-empty string")

        parsed = urlsplit(url.strip())
        scheme = parsed.scheme.lower()
        if scheme not in {"http", "https"}:
            raise DomainPolicyError(f"unsupported URL scheme: {parsed.scheme!r}")
        if parsed.username is not None or parsed.password is not None:
            raise DomainPolicyError("credentials embedded in URLs are prohibited")
        if not parsed.hostname:
            raise DomainPolicyError("URL must contain a hostname")

        raw_hostname = parsed.hostname.rstrip(".").lower()
        if _is_ip_literal(raw_hostname):
            raise DomainPolicyError("IP-literal targets are prohibited")

        hostname = normalize_domain(raw_hostname)
        if not self.allows_hostname(hostname):
            raise DomainPolicyError(f"hostname is outside the approved domain scope: {hostname}")

        try:
            explicit_port = parsed.port
        except ValueError as exc:
            raise DomainPolicyError("URL contains an invalid port") from exc

        expected_port = 443 if scheme == "https" else 80
        if explicit_port is not None and explicit_port != expected_port:
            raise DomainPolicyError(
                f"non-standard port is prohibited for {scheme}: {explicit_port}"
            )

        if resolve_dns:
            resolve_public_addresses(hostname, explicit_port or expected_port)

        return parsed.geturl()

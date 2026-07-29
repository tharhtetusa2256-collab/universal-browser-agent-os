"""Network policy enforcement for the read-only Playwright adapter."""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from dataclasses import dataclass, field
from urllib.parse import urlsplit


class PolicyViolation(ValueError):
    """Raised when a URL or browser request is outside the approved policy."""


@dataclass
class DomainPolicy:
    approved_domains: tuple[str, ...]
    allow_private_network: bool = False
    _dns_cache: dict[str, tuple[str, ...]] = field(default_factory=dict, init=False)

    def __post_init__(self) -> None:
        self.approved_domains = tuple(
            domain.lower().rstrip(".") for domain in self.approved_domains
        )

    def validate_url_syntax(self, url: str) -> str:
        parsed = urlsplit(url)
        if parsed.scheme not in {"http", "https"}:
            raise PolicyViolation(f"Unsupported URL scheme: {parsed.scheme or '(missing)'}")
        if parsed.username or parsed.password:
            raise PolicyViolation("Credentials in URLs are prohibited")
        if not parsed.hostname:
            raise PolicyViolation("URL must include a hostname")

        hostname = parsed.hostname.lower().rstrip(".")
        if hostname not in self.approved_domains:
            raise PolicyViolation(f"Domain is not approved: {hostname}")

        try:
            port = parsed.port
        except ValueError as exc:
            raise PolicyViolation("URL contains an invalid port") from exc
        expected_port = 443 if parsed.scheme == "https" else 80
        if (
            port is not None
            and port != expected_port
            and not self.allow_private_network
        ):
            raise PolicyViolation(f"Non-standard port is prohibited: {port}")
        return hostname

    async def validate_url(self, url: str) -> str:
        hostname = self.validate_url_syntax(url)
        if self.allow_private_network:
            return hostname

        addresses = self._dns_cache.get(hostname)
        if addresses is None:
            addresses = await asyncio.to_thread(self._resolve, hostname)
            self._dns_cache[hostname] = addresses
        if not addresses:
            raise PolicyViolation(f"Domain did not resolve: {hostname}")
        for address in addresses:
            if not ipaddress.ip_address(address).is_global:
                raise PolicyViolation(
                    f"Domain resolves to a non-public address: {hostname} -> {address}"
                )
        return hostname

    @staticmethod
    def _resolve(hostname: str) -> tuple[str, ...]:
        try:
            records = socket.getaddrinfo(
                hostname,
                None,
                type=socket.SOCK_STREAM,
            )
        except socket.gaierror as exc:
            raise PolicyViolation(f"Domain did not resolve: {hostname}") from exc
        return tuple(sorted({record[4][0] for record in records}))

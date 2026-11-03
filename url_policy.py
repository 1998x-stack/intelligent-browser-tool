"""Central URL allowlist and network-address policy for browser and crawler.

This is a preflight guard, not a network sandbox: production browser traffic
must also be restricted at the network/egress layer to defeat DNS rebinding.
"""
from __future__ import annotations

import ipaddress
import socket
from dataclasses import dataclass
from urllib.parse import urlsplit


class URLPolicyError(ValueError):
    """A URL is outside the configured fetch boundary."""


def _hostname(value: str) -> str:
    value = value.strip().rstrip(".")
    if not value:
        raise URLPolicyError("missing hostname")
    try:
        return value.encode("idna").decode("ascii").lower()
    except UnicodeError as exc:
        raise URLPolicyError("invalid hostname") from exc


def _is_public(address: str) -> bool:
    try:
        return ipaddress.ip_address(address).is_global
    except ValueError:
        raise URLPolicyError("unparseable resolved IP address") from None


@dataclass(frozen=True)
class URLPolicy:
    allowed_domains: tuple[str, ...] = ()
    allow_subdomains: bool = True
    allow_private_network: bool = False

    def check(self, url: str, *, resolve_dns: bool = False) -> str:
        if not isinstance(url, str) or not url.strip():
            raise URLPolicyError("empty URL")
        try:
            parsed = urlsplit(url)
            port = parsed.port  # triggers validation of malformed ports
            host = _hostname(parsed.hostname or "")
        except (ValueError, UnicodeError) as exc:
            raise URLPolicyError(f"invalid URL: {exc}") from exc
        if parsed.scheme.lower() not in ("http", "https"):
            raise URLPolicyError("only http and https URLs are supported")
        if parsed.username is not None or parsed.password is not None:
            raise URLPolicyError("URLs with userinfo are not allowed")
        if "%" in host or "\\" in url or any(ord(c) < 32 for c in url):
            raise URLPolicyError("unsafe URL syntax")
        domains = tuple(_hostname(d) for d in self.allowed_domains if d)
        if domains and not any(
            host == domain or (self.allow_subdomains and host.endswith("." + domain))
            for domain in domains
        ):
            raise URLPolicyError("hostname is not in the domain allowlist")
        if not self.allow_private_network:
            if host == "localhost" or host.endswith(".localhost") or host.endswith(".local"):
                raise URLPolicyError("local hostname is not allowed")
            try:
                address = ipaddress.ip_address(host)
            except ValueError:
                address = None
            if address is not None and not address.is_global:
                raise URLPolicyError("non-public IP address is not allowed")
            if resolve_dns:
                try:
                    results = socket.getaddrinfo(
                        host, port or (443 if parsed.scheme == "https" else 80),
                        type=socket.SOCK_STREAM
                    )
                except OSError as exc:
                    raise URLPolicyError("hostname DNS resolution failed") from exc
                if not results or any(not _is_public(result[4][0]) for result in results):
                    raise URLPolicyError("hostname resolves to a non-public IP address")
        return url

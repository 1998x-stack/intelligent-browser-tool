"""Conservative URL admission policy for untrusted crawl targets.

This validates URLs and resolved addresses before an HTTP request. DNS validation
alone does not pin the socket destination; production deployments also need an
egress firewall/proxy that denies private networks and revalidates DNS at connect.
"""
from dataclasses import dataclass
import ipaddress
import socket
from urllib.parse import urlsplit


class URLPolicyError(ValueError):
    pass


@dataclass(frozen=True)
class URLPolicy:
    allowed_domains: tuple[str, ...] = ()
    allow_subdomains: bool = False

    def validate(self, url: str, *, resolve_dns: bool = True) -> str:
        try:
            parsed = urlsplit(url)
            host = parsed.hostname
            port = parsed.port
        except ValueError as exc:
            raise URLPolicyError("Malformed URL") from exc
        if parsed.scheme.lower() not in ("http", "https") or not host:
            raise URLPolicyError("Only HTTP(S) URLs with a hostname are allowed")
        if parsed.username is not None or parsed.password is not None:
            raise URLPolicyError("Credential-bearing URLs are forbidden")
        if any(ord(ch) < 32 or ord(ch) == 127 for ch in url):
            raise URLPolicyError("Control characters in URL")
        try:
            host = host.rstrip(".").encode("idna").decode("ascii").lower()
        except UnicodeError as exc:
            raise URLPolicyError("Invalid hostname") from exc
        allowed = tuple(d.rstrip(".").encode("idna").decode("ascii").lower()
                        for d in self.allowed_domains)
        if allowed and not any(
            host == domain or (self.allow_subdomains and host.endswith("." + domain))
            for domain in allowed
        ):
            raise URLPolicyError("Hostname not in allowed domains")
        if host in {"localhost", "localhost.localdomain"} or host.endswith(".localhost"):
            raise URLPolicyError("Localhost is forbidden")
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            address = None
        if address is not None and not address.is_global:
            raise URLPolicyError("Non-public IP address is forbidden")
        if resolve_dns:
            try:
                answers = socket.getaddrinfo(host, port or (443 if parsed.scheme == "https" else 80),
                                             type=socket.SOCK_STREAM)
            except (OSError, ValueError) as exc:
                raise URLPolicyError("DNS resolution failed") from exc
            if not answers:
                raise URLPolicyError("DNS returned no addresses")
            for answer in answers:
                try:
                    ip = ipaddress.ip_address(answer[4][0].split("%", 1)[0])
                except ValueError as exc:
                    raise URLPolicyError("Unrecognized resolved address") from exc
                if not ip.is_global:
                    raise URLPolicyError("DNS resolved to a non-public address")
        return url

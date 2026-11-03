"""Browser proxy admission and post-navigation checks.

This module cannot replace kernel/container egress enforcement. A browser can
emit redirects, subresources, WebSockets, and other traffic before Python sees
the final URL. Strict mode therefore REQUIRES an externally enforced proxy
plus a network namespace that has no direct route to the public network.
"""
from dataclasses import dataclass
from urllib.parse import urlsplit
from url_policy import URLPolicy, URLPolicyError


class NetworkBoundaryError(RuntimeError):
    """The required network isolation configuration is missing or invalid."""


def validate_proxy_url(proxy_url: str) -> str:
    try:
        parsed = urlsplit(proxy_url)
        port = parsed.port
    except ValueError as exc:
        raise NetworkBoundaryError("Malformed egress proxy URL") from exc
    if (parsed.scheme not in ("http", "https") or not parsed.hostname or
            not port or parsed.username is not None or
            parsed.password is not None or parsed.path not in ("", "/") or
            parsed.query or parsed.fragment):
        raise NetworkBoundaryError("Expected HTTP(S) proxy host:port, without credentials or URL path")
    return proxy_url


@dataclass(frozen=True)
class BrowserNetworkPolicy:
    allowed_domains: tuple[str, ...]
    strict: bool = False
    proxy_url: str | None = None

    def __post_init__(self):
        if self.strict:
            if not self.allowed_domains:
                raise NetworkBoundaryError("Strict browser mode requires explicit allowed domains")
            if not self.proxy_url:
                raise NetworkBoundaryError("Strict browser mode requires a controlled egress proxy")
            validate_proxy_url(self.proxy_url)
        elif self.proxy_url:
            validate_proxy_url(self.proxy_url)

    def check_navigation(self, url: str, *, resolve_dns: bool = False) -> str:
        return URLPolicy(self.allowed_domains).validate(url, resolve_dns=resolve_dns)

    def install_chrome_proxy(self, options) -> None:
        if not self.proxy_url:
            return
        # This is a proxy configuration, not proof of network isolation.
        options.add_argument(f"--proxy-server={self.proxy_url}")
        options.add_argument("--proxy-bypass-list=<-loopback>")

    def check_chrome_arguments(self, options: list[str]) -> None:
        if not self.strict:
            return
        conflicts = ("--no-proxy-server", "--proxy-server=", "--proxy-bypass-list=",
                     "--proxy-auto-detect", "--proxy-pac-url=")
        if any(arg.startswith(conflicts) for arg in options):
            raise NetworkBoundaryError("Browser chrome_options conflicts with the enforced proxy")

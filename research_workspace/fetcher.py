"""Explicit-allowlist public-web reader for trusted LOCAL operators only.

Preflight DNS is not socket pinning. Do not deploy this as an arbitrary-URL
remote browsing API without an independently reviewed egress firewall/proxy.
"""
from __future__ import annotations
from dataclasses import dataclass
from urllib.parse import urlsplit, urljoin, urldefrag
from urllib.robotparser import RobotFileParser
from collections.abc import Callable
import ipaddress
import re
import requests
import time
from threading import Lock
from bs4 import BeautifulSoup
from url_policy import URLPolicy, URLPolicyError


class FetchError(ValueError):
    """Human-readable, source-scoped controlled failure."""


@dataclass(frozen=True)
class SourcePolicy:
    hosts: tuple[str, ...]
    max_bytes: int = 400_000
    timeout_seconds: int = 12
    max_redirects: int = 3
    respect_robots: bool = True
    min_interval_seconds: float = 0.75
    user_agent: str = "EvidenceRadarLocal/0.2 (+https://github.com/1998x-stack/intelligent-browser-tool)"

    def __post_init__(self):
        if not self.hosts or any(not host or any(ch in host for ch in "/:@ ") for host in self.hosts):
            raise ValueError("Explicit allowed hostnames are required")
        for host in self.hosts:
            if host.lower() in {"localhost", "localhost.localdomain"} or host.lower().endswith(".localhost"):
                raise ValueError("Local hosts cannot be allowed")
            try:
                ip = ipaddress.ip_address(host)
            except ValueError:
                continue
            if not ip.is_global:
                raise ValueError("Private/non-global IP hosts cannot be allowed")
        if not 1 <= self.max_bytes <= 2_000_000:
            raise ValueError("max_bytes must be 1..2MB")
        if not 1 <= self.timeout_seconds <= 60:
            raise ValueError("timeout must be 1..60s")
        if not 0 <= self.max_redirects <= 5:
            raise ValueError("max_redirects must be 0..5")
        if not 0 <= self.min_interval_seconds <= 30:
            raise ValueError("min_interval_seconds must be 0..30")

    def validate(self, url: str, *, resolve_dns: bool = False) -> str:
        url = urldefrag(url)[0]
        try:
            parsed = urlsplit(url)
            if parsed.port not in (None, 80, 443):
                raise FetchError("Only standard HTTP(S) ports are supported")
            if parsed.scheme not in ("http", "https"):
                raise FetchError("Only HTTP(S) links are supported")
            URLPolicy(self.hosts).validate(url, resolve_dns=resolve_dns)
        except (URLPolicyError, ValueError) as exc:
            raise FetchError(f"Source outside permitted public hosts: {exc}") from exc
        return url


def html_to_text(body: bytes, *, encoding: str = "utf-8", max_chars: int = 48_000) -> str:
    """Extract bounded, plain, readable text. Never render site HTML in the UI."""
    soup = BeautifulSoup(body, "html.parser", from_encoding=encoding)
    for tag in soup(["script", "style", "noscript", "nav", "footer", "iframe", "svg", "form", "button"]):
        tag.decompose()
    text = " ".join(soup.stripped_strings)
    return re.sub(r"\s+", " ", text).strip()[:max_chars]


@dataclass(frozen=True)
class FetchedPage:
    final_url: str
    text: str
    bytes_read: int
    content_type: str


class BoundedFetcher:
    def __init__(self, policy: SourcePolicy, *, session: requests.Session | None = None):
        self.policy = policy
        self.session = session or requests.Session()
        self.session.trust_env = False  # don't inherit arbitrary proxy settings
        self.session.headers.update({"User-Agent": policy.user_agent, "Accept": "text/html,text/plain;q=0.8"})
        self._robot_cache: dict[str, RobotFileParser] = {}
        self._request_lock = Lock()
        self._next_request_at = 0.0

    def _download(self, url: str, *, max_bytes: int, allowed_types: tuple[str, ...]) -> tuple[bytes, str, str, int]:
        current = url
        for index in range(self.policy.max_redirects + 1):
            self.policy.validate(current, resolve_dns=True)
            try:
                # Local operator worker; keep controlled HTTP request frequency.
                with self._request_lock:
                    wait=max(0.0,self._next_request_at-time.monotonic())
                    if wait:time.sleep(wait)
                    self._next_request_at=time.monotonic()+self.policy.min_interval_seconds
                with self.session.get(current, timeout=(4, self.policy.timeout_seconds),
                                      allow_redirects=False, stream=True) as response:
                    if response.status_code in (301, 302, 303, 307, 308):
                        location = response.headers.get("Location")
                        if not location or index == self.policy.max_redirects:
                            raise FetchError("Redirect missing location or limit exceeded")
                        target = urljoin(current, location)
                        self.policy.validate(target, resolve_dns=False)
                        current = target
                        continue
                    if response.status_code >= 400:
                        raise FetchError(f"HTTP status {response.status_code}")
                    typ = response.headers.get("Content-Type", "").split(";", 1)[0].lower()
                    if typ not in allowed_types:
                        raise FetchError("Source is not a permitted HTML/plain-text document")
                    parts = []
                    size = 0
                    for chunk in response.iter_content(chunk_size=8192):
                        if not chunk:
                            continue
                        size += len(chunk)
                        if size > max_bytes:
                            raise FetchError("Source exceeds configured byte limit")
                        parts.append(chunk)
                    return b"".join(parts), current, typ, size
            except requests.RequestException as exc:
                raise FetchError(f"Network fetch failed: {type(exc).__name__}") from exc
        raise FetchError("Redirect limit exceeded")

    def _robots_allowed(self, url: str) -> bool:
        parsed = urlsplit(url)
        host = f"{parsed.scheme}://{parsed.netloc}"
        if host not in self._robot_cache:
            robots_url = host + "/robots.txt"
            # Fail closed if robots cannot be fetched; never bypass restrictions.
            try:
                body, _, _, _ = self._download(robots_url, max_bytes=32_000,
                                                allowed_types=("text/plain",))
            except FetchError as exc:
                raise FetchError(f"Robots policy unavailable: {exc}") from exc
            parser = RobotFileParser()
            parser.parse(body.decode("utf-8", "replace").splitlines())
            self._robot_cache[host] = parser
        return self._robot_cache[host].can_fetch(self.policy.user_agent, url)

    def fetch(self, url: str, *, byte_limit: int | None = None) -> FetchedPage:
        url = self.policy.validate(url, resolve_dns=True)
        if self.policy.respect_robots and not self._robots_allowed(url):
            raise FetchError("Robots policy does not permit this page")
        body, final, typ, size = self._download(url, max_bytes=min(self.policy.max_bytes,byte_limit or self.policy.max_bytes),
                                                allowed_types=("text/html", "text/plain"))
        if typ == "text/plain":
            text = re.sub(r"\s+", " ", body.decode("utf-8", "replace")).strip()[:48_000]
        else:
            text = html_to_text(body)
        if not text:
            raise FetchError("Page has no extractable plain text")
        return FetchedPage(final_url=final, text=text, bytes_read=size, content_type=typ)

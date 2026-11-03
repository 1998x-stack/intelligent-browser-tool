import socket

import pytest

from browser_engine import RequestsEngine
from config import BrowserConfig
from url_policy import URLPolicyError


class FakeResponse:
    def __init__(self, url, status_code, location=None):
        self.url = url
        self.status_code = status_code
        self.headers = {"Location": location} if location else {}
        self.closed = False

    def close(self):
        self.closed = True


@pytest.fixture
def engine(monkeypatch):
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *a, **k: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))]
    )
    config = BrowserConfig()
    config.allowed_domains = ["example.com"]
    instance = RequestsEngine(config)
    yield instance
    instance.close()


def test_redirect_within_allowlist(engine, monkeypatch):
    responses = [
        FakeResponse("https://example.com/a", 302, "/b"),
        FakeResponse("https://example.com/b", 200)
    ]
    visited = []

    def get(url, **kwargs):
        visited.append(url)
        assert kwargs["allow_redirects"] is False
        return responses.pop(0)

    monkeypatch.setattr(engine.session, "get", get)
    response = engine._get_with_validated_redirects("https://example.com/a")
    assert response.url == "https://example.com/b"
    assert visited == ["https://example.com/a", "https://example.com/b"]


@pytest.mark.parametrize("redirect", [
    "https://example.com.attacker.test/secret", "http://127.0.0.1/admin",
    "http://169.254.169.254/latest/meta-data/"
])
def test_redirect_outside_policy_blocked(engine, monkeypatch, redirect):
    visited = []
    response = FakeResponse("https://example.com/a", 302, redirect)

    def get(url, **kwargs):
        visited.append(url)
        return response

    monkeypatch.setattr(engine.session, "get", get)
    with pytest.raises(URLPolicyError):
        engine._get_with_validated_redirects("https://example.com/a")
    assert visited == ["https://example.com/a"]
    assert response.closed


def test_explicit_redirect_override_rejected(engine):
    with pytest.raises(URLPolicyError, match="overridden"):
        engine._get_with_validated_redirects("https://example.com", allow_redirects=True)

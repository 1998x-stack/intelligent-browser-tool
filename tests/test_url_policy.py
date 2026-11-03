import socket

import pytest

from url_policy import URLPolicy, URLPolicyError


@pytest.mark.parametrize("url", [
    "https://example.com/", "https://sub.example.com/path", "http://example.com:8080/a"
])
def test_allowed_domain_and_subdomain(url):
    assert URLPolicy(("example.com",)).check(url) == url


@pytest.mark.parametrize("url", [
    "https://example.com.attacker.tld/", "https://notexample.com/",
    "https://example.com@evil.com/", "file:///etc/passwd",
    "https://localhost/", "http://127.0.0.1/", "http://10.0.0.1/",
    "http://169.254.169.254/", "http://[::1]/", "http://0.0.0.0/",
    "http://internal.local/", "https://example.com\\@evil.com/",
    "https://example.com:bad/"
])
def test_reject_unsafe_urls(url):
    with pytest.raises(URLPolicyError):
        URLPolicy(("example.com",)).check(url)


def test_no_implicit_parent_domain():
    with pytest.raises(URLPolicyError):
        URLPolicy(("www.example.com",)).check("https://example.com")


def test_subdomain_requires_explicit_optin():
    with pytest.raises(URLPolicyError):
        URLPolicy(("example.com",), allow_subdomains=False).check("https://sub.example.com")


def test_private_network_is_opt_in_only():
    assert URLPolicy(("localhost",), allow_private_network=True).check("http://localhost:8000")


def test_dns_local_address_rejected(monkeypatch):
    def fake_dns(*args, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.10", 443))]
    monkeypatch.setattr(socket, "getaddrinfo", fake_dns)
    with pytest.raises(URLPolicyError, match="non-public"):
        URLPolicy(("example.com",)).check("https://example.com", resolve_dns=True)


def test_dns_public_address_accepted(monkeypatch):
    def fake_dns(*args, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))]
    monkeypatch.setattr(socket, "getaddrinfo", fake_dns)
    assert URLPolicy(("example.com",)).check("https://example.com", resolve_dns=True)

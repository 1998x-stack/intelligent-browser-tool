import pytest

from url_policy import URLPolicy, URLPolicyError
from frontier_state import FrontierState


@pytest.mark.parametrize("url", [
    "http://localhost/", "http://127.0.0.1/", "http://169.254.169.254/",
    "http://10.0.0.1/", "http://[::1]/", "file:///etc/passwd",
    "https://example.com@evil.test/", "http://example.com.evil.test/",
    "https://badexample.com/", "https://example.com:bad/"
])
def test_reject_unsafe_targets(url):
    with pytest.raises(URLPolicyError):
        URLPolicy(("example.com",)).validate(url, resolve_dns=False)


def test_exact_host_and_opt_in_subdomains():
    URLPolicy(("example.com",)).validate("https://example.com/page", resolve_dns=False)
    with pytest.raises(URLPolicyError):
        URLPolicy(("example.com",)).validate("https://www.example.com/", resolve_dns=False)
    URLPolicy(("example.com",), allow_subdomains=True).validate(
        "https://www.example.com/", resolve_dns=False)


def test_resolved_private_ip_rejected(monkeypatch):
    import socket
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: [
        (socket.AF_INET, socket.SOCK_STREAM, 0, "", ("10.1.2.3", 80))])
    with pytest.raises(URLPolicyError):
        URLPolicy(("example.com",)).validate("http://example.com/")


def test_frontier_dedup_lease_resume(tmp_path):
    with FrontierState(tmp_path / "frontier.db", URLPolicy(("example.com",)),
                       lease_seconds=10) as queue:
        assert queue.enqueue("https://example.com/a", 1)
        assert not queue.enqueue("https://example.com/a#section", 1)
        assert queue.enqueue("https://example.com/b", 2)
        first = queue.lease(now=100)
        assert first["url"] == "https://example.com/a"
        assert queue.lease(now=100)["url"] == "https://example.com/b"
        assert queue.recover_expired(now=111) == 2
        assert queue.lease(now=111)["url"] == "https://example.com/a"
        queue.finish("https://example.com/a", state="completed")
        assert queue.counts()["completed"] == 1


def test_finishing_unleased_raises(tmp_path):
    with FrontierState(tmp_path / "frontier.db", URLPolicy(("example.com",))) as q:
        q.enqueue("https://example.com/")
        with pytest.raises(ValueError):
            q.finish("https://example.com/", state="completed")

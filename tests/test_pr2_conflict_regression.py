"""Regression checks for PR #2 / PR #1 semantic merge decisions."""
import pytest

from url_policy import URLPolicy, URLPolicyError
from config import Config
from url_queue import URLQueue


def test_policy_api_is_consistently_validate():
    policy = URLPolicy(("example.com",))
    assert policy.validate("https://example.com/path", resolve_dns=False)
    with pytest.raises(URLPolicyError):
        policy.validate("https://example.com.attacker.invalid/", resolve_dns=False)


def test_subdomains_need_explicit_permission():
    with pytest.raises(URLPolicyError):
        URLPolicy(("example.com",)).validate(
            "https://sub.example.com/", resolve_dns=False)
    assert URLPolicy(("example.com",), allow_subdomains=True).validate(
        "https://sub.example.com/", resolve_dns=False)


def test_frontier_preserves_exact_allowlist():
    cfg = Config()
    cfg.browser.allowed_domains = ["example.com"]
    queue = URLQueue(cfg)
    assert queue.add("https://example.com/valid")
    assert not queue.add("https://example.com.attacker.invalid/not-allowed")


def test_compatibility_cli_import():
    import main
    assert callable(main.main)


def test_package_metadata_exists():
    from pathlib import Path
    project = Path(__file__).resolve().parents[1]
    contents = (project / "pyproject.toml").read_text("utf-8")
    assert '[project.scripts]' in contents
    assert 'intelligent-browser = "crawler:main"' in contents

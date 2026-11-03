from datetime import datetime

import pytest

from config import Config
from crawler import CrawlConfig, PageResult, WebCrawler
from url_queue import URLQueue


def make_crawler(tmp_path):
    config = Config()
    config.browser.allowed_domains = ["example.com"]
    crawler = WebCrawler.__new__(WebCrawler)
    crawler.crawl_config = CrawlConfig(
        start_url="https://example.com/", intent="research",
        output_dir=str(tmp_path), use_search_seeds=False
    )
    crawler.url_queue = URLQueue(config)
    crawler.results = []
    crawler.start_time = datetime.now()
    return crawler


def test_checkpoint_restores_frontier_and_prior_results(tmp_path):
    old = make_crawler(tmp_path)
    old.url_queue.add("https://example.com/next")
    old.results = [PageResult(url="https://example.com/done", success=True, analyzed=True)]
    old._save_checkpoint()

    recovered = make_crawler(tmp_path)
    recovered._load_checkpoint()
    assert len(recovered.results) == 1
    assert recovered.results[0].analyzed
    assert recovered.url_queue.get_next().url == "https://example.com/next"


def test_resume_rejects_other_task_intent(tmp_path):
    old = make_crawler(tmp_path)
    old._save_checkpoint()
    recovered = make_crawler(tmp_path)
    recovered.crawl_config.intent = "other"
    with pytest.raises(ValueError, match="does not match"):
        recovered._load_checkpoint()


def test_missing_checkpoint_is_not_silent_restart(tmp_path):
    crawler = make_crawler(tmp_path)
    with pytest.raises(FileNotFoundError):
        crawler._load_checkpoint()

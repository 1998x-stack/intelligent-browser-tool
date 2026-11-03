"""Drive real Chrome running inside a Docker --internal network."""
import json
import time
import urllib.request
from selenium import webdriver
from selenium.webdriver.chrome.options import Options


def proxy_hits():
    with urllib.request.urlopen("http://127.0.0.1:3128/__stats__", timeout=4) as r:
        return json.load(r)


def main():
    endpoint = "http://127.0.0.1:4444"
    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--proxy-server=http://local-proxy:3128")
    options.add_argument("--proxy-bypass-list=<-loopback>")
    options.page_load_strategy = "eager"
    browser = webdriver.Remote(command_executor=endpoint, options=options)
    try:
        browser.set_page_load_timeout(20)
        browser.get("http://allowed.test/redirect")
        assert "Isolated Browser Verified" in browser.page_source, browser.page_source[:500]
        deadline = time.monotonic() + 6
        while time.monotonic() < deadline:
            hits = proxy_hits()
            if any(row[0] == "blocked.test" for row in hits):
                break
            time.sleep(0.2)
        assert ["allowed.test", "/redirect"] in hits, hits
        assert ["allowed.test", "/start"] in hits, hits
        assert any(h[0] == "blocked.test" for h in hits), hits
        print("INTERNAL_PROXY_NAVIGATION_AND_SUBRESOURCES_PASS")
    finally:
        browser.quit()

    # Independent Chrome session without a proxy must not reach the public
    # internet from its internal-only Docker network.
    direct = Options()
    direct.add_argument("--headless=new")
    direct.add_argument("--no-proxy-server")
    direct.page_load_strategy = "eager"
    driver = webdriver.Remote(command_executor=endpoint, options=direct)
    try:
        driver.set_page_load_timeout(8)
        try:
            driver.get("http://example.com/")
        except Exception:
            pass
        source = driver.page_source
        assert "Example Domain" not in source, "Browser escaped internal network"
        print("INTERNAL_NETWORK_DENIES_DIRECT_PUBLIC_NAVIGATION")
    finally:
        driver.quit()


if __name__ == "__main__":
    main()

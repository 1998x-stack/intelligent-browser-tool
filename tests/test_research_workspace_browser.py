"""Real Chrome local-workspace E2E, using an approved in-memory fetch stub.

No third-party URLs or browser subrequests are emitted by this test.
"""
import json
import tempfile
import unittest
from pathlib import Path
from threading import Thread
from http.server import ThreadingHTTPServer
from research_workspace import ResearchService, SourcePolicy
from research_workspace.fetcher import FetchedPage
from research_workspace.server import handler_factory

try:
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
except ImportError:
    webdriver = None


class FixtureFetcher:
    def fetch(self,url,*,byte_limit):
        content="Aster Pro $29/month. API available." if url.startswith("https://alpha.example/") else "Birch $49/month. API is limited."
        return FetchedPage(url,content,len(content.encode()),"text/html")


@unittest.skipIf(webdriver is None,"Install selenium browser extra to run E2E")
class LocalResearchBrowserTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory(prefix="evidence-radar-browser-")
        cls.download_dir=Path(cls.tmp.name)
        cls.service=ResearchService(cls.download_dir/"state.db",
                                    SourcePolicy(("alpha.example","beta.example"),respect_robots=False),
                                    fetcher=FixtureFetcher())
        cls.token="test-token-"+"z"*40
        cls.server=ThreadingHTTPServer(("127.0.0.1",0),handler_factory(cls.service,cls.token))
        cls.thread=Thread(target=cls.server.serve_forever,daemon=True)
        cls.thread.start()
        opts=Options()
        opts.add_argument("--headless=new")
        opts.add_argument("--no-sandbox")
        opts.add_argument("--disable-dev-shm-usage")
        opts.add_argument("--window-size=1420,1000")
        opts.add_argument("--disable-background-networking")
        opts.add_experimental_option("prefs",{"download.default_directory":str(cls.download_dir),"download.prompt_for_download":False})
        cls.browser=webdriver.Chrome(options=opts)
        cls.browser.execute_cdp_cmd("Page.setDownloadBehavior",{"behavior":"allow","downloadPath":str(cls.download_dir)})
        cls.url=f"http://127.0.0.1:{cls.server.server_port}/live.html"

    @classmethod
    def tearDownClass(cls):
        cls.browser.quit()
        cls.server.shutdown();cls.server.server_close();cls.thread.join(timeout=4)
        cls.tmp.cleanup()

    def test_workflow_source_evidence_export_and_deletion(self):
        b=self.browser
        b.get(self.url)
        b.find_element(By.ID,"token").send_keys(self.token)
        b.find_element(By.ID,"connect").click()
        WebDriverWait(b,8).until(lambda d:"alpha.example" in d.find_element(By.ID,"approved-hosts").text)
        b.find_element(By.ID,"sources").send_keys("Aster | https://alpha.example/pricing\nBirch | https://beta.example/pricing")
        b.find_element(By.ID,"start").click()
        WebDriverWait(b,12).until(lambda d:d.find_element(By.ID,"run-state").text=="COMPLETED")
        self.assertIn("2 / 5",b.find_element(By.ID,"metrics").text)
        self.assertIn("SUPPORTED",b.find_element(By.ID,"comparison").text)
        buttons=b.find_elements(By.CSS_SELECTOR,"#comparison tbody button")
        self.assertGreaterEqual(len(buttons),4)
        buttons[0].click()
        evidence=b.find_element(By.ID,"evidence")
        self.assertIn("SHA-256",evidence.text)
        self.assertIn("$29/month",evidence.text)
        self.assertEqual(b.switch_to.active_element.get_attribute("id"),"evidence")
        b.find_element(By.ID,"export-json").click()
        WebDriverWait(b,8).until(lambda _:len(list(self.download_dir.glob("research-*.json")))==1)
        payload=json.loads(next(self.download_dir.glob("research-*.json")).read_text())
        self.assertEqual(payload["mode"],"local_live")
        self.assertEqual(len(payload["sources"]),2)
        b.find_element(By.ID,"export-md").click()
        WebDriverWait(b,8).until(lambda _:len(list(self.download_dir.glob("research-*.md")))==1)
        self.assertIn("Original source evidence",next(self.download_dir.glob("research-*.md")).read_text())
        b.set_window_size(390,850)
        width=b.execute_script("return document.documentElement.scrollWidth")
        viewport=b.execute_script("return window.innerWidth")
        self.assertLessEqual(width,viewport+2,f"mobile overflow {width}>{viewport}")
        delete=b.find_element(By.CSS_SELECTOR,".saved-project .delete")
        b.execute_script("arguments[0].scrollIntoView({block:'center'})",delete)
        delete.click();b.switch_to.alert.accept()
        WebDriverWait(b,8).until(lambda d:"No saved projects yet" in d.find_element(By.ID,"projects").text)
        b.set_window_size(1420,1000)


if __name__=="__main__":
    unittest.main()

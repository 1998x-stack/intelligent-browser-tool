"""V0.3 Chrome E2E: real DOM interactions against local deterministic research API.

All fetched source pages are injected fixtures; no internet browsing occurs.
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
    from selenium.webdriver.support.select import Select
except ImportError:
    webdriver=None

URL='https://alpha.example/pricing'


class MutableFetcher:
    content='Alpha Pro $29/month. API available.'
    def fetch(self,url,*,byte_limit):
        t=self.content
        return FetchedPage(url,t,len(t.encode()),'text/html')


@unittest.skipIf(webdriver is None,'Install selenium browser extra')
class MonitorBrowserTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory(prefix='evidence-radar-monitor-')
        cls.folder=Path(cls.temp.name)
        cls.fetcher=MutableFetcher()
        cls.service=ResearchService(cls.folder/'state.db',
          SourcePolicy(('alpha.example',),respect_robots=False),fetcher=cls.fetcher)
        cls.project=cls.service.create_project({
          'question':'Compare documented pricing for Alpha Pro',
          'sources':[{'url':URL,'label':'Alpha'}],
          'fields':[{'key':'price','kind':'price','label':'Price'}]})
        cls.service.execute(cls.service.new_run(cls.project['id'])['id'])
        cls.fetcher.content='Alpha Pro $39/month. API available.'
        cls.service.execute(cls.service.new_run(cls.project['id'])['id'])
        cls.token='browser-monitor-'+('x'*40)
        cls.server=ThreadingHTTPServer(('127.0.0.1',0),handler_factory(cls.service,cls.token))
        cls.thread=Thread(target=cls.server.serve_forever,daemon=True);cls.thread.start()
        opts=Options();opts.add_argument('--headless=new');opts.add_argument('--no-sandbox')
        opts.add_argument('--disable-dev-shm-usage');opts.add_argument('--window-size=1420,1100')
        opts.add_argument('--disable-background-networking')
        opts.add_experimental_option('prefs',{'download.default_directory':str(cls.folder),
                                               'download.prompt_for_download':False})
        cls.browser=webdriver.Chrome(options=opts)
        cls.browser.execute_cdp_cmd('Page.setDownloadBehavior',
             {'behavior':'allow','downloadPath':str(cls.folder)})
        cls.url=f'http://127.0.0.1:{cls.server.server_port}/live.html'

    @classmethod
    def tearDownClass(cls):
        cls.browser.quit();cls.server.shutdown();cls.server.server_close()
        cls.thread.join(timeout=3);cls.temp.cleanup()

    def test_live_change_inbox_schedule_ack_digest_and_mobile(self):
        b=self.browser;b.get(self.url)
        b.find_element(By.ID,'token').send_keys(self.token)
        b.find_element(By.ID,'connect').click()
        WebDriverWait(b,8).until(lambda d: len(d.find_elements(By.CSS_SELECTOR,'.saved-project button'))>=1)
        b.find_element(By.CSS_SELECTOR,'.saved-project button').click()
        WebDriverWait(b,8).until(lambda d: not d.find_element(By.ID,'monitoring-panel').get_attribute('hidden'))
        changes=b.find_element(By.ID,'monitor-changes')
        self.assertIn('CHANGED',changes.text)
        self.assertIn('USD 29/month',changes.text)
        self.assertIn('USD 39/month',changes.text)
        details=changes.find_element(By.TAG_NAME,'summary')
        b.execute_script("arguments[0].scrollIntoView({block:'center'})",details)
        details.click()
        self.assertIn('$29/month',changes.text)
        self.assertIn('$39/month',changes.text)
        b.find_element(By.ID,'export-digest').click()
        WebDriverWait(b,8).until(lambda _:any(self.folder.glob('research-digest-*.md')))
        digest=next(self.folder.glob('research-digest-*.md')).read_text()
        self.assertIn('39',digest)
        ack=changes.find_element(By.XPATH,'.//button[contains(text(),"Acknowledge")]')
        b.execute_script("arguments[0].scrollIntoView({block:'center'})",ack)
        ack.click()
        WebDriverWait(b,8).until(lambda d:'ACKNOWLEDGED' in d.find_element(By.ID,'monitor-changes').text)
        checkbox=b.find_element(By.ID,'schedule-enabled')
        b.execute_script("arguments[0].scrollIntoView({block:'center'})",checkbox)
        checkbox.click()
        Select(b.find_element(By.ID,'schedule-interval')).select_by_value('86400')
        save=b.find_element(By.CSS_SELECTOR,'#schedule-form button')
        save.click()
        WebDriverWait(b,8).until(lambda d:'Next due:' in d.find_element(By.ID,'schedule-state').text)
        b.find_element(By.ID,'run-due').click()
        WebDriverWait(b,8).until(lambda d:'No schedules are due' in d.find_element(By.ID,'schedule-state').text)
        b.set_window_size(390,850)
        width=b.execute_script('return document.documentElement.scrollWidth')
        viewport=b.execute_script('return window.innerWidth')
        self.assertLessEqual(width,viewport+2,f'mobile overflow: {width} > {viewport}')
        b.set_window_size(1420,1100)


if __name__=='__main__':unittest.main()

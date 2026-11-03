"""Run against: python3 -m http.server 8765 --directory apps/evidence-demo.
Requires real Chrome + Selenium. No live third-party URLs are visited.
"""
import os
import unittest
from pathlib import Path
from urllib.request import urlopen

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait


class EvidenceDemoE2E(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        options = Options()
        options.add_argument('--headless=new')
        options.add_argument('--no-sandbox')
        options.add_argument('--disable-dev-shm-usage')
        options.add_argument('--window-size=1420,1000')
        options.add_argument('--disable-background-networking')
        options.add_argument('--disable-features=MediaRouter')
        binary = os.environ.get('CHROME_BIN')
        if binary:
            options.binary_location = binary
        cls.driver = webdriver.Chrome(options=options)
        cls.driver.set_page_load_timeout(25)

    @classmethod
    def tearDownClass(cls):
        cls.driver.quit()

    def test_first_120_seconds_path_and_evidence(self):
        driver = self.driver
        driver.get(os.environ.get('EVIDENCE_DEMO_URL', 'http://127.0.0.1:8765/'))
        WebDriverWait(driver, 12).until(lambda d: d.find_element(By.ID, 'research-app').is_displayed())
        self.assertIn('Research the web', driver.find_element(By.ID, 'hero-title').text)
        self.assertIn('fictional', driver.find_element(By.CLASS_NAME, 'notice-banner').text.lower())
        driver.find_element(By.ID, 'hero-demo').click()
        self.assertIn('research', driver.find_element(By.ID, 'workspace-heading').text.lower())
        self.assertIn('09', driver.find_element(By.ID, 'metrics').text)
        driver.find_element(By.ID, 'tab-compare').click()
        self.assertTrue(driver.find_element(By.CLASS_NAME, 'matrix').is_displayed())
        driver.find_element(By.CSS_SELECTOR, 'button[data-fact="cedar-api"]').click()
        evidence = driver.find_element(By.ID, 'evidence-pane').text
        self.assertIn('Enterprise contracts only', evidence)
        self.assertIn('Starter and Enterprise', evidence)
        self.assertIn('Conflicting sources', evidence)
        driver.find_element(By.ID, 'tab-sources').click()
        self.assertEqual(len(driver.find_elements(By.CLASS_NAME, 'source-card')), 4)
        driver.find_element(By.ID, 'tab-runs').click()
        self.assertIn('not a live crawl', driver.find_element(By.ID, 'research-content').text.lower())
        driver.find_element(By.CSS_SELECTOR, 'button[data-template="api"]').click()
        self.assertEqual(driver.find_element(By.ID, 'tab-brief').get_attribute('aria-selected'), 'true')
        self.assertEqual(driver.find_element(By.CSS_SELECTOR, 'button[data-template="api"]').get_attribute('aria-pressed'), 'true')
        driver.find_element(By.ID, 'reset-demo').click()
        self.assertEqual(driver.find_element(By.CSS_SELECTOR, 'button[data-template="pricing"]').get_attribute('aria-pressed'), 'true')
        self.assertFalse(driver.find_element(By.ID, 'research-app').get_attribute('hidden'))

    def test_accessibility_tabs_mobile_and_no_horizontal_overflow(self):
        driver = self.driver
        driver.set_window_size(390, 850)
        driver.get(os.environ.get('EVIDENCE_DEMO_URL', 'http://127.0.0.1:8765/'))
        WebDriverWait(driver, 12).until(lambda d: d.find_element(By.ID, 'research-app').is_displayed())
        width = driver.execute_script('return document.documentElement.scrollWidth')
        viewport = driver.execute_script('return window.innerWidth')
        self.assertLessEqual(width, viewport + 2, f'horizontal overflow: {width} > {viewport}')
        tab = driver.find_element(By.ID, 'tab-brief')
        tab.click()
        tab.send_keys(Keys.ARROW_RIGHT)
        self.assertEqual(driver.find_element(By.ID, 'tab-compare').get_attribute('aria-selected'), 'true')
        self.assertEqual(driver.find_element(By.ID, 'tab-brief').get_attribute('tabindex'), '-1')
        self.assertEqual(driver.find_element(By.ID, 'tab-compare').get_attribute('tabindex'), '0')
        button = driver.find_element(By.CSS_SELECTOR, 'button[data-fact="cedar-price"]')
        driver.execute_script('arguments[0].click()', button)
        self.assertIn('Evidence insufficient', driver.find_element(By.ID, 'evidence-pane').text)
        self.assertEqual(driver.switch_to.active_element.get_attribute('id'), 'evidence-title')
        driver.set_window_size(1420, 1000)


if __name__ == '__main__':
    unittest.main()

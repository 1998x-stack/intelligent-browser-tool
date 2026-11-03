"""Dependency-free static contract checks for the first product demo."""
from html.parser import HTMLParser
from pathlib import Path
import json
import re
import unittest
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1] / 'apps' / 'evidence-demo'


class DocumentParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.ids = []
        self.scripts = []
        self.links = []
        self.images_without_alt = []
        self.controls = []
        self.uses_iframe = False

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if 'id' in attributes:
            self.ids.append(attributes['id'])
        if tag == 'script':
            self.scripts.append(attributes)
        if tag == 'link':
            self.links.append(attributes)
        if tag == 'img' and 'alt' not in attributes:
            self.images_without_alt.append(attrs)
        if tag in ('button', 'a'):
            self.controls.append((tag, attributes))
        if tag == 'iframe':
            self.uses_iframe = True


class EvidenceDemoStatic(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = (ROOT / 'index.html').read_text()
        cls.css = (ROOT / 'styles.css').read_text()
        cls.js = (ROOT / 'src' / 'app.js').read_text()
        cls.data = json.loads((ROOT / 'data' / 'demo.json').read_text())
        cls.dom = DocumentParser()
        cls.dom.feed(cls.html)

    def test_duplicate_ids_and_fundamental_semantics(self):
        self.assertEqual(len(self.dom.ids), len(set(self.dom.ids)))
        for target in ['main', 'hero-title', 'workspace', 'research-app', 'research-content',
                       'evidence-title', 'live-message', 'error-state', 'loading-state']:
            self.assertIn(target, self.dom.ids)
        self.assertIn('class="skip-link"', self.html)
        self.assertIn('role="tablist"', self.html)
        self.assertIn('aria-live="polite"', self.html)

    def test_fixtures_never_call_real_vendor_hosts(self):
        self.assertEqual(self.data['mode'], 'offline_fixture')
        for source in self.data['snapshots']:
            host = urlsplit(source['url']).hostname
            self.assertTrue(host.endswith('.example'), host)
            self.assertTrue(source['fixture'])
        self.assertIn('No live browsing', self.html)

    def test_no_external_runtime_code_or_dangerous_embeds(self):
        self.assertFalse(self.dom.uses_iframe)
        self.assertFalse(self.dom.images_without_alt)
        self.assertTrue(all((script.get('src') or '').startswith('./') for script in self.dom.scripts))
        self.assertFalse(any('@import' in line for line in self.css.splitlines()))
        self.assertNotIn('.innerHTML', self.js)
        self.assertNotIn('eval(', self.js)
        self.assertNotIn('localStorage', self.js)
        self.assertIn('textContent', self.js)

    def test_mobile_reduced_motion_and_keyboard_support(self):
        self.assertIn('@media(max-width:780px)', self.css)
        self.assertIn('@media(max-width:420px)', self.css)
        self.assertIn('prefers-reduced-motion:reduce', self.css)
        self.assertIn("'ArrowRight'", self.js)
        self.assertIn("'ArrowLeft'", self.js)
        self.assertIn('evidenceTitle.focus', self.js)

    def test_html_link_refs_and_tab_panels(self):
        for identifier in ['tab-brief', 'tab-compare', 'tab-sources', 'tab-runs', 'download-json', 'download-md']:
            self.assertIn(identifier, self.dom.ids)
        for link in self.dom.links:
            self.assertFalse((link.get('href') or '').startswith(('http://', 'https://')))
        self.assertIn('aria-controls="research-content"', self.html)


if __name__ == '__main__':
    unittest.main()

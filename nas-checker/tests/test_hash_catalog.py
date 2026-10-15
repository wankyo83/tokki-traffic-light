import asyncio
import copy
import os
import tempfile
import unittest
from unittest.mock import patch

from signal_nas.browser import BrowserVerifier
from signal_nas.model import BY_KEY, RULES, validate_page
from signal_nas.server import public_overview
from signal_nas.service import CheckerService

BASE = 'https://blacktoon424.com'

def page(links=None, fragment=''):
    return {'url': BASE + '/' + fragment, 'status': 200, 'title': '블랙툰',
            'body': '연재 완결 인기 작품', 'html': '<html>catalog</html>',
            'links': links if links is not None else [
                {'href': BASE + '/#continue'}, {'href': BASE + '/webtoon/123.html'},
                {'href': BASE + '/webtoon/456.html'}]}

def validate(p, **kw):
    return validate_page('blacktoon', p['url'], p['title'], p['body'], p['links'], p['html'],
                         p['status'], require_candidate_content=True, **kw)

class HashCatalogTests(unittest.TestCase):
    def test_rendered_hash_category_accepts_two_distinct_works(self):
        self.assertEqual(validate(page())[0], BASE)

    def test_empty_menu_or_repeated_work_is_not_a_candidate(self):
        links = [{'href': BASE + '/#continue'}, {'href': BASE + '/webtoon/123.html'}]
        self.assertIsNone(validate(page(links + [links[-1]]))[0])

    def test_external_work_links_do_not_verify_a_candidate(self):
        self.assertIsNone(validate(page([{'href': BASE + '/#continue'},
            {'href': 'https://other.example/webtoon/123.html'},
            {'href': 'https://other.example/webtoon/456.html'}]))[0])

    def test_hash_route_needs_work_content_not_just_fragment(self):
        self.assertEqual(validate(page(fragment='#continue'), requested_category='/#continue')[0], BASE)
        self.assertIsNone(validate(page([], '#continue'), requested_category='/#continue')[0])

    def test_403_451_challenge_and_cross_family_still_fail(self):
        for change in ({'status': 403}, {'status': 451}, {'title': 'Just a moment...'},
                       {'url': 'https://advert.example/#continue'}):
            p = page(); p.update(change)
            self.assertIsNone(validate(p)[0])

    def test_fragment_fallback_is_actually_probed(self):
        visited = []
        async def fake_page(url, **kw):
            visited.append((url, kw))
            return page([], '') if url == BASE else page(fragment='#continue')
        browser = BrowserVerifier()
        with patch.object(browser, '_page', fake_page):
            result, _ = asyncio.run(browser.verify('blacktoon', BASE, candidate=True))
        self.assertEqual(result, BASE)
        self.assertEqual([x[0] for x in visited], [BASE, BASE + '/#continue'])
        self.assertEqual(visited[0][1]['content_selector'], RULES['blacktoon']['contentReadySelector'])

    def test_failed_candidate_is_preserved_separately_from_active(self):
        class FakeBrowser:
            async def discover(self, _): return [BASE], 'guide read'
            async def verify(self, *args, **kw): return None, 'category navigation not found'
            async def __aenter__(self): return self
            async def __aexit__(self, *_): pass
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {'DATA_DIR': tmp}):
            service = CheckerService()
            old = {'schemaVersion': 1, 'domains': {'blacktoon': {'baseUrl': 'https://blacktoon423.com'}}}
            with patch('signal_nas.service.SITES', [BY_KEY['blacktoon']]), patch('signal_nas.service.BrowserVerifier', FakeBrowser):
                domains, status = asyncio.run(service._run_async(copy.deepcopy(old), {'groups': []}))
        self.assertEqual(domains['domains'], old['domains'])
        row = status['groups'][0]
        self.assertEqual(row['candidateBaseUrl'], BASE)
        self.assertEqual(row['checks']['source']['candidates'][0]['state'], 'failed')
        visible = public_overview({'running': False, 'groups': [row]})['groups'][0]
        self.assertEqual(visible['candidateBaseUrl'], BASE)
        self.assertIn('category navigation not found', visible['checks']['source']['detail'])

    def test_targeted_recheck_preserves_other_domains_and_status_rows(self):
        class FakeBrowser:
            async def discover(self, _): return [BASE], 'guide read'
            async def verify(self, *args, **kw): return BASE, 'real work links verified'
            async def __aenter__(self): return self
            async def __aexit__(self, *_): pass
        other = {'key': 'naver', 'name': '네이버', 'state': 'healthy', 'checkedAt': 'unchanged', 'extra': [1, 2]}
        domains = {'domains': {'blacktoon': {'baseUrl': 'https://blacktoon423.com'},
                               'naver': {'baseUrl': 'https://comic.naver.com', 'extra': 42}}}
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {'DATA_DIR': tmp}):
            service = CheckerService()
            with patch('signal_nas.service.SITES', [BY_KEY['blacktoon'], BY_KEY['naver']]), patch('signal_nas.service.BrowserVerifier', FakeBrowser):
                result, status = asyncio.run(service._run_async(copy.deepcopy(domains), {'groups': [other]}, {'blacktoon'}))
        self.assertEqual(result['domains']['naver'], domains['domains']['naver'])
        self.assertEqual(status['groups'][1], other)
        self.assertEqual(result['domains']['blacktoon']['baseUrl'], BASE)

if __name__ == '__main__':
    unittest.main()

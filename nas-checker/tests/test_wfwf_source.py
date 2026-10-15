import unittest
from signal_nas.browser import telegram_candidates
from signal_nas.model import BY_KEY

class WfwfSourceTests(unittest.TestCase):
    def test_configured_source_is_user_selected_channel(self):
        source = BY_KEY['wfwf']['source']
        self.assertEqual(source['url'], 'https://t.me/s/wftoon999')
        self.assertTrue(source['strictPreferredLabel'])

    def test_latest_primary_address_not_second_service(self):
        posts = [
            '늑대닷컴 주소\nhttps://wfwf515.com',
            '늑대닷컴 주소\nhttps://wfwf516.com\n늑대닷컴2 주소\nhttps://wtoon233.com',
            '늑대닷컴2 주소\nhttps://wtoon234.com',
        ]
        self.assertEqual(telegram_candidates(BY_KEY['wfwf'], posts), ['https://wfwf516.com'])

    def test_missing_primary_label_does_not_select_unrelated_link(self):
        self.assertEqual(telegram_candidates(BY_KEY['wfwf'], ['https://wfwf999.com',
                         '늑대닷컴2 주소\nhttps://wtoon233.com']), [])

if __name__ == '__main__':
    unittest.main()

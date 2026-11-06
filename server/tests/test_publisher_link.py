import unittest

from routes.studio import publisher_url


class PublisherLinkTests(unittest.TestCase):
    def test_opens_brand_page(self):
        self.assertEqual(publisher_url("108123456789"), "https://business.facebook.com/latest/composer?asset_id=108123456789")

    def test_generic_without_page_and_never_injects(self):
        self.assertEqual(publisher_url(None), "https://business.facebook.com/latest/composer")
        self.assertEqual(publisher_url("12&x=<script>"), "https://business.facebook.com/latest/composer?asset_id=12")


if __name__ == "__main__":
    unittest.main()

import unittest

from zotvault.zotero_reader import RawItem
from zotvault.pdf_resolver import find_arxiv_id


def item_with(fields):
    it = RawItem(item_id=1, item_key="K", type_name="journalArticle", date_added="2026-01-01 00:00:00")
    it.fields = fields
    return it


class TestRawItem(unittest.TestCase):
    def test_extra_citekey(self):
        it = item_with({"extra": "Citation Key: xiaoCoupled2012\ntex.ids: foo"})
        self.assertEqual(it.extra_citekey(), "xiaoCoupled2012")
        self.assertIsNone(item_with({"extra": "nothing here"}).extra_citekey())

    def test_year_parsing(self):
        self.assertEqual(item_with({"date": "2024-03-01 2024"}).year, "2024")
        self.assertEqual(item_with({"date": "May 7, 2019"}).year, "2019")
        self.assertEqual(item_with({"date": ""}).year, "")

    def test_authors(self):
        it = item_with({})
        it.creators = [("A", "Kim"), ("", "Lee"), ("C", "")]
        self.assertEqual(it.authors, "A Kim, Lee, C")


class TestArxivDetect(unittest.TestCase):
    def test_from_url(self):
        it = item_with({"url": "https://arxiv.org/abs/2405.01234v2"})
        self.assertEqual(find_arxiv_id(it), "2405.01234v2")

    def test_from_doi(self):
        it = item_with({"DOI": "10.48550/arXiv.2210.07021"})
        self.assertEqual(find_arxiv_id(it), "2210.07021")

    def test_from_extra(self):
        it = item_with({"extra": "arXiv: 1802.06266"})
        self.assertEqual(find_arxiv_id(it), "1802.06266")

    def test_none(self):
        self.assertIsNone(find_arxiv_id(item_with({"url": "https://nature.com/x"})))


if __name__ == "__main__":
    unittest.main()

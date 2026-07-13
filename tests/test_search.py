import socket
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

from zotvault.search import SearchResult, _get_polite, lookup_identifier, mark_in_library, parse_s2
from zotvault.state import State

S2_DATA = {
    "data": [
        {
            "title": "Valley polarization in MoS2",
            "abstract": "We polarize valleys.",
            "year": 2012,
            "venue": "Nature Nano",
            "externalIds": {"DOI": "10.1038/nnano.2012.95", "ArXiv": "1205.1822"},
            "citationCount": 3000,
            "openAccessPdf": {"url": "https://arxiv.org/pdf/1205.1822"},
            "authors": [{"name": "K. F. Mak"}, {"name": "K. He"}],
        },
        {"title": "", "externalIds": None, "authors": []},
    ]
}


class TestParseS2(unittest.TestCase):
    def test_parse(self):
        rs = parse_s2(S2_DATA)
        r = rs[0]
        self.assertEqual(r.source, "s2")
        self.assertEqual(r.doi, "10.1038/nnano.2012.95")
        self.assertEqual(r.arxiv_id, "1205.1822")
        self.assertEqual(r.citations, 3000)
        self.assertEqual(r.year, "2012")
        self.assertEqual(r.best_identifier, "10.1038/nnano.2012.95")

    def test_best_identifier_arxiv_only(self):
        r = SearchResult(source="arxiv", title="t", arxiv_id="2405.01234")
        self.assertEqual(r.best_identifier, "arXiv:2405.01234")


class TestInLibrary(unittest.TestCase):
    def test_mark(self):
        with tempfile.TemporaryDirectory() as td:
            state = State(Path(td) / "s.db")
            state.upsert_item(1, item_key="A", citekey="Mak2012",
                              doi="10.1038/nnano.2012.95")
            state.upsert_item(2, item_key="B", citekey="Kim2024", arxiv_id="2401.00001")
            rs = [
                SearchResult(source="s2", title="x", doi="10.1038/NNANO.2012.95"),
                SearchResult(source="arxiv", title="y", arxiv_id="2401.00001v3"),
                SearchResult(source="arxiv", title="z", arxiv_id="9999.99999"),
            ]
            mark_in_library(rs, state)
            state.close()
            self.assertEqual(rs[0].in_library, "Mak2012")
            self.assertEqual(rs[1].in_library, "Kim2024")
            self.assertIsNone(rs[2].in_library)


class TestLookupIdentifier(unittest.TestCase):
    def test_keywords_return_none(self):
        self.assertIsNone(lookup_identifier("valley polarization dynamics"))

    def test_doi_lookup(self):
        fake = {
            "itemType": "journalArticle",
            "title": "Exact Paper",
            "creators": [{"creatorType": "author", "firstName": "A", "lastName": "Kim"}],
            "date": "2024-06-01",
            "DOI": "10.3389/fchem.2024.1425306",
            "publicationTitle": "Frontiers in Chemistry",
            "abstractNote": "abs",
        }
        with mock.patch("zotvault.zotero_writer.resolve_doi", return_value=fake):
            rs = lookup_identifier("10.3389/fchem.2024.1425306")
        self.assertEqual(len(rs), 1)
        self.assertEqual(rs[0].title, "Exact Paper")
        self.assertEqual(rs[0].doi, "10.3389/fchem.2024.1425306")
        self.assertEqual(rs[0].source, "doi-lookup")
        self.assertEqual(rs[0].year, "2024")

    def test_doi_lookup_failure_returns_empty(self):
        with mock.patch("zotvault.zotero_writer.resolve_doi", side_effect=OSError("down")):
            self.assertEqual(lookup_identifier("10.1000/nonexistent.404"), [])

    def test_arxiv_lookup(self):
        fake = {
            "itemType": "preprint",
            "title": "ArXiv Paper",
            "creators": [{"creatorType": "author", "firstName": "B", "lastName": "Lee"}],
            "date": "2024-05-02",
            "DOI": "",
            "repository": "arXiv",
            "abstractNote": "abs",
            "_pdf_url": "https://arxiv.org/pdf/2405.01234",
        }
        with mock.patch("zotvault.zotero_writer.resolve_arxiv", return_value=fake):
            rs = lookup_identifier("arXiv:2405.01234v2")
        self.assertEqual(len(rs), 1)
        self.assertEqual(rs[0].arxiv_id, "2405.01234")
        self.assertEqual(rs[0].source, "arxiv-lookup")
        self.assertTrue(rs[0].pdf_url.endswith("2405.01234"))


class TestGetPolite(unittest.TestCase):
    """arXiv/S2/Crossref occasionally stall instead of erroring cleanly —
    _get_polite retries once after a delay and only then gives up with a
    message a human can act on. See AGENTS.md network etiquette."""

    def test_retries_once_on_timeout_then_succeeds(self):
        with mock.patch("zotvault.search._get", side_effect=[socket.timeout("timed out"), b"ok"]) as m, \
             mock.patch("zotvault.search.time.sleep") as sleep_m:
            result = _get_polite("http://x", "TestSource", retry_delay=3.0)
        self.assertEqual(result, b"ok")
        self.assertEqual(m.call_count, 2)
        sleep_m.assert_called_once_with(3.0)

    def test_raises_friendly_message_after_two_timeouts(self):
        with mock.patch("zotvault.search._get",
                         side_effect=[socket.timeout("timed out"), socket.timeout("timed out")]), \
             mock.patch("zotvault.search.time.sleep"):
            with self.assertRaises(RuntimeError) as cm:
                _get_polite("http://x", "TestSource", retry_delay=0.01)
        self.assertIn("TestSource", str(cm.exception))
        self.assertIn("twice in a row", str(cm.exception))

    def test_http_error_is_not_retried(self):
        err = urllib.error.HTTPError("http://x", 429, "rate limited", {}, None)
        with mock.patch("zotvault.search._get", side_effect=err) as m, \
             mock.patch("zotvault.search.time.sleep") as sleep_m:
            with self.assertRaises(urllib.error.HTTPError):
                _get_polite("http://x", "TestSource")
        self.assertEqual(m.call_count, 1)
        sleep_m.assert_not_called()


if __name__ == "__main__":
    unittest.main()

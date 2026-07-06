import tempfile
import unittest
from pathlib import Path

from paperflow.search import SearchResult, mark_in_library, parse_s2
from paperflow.state import State

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


if __name__ == "__main__":
    unittest.main()

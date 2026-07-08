import tempfile
import unittest
from pathlib import Path

from zotvault.alerts import store_entries
from zotvault.state import State


def entry(aid, published="2026-07-04", title="T"):
    return {"arxiv_id": aid, "title": title, "summary": "s", "published": published,
            "authors": ["A B"], "doi": "", "pdf_url": "", "categories": []}


class TestAlerts(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.state = State(Path(self.td.name) / "s.db")

    def tearDown(self):
        self.state.close()
        self.td.cleanup()

    def test_store_dedupe_cutoff_library(self):
        self.state.upsert_item(1, item_key="K", citekey="InLib2026", arxiv_id="2406.00001")
        seen = self.state.alert_seen_ids()
        lib = self.state.arxiv_map()
        entries = [
            entry("2407.00001v1"),                      # new -> stored
            entry("2407.00001v2"),                      # same base id -> skipped
            entry("2406.00001"),                        # already in library -> skipped
            entry("2401.00009", published="2026-01-01"),  # too old -> skipped
        ]
        added = store_entries(entries, "valleytronics", "cond-mat.mes-hall",
                              cutoff="2026-07-01", seen=seen, in_library=lib,
                              state=self.state)
        self.assertEqual(added, 1)
        rows = self.state.alerts_list("pending")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["arxiv_id"], "2407.00001")
        self.assertIn("valleytronics", rows[0]["matched"])
        # second fetch: no duplicates
        added2 = store_entries([entry("2407.00001v3")], "kw", "",
                               cutoff="2026-07-01", seen=self.state.alert_seen_ids(),
                               in_library=lib, state=self.state)
        self.assertEqual(added2, 0)

    def test_status_flow(self):
        store_entries([entry("2407.11111")], "kw", "", "2026-07-01",
                      set(), {}, self.state)
        row = self.state.alerts_list("pending")[0]
        self.state.alert_set_status(row["id"], "dismissed")
        self.assertEqual(self.state.alerts_list("pending"), [])
        self.assertEqual(len(self.state.alerts_list("dismissed")), 1)


if __name__ == "__main__":
    unittest.main()

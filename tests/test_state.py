import tempfile
import unittest
from pathlib import Path

from zotvault.state import State


class TestState(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.state = State(Path(self.td.name) / "state.db")

    def tearDown(self):
        self.state.close()
        self.td.cleanup()

    def test_kv(self):
        self.assertIsNone(self.state.kv_get("x"))
        self.state.kv_set("x", "1")
        self.state.kv_set("x", "2")
        self.assertEqual(self.state.kv_get("x"), "2")

    def test_item_upsert_and_retry(self):
        self.state.upsert_item(10, item_key="ABC", citekey=None, note_status="pending")
        self.assertEqual(self.state.known_item_ids(), {10})
        self.assertIn(10, self.state.retry_item_ids())
        # dry-run leftovers must be retried on the next real run
        self.state.upsert_item(11, item_key="DRY", citekey="Dry2026", note_status="dry-run", pdf_status="zotero")
        self.assertIn(11, self.state.retry_item_ids())
        self.state.upsert_item(
            10, citekey="Kim2026", note_status="created", pdf_status="zotero", retries=0
        )
        row = self.state.get_item(10)
        self.assertEqual(row["citekey"], "Kim2026")
        self.assertNotIn(10, self.state.retry_item_ids())

    def test_analysis_flag_and_counts(self):
        self.state.upsert_item(1, item_key="A", citekey="X1", note_status="created", pdf_status="zotero")
        self.state.upsert_item(2, item_key="B", citekey="X2", note_status="existing", pdf_status="missing")
        self.assertEqual(len(self.state.items_awaiting_analysis()), 2)
        self.state.upsert_item(1, analysis_done=1)
        self.assertEqual(len(self.state.items_awaiting_analysis()), 1)
        c = self.state.counts()
        self.assertEqual(c["items"], 2)
        self.assertEqual(c["analyzed"], 1)

    def test_downloads_budget(self):
        self.assertEqual(self.state.downloads_today(), 0)
        self.state.record_download()
        self.state.record_download()
        self.assertEqual(self.state.downloads_today(), 2)

    def test_deleted(self):
        self.state.upsert_item(5, item_key="D", citekey="Del2026")
        self.state.mark_deleted(5)
        self.assertEqual(self.state.all_items(), [])
        self.assertEqual(len(self.state.all_items(include_deleted=True)), 1)


if __name__ == "__main__":
    unittest.main()

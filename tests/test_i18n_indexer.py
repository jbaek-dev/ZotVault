import tempfile
import unittest
from pathlib import Path

from zotvault import i18n
from zotvault.indexer import current_progress, update_progress


class TestI18n(unittest.TestCase):
    def tearDown(self):
        i18n.set_language("en")

    def test_default_english(self):
        i18n.set_language("en")
        self.assertEqual(i18n.t("log.sync_title"), "ZotVault automatic sync")
        self.assertIn("2 note", i18n.t("log.notes_created", n=2, items="A, B"))

    def test_korean_opt_in(self):
        i18n.set_language("ko")
        self.assertIn("자동 동기화", i18n.t("log.sync_title"))

    def test_unknown_lang_falls_back_en(self):
        i18n.set_language("de")
        self.assertEqual(i18n.t("log.sync_title"), "ZotVault automatic sync")

    def test_missing_key_returns_key(self):
        self.assertEqual(i18n.t("no.such.key"), "no.such.key")


class TestProgressMarkers(unittest.TestCase):
    def test_sentinel_preferred(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "index.md"
            p.write_text("# Index\n\nprogress: <!-- zotvault:progress 3/10 -->\n", encoding="utf-8")
            self.assertEqual(current_progress(p), (3, 10))
            self.assertTrue(update_progress(p, 4, 12))
            self.assertIn("<!-- zotvault:progress 4/12 -->", p.read_text(encoding="utf-8"))

    def test_legacy_korean_still_works(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "index.md"
            p.write_text("- ✅ **5 / 5** zotero 논문 완료\n", encoding="utf-8")
            self.assertEqual(current_progress(p), (5, 5))
            self.assertTrue(update_progress(p, 5, 6))
            self.assertIn("**5 / 6** zotero 논문", p.read_text(encoding="utf-8"))

    def test_sentinel_wins_when_both_present(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "index.md"
            p.write_text("<!-- zotvault:progress 1/2 -->\n- ✅ **9 / 9** zotero 논문\n", encoding="utf-8")
            update_progress(p, 7, 8)
            text = p.read_text(encoding="utf-8")
            self.assertIn("zotvault:progress 7/8", text)
            self.assertIn("**9 / 9** zotero 논문", text)  # legacy untouched


if __name__ == "__main__":
    unittest.main()

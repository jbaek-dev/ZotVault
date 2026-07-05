import tempfile
import unittest
from pathlib import Path

from paperflow import analysis_queue


def make_vault(td: Path):
    papers = td / "30_Resources" / "Papers" / "zotero"
    a = papers / "Kim2026"
    a.mkdir(parents=True)
    (a / "Kim2026.md").write_text("note", encoding="utf-8")
    (a / "Kim2026_claude_analysis.md").write_text("analysis", encoding="utf-8")
    b = papers / "Lee2025"
    b.mkdir(parents=True)
    (b / "Lee2025.md").write_text("note", encoding="utf-8")
    c = papers / "Park2024"
    c.mkdir(parents=True)  # folder without note (edge case)
    return papers


class TestQueue(unittest.TestCase):
    def test_scan_pending_progress(self):
        with tempfile.TemporaryDirectory() as td:
            papers = make_vault(Path(td))
            entries = analysis_queue.scan(papers)
            self.assertEqual(len(entries), 3)
            by_key = {e.citekey: e for e in entries}
            self.assertTrue(by_key["Kim2026"].analyzed)
            self.assertFalse(by_key["Lee2025"].analyzed)
            self.assertTrue(by_key["Lee2025"].has_note)
            self.assertFalse(by_key["Park2024"].has_note)
            pend = analysis_queue.pending(papers)
            self.assertEqual({e.citekey for e in pend}, {"Lee2025", "Park2024"})
            self.assertEqual(analysis_queue.progress(papers), (1, 3))

    def test_analysis_file_for(self):
        with tempfile.TemporaryDirectory() as td:
            papers = make_vault(Path(td))
            hit = analysis_queue.analysis_file_for(papers, "Kim2026")
            self.assertIsNotNone(hit)
            self.assertTrue(hit.name.endswith("_claude_analysis.md"))
            self.assertIsNone(analysis_queue.analysis_file_for(papers, "Lee2025"))
            self.assertIsNone(analysis_queue.analysis_file_for(papers, "Nope2000"))

    def test_missing_dir(self):
        self.assertEqual(analysis_queue.scan(Path("/nonexistent/papers")), [])


if __name__ == "__main__":
    unittest.main()

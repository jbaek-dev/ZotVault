import tempfile
import unittest
from pathlib import Path

from zotvault.indexer import append_log, current_progress, update_progress

INDEX_SAMPLE = """# Index

## 📑 문헌 AI리뷰 진척 (Zotero Papers)
- ✅ **154 / 154** zotero 논문 Claude 중립분석 완료 (`{citekey}_claude_analysis.md`) — **전수 완료**.
- 다음 단계 후보: synthesis.
"""


class TestIndexer(unittest.TestCase):
    def test_update_progress(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "index.md"
            p.write_text(INDEX_SAMPLE, encoding="utf-8")
            self.assertEqual(current_progress(p), (154, 154))
            changed = update_progress(p, 154, 156)
            self.assertTrue(changed)
            self.assertIn("**154 / 156** zotero 논문", p.read_text(encoding="utf-8"))
            # unchanged numbers -> no write
            self.assertFalse(update_progress(p, 154, 156))

    def test_update_progress_pattern_missing(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "index.md"
            p.write_text("# no counters here\n", encoding="utf-8")
            self.assertFalse(update_progress(p, 1, 2))
            self.assertEqual(p.read_text(encoding="utf-8"), "# no counters here\n")

    def test_append_log(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "log.md"
            p.write_text("# log\n", encoding="utf-8")
            ok = append_log(p, "ZotVault 자동 동기화", "노트 2건 생성", "papers/")
            self.assertTrue(ok)
            text = p.read_text(encoding="utf-8")
            self.assertIn("ZotVault 자동 동기화", text)
            self.assertIn("- summary: 노트 2건 생성", text)

    def test_append_log_missing_file(self):
        self.assertFalse(append_log(Path("/nonexistent/log.md"), "t", "s", "f"))

    def test_dry_run(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "index.md"
            p.write_text(INDEX_SAMPLE, encoding="utf-8")
            self.assertTrue(update_progress(p, 1, 2, dry_run=True))
            self.assertIn("**154 / 154**", p.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()

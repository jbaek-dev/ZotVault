import tempfile
import unittest
from pathlib import Path

from zotvault.note_renderer import render_note, write_note
from zotvault.zotero_reader import RawItem


def make_item(**kw):
    item = RawItem(item_id=1, item_key="KEY123", type_name="journalArticle", date_added="2026-07-04 10:00:00")
    item.fields = {
        "title": 'Valley "memory" in Janus TMDCs',
        "DOI": "10.1000/test.123",
        "url": "https://example.com/paper",
        "publicationTitle": "Phys. Rev. Test",
        "abstractNote": "We test things.",
        "date": "2026-05-01 2026",
    }
    item.creators = [("Jong", "Min"), ("Ada", "Lovelace")]
    item.citekey = "MinLovelace2026"
    for k, v in kw.items():
        setattr(item, k, v)
    return item


class TestRender(unittest.TestCase):
    def test_yaml_and_sections(self):
        text = render_note(make_item())
        self.assertIn('citekey: "MinLovelace2026"', text)
        self.assertIn('title: "Valley \\"memory\\" in Janus TMDCs"', text)
        self.assertIn('authors: "Jong Min, Ada Lovelace"', text)
        self.assertIn('year: "2026"', text)
        self.assertIn('itemKey: "KEY123"', text)
        self.assertIn("## Abstract\nWe test things.", text)
        self.assertIn("https://doi.org/10.1000/test.123", text)
        self.assertIn("zotero://select/items/KEY123", text)
        self.assertIn("zotvault_note_version: 1", text)

    def test_default_backlink_is_claude(self):
        # engine "none" defaults to the historical _claude_analysis convention
        self.assertIn("[[MinLovelace2026_claude_analysis]]", render_note(make_item()))

    def test_engine_suffix_backlink_and_template_override(self):
        from zotvault.config import Config

        cfg = Config()
        cfg.analysis_engine = "ollama"
        self.assertIn("[[MinLovelace2026_ollama_analysis]]", render_note(make_item(), cfg))
        with tempfile.TemporaryDirectory() as td:
            tf = Path(td) / "tmpl.md"
            tf.write_text("CUSTOM {citekey} / {analysis_link}", encoding="utf-8")
            cfg.template_file = str(tf)
            out = render_note(make_item(), cfg)
            self.assertTrue(out.startswith("CUSTOM MinLovelace2026 / MinLovelace2026_ollama_analysis"))

    def test_no_citekey_raises(self):
        item = make_item()
        item.citekey = None
        with self.assertRaises(ValueError):
            render_note(item)


class TestWrite(unittest.TestCase):
    def test_create_then_skip(self):
        with tempfile.TemporaryDirectory() as td:
            papers = Path(td)
            item = make_item()
            status, path = write_note(papers, item)
            self.assertEqual(status, "created")
            self.assertTrue(path.exists())
            original = path.read_text(encoding="utf-8")
            # second run must NOT touch the file (My Synthesis protection)
            path.write_text(original + "\n- my manual edit\n", encoding="utf-8")
            status2, _ = write_note(papers, item)
            self.assertEqual(status2, "existing")
            self.assertIn("my manual edit", path.read_text(encoding="utf-8"))

    def test_dry_run(self):
        with tempfile.TemporaryDirectory() as td:
            status, path = write_note(Path(td), make_item(), dry_run=True)
            self.assertEqual(status, "dry-run")
            self.assertFalse(path.exists())


if __name__ == "__main__":
    unittest.main()

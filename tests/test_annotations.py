import tempfile
import unittest
from pathlib import Path

from zotvault.annotations import END, START, digest, prepare_images, render_block, upsert_block
from zotvault.config import Config
from zotvault.zotero_reader import Annotation


def ann(key="A1", type=1, text="Valley polarization is robust.", comment="",
        color="#ffd400", page="3", sort="00001", mod="2026-07-08"):
    return Annotation(key=key, attachment_key="ATT1", type=type, text=text,
                      comment=comment, color=color, page_label=page,
                      sort_index=sort, date_modified=mod)


class TestRenderAndDigest(unittest.TestCase):
    def setUp(self):
        self.cfg = Config()

    def test_render_groups_by_color_in_palette_order(self):
        block = render_block(
            [ann(key="Y", color="#ffd400"), ann(key="R", color="#ff6666"),
             ann(key="G", color="#5fb236")], self.cfg)
        self.assertTrue(block.startswith(START))
        self.assertTrue(block.endswith(END))
        y, r, g = block.index("🟡 Yellow"), block.index("🔴 Red"), block.index("🟢 Green")
        self.assertTrue(y < r < g)  # palette order, not insertion order
        self.assertIn("zotero://open-pdf/library/items/ATT1?page=3&annotation=Y", block)

    def test_comment_and_truncation(self):
        self.cfg.annotations_max_quote_chars = 10
        block = render_block([ann(text="A" * 50, comment="note to self")], self.cfg)
        self.assertIn("AAAAAAAAAA…", block)
        self.assertIn("💬 note to se…", block)
        self.cfg.annotations_include_comments = False
        block2 = render_block([ann(comment="hidden")], self.cfg)
        self.assertNotIn("hidden", block2)

    def test_image_without_cache_falls_back_to_link(self):
        block = render_block([ann(), ann(key="I1", type=3, text="")], self.cfg)
        self.assertIn("🖼 Figures & areas (1)", block)
        self.assertIn("annotation=I1", block)   # deep link fallback
        self.assertNotIn("![[", block)

    def test_image_embedded_when_cached(self):
        with tempfile.TemporaryDirectory() as td:
            cache = Path(td) / "cache"
            cache.mkdir()
            (cache / "I1.png").write_bytes(b"\x89PNG fake")
            assets = Path(td) / "vault" / "K2026"
            anns = [ann(key="I1", type=3, text="")]
            images = prepare_images(anns, cache, assets, "K2026")
            self.assertEqual(images, {"I1": "K2026_I1.png"})
            self.assertTrue((assets / "K2026_I1.png").exists())
            block = render_block(anns, self.cfg, images)
            self.assertIn("![[K2026_I1.png]]", block)

    def test_color_label_override(self):
        self.cfg.annotations_labels = {"red": "Core Claims"}
        block = render_block([ann(key="R", color="#ff6666")], self.cfg)
        self.assertIn("🔴 Core Claims (1)", block)
        self.assertNotIn("🔴 Red", block)

    def test_empty_set_renders_placeholder(self):
        block = render_block([], self.cfg)
        self.assertIn("_no annotations_", block)

    def test_digest_stable_and_sensitive(self):
        a, b = ann(key="A"), ann(key="B", sort="00002")
        self.assertEqual(digest([a, b]), digest([b, a]))  # order-insensitive
        self.assertNotEqual(digest([a]), digest([a, b]))
        self.assertNotEqual(digest([a]), digest([ann(key="A", text="changed")]))


class TestUpsert(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.note = Path(self.td.name) / "K.md"

    def tearDown(self):
        self.td.cleanup()

    def _block(self, marker="v1"):
        return "{}\ncontent {}\n{}".format(START, marker, END)

    def test_marked_note_replaced_between_markers_only(self):
        self.note.write_text(
            "# My note\nmy precious text\n\n{}\nold\n{}\n\n## After\nkeep me\n".format(START, END),
            encoding="utf-8")
        status = upsert_block(self.note, self._block(), adopt_existing=False)
        self.assertEqual(status, "updated")
        text = self.note.read_text(encoding="utf-8")
        self.assertIn("my precious text", text)
        self.assertIn("keep me", text)
        self.assertIn("content v1", text)
        self.assertNotIn("\nold\n", text)

    def test_unchanged_returns_unchanged(self):
        self.note.write_text("x\n{}\n".format(self._block()), encoding="utf-8")
        self.assertEqual(upsert_block(self.note, self._block(), False), "unchanged")

    def test_unmarked_skipped_by_default(self):
        original = "# legacy note\nno markers here\n"
        self.note.write_text(original, encoding="utf-8")
        status = upsert_block(self.note, self._block(), adopt_existing=False)
        self.assertEqual(status, "skipped-unmarked")
        self.assertEqual(self.note.read_text(encoding="utf-8"), original)  # byte-identical

    def test_unmarked_appended_when_adopted(self):
        self.note.write_text("# legacy note\nbody\n", encoding="utf-8")
        status = upsert_block(self.note, self._block(), adopt_existing=True)
        self.assertEqual(status, "appended")
        text = self.note.read_text(encoding="utf-8")
        self.assertTrue(text.startswith("# legacy note\nbody\n"))
        self.assertIn(START, text)
        # second sync now updates in place, no duplicate blocks
        status2 = upsert_block(self.note, self._block("v2"), adopt_existing=True)
        self.assertEqual(status2, "updated")
        self.assertEqual(self.note.read_text(encoding="utf-8").count(START), 1)

    def test_dry_run_no_write(self):
        original = "x\n{}\n".format(self._block("old"))
        self.note.write_text(original, encoding="utf-8")
        status = upsert_block(self.note, self._block("new"), False, dry_run=True)
        self.assertEqual(status, "updated")
        self.assertEqual(self.note.read_text(encoding="utf-8"), original)

    def test_missing_note(self):
        self.assertEqual(upsert_block(Path(self.td.name) / "nope.md", "b", True), "missing-note")


if __name__ == "__main__":
    unittest.main()

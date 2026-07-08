"""End-to-end pipeline smoke test with a synthetic Zotero sqlite + tmp vault.

Covers the core product path that was previously untested: snapshot → fetch →
citekey → note create → analysis-completion detection → index/log update, plus
the non-BBT 'blocked' behavior and the DB-unchanged fast-skip.
"""
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from zotvault.config import Config
from zotvault.pipeline import run_once
from zotvault.state import State


def build_zotero_db(path: Path, items):
    """Minimal Zotero schema sufficient for ZoteroReader.fetch_items."""
    c = sqlite3.connect(str(path))
    c.executescript(
        """
        CREATE TABLE itemTypes (itemTypeID INTEGER PRIMARY KEY, typeName TEXT);
        CREATE TABLE items (itemID INTEGER PRIMARY KEY, key TEXT, dateAdded TEXT, dateModified TEXT, itemTypeID INTEGER);
        CREATE TABLE deletedItems (itemID INTEGER PRIMARY KEY);
        CREATE TABLE fields (fieldID INTEGER PRIMARY KEY, fieldName TEXT);
        CREATE TABLE itemData (itemID INT, fieldID INT, valueID INT);
        CREATE TABLE itemDataValues (valueID INTEGER PRIMARY KEY, value TEXT);
        CREATE TABLE creators (creatorID INTEGER PRIMARY KEY, firstName TEXT, lastName TEXT);
        CREATE TABLE itemCreators (itemID INT, creatorID INT, orderIndex INT);
        CREATE TABLE itemAttachments (itemID INT, parentItemID INT, contentType TEXT, path TEXT);
        CREATE TABLE itemAnnotations (itemID INTEGER PRIMARY KEY, parentItemID INT, type INT,
            authorName TEXT, text TEXT, comment TEXT, color TEXT, pageLabel TEXT,
            sortIndex TEXT, position TEXT, isExternal INT);
        """
    )
    c.execute("INSERT INTO itemTypes VALUES (1,'journalArticle')")
    c.execute("INSERT INTO fields VALUES (1,'title')")
    c.execute("INSERT INTO fields VALUES (2,'DOI')")
    vid = 1
    for it in items:
        c.execute("INSERT INTO items VALUES (?,?,?,?,1)", (it["id"], it["key"], "2026-07-01 00:00:00", "2026-07-01 00:00:00"))
        for fid, val in ((1, it["title"]), (2, it.get("doi", ""))):
            c.execute("INSERT INTO itemDataValues VALUES (?,?)", (vid, val))
            c.execute("INSERT INTO itemData VALUES (?,?,?)", (it["id"], fid, vid))
            vid += 1
    c.commit()
    c.close()


def add_annotation(db: Path, paper_id: int, ann_id: int, text: str, color: str = "#ffd400"):
    """Attach (once) + one highlight annotation to a paper in the synthetic DB."""
    c = sqlite3.connect(str(db))
    att_id = 9000 + paper_id
    row = c.execute("SELECT 1 FROM items WHERE itemID=?", (att_id,)).fetchone()
    if not row:
        c.execute("INSERT INTO items VALUES (?,?,?,?,1)", (att_id, "ATT{}".format(paper_id),
                                                          "2026-07-01 00:00:00", "2026-07-01 00:00:00"))
        c.execute("INSERT INTO itemAttachments VALUES (?,?,?,?)",
                  (att_id, paper_id, "application/pdf", None))
    c.execute("INSERT INTO items VALUES (?,?,?,?,1)", (ann_id, "ANN{}".format(ann_id),
                                                      "2026-07-02 00:00:00", "2026-07-02 00:00:00"))
    c.execute("INSERT INTO itemAnnotations VALUES (?,?,?,?,?,?,?,?,?,?,?)",
              (ann_id, att_id, 1, "", text, "", color, "2", "0000{}".format(ann_id), "{}", 0))
    c.commit()
    c.close()


class TestPipelineE2E(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        root = Path(self.td.name)
        self.zdir = root / "Zotero"
        self.zdir.mkdir()
        build_zotero_db(self.zdir / "zotero.sqlite",
                        [{"id": 10, "key": "AAA10", "title": "Paper One", "doi": "10.1/one"},
                         {"id": 11, "key": "BBB11", "title": "Paper Two"}])
        self.vault = root / "vault"
        (self.vault / "30_Resources/Papers/zotero").mkdir(parents=True)
        (self.vault / "index.md").write_text(
            "progress <!-- zotvault:progress 0/0 -->\n", encoding="utf-8")
        (self.vault / "log.md").write_text("# log\n", encoding="utf-8")
        cfg = Config()
        cfg.zotero_data_dir = self.zdir
        cfg.vault_dir = self.vault
        cfg.state_db = root / "state.db"
        cfg.pdf_dir = root / "pdfs"
        cfg.resolve_pdfs = False
        self.cfg = cfg

    def tearDown(self):
        self.td.cleanup()

    def _run(self, citekeys):
        with mock.patch("zotvault.zotero_reader.ZoteroReader.bbt_citekeys", return_value=citekeys):
            state = State(self.cfg.state_db)
            try:
                return run_once(self.cfg, state)
            finally:
                state.close()

    def test_full_cycle_creates_notes(self):
        s = self._run({"AAA10": "One2026", "BBB11": "Two2026"})
        self.assertEqual(s.notes_created, 2)
        self.assertTrue((self.vault / "30_Resources/Papers/zotero/One2026/One2026.md").exists())
        # index progress updated to 0/2 (0 analyzed of 2)
        self.assertIn("zotvault:progress 0/2", (self.vault / "index.md").read_text(encoding="utf-8"))
        # log.md got an English entry
        self.assertIn("ZotVault", (self.vault / "log.md").read_text(encoding="utf-8"))

    def test_non_bbt_blocks(self):
        s = self._run({})  # no citekeys -> blocked after retries
        self.assertEqual(s.notes_created, 0)
        self.assertEqual(s.citekey_pending, 2)
        # run a few cycles → status becomes 'blocked'
        for _ in range(3):
            self._run({})
        state = State(self.cfg.state_db)
        statuses = {r["note_status"] for r in state.all_items()}
        state.close()
        self.assertIn("blocked", statuses)

    def test_annotation_sync_marked_notes(self):
        # first cycle creates notes (default template contains the marker pair)
        keys = {"AAA10": "One2026", "BBB11": "Two2026"}
        self._run(keys)
        note = self.vault / "30_Resources/Papers/zotero/One2026/One2026.md"
        self.assertIn("zotvault:annotations:start", note.read_text(encoding="utf-8"))
        # user writes above the block; then a highlight appears in Zotero
        original = note.read_text(encoding="utf-8")
        note.write_text(original.replace("## Notes", "## Notes\nMY PRECIOUS EDIT"), encoding="utf-8")
        add_annotation(self.zdir / "zotero.sqlite", 10, 500, "Key highlighted claim.")
        s = self._run(keys)
        self.assertEqual(s.annotations_updated, 1)
        text = note.read_text(encoding="utf-8")
        self.assertIn("MY PRECIOUS EDIT", text)              # user text untouched
        self.assertIn("Key highlighted claim.", text)        # highlight synced
        self.assertIn("🟡 Yellow (1)", text)
        # unchanged set -> no rewrite next cycle
        s2 = self._run(keys)
        self.assertEqual(s2.annotations_updated, 0)
        # deleting the annotation clears the block
        c = sqlite3.connect(str(self.zdir / "zotero.sqlite"))
        c.execute("DELETE FROM itemAnnotations WHERE itemID=500")
        c.commit()
        c.close()
        s3 = self._run(keys)
        self.assertEqual(s3.annotations_updated, 1)
        self.assertIn("_no annotations_", note.read_text(encoding="utf-8"))
        self.assertIn("MY PRECIOUS EDIT", note.read_text(encoding="utf-8"))

    def test_annotation_unmarked_note_untouched_by_default(self):
        keys = {"AAA10": "One2026", "BBB11": "Two2026"}
        self._run(keys)
        note = self.vault / "30_Resources/Papers/zotero/One2026/One2026.md"
        legacy = "# hand-made legacy note\nno markers\n"
        note.write_text(legacy, encoding="utf-8")
        add_annotation(self.zdir / "zotero.sqlite", 10, 501, "hl")
        s = self._run(keys)
        self.assertEqual(s.annotations_updated, 0)
        self.assertEqual(note.read_text(encoding="utf-8"), legacy)  # byte-identical
        # opt-in adopt appends the block once
        self.cfg.annotations_adopt_existing = True
        add_annotation(self.zdir / "zotero.sqlite", 10, 502, "hl2")
        s2 = self._run(keys)
        self.assertEqual(s2.annotations_updated, 1)
        text = note.read_text(encoding="utf-8")
        self.assertTrue(text.startswith(legacy))
        self.assertIn("hl2", text)

    def test_analysis_detection_and_skip(self):
        self._run({"AAA10": "One2026", "BBB11": "Two2026"})
        # drop an analysis file, then a cycle should detect it and bump progress
        folder = self.vault / "30_Resources/Papers/zotero/One2026"
        (folder / "One2026_claude_analysis.md").write_text("x", encoding="utf-8")
        s = self._run({"AAA10": "One2026", "BBB11": "Two2026"})
        self.assertEqual(s.analyses_detected, 1)
        self.assertIn("zotvault:progress 1/2", (self.vault / "index.md").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()

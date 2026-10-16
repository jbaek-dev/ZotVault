"""AUTO notes (Citation_Graph.md, Related_Suggestions.md) must not keep links to
papers that were deleted, archived out of the vault, or re-keyed.

Citation edges and embeddings are stored by citekey and outlive their papers,
so the notes filter at render time and the relink step moves edges to the new
key. Network-free: no Semantic Scholar or Ollama calls.
"""
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from zotvault import enrich, related
from zotvault.config import Config
from zotvault.state import State


class _Base(unittest.TestCase):
    PAPERS = "30_Resources/Papers/zotero"

    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        root = Path(self.td.name)
        self.vault = root / "vault"
        (self.vault / self.PAPERS).mkdir(parents=True)
        cfg = Config()
        cfg.vault_dir = self.vault
        cfg.state_db = root / "state.db"
        self.cfg = cfg
        self.state = State(cfg.state_db)

    def tearDown(self):
        self.state.close()
        self.td.cleanup()

    def _item(self, item_id, citekey, deleted=0):
        self.state.upsert_item(item_id, item_key="K{}".format(item_id), citekey=citekey,
                               deleted=deleted)

    def _folder(self, citekey):
        d = self.vault / self.PAPERS / citekey
        d.mkdir()
        (d / (citekey + ".md")).write_text("note\n", encoding="utf-8")


class TestCiteRekey(_Base):
    def test_moves_both_directions_and_merges(self):
        self.state.cite_replace("Old", ["X", "New"])   # Old cites its own re-keyed twin
        self.state.cite_replace("Y", ["Old"])
        self.state.cite_replace("New", ["X"])          # already there under the new key
        moved = self.state.cite_rekey("Old", "New")
        edges = sorted((e["citing"], e["cited"]) for e in self.state.cite_edges())
        self.assertEqual(edges, [("New", "X"), ("Y", "New")])
        self.assertEqual(moved, 2)  # Old->New (becomes a self-edge, dropped) and Y->Old

    def test_noop_for_same_or_empty_key(self):
        self.state.cite_replace("A", ["B"])
        self.assertEqual(self.state.cite_rekey("A", "A"), 0)
        self.assertEqual(self.state.cite_rekey("", "A"), 0)
        self.assertEqual(len(self.state.cite_edges()), 1)


class TestCitationGraphNote(_Base):
    def setUp(self):
        super().setUp()
        self._item(1, "Live2020")
        self._item(2, "Other2021")
        self._item(3, "Gone2019", deleted=1)
        self.state.cite_replace("Live2020", ["Other2021", "Gone2019", "Unknown2018"])
        self.state.cite_replace("Gone2019", ["Live2020"])

    def test_render_drops_edges_to_dead_keys(self):
        text = enrich.render_citation_graph(self.state)
        self.assertIn("[[Live2020]] → [[Other2021]]", text)
        self.assertNotIn("Gone2019", text)
        self.assertNotIn("Unknown2018", text)
        self.assertIn("In-library edges: **1**", text)

    def test_existing_note_is_rerendered_without_new_fetches(self):
        path = enrich.note_path(self.cfg)
        path.write_text("old note with [[Gone2019]]\n", encoding="utf-8")
        with mock.patch("zotvault.enrich.s2_fetch") as fetch:
            self.assertEqual(enrich.run(self.cfg, self.state), 0)
        fetch.assert_not_called()
        text = path.read_text(encoding="utf-8")
        self.assertNotIn("Gone2019", text)
        self.assertIn("[[Live2020]] → [[Other2021]]", text)

    def test_existing_note_is_rerendered_when_every_fetch_fails(self):
        self.state.upsert_item(4, item_key="K4", citekey="Pending2022", doi="10.1/p")
        path = enrich.note_path(self.cfg)
        path.write_text("old note with [[Gone2019]]\n", encoding="utf-8")
        with mock.patch("zotvault.enrich.s2_fetch", side_effect=OSError("offline")), \
             mock.patch("zotvault.enrich.time.sleep"):
            self.assertEqual(enrich.run(self.cfg, self.state), 0)
        self.assertNotIn("Gone2019", path.read_text(encoding="utf-8"))

    def test_missing_note_is_not_created_without_new_fetches(self):
        with mock.patch("zotvault.enrich.s2_fetch") as fetch:
            enrich.run(self.cfg, self.state)
        fetch.assert_not_called()
        self.assertFalse(enrich.note_path(self.cfg).exists())

    def test_dry_run_writes_nothing(self):
        self.cfg.dry_run = True
        path = enrich.note_path(self.cfg)
        path.write_text("old\n", encoding="utf-8")
        enrich.run(self.cfg, self.state)
        self.assertEqual(path.read_text(encoding="utf-8"), "old\n")


class TestRelatedNote(_Base):
    def setUp(self):
        super().setUp()
        self.cfg.related_threshold = 0.5
        vec = related.vec_to_blob([1.0, 0.0])
        for ck in ("Here2020", "AlsoHere2021", "Archived2019"):
            self.state.emb_set(ck, self.cfg.ollama_embed_model, 2, vec, 0.0)
        self._folder("Here2020")
        self._folder("AlsoHere2021")   # Archived2019 has a vector but no folder

    def test_only_papers_still_in_the_vault(self):
        vecs = related.load_vectors(self.state, self.cfg.ollama_embed_model, self.cfg.papers_dir)
        self.assertEqual(sorted(vecs), ["AlsoHere2021", "Here2020"])
        text = related.render_note(self.cfg, self.state)
        self.assertIn("[[Here2020]] → [[AlsoHere2021]]", text)
        self.assertNotIn("Archived2019", text)

    def test_unfiltered_without_papers_dir(self):
        vecs = related.load_vectors(self.state, self.cfg.ollama_embed_model)
        self.assertEqual(len(vecs), 3)


if __name__ == "__main__":
    unittest.main()

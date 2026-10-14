import unittest

from zotvault.zotero_writer import (
    classify_identifier,
    entry_to_preprint_item,
    parse_arxiv_atom,
    parse_crossref,
)

ARXIV_ATOM = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom" xmlns:arxiv="http://arxiv.org/schemas/atom">
  <entry>
    <id>http://arxiv.org/abs/2405.01234v2</id>
    <title>Valley  dynamics in
      Janus TMDCs</title>
    <summary>We study valley dynamics.</summary>
    <published>2024-05-02T17:59:59Z</published>
    <author><name>Ada Lovelace</name></author>
    <author><name>Jong Min Baek</name></author>
    <arxiv:doi>10.1103/PhysRevB.1.1</arxiv:doi>
    <link title="pdf" href="http://arxiv.org/pdf/2405.01234v2" rel="related" type="application/pdf"/>
    <category term="cond-mat.mes-hall"/>
  </entry>
</feed>"""

CROSSREF_MSG = {
    "type": "journal-article",
    "title": ["Coupled spin and valley physics"],
    "author": [
        {"given": "Di", "family": "Xiao"},
        {"name": "ACME Collaboration"},
    ],
    "issued": {"date-parts": [[2012, 5, 7]]},
    "container-title": ["Physical Review Letters"],
    "DOI": "10.1103/physrevlett.108.196802",
    "URL": "https://doi.org/10.1103/physrevlett.108.196802",
    "abstract": "<jats:p>We couple <i>spin</i> and valley.</jats:p>",
    "volume": "108",
    "issue": "19",
    "page": "196802",
}


class TestClassify(unittest.TestCase):
    def test_doi_forms(self):
        for raw in ("10.1103/PhysRevB.1.1",
                    "https://doi.org/10.1103/PhysRevB.1.1",
                    "doi:10.1103/PhysRevB.1.1",
                    "see 10.1103/PhysRevB.1.1 for details"):
            kind, norm = classify_identifier(raw)
            self.assertEqual((kind, norm), ("doi", "10.1103/PhysRevB.1.1"), raw)

    def test_arxiv_forms(self):
        for raw, want in (("2405.01234", "2405.01234"),
                          ("2405.01234v2", "2405.01234v2"),
                          ("arXiv:2405.01234", "2405.01234"),
                          ("https://arxiv.org/abs/2405.01234v2", "2405.01234v2"),
                          ("cond-mat/0701234", "cond-mat/0701234")):
            kind, norm = classify_identifier(raw)
            self.assertEqual((kind, norm), ("arxiv", want), raw)

    def test_url_and_unknown(self):
        self.assertEqual(classify_identifier("https://nature.com/articles/x")[0], "url")
        self.assertEqual(classify_identifier("hello world")[0], "unknown")


class TestParsers(unittest.TestCase):
    def test_crossref(self):
        item = parse_crossref(CROSSREF_MSG)
        self.assertEqual(item["itemType"], "journalArticle")
        self.assertEqual(item["title"], "Coupled spin and valley physics")
        self.assertEqual(item["creators"][0]["lastName"], "Xiao")
        self.assertEqual(item["creators"][1]["lastName"], "ACME Collaboration")
        self.assertEqual(item["date"], "2012-05-07")
        self.assertEqual(item["publicationTitle"], "Physical Review Letters")
        self.assertNotIn("<", item["abstractNote"])
        self.assertEqual(item["pages"], "196802")

    def test_arxiv_atom_and_item(self):
        entries = parse_arxiv_atom(ARXIV_ATOM)
        self.assertEqual(len(entries), 1)
        e = entries[0]
        self.assertEqual(e["arxiv_id"], "2405.01234v2")
        self.assertEqual(e["title"], "Valley dynamics in Janus TMDCs")
        self.assertEqual(e["doi"], "10.1103/PhysRevB.1.1")
        self.assertTrue(e["pdf_url"].endswith("2405.01234v2"))
        item = entry_to_preprint_item(e)
        self.assertEqual(item["itemType"], "preprint")
        self.assertEqual(item["repository"], "arXiv")
        self.assertEqual(item["creators"][0]["lastName"], "Lovelace")
        self.assertEqual(item["creators"][1]["firstName"], "Jong Min")


if __name__ == "__main__":
    unittest.main()


MML_TITLE = (
    'Tunable Berry curvature and valley and spin Hall effect in bilayer '
    '<mml:math xmlns:mml="http://www.w3.org/1998/Math/MathML"><mml:msub>'
    '<mml:mi>MoS</mml:mi><mml:mn>2</mml:mn></mml:msub></mml:math>'
)


class TestStripMarkup(unittest.TestCase):
    """Crossref embeds MathML/JATS in titles (v0.9.1 user-reported bug)."""

    def test_mathml_title_joins_text_nodes(self):
        from zotvault.zotero_writer import strip_markup
        self.assertEqual(
            strip_markup(MML_TITLE),
            "Tunable Berry curvature and valley and spin Hall effect in bilayer MoS2")

    def test_latex_annotation_not_duplicated(self):
        from zotvault.zotero_writer import strip_markup
        t = ('gap of <mml:math><mml:semantics><mml:msub><mml:mi>WSe</mml:mi>'
             '<mml:mn>2</mml:mn></mml:msub><mml:annotation encoding='
             '"application/x-tex">WSe_2</mml:annotation></mml:semantics></mml:math>')
        self.assertEqual(strip_markup(t), "gap of WSe2")

    def test_entities_and_whitespace(self):
        from zotvault.zotero_writer import strip_markup
        self.assertEqual(strip_markup("Spin &amp;  valley\n physics"),
                         "Spin & valley physics")

    def test_abstract_keeps_word_boundaries(self):
        from zotvault.zotero_writer import strip_markup
        t = "<jats:title>Abstract</jats:title><jats:p>We study X.</jats:p>"
        self.assertEqual(strip_markup(t, sep=" "), "Abstract We study X.")

    def test_parse_crossref_sanitizes_title(self):
        msg = dict(CROSSREF_MSG, title=[MML_TITLE],
                   **{"container-title": ["Physical Review <i>B</i>"]})
        item = parse_crossref(msg)
        self.assertNotIn("<", item["title"])
        self.assertTrue(item["title"].endswith("bilayer MoS2"))
        self.assertEqual(item["publicationTitle"], "Physical Review B")


class TestPdfAttachAtAdd(unittest.TestCase):
    """v0.10.0: add_identifiers attaches the PDF in the SAME connector session.

    saveItems alone can't attach (ATTACHMENT_MODE_IGNORE); the browser
    connector sends the file in a second call, /connector/saveAttachment,
    naming the saved item as `parentItemID`. Success is HTTP 201 only.
    """

    PDF = b"%PDF-1.5 " + b"x" * 20000

    def _cfg_state(self, email="me@example.org"):
        from unittest import mock

        from zotvault.config import Config

        cfg = Config()
        cfg.unpaywall_email = email
        cfg.request_delay_sec = 0
        state = mock.Mock()
        state.doi_map.return_value = {}
        state.arxiv_map.return_value = {}
        state.ignored_identifiers.return_value = {}
        state.downloads_today.return_value = 0
        return cfg, state

    def _run(self, ids=("10.1103/PhysRevB.90.1",), pdf=PDF, upload=(True, "attached"),
             resolver=(False, "x"), zotero_maps=({}, {}), **kw):
        from unittest import mock

        from zotvault.zotero_writer import add_identifiers

        cfg, state = self._cfg_state()
        calls = {"saved": None, "sid": None, "upload": None, "resolver": 0}

        def fake_save(items, url, timeout=30, session_id=None):
            calls["saved"], calls["sid"] = items, session_id
            return True, "saved"

        def fake_upload(url, sid, data, src, **k):
            calls["upload"] = (sid, data, src)
            return upload

        def fake_resolver(url, sid, **k):
            calls["resolver"] += 1
            return resolver

        with mock.patch("zotvault.zotero_writer.resolve_doi",
                        return_value={"itemType": "journalArticle", "title": "T", "DOI": ids[0]}), \
             mock.patch("zotvault.zotero_writer._zotero_identifier_maps", return_value=zotero_maps), \
             mock.patch("zotvault.pdf_resolver.unpaywall_pdf_urls",
                        return_value=["https://oa.example/p.pdf"]) as unpay, \
             mock.patch("zotvault.pdf_resolver.fetch_pdf_bytes", return_value=pdf) as fetch, \
             mock.patch("zotvault.zotero_writer.save_items_to_zotero", fake_save), \
             mock.patch("zotvault.zotero_writer.attach_pdf_to_saved_item", fake_upload), \
             mock.patch("zotvault.zotero_writer.attach_via_zotero_resolver", fake_resolver):
            results = add_identifiers(list(ids), cfg, state, **kw)
        return results, calls, fetch, unpay

    def test_payload_has_parent_id_and_no_attachments_key(self):
        results, calls, _, _ = self._run()
        self.assertNotIn("attachments", calls["saved"][0])
        self.assertEqual(calls["saved"][0]["id"], "zv1")
        self.assertTrue(calls["sid"])

    def test_pdf_uploaded_in_same_session(self):
        results, calls, _, _ = self._run()
        self.assertEqual(results[0]["status"], "added")
        self.assertEqual(results[0]["pdf"], "attached")
        self.assertIn("PDF attached", results[0]["message"])
        sid, data, src = calls["upload"]
        self.assertEqual(sid, calls["sid"])
        self.assertEqual(data, self.PDF)
        self.assertEqual(src, "https://oa.example/p.pdf")

    def test_upload_failure_is_reported_not_hidden(self):
        results, _, _, _ = self._run(upload=(False, "Zotero answered HTTP 200"))
        self.assertEqual(results[0]["status"], "added")
        self.assertEqual(results[0]["pdf"], "failed")
        self.assertNotIn("PDF attached", results[0]["message"])
        self.assertIn("Find Available PDF", results[0]["message"])

    def test_no_pdf_found_falls_back_to_zotero_resolver(self):
        results, calls, _, _ = self._run(pdf=None, resolver=(True, "Full Text PDF"))
        self.assertEqual(calls["resolver"], 1)
        self.assertIsNone(calls["upload"])
        self.assertEqual(results[0]["pdf"], "attached")

    def test_nothing_found_anywhere_says_so(self):
        results, calls, _, _ = self._run(pdf=None, resolver=(False, "500"))
        self.assertEqual(results[0]["status"], "added")
        self.assertEqual(results[0]["pdf"], "none")
        self.assertIn("no PDF attached", results[0]["message"])

    def test_no_pdf_flag_skips_everything(self):
        results, calls, fetch, unpay = self._run(attach_pdf=False)
        fetch.assert_not_called()
        unpay.assert_not_called()
        self.assertIsNone(calls["upload"])
        self.assertEqual(calls["resolver"], 0)
        self.assertEqual(results[0]["message"], "saved to Zotero")

    def test_dry_run_downloads_and_saves_nothing(self):
        results, calls, fetch, _ = self._run(dry_run=True)
        fetch.assert_not_called()
        self.assertIsNone(calls["saved"])
        self.assertEqual(results[0]["status"], "resolved")

    def test_duplicate_found_in_zotero_db_even_if_state_db_is_blind(self):
        results, calls, fetch, _ = self._run(
            zotero_maps=({"10.1103/physrevb.90.1": "ABCD1234"}, {}))
        self.assertEqual(results[0]["status"], "duplicate")
        self.assertIsNone(calls["saved"])
        fetch.assert_not_called()

    def test_zotero_identifier_maps_cover_webpage_items(self):
        """A paper saved from an arXiv abstract page is a `webpage` item; the
        duplicate check must still see it (it is not a pipeline item type)."""
        import sqlite3
        from unittest import mock

        from zotvault.zotero_reader import RawItem
        from zotvault.zotero_writer import _zotero_identifier_maps

        seen = {}

        class FakeReader:
            def __init__(self, *a, **k): pass
            def snapshot(self):
                conn = sqlite3.connect(":memory:")
                conn.execute("CREATE TABLE itemTypes (typeName TEXT)")
                conn.executemany("INSERT INTO itemTypes VALUES (?)",
                                 [("journalArticle",), ("webpage",), ("attachment",),
                                  ("note",), ("annotation",)])
                return conn
            def fetch_items(self, conn, types):
                seen["types"] = types
                it = RawItem(item_id=1, item_key="WEBPG", type_name="webpage", date_added="")
                it.fields = {"url": "https://arxiv.org/abs/2506.07043v3"}
                return [it]
            def cleanup(self): pass

        from zotvault.config import Config
        with mock.patch("zotvault.zotero_reader.ZoteroReader", FakeReader):
            doi_map, arxiv_map = _zotero_identifier_maps(Config())
        self.assertIn("webpage", seen["types"])
        self.assertNotIn("attachment", seen["types"])
        self.assertEqual(arxiv_map.get("2506.07043"), "WEBPG")

    def test_arxiv_doi_matches_arxiv_item_in_zotero(self):
        results, calls, _, _ = self._run(
            ids=("10.48550/arXiv.2506.07043",),
            zotero_maps=({}, {"2506.07043": "ABCD1234"}))
        self.assertEqual(results[0]["status"], "duplicate")

    def test_arxiv_internal_pdf_url_never_leaks_into_payload(self):
        from unittest import mock

        from zotvault.zotero_writer import add_identifiers

        cfg, state = self._cfg_state()
        saved = {}

        def fake_save(items, url, timeout=30, session_id=None):
            saved["items"] = items
            return True, "saved"

        with mock.patch("zotvault.zotero_writer.resolve_arxiv",
                        return_value={"itemType": "preprint", "title": "T",
                                     "_pdf_url": "https://arxiv.org/pdf/2405.01234v1"}), \
             mock.patch("zotvault.zotero_writer._zotero_identifier_maps", return_value=({}, {})), \
             mock.patch("zotvault.zotero_writer.save_items_to_zotero", fake_save):
            results = add_identifiers(["2405.01234"], cfg, state, attach_pdf=False)
        self.assertEqual(results[0]["status"], "added")
        self.assertNotIn("_pdf_url", saved["items"][0])
        self.assertNotIn("attachments", saved["items"][0])


class TestAttachWire(unittest.TestCase):
    """The HTTP-level contract of the two connector calls."""

    def test_only_201_is_success(self):
        from unittest import mock

        from zotvault.zotero_writer import attach_pdf_to_saved_item

        for status, expect in ((201, True), (200, False), (400, False), (500, False)):
            with mock.patch("zotvault.zotero_writer._post", return_value=(status, b"msg")):
                ok, _ = attach_pdf_to_saved_item("http://127.0.0.1:23119", "sid", b"%PDF", "u")
            self.assertEqual(ok, expect, status)

    def test_metadata_header_is_ascii_and_names_parent_and_session(self):
        from unittest import mock

        from zotvault.zotero_writer import attach_pdf_to_saved_item

        seen = {}

        def fake_post(url, data, headers, timeout):
            seen.update(url=url, headers=headers, data=data)
            return 201, b""

        with mock.patch("zotvault.zotero_writer._post", fake_post):
            attach_pdf_to_saved_item("http://127.0.0.1:23119/", "SID", b"%PDF-x",
                                     "https://x.org/WSe\u2082.pdf")
        meta = seen["headers"]["X-Metadata"]
        meta.encode("ascii")  # HTTP header values must stay ASCII
        import json as _json
        d = _json.loads(meta)
        self.assertEqual((d["sessionID"], d["parentItemID"]), ("SID", "zv1"))
        self.assertTrue(seen["url"].endswith("/connector/saveAttachment"))
        self.assertEqual(seen["headers"]["Content-Type"], "application/pdf")
        self.assertEqual(seen["data"], b"%PDF-x")


class TestSupplementPreferMain(unittest.TestCase):
    """A Supplementary-Information PDF attached to the same item must not be
    picked as the paper's main text, but must never cost an item its only PDF.
    Runs the real `_pdf_for` SQL against an in-memory Zotero-shaped schema."""

    def _reader(self, attachments):
        """attachments: [(title, filename)] in insertion (= itemID) order."""
        import sqlite3
        import tempfile
        from pathlib import Path

        from zotvault.zotero_reader import ZoteroReader

        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(__import__("shutil").rmtree, str(tmp), True)
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.executescript("""
            CREATE TABLE items (itemID INTEGER PRIMARY KEY, key TEXT);
            CREATE TABLE itemAttachments (itemID INT, parentItemID INT, contentType TEXT, path TEXT);
            CREATE TABLE fields (fieldID INTEGER PRIMARY KEY, fieldName TEXT);
            CREATE TABLE itemDataValues (valueID INTEGER PRIMARY KEY, value TEXT);
            CREATE TABLE itemData (itemID INT, fieldID INT, valueID INT);
            CREATE TABLE deletedItems (itemID INT);
            INSERT INTO fields VALUES (1, 'title');
            INSERT INTO items VALUES (1, 'PARENT');
        """)
        for n, (title, fname) in enumerate(attachments, start=10):
            key = "ATT%d" % n
            conn.execute("INSERT INTO items VALUES (?, ?)", (n, key))
            conn.execute("INSERT INTO itemAttachments VALUES (?, 1, 'application/pdf', ?)",
                         (n, "storage:" + fname))
            conn.execute("INSERT INTO itemDataValues VALUES (?, ?)", (n, title))
            conn.execute("INSERT INTO itemData VALUES (?, 1, ?)", (n, n))
            d = tmp / "storage" / key
            d.mkdir(parents=True)
            (d / fname).write_bytes(b"%PDF-1.5")
        return ZoteroReader(tmp), conn

    def test_main_wins_even_when_supplement_was_attached_first(self):
        r, conn = self._reader([("Supplementary Information", "si.pdf"),
                                ("Full Text PDF", "main.pdf")])
        self.assertTrue(r._pdf_for(conn, 1).endswith("main.pdf"))

    def test_only_supplement_is_kept_as_before(self):
        r, conn = self._reader([("Supporting Information", "si.pdf")])
        self.assertTrue(r._pdf_for(conn, 1).endswith("si.pdf"))

    def test_silicon_is_not_a_supplement(self):
        """"Si" (the element) in a drag-dropped title must not demote the paper."""
        r, conn = self._reader([("Wang - 2020 - Band structure of Si SiO2 interfaces", "a.pdf"),
                                ("Full Text PDF", "b.pdf")])
        self.assertTrue(r._pdf_for(conn, 1).endswith("a.pdf"))

    def test_abbreviations_match_as_written(self):
        from zotvault.zotero_reader import _SUPPLEMENT_TITLE_RE as rx

        for t in ("SI", "ESI", "ESM 1", "Wang - Supplement", "supporting info", "Appendix A"):
            self.assertTrue(rx.search(t), t)
        for t in ("Full Text PDF", "Band structure of Si SiO2", "Accepted Version"):
            self.assertFalse(rx.search(t), t)


class TestDelatex(unittest.TestCase):
    """arXiv titles carry raw TeX (v0.9.6 user-reported)."""

    def test_subscripts_and_superscripts(self):
        from zotvault.zotero_writer import delatex
        self.assertEqual(delatex("monolayer WSe$_2$"), "monolayer WSe₂")
        self.assertEqual(delatex("MoS$_2$/WSe$_{2}$"), "MoS₂/WSe₂")
        self.assertEqual(delatex("10$^{-9}$ s"), "10⁻⁹ s")

    def test_greek_and_symbols(self):
        from zotvault.zotero_writer import delatex
        self.assertEqual(delatex("$\\Gamma$ point"), "Γ point")
        self.assertEqual(delatex("$\\alpha$-RuCl$_3$"), "α-RuCl₃")
        self.assertEqual(delatex("5$\\times$10$^3$"), "5×10³")

    def test_plain_text_untouched(self):
        from zotvault.zotero_writer import delatex
        self.assertEqual(delatex("snake_case and x^y outside math"),
                         "snake_case and x^y outside math")
        self.assertEqual(delatex("plain title"), "plain title")

    def test_unmappable_subscript_degrades_gracefully(self):
        from zotvault.zotero_writer import delatex
        self.assertEqual(delatex("T$_c$ enhancement"), "Tc enhancement")

    def test_arxiv_atom_titles_are_delatexed(self):
        feed = ARXIV_ATOM.replace("Valley  dynamics in\n      Janus TMDCs",
                                  "Valley dynamics in WSe$_2$")
        entries = parse_arxiv_atom(feed)
        self.assertEqual(entries[0]["title"], "Valley dynamics in WSe₂")

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


class TestOaAttachment(unittest.TestCase):
    """DOI adds attach an OA PDF url so Zotero downloads it itself (v0.9.1)."""

    def _run_add(self, oa_urls, email="me@example.org"):
        from unittest import mock

        from zotvault.config import Config
        from zotvault.zotero_writer import add_identifiers

        cfg = Config()
        cfg.unpaywall_email = email
        state = mock.Mock()
        state.doi_map.return_value = {}
        state.arxiv_map.return_value = {}
        saved = {}

        def fake_save(items, url, timeout=30):
            saved["items"] = items
            return True, "saved"

        with mock.patch("zotvault.zotero_writer.resolve_doi",
                        return_value={"itemType": "journalArticle", "title": "T"}), \
             mock.patch("zotvault.pdf_resolver.unpaywall_pdf_urls",
                        return_value=oa_urls), \
             mock.patch("zotvault.zotero_writer.save_items_to_zotero", fake_save):
            results = add_identifiers(["10.1103/PhysRevB.90.1"], cfg, state)
        return results, saved

    def test_oa_found_lands_in_payload(self):
        results, saved = self._run_add(["https://oa.example/x.pdf"])
        self.assertEqual(results[0]["status"], "added")
        att = saved["items"][0]["attachments"]
        self.assertEqual(att[0]["url"], "https://oa.example/x.pdf")
        self.assertEqual(att[0]["mimeType"], "application/pdf")
        self.assertIn("PDF", results[0]["message"])

    def test_no_oa_is_graceful(self):
        results, saved = self._run_add([])
        self.assertEqual(results[0]["status"], "added")
        self.assertNotIn("attachments", saved["items"][0])

    def test_no_email_skips_lookup(self):
        results, saved = self._run_add(["https://oa.example/x.pdf"], email="")
        self.assertNotIn("attachments", saved["items"][0])

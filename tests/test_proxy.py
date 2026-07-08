import tempfile
import unittest
from pathlib import Path

from paperflow.proxy import (
    extract_pdf_url,
    is_proxied,
    load_cookiejar,
    pdf_url_candidates,
    proxied_url,
)

TEMPLATE = "https://login.ezproxy.example.edu/login?url={url}"

HTML = """<html><head>
<meta name="citation_title" content="Some Paper">
<meta name="citation_pdf_url" content="/doi/pdf/10.1/x.pdf">
</head></html>"""

HTML_REVERSED = """<html><head>
<meta content="https://pub.example.com/x.pdf" name='citation_pdf_url'>
</head></html>"""

COOKIES = """# Netscape HTTP Cookie File
.ezproxy.example.edu\tTRUE\t/\tTRUE\t2082787200\tezproxy\tabc123
.ezproxy.example.edu\tTRUE\t/\tTRUE\t0\tezproxyn\tsession456
"""


class TestProxy(unittest.TestCase):
    def test_proxied_url(self):
        t = "https://login.ezproxy.example.edu/login?url={url}"
        out = proxied_url("https://doi.org/10.1103/PhysRevB.1.1?x=1", t)
        self.assertTrue(out.startswith("https://login.ezproxy.example.edu/login?url=https://doi.org/"))
        with self.assertRaises(ValueError):
            proxied_url("https://x", "https://no-placeholder")

    def test_extract_pdf_url(self):
        self.assertEqual(
            extract_pdf_url(HTML, "https://pub.example.com/doi/10.1/x"),
            "https://pub.example.com/doi/pdf/10.1/x.pdf",
        )
        self.assertEqual(
            extract_pdf_url(HTML_REVERSED, "https://pub.example.com/"),
            "https://pub.example.com/x.pdf",
        )
        self.assertIsNone(extract_pdf_url("<html></html>", "https://x/"))

    def test_is_proxied(self):
        self.assertTrue(is_proxied("https://login.ezproxy.example.edu/x", TEMPLATE))
        self.assertTrue(is_proxied("https://journals-aps-org.login.ezproxy.example.edu/y", TEMPLATE))
        self.assertFalse(is_proxied("https://onlinelibrary.wiley.com/doi/pdf/10.1/x", TEMPLATE))

    def test_pdf_url_candidates(self):
        cands = pdf_url_candidates("https://onlinelibrary.wiley.com/doi/pdf/10.1/x", TEMPLATE)
        self.assertEqual(len(cands), 2)
        self.assertIn("pdfdirect", cands[0])           # raw-file variant first
        for c in cands:
            self.assertTrue(c.startswith("https://login.ezproxy.example.edu/login?url="))
        # already-proxied URLs are left alone
        already = "https://pub-com.login.ezproxy.example.edu/a.pdf"
        self.assertEqual(pdf_url_candidates(already, TEMPLATE), [already])

    def test_cookiejar(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "cookies.txt"
            p.write_text(COOKIES, encoding="utf-8")
            jar = load_cookiejar(str(p))
            by_name = {c.name: c for c in jar}
            self.assertIn("ezproxy", by_name)
            # session cookie (expiry=0) must be sendable: pinned to the future
            self.assertIn("ezproxyn", by_name)
            self.assertTrue(by_name["ezproxyn"].expires and by_name["ezproxyn"].expires > 0)
            self.assertFalse(by_name["ezproxyn"].is_expired())


if __name__ == "__main__":
    unittest.main()

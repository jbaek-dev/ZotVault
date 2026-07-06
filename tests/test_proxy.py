import tempfile
import unittest
from pathlib import Path

from paperflow.proxy import extract_pdf_url, load_cookiejar, proxied_url

HTML = """<html><head>
<meta name="citation_title" content="Some Paper">
<meta name="citation_pdf_url" content="/doi/pdf/10.1/x.pdf">
</head></html>"""

HTML_REVERSED = """<html><head>
<meta content="https://pub.example.com/x.pdf" name='citation_pdf_url'>
</head></html>"""

COOKIES = """# Netscape HTTP Cookie File
.ezproxy.example.edu\tTRUE\t/\tTRUE\t2082787200\tezproxy\tabc123
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

    def test_cookiejar(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "cookies.txt"
            p.write_text(COOKIES, encoding="utf-8")
            jar = load_cookiejar(str(p))
            names = {c.name for c in jar}
            self.assertIn("ezproxy", names)


if __name__ == "__main__":
    unittest.main()

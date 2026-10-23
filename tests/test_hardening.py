"""Security hardening and the embedding-refresh stall (0.10.0).

- claude-cli analysis runs with NO tools (`--tools ""`), no MCP servers, in an
  empty working directory. `--allowedTools ""` did not disable anything.
- Ollama context-length refusals shorten the text; a note that never fits is
  skipped instead of stopping the whole refresh.
- The PDF fetcher only opens http(s) and refuses oversized bodies.
- Citekeys "." / ".." / ".hidden" are refused as folder names.

Network-free: subprocess and urlopen are mocked.
"""
import io
import os
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

from zotvault import analyze, pdf_resolver, related
from zotvault.config import Config
from zotvault.state import State


class TestClaudeCliHasNoTools(unittest.TestCase):
    def test_flags_and_empty_cwd(self):
        seen = {}

        def fake_run(cmd, **kw):
            seen["cmd"] = cmd
            seen["cwd"] = kw.get("cwd")
            seen["cwd_listing"] = os.listdir(kw["cwd"])
            return mock.Mock(returncode=0, stdout=b"analysis", stderr=b"")

        cfg = Config()
        cfg.analysis_model = "haiku"
        with mock.patch("zotvault.analyze.shutil.which", return_value="/usr/bin/claude"), \
             mock.patch("zotvault.analyze.subprocess.run", side_effect=fake_run):
            self.assertEqual(analyze._gen_claude_cli("prompt", cfg), "analysis")
        cmd = seen["cmd"]
        self.assertEqual(cmd[cmd.index("--tools") + 1], "")
        self.assertIn("--strict-mcp-config", cmd)
        self.assertNotIn("--allowedTools", cmd)
        self.assertNotEqual(Path(seen["cwd"]).resolve(), Path.cwd().resolve())
        self.assertEqual(seen["cwd_listing"], [])
        self.assertFalse(os.path.exists(seen["cwd"]))  # removed afterwards

    def test_old_cli_without_the_flags_fails_closed(self):
        cfg = Config()
        bad = mock.Mock(returncode=1, stdout=b"", stderr=b"error: unknown option '--tools'")
        with mock.patch("zotvault.analyze.shutil.which", return_value="/usr/bin/claude"), \
             mock.patch("zotvault.analyze.subprocess.run", return_value=bad):
            with self.assertRaises(RuntimeError):
                analyze._gen_claude_cli("prompt", cfg)


def _http_error(code, body):
    return urllib.error.HTTPError("http://x", code, "err", {}, io.BytesIO(body))


_TOO_LONG = b'{"error":"the input length exceeds the context length"}'


class TestEmbedShortening(unittest.TestCase):
    def test_halves_until_it_fits(self):
        lengths = []

        def once(text, cfg, timeout):
            lengths.append(len(text))
            if len(text) > 2000:
                raise _http_error(500, _TOO_LONG)
            return [0.1, 0.2]

        with mock.patch("zotvault.related._ollama_embed_once", side_effect=once):
            self.assertEqual(related.ollama_embed("x" * 10000, Config()), [0.1, 0.2])
        self.assertEqual(lengths, [6000, 3000, 1500])

    def test_gives_up_with_input_too_long(self):
        with mock.patch("zotvault.related._ollama_embed_once",
                        side_effect=lambda *a: (_ for _ in ()).throw(_http_error(500, _TOO_LONG))):
            with self.assertRaises(related.InputTooLong):
                related.ollama_embed("x" * 10000, Config())

    def test_other_http_errors_propagate(self):
        with mock.patch("zotvault.related._ollama_embed_once",
                        side_effect=_http_error(404, b'{"error":"model not found"}')):
            with self.assertRaises(urllib.error.HTTPError):
                related.ollama_embed("x", Config())


class TestRefreshSkipsTooLongNote(unittest.TestCase):
    PAPERS = "30_Resources/Papers/zotero"

    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        root = Path(self.td.name)
        cfg = Config()
        cfg.vault_dir = root / "vault"
        cfg.state_db = root / "state.db"
        self.cfg = cfg
        for ck in ("Aaa2020", "Bbb2021", "Ccc2022"):
            d = cfg.vault_dir / self.PAPERS / ck
            d.mkdir(parents=True)
            (d / (ck + ".md")).write_text(ck, encoding="utf-8")
        self.state = State(cfg.state_db)

    def tearDown(self):
        self.state.close()
        self.td.cleanup()

    def _embed(self, text, cfg):
        if text == "Aaa2020":
            raise related.InputTooLong("too long")
        return [1.0, 0.0]

    def test_later_notes_still_embedded_and_skip_traced_once(self):
        with mock.patch("zotvault.related.ollama_embed", side_effect=self._embed):
            self.assertEqual(related.refresh(self.cfg, self.state), 2)
            self.assertEqual(related.refresh(self.cfg, self.state), 0)
        self.assertIsNone(self.state.emb_get("Aaa2020"))
        self.assertIsNotNone(self.state.emb_get("Ccc2022"))
        skips = list(self.state.conn.execute("SELECT * FROM trace WHERE action='embed_skipped'"))
        self.assertEqual(len(skips), 1)

    def test_ollama_down_still_stops_the_run(self):
        with mock.patch("zotvault.related.ollama_embed",
                        side_effect=urllib.error.URLError("connection refused")):
            self.assertEqual(related.refresh(self.cfg, self.state), 0)
        self.assertEqual(
            len(list(self.state.conn.execute("SELECT * FROM trace WHERE action='embed_unavailable'"))), 1)


class TestPdfFetchGuards(unittest.TestCase):
    def test_non_http_schemes_are_not_opened(self):
        with mock.patch("zotvault.pdf_resolver.urllib.request.urlopen") as uo:
            for url in ("file:///etc/passwd", "ftp://x/y.pdf", "FILE:///tmp/a.pdf"):
                self.assertIsNone(pdf_resolver.fetch_pdf_bytes(url, Config()))
        uo.assert_not_called()

    def _resp(self, body):
        r = mock.MagicMock()
        r.__enter__.return_value.read.side_effect = lambda n=-1: body if n < 0 else body[:n]
        return r

    def test_oversized_body_refused(self):
        big = b"%PDF-1.7" + b"0" * (pdf_resolver._MAX_PDF_BYTES + 10)
        with mock.patch("zotvault.pdf_resolver.urllib.request.urlopen", return_value=self._resp(big)):
            self.assertIsNone(pdf_resolver.fetch_pdf_bytes("https://x/a.pdf", Config()))

    def test_normal_pdf_accepted(self):
        ok = b"%PDF-1.7" + b"0" * 20000
        with mock.patch("zotvault.pdf_resolver.urllib.request.urlopen", return_value=self._resp(ok)):
            self.assertEqual(pdf_resolver.fetch_pdf_bytes("https://x/a.pdf", Config()), ok)


class TestUnsafeCitekeys(unittest.TestCase):
    def test_dot_keys_refused(self):
        from zotvault.pipeline import _SAFE_CITEKEY_RE as rx
        for bad in (".", "..", "...", ".hidden", "a/b", "a b", ""):
            self.assertIsNone(rx.match(bad), bad)
        for good in ("xiaoCoupledSpinValley2012a", "Wang.2012", "Lee-2026", "ManzeliEtAl2017"):
            self.assertIsNotNone(rx.match(good), good)


if __name__ == "__main__":
    unittest.main()

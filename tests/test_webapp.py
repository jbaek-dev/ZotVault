import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

from zotvault.config import Config
from zotvault.webapp import make_handler


class TestWebappGuards(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.td = tempfile.TemporaryDirectory()
        cfg = Config()
        cfg.state_db = Path(cls.td.name) / "state.db"
        cfg.pdf_dir = Path(cls.td.name) / "pdfs"
        cfg.vault_dir = None
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(cfg))
        cls.port = cls.server.server_address[1]
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.td.cleanup()

    def _post(self, path, headers=None, body=b"{}"):
        req = urllib.request.Request(
            "http://127.0.0.1:{}{}".format(self.port, path),
            data=body,
            headers={"Content-Type": "application/json", **(headers or {})},
        )
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                return resp.status, json.loads(resp.read().decode())
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read().decode())

    def test_post_without_header_is_forbidden(self):
        code, body = self._post("/api/add")
        self.assertEqual(code, 403)
        self.assertIn("X-ZotVault", body["error"])

    def test_post_with_header_passes_guard(self):
        code, body = self._post("/api/add", headers={"X-ZotVault": "1"})
        self.assertEqual(code, 200)
        self.assertEqual(body["error"], "no identifiers")  # guard passed, input invalid

    def test_get_status_open(self):
        with urllib.request.urlopen(
            "http://127.0.0.1:{}/api/status".format(self.port), timeout=5
        ) as resp:
            self.assertEqual(resp.status, 200)
            data = json.loads(resp.read().decode())
            self.assertIn("version", data)

    def test_foreign_host_header_rejected(self):
        code, body = self._post("/api/add",
                                headers={"X-ZotVault": "1", "Host": "evil.example.com"})
        self.assertEqual(code, 403)


if __name__ == "__main__":
    unittest.main()


    def test_doctor_endpoint(self):
        req = urllib.request.Request("http://127.0.0.1:{}/api/doctor".format(self.port))
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
        self.assertIsInstance(data, list)
        self.assertGreater(len(data), 3)
        self.assertIn("name", data[0])
        self.assertIn("ok", data[0])
        self.assertIn("detail", data[0])

    def test_status_reports_zotero_only_mode(self):
        req = urllib.request.Request("http://127.0.0.1:{}/api/status".format(self.port))
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode())
        self.assertEqual(data["mode"], "zotero-only")   # cfg.vault_dir=None in setUp

import os
import tempfile
import unittest
from pathlib import Path

from paperflow.config import load_config, parse_toml_mini


class TestMiniToml(unittest.TestCase):
    def test_basic(self):
        text = """
# comment
[zotero]
data_dir = "~/Zotero"   # trailing comment
connector_url = "http://127.0.0.1:23119"

[pipeline]
poll_interval_sec = 60
create_notes = true
dry_run = false
item_types = ["journalArticle", "preprint"]

[pdf]
request_delay_sec = 2.5
"""
        data = parse_toml_mini(text)
        self.assertEqual(data["zotero"]["data_dir"], "~/Zotero")
        self.assertEqual(data["pipeline"]["poll_interval_sec"], 60)
        self.assertIs(data["pipeline"]["create_notes"], True)
        self.assertIs(data["pipeline"]["dry_run"], False)
        self.assertEqual(data["pipeline"]["item_types"], ["journalArticle", "preprint"])
        self.assertEqual(data["pdf"]["request_delay_sec"], 2.5)

    def test_hash_inside_string(self):
        data = parse_toml_mini('[a]\nkey = "value#notcomment"\n')
        self.assertEqual(data["a"]["key"], "value#notcomment")


class TestLoadConfig(unittest.TestCase):
    def test_file_and_env_override(self):
        with tempfile.TemporaryDirectory() as td:
            cfg_path = Path(td) / "config.toml"
            cfg_path.write_text(
                '[vault]\ndir = "{}"\n[pipeline]\npoll_interval_sec = 42\n'.format(td),
                encoding="utf-8",
            )
            old = dict(os.environ)
            try:
                os.environ.pop("PAPERFLOW_VAULT_DIR", None)
                cfg = load_config(str(cfg_path))
                self.assertEqual(cfg.poll_interval_sec, 42)
                self.assertEqual(str(cfg.vault_dir), td)
                os.environ["PAPERFLOW_VAULT_DIR"] = td + "/other"
                cfg2 = load_config(str(cfg_path))
                self.assertTrue(str(cfg2.vault_dir).endswith("/other"))
            finally:
                os.environ.clear()
                os.environ.update(old)

    def test_missing_file_defaults(self):
        cfg = load_config("/nonexistent/paperflow.toml")
        self.assertIsNone(cfg.vault_dir)
        self.assertEqual(cfg.poll_interval_sec, 120)


if __name__ == "__main__":
    unittest.main()

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from zotvault.cli import _clean_pasted_path, apply_init_answers
from zotvault.config import CONFIG_TEMPLATE, Config
from zotvault.health import _decorrupted_vault_hint, checks


class TestHealthChecks(unittest.TestCase):
    def test_structure_and_graceful_failures(self):
        out = checks(Config())  # nothing configured/running -> must not raise
        self.assertGreater(len(out), 5)
        for name, ok, detail in out:
            self.assertIsInstance(name, str)
            self.assertIsInstance(ok, bool)
            self.assertIsInstance(detail, str)


class TestInitWizardInjection(unittest.TestCase):
    def test_injects_answers(self):
        t = apply_init_answers(CONFIG_TEMPLATE, vault="C:\\Users\\me\\Vault",
                               papers="Papers", email="a@b.c", lang="ko")
        self.assertIn('dir = "C:/Users/me/Vault"', t)      # 백슬래시 -> TOML 안전 슬래시
        self.assertIn('papers_subdir = "Papers"', t)
        self.assertIn('unpaywall_email = "a@b.c"', t)
        self.assertIn('language = "ko"', t)

    def test_blank_answers_leave_template_unchanged(self):
        self.assertEqual(apply_init_answers(CONFIG_TEMPLATE), CONFIG_TEMPLATE)

    def test_en_language_not_duplicated(self):
        t = apply_init_answers(CONFIG_TEMPLATE, lang="en")
        self.assertEqual(t.count('language = "en"'), 1)


class TestCleanPastedPath(unittest.TestCase):
    """`zotvault init`'s vault-path prompt: terminal tab-completion (or
    dragging a folder into a POSIX shell) inserts a backslash before
    spaces/tildes/etc. so the shell treats them literally. input() isn't a
    shell, so a pasted, already-escaped path arrives with those backslashes
    still in it — left alone, _toml_str()'s Windows-path-normalizing
    backslash->slash conversion turns them into a similar-looking but
    nonexistent path (the reported v0.9.8 bug)."""

    def test_unescapes_space_and_tilde(self):
        raw = r"/Users/x/Library/Mobile\ Documents/iCloud\~md\~obsidian/My\ Second\ Brain"
        self.assertEqual(
            _clean_pasted_path(raw),
            "/Users/x/Library/Mobile Documents/iCloud~md~obsidian/My Second Brain")

    def test_no_backslash_is_unchanged(self):
        self.assertEqual(_clean_pasted_path("/Users/x/Vault"), "/Users/x/Vault")

    def test_windows_backslash_path_left_untouched(self):
        with mock.patch("zotvault.cli.os.name", "nt"):
            self.assertEqual(_clean_pasted_path("C:\\Users\\me\\Vault"), "C:\\Users\\me\\Vault")

    def test_cleaned_path_survives_toml_injection_intact(self):
        # regression test for the reported bug: a pasted, shell-escaped path
        # must round-trip through init unchanged, not get mangled into
        # slashes by _toml_str().
        raw = r"/Users/x/Library/Mobile\ Documents/iCloud\~md\~obsidian/My\ Second\ Brain"
        t = apply_init_answers(CONFIG_TEMPLATE, vault=_clean_pasted_path(raw))
        self.assertIn(
            'dir = "/Users/x/Library/Mobile Documents/iCloud~md~obsidian/My Second Brain"', t)


class TestDecorruptedVaultHint(unittest.TestCase):
    def test_finds_existing_dir_after_undoing_corruption(self):
        with tempfile.TemporaryDirectory() as td:
            real = Path(td) / "iCloud~md~obsidian" / "My Second Brain"
            real.mkdir(parents=True)
            # simulate the exact corruption _toml_str() produced: a '/' folded
            # in wherever a '\' preceded a space or tilde
            corrupted = str(real).replace(" ", "/ ").replace("~", "/~")
            self.assertEqual(_decorrupted_vault_hint(corrupted), str(real))

    def test_no_hint_when_nothing_matches(self):
        self.assertEqual(_decorrupted_vault_hint("/nonexistent/totally/made/up/path"), "")

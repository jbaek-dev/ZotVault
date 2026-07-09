import unittest

from zotvault.cli import apply_init_answers
from zotvault.config import CONFIG_TEMPLATE, Config
from zotvault.health import checks


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

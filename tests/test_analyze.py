import tempfile
import unittest
from pathlib import Path
from unittest import mock

from zotvault import analyze
from zotvault.config import Config
from zotvault.state import State


def make_cfg(td: Path, engine: str = "ollama", model: str = "testmodel") -> Config:
    cfg = Config()
    cfg.vault_dir = td
    cfg.state_db = td / "state.db"
    cfg.pdf_dir = td / "pdfs"
    cfg.analysis_engine = engine
    cfg.analysis_model = model
    cfg.analysis_daily_limit = 2
    return cfg


def make_paper(papers: Path, citekey: str, with_analysis: bool = False) -> Path:
    folder = papers / citekey
    folder.mkdir(parents=True, exist_ok=True)
    (folder / (citekey + ".md")).write_text(
        '---\ntitle: "T"\nauthors: "A"\nyear: "2024"\n---\n\n'
        "## 📄 Abstract\nThis paper studies things in detail and reports results.\n\n---\n",
        encoding="utf-8")
    if with_analysis:
        (folder / (citekey + "_claude_analysis.md")).write_text("x", encoding="utf-8")
    return folder


LONG_BODY = "## 🧠 Core Summary (neutral)\n" + ("Solid neutral sentences. " * 20)


class TestHelpers(unittest.TestCase):
    def test_engine_suffix_defaults(self):
        cfg = Config()
        for engine, want in (("claude-cli", "claude"), ("anthropic", "claude"),
                             ("ollama", "ollama"), ("openai-compatible", "ai")):
            cfg.analysis_engine = engine
            cfg.analysis_suffix = ""
            self.assertEqual(analyze.engine_suffix(cfg), want)
        cfg.analysis_suffix = "custom"
        self.assertEqual(analyze.engine_suffix(cfg), "custom")

    def test_prompt_build_and_wrap(self):
        cfg = Config()
        cfg.analysis_engine = "ollama"
        cfg.analysis_model = "m1"
        prompt = analyze.build_prompt(
            {"title": "T", "authors": "A", "year": "2024", "journal": "J",
             "doi": "10.1/x", "citekey": "K2024"},
            "FULLTEXT HERE", "full-text", cfg)
        self.assertIn("Title: T", prompt)
        self.assertIn("FULLTEXT HERE", prompt)
        note = analyze.wrap_note("## body", "K2024", "full-text", cfg)
        self.assertIn("type: ai_analysis", note)
        self.assertIn("source: ollama:m1", note)
        self.assertIn('citekey: "K2024"', note)
        self.assertIn('input_basis: "full-text"', note)
        self.assertIn("immutable: true", note)

    def test_generate_dispatch_none(self):
        cfg = Config()
        with self.assertRaises(ValueError):
            analyze.generate("hi", cfg)


class TestAnalyzeOne(unittest.TestCase):
    def test_skip_existing(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            cfg = make_cfg(td)
            papers = cfg.papers_dir
            folder = make_paper(papers, "Kim2026", with_analysis=True)
            state = State(cfg.state_db)
            status, _ = analyze.analyze_one("Kim2026", folder, None, cfg, state)
            state.close()
            self.assertEqual(status, "exists")

    def test_write_via_abstract_fallback(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            cfg = make_cfg(td)
            folder = make_paper(cfg.papers_dir, "Lee2025")
            state = State(cfg.state_db)
            with mock.patch.object(analyze, "_gen_ollama", return_value=LONG_BODY):
                status, detail = analyze.analyze_one("Lee2025", folder, None, cfg, state)
            self.assertEqual(status, "written", detail)
            target = folder / "Lee2025_ollama_analysis.md"
            self.assertTrue(target.exists())
            text = target.read_text(encoding="utf-8")
            self.assertIn('input_basis: "abstract+metadata only"', text)
            self.assertEqual(state.analyses_today(), 1)
            state.close()

    def test_short_output_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            cfg = make_cfg(td)
            folder = make_paper(cfg.papers_dir, "Park2024")
            state = State(cfg.state_db)
            with mock.patch.object(analyze, "_gen_ollama", return_value="ok"):
                status, detail = analyze.analyze_one("Park2024", folder, None, cfg, state)
            state.close()
            self.assertEqual(status, "error")
            self.assertFalse((folder / "Park2024_ollama_analysis.md").exists())


class TestBatch(unittest.TestCase):
    def test_engine_none_refuses(self):
        with tempfile.TemporaryDirectory() as td:
            cfg = make_cfg(Path(td), engine="none")
            state = State(cfg.state_db)
            out = analyze.run_batch(cfg, state)
            state.close()
            self.assertEqual(out[0]["status"], "error")

    def test_budget_enforced(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            cfg = make_cfg(td)  # daily_limit = 2
            for ck in ("A2020", "B2021", "C2022"):
                make_paper(cfg.papers_dir, ck)
            state = State(cfg.state_db)
            with mock.patch.object(analyze, "_gen_ollama", return_value=LONG_BODY):
                results = analyze.run_batch(cfg, state)
            state.close()
            statuses = sorted(r["status"] for r in results)
            self.assertEqual(statuses.count("written"), 2)
            self.assertEqual(statuses.count("deferred"), 1)


if __name__ == "__main__":
    unittest.main()

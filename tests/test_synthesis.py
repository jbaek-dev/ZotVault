import tempfile
import unittest
from pathlib import Path

from paperflow.config import Config
from paperflow.synthesis import covered_citekeys, label_for, leader_cluster


class TestClustering(unittest.TestCase):
    def test_leader_cluster(self):
        vecs = {
            "A": [1.0, 0.0], "B": [0.95, 0.05], "C": [0.9, 0.1],
            "X": [0.0, 1.0], "Y": [0.05, 0.95],
            "Z": [0.7, 0.7],
        }
        clusters = leader_cluster(vecs, list(vecs), threshold=0.9)
        as_sets = sorted([tuple(sorted(c)) for c in clusters])
        self.assertIn(("A", "B", "C"), as_sets)
        self.assertIn(("X", "Y"), as_sets)

    def test_label(self):
        titles = {
            "A": "Valley lifetime in Janus TMDC monolayers",
            "B": "Janus TMDC valley depolarization",
            "C": "Strain effects on valley lifetime",
        }
        label = label_for(["A", "B", "C"], titles)
        self.assertIn("valley", label)


class TestCovered(unittest.TestCase):
    def test_covered_citekeys(self):
        with tempfile.TemporaryDirectory() as td:
            vault = Path(td)
            syn = vault / "30_Resources" / "Papers" / "syntheses"
            syn.mkdir(parents=True)
            (syn / "Real_Synthesis.md").write_text(
                "based on [[Kim2026]] and [[Lee2025|Lee et al.]] plus [[Note#sec]]",
                encoding="utf-8")
            (syn / "_Synthesis_Suggestions.md").write_text(
                "- [[ShouldNotCount2020]]", encoding="utf-8")
            cfg = Config()
            cfg.vault_dir = vault
            covered = covered_citekeys(cfg)
            self.assertIn("Kim2026", covered)
            self.assertIn("Lee2025", covered)
            self.assertIn("Note", covered)
            self.assertNotIn("ShouldNotCount2020", covered)


if __name__ == "__main__":
    unittest.main()

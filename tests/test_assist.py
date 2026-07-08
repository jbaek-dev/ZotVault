import tempfile
import unittest
from pathlib import Path
from unittest import mock

from zotvault import assist
from zotvault.config import Config
from zotvault.state import State


def make_cfg(**kw):
    cfg = Config()
    cfg.assist_enabled = True
    cfg.assist_model = "tiny:3b"
    cfg.alerts_keywords = ["valleytronics"]
    for k, v in kw.items():
        setattr(cfg, k, v)
    return cfg


class TestValidate(unittest.TestCase):
    def test_valid(self):
        self.assertIsNone(assist.validate_triage({"score": 7, "reason": "on topic"}))

    def test_invalid_cases(self):
        for bad in (None, [], {"score": "7", "reason": "x"}, {"score": 11, "reason": "x"},
                    {"score": -1, "reason": "x"}, {"score": True, "reason": "x"},
                    {"score": 5, "reason": ""}, {"score": 5}):
            self.assertIsNotNone(assist.validate_triage(bad), repr(bad))


class TestTriageOne(unittest.TestCase):
    def test_valid_first_try(self):
        with mock.patch.object(assist, "_ollama_chat_json",
                               return_value={"score": 8, "reason": "  direct hit  "}):
            out = assist.triage_one("T", "A", "valleytronics", make_cfg())
        self.assertEqual(out, {"score": 8, "reason": "direct hit"})

    def test_retry_once_with_feedback_then_success(self):
        calls = []

        def fake(prompt, cfg, timeout=120):
            calls.append(prompt)
            return {"score": 99, "reason": "x"} if len(calls) == 1 else {"score": 3, "reason": "adjacent"}

        with mock.patch.object(assist, "_ollama_chat_json", side_effect=fake):
            out = assist.triage_one("T", "A", "kw", make_cfg())
        self.assertEqual(out["score"], 3)
        self.assertEqual(len(calls), 2)
        self.assertIn("previous output was invalid", calls[1])

    def test_gives_up_after_two_bad(self):
        with mock.patch.object(assist, "_ollama_chat_json", return_value={"nope": 1}):
            self.assertIsNone(assist.triage_one("T", "A", "kw", make_cfg()))

    def test_model_down_returns_none(self):
        with mock.patch.object(assist, "_ollama_chat_json", side_effect=OSError("down")):
            self.assertIsNone(assist.triage_one("T", "A", "kw", make_cfg()))


class TestTriageAlerts(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.state = State(Path(self.td.name) / "s.db")
        for i, aid in enumerate(("2401.0001", "2401.0002", "2401.0003")):
            self.state.alert_add(aid, "Title {}".format(i), "A", "abs", "2026-07-01", "kw")

    def tearDown(self):
        self.state.close()
        self.td.cleanup()

    def test_scores_pending_within_budget(self):
        cfg = make_cfg(assist_max_per_run=2)
        with mock.patch.object(assist, "triage_one",
                               return_value={"score": 6, "reason": "r"}):
            n = assist.triage_alerts(cfg, self.state)
        self.assertEqual(n, 2)
        scored = [r for r in self.state.alerts_list("pending") if r["score"] is not None]
        self.assertEqual(len(scored), 2)
        # second run picks up the remaining one only
        with mock.patch.object(assist, "triage_one",
                               return_value={"score": 2, "reason": "r"}):
            n2 = assist.triage_alerts(cfg, self.state)
        self.assertEqual(n2, 1)

    def test_disabled_noop(self):
        cfg = make_cfg(assist_enabled=False)
        self.assertEqual(assist.triage_alerts(cfg, self.state), 0)

    def test_stops_batch_when_model_fails(self):
        cfg = make_cfg()
        with mock.patch.object(assist, "triage_one", return_value=None):
            self.assertEqual(assist.triage_alerts(cfg, self.state), 0)


if __name__ == "__main__":
    unittest.main()

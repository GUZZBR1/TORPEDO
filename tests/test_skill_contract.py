import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILL = (ROOT / "skills" / "scout" / "SKILL.md").read_text(encoding="utf-8")


class TestSkillContract(unittest.TestCase):
    def test_current_latch_tools_and_actions_are_named(self):
        for name in (
            "plow_read_skill", "plow_browser_open", "plow_browser_request",
            "plow_browser", "plow_vault", "plow_get_result", "plow_browser_close",
        ):
            with self.subTest(name=name):
                self.assertIn(f"`{name}`", SKILL)
        for action in ("screenshot", "text", "forms", "tables", "fill_secret", "use_page"):
            with self.subTest(action=action):
                self.assertIn(f"`{action}`", SKILL)

    def test_screenshot_precedes_interaction_and_eval_is_forbidden(self):
        screenshot = SKILL.index("action `screenshot` before interacting")
        proposed_action = SKILL.index("Run `safety_check.py` on the exact proposed")
        self.assertLess(screenshot, proposed_action)
        self.assertIn("Never use Latch action `eval`", SKILL)

    def test_vault_values_never_enter_model_or_database(self):
        compact = " ".join(SKILL.split())
        self.assertIn("This is the only credential fill path", compact)
        self.assertIn("Never retrieve", compact)
        self.assertIn("persist a value", compact)


if __name__ == "__main__":
    unittest.main()

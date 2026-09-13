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
        for action in ("goto", "screenshot", "text", "forms", "tables", "fill_secret", "use_page"):
            with self.subTest(action=action):
                self.assertIn(f"`{action}`", SKILL)

    def test_screenshot_precedes_interaction_and_eval_is_forbidden(self):
        screenshot = SKILL.index("action `screenshot` before interacting")
        proposed_action = SKILL.index("Run `safety_check.py` on the exact proposed")
        self.assertLess(screenshot, proposed_action)
        self.assertIn("including the active `mission_id`", " ".join(SKILL.split()))
        self.assertIn("Never use Latch action `eval`", SKILL)

    def test_vault_values_never_enter_model_or_database(self):
        compact = " ".join(SKILL.split())
        self.assertIn("This is the only credential fill path", compact)
        self.assertIn("Never retrieve", compact)
        self.assertIn("persist a value", compact)

    def test_ordinary_process_requests_activate_scout_without_generic_fallback(self):
        compact = " ".join(SKILL.split())
        for request in ("apply for", "book", "buy", "sign up for", "navigate"):
            with self.subTest(request=request):
                self.assertIn(request, compact)
        self.assertIn("do not fall back to a generic assistant capability list", compact)

    def test_latch_failure_cannot_fall_back_to_static_web_tools(self):
        compact = " ".join(SKILL.split())
        for forbidden_fallback in ("web_extract", "web search", "HTTP fetch", "cloud browser"):
            with self.subTest(forbidden_fallback=forbidden_fallback):
                self.assertIn(forbidden_fallback, compact)
        self.assertIn("must remain non-complete", compact)


if __name__ == "__main__":
    unittest.main()

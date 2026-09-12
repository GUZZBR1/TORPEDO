import unittest

from tests.support import DatabaseCase  # noqa: F401 - installs scripts import path
from safety_check import classify_action


class TestSafety(unittest.TestCase):
    def assertDenied(self, action_type, target):
        result = classify_action({"action_type": action_type, "target": target})
        self.assertFalse(result["allowed"], result)

    def test_golden_hard_stops(self):
        cases = [
            ("click", "Final submit"), ("purchase", "Product"), ("pay", "Invoice"),
            ("cancel", "Subscription"), ("delete", "Account"),
            ("send_message", "External recipient"), ("sign", "Agreement"),
            ("publish", "Application"), ("verify_identity", "Complete verification"),
        ]
        for action_type, target in cases:
            with self.subTest(action_type=action_type):
                self.assertDenied(action_type, target)

    def test_navigation_to_payment_page_is_allowed_for_inspection(self):
        result = classify_action({"action_type": "navigate", "target": "payment page"})
        self.assertTrue(result["allowed"])
        self.assertEqual("REVERSIBLE_NAVIGATION", result["classification"])

    def test_safe_continue_click_is_reversible_navigation(self):
        result = classify_action({"action_type": "click", "target": "Continue to next page"})
        self.assertTrue(result["allowed"])

    def test_unknown_action_fails_closed(self):
        self.assertDenied("run_magic", "continue")

    def test_draft_requires_explicit_narrow_justification(self):
        self.assertFalse(classify_action({"action_type": "fill", "target": "first name"})["allowed"])
        allowed = classify_action({
            "action_type": "fill", "target": "first name", "narrowly_justified": True,
            "creates_side_effect": False,
        })
        self.assertTrue(allowed["allowed"])


if __name__ == "__main__":
    unittest.main()

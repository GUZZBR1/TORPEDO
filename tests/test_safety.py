import unittest

from tests.support import DatabaseCase  # noqa: F401 - installs scripts import path
from scout_db import ScoutError
from safety_check import classify_action


class TestSafety(DatabaseCase, unittest.TestCase):
    def action(self, data, mission=None):
        mission = mission or self.recon_mission()
        return classify_action({**data, "mission_id": mission["id"]}, self.db)

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
        result = self.action({"action_type": "navigate", "target": "payment page"})
        self.assertTrue(result["allowed"])
        self.assertEqual("REVERSIBLE_NAVIGATION", result["classification"])

    def test_latch_goto_is_supported(self):
        result = self.action({"action_type": "goto", "target": "https://example.test/next"})
        self.assertTrue(result["allowed"])
        self.assertEqual("REVERSIBLE_NAVIGATION", result["classification"])

    def test_safe_continue_click_is_reversible_navigation(self):
        result = self.action({"action_type": "click", "target": "Continue to next page"})
        self.assertTrue(result["allowed"])

    def test_compound_continue_action_cannot_hide_submit_or_payment(self):
        for target in (
            "Continue and submit", "Continue and pay", "Allow and continue",
            "Continue and delete file", "Continue and cancel reservation",
            "Grant access and continue", "Accept and continue",
            "Continuar e autorizar", "Continuar e cancelar reserva",
        ):
            with self.subTest(target=target):
                result = self.action({"action_type": "click", "target": target})
                self.assertFalse(result["allowed"])
                self.assertEqual("IRREVERSIBLE", result["classification"])

    def test_unknown_action_fails_closed(self):
        self.assertDenied("run_magic", "continue")

    def test_ambiguous_click_fails_closed(self):
        self.assertDenied("click", "Confirm")

    def test_reading_a_dangerous_control_is_allowed(self):
        result = classify_action({"action_type": "screenshot", "target": "Final submit button"})
        self.assertTrue(result["allowed"])
        self.assertEqual("READ_ONLY", result["classification"])

    def test_portuguese_hard_stops_are_denied(self):
        for target in ("Pagar agora", "Aceitar os termos", "Enviar a inscrição", "Excluir conta"):
            with self.subTest(target=target):
                self.assertDenied("click", target)

    def test_action_contract_rejects_unknown_fields_and_wrong_types(self):
        with self.assertRaises(ScoutError):
            classify_action({"action_type": "read", "typo": True})
        with self.assertRaises(ScoutError):
            classify_action({"action_type": "fill", "narrowly_justified": "yes"})
        with self.assertRaises(ScoutError):
            classify_action({"action_type": "read", "mission_id": 123})

    def test_draft_requires_explicit_narrow_justification(self):
        self.assertFalse(classify_action({"action_type": "fill", "target": "first name"})["allowed"])
        mission = self.recon_mission(allow_form_draft=True)
        allowed = self.action({
            "action_type": "fill", "target": "first name", "narrowly_justified": True,
            "creates_side_effect": False,
        }, mission)
        self.assertTrue(allowed["allowed"])

    def test_secret_fill_requires_user_approval(self):
        base = {
            "action_type": "fill_secret", "target": "password field",
            "narrowly_justified": True, "creates_side_effect": False,
        }
        mission = self.recon_mission()
        self.assertFalse(self.action(base, mission)["allowed"])
        self.assertTrue(self.action({**base, "user_approved": True}, mission)["allowed"])

    def test_mutating_or_navigation_action_without_mission_fails_closed(self):
        for action in (
            {"action_type": "goto", "target": "https://example.test/next"},
            {
                "action_type": "fill", "target": "name", "narrowly_justified": True,
                "creates_side_effect": False,
            },
        ):
            with self.subTest(action=action["action_type"]):
                result = classify_action(action)
                self.assertFalse(result["allowed"])
                self.assertIn("mission_id is required", result["reason"])

    def test_navigation_policy_is_enforced(self):
        mission = self.recon_mission(allow_navigation=False)
        for action_type in ("goto", "navigate", "click"):
            with self.subTest(action_type=action_type):
                target = "Continue" if action_type == "click" else "https://example.test/next"
                result = self.action({"action_type": action_type, "target": target}, mission)
                self.assertFalse(result["allowed"])
                self.assertIn("allow_navigation", result["reason"])

    def test_browser_action_requires_recon_phase(self):
        created = self.mission()
        result = self.action({"action_type": "goto", "target": "https://example.test"}, created)
        self.assertFalse(result["allowed"])
        self.assertIn("phase CREATED", result["reason"])

    def test_form_draft_policy_is_enforced(self):
        action = {
            "action_type": "fill", "target": "name", "narrowly_justified": True,
            "creates_side_effect": False,
        }
        denied = self.action(action, self.recon_mission(allow_form_draft=False))
        allowed = self.action(action, self.recon_mission(allow_form_draft=True))
        self.assertFalse(denied["allowed"])
        self.assertTrue(allowed["allowed"])

    def test_file_lookup_and_upload_policies_are_enforced(self):
        denied_lookup = self.action(
            {"action_type": "file_lookup", "target": "resume.pdf"},
            self.recon_mission(allow_file_lookup=False),
        )
        allowed_lookup = self.action(
            {"action_type": "file_lookup", "target": "resume.pdf"},
            self.recon_mission(allow_file_lookup=True),
        )
        self.assertFalse(denied_lookup["allowed"])
        self.assertTrue(allowed_lookup["allowed"])

        upload = {
            "action_type": "upload_draft", "target": "resume.pdf",
            "narrowly_justified": True, "creates_side_effect": False,
        }
        missing_file_permission = self.action(
            upload, self.recon_mission(allow_form_draft=True, allow_file_lookup=False)
        )
        missing_form_permission = self.action(
            upload, self.recon_mission(allow_form_draft=False, allow_file_lookup=True)
        )
        allowed_upload = self.action(
            {**upload, "user_approved": True},
            self.recon_mission(allow_form_draft=True, allow_file_lookup=True),
        )
        self.assertFalse(missing_file_permission["allowed"])
        self.assertFalse(missing_form_permission["allowed"])
        self.assertTrue(allowed_upload["allowed"])
        self.assertFalse(self.action(
            upload, self.recon_mission(allow_form_draft=True, allow_file_lookup=True)
        )["allowed"])

    def test_authentication_policy_is_enforced(self):
        action = {
            "action_type": "fill_secret", "target": "password field",
            "narrowly_justified": True, "creates_side_effect": False,
            "user_approved": True,
        }
        denied = self.action(action, self.recon_mission(allow_authentication=False))
        allowed = self.action(action, self.recon_mission(allow_authentication=True))
        self.assertFalse(denied["allowed"])
        self.assertTrue(allowed["allowed"])

        denied_sign_in = self.action(
            {"action_type": "click", "target": "Sign in"},
            self.recon_mission(allow_authentication=False),
        )
        allowed_sign_in = self.action(
            {"action_type": "click", "target": "Sign in"},
            self.recon_mission(allow_authentication=True),
        )
        self.assertFalse(denied_sign_in["allowed"])
        self.assertTrue(allowed_sign_in["allowed"])
        denied_oauth = self.action(
            {"action_type": "click", "target": "Continue with Google"},
            self.recon_mission(allow_authentication=False),
        )
        self.assertFalse(denied_oauth["allowed"])

    def test_word_make_is_not_an_irreversible_false_positive(self):
        result = self.action({"action_type": "goto", "description": "Make a profile draft"})
        self.assertTrue(result["allowed"])

    def test_make_payment_remains_irreversible(self):
        result = self.action({"action_type": "goto", "description": "Make the payment"})
        self.assertFalse(result["allowed"])
        self.assertEqual("IRREVERSIBLE", result["classification"])


if __name__ == "__main__":
    unittest.main()

import unittest

from tests.support import DatabaseCase
from scout_db import record_blocker, record_requirement, record_step, show_mission


class TestDeduplication(DatabaseCase, unittest.TestCase):
    def test_steps_requirements_and_blockers_are_idempotent(self):
        mission = self.recon_mission()
        step_input = {
            "mission_id": mission["id"], "kind": "FORM", "title": "Profile form",
            "url": "https://example.test/profile", "sequence_hint": 2,
            "evidence": [{"kind": "FORM_SCHEMA", "summary": "Name and email are required"}],
        }
        first = record_step(step_input, self.db)
        second = record_step(step_input, self.db)
        self.assertTrue(first["created"])
        self.assertFalse(second["created"])
        requirement = {
            "mission_id": mission["id"], "step_id": first["step"]["id"], "name": "Email",
            "category": "DATA", "status": "OBSERVED_REQUIRED", "evidence_id": first["evidence_ids"][0],
        }
        blocker = {
            "mission_id": mission["id"], "step_id": first["step"]["id"], "type": "LOGIN",
            "description": "Account login required", "recoverable": True, "owner_action": "Sign in",
        }
        self.assertTrue(record_requirement(requirement, self.db)["created"])
        self.assertFalse(record_requirement(requirement, self.db)["created"])
        self.assertTrue(record_blocker(blocker, self.db)["created"])
        self.assertFalse(record_blocker(blocker, self.db)["created"])
        snapshot = show_mission({"mission_id": mission["id"]}, self.db)
        self.assertEqual(1, len(snapshot["steps"]))
        self.assertEqual(1, len(snapshot["requirements"]))
        self.assertEqual(1, len(snapshot["blockers"]))


if __name__ == "__main__":
    unittest.main()


import unittest
import sqlite3

from tests.support import DatabaseCase
from scout_db import (
    ScoutError, record_blocker, record_fact, record_requirement, record_step, show_mission,
)


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

    def test_step_identity_distinguishes_wizard_pages_with_same_url_and_title(self):
        mission = self.recon_mission()
        base = {
            "mission_id": mission["id"], "kind": "PAGE", "title": "Same page",
            "url": "https://example.test/same", "sequence_hint": 1,
        }
        first = record_step(base, self.db)
        second = record_step({**base, "sequence_hint": 99}, self.db)
        self.assertTrue(first["created"])
        self.assertTrue(second["created"])

    def test_legacy_step_dedupe_key_is_migrated_without_duplicate(self):
        mission = self.recon_mission()
        payload = {
            "mission_id": mission["id"], "kind": "PAGE", "title": "Legacy page",
            "url": "https://example.test/legacy", "sequence_hint": 3,
        }
        first = record_step(payload, self.db)
        from scout_db import _fingerprint
        legacy_key = _fingerprint("PAGE", "Legacy page", "https://example.test/legacy")
        with sqlite3.connect(self.db) as conn:
            conn.execute("UPDATE steps SET dedupe_key=? WHERE id=?", (legacy_key, first["step"]["id"]))
        repeated = record_step(payload, self.db)
        self.assertFalse(repeated["created"])
        self.assertEqual(first["step"]["id"], repeated["step"]["id"])

    def test_step_and_requirement_can_advance_when_evidence_arrives(self):
        mission = self.recon_mission()
        partial_input = {
            "mission_id": mission["id"], "kind": "FORM", "title": "Profile",
            "url": "https://example.test/profile", "sequence_hint": 1,
            "status": "PARTIAL",
        }
        partial = record_step(partial_input, self.db)
        inferred = record_requirement({
            "mission_id": mission["id"], "step_id": partial["step"]["id"],
            "name": "Email", "category": "DATA", "status": "INFERRED",
        }, self.db)
        observed = record_step({
            **partial_input, "status": "OBSERVED",
            "evidence": [{"kind": "SCREENSHOT", "summary": "Email field visible"}],
        }, self.db)
        promoted = record_requirement({
            "mission_id": mission["id"], "step_id": partial["step"]["id"],
            "name": "Email", "category": "DATA", "status": "OBSERVED_REQUIRED",
            "evidence_id": observed["evidence_ids"][0],
        }, self.db)
        self.assertFalse(observed["created"])
        self.assertFalse(promoted["created"])
        self.assertEqual("OBSERVED", observed["step"]["status"])
        self.assertEqual("OBSERVED_REQUIRED", promoted["requirement"]["status"])

        inferred_fact = record_fact({
            "mission_id": mission["id"], "step_id": partial["step"]["id"],
            "type": "COST", "name": "Fee", "status": "INFERRED", "value": "$20",
        }, self.db)
        promoted_fact = record_fact({
            "mission_id": mission["id"], "step_id": partial["step"]["id"],
            "type": "COST", "name": "Fee", "status": "OBSERVED", "value": "$25",
            "evidence_id": observed["evidence_ids"][0],
        }, self.db)
        self.assertFalse(promoted_fact["created"])
        self.assertEqual("OBSERVED", promoted_fact["fact"]["status"])
        self.assertEqual("$25", promoted_fact["fact"]["value"])

    def test_conflicting_duplicate_is_not_silently_discarded(self):
        mission = self.recon_mission()
        original = {
            "mission_id": mission["id"], "kind": "PAGE", "title": "Same page",
            "url": "https://example.test/same", "sequence_hint": 1,
        }
        record_step(original, self.db)
        with self.assertRaises(ScoutError):
            record_step({**original, "status": "PARTIAL"}, self.db)


if __name__ == "__main__":
    unittest.main()

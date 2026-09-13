import sqlite3
import stat
import unittest
from pathlib import Path

from tests.support import DatabaseCase
from scout_db import (
    ScoutError, checkpoint, create_mission, record_blocker, record_requirement,
    record_step, show_mission,
)


class TestDatabase(DatabaseCase, unittest.TestCase):
    def test_schema_and_mission_creation(self):
        mission = self.mission(target_name="Example application")
        self.assertRegex(mission["id"], r"^sc_[0-9A-HJKMNP-TV-Z]{26}$")
        self.assertEqual("CREATED", mission["phase"])
        with sqlite3.connect(self.db) as conn:
            tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertTrue({"missions", "steps", "requirements", "blockers", "evidence", "facts", "mission_events"} <= tables)

    def test_checkpoint_survives_new_connection(self):
        mission = self.recon_mission()
        step = record_step({
            "mission_id": mission["id"], "kind": "PAGE", "title": "Start",
            "url": "https://example.test/apply", "sequence_hint": 1,
            "evidence": [{"kind": "SCREENSHOT", "summary": "Application landing page"}],
        }, self.db)["step"]
        checkpoint({"mission_id": mission["id"], "last_completed_step_id": step["id"], "current_url": step["url"]}, self.db)
        restored = show_mission({"mission_id": mission["id"]}, self.db)["mission"]
        self.assertEqual(step["id"], restored["last_completed_step_id"])
        self.assertIsNotNone(restored["last_checkpoint_at"])

    def test_secret_fields_are_rejected_and_url_tokens_are_redacted(self):
        with self.assertRaises(ScoutError):
            create_mission({
                "raw_user_request": "Scout this portal",
                "entrypoint": "https://example.test",
                "password": "must-not-persist",
            }, self.db)
        mission = create_mission({
            "raw_user_request": "Scout this portal",
            "entrypoint": "https://example.test/callback?code=private&next=home",
        }, self.db)["mission"]
        self.assertIn("code=%5BREDACTED%5D", mission["entrypoint"])
        self.assertNotIn("private", mission["entrypoint"])
        redacted = create_mission({
            "raw_user_request": (
                "password is correct horse battery staple; open "
                "https://alice:secret@example.test/callback?code=private"
                "; Authorization: Bearer abcdefghijklmnop"
            ),
        }, self.db)["mission"]["raw_user_request"]
        self.assertNotIn("correct horse battery staple", redacted)
        self.assertNotIn("alice:secret", redacted)
        self.assertNotIn("private", redacted)
        self.assertNotIn("abcdefghijklmnop", redacted)
        pem_redacted = create_mission({
            "raw_user_request": (
                "Scout this\n-----BEGIN PRIVATE KEY-----\nvery-secret-material\n"
                "-----END PRIVATE KEY-----"
            ),
        }, self.db)["mission"]["raw_user_request"]
        self.assertNotIn("very-secret-material", pem_redacted)
        with self.assertRaisesRegex(ScoutError, "userinfo"):
            create_mission({
                "raw_user_request": "Scout this portal",
                "entrypoint": "https://alice:secret@example.test/start",
            }, self.db)

    def test_database_permissions_are_private(self):
        self.mission()
        db_path = Path(self.db)
        self.assertEqual(0o600, stat.S_IMODE(db_path.stat().st_mode))
        self.assertEqual(0o700, stat.S_IMODE(db_path.parent.stat().st_mode))

    def test_raw_user_request_is_preserved_verbatim(self):
        raw = "  Scout this exactly:\nhttps://example.test/path  "
        mission = create_mission({"raw_user_request": raw}, self.db)["mission"]
        self.assertEqual(raw, mission["raw_user_request"])

    def test_unknown_fields_and_non_boolean_policy_are_rejected(self):
        with self.assertRaises(ScoutError):
            create_mission({"raw_user_request": "Scout this", "ignored": "value"}, self.db)
        with self.assertRaises(ScoutError):
            create_mission({
                "raw_user_request": "Scout this",
                "allow_authentication": "false",
            }, self.db)

    def test_failed_nested_evidence_write_rolls_back_step(self):
        mission = self.recon_mission()
        with self.assertRaises(ScoutError):
            record_step({
                "mission_id": mission["id"], "kind": "PAGE", "title": "Atomic page",
                "url": "https://example.test/atomic", "sequence_hint": 1,
                "evidence": [
                    {"kind": "SCREENSHOT", "summary": "valid"},
                    {"kind": "SCREENSHOT", "summary": "invalid", "unexpected": True},
                ],
            }, self.db)
        self.assertEqual([], show_mission({"mission_id": mission["id"]}, self.db)["steps"])

    def test_evidence_timestamp_requires_iso_timezone(self):
        mission = self.recon_mission()
        with self.assertRaisesRegex(ScoutError, "timezone"):
            record_step({
                "mission_id": mission["id"], "kind": "PAGE", "title": "Timestamp",
                "url": "https://example.test/time", "sequence_hint": 1,
                "evidence": [{
                    "kind": "SCREENSHOT", "summary": "Page visible",
                    "captured_at": "2026-09-12T12:00:00",
                }],
            }, self.db)

    def test_cross_mission_references_are_rejected(self):
        first = self.recon_mission()
        foreign_step = record_step({
            "mission_id": first["id"], "kind": "PAGE", "title": "Foreign",
            "url": "https://example.test/foreign", "sequence_hint": 1,
            "evidence": [{"kind": "SCREENSHOT", "summary": "Foreign page"}],
        }, self.db)
        second = self.recon_mission()
        with self.assertRaises(ScoutError):
            record_requirement({
                "mission_id": second["id"], "step_id": foreign_step["step"]["id"],
                "name": "ID", "category": "IDENTITY", "status": "OBSERVED_REQUIRED",
            }, self.db)
        with self.assertRaises(ScoutError):
            record_blocker({
                "mission_id": second["id"], "step_id": foreign_step["step"]["id"],
                "type": "LOGIN", "description": "Login", "recoverable": True,
            }, self.db)


if __name__ == "__main__":
    unittest.main()

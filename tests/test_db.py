import sqlite3
import unittest

from tests.support import DatabaseCase
from scout_db import ScoutError, checkpoint, create_mission, record_step, show_mission


class TestDatabase(DatabaseCase, unittest.TestCase):
    def test_schema_and_mission_creation(self):
        mission = self.mission(target_name="Example application")
        self.assertTrue(mission["id"].startswith("sc_"))
        self.assertEqual("CREATED", mission["phase"])
        with sqlite3.connect(self.db) as conn:
            tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertTrue({"missions", "steps", "requirements", "blockers", "evidence", "mission_events"} <= tables)

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


if __name__ == "__main__":
    unittest.main()

import unittest

from tests.support import DatabaseCase
from scout_db import ScoutError, update_mission


class TestStateMachine(DatabaseCase, unittest.TestCase):
    def test_block_and_resume(self):
        mission = self.recon_mission()
        blocked = update_mission({"mission_id": mission["id"], "phase": "BLOCKED"}, self.db)["mission"]
        self.assertEqual("BLOCKED", blocked["phase"])
        resumed = update_mission({"mission_id": mission["id"], "phase": "RECON"}, self.db)["mission"]
        self.assertEqual("RECON", resumed["phase"])

    def test_invalid_transition_is_rejected(self):
        mission = self.mission()
        with self.assertRaises(ScoutError):
            update_mission({"mission_id": mission["id"], "phase": "COMPLETE"}, self.db)

    def test_terminal_state_cannot_restart(self):
        mission = self.recon_mission()
        update_mission({"mission_id": mission["id"], "phase": "CANCELLED"}, self.db)
        with self.assertRaises(ScoutError):
            update_mission({"mission_id": mission["id"], "phase": "RECON"}, self.db)


if __name__ == "__main__":
    unittest.main()


import unittest

from tests.support import DatabaseCase
from scout_db import (
    ScoutError, checkpoint, record_blocker, record_step, resolve_blocker, update_mission,
)


class TestStateMachine(DatabaseCase, unittest.TestCase):
    def observed_step(self, mission, *, boundary=False):
        return record_step({
            "mission_id": mission["id"], "kind": "SUBMIT" if boundary else "PAGE",
            "title": "Final submit" if boundary else "Start",
            "url": "https://example.test/review" if boundary else "https://example.test/apply",
            "sequence_hint": 1, "reversible": not boundary,
            "side_effect_risk": "CONSEQUENTIAL" if boundary else "NONE",
            "evidence": [{"kind": "SCREENSHOT", "summary": "Observed page"}],
        }, self.db)["step"]

    def test_block_and_resume(self):
        mission = self.recon_mission()
        step = self.observed_step(mission)
        checkpoint({
            "mission_id": mission["id"], "last_completed_step_id": step["id"],
            "current_url": step["url"],
        }, self.db)
        blocker = record_blocker({
            "mission_id": mission["id"], "step_id": step["id"], "type": "CAPTCHA",
            "description": "CAPTCHA requires user", "recoverable": True,
            "owner_action": "Complete CAPTCHA",
        }, self.db)["blocker"]
        blocked = update_mission({"mission_id": mission["id"], "phase": "BLOCKED"}, self.db)["mission"]
        self.assertEqual("BLOCKED", blocked["phase"])
        with self.assertRaises(ScoutError):
            update_mission({"mission_id": mission["id"], "phase": "RECON"}, self.db)
        resolve_blocker({"mission_id": mission["id"], "blocker_id": blocker["id"]}, self.db)
        resumed = update_mission({"mission_id": mission["id"], "phase": "RECON"}, self.db)["mission"]
        self.assertEqual("RECON", resumed["phase"])

    def test_blocked_requires_a_recorded_blocker(self):
        mission = self.recon_mission()
        with self.assertRaises(ScoutError):
            update_mission({"mission_id": mission["id"], "phase": "BLOCKED"}, self.db)

    def test_complete_requires_checkpoint_and_boundary_or_safe_end(self):
        mission = self.recon_mission()
        step = self.observed_step(mission)
        with self.assertRaises(ScoutError):
            update_mission({"mission_id": mission["id"], "phase": "COMPLETE"}, self.db)
        checkpoint({
            "mission_id": mission["id"], "last_completed_step_id": step["id"],
            "current_url": step["url"],
        }, self.db)
        with self.assertRaises(ScoutError):
            update_mission({"mission_id": mission["id"], "phase": "COMPLETE"}, self.db)
        complete = update_mission({
            "mission_id": mission["id"], "phase": "COMPLETE", "safe_end_confirmed": True,
        }, self.db)["mission"]
        self.assertEqual("COMPLETE", complete["phase"])

    def test_failed_requires_structured_error(self):
        mission = self.recon_mission()
        with self.assertRaises(ScoutError):
            update_mission({"mission_id": mission["id"], "phase": "FAILED"}, self.db)
        failed = update_mission({
            "mission_id": mission["id"], "phase": "FAILED",
            "error_code": "DB_WRITE", "error_message": "Database unavailable",
        }, self.db)["mission"]
        self.assertEqual("FAILED", failed["phase"])

    def test_invalid_transition_is_rejected(self):
        mission = self.mission()
        with self.assertRaises(ScoutError):
            update_mission({"mission_id": mission["id"], "phase": "COMPLETE"}, self.db)

    def test_same_phase_only_is_rejected_as_noop(self):
        mission = self.recon_mission()
        with self.assertRaises(ScoutError):
            update_mission({"mission_id": mission["id"], "phase": "RECON"}, self.db)
        with self.assertRaises(ScoutError):
            update_mission({
                "mission_id": mission["id"], "target_name": "Target",
                "safe_end_confirmed": True,
            }, self.db)

    def test_terminal_state_cannot_restart(self):
        mission = self.recon_mission()
        update_mission({"mission_id": mission["id"], "phase": "CANCELLED"}, self.db)
        with self.assertRaises(ScoutError):
            update_mission({"mission_id": mission["id"], "phase": "RECON"}, self.db)


if __name__ == "__main__":
    unittest.main()

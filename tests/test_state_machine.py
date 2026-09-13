import unittest

from tests.support import DatabaseCase
from scout_db import (
    ScoutError, checkpoint, link_steps, record_blocker, record_requirement, record_step,
    resolve_blocker, update_mission,
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

    def test_early_block_can_resume_after_transient_blocker_is_resolved(self):
        mission = self.recon_mission()
        blocker = record_blocker({
            "mission_id": mission["id"], "type": "SITE_FAILURE",
            "description": "Latch temporarily unavailable", "recoverable": True,
            "owner_action": "Reconnect Latch",
        }, self.db)["blocker"]
        update_mission({"mission_id": mission["id"], "phase": "BLOCKED"}, self.db)
        resolve_blocker({"mission_id": mission["id"], "blocker_id": blocker["id"]}, self.db)
        resumed = update_mission({"mission_id": mission["id"], "phase": "RECON"}, self.db)
        self.assertEqual("RECON", resumed["mission"]["phase"])

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

    def test_checkpoint_and_completion_require_screenshot_evidence(self):
        mission = self.recon_mission()
        text_only = record_step({
            "mission_id": mission["id"], "kind": "PAGE", "title": "Static fallback",
            "url": "https://example.test/static", "sequence_hint": 1,
            "evidence": [{"kind": "PAGE_TEXT", "summary": "Text fetched without Latch"}],
        }, self.db)["step"]
        with self.assertRaisesRegex(ScoutError, "screenshot"):
            checkpoint({
                "mission_id": mission["id"], "last_completed_step_id": text_only["id"],
                "current_url": text_only["url"],
            }, self.db)

        observed = self.observed_step(mission)
        checkpoint({
            "mission_id": mission["id"], "last_completed_step_id": observed["id"],
            "current_url": observed["url"],
        }, self.db)
        with self.assertRaisesRegex(ScoutError, "screenshot"):
            update_mission({
                "mission_id": mission["id"], "phase": "COMPLETE", "safe_end_confirmed": True,
            }, self.db)

    def test_complete_rejects_disconnected_route_and_unobserved_boundary(self):
        mission = self.recon_mission()
        first = self.observed_step(mission)
        second = record_step({
            "mission_id": mission["id"], "kind": "SUBMIT", "title": "Submit",
            "url": "https://example.test/submit", "status": "UNREACHABLE",
            "sequence_hint": 2, "reversible": False,
            "side_effect_risk": "CONSEQUENTIAL",
        }, self.db)["step"]
        checkpoint({
            "mission_id": mission["id"], "last_completed_step_id": first["id"],
            "current_url": first["url"],
        }, self.db)
        with self.assertRaisesRegex(ScoutError, "boundary"):
            update_mission({"mission_id": mission["id"], "phase": "COMPLETE"}, self.db)
        observed_boundary = record_step({
            "mission_id": mission["id"], "kind": "SUBMIT", "title": "Submit",
            "url": "https://example.test/submit", "status": "OBSERVED",
            "sequence_hint": 2, "reversible": False, "side_effect_risk": "CONSEQUENTIAL",
            "evidence": [{"kind": "SCREENSHOT", "summary": "Submit visible"}],
        }, self.db)["step"]
        self.assertEqual(second["id"], observed_boundary["id"])
        with self.assertRaisesRegex(ScoutError, "route root"):
            update_mission({"mission_id": mission["id"], "phase": "COMPLETE"}, self.db)
        link_steps({
            "mission_id": mission["id"], "from_step_id": first["id"],
            "to_step_id": observed_boundary["id"],
        }, self.db)
        checkpoint({
            "mission_id": mission["id"], "last_completed_step_id": observed_boundary["id"],
            "current_url": observed_boundary["url"],
        }, self.db)
        complete = update_mission({"mission_id": mission["id"], "phase": "COMPLETE"}, self.db)
        self.assertEqual("COMPLETE", complete["mission"]["phase"])

    def test_complete_rejects_cycle_in_route_graph(self):
        mission = self.recon_mission()
        first = self.observed_step(mission)
        second = record_step({
            "mission_id": mission["id"], "kind": "PAGE", "title": "Second",
            "url": "https://example.test/second", "sequence_hint": 2,
            "evidence": [{"kind": "SCREENSHOT", "summary": "Second visible"}],
        }, self.db)["step"]
        third = record_step({
            "mission_id": mission["id"], "kind": "PAGE", "title": "Third",
            "url": "https://example.test/third", "sequence_hint": 3,
            "evidence": [{"kind": "SCREENSHOT", "summary": "Third visible"}],
        }, self.db)["step"]
        link_steps({"mission_id": mission["id"], "from_step_id": first["id"], "to_step_id": second["id"]}, self.db)
        link_steps({"mission_id": mission["id"], "from_step_id": second["id"], "to_step_id": third["id"]}, self.db)
        link_steps({"mission_id": mission["id"], "from_step_id": third["id"], "to_step_id": second["id"]}, self.db)
        checkpoint({
            "mission_id": mission["id"], "last_completed_step_id": third["id"],
            "current_url": third["url"],
        }, self.db)
        with self.assertRaisesRegex(ScoutError, "acyclic"):
            update_mission({
                "mission_id": mission["id"], "phase": "COMPLETE", "safe_end_confirmed": True,
            }, self.db)

    def test_complete_requires_checkpoint_at_terminal_boundary(self):
        mission = self.recon_mission()
        first = self.observed_step(mission)
        boundary = record_step({
            "mission_id": mission["id"], "kind": "SUBMIT", "title": "Submit",
            "url": "https://example.test/submit", "sequence_hint": 2,
            "reversible": False, "side_effect_risk": "CONSEQUENTIAL",
            "evidence": [{"kind": "SCREENSHOT", "summary": "Submit visible"}],
        }, self.db)["step"]
        link_steps({
            "mission_id": mission["id"], "from_step_id": first["id"],
            "to_step_id": boundary["id"],
        }, self.db)
        checkpoint({
            "mission_id": mission["id"], "last_completed_step_id": first["id"],
            "current_url": first["url"],
        }, self.db)
        with self.assertRaisesRegex(ScoutError, "terminal route step"):
            update_mission({"mission_id": mission["id"], "phase": "COMPLETE"}, self.db)

    def test_observed_requirement_requires_evidence(self):
        mission = self.recon_mission()
        step = self.observed_step(mission)
        with self.assertRaisesRegex(ScoutError, "evidence_id"):
            record_requirement({
                "mission_id": mission["id"], "step_id": step["id"], "name": "ID",
                "category": "IDENTITY", "status": "OBSERVED_REQUIRED",
            }, self.db)

    def test_boolean_sequence_hint_is_rejected(self):
        mission = self.recon_mission()
        with self.assertRaisesRegex(ScoutError, "sequence_hint"):
            record_step({
                "mission_id": mission["id"], "kind": "PAGE", "title": "Start",
                "sequence_hint": True,
            }, self.db)

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

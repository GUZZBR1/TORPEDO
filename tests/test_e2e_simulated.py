import unittest

from tests.support import DatabaseCase
from report_build import build_report
from safety_check import classify_action
from scout_db import (
    checkpoint, link_steps, record_blocker, record_requirement, record_step,
    resolve_blocker, update_mission,
)


class TestSimulatedEndToEnd(DatabaseCase, unittest.TestCase):
    def step(self, mission_id, title, sequence, *, kind="PAGE", risk="NONE"):
        result = record_step({
            "mission_id": mission_id, "kind": kind, "title": title,
            "url": f"https://example.test/step-{sequence}", "sequence_hint": sequence,
            "reversible": risk != "CONSEQUENTIAL", "side_effect_risk": risk,
            "evidence": [{"kind": "SCREENSHOT", "summary": f"{title} observed"}],
        }, self.db)
        checkpoint({
            "mission_id": mission_id, "last_completed_step_id": result["step"]["id"],
            "current_url": result["step"]["url"],
        }, self.db)
        return result

    def requirement(self, mission_id, step):
        record_requirement({
            "mission_id": mission_id, "step_id": step["step"]["id"],
            "name": "Email address", "category": "DATA", "status": "OBSERVED_REQUIRED",
            "evidence_id": step["evidence_ids"][0],
        }, self.db)

    def test_public_multistep_safe_end(self):
        mission = self.recon_mission(target_name="Public application")
        start = self.step(mission["id"], "Start", 1)
        form = self.step(mission["id"], "Form", 2, kind="FORM")
        link_steps({
            "mission_id": mission["id"], "from_step_id": start["step"]["id"],
            "to_step_id": form["step"]["id"],
        }, self.db)
        self.requirement(mission["id"], form)
        update_mission({
            "mission_id": mission["id"], "phase": "COMPLETE", "safe_end_confirmed": True,
        }, self.db)
        self.assertIn("2 steps", build_report({"mission_id": mission["id"]}, self.db)["report"])

    def test_authenticated_portal_block_and_resume(self):
        mission = self.recon_mission(target_name="Authenticated portal")
        auth = self.step(mission["id"], "Login", 1, kind="AUTH")
        blocker = record_blocker({
            "mission_id": mission["id"], "step_id": auth["step"]["id"], "type": "LOGIN",
            "description": "Owner login required", "recoverable": True,
            "owner_action": "Approve vault item",
        }, self.db)["blocker"]
        update_mission({"mission_id": mission["id"], "phase": "BLOCKED"}, self.db)
        resolve_blocker({"mission_id": mission["id"], "blocker_id": blocker["id"]}, self.db)
        update_mission({"mission_id": mission["id"], "phase": "RECON"}, self.db)
        portal = self.step(mission["id"], "Portal", 2)
        link_steps({
            "mission_id": mission["id"], "from_step_id": auth["step"]["id"],
            "to_step_id": portal["step"]["id"],
        }, self.db)
        self.requirement(mission["id"], portal)
        update_mission({
            "mission_id": mission["id"], "phase": "COMPLETE", "safe_end_confirmed": True,
        }, self.db)
        report = build_report({"mission_id": mission["id"]}, self.db)["report"]
        self.assertIn("Owner login required (resolved)", report)

    def test_irreversible_boundary_is_observed_but_not_clicked(self):
        mission = self.recon_mission(target_name="Purchase flow")
        start = self.step(mission["id"], "Cart", 1)
        self.requirement(mission["id"], start)
        boundary = self.step(
            mission["id"], "Pay now", 2, kind="PAYMENT", risk="CONSEQUENTIAL"
        )
        link_steps({
            "mission_id": mission["id"], "from_step_id": start["step"]["id"],
            "to_step_id": boundary["step"]["id"],
        }, self.db)
        action = classify_action({"action_type": "click", "target": "Pay now"})
        self.assertFalse(action["allowed"])
        update_mission({"mission_id": mission["id"], "phase": "COMPLETE"}, self.db)
        report = build_report({"mission_id": mission["id"]}, self.db)["report"]
        self.assertIn("Scout stopped before Pay now.", report)
        self.assertTrue(boundary["step"]["evidence_ids"])


if __name__ == "__main__":
    unittest.main()

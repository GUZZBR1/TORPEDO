import unittest

from tests.support import DatabaseCase
from report_build import build_report
from scout_db import (
    ScoutError, checkpoint, link_steps, record_fact, record_requirement, record_step, update_mission,
)


class TestReport(DatabaseCase, unittest.TestCase):
    def test_complete_evidence_backed_report(self):
        mission = self.recon_mission(target_name="Example grant")
        page = record_step({
            "mission_id": mission["id"], "kind": "PAGE", "title": "Grant details",
            "url": "https://example.test/grant", "sequence_hint": 1,
            "evidence": [{"kind": "SCREENSHOT", "summary": "Grant details page"}],
        }, self.db)
        record_requirement({
            "mission_id": mission["id"], "step_id": page["step"]["id"], "name": "Project summary",
            "category": "DOCUMENT", "status": "OBSERVED_REQUIRED", "evidence_id": page["evidence_ids"][0],
        }, self.db)
        record_fact({
            "mission_id": mission["id"], "step_id": page["step"]["id"],
            "type": "COST", "name": "Application fee", "value": "$25",
            "status": "OBSERVED", "evidence_id": page["evidence_ids"][0],
        }, self.db)
        record_fact({
            "mission_id": mission["id"], "step_id": page["step"]["id"],
            "type": "DEADLINE", "name": "Submission deadline", "value": "2026-10-01",
            "status": "OBSERVED", "evidence_id": page["evidence_ids"][0],
        }, self.db)
        record_fact({
            "mission_id": mission["id"], "step_id": page["step"]["id"],
            "type": "OTHER", "name": "Estimated review time", "status": "UNKNOWN",
        }, self.db)
        boundary = record_step({
            "mission_id": mission["id"], "kind": "SUBMIT", "title": "final submission",
            # Deliberately out of order: the graph, not the hint, owns report order.
            "url": "https://example.test/grant/review", "sequence_hint": 0,
            "reversible": False, "side_effect_risk": "CONSEQUENTIAL",
            "evidence": [{"kind": "SCREENSHOT", "summary": "Final submit button visible but not clicked"}],
        }, self.db)["step"]
        link_steps({
            "mission_id": mission["id"], "from_step_id": page["step"]["id"],
            "to_step_id": boundary["id"],
        }, self.db)
        checkpoint({
            "mission_id": mission["id"], "last_completed_step_id": boundary["id"],
            "current_url": boundary["url"],
        }, self.db)
        update_mission({"mission_id": mission["id"], "phase": "COMPLETE"}, self.db)
        result = build_report({"mission_id": mission["id"]}, self.db)
        self.assertIn("SCOUT COMPLETE", result["report"])
        self.assertIn("Application fee: $25", result["report"])
        self.assertIn("Submission deadline: 2026-10-01", result["report"])
        self.assertIn("Unknown: Estimated review time", result["report"])
        self.assertIn("Scout stopped before final submission.", result["report"])
        self.assertIn("1. [OBSERVED] Grant details", result["report"])
        self.assertIn("2. [OBSERVED] final submission", result["report"])

    def test_incomplete_report_is_refused(self):
        mission = self.recon_mission()
        with self.assertRaises(ScoutError):
            build_report({"mission_id": mission["id"]}, self.db)

    def test_safe_end_report_allows_another_branch_to_end_at_boundary(self):
        mission = self.recon_mission(target_name="Branched flow")
        root = record_step({
            "mission_id": mission["id"], "kind": "PAGE", "title": "Start",
            "url": "https://example.test/start", "sequence_hint": 1,
            "evidence": [{"kind": "SCREENSHOT", "summary": "Start visible"}],
        }, self.db)["step"]
        boundary = record_step({
            "mission_id": mission["id"], "kind": "PAYMENT", "title": "Pay",
            "url": "https://example.test/pay", "sequence_hint": 2,
            "reversible": False, "side_effect_risk": "CONSEQUENTIAL",
            "evidence": [{"kind": "SCREENSHOT", "summary": "Payment visible"}],
        }, self.db)["step"]
        safe_end = record_step({
            "mission_id": mission["id"], "kind": "PAGE", "title": "Eligibility result",
            "url": "https://example.test/result", "sequence_hint": 3,
            "evidence": [{"kind": "SCREENSHOT", "summary": "Result visible"}],
        }, self.db)["step"]
        for destination in (boundary, safe_end):
            link_steps({
                "mission_id": mission["id"], "from_step_id": root["id"],
                "to_step_id": destination["id"],
            }, self.db)
        checkpoint({
            "mission_id": mission["id"], "last_completed_step_id": safe_end["id"],
            "current_url": safe_end["url"],
        }, self.db)
        completed = update_mission({
            "mission_id": mission["id"], "phase": "COMPLETE", "safe_end_confirmed": True,
        }, self.db)["mission"]
        self.assertEqual(1, completed["safe_end_confirmed"])
        self.assertIn("Eligibility result", build_report({"mission_id": mission["id"]}, self.db)["report"])


if __name__ == "__main__":
    unittest.main()

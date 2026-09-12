import unittest

from tests.support import DatabaseCase
from report_build import build_report
from scout_db import ScoutError, record_requirement, record_step, update_mission


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
        record_step({
            "mission_id": mission["id"], "kind": "SUBMIT", "title": "final submission",
            "url": "https://example.test/grant/review", "sequence_hint": 2,
            "reversible": False, "side_effect_risk": "CONSEQUENTIAL",
            "evidence": [{"kind": "OBSERVATION", "summary": "Final submit button visible but not clicked"}],
        }, self.db)
        update_mission({"mission_id": mission["id"], "phase": "COMPLETE"}, self.db)
        result = build_report({"mission_id": mission["id"]}, self.db)
        self.assertIn("SCOUT COMPLETE", result["report"])
        self.assertIn("Scout stopped before final submission.", result["report"])

    def test_incomplete_report_is_refused(self):
        mission = self.recon_mission()
        with self.assertRaises(ScoutError):
            build_report({"mission_id": mission["id"]}, self.db)


if __name__ == "__main__":
    unittest.main()


import unittest

from tests.support import DatabaseCase
from scout_db import ScoutError, link_steps, record_fact, record_step, show_mission


class TestGraphAndFacts(DatabaseCase, unittest.TestCase):
    def step(self, mission_id, title, sequence):
        return record_step({
            "mission_id": mission_id,
            "kind": "PAGE",
            "title": title,
            "url": f"https://example.test/{title.casefold()}",
            "sequence_hint": sequence,
            "evidence": [{"kind": "SCREENSHOT", "summary": f"{title} visible"}],
        }, self.db)

    def test_links_are_idempotent_and_exposed_as_graph(self):
        mission = self.recon_mission()
        first = self.step(mission["id"], "Start", 1)
        second = self.step(mission["id"], "Review", 2)
        link = {
            "mission_id": mission["id"],
            "from_step_id": first["step"]["id"],
            "to_step_id": second["step"]["id"],
        }
        self.assertTrue(link_steps(link, self.db)["created"])
        self.assertFalse(link_steps(link, self.db)["created"])
        snapshot = show_mission({"mission_id": mission["id"]}, self.db)
        self.assertEqual([second["step"]["id"]], snapshot["steps"][0]["next_step_ids"])
        self.assertEqual(first["evidence_ids"], snapshot["steps"][0]["evidence_ids"])

    def test_cross_mission_and_self_links_are_rejected(self):
        first_mission = self.recon_mission()
        first = self.step(first_mission["id"], "One", 1)
        second_mission = self.recon_mission()
        second = self.step(second_mission["id"], "Two", 1)
        with self.assertRaises(ScoutError):
            link_steps({
                "mission_id": first_mission["id"],
                "from_step_id": first["step"]["id"],
                "to_step_id": second["step"]["id"],
            }, self.db)
        with self.assertRaises(ScoutError):
            link_steps({
                "mission_id": first_mission["id"],
                "from_step_id": first["step"]["id"],
                "to_step_id": first["step"]["id"],
            }, self.db)

    def test_observed_cost_and_deadline_require_evidence(self):
        mission = self.recon_mission()
        step = self.step(mission["id"], "Fees", 1)
        with self.assertRaises(ScoutError):
            record_fact({
                "mission_id": mission["id"], "step_id": step["step"]["id"],
                "type": "COST", "name": "Application fee", "value": "$25",
                "status": "OBSERVED",
            }, self.db)
        cost = record_fact({
            "mission_id": mission["id"], "step_id": step["step"]["id"],
            "type": "COST", "name": "Application fee", "value": "$25",
            "status": "OBSERVED", "evidence_id": step["evidence_ids"][0],
        }, self.db)
        deadline = record_fact({
            "mission_id": mission["id"], "step_id": step["step"]["id"],
            "type": "DEADLINE", "name": "Submission closes", "value": "2026-10-01",
            "status": "OBSERVED", "evidence_id": step["evidence_ids"][0],
        }, self.db)
        self.assertTrue(cost["created"])
        self.assertTrue(deadline["created"])
        self.assertEqual(2, len(show_mission({"mission_id": mission["id"]}, self.db)["facts"]))


if __name__ == "__main__":
    unittest.main()

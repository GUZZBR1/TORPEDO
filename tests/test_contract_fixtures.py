import json
import unittest
from pathlib import Path

from tests.support import DatabaseCase  # noqa: F401 - installs scripts import path
from safety_check import classify_action


class TestContractFixtures(unittest.TestCase):
    def test_fixture_boundaries_fail_closed_as_declared(self):
        path = Path(__file__).parent / "fixtures" / "flows.json"
        flows = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(8, len(flows))
        for flow in flows:
            with self.subTest(flow=flow["name"]):
                result = classify_action(flow["boundary_action"])
                self.assertEqual(flow["expected_allowed"], result["allowed"], result)


if __name__ == "__main__":
    unittest.main()


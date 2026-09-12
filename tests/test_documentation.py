import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class TestDocumentation(unittest.TestCase):
    def test_readme_links_runbooks_and_avoids_download_in_repo(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("docs/OPERATIONS.md", readme)
        self.assertIn("docs/DEMO.md", readme)
        self.assertIn("docs/hackathon-build/checklist.md", readme)
        self.assertIn("/tmp/agent_index_client.py", readme)

    def test_operations_covers_durability_safety_and_telemetry(self):
        operations = (ROOT / "docs" / "OPERATIONS.md").read_text(encoding="utf-8")
        for term in ("agent-home", "checkpoint", "fill_secret", "safety_check.py", "Agent Index"):
            with self.subTest(term=term):
                self.assertIn(term, operations)

    def test_demo_has_all_three_acceptance_flows(self):
        demo = (ROOT / "docs" / "DEMO.md").read_text(encoding="utf-8")
        for title in (
            "Demo 1 — Public multi-step application",
            "Demo 2 — Authenticated portal",
            "Demo 3 — Irreversible boundary",
        ):
            with self.subTest(title=title):
                self.assertIn(title, demo)


if __name__ == "__main__":
    unittest.main()

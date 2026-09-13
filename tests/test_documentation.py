import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class TestDocumentation(unittest.TestCase):
    def test_readme_links_runbooks_and_avoids_download_in_repo(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("docs/OPERATIONS.md", readme)
        self.assertIn("docs/DEMO.md", readme)
        self.assertIn("docs/ACCEPTANCE_RECORD.md", readme)
        self.assertIn("docs/hackathon-build/checklist.md", readme)
        self.assertIn("/tmp/agent_index_client.py", readme)
        self.assertIn("Linux (or WSL on Windows)", readme)

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

    def test_external_gates_have_an_evidence_record(self):
        record = (ROOT / "docs" / "ACCEPTANCE_RECORD.md").read_text(encoding="utf-8")
        for term in (
            "Plow Chat startup",
            "Mac/Latch reconnaissance",
            "Agent Index ingestion",
            "Public multi-step demo",
            "Authenticated portal demo",
            "Irreversible-boundary demo",
        ):
            with self.subTest(term=term):
                self.assertIn(term, record)
        for forbidden in ("credential value", "browser session handle", "vault value"):
            with self.subTest(forbidden=forbidden):
                self.assertIn(forbidden, record)


if __name__ == "__main__":
    unittest.main()

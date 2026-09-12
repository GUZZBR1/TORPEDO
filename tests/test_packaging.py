import re
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SERVICE = ROOT / "image" / "s6-overlay" / "s6-rc.d" / "agent-index"


class TestPackaging(unittest.TestCase):
    def test_agent_index_service_is_wired_after_plow_init(self):
        self.assertEqual("longrun", (SERVICE / "type").read_text().strip())
        self.assertTrue((SERVICE / "dependencies.d" / "plow-init").exists())
        self.assertTrue(
            (ROOT / "image" / "s6-overlay" / "s6-rc.d" / "user" / "contents.d" / "agent-index").exists()
        )
        subprocess.run(["sh", "-n", str(SERVICE / "run")], check=True)

    def test_client_and_base_are_immutable_and_checked(self):
        pin = (ROOT / "vendor" / "client.pin").read_text()
        self.assertRegex(pin, r"(?m)^sha=[0-9a-f]{40}$")
        self.assertRegex(pin, r"(?m)^sha256=[0-9a-f]{64}$")
        dockerfile = (ROOT / "Dockerfile").read_text()
        self.assertRegex(dockerfile, r"(?m)^FROM .*:base-[0-9a-f]{40}@sha256:[0-9a-f]{64}$")
        self.assertIn("sha256sum", dockerfile)
        self.assertNotRegex(dockerfile, r"COPY[^\n]*/var/lib/hermes/skills")

    def test_compose_preserves_home_and_mounts_credentials_read_only(self):
        compose = (ROOT / "compose.yml").read_text()
        self.assertIn("agent-home:/var/lib/hermes", compose)
        self.assertIn("credentials.host:ro", compose)
        self.assertIn("AGENT_ID", compose)


if __name__ == "__main__":
    unittest.main()

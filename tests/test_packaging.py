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

    def test_scout_persona_is_installed_after_base_bootstrap(self):
        dockerfile = (ROOT / "Dockerfile").read_text()
        self.assertIn("runtime/persona.md /opt/hermes/plow-seed/persona.md", dockerfile)
        self.assertNotIn("/var/lib/hermes/SOUL.md", dockerfile)

    def test_generic_productivity_skills_are_excluded_from_scout_image(self):
        dockerfile = (ROOT / "Dockerfile").read_text()
        for path in (
            "/var/lib/hermes/skills/growth",
            "/var/lib/hermes/skills/productivity",
            "/opt/hermes/skills/growth",
            "/opt/hermes/skills/productivity",
        ):
            with self.subTest(path=path):
                self.assertIn(path, dockerfile)

    def test_persona_limits_scout_to_reconnaissance(self):
        persona = " ".join((ROOT / "runtime" / "persona.md").read_text(encoding="utf-8").split())
        self.assertIn("only product purpose is digital-process reconnaissance", persona)
        self.assertIn("Do not present yourself as a general digital assistant", persona)
        for unsupported_capability in (
            "email", "calendar", "files", "price monitoring", "documents", "spreadsheets",
        ):
            with self.subTest(unsupported_capability=unsupported_capability):
                self.assertIn(unsupported_capability, persona)
        self.assertIn("Ask them to send a link or name a specific process to scout", persona)
        self.assertIn("Olá, sou o Scout.", persona)
        self.assertIn("Envie um link ou diga qual processo quer que eu investigue.", persona)


if __name__ == "__main__":
    unittest.main()

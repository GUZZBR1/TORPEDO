import json
import subprocess
import sys
import unittest

from tests.support import DatabaseCase, ROOT, SCRIPTS


class TestCli(DatabaseCase, unittest.TestCase):
    def run_script(self, name, payload):
        return subprocess.run(
            [sys.executable, str(SCRIPTS / name), "--db", self.db],
            cwd=ROOT,
            input=json.dumps(payload),
            text=True,
            capture_output=True,
            check=False,
        )

    def test_cli_emits_machine_readable_success(self):
        result = self.run_script("mission_create.py", {"raw_user_request": "Scout this"})
        self.assertEqual(0, result.returncode, result.stderr)
        payload = json.loads(result.stdout)
        self.assertTrue(payload["ok"])
        self.assertEqual("CREATED", payload["mission"]["phase"])

    def test_cli_emits_json_and_nonzero_for_unknown_field(self):
        result = self.run_script(
            "mission_create.py", {"raw_user_request": "Scout this", "typo": True}
        )
        self.assertEqual(2, result.returncode)
        payload = json.loads(result.stdout)
        self.assertFalse(payload["ok"])
        self.assertIn("unknown input field", payload["error"])


if __name__ == "__main__":
    unittest.main()

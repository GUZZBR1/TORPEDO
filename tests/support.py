import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills" / "scout" / "scripts"
sys.path.insert(0, str(SCRIPTS))

from scout_db import create_mission, update_mission  # noqa: E402


class DatabaseCase:
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = str(Path(self.temp.name) / "scout.db")

    def tearDown(self):
        self.temp.cleanup()

    def mission(self, **overrides):
        data = {"raw_user_request": "Scout this: https://example.test/apply", "entrypoint": "https://example.test/apply"}
        data.update(overrides)
        return create_mission(data, self.db)["mission"]

    def recon_mission(self, **overrides):
        mission = self.mission(**overrides)
        return update_mission({"mission_id": mission["id"], "phase": "RECON"}, self.db)["mission"]


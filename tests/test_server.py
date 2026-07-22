import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from agent_project_hq.server import clean_markdown, load_config, path_artifacts, plan_progress


class ServerTests(unittest.TestCase):
    def test_plan_progress_is_structural(self):
        plan = [
            {"step": "one", "status": "completed"},
            {"step": "two", "status": "in_progress"},
            {"step": "three", "status": "pending"},
        ]
        self.assertEqual(plan_progress(plan, "active"), 52)

    def test_clean_markdown(self):
        self.assertEqual(clean_markdown("**完成** `model.pt`", 80), "完成 model.pt")
        self.assertTrue(clean_markdown("x" * 100, 12).endswith("…"))

    def test_artifact_filter_keeps_allowed_and_drops_cache(self):
        config = {
            "artifacts": {
                "allowed_roots": ["/project"],
                "remote_prefixes": ["/home/"],
                "ignore_contains": ["/tmp/", "/site-packages/"],
                "max_per_task": 8,
            }
        }
        rows = path_artifacts(config, [
            "/project/report.md",
            "/tmp/nope.mp4",
            "/outside/private.txt",
            "/home/user/model.pt",
            "/home/user/site-packages/nope.py",
        ])
        self.assertEqual({item["path"] for item in rows}, {"/project/report.md", "/home/user/model.pt"})

    def test_config_defaults_are_portable(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_path = root / "project-hq.json"
            config_path.write_text(json.dumps({"project": {"name": "Demo", "root": tmp}}))
            config = load_config(config_path)
            self.assertEqual(config["project"]["name"], "Demo")
            self.assertEqual(config["discovery"]["workspace_match"], str(root.resolve()))
            self.assertEqual(config["artifacts"]["allowed_roots"], [str(root.resolve())])


if __name__ == "__main__":
    unittest.main()

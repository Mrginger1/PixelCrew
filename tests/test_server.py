import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from pixelcrew.server import build_crew_report, build_insights, clean_markdown, extract_rollout, load_config, path_artifacts, plan_progress


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


    def test_stage_reports_capture_milestones_and_decisions(self):
        rows = [
            {"timestamp": "2026-01-01T01:00:00Z", "payload": {"type": "function_call", "name": "update_plan", "arguments": json.dumps({"plan": [{"step": "实现", "status": "in_progress"}, {"step": "验证", "status": "pending"}]})}},
            {"timestamp": "2026-01-01T02:00:00Z", "payload": {"type": "function_call", "name": "update_plan", "arguments": json.dumps({"explanation": "决定采用独立验证，核心实现已经完成。", "plan": [{"step": "实现", "status": "completed"}, {"step": "验证", "status": "in_progress"}]})}},
        ]
        with tempfile.TemporaryDirectory() as tmp:
            rollout = Path(tmp) / "rollout.jsonl"
            rollout.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows))
            result = extract_rollout(rollout)
        self.assertEqual(len(result["stageReports"]), 2)
        latest = result["stageReports"][-1]
        self.assertEqual(latest["kind"], "decision")
        self.assertEqual(latest["completed"], ["实现"])
        self.assertEqual(latest["current"], "验证")
        self.assertGreater(latest["delta"], 0)

    def test_crew_report_collapses_history_into_one_dossier(self):
        employee = {
            "id": "worker", "threadId": "thread", "name": "实现工程师", "title": "实现功能",
            "status": "active", "statusLabel": "工作中", "progress": 60, "updatedLabel": "刚刚",
            "assignment": "补齐测试", "summary": "最新汇报", "color": "#123", "accent": "#456",
            "plan": [{"step": "实现", "status": "completed"}, {"step": "交付", "status": "pending"}],
            "artifacts": [{"path": "/project/result.md"}],
            "stageReports": [
                {"timestamp": "2026-01-01T01:00:00Z", "kind": "milestone", "headline": "实现完成", "summary": "核心功能完成", "completed": ["实现"], "current": "测试"},
                {"timestamp": "2026-01-01T02:00:00Z", "kind": "decision", "headline": "采用独立验证", "summary": "交给验证成员", "completed": [], "current": "补齐测试"},
            ],
        }
        report = build_crew_report(employee)
        self.assertEqual(report["latestHeadline"], "采用独立验证")
        self.assertEqual(report["outcomes"], ["实现"])
        self.assertEqual(report["nextSteps"], ["交付"])
        self.assertEqual(report["stats"], {"reports": 2, "milestones": 1, "decisions": 1, "evidence": 1})

    def test_project_insights_measure_breadth_and_attention(self):
        employees = [
            {"id": "a", "name": "A", "status": "complete", "progress": 100, "plan": [{"step": "one", "status": "completed"}], "artifacts": [{"path": "/x"}], "stageReports": [{}], "updatedAt": "2999-01-01T00:00:00+00:00"},
            {"id": "b", "name": "B", "status": "blocked", "progress": 20, "plan": [{"step": "two", "status": "in_progress"}], "artifacts": [], "stageReports": [], "updatedAt": "2999-01-01T00:00:00+00:00"},
        ]
        insights = build_insights(employees)
        radar = {item["key"]: item["value"] for item in insights["radar"]}
        self.assertEqual(radar["evidence"], 50)
        self.assertEqual(radar["reporting"], 50)
        self.assertFalse(insights["healthy"])
        self.assertEqual(insights["attention"][0]["owner"], "B")

    def test_config_defaults_are_portable(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_path = root / "pixelcrew.json"
            config_path.write_text(json.dumps({"project": {"name": "Demo", "root": tmp}}))
            config = load_config(config_path)
            self.assertEqual(config["project"]["name"], "Demo")
            self.assertEqual(config["discovery"]["workspace_match"], str(root.resolve()))
            self.assertEqual(config["artifacts"]["allowed_roots"], [str(root.resolve())])


if __name__ == "__main__":
    unittest.main()

"""Unit tests for PixelCrew's local lifecycle CLI."""
from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import signal
import tempfile
import unittest
import webbrowser
from pathlib import Path
from unittest import mock

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from pixelcrew import cli


class LifecycleCliTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.config = self.root / "pixelcrew.json"
        self.config.write_text(
            json.dumps({"project": {"name": "Demo", "root": str(self.root)}}),
            encoding="utf-8",
        )

    def args(self, **overrides):
        values = {
            "config": self.config,
            "port": 8765,
            "timeout": 0.1,
            "foreground": False,
        }
        values.update(overrides)
        return argparse.Namespace(**values)

    def state(self, **overrides):
        values = {
            "pid": 4321,
            "process_token": "x" * 32,
            "config": str(self.config),
            "port": 8765,
            "log": str(self.root / ".pixelcrew" / "server.log"),
            "status": "running",
        }
        values.update(overrides)
        state_path = self.root / ".pixelcrew" / "server.json"
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text(json.dumps(values), encoding="utf-8")
        return state_path

    def capture(self, function, args):
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            result = function(args)
        return result, stdout.getvalue(), stderr.getvalue()

    def test_parser_exposes_lifecycle_commands_and_keeps_serve(self):
        parser = cli.build_parser()
        for command in ("start", "status", "open", "stop", "serve"):
            parsed = parser.parse_args([command])
            self.assertEqual(parsed.command, command)
        with mock.patch("pixelcrew.cli.legacy_server_main") as legacy:
            cli.main(["serve", "--config", str(self.config), "--process-token", "secret-token"])
        legacy.assert_called_once_with(
            [
                "--config", str(self.config), "--host", "127.0.0.1", "--port", "8765",
                "--process-token", "secret-token",
            ]
        )

    def test_start_missing_config_guides_init_without_spawning(self):
        missing = self.root / "missing.json"
        with mock.patch("pixelcrew.cli.subprocess.Popen") as popen:
            result, _out, error = self.capture(cli.command_start, self.args(config=missing))
        self.assertEqual(result, cli.STATUS_CONFIG_ERROR)
        self.assertIn("pixelcrew init", error)
        popen.assert_not_called()

    def test_start_creates_detached_local_process_state_and_log(self):
        process = mock.Mock(pid=4321)
        with (
            mock.patch("pixelcrew.cli._port_available", return_value=True),
            mock.patch("pixelcrew.cli._wait_for_health", return_value=(True, "")),
            mock.patch("pixelcrew.cli._process_start_identity", return_value="ps:test"),
            mock.patch("pixelcrew.cli.subprocess.Popen", return_value=process) as popen,
        ):
            result, output, error = self.capture(cli.command_start, self.args(port=9123))
        self.assertEqual((result, error), (cli.STATUS_RUNNING, ""))
        self.assertIn("http://127.0.0.1:9123", output)
        state_path = self.root / ".pixelcrew" / "server.json"
        log_path = self.root / ".pixelcrew" / "server.log"
        state = json.loads(state_path.read_text(encoding="utf-8"))
        self.assertEqual(state["pid"], 4321)
        self.assertEqual(state["status"], "running")
        self.assertEqual(Path(state["log"]), log_path)
        self.assertGreaterEqual(len(state["process_token"]), 24)
        self.assertTrue(log_path.is_file())
        command = popen.call_args.args[0]
        self.assertEqual(command[command.index("--host") + 1], "127.0.0.1")
        self.assertEqual(command[command.index("--port") + 1], "9123")
        self.assertEqual(command[command.index("--process-token") + 1], state["process_token"])
        self.assertTrue(popen.call_args.kwargs["start_new_session"])
        self.assertEqual(popen.call_args.kwargs["cwd"], self.root)
        pythonpath = popen.call_args.kwargs["env"]["PYTHONPATH"].split(os.pathsep)
        self.assertEqual(Path(pythonpath[0]), Path(cli.__file__).resolve().parents[1])

    def test_foreground_start_reclaims_child_when_sigterm_arrives_during_spawn(self):
        process = mock.Mock(pid=4321)

        def spawn_then_signal(*_args, **_kwargs):
            os.kill(os.getpid(), signal.SIGTERM)
            return process

        with (
            mock.patch("pixelcrew.cli._port_available", return_value=True),
            mock.patch("pixelcrew.cli.subprocess.Popen", side_effect=spawn_then_signal),
            mock.patch("pixelcrew.cli._stop_child", return_value=True) as stop_child,
        ):
            result, _output, error = self.capture(
                cli.command_start, self.args(port=9124, foreground=True)
            )

        self.assertEqual((result, error), (128 + signal.SIGTERM, ""))
        stop_child.assert_called_once_with(process)
        self.assertFalse((self.root / ".pixelcrew" / "server.json").exists())

    def test_start_does_not_duplicate_a_verified_running_service(self):
        self.state()
        with (
            mock.patch("pixelcrew.cli._process_is_running", return_value=True),
            mock.patch("pixelcrew.cli._process_identity_matches", return_value=True),
            mock.patch("pixelcrew.cli._health", return_value=(True, "")),
            mock.patch("pixelcrew.cli.subprocess.Popen") as popen,
        ):
            result, output, _error = self.capture(cli.command_start, self.args())
        self.assertEqual(result, cli.STATUS_RUNNING)
        self.assertIn("不会创建重复进程", output)
        popen.assert_not_called()

    def test_start_refuses_corrupt_state_without_spawning(self):
        state_path = self.root / ".pixelcrew" / "server.json"
        state_path.parent.mkdir(parents=True)
        state_path.write_text("{broken", encoding="utf-8")
        with mock.patch("pixelcrew.cli.subprocess.Popen") as popen:
            result, _output, error = self.capture(cli.command_start, self.args())
        self.assertEqual(result, cli.STATUS_CONFIG_ERROR)
        self.assertIn("状态损坏", error)
        popen.assert_not_called()

    def test_start_refuses_symlink_runtime_directory(self):
        target = self.root / "runtime-target"
        target.mkdir()
        (self.root / ".pixelcrew").symlink_to(target, target_is_directory=True)
        with mock.patch("pixelcrew.cli.subprocess.Popen") as popen:
            result, _output, error = self.capture(cli.command_start, self.args())
        self.assertEqual(result, cli.STATUS_CONFIG_ERROR)
        self.assertIn("符号链接", error)
        popen.assert_not_called()

    def test_start_reclaims_child_if_state_publish_fails(self):
        process = mock.Mock(pid=4321)
        with (
            mock.patch("pixelcrew.cli._port_available", return_value=True),
            mock.patch("pixelcrew.cli._process_start_identity", return_value="ps:test"),
            mock.patch("pixelcrew.cli.subprocess.Popen", return_value=process),
            mock.patch("pixelcrew.cli._atomic_write_json", side_effect=OSError("disk full")),
            mock.patch("pixelcrew.cli._stop_child", return_value=True) as stop_child,
        ):
            result, _output, error = self.capture(cli.command_start, self.args())
        self.assertEqual(result, cli.STATUS_CONFIG_ERROR)
        self.assertIn("已回收子进程", error)
        stop_child.assert_called_once_with(process)

    def test_start_rejects_non_finite_timeout(self):
        with mock.patch("pixelcrew.cli.subprocess.Popen") as popen:
            result, _output, error = self.capture(cli.command_start, self.args(timeout=float("inf")))
        self.assertEqual(result, cli.STATUS_CONFIG_ERROR)
        self.assertIn("有限秒数", error)
        popen.assert_not_called()

    def test_start_reports_port_conflict_with_action(self):
        with (
            mock.patch("pixelcrew.cli._port_available", return_value=False),
            mock.patch("pixelcrew.cli.subprocess.Popen") as popen,
        ):
            result, _output, error = self.capture(cli.command_start, self.args())
        self.assertEqual(result, cli.STATUS_UNREACHABLE)
        self.assertIn("端口冲突", error)
        self.assertIn("--port 8766", error)
        popen.assert_not_called()

    def test_status_distinguishes_config_error_exited_running_and_unreachable(self):
        missing = self.root / "missing.json"
        result, _output, error = self.capture(cli.command_status, self.args(config=missing))
        self.assertEqual(result, cli.STATUS_CONFIG_ERROR)
        self.assertIn("配置错误", error)

        result, output, _error = self.capture(cli.command_status, self.args())
        self.assertEqual(result, cli.STATUS_EXITED)
        self.assertIn("已退出", output)

        self.state()
        with (
            mock.patch("pixelcrew.cli._process_is_running", return_value=True),
            mock.patch("pixelcrew.cli._process_identity_matches", return_value=True),
            mock.patch("pixelcrew.cli._health", return_value=(False, "connection refused")),
        ):
            result, _output, error = self.capture(cli.command_status, self.args())
        self.assertEqual(result, cli.STATUS_UNREACHABLE)
        self.assertIn("服务不可达", error)

        with (
            mock.patch("pixelcrew.cli._process_is_running", return_value=True),
            mock.patch("pixelcrew.cli._process_identity_matches", return_value=True),
            mock.patch("pixelcrew.cli._health", return_value=(True, "")),
        ):
            result, output, error = self.capture(cli.command_status, self.args())
        self.assertEqual((result, error), (cli.STATUS_RUNNING, ""))
        self.assertIn("正在运行", output)
        self.assertIn("PID：4321", output)

    def test_status_treats_stale_pid_identity_as_exited(self):
        self.state()
        with (
            mock.patch("pixelcrew.cli._process_is_running", return_value=True),
            mock.patch("pixelcrew.cli._process_identity_matches", return_value=False),
        ):
            result, _output, error = self.capture(cli.command_status, self.args())
        self.assertEqual(result, cli.STATUS_EXITED)
        self.assertIn("不是可验证的 PixelCrew", error)

    def test_stop_refuses_to_signal_identity_mismatch(self):
        self.state()
        with (
            mock.patch("pixelcrew.cli._process_is_running", return_value=True),
            mock.patch("pixelcrew.cli._process_identity_matches", return_value=False),
            mock.patch("pixelcrew.cli.os.kill") as kill,
        ):
            result, _output, error = self.capture(cli.command_stop, self.args())
        self.assertEqual(result, cli.STATUS_EXITED)
        self.assertIn("拒绝停止", error)
        kill.assert_not_called()

    def test_stop_terminates_only_verified_recorded_process(self):
        state_path = self.state()
        with (
            mock.patch("pixelcrew.cli._process_is_running", side_effect=[True, False, False]),
            mock.patch("pixelcrew.cli._process_identity_matches", return_value=True),
            mock.patch("pixelcrew.cli.os.kill") as kill,
        ):
            result, output, error = self.capture(cli.command_stop, self.args())
        self.assertEqual((result, error), (cli.STATUS_RUNNING, ""))
        kill.assert_called_once_with(4321, signal.SIGTERM)
        self.assertIn("已停止", output)
        self.assertEqual(json.loads(state_path.read_text(encoding="utf-8"))["status"], "stopped")

    def test_open_handles_browser_backend_error(self):
        self.state()
        with (
            mock.patch("pixelcrew.cli._process_is_running", return_value=True),
            mock.patch("pixelcrew.cli._process_identity_matches", return_value=True),
            mock.patch("pixelcrew.cli._health", return_value=(True, "")),
            mock.patch("pixelcrew.cli.webbrowser.open", side_effect=webbrowser.Error("no browser")),
        ):
            result, _output, error = self.capture(cli.command_open, self.args())
        self.assertEqual(result, cli.STATUS_UNREACHABLE)
        self.assertIn("手动访问", error)

    def test_open_checks_health_and_opens_only_computed_loopback_url(self):
        self.state(url="https://example.com/unsafe")
        with (
            mock.patch("pixelcrew.cli._process_is_running", return_value=True),
            mock.patch("pixelcrew.cli._process_identity_matches", return_value=True),
            mock.patch("pixelcrew.cli._health", return_value=(True, "")),
            mock.patch("pixelcrew.cli.webbrowser.open", return_value=True) as browser,
        ):
            result, output, error = self.capture(cli.command_open, self.args())
        self.assertEqual((result, error), (cli.STATUS_RUNNING, ""))
        browser.assert_called_once_with("http://127.0.0.1:8765")
        self.assertIn("已打开", output)


if __name__ == "__main__":
    unittest.main()

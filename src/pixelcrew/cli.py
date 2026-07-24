"""Command-line interface for creating and running a PixelCrew office."""
from __future__ import annotations

import argparse
import contextlib
import json
import math
import os
import secrets
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

try:  # Unix and Windows both use a standard-library advisory file lock.
    import fcntl
except ImportError:  # pragma: no cover - exercised on Windows CI/users.
    fcntl = None  # type: ignore[assignment]
    import msvcrt

from .secretary import run_codex_secretary, secretary_prompt
from .server import DEFAULT_WEB_DIR, Dashboard, load_config, main as legacy_server_main

LOOPBACK_HOST = "127.0.0.1"
DEFAULT_PORT = 8765
STATE_DIRECTORY = ".pixelcrew"
STATE_FILENAME = "server.json"
LOG_FILENAME = "server.log"
LOCK_FILENAME = "server.lock"
STATUS_RUNNING = 0
STATUS_EXITED = 1
STATUS_CONFIG_ERROR = 2
STATUS_UNREACHABLE = 3


class LifecycleConfigError(RuntimeError):
    """Raised when a lifecycle command cannot safely resolve its project."""


def create_config(root: Path, name: str | None = None, manager_thread_id: str = "") -> dict:
    root = root.expanduser().resolve()
    return {
        "project": {
            "name": name or root.name,
            "subtitle": "负责人统筹 · 子任务并行 · 统一验收",
            "root": str(root),
            "manager_thread_id": manager_thread_id,
        },
        "discovery": {
            "workspace_match": str(root),
            "include_archived": False,
            "title_keywords": [],
            "exclude_title_patterns": [],
        },
        "roles": {},
        "artifacts": {
            "allowed_roots": [str(root)],
            "remote_prefixes": ["/home/", "/workspace/"],
            "ignore_contains": ["/tmp/", "/.cache/", "/node_modules/", "/site-packages/"],
            "max_per_task": 8,
        },
        "secretary": {
            "enabled": True,
            "cache": str(root / ".pixelcrew" / "secretary.json"),
            "max_age_minutes": 180,
        },
    }


def command_init(args: argparse.Namespace) -> int:
    output = args.output.expanduser().resolve()
    if output.exists() and not args.force:
        raise RuntimeError(f"{output} 已存在；使用 --force 才会覆盖。")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(create_config(args.project_root, args.name, args.manager_thread_id), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"✓ 配置已生成：{output}")
    print(f"下一步：pixelcrew doctor --config {output}")
    return 0


def command_doctor(args: argparse.Namespace) -> int:
    config_path = args.config.expanduser().resolve()
    config = load_config(config_path)
    checks = [
        ("配置文件", config_path.is_file(), str(config_path)),
        ("项目目录", Path(config["project"]["root"]).is_dir(), config["project"]["root"]),
        ("Codex 状态库", Path(config["codex"]["state_db"]).is_file(), config["codex"]["state_db"]),
        ("Codex 会话索引", Path(config["codex"]["session_index"]).is_file(), config["codex"]["session_index"]),
        ("办公室页面", (DEFAULT_WEB_DIR / "index.html").is_file(), str(DEFAULT_WEB_DIR / "index.html")),
    ]
    failed = False
    for label, okay, detail in checks:
        print(f"{'✓' if okay else '✗'} {label}：{detail}")
        failed = failed or not okay
    if not failed:
        try:
            count = len(Dashboard(config)._rows())
            print(f"✓ 自动发现：{count} 个匹配当前项目的 Codex 任务")
            if count == 0:
                print("  提示：请确认任务工作目录位于 project.root，或调整 discovery.workspace_match。")
        except Exception as exc:
            print(f"✗ 无法读取 Codex 任务：{exc}")
            failed = True
    return 1 if failed else 0


def command_snapshot(args: argparse.Namespace) -> int:
    config = load_config(args.config.expanduser().resolve())
    print(json.dumps(Dashboard(config).snapshot(), ensure_ascii=False, indent=2))
    return 0


def command_secretary(args: argparse.Namespace) -> int:
    config = load_config(args.config.expanduser().resolve())
    dashboard = Dashboard(config)
    cache = Path(config["secretary"]["cache"])
    if args.output:
        cache = args.output.expanduser().resolve()
    if args.dry_run:
        print(secretary_prompt(dashboard.snapshot()))
        return 0

    def generate() -> None:
        snapshot = dashboard.snapshot()
        memo = run_codex_secretary(
            snapshot,
            output=cache,
            project_root=Path(config["project"]["root"]),
            codex_executable=args.codex,
            timeout=args.timeout,
        )
        print(f"✓ AI 秘书简报：{cache} · {memo['generatedLabel']}", flush=True)

    generate()
    if args.watch:
        interval = max(60, args.interval)
        print(f"秘书值班中：每 {interval} 秒更新一次；Ctrl-C 停止。", flush=True)
        try:
            while True:
                time.sleep(interval)
                try:
                    generate()
                except Exception as exc:
                    print(f"! 本轮秘书更新失败：{exc}", file=sys.stderr, flush=True)
        except KeyboardInterrupt:
            pass
    return 0


def _lifecycle_context(config_argument: Path) -> tuple[Path, dict[str, Any], Path, Path, Path]:
    config_path = config_argument.expanduser().resolve()
    if not config_path.is_file():
        raise LifecycleConfigError(
            f"找不到配置 {config_path}。请先运行：pixelcrew init {config_path.parent} --output {config_path}"
        )
    try:
        config = load_config(config_path)
        project_root = Path(config["project"]["root"]).expanduser().resolve()
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise LifecycleConfigError(f"无法读取配置 {config_path}：{exc}") from exc
    if not project_root.is_dir():
        raise LifecycleConfigError(f"project.root 不存在或不是目录：{project_root}")
    runtime_dir = project_root / STATE_DIRECTORY
    return config_path, config, project_root, runtime_dir / STATE_FILENAME, runtime_dir / LOG_FILENAME


def _prepare_runtime_directory(runtime_dir: Path) -> None:
    if runtime_dir.is_symlink():
        raise LifecycleConfigError(f"拒绝使用符号链接运行目录：{runtime_dir}")
    try:
        runtime_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    except OSError as exc:
        raise LifecycleConfigError(f"无法创建运行目录 {runtime_dir}：{exc}") from exc
    if not runtime_dir.is_dir():
        raise LifecycleConfigError(f"运行路径不是目录：{runtime_dir}")


def _safe_open(path: Path, flags: int, mode: int = 0o600) -> int:
    if path.is_symlink():
        raise LifecycleConfigError(f"拒绝跟随符号链接：{path}")
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    cloexec = getattr(os, "O_CLOEXEC", 0)
    try:
        return os.open(path, flags | nofollow | cloexec, mode)
    except OSError as exc:
        raise LifecycleConfigError(f"无法安全打开 {path}：{exc}") from exc


@contextlib.contextmanager
def _runtime_lock(runtime_dir: Path):
    _prepare_runtime_directory(runtime_dir)
    lock_path = runtime_dir / LOCK_FILENAME
    descriptor = _safe_open(lock_path, os.O_RDWR | os.O_CREAT)
    with os.fdopen(descriptor, "a+") as lock_handle:
        if fcntl is not None:
            fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX)
        else:  # pragma: no cover - Windows fallback.
            lock_handle.seek(0)
            if lock_handle.read(1) == "":
                lock_handle.write("0")
                lock_handle.flush()
            lock_handle.seek(0)
            msvcrt.locking(lock_handle.fileno(), msvcrt.LK_LOCK, 1)
        try:
            yield
        finally:
            if fcntl is not None:
                fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)
            else:  # pragma: no cover - Windows fallback.
                lock_handle.seek(0)
                msvcrt.locking(lock_handle.fileno(), msvcrt.LK_UNLCK, 1)


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    _prepare_runtime_directory(path.parent)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{secrets.token_hex(8)}.tmp")
    descriptor = _safe_open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def _read_state(path: Path) -> dict[str, Any] | None:
    if path.parent.is_symlink():
        return {"invalid": True, "error": "运行目录是符号链接"}
    if path.is_symlink():
        return {"invalid": True, "error": "状态文件是符号链接"}
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return {"invalid": True, "error": str(exc)}
    return state if isinstance(state, dict) else {"invalid": True, "error": "状态根节点不是对象"}


def _process_is_running(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _process_command_line(pid: int) -> str | None:
    proc_cmdline = Path(f"/proc/{pid}/cmdline")
    try:
        raw = proc_cmdline.read_bytes()
        if raw:
            return " ".join(part.decode("utf-8", errors="replace") for part in raw.split(b"\0") if part)
    except OSError:
        pass
    try:
        result = subprocess.run(
            ["ps", "-ww", "-p", str(pid), "-o", "command="],
            check=False,
            capture_output=True,
            text=True,
            timeout=2,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    command = result.stdout.strip()
    return command or None


def _process_start_identity(pid: int) -> str | None:
    proc_stat = Path(f"/proc/{pid}/stat")
    try:
        fields = proc_stat.read_text(encoding="utf-8").split()
        if len(fields) > 21:
            return f"proc:{fields[21]}"
    except OSError:
        pass
    try:
        result = subprocess.run(
            ["ps", "-p", str(pid), "-o", "lstart="],
            check=False,
            capture_output=True,
            text=True,
            timeout=2,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    started = result.stdout.strip()
    return f"ps:{started}" if started else None


def _process_identity_matches(state: dict[str, Any]) -> bool:
    try:
        pid = int(state["pid"])
    except (KeyError, TypeError, ValueError):
        return False
    token = state.get("process_token")
    if not isinstance(token, str) or len(token) < 24:
        return False
    recorded_start = state.get("process_start")
    if recorded_start and _process_start_identity(pid) != recorded_start:
        return False
    command = _process_command_line(pid)
    if not command:
        return False
    return all(fragment in command for fragment in ("pixelcrew", "serve", "--process-token", token))


def _port_available(port: int) -> bool:
    if not 1 <= port <= 65535:
        return False
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            probe.bind((LOOPBACK_HOST, port))
        except OSError:
            return False
    return True


def _local_url(port: int) -> str:
    return f"http://{LOOPBACK_HOST}:{port}"


def _health(url: str, expected_token: str | None = None, timeout: float = 0.75) -> tuple[bool, str]:
    request = urllib.request.Request(f"{url}/api/status", headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            if response.status != 200:
                return False, f"HTTP {response.status}"
            response.read(1)
            if expected_token and response.headers.get("X-PixelCrew-Process-Token") != expected_token:
                return False, "端口响应不属于当前 PixelCrew 实例"
            return True, ""
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        return False, str(exc)


def _wait_for_health(url: str, pid: int, token: str, timeout: float) -> tuple[bool, str]:
    deadline = time.monotonic() + max(0.1, timeout)
    reason = "服务尚未响应"
    while time.monotonic() < deadline:
        if not _process_is_running(pid):
            return False, "服务进程已提前退出"
        healthy, reason = _health(url, token)
        if healthy:
            return True, ""
        time.sleep(0.1)
    return False, reason


def _state_url(state: dict[str, Any]) -> str | None:
    try:
        port = int(state["port"])
    except (KeyError, TypeError, ValueError):
        return None
    if not 1 <= port <= 65535:
        return None
    return _local_url(port)


def _print_running(state: dict[str, Any], state_path: Path) -> None:
    url = _state_url(state) or "本地 URL 无效"
    print("✓ PixelCrew 正在运行")
    print(f"  URL：{url}")
    print(f"  PID：{state.get('pid', '未知')}")
    print(f"  日志：{state.get('log', state_path.with_name(LOG_FILENAME))}")


def _stop_child(process: subprocess.Popen[Any], timeout: float = 5.0) -> bool:
    if process.poll() is not None:
        return True
    try:
        process.terminate()
        process.wait(timeout=max(0.1, timeout))
    except ProcessLookupError:
        return True
    except subprocess.TimeoutExpired:
        try:
            process.kill()
            process.wait(timeout=1.0)
        except (ProcessLookupError, subprocess.TimeoutExpired):
            pass
    return process.poll() is not None


def _command_start_impl(args: argparse.Namespace, foreground: dict[str, Any]) -> int:
    if foreground["received"]:
        return 128 + int(foreground["received"])
    try:
        config_path, _config, project_root, state_path, log_path = _lifecycle_context(args.config)
    except LifecycleConfigError as exc:
        print(f"✗ 配置错误：{exc}", file=sys.stderr)
        return STATUS_CONFIG_ERROR

    port = args.port
    if not 1 <= port <= 65535:
        print(f"✗ 配置错误：端口必须在 1–65535 之间，当前为 {port}。", file=sys.stderr)
        return STATUS_CONFIG_ERROR
    if not math.isfinite(args.timeout) or args.timeout <= 0:
        print("✗ 配置错误：--timeout 必须是大于 0 的有限秒数。", file=sys.stderr)
        return STATUS_CONFIG_ERROR

    runtime_dir = state_path.parent
    process: subprocess.Popen[Any] | None = None
    state: dict[str, Any] | None = None
    try:
        with _runtime_lock(runtime_dir):
            existing = _read_state(state_path)
            if existing and existing.get("invalid"):
                print(
                    f"✗ 配置错误：运行状态损坏或不安全：{state_path}（{existing.get('error', '未知原因')}）。",
                    file=sys.stderr,
                )
                print("  请先备份并修复该文件；PixelCrew 不会在身份未知时继续启动。", file=sys.stderr)
                return STATUS_CONFIG_ERROR
            if existing:
                try:
                    existing_pid = int(existing["pid"])
                except (KeyError, TypeError, ValueError):
                    existing_pid = 0
                if _process_is_running(existing_pid) and _process_identity_matches(existing):
                    try:
                        recorded_config = Path(str(existing.get("config", ""))).expanduser().resolve()
                    except (OSError, RuntimeError):
                        recorded_config = Path()
                    if recorded_config != config_path or existing.get("port") != port:
                        print("✗ 已有 PixelCrew 使用不同配置或端口运行；不会静默复用。", file=sys.stderr)
                        print(
                            f"  当前：config={existing.get('config', '未知')} port={existing.get('port', '未知')}",
                            file=sys.stderr,
                        )
                        print(f"  请求：config={config_path} port={port}", file=sys.stderr)
                        print(f"  请先运行：pixelcrew stop --config {config_path}", file=sys.stderr)
                        return STATUS_CONFIG_ERROR
                    url = _state_url(existing)
                    expected_token = existing.get("process_token")
                    healthy, reason = (
                        _health(url, expected_token) if url else (False, "状态文件中的端口无效")
                    )
                    if healthy:
                        print("PixelCrew 已启动；不会创建重复进程。")
                        _print_running(existing, state_path)
                        return STATUS_RUNNING
                    print(f"✗ PixelCrew 进程仍在，但服务不可达：{reason}", file=sys.stderr)
                    print(f"  请查看日志：{existing.get('log', log_path)}", file=sys.stderr)
                    print(f"  可运行：pixelcrew stop --config {config_path}", file=sys.stderr)
                    return STATUS_UNREACHABLE

            if not _port_available(port):
                print(f"✗ 端口冲突：{LOOPBACK_HOST}:{port} 已被占用。", file=sys.stderr)
                alternative = port + 1 if port < 65535 else port - 1
                print(
                    f"  请停止占用程序，或改用：pixelcrew start --port {alternative} --config {config_path}",
                    file=sys.stderr,
                )
                return STATUS_UNREACHABLE

            if foreground["received"]:
                return 128 + int(foreground["received"])
            token = secrets.token_urlsafe(24)
            url = _local_url(port)
            command = [
                sys.executable,
                "-m",
                "pixelcrew",
                "serve",
                "--config",
                str(config_path),
                "--host",
                LOOPBACK_HOST,
                "--port",
                str(port),
                "--process-token",
                token,
            ]
            child_environment = os.environ.copy()
            # Keep `python3 pixelcrew.py start` working from a source checkout. The
            # child changes cwd to the managed project, so it cannot otherwise import
            # this repository's src-layout package unless PixelCrew is installed.
            source_root = str(Path(__file__).resolve().parents[1])
            existing_pythonpath = child_environment.get("PYTHONPATH")
            child_environment["PYTHONPATH"] = (
                os.pathsep.join((source_root, existing_pythonpath)) if existing_pythonpath else source_root
            )
            log_descriptor = _safe_open(log_path, os.O_WRONLY | os.O_CREAT | os.O_APPEND)
            with os.fdopen(log_descriptor, "ab", buffering=0) as log_handle:
                try:
                    process = subprocess.Popen(
                        command,
                        cwd=project_root,
                        stdin=subprocess.DEVNULL,
                        stdout=log_handle,
                        stderr=subprocess.STDOUT,
                        start_new_session=not args.foreground,
                        close_fds=True,
                        env=child_environment,
                    )
                except OSError as exc:
                    print(f"✗ 无法启动 PixelCrew：{exc}", file=sys.stderr)
                    return STATUS_UNREACHABLE
            foreground["process"] = process
            if foreground["received"]:
                _stop_child(process)
                return 128 + int(foreground["received"])

            state = {
                "schema_version": 1,
                "status": "starting",
                "pid": process.pid,
                "process_token": token,
                "process_start": _process_start_identity(process.pid),
                "config": str(config_path),
                "project_root": str(project_root),
                "host": LOOPBACK_HOST,
                "port": port,
                "url": url,
                "log": str(log_path),
                "started_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            }
            try:
                _atomic_write_json(state_path, state)
            except (OSError, LifecycleConfigError) as exc:
                _stop_child(process)
                print(f"✗ 无法发布 PixelCrew 运行状态，已回收子进程：{exc}", file=sys.stderr)
                return STATUS_CONFIG_ERROR

            healthy, reason = _wait_for_health(url, process.pid, token, args.timeout)
            if not healthy:
                interrupted_during_start = bool(foreground["received"])
                state["status"] = "stopped" if interrupted_during_start else (
                    "unreachable" if _process_is_running(process.pid) else "exited"
                )
                state["last_error"] = reason
                try:
                    _atomic_write_json(state_path, state)
                except (OSError, LifecycleConfigError) as exc:
                    _stop_child(process)
                    print(f"✗ 无法保存失败状态，已回收子进程：{exc}", file=sys.stderr)
                if interrupted_during_start:
                    _stop_child(process)
                    return 128 + int(foreground["received"])
                print(f"✗ 服务未能在 {args.timeout:g} 秒内就绪：{reason}", file=sys.stderr)
                print(f"  PID：{process.pid}", file=sys.stderr)
                print(f"  日志：{log_path}", file=sys.stderr)
                return STATUS_UNREACHABLE

            if foreground["received"]:
                _stop_child(process)
                state["status"] = "stopped"
                state["stopped_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
                _atomic_write_json(state_path, state)
                return 128 + int(foreground["received"])
            state["status"] = "running"
            state["ready_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
            try:
                _atomic_write_json(state_path, state)
            except (OSError, LifecycleConfigError) as exc:
                _stop_child(process)
                print(f"✗ 无法确认 PixelCrew 运行状态，已回收子进程：{exc}", file=sys.stderr)
                return STATUS_CONFIG_ERROR
    except LifecycleConfigError as exc:
        print(f"✗ 配置错误：{exc}", file=sys.stderr)
        return STATUS_CONFIG_ERROR

    assert process is not None and state is not None
    _print_running(state, state_path)
    if not args.foreground:
        return STATUS_RUNNING

    print("前台模式运行中；按 Ctrl-C 停止。")
    interrupted = False
    try:
        exit_code = process.wait()
        if foreground["received"]:
            interrupted = True
            exit_code = 128 + int(foreground["received"])
    except KeyboardInterrupt:
        interrupted = True
        stopped = _stop_child(process)
        exit_code = 128 + signal.SIGINT if stopped else STATUS_UNREACHABLE

    try:
        with _runtime_lock(runtime_dir):
            current = _read_state(state_path)
            if current and current.get("process_token") == state["process_token"]:
                state["status"] = "stopped" if interrupted else "exited"
                state["exit_code"] = exit_code
                state["exited_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
                _atomic_write_json(state_path, state)
    except (OSError, LifecycleConfigError) as exc:
        print(f"! 无法保存前台退出状态：{exc}", file=sys.stderr)
    return exit_code


def command_start(args: argparse.Namespace) -> int:
    foreground: dict[str, Any] = {"received": 0, "process": None}
    previous_sigterm: Any = None
    if args.foreground:
        def handle_termination(signum: int, _frame: Any) -> None:
            foreground["received"] = signum
            process = foreground.get("process")
            if process is not None and process.poll() is None:
                try:
                    process.terminate()
                except ProcessLookupError:
                    pass

        previous_sigterm = signal.signal(signal.SIGTERM, handle_termination)
    try:
        return _command_start_impl(args, foreground)
    finally:
        if args.foreground:
            signal.signal(signal.SIGTERM, previous_sigterm)


def command_status(args: argparse.Namespace) -> int:
    try:
        config_path, _config, _project_root, state_path, log_path = _lifecycle_context(args.config)
    except LifecycleConfigError as exc:
        print(f"✗ 配置错误：{exc}", file=sys.stderr)
        return STATUS_CONFIG_ERROR
    state = _read_state(state_path)
    if not state:
        print("○ PixelCrew 已退出：尚未找到本项目的运行状态。")
        print(f"  启动：pixelcrew start --config {config_path}")
        return STATUS_EXITED
    if state.get("invalid"):
        print(
            f"✗ 配置错误：状态文件损坏或不安全：{state_path}（{state.get('error', '未知原因')}）。",
            file=sys.stderr,
        )
        return STATUS_CONFIG_ERROR
    try:
        pid = int(state["pid"])
    except (KeyError, TypeError, ValueError):
        print(f"○ PixelCrew 已退出：状态文件缺少有效 PID：{state_path}", file=sys.stderr)
        return STATUS_EXITED
    if not _process_is_running(pid):
        print(f"○ PixelCrew 已退出（最后记录 PID {pid}）。")
        print(f"  日志：{state.get('log', log_path)}")
        return STATUS_EXITED
    if not _process_identity_matches(state):
        print(f"○ PixelCrew 已退出：PID {pid} 当前不是可验证的 PixelCrew 服务；不会对其执行操作。", file=sys.stderr)
        return STATUS_EXITED
    url = _state_url(state)
    if not url:
        print("✗ 服务不可达：状态中的本地端口无效。", file=sys.stderr)
        return STATUS_UNREACHABLE
    healthy, reason = _health(url, state.get("process_token"))
    if not healthy:
        print(f"✗ PixelCrew 服务不可达：进程 {pid} 存活，但 /api/status 无响应（{reason}）。", file=sys.stderr)
        print(f"  日志：{state.get('log', log_path)}", file=sys.stderr)
        return STATUS_UNREACHABLE
    _print_running(state, state_path)
    return STATUS_RUNNING


def command_open(args: argparse.Namespace) -> int:
    try:
        _config_path, _config, _project_root, state_path, _log_path = _lifecycle_context(args.config)
    except LifecycleConfigError as exc:
        print(f"✗ 配置错误：{exc}", file=sys.stderr)
        return STATUS_CONFIG_ERROR
    state = _read_state(state_path)
    if not state:
        print("✗ PixelCrew 未运行；请先执行 pixelcrew start。", file=sys.stderr)
        return STATUS_EXITED
    if state.get("invalid"):
        print(f"✗ 配置错误：状态文件损坏或不安全：{state_path}。", file=sys.stderr)
        return STATUS_CONFIG_ERROR
    try:
        pid = int(state["pid"])
    except (KeyError, TypeError, ValueError):
        pid = 0
    url = _state_url(state)
    if not _process_is_running(pid) or not _process_identity_matches(state) or not url:
        print("✗ PixelCrew 未运行或进程身份无法验证；不会打开页面。", file=sys.stderr)
        return STATUS_EXITED
    parsed = urlparse(url)
    if parsed.scheme != "http" or parsed.hostname != LOOPBACK_HOST:
        print("✗ 拒绝打开非本地 URL。", file=sys.stderr)
        return STATUS_CONFIG_ERROR
    healthy, reason = _health(url, state.get("process_token"))
    if not healthy:
        print(f"✗ PixelCrew 服务不可达：{reason}", file=sys.stderr)
        return STATUS_UNREACHABLE
    try:
        opened = webbrowser.open(url)
    except (OSError, webbrowser.Error) as exc:
        print(f"! 无法自动打开浏览器（{exc}），请手动访问：{url}", file=sys.stderr)
        return STATUS_UNREACHABLE
    if not opened:
        print(f"! 无法自动打开浏览器，请手动访问：{url}", file=sys.stderr)
        return STATUS_UNREACHABLE
    print(f"✓ 已打开：{url}")
    return STATUS_RUNNING


def command_stop(args: argparse.Namespace) -> int:
    try:
        _config_path, _config, _project_root, state_path, log_path = _lifecycle_context(args.config)
    except LifecycleConfigError as exc:
        print(f"✗ 配置错误：{exc}", file=sys.stderr)
        return STATUS_CONFIG_ERROR
    if not math.isfinite(args.timeout) or args.timeout <= 0:
        print("✗ 配置错误：--timeout 必须是大于 0 的有限秒数。", file=sys.stderr)
        return STATUS_CONFIG_ERROR

    try:
        with _runtime_lock(state_path.parent):
            state = _read_state(state_path)
            if not state:
                print("○ PixelCrew 已退出：没有可停止的已记录服务。")
                return STATUS_EXITED
            if state.get("invalid"):
                print(f"✗ 配置错误：状态文件损坏或不安全：{state_path}。", file=sys.stderr)
                return STATUS_CONFIG_ERROR
            try:
                pid = int(state["pid"])
            except (KeyError, TypeError, ValueError):
                print("✗ 状态文件没有有效 PID；为安全起见未终止任何进程。", file=sys.stderr)
                return STATUS_EXITED
            if not _process_is_running(pid):
                print(f"○ PixelCrew 已退出（最后记录 PID {pid}）。")
                return STATUS_EXITED
            if not _process_identity_matches(state):
                print(
                    f"✗ 拒绝停止 PID {pid}：它与状态文件记录的 PixelCrew 命令身份不匹配。未终止任何进程。",
                    file=sys.stderr,
                )
                return STATUS_EXITED

            try:
                os.kill(pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            except OSError as exc:
                print(f"✗ 无法停止 PixelCrew PID {pid}：{exc}", file=sys.stderr)
                return STATUS_UNREACHABLE
            deadline = time.monotonic() + args.timeout
            while _process_is_running(pid) and time.monotonic() < deadline:
                time.sleep(0.1)
            if _process_is_running(pid):
                if not _process_identity_matches(state):
                    print("✗ 等待期间进程身份发生变化；为安全起见不发送强制终止信号。", file=sys.stderr)
                    return STATUS_UNREACHABLE
                try:
                    os.kill(pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                except OSError as exc:
                    print(f"✗ 无法强制停止 PixelCrew PID {pid}：{exc}", file=sys.stderr)
                    return STATUS_UNREACHABLE
                kill_deadline = time.monotonic() + 1.0
                while _process_is_running(pid) and time.monotonic() < kill_deadline:
                    time.sleep(0.05)
                if _process_is_running(pid):
                    print(f"✗ 已发送 SIGKILL，但无法确认 PID {pid} 已退出。", file=sys.stderr)
                    return STATUS_UNREACHABLE
            state["status"] = "stopped"
            state["stopped_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
            _atomic_write_json(state_path, state)
    except (OSError, LifecycleConfigError) as exc:
        print(f"✗ 配置错误：{exc}", file=sys.stderr)
        return STATUS_CONFIG_ERROR

    print(f"✓ PixelCrew 已停止（PID {pid}）。")
    print(f"  日志保留在：{state.get('log', log_path)}")
    return STATUS_RUNNING


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="pixelcrew", description="A live pixel office for Codex projects")
    sub = parser.add_subparsers(dest="command", required=True)

    init = sub.add_parser("init", help="为一个项目生成本地配置")
    init.add_argument("project_root", type=Path)
    init.add_argument("--name")
    init.add_argument("--manager-thread-id", default="")
    init.add_argument("--output", type=Path, default=Path("pixelcrew.json"))
    init.add_argument("--force", action="store_true")
    init.set_defaults(func=command_init)

    doctor = sub.add_parser("doctor", help="检查 Codex 数据与办公室接入")
    doctor.add_argument("--config", type=Path, default=Path("pixelcrew.json"))
    doctor.set_defaults(func=command_doctor)

    snapshot = sub.add_parser("snapshot", help="输出当前结构化项目快照")
    snapshot.add_argument("--config", type=Path, default=Path("pixelcrew.json"))
    snapshot.set_defaults(func=command_snapshot)

    serve = sub.add_parser("serve", help="兼容入口：以前台方式启动本地只读办公室")
    serve.add_argument("--config", type=Path, default=Path("pixelcrew.json"))
    serve.add_argument("--host", default=LOOPBACK_HOST)
    serve.add_argument("--port", type=int, default=DEFAULT_PORT)
    serve.add_argument("--process-token", help=argparse.SUPPRESS)
    serve.set_defaults(func=None)

    start = sub.add_parser("start", help="稳定启动本地办公室（默认后台）")
    start.add_argument("--config", type=Path, default=Path("pixelcrew.json"))
    start.add_argument("--port", type=int, default=DEFAULT_PORT)
    start.add_argument("--timeout", type=float, default=15.0, help="等待 /api/status 就绪的秒数")
    start.add_argument("--foreground", action="store_true", help="保持命令在前台，Ctrl-C 停止")
    start.set_defaults(func=command_start)

    status = sub.add_parser("status", help="检查配置、进程身份和服务健康状态")
    status.add_argument("--config", type=Path, default=Path("pixelcrew.json"))
    status.set_defaults(func=command_status)

    open_command = sub.add_parser("open", help="在浏览器打开正在运行的本地办公室")
    open_command.add_argument("--config", type=Path, default=Path("pixelcrew.json"))
    open_command.set_defaults(func=command_open)

    stop = sub.add_parser("stop", help="安全停止本项目记录的 PixelCrew 服务")
    stop.add_argument("--config", type=Path, default=Path("pixelcrew.json"))
    stop.add_argument("--timeout", type=float, default=5.0, help="发送 SIGTERM 后的等待秒数")
    stop.set_defaults(func=command_stop)

    secretary = sub.add_parser("secretary", help="用现有 Codex 登录生成跨任务 AI 简报")
    secretary.add_argument("--config", type=Path, default=Path("pixelcrew.json"))
    secretary.add_argument("--codex", help="Codex CLI 可执行文件路径")
    secretary.add_argument("--output", type=Path)
    secretary.add_argument("--timeout", type=int, default=180)
    secretary.add_argument("--watch", action="store_true", help="持续值班并定时刷新")
    secretary.add_argument("--interval", type=int, default=900, help="值班刷新秒数，最少 60")
    secretary.add_argument("--dry-run", action="store_true", help="只显示脱敏后的秘书输入，不调用模型")
    secretary.set_defaults(func=command_secretary)
    return parser


def main(argv: list[str] | None = None) -> None:
    argv = list(sys.argv[1:] if argv is None else argv)
    # v0.2 compatibility: `pixelcrew --config ... --snapshot` still works.
    commands = {"init", "doctor", "snapshot", "serve", "start", "status", "open", "stop", "secretary"}
    if argv and argv[0] not in commands and argv[0] not in {"-h", "--help"}:
        legacy_server_main(argv)
        return
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "serve":
            serve_arguments = ["--config", str(args.config), "--host", args.host, "--port", str(args.port)]
            if args.process_token:
                serve_arguments.extend(["--process-token", args.process_token])
            legacy_server_main(serve_arguments)
            return
        raise SystemExit(args.func(args))
    except RuntimeError as exc:
        parser.exit(1, f"PixelCrew: {exc}\n")

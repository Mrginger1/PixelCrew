"""Command-line interface for creating and running a PixelCrew office."""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from .secretary import run_codex_secretary, secretary_prompt
from .server import DEFAULT_WEB_DIR, Dashboard, load_config, main as legacy_server_main


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

    serve = sub.add_parser("serve", help="启动本地只读办公室")
    serve.add_argument("--config", type=Path, default=Path("pixelcrew.json"))
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8765)
    serve.set_defaults(func=None)

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
    commands = {"init", "doctor", "snapshot", "serve", "secretary"}
    if argv and argv[0] not in commands and argv[0] not in {"-h", "--help"}:
        legacy_server_main(argv)
        return
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "serve":
            legacy_server_main(["--config", str(args.config), "--host", args.host, "--port", str(args.port)])
            return
        raise SystemExit(args.func(args))
    except RuntimeError as exc:
        parser.exit(1, f"PixelCrew: {exc}\n")

"""Read-only Codex project status collector and local dashboard server."""
from __future__ import annotations

import argparse
import json
import mimetypes
import os
import re
import sqlite3
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

PACKAGE_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_WEB_DIR = PACKAGE_ROOT / "web"
DEFAULT_CODEX_HOME = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))

PALETTES = [
    ("#4c8064", "#26364b", "#46765e", "#dcb34c"),
    ("#c18635", "#6d4638", "#c08536", "#5d7994"),
    ("#b95348", "#31495b", "#a95249", "#d7b650"),
    ("#527895", "#4b3f59", "#527895", "#d69a48"),
    ("#7567a1", "#39485d", "#7567a1", "#d4a85a"),
    ("#5f8b7b", "#4f3e36", "#5f8b7b", "#d7ae58"),
]
SLOTS = [
    {"x": 320, "y": 254}, {"x": 147, "y": 195}, {"x": 493, "y": 195},
    {"x": 548, "y": 337}, {"x": 105, "y": 337}, {"x": 320, "y": 116},
]
GOOD_SUFFIXES = {
    ".pt": "model", ".pth": "model", ".ckpt": "model", ".onnx": "model",
    ".npy": "data", ".npz": "data", ".csv": "data", ".parquet": "data",
    ".json": "report", ".md": "report", ".html": "report", ".pdf": "report",
    ".mp4": "video", ".mov": "video", ".webm": "video", ".gif": "video",
    ".png": "image", ".jpg": "image", ".jpeg": "image", ".svg": "image",
}
DEFAULT_IGNORES = ["/tmp/", "/.cache/", "/node_modules/", "/site-packages/", "/.codex/skills/", "/.codex/plugins/"]


def load_config(path: Path) -> dict[str, Any]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    project = raw.setdefault("project", {})
    project.setdefault("name", path.parent.name or "New Project")
    project.setdefault("subtitle", "负责人统筹 · 子任务并行 · 统一验收")
    root = Path(project.get("root") or path.parent).expanduser().resolve()
    project["root"] = str(root)
    discovery = raw.setdefault("discovery", {})
    discovery.setdefault("workspace_match", str(root))
    discovery.setdefault("include_archived", False)
    discovery.setdefault("title_keywords", [])
    discovery.setdefault("exclude_title_patterns", [])
    raw.setdefault("roles", {})
    artifacts = raw.setdefault("artifacts", {})
    artifacts.setdefault("allowed_roots", [str(root)])
    artifacts.setdefault("remote_prefixes", ["/home/", "/workspace/"])
    artifacts.setdefault("ignore_contains", DEFAULT_IGNORES)
    artifacts.setdefault("max_per_task", 8)
    codex = raw.setdefault("codex", {})
    codex_home = Path(codex.get("home") or DEFAULT_CODEX_HOME).expanduser()
    codex["home"] = str(codex_home)
    codex.setdefault("state_db", str(codex_home / "state_5.sqlite"))
    codex.setdefault("session_index", str(codex_home / "session_index.jsonl"))
    return raw


def read_json_lines(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                try:
                    rows.append(json.loads(line))
                except (json.JSONDecodeError, ValueError):
                    continue
    except OSError:
        pass
    return rows


def session_names(path: Path) -> dict[str, str]:
    return {
        str(row["id"]): str(row["thread_name"])
        for row in read_json_lines(path)
        if row.get("id") and row.get("thread_name")
    }


def clean_markdown(text: str, limit: int = 150) -> str:
    text = re.sub(r"```.*?```", " ", text, flags=re.S)
    text = re.sub(r"`([^`]+)`", r"\1", text)
    text = re.sub(r"(\*\*|__)(.*?)\1", r"\2", text)
    text = re.sub(r"\[([^]]+)]\([^)]*\)", r"\1", text)
    text = re.sub(r"^[#>*+\-\d.\s]+", "", text, flags=re.M)
    text = re.sub(r"\s+", " ", text).strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip("，。；： ") + "…"


def extract_paths(text: str) -> list[str]:
    quoted = re.findall(r"[\"'`](/[^\n\r\"'`]+)[\"'`]", text)
    plain = re.findall(r"(?<![\w.-])(/(?:Users|home|workspace|Volumes)/[^\s`'\"，。；：)\]}]+)", text)
    cleaned: list[str] = []
    for value in quoted + plain:
        value = re.split(r"\\[nrt]|[\n\r\t|;&]", value, maxsplit=1)[0]
        value = re.sub(r":\d+(?::.*)?$", "", value).rstrip(".,;:)")
        if value and not any(char in value for char in "{}*<>"):
            cleaned.append(value)
    return cleaned


def extract_rollout(path: Path) -> dict[str, Any]:
    latest_plan: list[dict[str, str]] = []
    explanation = ""
    final_message = ""
    agent_message = ""
    last_kind = ""
    paths: list[str] = []
    wandb_urls: list[str] = []
    for row in read_json_lines(path):
        payload = row.get("payload") or {}
        typ = str(payload.get("type") or "")
        last_kind = typ or last_kind
        if typ == "function_call" and payload.get("name") == "update_plan":
            try:
                args = json.loads(payload.get("arguments") or "{}")
                latest_plan = args.get("plan") or latest_plan
                explanation = args.get("explanation") or explanation
            except (json.JSONDecodeError, TypeError):
                pass
        elif typ == "message" and payload.get("role") == "assistant":
            parts = [
                str(item.get("text", "")) for item in (payload.get("content") or [])
                if item.get("type") in {"output_text", "text"}
            ]
            if parts:
                final_message = "\n".join(parts)
        elif typ == "agent_message":
            agent_message = str(payload.get("message") or agent_message)
        elif typ == "task_complete":
            agent_message = str(payload.get("last_agent_message") or agent_message)
        blob = " ".join(str(v) for v in payload.values() if isinstance(v, str))
        if blob:
            paths.extend(extract_paths(blob))
            wandb_urls.extend(re.findall(r"https?://(?:www\.)?wandb\.ai/[^\s`'\"，。)]+", blob, flags=re.I))
    message = agent_message or final_message
    return {
        "plan": latest_plan,
        "explanation": explanation,
        "message": message,
        "bubble": clean_markdown(explanation or message, 72),
        "summary": clean_markdown(message, 320),
        "paths": list(dict.fromkeys(paths)),
        "wandb": list(dict.fromkeys(wandb_urls))[-5:],
        "last_kind": last_kind,
    }


def infer_state(archived: int, updated_at: int, rollout: dict[str, Any]) -> tuple[str, str]:
    statuses = [str(item.get("status", "")) for item in rollout.get("plan") or []]
    text = f"{rollout.get('explanation', '')} {rollout.get('message', '')}".lower()
    age = time.time() - updated_at
    if archived:
        return "archived", "已归档"
    if statuses and all(status == "completed" for status in statuses):
        return "complete", "已完成"
    if any(word in text for word in ("blocked", "阻塞", "无法继续", "等待用户", "need input")):
        return "blocked", "需要处理"
    if any(word in text for word in ("等待 gpu", "等待可用", "安全等待", "waiting", "queue", "等待交付")):
        return "waiting", "等待资源"
    if age < 15 * 60 and rollout.get("last_kind") != "task_complete":
        return "active", "工作中"
    if statuses and "in_progress" in statuses:
        return "active", "推进中"
    if age > 24 * 3600:
        return "stale", "待跟进"
    return "idle", "已汇报"


def plan_progress(plan: list[dict[str, Any]], state: str) -> int:
    if not plan:
        return 100 if state == "complete" else 15 if state == "blocked" else 35
    weights = {"completed": 1.0, "in_progress": 0.55, "pending": 0.0}
    score = sum(weights.get(str(item.get("status")), 0.0) for item in plan)
    return max(3, min(100, round(100 * score / len(plan))))


def role_for(config: dict[str, Any], thread_id: str, title: str, index: int) -> tuple[str, str, str]:
    manager_id = str(config["project"].get("manager_thread_id") or "")
    role = (config.get("roles") or {}).get(thread_id) or {}
    if thread_id == manager_id:
        return "lead", role.get("name", "总负责人"), role.get("assignment", "项目规划、协调与统一验收")
    if role:
        return role.get("id", f"staff-{index + 1}"), role.get("name", title[:14]), role.get("assignment", title)
    return f"staff-{index + 1}", title[:14] or f"任务成员 {index + 1}", title


def path_artifacts(config: dict[str, Any], values: list[str]) -> list[dict[str, Any]]:
    settings = config["artifacts"]
    ignores = tuple(settings.get("ignore_contains") or [])
    remote_prefixes = tuple(settings.get("remote_prefixes") or [])
    allowed_roots = [str(Path(p).expanduser()) for p in settings.get("allowed_roots") or []]
    result: list[dict[str, Any]] = []
    unique_values = list(dict.fromkeys(values))[-120:]
    for recency, value in enumerate(unique_values):
        if any(ignore in value for ignore in ignores):
            continue
        remote = value.startswith(remote_prefixes)
        local_allowed = any(value == root or value.startswith(root.rstrip("/") + "/") for root in allowed_roots)
        if not remote and not local_allowed:
            continue
        suffix = Path(value).suffix.lower()
        exists = None if remote else Path(value).exists()
        if not suffix:
            kind, priority = "folder", 2
        else:
            kind = GOOD_SUFFIXES.get(suffix, "file")
            priority = 4 if kind in {"model", "video"} else 3 if kind in {"report", "data", "image"} else 1
        result.append({"label": Path(value).name or value, "path": value, "kind": kind, "remote": remote, "exists": exists, "priority": priority, "recency": recency})
    result.sort(key=lambda item: (item["recency"], item["priority"], bool(item["exists"])), reverse=True)
    return result[: int(settings.get("max_per_task", 8))]


class Dashboard:
    def __init__(self, config: dict[str, Any]):
        self.config = config

    def _rows(self) -> list[sqlite3.Row]:
        db = Path(self.config["codex"]["state_db"]).expanduser()
        conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=2)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """SELECT id, rollout_path, updated_at, cwd, archived, title
               FROM threads WHERE thread_source='user' ORDER BY updated_at DESC"""
        ).fetchall()
        conn.close()
        discovery = self.config["discovery"]
        marker = str(discovery.get("workspace_match") or "")
        keywords = [str(k).lower() for k in discovery.get("title_keywords") or []]
        excludes = [re.compile(str(p), re.I) for p in discovery.get("exclude_title_patterns") or []]
        output: list[sqlite3.Row] = []
        for row in rows:
            title, cwd = str(row["title"] or ""), str(row["cwd"] or "")
            if marker and marker not in cwd:
                continue
            if keywords and not any(keyword in title.lower() for keyword in keywords):
                continue
            if any(pattern.search(title) for pattern in excludes):
                continue
            if row["archived"] and not discovery.get("include_archived"):
                continue
            output.append(row)
        return output

    def snapshot(self) -> dict[str, Any]:
        names = session_names(Path(self.config["codex"]["session_index"]).expanduser())
        rows = self._rows()
        manager_id = str(self.config["project"].get("manager_thread_id") or "")
        rows.sort(key=lambda row: (0 if str(row["id"]) == manager_id else 1, -int(row["updated_at"])))
        employees: list[dict[str, Any]] = []
        artifacts: list[dict[str, Any]] = []
        for index, row in enumerate(rows):
            thread_id = str(row["id"])
            title = names.get(thread_id, str(row["title"] or "").splitlines()[0])
            rollout = extract_rollout(Path(row["rollout_path"]))
            status, status_label = infer_state(int(row["archived"]), int(row["updated_at"]), rollout)
            role_id, name, default_assignment = role_for(self.config, thread_id, title, index)
            plan = rollout.get("plan") or []
            current = next((p.get("step") for p in plan if p.get("status") == "in_progress"), None)
            current = current or next((p.get("step") for p in plan if p.get("status") == "pending"), default_assignment)
            owned = path_artifacts(self.config, rollout.get("paths") or [])
            artifacts.extend({**item, "owner": name} for item in owned)
            palette = PALETTES[index % len(PALETTES)]
            employees.append({
                "id": role_id, "threadId": thread_id, "name": name, "title": title,
                "assignment": clean_markdown(str(current), 76), "status": status, "statusLabel": status_label,
                "progress": plan_progress(plan, status),
                "bubble": rollout.get("bubble") or "正在整理当前任务进展…",
                "summary": rollout.get("summary") or "暂无最新文字汇报。",
                "plan": plan, "artifacts": owned, "wandb": rollout.get("wandb") or [],
                "updatedAt": datetime.fromtimestamp(int(row["updated_at"])).astimezone().isoformat(timespec="seconds"),
                "updatedLabel": datetime.fromtimestamp(int(row["updated_at"])).strftime("%m-%d %H:%M"),
                "color": palette[0], "hair": palette[1], "shirt": palette[2], "accent": palette[3],
                "slot": SLOTS[index % len(SLOTS)], "floor": index // len(SLOTS),
            })
        states = ("active", "waiting", "blocked", "complete", "idle", "stale", "archived")
        return {
            "generatedAt": datetime.now().astimezone().isoformat(timespec="seconds"),
            "generatedLabel": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "source": "Codex 本地任务记录（只读）",
            "project": {k: v for k, v in self.config["project"].items() if k not in {"root", "manager_thread_id"}},
            "employees": employees,
            "counts": {state: sum(1 for e in employees if e["status"] == state) for state in states},
            "artifacts": artifacts[:30],
        }


def make_handler(dashboard: Dashboard, web_dir: Path):
    class Handler(BaseHTTPRequestHandler):
        server_version = "PixelCrew/1.0"

        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            if parsed.path == "/api/status":
                try:
                    payload = json.dumps(dashboard.snapshot(), ensure_ascii=False).encode("utf-8")
                    self._send(200, "application/json; charset=utf-8", payload)
                except Exception as exc:
                    payload = json.dumps({"error": str(exc)}, ensure_ascii=False).encode("utf-8")
                    self._send(500, "application/json; charset=utf-8", payload)
                return
            target = "index.html" if parsed.path in {"", "/"} else unquote(parsed.path.lstrip("/"))
            path = (web_dir / target).resolve()
            if web_dir.resolve() not in path.parents and path != web_dir.resolve():
                self.send_error(403)
                return
            if not path.is_file():
                self.send_error(404)
                return
            self._send(200, mimetypes.guess_type(path.name)[0] or "application/octet-stream", path.read_bytes())

        def _send(self, status: int, content_type: str, body: bytes) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, fmt: str, *args: Any) -> None:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] {fmt % args}")

    return Handler


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Pixel office dashboard for Codex project tasks")
    parser.add_argument("--config", type=Path, default=Path("pixelcrew.json"))
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--snapshot", action="store_true")
    args = parser.parse_args(argv)
    config = load_config(args.config.resolve())
    dashboard = Dashboard(config)
    if args.snapshot:
        print(json.dumps(dashboard.snapshot(), ensure_ascii=False, indent=2))
        return
    server = ThreadingHTTPServer((args.host, args.port), make_handler(dashboard, DEFAULT_WEB_DIR))
    print(f"PixelCrew: http://{args.host}:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()

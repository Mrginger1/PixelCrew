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

from .secretary import build_secretary

PACKAGE_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_WEB_DIR = Path(__file__).resolve().parent / "web"
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
    secretary = raw.setdefault("secretary", {})
    secretary.setdefault("enabled", True)
    secretary.setdefault("cache", str(root / ".pixelcrew" / "secretary.json"))
    secretary.setdefault("max_age_minutes", 180)
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


def _timestamp_label(value: str) -> str:
    """Render rollout ISO timestamps in the machine's local timezone."""
    try:
        moment = datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone()
        return moment.strftime("%m-%d %H:%M")
    except (TypeError, ValueError):
        return "时间未知"


def _stage_kind(text: str, completed: list[str]) -> str:
    lowered = text.lower()
    decision_words = ("决定", "选择", "改为", "转为", "采用", "确认", "decision", "switch", "choose")
    if any(word in lowered for word in decision_words):
        return "decision"
    if completed:
        return "milestone"
    return "checkpoint"


def _stage_report(
    timestamp: str,
    explanation: str,
    plan: list[dict[str, Any]],
    previous_plan: list[dict[str, Any]],
    sequence: int,
) -> dict[str, Any]:
    old_completed = {
        str(item.get("step")) for item in previous_plan if item.get("status") == "completed"
    }
    completed = [
        str(item.get("step")) for item in plan
        if item.get("status") == "completed" and str(item.get("step")) not in old_completed
    ]
    current = next((str(item.get("step")) for item in plan if item.get("status") == "in_progress"), "")
    pending = sum(1 for item in plan if item.get("status") == "pending")
    previous_progress = plan_progress(previous_plan, "active") if previous_plan else 0
    progress = plan_progress(plan, "active")
    delta = max(0, progress - previous_progress)
    if explanation:
        headline = clean_markdown(explanation, 92)
        summary = clean_markdown(explanation, 280)
    elif completed:
        headline = f"完成 {completed[-1]}"
        summary = "本阶段完成：" + "、".join(completed[-3:])
    elif current:
        headline = f"进入 {current}"
        summary = f"计划已更新，当前推进：{current}"
    else:
        headline, summary = "计划检查点", "任务计划已更新。"
    return {
        "id": f"stage-{sequence}",
        "timestamp": timestamp,
        "updatedLabel": _timestamp_label(timestamp),
        "headline": headline,
        "summary": summary,
        "kind": _stage_kind(explanation, completed),
        "progress": progress,
        "delta": delta,
        "completed": completed[-4:],
        "current": current,
        "pending": pending,
    }


def extract_rollout(path: Path) -> dict[str, Any]:
    latest_plan: list[dict[str, str]] = []
    explanation = ""
    final_message = ""
    agent_message = ""
    last_kind = ""
    paths: list[str] = []
    wandb_urls: list[str] = []
    stage_reports: list[dict[str, Any]] = []
    previous_plan: list[dict[str, Any]] = []
    for row in read_json_lines(path):
        payload = row.get("payload") or {}
        typ = str(payload.get("type") or "")
        timestamp = str(row.get("timestamp") or "")
        last_kind = typ or last_kind
        if typ == "function_call" and payload.get("name") == "update_plan":
            try:
                args = json.loads(payload.get("arguments") or "{}")
                candidate = args.get("plan") or latest_plan
                note = str(args.get("explanation") or "")
                changed = candidate != latest_plan
                if candidate and (changed or note):
                    report = _stage_report(timestamp, note, candidate, previous_plan or latest_plan, len(stage_reports) + 1)
                    signature = (report["headline"], report["progress"], report["current"])
                    if not stage_reports or signature != (
                        stage_reports[-1]["headline"], stage_reports[-1]["progress"], stage_reports[-1]["current"]
                    ):
                        stage_reports.append(report)
                    previous_plan = [dict(item) for item in candidate]
                latest_plan = candidate
                explanation = note or explanation
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
        "stageReports": stage_reports[-10:],
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


def _is_fresh(iso_value: str, hours: int = 24) -> bool:
    try:
        value = datetime.fromisoformat(iso_value)
        return (datetime.now().astimezone() - value).total_seconds() <= hours * 3600
    except (TypeError, ValueError):
        return False


def build_insights(employees: list[dict[str, Any]]) -> dict[str, Any]:
    """Build deterministic portfolio-level signals without inventing project facts."""
    count = len(employees)
    plans = [item for employee in employees for item in employee.get("plan") or []]
    completed_steps = sum(1 for item in plans if item.get("status") == "completed")
    active_steps = sum(1 for item in plans if item.get("status") == "in_progress")
    pending_steps = sum(1 for item in plans if item.get("status") == "pending")
    progress = round(sum(employee.get("progress", 0) for employee in employees) / count) if count else 0
    evidence_count = sum(bool(employee.get("artifacts")) for employee in employees)
    reporting_count = sum(bool(employee.get("stageReports")) for employee in employees)
    fresh_count = sum(_is_fresh(str(employee.get("updatedAt") or "")) for employee in employees)
    coverage = lambda value: round(value * 100 / count) if count else 0

    attention: list[dict[str, str]] = []
    for employee in employees:
        status = str(employee.get("status") or "idle")
        if status == "blocked":
            attention.append({"level": "high", "owner": employee["name"], "reason": "任务已阻塞，需要负责人处理", "taskId": employee["id"]})
        elif status == "stale":
            attention.append({"level": "medium", "owner": employee["name"], "reason": "超过 24 小时没有新汇报", "taskId": employee["id"]})
        elif status == "waiting":
            attention.append({"level": "low", "owner": employee["name"], "reason": "正在等待外部资源或交付", "taskId": employee["id"]})
        if employee.get("status") == "complete" and not employee.get("artifacts"):
            attention.append({"level": "medium", "owner": employee["name"], "reason": "任务已完成，但尚未识别到成果证据", "taskId": employee["id"]})
        if not employee.get("plan"):
            attention.append({"level": "low", "owner": employee["name"], "reason": "尚未建立结构化任务计划", "taskId": employee["id"]})
    rank = {"high": 0, "medium": 1, "low": 2}
    attention.sort(key=lambda item: rank[item["level"]])

    blocked = sum(employee.get("status") == "blocked" for employee in employees)
    stale = sum(employee.get("status") == "stale" for employee in employees)
    active = sum(employee.get("status") == "active" for employee in employees)
    waiting = sum(employee.get("status") == "waiting" for employee in employees)
    briefing = (
        f"{count} 个任务中，{active} 个正在推进、{waiting} 个等待资源；"
        f"结构化计划已完成 {completed_steps}/{len(plans) or 0} 步。"
        f"{evidence_count} 个任务提交了可识别成果，{reporting_count} 个留下阶段报告。"
    )
    if blocked or stale:
        briefing += f"当前有 {blocked + stale} 项需要负责人优先关注。"
    elif count:
        briefing += "当前没有阻塞或超时任务。"

    return {
        "briefing": briefing,
        "overallProgress": progress,
        "path": {"completed": completed_steps, "active": active_steps, "pending": pending_steps, "total": len(plans)},
        "radar": [
            {"key": "progress", "label": "计划推进", "value": progress, "detail": f"{completed_steps} 个步骤完成"},
            {"key": "evidence", "label": "成果证据", "value": coverage(evidence_count), "detail": f"{evidence_count}/{count} 个任务有交付物"},
            {"key": "reporting", "label": "阶段汇报", "value": coverage(reporting_count), "detail": f"{reporting_count}/{count} 个任务有报告"},
            {"key": "freshness", "label": "信息新鲜度", "value": coverage(fresh_count), "detail": f"{fresh_count}/{count} 在 24h 内更新"},
        ],
        "attention": attention[:8],
        "healthy": not blocked and not stale,
    }


def build_crew_report(employee: dict[str, Any]) -> dict[str, Any]:
    """Collapse a Crew member's checkpoints into one readable stage dossier."""
    reports = list(employee.get("stageReports") or [])
    history = sorted(reports, key=lambda item: str(item.get("timestamp") or ""), reverse=True)
    latest = history[0] if history else {}
    outcomes: list[str] = []
    for report in history:
        for step in report.get("completed") or []:
            if step and step not in outcomes:
                outcomes.append(str(step))
    for step in employee.get("plan") or []:
        value = str(step.get("step") or "")
        if step.get("status") == "completed" and value and value not in outcomes:
            outcomes.append(value)
    pending_steps = [
        str(step.get("step")) for step in employee.get("plan") or []
        if step.get("status") == "pending" and step.get("step")
    ]
    decisions = [report for report in history if report.get("kind") == "decision"]
    return {
        "taskId": employee.get("id"),
        "threadId": employee.get("threadId"),
        "owner": employee.get("name"),
        "title": employee.get("title"),
        "status": employee.get("status"),
        "statusLabel": employee.get("statusLabel"),
        "progress": employee.get("progress", 0),
        "updatedLabel": employee.get("updatedLabel"),
        "latestHeadline": latest.get("headline") or employee.get("assignment") or "尚未提交阶段报告",
        "summary": latest.get("summary") or employee.get("summary") or "暂无阶段总结。",
        "current": latest.get("current") or employee.get("assignment") or "",
        "outcomes": outcomes[:8],
        "nextSteps": pending_steps[:5],
        "artifacts": list(employee.get("artifacts") or [])[:6],
        "history": history[:20],
        "decisions": decisions[:8],
        "stats": {
            "reports": len(reports),
            "milestones": sum(report.get("kind") == "milestone" for report in reports),
            "decisions": len(decisions),
            "evidence": len(employee.get("artifacts") or []),
        },
        "color": employee.get("color"),
        "accent": employee.get("accent"),
    }


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
        recent_reports: list[dict[str, Any]] = []
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
            updated_iso = datetime.fromtimestamp(int(row["updated_at"])).astimezone().isoformat(timespec="seconds")
            updated_label = datetime.fromtimestamp(int(row["updated_at"])).strftime("%m-%d %H:%M")
            artifacts.extend({**item, "owner": name, "taskId": role_id, "updatedAt": updated_iso, "updatedLabel": updated_label} for item in owned)
            reports = [
                {**report, "owner": name, "taskId": role_id, "status": status, "accent": PALETTES[index % len(PALETTES)][3]}
                for report in rollout.get("stageReports") or []
            ]
            recent_reports.extend(reports)
            palette = PALETTES[index % len(PALETTES)]
            employees.append({
                "id": role_id, "threadId": thread_id, "name": name, "title": title,
                "assignment": clean_markdown(str(current), 76), "status": status, "statusLabel": status_label,
                "progress": plan_progress(plan, status),
                "bubble": rollout.get("bubble") or "正在整理当前任务进展…",
                "summary": rollout.get("summary") or "暂无最新文字汇报。",
                "plan": plan, "artifacts": owned, "wandb": rollout.get("wandb") or [],
                "stageReports": reports,
                "updatedAt": updated_iso,
                "updatedLabel": updated_label,
                "color": palette[0], "hair": palette[1], "shirt": palette[2], "accent": palette[3],
                "slot": SLOTS[index % len(SLOTS)], "floor": index // len(SLOTS),
            })
        states = ("active", "waiting", "blocked", "complete", "idle", "stale", "archived")
        recent_reports.sort(key=lambda item: str(item.get("timestamp") or ""), reverse=True)
        artifacts.sort(key=lambda item: str(item.get("updatedAt") or ""), reverse=True)
        insights = build_insights(employees)
        decisions = [report for report in recent_reports if report.get("kind") == "decision"][:8]
        crew_reports = [build_crew_report(employee) for employee in employees]
        snapshot = {
            "generatedAt": datetime.now().astimezone().isoformat(timespec="seconds"),
            "generatedLabel": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "source": "Codex 本地任务记录（只读）",
            "project": {k: v for k, v in self.config["project"].items() if k not in {"root", "manager_thread_id"}},
            "employees": employees,
            "counts": {state: sum(1 for e in employees if e["status"] == state) for state in states},
            "insights": insights,
            "recentReports": recent_reports[:40],
            "crewReports": crew_reports,
            "decisions": decisions,
            "artifacts": artifacts[:30],
        }
        snapshot["secretary"] = build_secretary(snapshot, self.config.get("secretary") or {})
        return snapshot


def make_handler(dashboard: Dashboard, web_dir: Path, process_token: str | None = None):
    class Handler(BaseHTTPRequestHandler):
        server_version = "PixelCrew/1.1"

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
            if process_token:
                self.send_header("X-PixelCrew-Process-Token", process_token)
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
    parser.add_argument("--process-token", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    config = load_config(args.config.resolve())
    dashboard = Dashboard(config)
    if args.snapshot:
        print(json.dumps(dashboard.snapshot(), ensure_ascii=False, indent=2))
        return
    server = ThreadingHTTPServer((args.host, args.port), make_handler(dashboard, DEFAULT_WEB_DIR, args.process_token))
    print(f"PixelCrew: http://{args.host}:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Create a privacy-safe local config for a Codex project workspace."""
from __future__ import annotations
import argparse
import json
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("project_root", type=Path)
parser.add_argument("--name")
parser.add_argument("--manager-thread-id", default="")
parser.add_argument("--output", type=Path, default=Path("pixelcrew.json"))
args = parser.parse_args()
root = args.project_root.expanduser().resolve()
config = {
    "project": {
        "name": args.name or root.name,
        "subtitle": "负责人统筹 · 子任务并行 · 统一验收",
        "root": str(root),
        "manager_thread_id": args.manager_thread_id,
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
}
args.output.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(args.output.resolve())

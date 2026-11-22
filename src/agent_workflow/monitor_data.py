from __future__ import annotations

import json
import os
from pathlib import Path


def state_root() -> Path:
    explicit = os.environ.get("AGENT_WORKFLOW_STATE_ROOT")
    if explicit:
        return Path(explicit).expanduser()
    workspace = Path(os.environ.get("AGENT_WORKFLOW_WORKSPACE", os.getcwd())).expanduser()
    return workspace / ".agent-workflow" / "state"


def task_records(root: Path | None = None) -> list[dict]:
    directory = root or state_root()
    records: list[dict] = []
    for path in sorted((directory / "tasks").glob("*.json")):
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            records.append({"task_id": path.stem, "state": "unknown", "error": True})
            continue
        record.setdefault("task_id", path.stem)
        records.append(record)
    return sorted(records, key=lambda item: (item.get("updated_at", ""), item.get("task_id", "")), reverse=True)


def format_task_lines(root: Path | None = None) -> list[str]:
    records = task_records(root)
    if not records:
        return ["  タスク状態ファイルなし"]
    lines = []
    for record in records:
        test = record.get("test") or {}
        test_status = test.get("status", "-") if isinstance(test, dict) else "-"
        pr = f"#{record['pr']}" if record.get("pr") else "-"
        line = (
            f"  {record.get('agent', '?')} [{record.get('phase', '?')}] "
            f"{record.get('task_id', '?')} {record.get('state', '?')} "
            f"test={test_status} PR={pr} hb={record.get('heartbeat_at', '-')}"
        )
        if record.get("error"):
            line += " ERROR"
        lines.append(line)
    return lines

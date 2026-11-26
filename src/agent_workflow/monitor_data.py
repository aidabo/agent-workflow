from __future__ import annotations

import json
import os
import re
import shutil
import time
import unicodedata
from pathlib import Path

SAFE_ID = re.compile(r"^[A-Za-z0-9._-]+$")
CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")


def short_text(value: object, limit: int = 64) -> str:
    text = CONTROL_CHARS.sub("", str(value or ""))
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def display_width(text: str) -> int:
    return sum(2 if unicodedata.east_asian_width(char) in "WF" else 1 for char in text)


def truncate_display(text: str, limit: int) -> str:
    if display_width(text) <= limit:
        return text
    out: list[str] = []
    used = 0
    for char in text:
        char_width = 2 if unicodedata.east_asian_width(char) in "WF" else 1
        if used + char_width > max(0, limit - 1):
            break
        out.append(char)
        used += char_width
    return "".join(out) + "…"


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
        except (OSError, ValueError, TypeError):
            records.append({"task_id": path.stem, "state": "unknown", "error": True})
            continue
        if not isinstance(record, dict):
            records.append({"task_id": path.stem, "state": "unknown", "error": True})
            continue
        record.setdefault("task_id", path.stem)
        records.append(record)
    return sorted(records, key=lambda item: (item.get("updated_at", ""), item.get("task_id", "")), reverse=True)


def format_task_lines(root: Path | None = None, max_rows: int = 8, records: list[dict] | None = None) -> list[str]:
    records = records if records is not None else task_records(root)
    if not records:
        return ["  タスク状態ファイルなし"]
    active = [record for record in records if record.get("state") != "done"]
    completed = [record for record in records if record.get("state") == "done"]
    visible = (active + completed)[:max_rows]
    lines = []
    for record in visible:
        test = record.get("test") or {}
        test_status = short_text((test.get("status") or "-") if isinstance(test, dict) else "-", 24)
        pr = f"#{record['pr']}" if record.get("pr") else "-"
        raw_task_id = record.get("task_id", "?")
        task_id = short_text(raw_task_id, 32)
        checkpoint = (root or state_root()) / "checkpoints" / f"{raw_task_id}.json"
        checkpoint_info = ""
        try:
            if not isinstance(raw_task_id, str) or not SAFE_ID.fullmatch(raw_task_id):
                raise OSError("invalid task id")
            stat = checkpoint.stat()
            size = stat.st_size
            shown = f"{size / 1024:.0f}KB" if size >= 1024 else f"{size}B"
            age = max(0, int(time.time() - stat.st_mtime))
            age_label = f"{age // 3600}h" if age >= 3600 else f"{age // 60}m"
            checkpoint_info = f" cp={shown}·{age_label}"
            if size > 512 * 1024:
                checkpoint_info += "!"
        except OSError:
            pass
        line = (
            f"  {short_text(record.get('agent', '?'), 20)} [{short_text(record.get('phase', '?'), 24)}] "
            f"{task_id} {short_text(record.get('state', '?'), 16)} "
            f"test={test_status} PR={pr} hb={short_text(record.get('heartbeat_at', '-'), 32)}"
            f"{checkpoint_info}"
        )
        goal = short_text(record.get("goal"), 48)
        next_action = short_text(record.get("next_action"), 48)
        if goal:
            line += f" 目的={goal}"
        if next_action and next_action != goal:
            line += f" 次={next_action}"
        if record.get("error"):
            line += " ERROR"
        width = shutil.get_terminal_size((120, 24)).columns
        line = truncate_display(line, max(1, width))
        lines.append(line)
    omitted = len(records) - len(visible)
    if omitted:
        lines.append(f"  … 他 {omitted} task（完了済みを含む）")
    return lines

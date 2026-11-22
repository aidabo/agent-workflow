from __future__ import annotations

import argparse
import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PHASES = {
    "docs", "docs_review", "docs_human_review", "assigned", "coding", "test",
    "code_review", "code_human_review", "done",
}
STATES = {"busy", "waiting_user", "blocked", "stale", "needs_human", "idle", "done"}
TASK_STATUSES = {"planned", "ready", "in_progress", "ready_for_review", "needs_human", "done"}
ALLOWED_PHASE_STATUS = {
    "docs": {"planned", "ready", "in_progress", "ready_for_review"},
    "docs_review": {"in_progress", "ready_for_review"},
    "docs_human_review": {"ready_for_review"},
    "assigned": {"ready", "in_progress"},
    "coding": {"in_progress"},
    "test": {"in_progress"},
    "code_review": {"ready_for_review"},
    "code_human_review": {"ready_for_review"},
    "done": {"done"},
}
SAFE_ID = re.compile(r"^[A-Za-z0-9._-]+$")
SECRET_VALUE = re.compile(r"(AKIA[0-9A-Z]{16}|(?:sk|rk)-[A-Za-z0-9_-]{20,}|https://[^\s/]+/api/webhooks/[A-Za-z0-9_/-]{20,})")


def now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def safe_id(value: str, label: str) -> str:
    if not value or value in {".", ".."} or not SAFE_ID.fullmatch(value):
        raise ValueError(f"invalid {label}: use only A-Z/a-z/0-9/._- and never . or ..")
    return value


def state_root(workspace: Path, explicit: str | None) -> Path:
    root = Path(explicit).expanduser() if explicit else workspace / ".agent-workflow" / "state"
    return root.resolve()


def path_for(root: Path, kind: str, identifier: str) -> Path:
    safe_id(identifier, kind)
    candidate = (root / kind / f"{identifier}.json").resolve()
    if root not in candidate.parents:
        raise ValueError("state path escapes state root")
    return candidate


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def atomic_write(path: Path, value: dict[str, Any]) -> None:
    root = path.parents[1]
    root.parent.mkdir(parents=True, exist_ok=True)
    if root.parent.name == ".agent-workflow":
        root.parent.chmod(0o700)
    root.mkdir(parents=True, exist_ok=True)
    root.chmod(0o700)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.parent.chmod(0o700)
    payload = json.dumps(value, ensure_ascii=False, indent=2) + "\n"
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_name, path)
        path.chmod(0o600)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def reject_secret(value: str | None, label: str) -> None:
    if value and SECRET_VALUE.search(value):
        raise ValueError(f"secret-like value is not allowed in {label}")


def validate_enum(value: str | None, values: set[str], label: str) -> None:
    if value is not None and value not in values:
        raise ValueError(f"invalid {label}: {value}")


def validate_combination(phase: str | None, state: str | None, task_status: str | None) -> None:
    if phase is not None and task_status is not None and task_status != "needs_human":
        allowed = ALLOWED_PHASE_STATUS.get(phase)
        if allowed is None or task_status not in allowed:
            raise ValueError(f"invalid phase/task_status combination: {phase}/{task_status}")
    if phase == "done" and task_status != "done":
        raise ValueError("phase=done requires task_status=done")
    if phase == "done" and state not in {None, "done"}:
        raise ValueError("phase=done requires state=done")
    if task_status == "done" and phase != "done":
        raise ValueError("task_status=done requires phase=done")
    if task_status == "done" and state not in {None, "done"}:
        raise ValueError("task_status=done requires state=done")
    if state == "done" and (phase != "done" or task_status != "done"):
        raise ValueError("state=done requires phase=done and task_status=done")
    if task_status == "needs_human" and state not in {None, "needs_human", "blocked", "waiting_user", "stale"}:
        raise ValueError("task_status=needs_human requires a human-escalation state")
    if state in {"blocked", "stale"}:
        return
    if phase in {"docs_human_review", "code_human_review"} and state not in {None, "waiting_user", "needs_human"}:
        raise ValueError(f"human-review phase requires waiting_user state: {phase}/{state}")
    if state == "idle" and task_status not in {None, "planned", "ready"}:
        raise ValueError("state=idle requires task_status=planned or ready")
    if phase == "done" and state not in {None, "done"}:
        raise ValueError("phase=done requires state=done")


def parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def sweep_stale(root: Path, stale_after_seconds: int, heartbeat_interval_seconds: int = 60, current: datetime | None = None) -> list[str]:
    if heartbeat_interval_seconds <= 0 or stale_after_seconds < heartbeat_interval_seconds * 10:
        raise ValueError("stale_after_seconds must be at least 10 times heartbeat_interval_seconds")
    current = current or datetime.now(timezone.utc)
    changed: list[str] = []
    for path in sorted((root / "tasks").glob("*.json")):
        record = read_json(path)
        heartbeat = record.get("heartbeat_at")
        if record.get("state") in {"done", "stale"} or not heartbeat:
            continue
        if (current - parse_time(heartbeat)).total_seconds() >= stale_after_seconds:
            record["previous_state"] = record.get("state")
            record["state"] = "stale"
            record["stale_at"] = current.replace(microsecond=0).isoformat()
            record["updated_at"] = current.replace(microsecond=0).isoformat()
            atomic_write(path, record)
            changed.append(record.get("task_id", path.stem))
    return changed


def merge_record(path: Path, updates: dict[str, Any], *, reset: bool = False, clear_fields: set[str] | None = None) -> dict[str, Any]:
    record = {} if reset else read_json(path)
    for field in clear_fields or set():
        record.pop(field, None)
    record.update({key: value for key, value in updates.items() if value is not None})
    record["updated_at"] = now()
    atomic_write(path, record)
    return record


def common_parser(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--workspace", default=".")
    parser.add_argument("--state-root")
    parser.add_argument("--agent", required=True)
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--repo")
    parser.add_argument("--repo-dir")
    parser.add_argument("--phase")
    parser.add_argument("--state")
    parser.add_argument("--task-status")
    parser.add_argument("--goal")
    parser.add_argument("--branch")
    parser.add_argument("--commit")
    parser.add_argument("--pr", type=int)
    parser.add_argument("--test-status")
    parser.add_argument("--test-summary")
    parser.add_argument("--event")
    parser.add_argument("--blocked-reason")
    parser.add_argument("--clear-blocked", action="store_true")


def command_status(args: argparse.Namespace) -> int:
    agent = safe_id(args.agent, "agent")
    task_id = safe_id(args.task_id, "task_id")
    validate_enum(args.phase, PHASES, "phase")
    validate_enum(args.state, STATES, "state")
    validate_enum(args.task_status, TASK_STATUSES, "task_status")
    for label, value in vars(args).items():
        if isinstance(value, str):
            reject_secret(value, label)

    workspace = Path(args.workspace).expanduser().resolve()
    root = state_root(workspace, args.state_root)
    timestamp = now()
    state = args.state
    task_status = args.task_status
    if args.command == "begin":
        if not args.phase:
            raise ValueError("begin requires --phase")
        state = state or "busy"
        task_status = task_status or "in_progress"
    elif args.command == "heartbeat":
        state = state or "busy"
    elif args.command == "end":
        args.phase = "done"
        state = state or "done"
        task_status = task_status or "done"
    task_path = path_for(root, "tasks", task_id)
    agent_path = path_for(root, "agents", agent)
    previous_task = read_json(task_path)
    previous_agent = read_json(agent_path)
    if args.command != "end" and previous_task.get("task_status") == "done":
        raise ValueError("cannot update a completed task; begin a new task_id")
    effective_phase = args.phase if args.phase is not None else previous_task.get("phase")
    effective_task_status = task_status if task_status is not None else previous_task.get("task_status")
    effective_state = state if state is not None else previous_task.get("state")
    validate_combination(effective_phase, effective_state, effective_task_status)

    task_updates = {
        "task_id": task_id, "agent": agent, "repo": args.repo, "repo_dir": args.repo_dir,
        "phase": args.phase, "state": state, "task_status": task_status, "goal": args.goal,
        "pr": args.pr, "branch": args.branch, "commit": args.commit,
        "test": ({"status": args.test_status, "summary": args.test_summary}
                  if args.test_status or args.test_summary else None),
        "last_event": args.event, "blocked_reason": args.blocked_reason, "heartbeat_at": timestamp,
        "updated_at": timestamp,
    }
    previous_active = set(previous_agent.get("active_task_ids", []))
    if args.command == "end":
        previous_active.discard(task_id)
    else:
        previous_active.add(task_id)
    current_task_id = previous_agent.get("current_task_id")
    if args.command != "end":
        current_task_id = task_id
    elif current_task_id == task_id:
        current_task_id = sorted(previous_active)[-1] if previous_active else None
    elif current_task_id not in previous_active:
        current_task_id = sorted(previous_active)[-1] if previous_active else None
    agent_updates = {
        "agent": agent, "active_task_ids": sorted(previous_active), "current_task_id": current_task_id,
        "heartbeat_at": timestamp, "updated_at": timestamp,
    }
    task = merge_record(
        task_path, task_updates,
        clear_fields={"blocked_reason"} if args.clear_blocked else set(),
    )
    agent_record = merge_record(
        agent_path, agent_updates,
        clear_fields=(({"current_task_id"} if current_task_id is None else set())
                      | ({"blocked_reason"} if args.clear_blocked else set())),
    )
    print(json.dumps({"task": task, "agent": agent_record}, ensure_ascii=False, indent=2))
    return 0


def command_sweep(args: argparse.Namespace) -> int:
    workspace = Path(args.workspace).expanduser().resolve()
    root = state_root(workspace, args.state_root)
    changed = sweep_stale(root, args.stale_after_seconds, args.heartbeat_interval_seconds, parse_time(args.now) if args.now else None)
    print(json.dumps({"stale_tasks": changed}, ensure_ascii=False, indent=2))
    return 0


def command_context(args: argparse.Namespace) -> int:
    from .context import resolve_context

    result = resolve_context(Path(args.context_file).expanduser().resolve(), args.project, args.task_file)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="agent-status")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("begin", "update", "heartbeat", "test", "end"):
        command = sub.add_parser(name)
        common_parser(command)
    sweep = sub.add_parser("sweep")
    sweep.add_argument("--workspace", default=".")
    sweep.add_argument("--state-root")
    sweep.add_argument("--heartbeat-interval-seconds", type=int, default=60)
    sweep.add_argument("--stale-after-seconds", type=int, default=600)
    sweep.add_argument("--now")
    context = sub.add_parser("context")
    context.add_argument("--context-file", required=True)
    context.add_argument("--project")
    context.add_argument("--task-file")
    try:
        args = parser.parse_args(argv)
        if args.command == "context":
            return command_context(args)
        if args.command == "sweep":
            return command_sweep(args)
        return command_status(args)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"agent-status: {exc}", file=os.sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

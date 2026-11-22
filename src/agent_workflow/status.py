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
SAFE_ID = re.compile(r"^[A-Za-z0-9._-]+$")
SENSITIVE_PATH = re.compile(r"(^|/)(\.env(?:\.|$)|\.ssh|\.aws|\.notify|\.clawhip|credentials?|secrets?)(/|$)", re.I)
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


def merge_record(path: Path, updates: dict[str, Any]) -> dict[str, Any]:
    record = read_json(path)
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
        state = state or "busy"
        task_status = task_status or "in_progress"
    elif args.command == "heartbeat":
        state = state or "busy"
    elif args.command == "end":
        state = state or "done"
        task_status = task_status or "done"

    task_updates = {
        "task_id": task_id, "repo": args.repo, "repo_dir": args.repo_dir,
        "phase": args.phase, "task_status": task_status, "goal": args.goal,
        "pr": args.pr, "branch": args.branch, "commit": args.commit,
        "test": ({"status": args.test_status, "summary": args.test_summary}
                  if args.test_status or args.test_summary else None),
        "last_event": args.event, "blocked_reason": args.blocked_reason,
        "updated_at": timestamp,
    }
    agent_updates = {
        "agent": agent, "task_id": task_id, "repo": args.repo, "repo_dir": args.repo_dir,
        "phase": args.phase, "state": state, "task_status": task_status,
        "goal": args.goal, "pr": args.pr, "branch": args.branch, "commit": args.commit,
        "test": ({"status": args.test_status, "summary": args.test_summary}
                  if args.test_status or args.test_summary else None),
        "last_event": args.event, "blocked_reason": args.blocked_reason,
        "heartbeat_at": timestamp, "updated_at": timestamp,
    }
    task = merge_record(path_for(root, "tasks", task_id), task_updates)
    agent_record = merge_record(path_for(root, "agents", agent), agent_updates)
    print(json.dumps({"task": task, "agent": agent_record}, ensure_ascii=False, indent=2))
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
    context = sub.add_parser("context")
    context.add_argument("--context-file", required=True)
    context.add_argument("--project")
    context.add_argument("--task-file")
    try:
        args = parser.parse_args(argv)
        if args.command == "context":
            return command_context(args)
        return command_status(args)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"agent-status: {exc}", file=os.sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

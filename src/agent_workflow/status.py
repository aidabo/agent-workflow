from __future__ import annotations

import argparse
import fcntl
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


def merge_record(path: Path, updates: dict[str, Any], *, reset: bool = False, clear_fields: set[str] | None = None, lock: bool = False) -> dict[str, Any]:
    lock_path = path.with_suffix(path.suffix + ".lock")
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_stream = open(lock_path, "a+", encoding="utf-8") if lock else None
    try:
        if lock_stream:
            os.chmod(lock_path, 0o600)
            fcntl.flock(lock_stream.fileno(), fcntl.LOCK_EX)
        record = {} if reset else read_json(path)
        for field in clear_fields or set():
            record.pop(field, None)
        record.update({key: value for key, value in updates.items() if value is not None})
        record["updated_at"] = now()
        atomic_write(path, record)
        return record
    finally:
        if lock_stream:
            fcntl.flock(lock_stream.fileno(), fcntl.LOCK_UN)
            lock_stream.close()


def save_checkpoint(path: Path, task: dict[str, Any], *, task_id: str, agent: str,
                    workspace: Path, next_action: str | None = None,
                    resume_note: str | None = None, allow_done: bool = False) -> dict[str, Any]:
    lock_path = path.with_suffix(path.suffix + ".lock")
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(lock_path, "a+", encoding="utf-8") as lock_stream:
        os.chmod(lock_path, 0o600)
        fcntl.flock(lock_stream.fileno(), fcntl.LOCK_EX)
        try:
            previous = read_json(path)
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
            print(f"agent-status: checkpoint warning: {exc}", file=os.sys.stderr)
            previous = {}
        checkpoint = build_checkpoint(
            task, task_id=task_id, agent=agent, workspace=workspace,
            next_action=next_action, resume_note=resume_note,
            previous=previous, allow_done=allow_done,
        )
        atomic_write(path, checkpoint)
        fcntl.flock(lock_stream.fileno(), fcntl.LOCK_UN)
        return checkpoint


def build_checkpoint(task: dict[str, Any], *, task_id: str, agent: str, workspace: Path,
                     next_action: str | None = None, resume_note: str | None = None,
                     previous: dict[str, Any] | None = None, allow_done: bool = False) -> dict[str, Any]:
    if task.get("agent") != agent:
        raise ValueError(f"task belongs to agent {task.get('agent', '?')}, not {agent}")
    if not allow_done and (task.get("task_status") == "done" or task.get("state") == "done"):
        raise ValueError("cannot checkpoint a completed task")
    references = task.get("references", [])
    if not isinstance(references, list):
        raise ValueError("references must be a list")
    for reference in references:
        if not isinstance(reference, str):
            raise ValueError("references must contain strings")
        reject_secret(reference, "reference")
        ref_path = Path(reference)
        if ref_path.is_absolute() or ".." in ref_path.parts:
            raise ValueError("references must be workspace-relative paths")
    previous = previous if isinstance(previous, dict) else {}
    return {
        "schema_version": 1,
        "task_id": task_id,
        "agent": agent,
        "workspace": str(workspace),
        "checkpoint_at": now(),
        "phase": task.get("phase"),
        "task_status": task.get("task_status"),
        "state": task.get("state"),
        "goal": task.get("goal"),
        "repo": task.get("repo"),
        "repo_dir": task.get("repo_dir"),
        "branch": task.get("branch"),
        "head_sha": task.get("commit"),
        "pr": task.get("pr"),
        "test": task.get("test"),
        "next_action": next_action or task.get("next_action") or previous.get("next_action") or task.get("goal"),
        "resume_note": resume_note or task.get("resume_note") or previous.get("resume_note"),
        "references": references,
    }


def command_checkpoint(args: argparse.Namespace) -> int:
    agent = safe_id(args.agent, "agent")
    task_id = safe_id(args.task_id, "task_id")
    for label, value in vars(args).items():
        if isinstance(value, str):
            reject_secret(value, label)
    workspace = Path(args.workspace).expanduser().resolve()
    root = state_root(workspace, args.state_root)
    task_path = path_for(root, "tasks", task_id)
    task = read_json(task_path)
    if not task:
        raise ValueError(f"task does not exist: {task_id}")
    checkpoint = save_checkpoint(
        path_for(root, "checkpoints", task_id), task, task_id=task_id, agent=agent,
        workspace=workspace, next_action=args.next_action, resume_note=args.resume_note,
    )
    print(json.dumps(checkpoint, ensure_ascii=False, indent=2))
    return 0


def command_resume(args: argparse.Namespace) -> int:
    workspace = Path(args.workspace).expanduser().resolve()
    root = state_root(workspace, args.state_root)
    task_paths = sorted((root / "tasks").glob("*.json"))
    candidates = []
    errors = []
    for task_path in task_paths:
        try:
            task = read_json(task_path)
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
            errors.append({"path": str(task_path), "warning": f"invalid task file: {exc}"})
            continue
        if not isinstance(task, dict):
            errors.append({"path": str(task_path), "warning": "task file is not an object"})
            continue
        if not task or task.get("state") == "done":
            continue
        task_id = task.get("task_id", task_path.stem)
        if not isinstance(task_id, str) or not SAFE_ID.fullmatch(task_id):
            errors.append({"path": str(task_path), "warning": "invalid task_id"})
            continue
        if args.task_id and task_id != args.task_id:
            continue
        try:
            checkpoint = read_json(path_for(root, "checkpoints", task_id))
            if not isinstance(checkpoint, dict):
                checkpoint = {}
                errors.append({"task_id": task_id, "warning": "checkpoint file is not an object"})
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
            checkpoint = {}
            errors.append({"task_id": task_id, "warning": f"invalid checkpoint: {exc}"})
        warning = []
        if task.get("state") in {"stale", "needs_human", "blocked"}:
            warning.append(f"task state is {task.get('state')}; human confirmation required")
        if task.get("phase") in {"docs_human_review", "code_human_review"} or task.get("task_status") == "needs_human":
            warning.append("human review is pending; do not auto-resume")
        if task.get("pr") and not checkpoint:
            warning.append("no checkpoint for current task")
        if checkpoint.get("workspace") and checkpoint.get("workspace") != str(workspace):
            warning.append("checkpoint workspace differs from current workspace")
        for label, checkpoint_value, task_value in (
            ("branch", checkpoint.get("branch"), task.get("branch")),
            ("pr", checkpoint.get("pr"), task.get("pr")),
            ("head_sha", checkpoint.get("head_sha"), task.get("commit")),
        ):
            if checkpoint_value and task_value and checkpoint_value != task_value:
                warning.append(f"checkpoint {label} differs from current task")
        candidates.append({
            "task_id": task_id,
            "agent": task.get("agent"),
            "phase": task.get("phase"),
            "task_status": task.get("task_status"),
            "state": task.get("state"),
            "branch": checkpoint.get("branch") or task.get("branch"),
            "pr": checkpoint.get("pr") or task.get("pr"),
            "head_sha": checkpoint.get("head_sha") or task.get("commit"),
            "test": checkpoint.get("test") or task.get("test"),
            "next_action": checkpoint.get("next_action") or task.get("next_action") or task.get("goal"),
            "checkpoint_at": checkpoint.get("checkpoint_at"),
            "warning": warning,
            "prompt": "同じbranchの未完了作業から続けてください。新しいPRや重複pushは作らないでください。",
        })
    print(json.dumps({"workspace": str(workspace), "resume_candidates": candidates, "errors": errors}, ensure_ascii=False, indent=2))
    return 0


def command_checkpoint_prune(args: argparse.Namespace) -> int:
    workspace = Path(args.workspace).expanduser().resolve()
    root = state_root(workspace, args.state_root)
    match = re.fullmatch(r"(\d+)([smhd])", args.older_than)
    if not match:
        raise ValueError("--older-than must look like 30d, 12h, 60m, or 30s")
    amount, unit = int(match.group(1)), match.group(2)
    seconds = amount * {"s": 1, "m": 60, "h": 3600, "d": 86400}[unit]
    cutoff = datetime.now(timezone.utc).timestamp() - seconds
    candidates = []
    for path in sorted((root / "checkpoints").glob("*.json")):
        try:
            if path.stat().st_mtime >= cutoff:
                continue
            task = read_json(root / "tasks" / path.name)
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            continue
        if not isinstance(task, dict) or task.get("state") != "done":
            continue
        candidates.append(str(path))
    if args.apply:
        for name in candidates:
            path = Path(name)
            lock_path = path.with_suffix(path.suffix + ".lock")
            with open(lock_path, "a+", encoding="utf-8") as lock_stream:
                fcntl.flock(lock_stream.fileno(), fcntl.LOCK_EX)
                try:
                    task = read_json(root / "tasks" / path.name)
                    if (isinstance(task, dict) and task.get("state") == "done"
                            and path.exists() and path.stat().st_mtime < cutoff):
                        path.unlink()
                finally:
                    fcntl.flock(lock_stream.fileno(), fcntl.LOCK_UN)
    print(json.dumps({"dry_run": not args.apply, "removed": candidates if args.apply else [],
                      "candidates": candidates, "count": len(candidates),
                      "bytes": sum(Path(name).stat().st_size for name in candidates if Path(name).exists())},
                     ensure_ascii=False, indent=2))
    return 0


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
    if args.command == "heartbeat" and args.state is None:
        state = previous_task.get("state") or "busy"
        if state == "stale":
            state = previous_task.get("previous_state") or "busy"
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
        lock=True,
    )
    checkpoint_event = args.command in {"begin", "test", "end"} or any(
        value is not None for value in (
            args.repo, args.repo_dir, args.phase, args.state, args.task_status, args.goal,
            args.branch, args.commit, args.pr, args.test_status, args.test_summary,
            args.event, args.blocked_reason,
        )
    )
    if checkpoint_event:
        checkpoint_path = path_for(root, "checkpoints", task_id)
        try:
            save_checkpoint(
                checkpoint_path, task, task_id=task_id, agent=agent, workspace=workspace,
                allow_done=args.command == "end",
            )
        except ValueError as exc:
            print(f"agent-status: checkpoint warning: {exc}", file=os.sys.stderr)
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
    checkpoint = sub.add_parser("checkpoint")
    checkpoint.add_argument("--workspace", default=".")
    checkpoint.add_argument("--state-root")
    checkpoint.add_argument("--agent", required=True)
    checkpoint.add_argument("--task-id", required=True)
    checkpoint.add_argument("--next-action")
    checkpoint.add_argument("--resume-note")
    resume = sub.add_parser("resume")
    resume.add_argument("--workspace", default=".")
    resume.add_argument("--state-root")
    resume.add_argument("--task-id")
    prune = sub.add_parser("checkpoint-prune")
    prune.add_argument("--workspace", default=".")
    prune.add_argument("--state-root")
    prune.add_argument("--older-than", required=True)
    prune.add_argument("--apply", action="store_true")
    try:
        args = parser.parse_args(argv)
        if args.command == "context":
            return command_context(args)
        if args.command == "sweep":
            return command_sweep(args)
        if args.command == "checkpoint":
            return command_checkpoint(args)
        if args.command == "resume":
            return command_resume(args)
        if args.command == "checkpoint-prune":
            return command_checkpoint_prune(args)
        return command_status(args)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"agent-status: {exc}", file=os.sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

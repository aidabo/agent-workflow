from __future__ import annotations

import argparse
import fcntl
import json
import os
import re
import tempfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PHASES = {
    "docs", "docs_review", "docs_human_review", "assigned", "coding", "test",
    "code_review", "code_human_review", "done",
}
STATES = {"busy", "waiting_user", "blocked", "stale", "needs_human", "idle", "done"}
TASK_STATUSES = {"planned", "ready", "in_progress", "ready_for_review", "needs_human", "done"}
REVIEW_STATUSES = {"pending", "approved", "changes_requested", "needs_you"}
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


def plan_path(root: Path, plan_id: str) -> Path:
    return path_for(root, "plans", plan_id)


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


def reject_secret_values(value: Any, label: str) -> None:
    if isinstance(value, str):
        reject_secret(value, label)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            reject_secret_values(item, f"{label}[{index}]")


def active_task_owners(root: Path, task_id: str) -> list[str]:
    owners: list[str] = []
    for path in sorted((root / "agents").glob("*.json")):
        try:
            record = read_json(path)
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            continue
        active_task_ids = record.get("active_task_ids") if isinstance(record, dict) else None
        if isinstance(active_task_ids, list) and task_id in active_task_ids:
            owners.append(str(record.get("agent") or path.stem))
    return owners


def replaceable_task(existing: dict[str, Any], root: Path, task_id: str) -> bool:
    return (
        existing.get("pipeline_managed") is True
        and existing.get("task_status") == "ready"
        and existing.get("state") == "idle"
        and not existing.get("agent")
        and not active_task_owners(root, task_id)
    )


def _command_plan_create_impl(args: argparse.Namespace) -> int:
    plan_id = safe_id(args.plan_id, "plan_id")
    workspace = Path(args.workspace).expanduser().resolve()
    root = state_root(workspace, args.state_root)
    values = {
        "plan_id": plan_id,
        "title": args.title,
        "requirement": args.requirement,
        "users": args.users,
        "acceptance_criteria": args.acceptance_criteria,
        "scope": args.scope,
        "non_goals": args.non_goals,
        "constraints": args.constraints,
        "open_questions": args.open_questions,
        "assumptions": args.assumptions,
        "task_ids": [],
        "risk_level": args.risk_level,
        "status": "draft",
        "created_at": now(),
        "updated_at": now(),
    }
    for key, value in values.items():
        reject_secret_values(value, key)
    path = plan_path(root, plan_id)
    if path.exists():
        existing = read_json(path)
        if not args.force:
            raise ValueError(f"plan already exists: {plan_id} (use --force to replace draft)")
        if not isinstance(existing, dict) or existing.get("status") != "draft":
            raise ValueError("--force can replace draft plans only")
        existing_task_ids = existing.get("task_ids")
        if isinstance(existing_task_ids, list):
            values["task_ids"] = existing_task_ids
    atomic_write(path, values)
    print(json.dumps(values, ensure_ascii=False, indent=2))
    return 0


def _command_task_create_impl(args: argparse.Namespace) -> int:
    task_id = safe_id(args.task_id, "task_id")
    plan_id = safe_id(args.plan_id, "plan_id")
    workspace = Path(args.workspace).expanduser().resolve()
    root = state_root(workspace, args.state_root)
    plan_path_value = plan_path(root, plan_id)
    if not plan_path_value.is_file():
        raise ValueError(f"plan does not exist: {plan_id}")
    plan = read_json(plan_path_value)
    if not isinstance(plan, dict) or plan.get("status") != "draft":
        raise ValueError("task drafts can be added to draft plans only")
    agent = safe_id(args.agent, "agent") if args.agent else None
    values = {
        "task_id": task_id,
        "plan_id": plan_id,
        "agent": agent,
        "summary": args.summary,
        "goal": args.goal,
        "next_action": args.next_action,
        "acceptance_criteria": args.acceptance_criteria,
        "phase": "docs",
        "state": "idle",
        "task_status": "ready",
        "pipeline_managed": True,
        "created_at": now(),
        "updated_at": now(),
    }
    for key, value in values.items():
        reject_secret_values(value, key)
    path = path_for(root, "tasks", task_id)
    if path.exists():
        existing = read_json(path)
        if not args.force:
            raise ValueError(f"task already exists: {task_id} (use --force to replace draft)")
        if not isinstance(existing, dict) or not replaceable_task(existing, root, task_id):
            raise ValueError("--force can replace only idle, unassigned pipeline-managed ready tasks")
    else:
        existing = None
    old_plan_id = existing.get("plan_id") if isinstance(existing, dict) else None
    old_plan_path = plan_path(root, old_plan_id) if old_plan_id and old_plan_id != plan_id else None
    old_plan = None
    if old_plan_path is not None:
        old_plan = read_json(old_plan_path)
        if not isinstance(old_plan, dict) or old_plan.get("status") != "draft":
            raise ValueError("--force cannot move a task out of a non-draft plan")
    atomic_write(path, values)
    task_ids = plan.get("task_ids") if isinstance(plan, dict) else None
    if not isinstance(task_ids, list):
        task_ids = []
    if task_id not in task_ids:
        plan["task_ids"] = [*task_ids, task_id]
        plan["updated_at"] = now()
        atomic_write(plan_path_value, plan)
    if old_plan is not None:
        old_task_ids = old_plan.get("task_ids")
        if isinstance(old_task_ids, list) and task_id in old_task_ids:
            old_plan["task_ids"] = [item for item in old_task_ids if item != task_id]
            old_plan["updated_at"] = now()
            atomic_write(old_plan_path, old_plan)
    print(json.dumps(values, ensure_ascii=False, indent=2))
    return 0


def command_task_list(args: argparse.Namespace) -> int:
    workspace = Path(args.workspace).expanduser().resolve()
    root = state_root(workspace, args.state_root)
    records = []
    for path in sorted((root / "tasks").glob("*.json")):
        try:
            record = read_json(path)
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            continue
        if not isinstance(record, dict):
            continue
        if args.plan_id and record.get("plan_id") != args.plan_id:
            continue
        records.append(record)
    print(json.dumps(records, ensure_ascii=False, indent=2))
    return 0


def command_revision_create(args: argparse.Namespace) -> int:
    source_id = safe_id(args.source_task_id, "source_task_id")
    task_id = safe_id(args.task_id, "task_id")
    workspace = Path(args.workspace).expanduser().resolve()
    root = state_root(workspace, args.state_root)
    with assignment_lock(root):
        source = read_object(path_for(root, "tasks", source_id), "source task")
        if source.get("state") == "done" or source.get("task_status") == "done":
            raise ValueError("cannot create a revision from a completed task")
        if source.get("pipeline_managed") is not True:
            raise ValueError("revision tasks require a pipeline-managed source task")
        if source.get("task_status") not in {"ready_for_review", "needs_human"}:
            raise ValueError("revision source must be awaiting review or human verification")
        if source.get("superseded_by"):
            raise ValueError(f"task {source_id} already has revision {source['superseded_by']}")
        target = path_for(root, "tasks", task_id)
        if target.exists():
            raise ValueError(f"task already exists: {task_id}")
        plan_id = source.get("plan_id")
        plan = read_object(plan_path(root, plan_id), "plan") if isinstance(plan_id, str) else {}
        if plan.get("status") != "approved":
            raise ValueError(f"plan {plan_id} must be approved before creating a revision")
        revision = source.get("revision", 0)
        if not isinstance(revision, int) or revision < 0:
            raise ValueError("source task has invalid revision")
        values = {
            "task_id": task_id, "plan_id": plan_id, "agent": None,
            "summary": args.summary, "goal": args.goal, "next_action": args.next_action,
            "acceptance_criteria": source.get("acceptance_criteria", []), "phase": "docs",
            "state": "idle", "task_status": "ready", "pipeline_managed": True,
            "revision": revision + 1, "previous_task_id": source_id,
            "failure_reason": args.failure_reason, "previous_evidence": args.previous_evidence,
            "created_at": now(), "updated_at": now(),
        }
        for key, value in values.items():
            reject_secret_values(value, key)
        write_assignment_record(target, values)
        source["superseded_by"] = task_id
        source["updated_at"] = now()
        write_assignment_record(path_for(root, "tasks", source_id), source)
        task_ids = plan.get("task_ids") if isinstance(plan.get("task_ids"), list) else []
        plan["task_ids"] = [*task_ids, task_id]
        plan["updated_at"] = now()
        write_assignment_record(plan_path(root, plan_id), plan)
    print(json.dumps(values, ensure_ascii=False, indent=2))
    return 0


@contextmanager
def assignment_lock(root: Path):
    root.mkdir(parents=True, exist_ok=True)
    root.chmod(0o700)
    if root.parent.name == ".agent-workflow":
        root.parent.mkdir(parents=True, exist_ok=True)
        root.parent.chmod(0o700)
    lock_path = root / "assignment.lock"
    with open(lock_path, "a+", encoding="utf-8") as lock_stream:
        os.chmod(lock_path, 0o600)
        fcntl.flock(lock_stream.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock_stream.fileno(), fcntl.LOCK_UN)


def write_assignment_record(path: Path, record: dict[str, Any]) -> None:
    lock_path = path.with_suffix(path.suffix + ".lock")
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(lock_path, "a+", encoding="utf-8") as lock_stream:
        os.chmod(lock_path, 0o600)
        fcntl.flock(lock_stream.fileno(), fcntl.LOCK_EX)
        try:
            atomic_write(path, record)
        finally:
            fcntl.flock(lock_stream.fileno(), fcntl.LOCK_UN)


def read_object(path: Path, label: str) -> dict[str, Any]:
    record = read_json(path)
    if not record:
        raise ValueError(f"{label} does not exist: {path.stem}")
    if not isinstance(record, dict):
        raise ValueError(f"{label} is not an object: {path.name}")
    return record


def active_ids(record: dict[str, Any]) -> list[str]:
    values = record.get("active_task_ids")
    if not isinstance(values, list):
        return []
    return sorted({value for value in values if isinstance(value, str) and SAFE_ID.fullmatch(value)})


def current_task_for(agent_record: dict[str, Any], task_ids: list[str]) -> str | None:
    current = agent_record.get("current_task_id")
    if isinstance(current, str) and current in task_ids:
        return current
    return task_ids[-1] if task_ids else None


def command_plan_approve(args: argparse.Namespace) -> int:
    plan_id = safe_id(args.plan_id, "plan_id")
    workspace = Path(args.workspace).expanduser().resolve()
    root = state_root(workspace, args.state_root)
    path = plan_path(root, plan_id)
    with assignment_lock(root):
        plan = read_object(path, "plan")
        if plan.get("status") != "draft":
            raise ValueError(f"plan {plan_id} is not draft: {plan.get('status')}")
        task_ids = plan.get("task_ids")
        if not isinstance(task_ids, list):
            raise ValueError(f"plan {plan_id} has invalid task_ids")
        if not task_ids:
            raise ValueError(f"plan {plan_id} has no tasks to approve")
        for task_id in task_ids:
            if not isinstance(task_id, str) or not SAFE_ID.fullmatch(task_id):
                raise ValueError(f"plan {plan_id} has invalid task_id")
            task = read_object(path_for(root, "tasks", task_id), "task")
            if task.get("plan_id") != plan_id:
                raise ValueError(f"task {task_id} does not belong to plan {plan_id}")
        plan["status"] = "approved"
        plan["updated_at"] = now()
        write_assignment_record(path, plan)
    print(json.dumps(plan, ensure_ascii=False, indent=2))
    return 0


def command_assign(args: argparse.Namespace) -> int:
    task_id = safe_id(args.task_id, "task_id")
    agent = safe_id(args.agent, "agent")
    workspace = Path(args.workspace).expanduser().resolve()
    root = state_root(workspace, args.state_root)
    task_path = path_for(root, "tasks", task_id)
    agent_path = path_for(root, "agents", agent)
    with assignment_lock(root):
        task = read_object(task_path, "task")
        if task.get("state") in {"done", "stale"} or task.get("task_status") == "done":
            raise ValueError(f"cannot assign {task_id}: task is {task.get('state') or task.get('task_status')}")
        if task.get("superseded_by"):
            raise ValueError(f"task {task_id} was superseded by {task['superseded_by']}")
        existing_agent = task.get("agent")
        if existing_agent and existing_agent != agent:
            raise ValueError(f"task {task_id} is already assigned to {existing_agent}")
        indexed_owners = active_task_owners(root, task_id)
        if any(owner != agent for owner in indexed_owners):
            raise ValueError(f"task {task_id} is already indexed by {', '.join(indexed_owners)}")
        if task.get("pipeline_managed") is True:
            plan_id = task.get("plan_id")
            plan = read_object(plan_path(root, plan_id), "plan") if isinstance(plan_id, str) else {}
            if plan.get("status") != "approved":
                raise ValueError(f"plan {plan_id} must be approved before assigning tasks")
        if task.get("state") not in {None, "idle"} or task.get("task_status") not in {None, "planned", "ready"}:
            raise ValueError(f"task {task_id} is not waiting for assignment")
        agent_record = read_json(agent_path)
        if not isinstance(agent_record, dict):
            agent_record = {}
        task["agent"] = agent
        task["phase"] = "assigned"
        task["state"] = "busy"
        task["task_status"] = "in_progress"
        task["assigned_at"] = now()
        task["updated_at"] = now()
        ids = sorted(set(active_ids(agent_record)) | {task_id})
        agent_record.update({
            "agent": agent,
            "active_task_ids": ids,
            "current_task_id": task_id,
            "heartbeat_at": now(),
            "updated_at": now(),
        })
        write_assignment_record(task_path, task)
        write_assignment_record(agent_path, agent_record)
    print(json.dumps({"task": task, "agent": agent_record}, ensure_ascii=False, indent=2))
    return 0


def command_unassign(args: argparse.Namespace) -> int:
    task_id = safe_id(args.task_id, "task_id")
    workspace = Path(args.workspace).expanduser().resolve()
    root = state_root(workspace, args.state_root)
    task_path = path_for(root, "tasks", task_id)
    with assignment_lock(root):
        task = read_object(task_path, "task")
        agent = task.get("agent")
        if not isinstance(agent, str) or not agent:
            raise ValueError(f"task {task_id} is not assigned")
        if task.get("phase") != "assigned":
            raise ValueError(f"cannot unassign active task {task_id}; phase is {task.get('phase')}")
        agent_path = path_for(root, "agents", agent)
        agent_record = read_json(agent_path)
        if not isinstance(agent_record, dict):
            agent_record = {"agent": agent}
        ids = [value for value in active_ids(agent_record) if value != task_id]
        task["agent"] = None
        task["phase"] = "docs"
        task["state"] = "idle"
        task["task_status"] = "ready"
        task["unassigned_at"] = now()
        task["updated_at"] = now()
        agent_record["agent"] = agent
        agent_record["active_task_ids"] = ids
        current_task_id = current_task_for(agent_record, ids)
        if current_task_id is None:
            agent_record.pop("current_task_id", None)
        else:
            agent_record["current_task_id"] = current_task_id
        agent_record["updated_at"] = now()
        write_assignment_record(task_path, task)
        write_assignment_record(agent_path, agent_record)
    print(json.dumps({"task": task, "agent": agent_record}, ensure_ascii=False, indent=2))
    return 0


def command_reconcile(args: argparse.Namespace) -> int:
    workspace = Path(args.workspace).expanduser().resolve()
    root = state_root(workspace, args.state_root)
    changed_tasks: list[str] = []
    changed_agents: list[str] = []
    warnings: list[str] = []
    with assignment_lock(root):
        tasks: dict[str, dict[str, Any]] = {}
        for path in sorted((root / "tasks").glob("*.json")):
            try:
                record = read_json(path)
            except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
                warnings.append(f"invalid task {path.name}: {exc}")
                continue
            if isinstance(record, dict):
                tasks[path.stem] = record
            else:
                warnings.append(f"task {path.name} is not an object")
        agents: dict[str, dict[str, Any]] = {}
        claims: dict[str, list[str]] = {}
        for path in sorted((root / "agents").glob("*.json")):
            try:
                record = read_json(path)
            except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
                warnings.append(f"invalid agent {path.name}: {exc}")
                continue
            if not isinstance(record, dict):
                warnings.append(f"agent {path.name} is not an object")
                continue
            name = record.get("agent") if isinstance(record.get("agent"), str) else path.stem
            agents[name] = record
            for task_id in active_ids(record):
                claims.setdefault(task_id, []).append(name)
        for task_id, task in tasks.items():
            owners = sorted(set(claims.get(task_id, [])))
            owner = task.get("agent") if isinstance(task.get("agent"), str) else None
            if owner and owner not in agents:
                agents[owner] = {"agent": owner}
            can_restore_pipeline_owner = (
                task.get("pipeline_managed") is not True
                or (
                    task.get("phase") == "assigned"
                    and task.get("state") == "busy"
                    and task.get("task_status") == "in_progress"
                )
            )
            if not owner and len(owners) == 1 and task.get("state") != "done" and can_restore_pipeline_owner:
                owner = owners[0]
                task["agent"] = owner
                task["updated_at"] = now()
                write_assignment_record(path_for(root, "tasks", task_id), task)
                changed_tasks.append(task_id)
            elif not owner and len(owners) == 1 and not can_restore_pipeline_owner:
                warnings.append(f"task {task_id} keeps task-side unassignment; removing stale index owner {owners[0]}")
            if len(owners) > 1 and not owner:
                warnings.append(f"task {task_id} has multiple indexed owners: {', '.join(owners)}")
        desired: dict[str, list[str]] = {name: [] for name in agents}
        for task_id, task in tasks.items():
            owner = task.get("agent")
            if isinstance(owner, str) and owner in desired and task.get("state") != "done":
                desired[owner].append(task_id)
        for name, record in agents.items():
            ids = sorted(desired.get(name, []))
            current = current_task_for(record, ids)
            if active_ids(record) != ids or record.get("current_task_id") != current:
                record["agent"] = name
                record["active_task_ids"] = ids
                record["current_task_id"] = current
                record["updated_at"] = now()
                write_assignment_record(path_for(root, "agents", name), record)
                changed_agents.append(name)
    result = {"changed_tasks": sorted(set(changed_tasks)), "changed_agents": sorted(set(changed_agents)), "warnings": warnings}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def command_plan_create(args: argparse.Namespace) -> int:
    workspace = Path(args.workspace).expanduser().resolve()
    root = state_root(workspace, args.state_root)
    with assignment_lock(root):
        return _command_plan_create_impl(args)


def command_task_create(args: argparse.Namespace) -> int:
    workspace = Path(args.workspace).expanduser().resolve()
    root = state_root(workspace, args.state_root)
    with assignment_lock(root):
        return _command_task_create_impl(args)


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


def latest_review(checkpoint: Any, task: Any) -> dict[str, Any] | None:
    candidates = [value for value in (checkpoint, task) if isinstance(value, dict)]
    if not candidates:
        return None
    return max(candidates, key=lambda value: str(value.get("updated_at") or ""))


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
        for key, value in updates.items():
            if value is None:
                continue
            if key == "review" and isinstance(value, dict):
                previous_review = record.get("review") if isinstance(record.get("review"), dict) else {}
                merged_review = {"status": "pending", **previous_review, **{k: v for k, v in value.items() if v is not None}}
                record[key] = merged_review
            else:
                record[key] = value
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
        "review": task.get("review"),
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
        review = latest_review(checkpoint.get("review"), task.get("review"))
        if isinstance(review, dict) and review.get("head_sha") and task.get("commit") and review["head_sha"] != task["commit"]:
            warning.append("review head differs from current task head; re-review required")
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
            "review": review,
            "revision": task.get("revision", 0),
            "previous_task_id": task.get("previous_task_id"),
            "superseded_by": task.get("superseded_by"),
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
    def prunable(path: Path) -> tuple[bool, int]:
        try:
            stat = path.stat()
            if stat.st_mtime >= cutoff:
                return False, 0
            task = read_json(root / "tasks" / path.name)
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return False, 0
        if not isinstance(task, dict) or task.get("state") != "done":
            return False, 0
        return True, stat.st_size

    candidates = []
    candidate_bytes = {}
    for path in sorted((root / "checkpoints").glob("*.json")):
        eligible, size = prunable(path)
        if eligible:
            candidates.append(str(path))
            candidate_bytes[str(path)] = size
    removed = []
    removed_bytes = 0
    if args.apply:
        for name in candidates:
            path = Path(name)
            lock_path = path.with_suffix(path.suffix + ".lock")
            with open(lock_path, "a+", encoding="utf-8") as lock_stream:
                fcntl.flock(lock_stream.fileno(), fcntl.LOCK_EX)
                try:
                    eligible, size = prunable(path)
                    if eligible:
                        path.unlink()
                        removed.append(name)
                        removed_bytes += size
                except (OSError, ValueError, TypeError, json.JSONDecodeError):
                    pass
                finally:
                    fcntl.flock(lock_stream.fileno(), fcntl.LOCK_UN)
    print(json.dumps({"dry_run": not args.apply, "removed": removed,
                      "candidates": candidates, "count": len(removed) if args.apply else len(candidates),
                      "bytes": removed_bytes if args.apply else sum(candidate_bytes.values())},
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
    parser.add_argument("--review-status", choices=sorted(REVIEW_STATUSES))
    parser.add_argument("--review-summary")
    parser.add_argument("--goal")
    parser.add_argument("--branch")
    parser.add_argument("--commit")
    parser.add_argument("--pr", type=int)
    parser.add_argument("--test-status")
    parser.add_argument("--test-summary")
    parser.add_argument("--event")
    parser.add_argument("--blocked-reason")
    parser.add_argument("--clear-blocked", action="store_true")


def plan_parser(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--workspace", default=".")
    parser.add_argument("--state-root")
    parser.add_argument("--plan-id", required=True)
    parser.add_argument("--title", required=True)
    parser.add_argument("--requirement", required=True)
    parser.add_argument("--users", action="append", default=[])
    parser.add_argument("--acceptance-criteria", action="append", default=[])
    parser.add_argument("--scope", action="append", default=[])
    parser.add_argument("--non-goals", action="append", default=[])
    parser.add_argument("--constraints", action="append", default=[])
    parser.add_argument("--open-questions", action="append", default=[])
    parser.add_argument("--assumptions", action="append", default=[])
    parser.add_argument("--risk-level", choices=("low", "medium", "high"), default="medium")
    parser.add_argument("--force", action="store_true")


def task_create_parser(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--workspace", default=".")
    parser.add_argument("--state-root")
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--plan-id", required=True)
    parser.add_argument("--summary", required=True)
    parser.add_argument("--goal", required=True)
    parser.add_argument("--next-action")
    parser.add_argument("--acceptance-criteria", action="append", default=[])
    parser.add_argument("--agent")
    parser.add_argument("--force", action="store_true")


def revision_create_parser(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--workspace", default=".")
    parser.add_argument("--state-root")
    parser.add_argument("--source-task-id", required=True)
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--summary", required=True)
    parser.add_argument("--goal", required=True)
    parser.add_argument("--next-action")
    parser.add_argument("--failure-reason", required=True)
    parser.add_argument("--previous-evidence", action="append", default=[])


def assignment_parser(parser: argparse.ArgumentParser, *, require_agent: bool = False) -> None:
    parser.add_argument("--workspace", default=".")
    parser.add_argument("--state-root")
    parser.add_argument("--task-id", required=True)
    if require_agent:
        parser.add_argument("--agent", required=True)


def command_status(args: argparse.Namespace) -> int:
    agent = safe_id(args.agent, "agent")
    task_id = safe_id(args.task_id, "task_id")
    validate_enum(args.phase, PHASES, "phase")
    validate_enum(args.state, STATES, "state")
    validate_enum(args.task_status, TASK_STATUSES, "task_status")
    validate_enum(args.review_status, REVIEW_STATUSES, "review_status")
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
    if args.review_status or args.review_summary:
        previous_review = previous_task.get("review") if isinstance(previous_task.get("review"), dict) else {}
        task_updates["review"] = {
            "status": args.review_status,
            "summary": args.review_summary,
            "head_sha": ((args.commit or previous_task.get("commit")) if args.review_status
                         else previous_review.get("head_sha")),
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
        lock=True,
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
            args.review_status, args.review_summary,
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
    plan_create = sub.add_parser("plan-create")
    plan_parser(plan_create)
    task_create = sub.add_parser("task-create")
    task_create_parser(task_create)
    revision_create = sub.add_parser("revision-create")
    revision_create_parser(revision_create)
    task_list = sub.add_parser("task-list")
    task_list.add_argument("--workspace", default=".")
    task_list.add_argument("--state-root")
    task_list.add_argument("--plan-id")
    plan_approve = sub.add_parser("plan-approve")
    plan_approve.add_argument("--workspace", default=".")
    plan_approve.add_argument("--state-root")
    plan_approve.add_argument("--plan-id", required=True)
    assign = sub.add_parser("assign")
    assignment_parser(assign, require_agent=True)
    unassign = sub.add_parser("unassign")
    assignment_parser(unassign)
    reconcile = sub.add_parser("reconcile")
    reconcile.add_argument("--workspace", default=".")
    reconcile.add_argument("--state-root")
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
        if args.command == "plan-create":
            return command_plan_create(args)
        if args.command == "task-create":
            return command_task_create(args)
        if args.command == "revision-create":
            return command_revision_create(args)
        if args.command == "task-list":
            return command_task_list(args)
        if args.command == "plan-approve":
            return command_plan_approve(args)
        if args.command == "assign":
            return command_assign(args)
        if args.command == "unassign":
            return command_unassign(args)
        if args.command == "reconcile":
            return command_reconcile(args)
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

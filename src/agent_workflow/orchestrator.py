from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from .status import reject_secret_values, safe_id, state_root
from .workspace_inspect import inspect_workspace


OPERATIONS = {"interview", "plan", "critic", "verifier"}
INTERVIEW_LIST_FIELDS = ("users", "scope", "non_goals", "constraints", "acceptance_criteria", "open_questions", "assumptions")


def _workspace_file(workspace: Path, value: str, label: str) -> Path:
    path = (workspace / value).resolve()
    if workspace not in path.parents or any(part.startswith(".") for part in path.relative_to(workspace).parts):
        raise ValueError(f"{label} must be a visible workspace-relative file")
    if not path.is_file():
        raise FileNotFoundError(path)
    return path


def _read_object(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid {label}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    reject_secret_values(value, label)
    return value


def _provider_command(config_path: Path, provider: str) -> list[str]:
    config = _read_object(config_path, "provider config")
    providers = config.get("providers")
    if not isinstance(providers, dict):
        raise ValueError("provider config requires a providers object")
    command = providers.get(provider)
    if not isinstance(command, list) or not command or not all(isinstance(item, str) and item for item in command):
        raise ValueError(f"provider {provider} requires a non-empty command list")
    return command


def _output_path(workspace: Path, value: str, forbidden: set[Path]) -> Path:
    path = (workspace / value).resolve()
    relative = path.relative_to(workspace) if workspace in path.parents else None
    if relative is None or any(part.startswith(".") for part in relative.parts):
        raise ValueError("output must be a visible workspace-relative path")
    if path.exists() and not path.is_file():
        raise ValueError("output must be a regular file")
    if path in forbidden:
        raise ValueError("output must not overwrite input or config")
    return path


def _write_result(workspace: Path, path: Path, result: dict[str, Any]) -> None:
    payload = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if path.resolve() != path or workspace not in path.resolve().parents:
        raise ValueError("output changed outside workspace")
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.resolve() != path or workspace not in path.resolve().parents:
        raise ValueError("output changed outside workspace")
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        path.chmod(0o600)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _interactive_payload() -> dict[str, Any]:
    def answer(label: str, required: bool = False) -> str:
        while True:
            value = input(f"{label}: ").strip()
            if value or not required:
                return value
            print(f"{label} is required")

    def list_answer(label: str) -> list[str]:
        value = answer(f"{label} (comma-separated, blank for none)")
        return [item.strip() for item in value.split(",") if item.strip()]

    payload: dict[str, Any] = {
        "background": answer("Background", required=True),
        "users": list_answer("Users"),
        "problem": answer("Problem", required=True),
        "desired_outcome": answer("Desired outcome", required=True),
    }
    for field in ("scope", "non_goals", "constraints", "acceptance_criteria", "open_questions", "assumptions"):
        payload[field] = list_answer(field)
    risk_level = answer("Risk level (low/medium/high)") or "medium"
    if risk_level not in {"low", "medium", "high"}:
        raise ValueError("risk level must be low, medium, or high")
    payload["risk_level"] = risk_level
    return payload


def run_provider(args: argparse.Namespace) -> int:
    workspace = Path(args.workspace).expanduser().resolve()
    provider = safe_id(args.provider, "provider")
    if args.operation not in OPERATIONS:
        raise ValueError(f"unsupported operation: {args.operation}")
    input_path = _workspace_file(workspace, args.input, "input") if args.input else None
    config_path = _workspace_file(workspace, args.config, "config")
    output_path = _output_path(workspace, args.output, {path for path in (input_path, config_path) if path}) if args.output else None
    payload = _interactive_payload() if args.interactive else _read_object(input_path, "provider input")
    preflight = inspect_workspace(workspace, args.docs_dir, state_root(workspace, args.state_root), args.max_files)
    reject_secret_values(preflight, "preflight")
    request = {
        "schema_version": 1,
        "operation": args.operation,
        "provider": provider,
        "preflight": preflight,
        "payload": payload,
    }
    command = _provider_command(config_path, provider)
    try:
        completed = subprocess.run(
            command,
            input=json.dumps(request, ensure_ascii=False),
            capture_output=True,
            text=True,
            timeout=args.timeout,
            check=False,
            cwd=workspace,
            env=os.environ.copy(),
        )
    except subprocess.TimeoutExpired as exc:
        raise ValueError(f"provider timed out after {args.timeout}s") from exc
    if completed.returncode != 0:
        raise ValueError(f"provider exited with {completed.returncode}")
    try:
        response = json.loads(completed.stdout)
    except (ValueError, TypeError, json.JSONDecodeError) as exc:
        raise ValueError(f"provider returned invalid JSON: {exc}") from exc
    if not isinstance(response, dict):
        raise ValueError("provider response must be a JSON object")
    if response.get("schema_version") != 1 or response.get("operation") != args.operation:
        raise ValueError("provider response schema_version or operation does not match request")
    if "result" not in response or not isinstance(response["result"], dict):
        raise ValueError("provider response requires a result object")
    reject_secret_values(response, "provider response")
    if output_path:
        _write_result(workspace, output_path, response["result"])
    print(json.dumps(response, ensure_ascii=False, indent=2))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="agent-orchestrator")
    parser.add_argument("operation", choices=sorted(OPERATIONS))
    parser.add_argument("--workspace", default=".")
    parser.add_argument("--state-root")
    parser.add_argument("--docs-dir", default="docs")
    parser.add_argument("--provider", required=True)
    parser.add_argument("--config", required=True)
    inputs = parser.add_mutually_exclusive_group(required=True)
    inputs.add_argument("--input")
    inputs.add_argument("--interactive", action="store_true")
    parser.add_argument("--output")
    parser.add_argument("--max-files", type=int, default=200)
    parser.add_argument("--timeout", type=int, default=300)
    try:
        args = parser.parse_args(argv)
        if args.timeout < 1 or args.timeout > 3600:
            raise ValueError("timeout must be between 1 and 3600")
        return run_provider(args)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"agent-orchestrator: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

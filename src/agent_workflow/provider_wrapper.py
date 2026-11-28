from __future__ import annotations

import json
import os
import signal
import shlex
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


SYSTEM_PROMPT = """You are an orchestrator planning assistant. Do not edit files, run tools, or save transcripts.
Use the supplied workspace preflight and payload. Return only a JSON object containing the requested result.
The result must be suitable for the operation named in the request. For interview, include background,
problem, desired_outcome, users, scope, non_goals, constraints, acceptance_criteria, open_questions,
assumptions, and risk_level."""


def _json_document(text: str) -> Any:
    candidate = text.strip()
    if candidate.startswith("```"):
        lines = candidate.splitlines()
        candidate = "\n".join(lines[1:-1]).strip()
    return json.loads(candidate)


def _result_from_output(text: str) -> dict[str, Any]:
    value = _json_document(text)
    if isinstance(value, dict) and "result" in value and not isinstance(value.get("result"), (dict, str)):
        raise ValueError("provider result envelope has invalid result")
    if isinstance(value, dict) and isinstance(value.get("result"), (dict, str)):
        value = value["result"]
        if isinstance(value, str):
            value = _json_document(value)
    if not isinstance(value, dict):
        raise ValueError("provider output must be a JSON object")
    return value


def _run_process(command: list[str], prompt: str, workspace: Path) -> subprocess.CompletedProcess[str]:
    timeout = int(os.environ.get("AGENT_WORKFLOW_WRAPPER_TIMEOUT", "300"))
    process = subprocess.Popen(
        command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, cwd=workspace,
    )
    try:
        stdout, stderr = process.communicate(prompt, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        os.killpg(process.pid, signal.SIGKILL)
        process.communicate()
        raise RuntimeError("provider wrapper timed out") from exc
    return subprocess.CompletedProcess(command, process.returncode, stdout, stderr)


def _prompt(request: dict[str, Any]) -> str:
    return (
        f"{SYSTEM_PROMPT}\n\n"
        f"Operation: {request['operation']}\n"
        "Return only the result JSON object, without markdown or commentary.\n"
        f"Workspace preflight:\n{json.dumps(request['preflight'], ensure_ascii=False, indent=2)}\n"
        f"Input payload:\n{json.dumps(request['payload'], ensure_ascii=False, indent=2)}"
    )


def _run_claude(prompt: str, workspace: Path) -> str:
    command = shlex.split(os.environ.get("AGENT_WORKFLOW_CLAUDE_COMMAND", "claude"))
    completed = _run_process(
        command + [
            "--print", "--output-format", "json", "--no-session-persistence",
            "--restricted", "--strict-mcp-config", "--setting-sources", "",
            "--tools", "", "--system-prompt", SYSTEM_PROMPT,
        ], prompt, workspace)
    if completed.returncode != 0:
        raise RuntimeError(f"claude wrapper exited with {completed.returncode}")
    return completed.stdout


def _run_codex(prompt: str, workspace: Path) -> str:
    command = shlex.split(os.environ.get("AGENT_WORKFLOW_CODEX_COMMAND", "codex"))
    with tempfile.NamedTemporaryFile(prefix="agent-provider-", suffix=".json", delete=False) as output:
        output_path = Path(output.name)
    try:
        completed = _run_process(
            command + [
                "exec", "--ephemeral", "--skip-git-repo-check", "-s", "read-only",
                "-o", str(output_path), "-",
            ], prompt, workspace)
        if completed.returncode != 0:
            raise RuntimeError(f"codex wrapper exited with {completed.returncode}")
        return output_path.read_text(encoding="utf-8")
    finally:
        output_path.unlink(missing_ok=True)


def _run_deepseek(prompt: str, workspace: Path) -> str:
    raw = os.environ.get("AGENT_WORKFLOW_DEEPSEEK_COMMAND")
    if not raw:
        raise RuntimeError("AGENT_WORKFLOW_DEEPSEEK_COMMAND is not configured")
    completed = _run_process(shlex.split(raw) + ["--print", "-"], prompt, workspace)
    if completed.returncode != 0:
        raise RuntimeError(f"deepseek wrapper exited with {completed.returncode}")
    return completed.stdout


def run(provider: str, request: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(request, dict) or request.get("schema_version") != 1:
        raise ValueError("request schema_version must be 1")
    if not isinstance(request.get("operation"), str) or not isinstance(request.get("preflight"), dict):
        raise ValueError("request requires operation and preflight")
    if not isinstance(request.get("payload"), dict):
        raise ValueError("request payload must be an object")
    workspace = Path(request["preflight"].get("workspace_root", ".")).expanduser().resolve()
    prompt = _prompt(request)
    if provider == "claude":
        output = _run_claude(prompt, workspace)
    elif provider == "codex":
        output = _run_codex(prompt, workspace)
    elif provider == "deepseek":
        output = _run_deepseek(prompt, workspace)
    else:
        raise ValueError(f"unsupported provider: {provider}")
    result = _result_from_output(output)
    if request["operation"] == "interview":
        required = ("background", "problem", "desired_outcome")
        if any(not isinstance(result.get(key), str) or not result[key].strip() for key in required):
            raise ValueError("interview result requires background, problem, and desired_outcome")
        risk_level = result.get("risk_level", "medium")
        if risk_level not in {"low", "medium", "high"}:
            raise ValueError("interview result risk_level must be low, medium, or high")
    return {"schema_version": 1, "operation": request["operation"], "result": result}


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]
    if len(argv) != 1 or argv[0] not in {"claude", "codex", "deepseek"}:
        print("usage: agent-provider {claude|codex|deepseek}", file=sys.stderr)
        return 64
    try:
        request = json.load(sys.stdin)
        print(json.dumps(run(argv[0], request), ensure_ascii=False))
        return 0
    except (OSError, ValueError, RuntimeError, json.JSONDecodeError) as exc:
        print(f"agent-provider: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

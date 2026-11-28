from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from .status import reject_secret_values, safe_id, state_root
from .workspace_inspect import inspect_workspace


def _existing_file(workspace: Path, value: str, label: str) -> Path:
    path = (workspace / value).resolve()
    if workspace not in path.parents or any(part.startswith(".") for part in path.relative_to(workspace).parts):
        raise ValueError(f"{label} must be a visible workspace-relative file")
    if not path.is_file():
        raise FileNotFoundError(path)
    return path


def _output_file(workspace: Path, value: str) -> Path:
    path = (workspace / value).resolve()
    if workspace not in path.parents or any(part.startswith(".") for part in path.relative_to(workspace).parts):
        raise ValueError("output must be a visible workspace-relative path")
    if path.exists() and not path.is_file():
        raise ValueError("output must be a regular file")
    return path


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(value, ensure_ascii=False, indent=2) + "\n"
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


def _run_one(root: Path, args: argparse.Namespace, provider: str, output: Path) -> dict[str, Any]:
    command = [
        sys.executable, str(root / "bin" / "agent-orchestrator"), args.operation,
        "--workspace", str(args.workspace), "--provider", provider,
        "--config", args.config, "--input", args.input,
        "--output", str(output), "--docs-dir", args.docs_dir,
        "--max-files", str(args.max_files), "--timeout", str(args.timeout),
    ]
    if args.state_root:
        command.extend(("--state-root", args.state_root))
    completed = subprocess.run(command, capture_output=True, text=True, check=False)
    if completed.returncode != 0:
        raise RuntimeError(f"provider {provider} exited with {completed.returncode}")
    try:
        result = json.loads(output.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        raise ValueError(f"provider {provider} returned invalid result") from exc
    if not isinstance(result, dict):
        raise ValueError(f"provider {provider} result must be an object")
    reject_secret_values(result, f"provider {provider} result")
    return result


def run(args: argparse.Namespace) -> int:
    workspace = Path(args.workspace).expanduser().resolve()
    if args.operation not in {"critic", "verifier"}:
        raise ValueError("fanout supports only critic or verifier")
    providers = [safe_id(provider, "provider") for provider in args.providers]
    if not providers or len(set(providers)) != len(providers):
        raise ValueError("at least one unique provider is required")
    input_path = _existing_file(workspace, args.input, "input")
    config_path = _existing_file(workspace, args.config, "config")
    output_dir = (workspace / args.output_dir).resolve()
    if workspace not in output_dir.parents or any(part.startswith(".") for part in output_dir.relative_to(workspace).parts):
        raise ValueError("output_dir must be a visible workspace-relative directory")
    output_path = _output_file(workspace, args.output) if args.output else output_dir / f"{args.operation}-findings.json"
    if output_path in {input_path, config_path}:
        raise ValueError("output must not overwrite input or config")
    preflight = inspect_workspace(workspace, args.docs_dir, state_root(workspace, args.state_root), args.max_files)
    reject_secret_values(preflight, "preflight")
    root = Path(__file__).resolve().parents[2]
    outputs = {provider: output_dir / f"{provider}.json" for provider in providers}
    if output_path in outputs.values():
        raise ValueError("aggregate output must not overwrite a provider result")
    findings: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=len(providers)) as executor:
        futures = {
            executor.submit(_run_one, root, args, provider, outputs[provider]): provider
            for provider in providers
        }
        for future in as_completed(futures):
            provider = futures[future]
            finding = {
                "provider": provider,
                "operation": args.operation,
                "request_head": (preflight.get("git") or {}).get("head"),
            }
            try:
                finding["result"] = future.result()
            except (OSError, ValueError, RuntimeError) as exc:
                finding["error"] = str(exc)
            findings.append(finding)
    findings.sort(key=lambda item: item["provider"])
    current = inspect_workspace(workspace, args.docs_dir, state_root(workspace, args.state_root), args.max_files)
    head_changed = (preflight.get("git") or {}).get("head") != (current.get("git") or {}).get("head")
    distinct = {
        json.dumps(item["result"], ensure_ascii=False, sort_keys=True)
        for item in findings if "result" in item
    }
    aggregate = {
        "schema_version": 1,
        "operation": args.operation,
        "status": "needs_human" if len(distinct) > 1 or any("error" in item for item in findings) or head_changed else "pending",
        "provider_count": len(findings),
        "head_changed": head_changed,
        "findings": findings,
    }
    reject_secret_values(aggregate, "aggregate findings")
    _atomic_json(output_path, aggregate)
    print(json.dumps(aggregate, ensure_ascii=False, indent=2))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="agent-orchestrator-fanout")
    parser.add_argument("operation", choices=("critic", "verifier"))
    parser.add_argument("--workspace", default=".")
    parser.add_argument("--state-root")
    parser.add_argument("--docs-dir", default="docs")
    parser.add_argument("--provider", dest="providers", action="append", required=True)
    parser.add_argument("--config", required=True)
    parser.add_argument("--input", required=True)
    parser.add_argument("--output-dir", default="orchestrator-findings")
    parser.add_argument("--output")
    parser.add_argument("--max-files", type=int, default=200)
    parser.add_argument("--timeout", type=int, default=300)
    try:
        args = parser.parse_args(argv)
        if args.timeout <= 5 or args.timeout > 3600:
            raise ValueError("timeout must be between 6 and 3600")
        return run(args)
    except (OSError, ValueError, RuntimeError, json.JSONDecodeError) as exc:
        print(f"agent-orchestrator-fanout: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

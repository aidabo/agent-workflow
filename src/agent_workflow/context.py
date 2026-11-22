from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


def sensitive_part(part: str) -> bool:
    lower = part.lower()
    return (
        lower == ".ssh" or lower == ".aws" or lower == ".notify" or lower == ".clawhip"
        or lower == ".env" or lower.startswith(".env.")
        or lower in {"secret", "secrets", "credential", "credentials"}
        or lower.startswith("secret.") or lower.startswith("secrets.")
        or lower.startswith("credential.") or lower.startswith("credentials.")
    )


def expand_path(value: str, base: Path) -> Path:
    expanded = os.path.expandvars(os.path.expanduser(value))
    if "${" in expanded:
        raise ValueError(f"unresolved path variable: {value}")
    path = Path(expanded)
    if not path.is_absolute():
        path = base / path
    return path.resolve()


def check_path(path: Path, workspace: Path, allow_external: bool = False) -> str | None:
    try:
        relative = path.relative_to(workspace)
    except ValueError:
        if not allow_external:
            raise ValueError(f"reference path is outside workspace: {path}")
        warning = f"external non-secret reference allowed: {path}"
        parts = path.parts
    else:
        warning = None
        parts = relative.parts
    if any(sensitive_part(part) for part in parts):
        raise ValueError(f"sensitive reference path is denied: {path}")
    if not path.exists():
        raise FileNotFoundError(path)
    return warning


def merge_unique(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value not in seen:
            result.append(value)
            seen.add(value)
    return result


def resolve_context(context_file: Path, project: str | None, task_file: str | None) -> dict[str, Any]:
    data = json.loads(context_file.read_text(encoding="utf-8"))
    workspace_value = data.get("workspace_root")
    if not workspace_value:
        raise ValueError("context config requires workspace_root")
    workspace = expand_path(str(workspace_value), context_file.parent)
    project_data = (data.get("projects") or {}).get(project or "", {})
    task_data: dict[str, Any] = {}
    if task_file:
        task_data = json.loads(Path(task_file).expanduser().read_text(encoding="utf-8"))

    dirs: dict[str, list[str]] = {}
    warnings: list[str] = []
    for key in ("screenshot_dirs", "reference_dirs"):
        raw = [
            *(data.get(f"default_{key}") or []),
            *(project_data.get(key) or []),
            *(task_data.get(key) or []),
        ]
        resolved: list[str] = []
        for item in raw:
            path = expand_path(str(item), workspace)
            warning = check_path(path, workspace, bool(data.get("allow_external_nonsecret", False)))
            if warning:
                warnings.append(warning)
            resolved.append(str(path))
        dirs[key] = merge_unique(resolved)

    screenshots: list[str] = []
    for item in [*(project_data.get("screenshots") or []), *(task_data.get("screenshots") or [])]:
        path = expand_path(str(item), workspace)
        warning = check_path(path, workspace, bool(data.get("allow_external_nonsecret", False)))
        if warning:
            warnings.append(warning)
        screenshots.append(str(path))

    repo_dir_value = task_data.get("repo_dir") or project_data.get("repo_dir")
    repo_dir = None
    if repo_dir_value:
        repo_dir_path = expand_path(str(repo_dir_value), workspace)
        warning = check_path(repo_dir_path, workspace, bool(data.get("allow_external_nonsecret", False)))
        if warning:
            warnings.append(warning)
        repo_dir = str(repo_dir_path)

    return {
        "workspace_root": str(workspace),
        "project": project,
        "repo": project_data.get("repo") or task_data.get("repo"),
        "repo_dir": repo_dir,
        "screenshots": merge_unique(screenshots),
        "screenshot_dirs": dirs["screenshot_dirs"],
        "reference_dirs": dirs["reference_dirs"],
        "warnings": warnings,
    }

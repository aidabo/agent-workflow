from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any


SENSITIVE = re.compile(r"(^|/)(\.env(?:\.|$)|\.ssh|\.aws|\.notify|\.clawhip|credentials?|secrets?)(/|$)", re.I)


def expand_path(value: str, base: Path) -> Path:
    expanded = os.path.expandvars(os.path.expanduser(value))
    if "${" in expanded:
        raise ValueError(f"unresolved path variable: {value}")
    path = Path(expanded)
    if not path.is_absolute():
        path = base / path
    return path.resolve()


def check_path(path: Path, workspace: Path, allow_external: bool = False) -> None:
    if SENSITIVE.search(str(path)):
        raise ValueError(f"sensitive reference path is denied: {path}")
    try:
        path.relative_to(workspace)
    except ValueError:
        if not allow_external:
            raise ValueError(f"reference path is outside workspace: {path}")
    if not path.exists():
        raise FileNotFoundError(path)


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
    workspace = expand_path(str(data["workspace_root"]), context_file.parent)
    project_data = (data.get("projects") or {}).get(project or "", {})
    task_data: dict[str, Any] = {}
    if task_file:
        task_data = json.loads(Path(task_file).expanduser().read_text(encoding="utf-8"))

    dirs: dict[str, list[str]] = {}
    for key in ("screenshot_dirs", "reference_dirs"):
        raw = [
            *(data.get(f"default_{key}") or []),
            *(project_data.get(key) or []),
            *(task_data.get(key) or []),
        ]
        resolved: list[str] = []
        for item in raw:
            path = expand_path(str(item), workspace)
            check_path(path, workspace, bool(data.get("allow_external_nonsecret", False)))
            resolved.append(str(path))
        dirs[key] = merge_unique(resolved)

    screenshots = [
        str(expand_path(str(item), workspace))
        for item in [*(project_data.get("screenshots") or []), *(task_data.get("screenshots") or [])]
    ]
    for item in screenshots:
        path = Path(item)
        check_path(path, workspace, bool(data.get("allow_external_nonsecret", False)))

    return {
        "workspace_root": str(workspace),
        "project": project,
        "repo": project_data.get("repo") or task_data.get("repo"),
        "repo_dir": project_data.get("repo_dir") or task_data.get("repo_dir"),
        "screenshots": merge_unique(screenshots),
        "screenshot_dirs": dirs["screenshot_dirs"],
        "reference_dirs": dirs["reference_dirs"],
    }

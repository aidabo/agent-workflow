from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any


SKIP_DIRS = {".git", ".agent-workflow", ".next", "build", "dist", "node_modules"}
MANIFESTS = {
    "AGENTS.md", "Makefile", "Cargo.toml", "go.mod", "package.json", "pyproject.toml",
    "requirements.txt", "yarn.lock", "package-lock.json", "pnpm-lock.yaml",
}
SOURCE_DIR_NAMES = {"app", "apps", "client", "lib", "packages", "server", "src", "test", "tests"}


def _relative_files(root: Path, limit: int) -> tuple[list[Path], bool]:
    files: list[Path] = []
    for current, directories, names in os.walk(root, topdown=True, followlinks=False):
        directories[:] = sorted(
            name for name in directories
            if name not in SKIP_DIRS
            and not name.startswith(".")
            and not (Path(current) / name).is_symlink()
        )
        for name in sorted(names):
            path = Path(current) / name
            if path.is_symlink() or not path.is_file():
                continue
            if len(files) >= limit:
                return files, True
            files.append(path)
    return files, False


def _headings(path: Path) -> list[str]:
    if path.suffix.lower() not in {".md", ".markdown", ".mdx"}:
        return []
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []
    headings: list[str] = []
    fence: str | None = None
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("```") or stripped.startswith("~~~"):
            marker = stripped[:3]
            fence = None if fence == marker else marker if fence is None else fence
            continue
        if fence is None and re.match(r"^#{1,6}\s+", stripped):
            headings.append(stripped[:160])
            if len(headings) == 20:
                break
    return headings


def _git_info(workspace: Path, warnings: list[str]) -> dict[str, Any]:
    def run(*args: str) -> str | None:
        try:
            result = subprocess.run(
                ["git", "-C", str(workspace), *args],
                capture_output=True,
                text=True,
                check=False,
            )
        except OSError:
            return None
        if result.returncode != 0:
            return None
        return result.stdout.strip()

    root = run("rev-parse", "--show-toplevel")
    if not root:
        warnings.append("workspace is not a git repository")
        return {"is_repository": False, "dirty": None}
    branch = run("symbolic-ref", "--short", "HEAD") or "(detached)"
    head = run("rev-parse", "HEAD")
    status = run("status", "--porcelain") or ""
    return {
        "is_repository": True,
        "root": root,
        "branch": branch,
        "head": head,
        "dirty": bool(status),
    }


def _state_summary(root: Path, warnings: list[str]) -> dict[str, Any]:
    summary: dict[str, Any] = {"root": str(root), "requirements": {}, "plans": {}, "tasks": {}}
    for kind in ("requirements", "plans", "tasks"):
        counts: dict[str, int] = {}
        malformed = 0
        directory = root / kind
        for path in sorted(directory.glob("*.json")) if directory.is_dir() else []:
            try:
                value = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError, TypeError, json.JSONDecodeError):
                malformed += 1
                continue
            if not isinstance(value, dict):
                malformed += 1
                continue
            status = value.get("task_status") if kind == "tasks" else value.get("status")
            if status is None:
                status = "unknown"
            if not isinstance(status, str):
                malformed += 1
                continue
            counts[status] = counts.get(status, 0) + 1
        summary[kind] = {"total": sum(counts.values()) + malformed, "by_status": counts, "malformed": malformed}
        if malformed:
            warnings.append(f"{kind} contains {malformed} unreadable JSON file(s)")
    return summary


def inspect_workspace(workspace: Path, docs_dir: str, state_root: Path, max_files: int) -> dict[str, Any]:
    workspace = workspace.resolve()
    if max_files < 1 or max_files > 2000:
        raise ValueError("max_files must be between 1 and 2000")
    docs = (workspace / docs_dir).resolve()
    if workspace not in docs.parents and docs != workspace:
        raise ValueError("docs_dir must stay inside workspace")
    warnings: list[str] = []
    if docs.exists() and not docs.is_dir():
        raise ValueError("docs_dir must be a directory")
    files, truncated = _relative_files(docs, max_files) if docs.is_dir() else ([], False)
    if not docs.exists():
        warnings.append(f"docs directory does not exist: {docs}")
    doc_records = []
    for path in files:
        doc_records.append({
            "path": str(path.relative_to(workspace)),
            "bytes": path.stat().st_size,
            "headings": _headings(path),
        })
    if truncated:
        warnings.append(f"docs listing truncated at {max_files} files")
    top_level = sorted(path.name for path in workspace.iterdir() if not path.name.startswith("."))
    source_dirs = sorted(
        path.name for path in workspace.iterdir()
        if path.is_dir() and path.name in SOURCE_DIR_NAMES
    )
    manifests = sorted(name for name in top_level if name in MANIFESTS)
    return {
        "schema_version": 1,
        "workspace_root": str(workspace),
        "git": _git_info(workspace, warnings),
        "source": {
            "top_level": top_level,
            "source_dirs": source_dirs,
            "manifests": manifests,
        },
        "docs": {
            "root": str(docs),
            "files": doc_records,
            "file_count": len(doc_records),
            "truncated": truncated,
        },
        "workflow_state": _state_summary(state_root.resolve(), warnings),
        "warnings": warnings,
    }

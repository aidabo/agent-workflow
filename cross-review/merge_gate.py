#!/usr/bin/env python3
"""Evaluate whether a PR is eligible for the opt-in auto-merge phase.

This module intentionally does not merge anything. The first phase is a
read-only gate so that its decisions can be observed before a merge executor
is enabled.
"""
from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable


BLOCKED_PATH_PARTS = {".github", "deploy", "infra", "migrations", "terraform"}
BLOCKED_PATH_NAMES = {
    ".env",
    ".env.local",
    ".env.production",
    "docker-compose.prod.yml",
    "docker-compose.production.yml",
}


@dataclass
class GateResult:
    eligible: bool
    reasons: list[str] = field(default_factory=list)
    changed_files: list[str] = field(default_factory=list)


def _blocked_paths(paths: Iterable[str]) -> list[str]:
    blocked = []
    for path in paths:
        parts = Path(path).parts
        name = parts[-1] if parts else path
        if (BLOCKED_PATH_PARTS.intersection(parts)
                or name in BLOCKED_PATH_NAMES
                or name.startswith(".env")):
            blocked.append(path)
    return sorted(blocked)


def evaluate(
    pr: dict,
    reviews: dict[str, dict],
    *,
    expected_reviewers: Iterable[str],
    changed_files: Iterable[str],
    require_auto_merge_label: str = "automation:auto-merge",
    base_branch: str = "main",
    require_tests: bool = True,
) -> GateResult:
    """Return a conservative, explainable decision for one PR head."""
    reasons: list[str] = []
    files = sorted(set(changed_files))
    expected = set(expected_reviewers)
    actual = set(reviews)

    if not expected:
        reasons.append("no expected reviewers configured")

    if pr.get("state") != "OPEN":
        reasons.append(f"PR state is {pr.get('state', '?')}, not OPEN")
    if pr.get("isDraft"):
        reasons.append("draft PR")
    if pr.get("baseRefName") != base_branch:
        reasons.append(f"base branch is {pr.get('baseRefName', '?')}, expected {base_branch}")
    labels = {
        label.get("name", label) if isinstance(label, dict) else label
        for label in pr.get("labels", [])
    }
    if require_auto_merge_label not in labels:
        reasons.append(f"missing opt-in label: {require_auto_merge_label}")

    missing = sorted(expected - actual)
    if missing:
        reasons.append("missing reviewer report: " + ", ".join(missing))
    unexpected = sorted(actual - expected) if expected else []
    if unexpected:
        reasons.append("unexpected reviewer report: " + ", ".join(unexpected))
    for reviewer in sorted(expected & actual):
        report = reviews[reviewer]
        if report.get("verdict") != "APPROVE":
            reasons.append(f"{reviewer}: verdict is {report.get('verdict', '?')}")
        if report.get("tests_failed"):
            reasons.append(f"{reviewer}: tests failed")
        if report.get("secrets"):
            reasons.append(f"{reviewer}: secret scan failed")
        if require_tests and not report.get("tests_ran"):
            reasons.append(f"{reviewer}: no test result")

    blocked = _blocked_paths(files)
    if blocked:
        reasons.append("blocked file paths: " + ", ".join(blocked))

    return GateResult(not reasons, reasons, files)


def review_reports_for_head(
    state_dir: Path, report_dir: Path, repo: str, pr: int, head: str
) -> dict[str, dict]:
    """Load only reports completed for the current PR head."""
    from status import review_rounds

    cfg = {"name": repo, "state_dir": str(state_dir), "report_dir": str(report_dir)}
    short = head[:8]
    return next(
        (reports for sha, _when, reports in review_rounds(cfg, repo, pr) if sha == short),
        {},
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="dry-run auto-merge eligibility gate")
    parser.add_argument("--json", required=True, dest="pr_json")
    parser.add_argument("--repo-name", required=True)
    parser.add_argument("--pr", required=True, type=int)
    parser.add_argument("--state-dir", required=True, type=Path)
    parser.add_argument("--report-dir", required=True, type=Path)
    parser.add_argument("--reviewers", required=True)
    parser.add_argument("--changed-files", required=True)
    args = parser.parse_args()

    pr = json.loads(args.pr_json)
    reviews = review_reports_for_head(
        args.state_dir, args.report_dir, args.repo_name, args.pr, pr["headRefOid"]
    )
    result = evaluate(
        pr,
        reviews,
        expected_reviewers=args.reviewers.split(),
        changed_files=args.changed_files.splitlines(),
    )
    if result.eligible:
        print(f"ELIGIBLE: {args.repo_name} #{args.pr} head={pr['headRefOid'][:8]} (dry-run only)")
        return 0
    print(f"BLOCKED: {args.repo_name} #{args.pr} head={pr['headRefOid'][:8]}")
    for reason in result.reasons:
        print(f"- {reason}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

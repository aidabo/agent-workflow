#!/usr/bin/env python3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cross-review"))
from merge_gate import evaluate, review_reports_for_head  # noqa: E402


def report(verdict="APPROVE", *, tests_ran=True, tests_failed=False, secrets=False):
    return {
        "verdict": verdict,
        "tests_ran": tests_ran,
        "tests_failed": tests_failed,
        "secrets": secrets,
    }


class MergeGate(unittest.TestCase):
    def setUp(self):
        self.pr = {
            "state": "OPEN",
            "isDraft": False,
            "baseRefName": "main",
            "labels": [{"name": "automation:auto-merge"}],
        }

    def gate(self, reviews=None, files=("docs/guide.md",)):
        return evaluate(
            self.pr,
            reviews or {"claude": report(), "deepseek": report()},
            expected_reviewers=("claude", "deepseek"),
            changed_files=files,
        )

    def test_all_required_reviewers_and_tests_are_eligible(self):
        self.assertTrue(self.gate().eligible)

    def test_missing_reviewer_is_blocked(self):
        result = self.gate({"claude": report()})
        self.assertFalse(result.eligible)
        self.assertIn("missing reviewer report: deepseek", result.reasons)

    def test_old_or_non_approved_result_is_blocked(self):
        result = self.gate({"claude": report(), "deepseek": report("COMMENT")})
        self.assertFalse(result.eligible)
        self.assertIn("deepseek: verdict is COMMENT", result.reasons)

    def test_failed_test_and_secret_scan_are_blocked(self):
        result = self.gate({"claude": report(tests_failed=True), "deepseek": report(secrets=True)})
        self.assertFalse(result.eligible)
        self.assertIn("claude: tests failed", result.reasons)
        self.assertIn("deepseek: secret scan failed", result.reasons)

    def test_opt_in_label_is_required(self):
        self.pr["labels"] = []
        result = self.gate()
        self.assertFalse(result.eligible)
        self.assertIn("missing opt-in label: automation:auto-merge", result.reasons)

    def test_sensitive_paths_are_blocked(self):
        result = self.gate(files=("docs/guide.md", ".github/workflows/release.yml"))
        self.assertFalse(result.eligible)
        self.assertIn("blocked file paths: .github/workflows/release.yml", result.reasons)

    def test_renamed_sensitive_path_is_blocked(self):
        result = self.gate(files=("docs/release.yml", "deploy/release.yml"))
        self.assertFalse(result.eligible)
        self.assertIn("blocked file paths: deploy/release.yml", result.reasons)

    def test_nested_environment_and_migration_paths_are_blocked(self):
        result = self.gate(files=("apps/api/.env.staging", "services/x/migrations/001.sql"))
        self.assertFalse(result.eligible)
        self.assertIn("apps/api/.env.staging", result.reasons[0] + " " + " ".join(result.reasons))
        self.assertIn("services/x/migrations/001.sql", " ".join(result.reasons))

    def test_no_expected_reviewers_is_fail_closed(self):
        result = evaluate(
            self.pr,
            {},
            expected_reviewers=(),
            changed_files=("docs/guide.md",),
        )
        self.assertFalse(result.eligible)
        self.assertIn("no expected reviewers configured", result.reasons)

    def test_no_test_result_is_blocked(self):
        result = self.gate({"claude": report(tests_ran=False), "deepseek": report()})
        self.assertFalse(result.eligible)
        self.assertIn("claude: no test result", result.reasons)

    def test_reports_are_limited_to_current_head(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            state, reports = root / "state", root / "reports"
            state.mkdir()
            reports.mkdir()
            for sha, verdict in (("aaaaaaaa", "APPROVE"), ("bbbbbbbb", "CHANGES_REQUESTED")):
                (state / f"x-9-{sha}-claude.done").touch()
                (reports / f"x-pr9-{sha}-claude.md").write_text(
                    f"- head: `{sha}` / author: claude / reviewed: x\n"
                    f"- tests: - exit=0: test\n- secrets: none\n\n## 判定\n{verdict}\n",
                    encoding="utf-8",
                )
            current = review_reports_for_head(state, reports, "x", 9, "aaaaaaaa1111")
            self.assertEqual(set(current), {"claude"})
            self.assertEqual(current["claude"]["verdict"], "APPROVE")


if __name__ == "__main__":
    unittest.main()

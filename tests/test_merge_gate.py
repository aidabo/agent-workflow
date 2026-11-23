#!/usr/bin/env python3
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cross-review"))
from merge_gate import evaluate  # noqa: E402


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


if __name__ == "__main__":
    unittest.main()

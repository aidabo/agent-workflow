#!/usr/bin/env python3
import os
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
COMMAND = ROOT / "bin" / "agent-workflow"


class AgentWorkflowCommandTests(unittest.TestCase):
    def run_command(self, *args):
        env = os.environ.copy()
        env["CROSS_REVIEW_CONFIG"] = "/tmp/agent-workflow-test-config-does-not-exist"
        return subprocess.run(
            [str(COMMAND), *args], env=env, text=True, capture_output=True
        )

    def test_help_is_successful(self):
        result = self.run_command("--help")
        self.assertEqual(result.returncode, 0)
        self.assertIn("cron", result.stdout)

    def test_unknown_command_is_usage_error(self):
        result = self.run_command("unknown")
        self.assertEqual(result.returncode, 64)
        self.assertIn("unknown command", result.stderr)

    def test_gate_configuration_error_is_not_blocked(self):
        result = self.run_command("gate", "--repo=x", "--pr=1")
        self.assertEqual(result.returncode, 78)
        self.assertEqual(result.stdout, "")
        self.assertIn("missing config", result.stderr)


if __name__ == "__main__":
    unittest.main()

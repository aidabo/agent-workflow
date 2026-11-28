import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from agent_workflow.provider_wrapper import run


class ProviderWrapperTests(unittest.TestCase):
    def request(self):
        return {
            "schema_version": 1,
            "operation": "interview",
            "preflight": {"workspace_root": str(Path.cwd()), "schema_version": 1},
            "payload": {"problem": "P"},
        }

    def test_normalizes_claude_json_result_without_live_provider(self):
        with tempfile.TemporaryDirectory() as tmp:
            fake = Path(tmp) / "fake-claude"
            fake.write_text("#!/bin/sh\nprintf '%s' '{\"result\":\"{\\\"desired_outcome\\\":\\\"O\\\"}\"}'\n")
            fake.chmod(0o700)
            with patch.dict("os.environ", {"AGENT_WORKFLOW_CLAUDE_COMMAND": str(fake)}):
                result = run("claude", self.request())
            self.assertEqual(result["result"], {"desired_outcome": "O"})

    def test_rejects_unknown_provider_and_missing_deepseek_command(self):
        with self.assertRaises(ValueError):
            run("unknown", self.request())
        with patch.dict("os.environ", {}, clear=True):
            with self.assertRaises(RuntimeError):
                run("deepseek", self.request())


if __name__ == "__main__":
    unittest.main()

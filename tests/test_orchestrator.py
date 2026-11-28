import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from agent_workflow.orchestrator import main


class OrchestratorTests(unittest.TestCase):
    def test_provider_receives_preflight_and_returns_validated_result(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            (workspace / "docs").mkdir()
            (workspace / "docs" / "plan.md").write_text("# Plan\n")
            (workspace / "answers.json").write_text(json.dumps({"problem": "P"}))
            command = [
                sys.executable, "-c",
                "import json,sys; r=json.load(sys.stdin); print(json.dumps({'schema_version':1,'operation':r['operation'],'result':{'preflight_schema':r['preflight']['schema_version']}}))",
            ]
            (workspace / "providers.json").write_text(json.dumps({"providers": {"test": command}}))
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                self.assertEqual(main([
                    "interview", "--workspace", tmp, "--provider", "test",
                    "--config", "providers.json", "--input", "answers.json",
                ]), 0)
            response = json.loads(output.getvalue())
            self.assertEqual(response["result"], {"preflight_schema": 1})

    def test_provider_output_schema_and_input_paths_are_fail_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            (workspace / "docs").mkdir()
            (workspace / "input.json").write_text("[]")
            (workspace / "providers.json").write_text(json.dumps({"providers": {"test": [sys.executable, "-c", "print('{}')"]}}))
            self.assertEqual(main([
                "plan", "--workspace", tmp, "--provider", "test",
                "--config", "providers.json", "--input", "input.json",
            ]), 2)
            self.assertEqual(main([
                "plan", "--workspace", tmp, "--provider", "test",
                "--config", "providers.json", "--input", "../input.json",
            ]), 2)


if __name__ == "__main__":
    unittest.main()

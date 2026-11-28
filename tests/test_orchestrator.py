import contextlib
import io
import json
import sys
import tempfile
import unittest
from unittest.mock import patch
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
            (workspace / "input.json").write_text(json.dumps({"a": 1}))
            for label, output in {
                "empty": "{}",
                "wrong-operation": json.dumps({"schema_version": 1, "operation": "critic", "result": {}}),
                "wrong-result": json.dumps({"schema_version": 1, "operation": "plan", "result": []}),
            }.items():
                config = workspace / f"{label}.json"
                config.write_text(json.dumps({"providers": {"test": [sys.executable, "-c", f"print({output!r})"]}}))
                self.assertEqual(main([
                    "plan", "--workspace", tmp, "--provider", "test",
                    "--config", config.name, "--input", "input.json",
                ]), 2)
            self.assertEqual(main([
                "plan", "--workspace", tmp, "--provider", "test",
                "--config", "empty.json", "--input", "../input.json",
            ]), 2)

    def test_preflight_secrets_and_provider_stderr_are_not_forwarded(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            (workspace / "docs").mkdir()
            (workspace / "docs" / "guide.md").write_text("# token: " + "A" * 20)
            (workspace / "input.json").write_text(json.dumps({"a": 1}))
            config = workspace / "providers.json"
            config.write_text(json.dumps({"providers": {"test": [
                sys.executable, "-c", "print('{\"schema_version\":1,\"operation\":\"interview\",\"result\":{}}')",
            ]}}))
            self.assertEqual(main([
                "interview", "--workspace", tmp, "--provider", "test",
                "--config", config.name, "--input", "input.json",
            ]), 2)
            (workspace / "docs" / "guide.md").write_text("# Safe\n")
            config.write_text(json.dumps({"providers": {"test": [
                sys.executable, "-c", "import sys; sys.stderr.write('sk-' + 'A' * 24); sys.exit(7)",
            ]}}))
            error = io.StringIO()
            with contextlib.redirect_stderr(error):
                self.assertEqual(main([
                    "interview", "--workspace", tmp, "--provider", "test",
                    "--config", config.name, "--input", "input.json",
                ]), 2)
            self.assertNotIn("sk-" + "A" * 24, error.getvalue())
            self.assertIn("provider exited with 7", error.getvalue())

    def test_custom_state_root_is_included_in_preflight(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            (workspace / "docs").mkdir()
            (workspace / "input.json").write_text(json.dumps({"a": 1}))
            state = workspace / "custom-state" / "state"
            (state / "requirements").mkdir(parents=True)
            (state / "requirements" / "req.json").write_text(json.dumps({"status": "clarified"}))
            config = workspace / "providers.json"
            command = [sys.executable, "-c", "import json,sys; r=json.load(sys.stdin); print(json.dumps({'schema_version':1,'operation':r['operation'],'result':r['preflight']['workflow_state']['requirements']}))"]
            config.write_text(json.dumps({"providers": {"test": command}}))
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                self.assertEqual(main([
                    "plan", "--workspace", tmp, "--state-root", str(state), "--provider", "test",
                    "--config", config.name, "--input", "input.json",
                ]), 0)
            self.assertEqual(json.loads(output.getvalue())["result"]["by_status"], {"clarified": 1})

    def test_output_persists_only_validated_result_with_private_mode(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            (workspace / "docs").mkdir()
            (workspace / "input.json").write_text(json.dumps({"a": 1}))
            config = workspace / "providers.json"
            command = [sys.executable, "-c", "import json,sys; r=json.load(sys.stdin); print(json.dumps({'schema_version':1,'operation':r['operation'],'result':{'desired_outcome':'O'}}))"]
            config.write_text(json.dumps({"providers": {"test": command}}))
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                self.assertEqual(main([
                    "interview", "--workspace", tmp, "--provider", "test",
                    "--config", config.name, "--input", "input.json", "--output", "clarified.json",
                ]), 0)
            result = json.loads((workspace / "clarified.json").read_text())
            self.assertEqual(result, {"desired_outcome": "O"})
            self.assertEqual((workspace / "clarified.json").stat().st_mode & 0o777, 0o600)
            self.assertNotIn("preflight", (workspace / "clarified.json").read_text())

    def test_output_cannot_overwrite_input_or_provider_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            (workspace / "docs").mkdir()
            (workspace / "input.json").write_text(json.dumps({"a": 1}))
            config = workspace / "providers.json"
            command = [sys.executable, "-c", "import json,sys; r=json.load(sys.stdin); print(json.dumps({'schema_version':1,'operation':r['operation'],'result':{}}))"]
            config.write_text(json.dumps({"providers": {"test": command}}))
            for output in ("input.json", "providers.json"):
                self.assertEqual(main([
                    "plan", "--workspace", tmp, "--provider", "test",
                    "--config", config.name, "--input", "input.json", "--output", output,
                ]), 2)

    def test_interactive_interview_builds_payload_without_saving_transcript(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            (workspace / "docs").mkdir()
            config = workspace / "providers.json"
            command = [sys.executable, "-c", "import json,sys; r=json.load(sys.stdin); print(json.dumps({'schema_version':1,'operation':r['operation'],'result':r['payload']}))"]
            config.write_text(json.dumps({"providers": {"test": command}}))
            answers = [
                "B", "operator", "P", "O", "src", "legacy", "constraint", "criteria", "question", "assumption", "low",
            ]
            output = io.StringIO()
            with patch("builtins.input", side_effect=answers), contextlib.redirect_stdout(output):
                self.assertEqual(main([
                    "interview", "--workspace", tmp, "--provider", "test",
                    "--config", config.name, "--interactive", "--output", "clarified.json",
                ]), 0)
            result = json.loads((workspace / "clarified.json").read_text())
            self.assertEqual(result["background"], "B")
            self.assertEqual(result["acceptance_criteria"], ["criteria"])
            self.assertFalse((workspace / "transcript.json").exists())


if __name__ == "__main__":
    unittest.main()

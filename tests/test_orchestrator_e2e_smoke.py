import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from agent_workflow.orchestrator import main as orchestrator_main
from agent_workflow.provider_fanout import main as fanout_main
from agent_workflow.status import main as status_main


class OrchestratorE2ESmokeTests(unittest.TestCase):
    def test_fake_provider_pipeline_reaches_assign(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            (workspace / "docs").mkdir()
            (workspace / "docs" / "requirements.md").write_text("# Requirements\n")
            (workspace / "brief.json").write_text(json.dumps({"request": "Add smoke feature"}))
            (workspace / "planner.json").write_text(json.dumps({
                "tasks": [{"task_id": "task-001", "summary": "Implement smoke feature", "goal": "Feature works"}],
            }))
            provider = workspace / "fake_provider.py"
            provider.write_text(
                "import json,sys\n"
                "request=json.load(sys.stdin)\n"
                "if request['operation'] == 'interview':\n"
                " result={'background':'B','users':['operator'],'problem':'P','desired_outcome':'O','scope':['src'],'non_goals':[],'constraints':[],'acceptance_criteria':['C'],'open_questions':[],'assumptions':[],'risk_level':'low'}\n"
                "else:\n"
                " result={'finding':'reviewed'}\n"
                "print(json.dumps({'schema_version':1,'operation':request['operation'],'result':result}))\n"
            )
            config = workspace / "providers.json"
            config.write_text(json.dumps({"providers": {
                "primary": [sys.executable, str(provider)],
                "critic-a": [sys.executable, str(provider)],
                "critic-b": [sys.executable, str(provider)],
            }}))

            self.assertEqual(orchestrator_main([
                "interview", "--workspace", tmp, "--provider", "primary",
                "--config", config.name, "--input", "brief.json", "--output", "clarified.json",
            ]), 0)
            self.assertEqual(status_main([
                "requirement-interview", "--workspace", tmp, "--requirement-id", "req-smoke",
                "--input", "clarified.json",
            ]), 0)
            self.assertEqual(status_main([
                "planner-fixture", "--workspace", tmp, "--requirement-id", "req-smoke",
                "--plan-id", "plan-smoke", "--input", "planner.json",
            ]), 0)

            plan_input = workspace / "plan-input.json"
            plan_input.write_text(json.dumps({"plan_id": "plan-smoke", "acceptance_criteria": ["C"]}))
            fanout_output = io.StringIO()
            with contextlib.redirect_stdout(fanout_output):
                self.assertEqual(fanout_main([
                    "critic", "--workspace", tmp, "--provider", "critic-a", "--provider", "critic-b",
                    "--config", config.name, "--input", plan_input.name, "--timeout", "10",
                ]), 0)
            aggregate = json.loads(fanout_output.getvalue())
            self.assertEqual(aggregate["status"], "pending")
            self.assertEqual(aggregate["provider_count"], 2)
            self.assertTrue(all("result" in finding for finding in aggregate["findings"]))

            self.assertEqual(status_main([
                "plan-review", "--workspace", tmp, "--plan-id", "plan-smoke",
                "--review-status", "changes_requested", "--critic-finding", "reviewed",
            ]), 0)
            self.assertEqual(status_main([
                "plan-review", "--workspace", tmp, "--plan-id", "plan-smoke",
                "--review-status", "approved", "--clear-findings",
            ]), 0)
            self.assertEqual(status_main(["plan-approve", "--workspace", tmp, "--plan-id", "plan-smoke"]), 0)
            self.assertEqual(status_main([
                "assign", "--workspace", tmp, "--task-id", "task-001", "--agent", "codex",
            ]), 0)
            task = json.loads((workspace / ".agent-workflow/state/tasks/task-001.json").read_text())
            self.assertEqual((task["agent"], task["task_status"]), ("codex", "in_progress"))


if __name__ == "__main__":
    unittest.main()

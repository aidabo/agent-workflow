import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from agent_workflow.status import atomic_write, main


class WorkspaceInspectTests(unittest.TestCase):
    def test_inspects_source_docs_and_workflow_state_without_content_dump(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            (workspace / "src").mkdir()
            (workspace / "docs" / "nested").mkdir(parents=True)
            (workspace / "docs" / "architecture.md").write_text("# Architecture\n\nsecret text is not returned")
            (workspace / "docs" / "nested" / "runbook.md").write_text("## Runbook\n")
            state = workspace / ".agent-workflow" / "state"
            atomic_write(state / "requirements" / "req-1.json", {"status": "clarified"})
            atomic_write(state / "tasks" / "task-1.json", {"task_status": "in_progress"})
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                self.assertEqual(main(["workspace-inspect", "--workspace", tmp]), 0)
            result = json.loads(output.getvalue())
            self.assertEqual(result["source"]["source_dirs"], ["src"])
            self.assertEqual(result["docs"]["file_count"], 2)
            self.assertEqual(result["docs"]["files"][0]["headings"], ["# Architecture"])
            self.assertEqual(result["workflow_state"]["requirements"]["by_status"], {"clarified": 1})
            self.assertNotIn("secret text is not returned", output.getvalue())

    def test_rejects_docs_path_outside_workspace(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(main(["workspace-inspect", "--workspace", tmp, "--docs-dir", "../outside"]), 2)


if __name__ == "__main__":
    unittest.main()

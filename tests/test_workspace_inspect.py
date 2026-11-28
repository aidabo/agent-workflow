import contextlib
import io
import json
import os
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

    def test_skips_code_fences_and_tolerates_missing_docs_and_bad_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            (workspace / "docs").mkdir()
            (workspace / "docs" / "guide.md").write_text("# Real\n```bash\n# Not a heading\n```\n")
            state = workspace / ".agent-workflow" / "state"
            (state / "requirements").mkdir(parents=True)
            (state / "requirements" / "bad.json").write_text("[]")
            (state / "tasks").mkdir()
            (state / "tasks" / "bad.json").write_text(json.dumps({"task_status": []}))
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                self.assertEqual(main(["workspace-inspect", "--workspace", tmp]), 0)
            result = json.loads(output.getvalue())
            self.assertEqual(result["schema_version"], 1)
            self.assertEqual(result["docs"]["files"][0]["headings"], ["# Real"])
            self.assertEqual(result["workflow_state"]["requirements"]["malformed"], 1)
            self.assertEqual(result["workflow_state"]["tasks"]["malformed"], 1)

    def test_missing_docs_returns_warning_with_other_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                self.assertEqual(main(["workspace-inspect", "--workspace", tmp]), 0)
            result = json.loads(output.getvalue())
            self.assertEqual(result["docs"]["file_count"], 0)
            self.assertTrue(any("docs directory does not exist" in warning for warning in result["warnings"]))

    def test_max_files_reports_only_when_another_regular_file_exists(self):
        with tempfile.TemporaryDirectory() as tmp:
            docs = Path(tmp) / "docs"
            (docs / "a").mkdir(parents=True)
            (docs / "b").mkdir()
            (docs / "a" / "one.md").write_text("# One\n")
            (docs / "b" / "two.md").write_text("# Two\n")
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                self.assertEqual(main(["workspace-inspect", "--workspace", tmp, "--max-files", "1"]), 0)
            limited = json.loads(output.getvalue())
            self.assertTrue(limited["docs"]["truncated"])
            self.assertTrue(any("truncated" in warning for warning in limited["warnings"]))
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                self.assertEqual(main(["workspace-inspect", "--workspace", tmp, "--max-files", "2"]), 0)
            exact = json.loads(output.getvalue())
            self.assertFalse(exact["docs"]["truncated"])

    def test_skips_symlinked_files_and_directories(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as outside:
            docs = Path(tmp) / "docs"
            docs.mkdir()
            (Path(outside) / "secret.md").write_text("# Outside\n")
            try:
                os.symlink(Path(outside) / "secret.md", docs / "linked.md")
                os.symlink(outside, docs / "linked-dir")
            except OSError:
                self.skipTest("symlinks are unavailable")
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                self.assertEqual(main(["workspace-inspect", "--workspace", tmp]), 0)
            result = json.loads(output.getvalue())
            self.assertEqual(result["docs"]["file_count"], 0)

    def test_rejects_docs_file_as_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            (workspace / "docs.txt").write_text("not a directory")
            self.assertEqual(main([
                "workspace-inspect", "--workspace", tmp, "--docs-dir", "docs.txt",
            ]), 2)


if __name__ == "__main__":
    unittest.main()

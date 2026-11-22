import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from agent_workflow.context import resolve_context
from agent_workflow.status import main


class StatusTests(unittest.TestCase):
    def test_begin_and_heartbeat_write_separate_atomic_records(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            self.assertEqual(main([
                "begin", "--workspace", str(workspace), "--agent", "codex", "--task-id", "task-1",
                "--repo", "aidabo/example", "--repo-dir", "example", "--phase", "docs",
                "--goal", "write a plan",
            ]), 0)
            task = json.loads((workspace / ".agent-workflow/state/tasks/task-1.json").read_text())
            agent = json.loads((workspace / ".agent-workflow/state/agents/codex.json").read_text())
            self.assertEqual(task["task_status"], "in_progress")
            self.assertEqual(agent["state"], "busy")
            self.assertEqual(main([
                "heartbeat", "--workspace", str(workspace), "--agent", "codex", "--task-id", "task-1",
            ]), 0)
            self.assertTrue(json.loads((workspace / ".agent-workflow/state/agents/codex.json").read_text())["heartbeat_at"])

    def test_rejects_path_traversal_and_secret_like_values(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(main(["begin", "--workspace", tmp, "--agent", "../codex", "--task-id", "task-1"]), 2)
            self.assertEqual(main(["begin", "--workspace", tmp, "--agent", "codex", "--task-id", "task-1", "--goal", "AKIA1234567890123456"]), 2)


class ContextTests(unittest.TestCase):
    def test_merges_defaults_project_and_task_and_denies_sensitive_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "docs").mkdir()
            (root / "images").mkdir()
            (root / "Screenshot.png").write_text("placeholder")
            config = root / "context.json"
            config.write_text(json.dumps({
                "workspace_root": str(root),
                "default_reference_dirs": ["docs"],
                "projects": {"app": {"screenshot_dirs": ["images"]}},
            }))
            task = root / "task.json"
            task.write_text(json.dumps({"screenshots": ["Screenshot.png"], "reference_dirs": ["docs"]}))
            result = resolve_context(config, "app", str(task))
            self.assertEqual(result["reference_dirs"], [str(root / "docs")])
            self.assertEqual(result["screenshots"], [str(root / "Screenshot.png")])

            config.write_text(json.dumps({"workspace_root": str(root), "default_reference_dirs": [str(Path.home() / ".ssh")] }))
            with self.assertRaises(ValueError):
                resolve_context(config, None, None)


if __name__ == "__main__":
    unittest.main()

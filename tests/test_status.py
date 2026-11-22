import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from agent_workflow.context import resolve_context
from agent_workflow.status import atomic_write, main, sweep_stale


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
            fake_key = "AKIA" + "0" * 16
            self.assertEqual(main(["begin", "--workspace", tmp, "--agent", "codex", "--task-id", "task-1", "--goal", fake_key]), 2)

    def test_switching_task_resets_agent_task_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(main(["begin", "--workspace", tmp, "--agent", "codex", "--task-id", "one", "--phase", "coding", "--branch", "old", "--pr", "1"]), 0)
            self.assertEqual(main(["begin", "--workspace", tmp, "--agent", "codex", "--task-id", "two", "--phase", "docs"]), 0)
            record = json.loads((Path(tmp) / ".agent-workflow/state/agents/codex.json").read_text())
            self.assertEqual(record["task_id"], "two")
            self.assertNotIn("branch", record)
            self.assertNotIn("pr", record)

    def test_rejects_invalid_state_combination(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(main(["begin", "--workspace", tmp, "--agent", "codex", "--task-id", "task-1", "--phase", "done"]), 2)

    def test_sweep_stale_has_599_600_boundary(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / ".agent-workflow" / "state"
            heartbeat = "2025-01-01T00:00:00+00:00"
            path = root / "agents" / "codex.json"
            atomic_write(path, {"agent": "codex", "state": "busy", "heartbeat_at": heartbeat})
            current = datetime(2025, 1, 1, 0, 9, 59, tzinfo=timezone.utc)
            self.assertEqual(sweep_stale(root, 600, current), [])
            current = datetime(2025, 1, 1, 0, 10, 0, tzinfo=timezone.utc)
            self.assertEqual(sweep_stale(root, 600, current), ["codex"])
            self.assertEqual(json.loads(path.read_text())["state"], "stale")


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

            for sensitive in (".env.local", "credentials.json", "secrets.yaml", ".ssh"):
                sensitive_path = root / sensitive
                if sensitive in {".ssh"}:
                    sensitive_path.mkdir()
                else:
                    sensitive_path.write_text("x")
                config.write_text(json.dumps({"workspace_root": str(root), "default_reference_dirs": [sensitive]}))
                with self.assertRaises(ValueError):
                    resolve_context(config, None, None)

    def test_task_repo_dir_overrides_project_and_is_expanded(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "project-repo").mkdir()
            (root / "task-repo").mkdir()
            config = root / "context.json"
            config.write_text(json.dumps({
                "workspace_root": "${WORKSPACE}",
                "projects": {"app": {"repo_dir": "${WORKSPACE}/project-repo"}},
            }))
            task = root / "task.json"
            task.write_text(json.dumps({"repo_dir": "${WORKSPACE}/task-repo"}))
            old_workspace = os.environ.get("WORKSPACE")
            os.environ["WORKSPACE"] = str(root)
            try:
                result = resolve_context(config, "app", str(task))
            finally:
                if old_workspace is None:
                    os.environ.pop("WORKSPACE", None)
                else:
                    os.environ["WORKSPACE"] = old_workspace
            self.assertEqual(result["repo_dir"], str(root / "task-repo"))


if __name__ == "__main__":
    unittest.main()

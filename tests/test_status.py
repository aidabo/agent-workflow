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
from agent_workflow.monitor_data import format_task_lines
from agent_workflow.status import atomic_write, main, sweep_stale


class StatusTests(unittest.TestCase):
    def test_plan_and_task_draft_commands_create_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(main([
                "plan-create", "--workspace", tmp, "--plan-id", "plan-1",
                "--title", "Test plan", "--requirement", "Do the thing",
                "--users", "operator", "--risk-level", "low",
            ]), 0)
            self.assertEqual(main([
                "task-create", "--workspace", tmp, "--task-id", "task-1",
                "--plan-id", "plan-1", "--summary", "Do the thing",
                "--goal", "The thing works", "--next-action", "Run tests",
            ]), 0)
            plan = json.loads((Path(tmp) / ".agent-workflow/state/plans/plan-1.json").read_text())
            task = json.loads((Path(tmp) / ".agent-workflow/state/tasks/task-1.json").read_text())
            self.assertEqual(plan["status"], "draft")
            self.assertEqual(task["task_status"], "planned")
            self.assertTrue(task["pipeline_managed"])

    def test_checkpoint_and_resume_preserve_task_without_changing_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            args = ["--workspace", tmp, "--agent", "codex", "--task-id", "task-1"]
            self.assertEqual(main(["begin", *args, "--phase", "coding", "--branch", "feature/x", "--pr", "12"]), 0)
            self.assertEqual(main(["checkpoint", *args, "--next-action", "run tests"]), 0)
            checkpoint = Path(tmp) / ".agent-workflow/state/checkpoints/task-1.json"
            self.assertTrue(checkpoint.exists())
            data = json.loads(checkpoint.read_text())
            self.assertEqual(data["next_action"], "run tests")
            self.assertEqual(data["branch"], "feature/x")
            self.assertEqual(data["pr"], 12)
            self.assertEqual(main(["resume", "--workspace", tmp]), 0)
            task = json.loads((Path(tmp) / ".agent-workflow/state/tasks/task-1.json").read_text())
            self.assertEqual(task["phase"], "coding")
            self.assertEqual(task["task_status"], "in_progress")

    def test_begin_and_test_events_create_checkpoint_but_heartbeat_does_not_change_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            args = ["--workspace", tmp, "--agent", "codex", "--task-id", "task-1"]
            self.assertEqual(main(["begin", *args, "--phase", "coding", "--goal", "goal"]), 0)
            checkpoint = Path(tmp) / ".agent-workflow/state/checkpoints/task-1.json"
            self.assertTrue(checkpoint.exists())
            first_inode = checkpoint.stat().st_ino
            self.assertEqual(main(["heartbeat", *args]), 0)
            self.assertEqual(checkpoint.stat().st_ino, first_inode)
            self.assertEqual(main(["test", *args, "--test-status", "passed", "--test-summary", "unit"]), 0)
            self.assertNotEqual(checkpoint.stat().st_ino, first_inode)

    def test_automatic_checkpoint_keeps_manual_next_action_and_recovers_corrupt_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            args = ["--workspace", tmp, "--agent", "codex", "--task-id", "task-1"]
            self.assertEqual(main(["begin", *args, "--phase", "coding", "--goal", "goal"]), 0)
            self.assertEqual(main(["checkpoint", *args, "--next-action", "manual next"]), 0)
            checkpoint = Path(tmp) / ".agent-workflow/state/checkpoints/task-1.json"
            self.assertEqual(main(["update", *args, "--branch", "feature/x"]), 0)
            self.assertEqual(json.loads(checkpoint.read_text())["next_action"], "manual next")
            checkpoint.write_text("not json")
            self.assertEqual(main(["update", *args, "--pr", "1"]), 0)
            data = json.loads(checkpoint.read_text())
            self.assertEqual(data["next_action"], "goal")

    def test_end_writes_final_checkpoint(self):
        with tempfile.TemporaryDirectory() as tmp:
            args = ["--workspace", tmp, "--agent", "codex", "--task-id", "task-1"]
            self.assertEqual(main(["begin", *args, "--phase", "coding"]), 0)
            self.assertEqual(main(["end", *args]), 0)
            data = json.loads((Path(tmp) / ".agent-workflow/state/checkpoints/task-1.json").read_text())
            self.assertEqual(data["task_status"], "done")

    def test_checkpoint_rejects_unknown_task(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(main([
                "checkpoint", "--workspace", tmp, "--agent", "codex", "--task-id", "missing",
            ]), 2)

    def test_manual_checkpoint_recovers_corrupt_previous_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            args = ["--workspace", tmp, "--agent", "codex", "--task-id", "task-1"]
            self.assertEqual(main(["begin", *args, "--phase", "coding", "--goal", "goal"]), 0)
            checkpoint = Path(tmp) / ".agent-workflow/state/checkpoints/task-1.json"
            checkpoint.write_text("not json")
            self.assertEqual(main(["checkpoint", *args, "--next-action", "recover"]), 0)
            self.assertEqual(json.loads(checkpoint.read_text())["next_action"], "recover")

    def test_checkpoint_prune_is_dry_run_and_skips_active_tasks(self):
        with tempfile.TemporaryDirectory() as tmp:
            args = ["--workspace", tmp, "--agent", "codex", "--task-id", "task-1"]
            self.assertEqual(main(["begin", *args, "--phase", "coding"]), 0)
            result = main(["checkpoint-prune", "--workspace", tmp, "--older-than", "0s"])
            self.assertEqual(result, 0)
            self.assertTrue((Path(tmp) / ".agent-workflow/state/checkpoints/task-1.json").exists())
            output_path = Path(tmp) / ".agent-workflow/state/tasks/task-1.json"
            record = json.loads(output_path.read_text())
            record["state"] = "done"
            record["phase"] = "done"
            record["task_status"] = "done"
            output_path.write_text(json.dumps(record))
            import os
            os.utime(Path(tmp) / ".agent-workflow/state/checkpoints/task-1.json", (1, 1))
            self.assertEqual(main(["checkpoint-prune", "--workspace", tmp, "--older-than", "0s", "--apply"]), 0)
            self.assertFalse((Path(tmp) / ".agent-workflow/state/checkpoints/task-1.json").exists())

    def test_checkpoint_prune_skips_unknown_task_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / ".agent-workflow/state"
            (root / "checkpoints").mkdir(parents=True)
            (root / "tasks").mkdir()
            (root / "tasks/task-1.json").write_text("[]")
            (root / "checkpoints/task-1.json").write_text("checkpoint")
            self.assertEqual(main(["checkpoint-prune", "--workspace", tmp, "--older-than", "0s", "--apply"]), 0)
            self.assertTrue((root / "checkpoints/task-1.json").exists())

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
            self.assertEqual(task["state"], "busy")
            self.assertEqual(main([
                "heartbeat", "--workspace", str(workspace), "--agent", "codex", "--task-id", "task-1",
            ]), 0)
            self.assertTrue(json.loads((workspace / ".agent-workflow/state/agents/codex.json").read_text())["heartbeat_at"])

    def test_rejects_path_traversal_and_secret_like_values(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(main(["begin", "--workspace", tmp, "--agent", "../codex", "--task-id", "task-1"]), 2)
            fake_key = "AKIA" + "0" * 16
            self.assertEqual(main(["begin", "--workspace", tmp, "--agent", "codex", "--task-id", "task-1", "--goal", fake_key]), 2)

    def test_parallel_tasks_keep_independent_task_records(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(main(["begin", "--workspace", tmp, "--agent", "codex", "--task-id", "one", "--phase", "coding", "--branch", "old", "--pr", "1"]), 0)
            self.assertEqual(main(["begin", "--workspace", tmp, "--agent", "codex", "--task-id", "two", "--phase", "docs"]), 0)
            agent = json.loads((Path(tmp) / ".agent-workflow/state/agents/codex.json").read_text())
            one = json.loads((Path(tmp) / ".agent-workflow/state/tasks/one.json").read_text())
            two = json.loads((Path(tmp) / ".agent-workflow/state/tasks/two.json").read_text())
            self.assertEqual(agent["active_task_ids"], ["one", "two"])
            self.assertEqual(agent["current_task_id"], "two")
            self.assertEqual(one["branch"], "old")
            self.assertEqual(one["pr"], 1)
            self.assertEqual(two["task_id"], "two")
            self.assertEqual(main(["end", "--workspace", tmp, "--agent", "codex", "--task-id", "one"]), 0)
            agent = json.loads((Path(tmp) / ".agent-workflow/state/agents/codex.json").read_text())
            self.assertEqual(agent["active_task_ids"], ["two"])
            self.assertEqual(agent["current_task_id"], "two")

    def test_completed_task_cannot_be_updated(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(main(["begin", "--workspace", tmp, "--agent", "codex", "--task-id", "task-1", "--phase", "coding"]), 0)
            self.assertEqual(main(["end", "--workspace", tmp, "--agent", "codex", "--task-id", "task-1"]), 0)
            self.assertEqual(main(["test", "--workspace", tmp, "--agent", "codex", "--task-id", "task-1", "--test-status", "passed"]), 2)

    def test_rejects_invalid_state_combination(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(main(["begin", "--workspace", tmp, "--agent", "codex", "--task-id", "task-1", "--phase", "done"]), 2)

    def test_sweep_stale_has_599_600_boundary(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / ".agent-workflow" / "state"
            heartbeat = "2025-01-01T00:00:00+00:00"
            path = root / "tasks" / "task-1.json"
            atomic_write(path, {"task_id": "task-1", "agent": "codex", "state": "busy", "heartbeat_at": heartbeat})
            current = datetime(2025, 1, 1, 0, 9, 59, tzinfo=timezone.utc)
            self.assertEqual(sweep_stale(root, 600, 60, current), [])
            current = datetime(2025, 1, 1, 0, 10, 0, tzinfo=timezone.utc)
            self.assertEqual(sweep_stale(root, 600, 60, current), ["task-1"])
            self.assertEqual(json.loads(path.read_text())["state"], "stale")

    def test_sweep_validates_heartbeat_ratio_and_naive_now(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(main(["sweep", "--workspace", tmp, "--heartbeat-interval-seconds", "120", "--stale-after-seconds", "600"]), 2)
            self.assertEqual(main(["sweep", "--workspace", tmp, "--heartbeat-interval-seconds", "120", "--stale-after-seconds", "1200", "--now", "2025-01-01T00:00:00"]), 0)

    def test_state_directories_are_private(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(main(["begin", "--workspace", tmp, "--agent", "codex", "--task-id", "task-1", "--phase", "docs"]), 0)
            root = Path(tmp) / ".agent-workflow"
            self.assertEqual((root / "state").stat().st_mode & 0o777, 0o700)
            self.assertEqual((root / "state/tasks").stat().st_mode & 0o777, 0o700)
            self.assertEqual((root / "state/tasks/task-1.json").stat().st_mode & 0o777, 0o600)

    def test_rejects_phase_status_mismatch_after_merge(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(main(["begin", "--workspace", tmp, "--agent", "codex", "--task-id", "task-1", "--phase", "coding"]), 0)
            self.assertEqual(main(["update", "--workspace", tmp, "--agent", "codex", "--task-id", "task-1", "--task-status", "ready_for_review"]), 2)
            self.assertEqual(main(["end", "--workspace", tmp, "--agent", "codex", "--task-id", "task-1"]), 0)
            self.assertEqual(main(["update", "--workspace", tmp, "--agent", "codex", "--task-id", "task-1", "--phase", "coding"]), 2)

    def test_phase_and_state_rules(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(main(["begin", "--workspace", tmp, "--agent", "codex", "--task-id", "task-1", "--phase", "docs_human_review", "--task-status", "ready_for_review", "--state", "busy"]), 2)
            self.assertEqual(main(["begin", "--workspace", tmp, "--agent", "codex", "--task-id", "task-1", "--phase", "docs_human_review", "--task-status", "ready_for_review", "--state", "waiting_user"]), 0)

    def test_heartbeat_preserves_human_state_and_recovers_stale(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(main(["begin", "--workspace", tmp, "--agent", "codex", "--task-id", "task-1", "--phase", "docs_human_review", "--task-status", "ready_for_review", "--state", "waiting_user"]), 0)
            self.assertEqual(main(["heartbeat", "--workspace", tmp, "--agent", "codex", "--task-id", "task-1"]), 0)
            task_path = Path(tmp) / ".agent-workflow/state/tasks/task-1.json"
            self.assertEqual(json.loads(task_path.read_text())["state"], "waiting_user")
            record = json.loads(task_path.read_text())
            record["state"] = "stale"
            record["previous_state"] = "waiting_user"
            task_path.write_text(json.dumps(record))
            self.assertEqual(main(["heartbeat", "--workspace", tmp, "--agent", "codex", "--task-id", "task-1"]), 0)
            self.assertEqual(json.loads(task_path.read_text())["state"], "waiting_user")
            self.assertEqual(main(["begin", "--workspace", tmp, "--agent", "codex", "--task-id", "task-2", "--phase", "docs_review"]), 0)


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

            for sensitive in (".env.local", "credentials.json", "secrets.yaml", "secret", "credential", ".ssh"):
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

    def test_external_nonsecret_reference_returns_warning(self):
        with tempfile.TemporaryDirectory() as workspace_tmp, tempfile.TemporaryDirectory() as external_tmp:
            workspace = Path(workspace_tmp)
            external = Path(external_tmp)
            config = workspace / "context.json"
            config.write_text(json.dumps({
                "workspace_root": str(workspace),
                "allow_external_nonsecret": True,
                "default_reference_dirs": [str(external)],
            }))
            result = resolve_context(config, None, None)
            self.assertEqual(result["reference_dirs"], [str(external)])
            self.assertTrue(result["warnings"])


if __name__ == "__main__":
    unittest.main()

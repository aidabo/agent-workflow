import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from agent_workflow.monitor_data import agent_current_tasks, display_width, format_task_lines, task_records


class MonitorDataTests(unittest.TestCase):
    def test_formats_multiple_tasks_without_network(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "state"
            (root / "tasks").mkdir(parents=True)
            for task_id, agent in (("a", "codex"), ("b", "claude")):
                (root / "tasks" / f"{task_id}.json").write_text(json.dumps({
                    "task_id": task_id, "agent": agent, "phase": "coding", "state": "busy",
                    "heartbeat_at": "2025-01-01T00:00:00+00:00", "test": {"status": "passed"},
                }))
            records = task_records(root)
            self.assertEqual({record["task_id"] for record in records}, {"a", "b"})
            lines = format_task_lines(root)
            self.assertEqual(len(lines), 2)
            self.assertTrue(any("codex" in line and "a" in line for line in lines))
            self.assertTrue(any("claude" in line and "b" in line for line in lines))

    def test_corrupt_task_is_visible_as_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "state"
            (root / "tasks").mkdir(parents=True)
            (root / "tasks/bad.json").write_text("{")
            self.assertIn("ERROR", format_task_lines(root)[0])
            (root / "tasks/list.json").write_text("[]")
            self.assertTrue(any("list" in line and "ERROR" in line for line in format_task_lines(root)))

    def test_completed_tasks_are_bounded(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "state"
            (root / "tasks").mkdir(parents=True)
            for index in range(12):
                (root / "tasks" / f"done-{index}.json").write_text(json.dumps({
                    "task_id": f"done-{index}", "state": "done", "updated_at": f"2025-01-{index + 1:02d}"
                }))
            lines = format_task_lines(root, max_rows=3)
            self.assertEqual(len(lines), 4)
            self.assertIn("他 9 task", lines[-1])

    def test_missing_test_status_is_displayed_as_dash(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "state"
            (root / "tasks").mkdir(parents=True)
            (root / "tasks/task.json").write_text(json.dumps({
                "task_id": "task", "state": "busy", "test": {"status": None, "summary": "running"}
            }))
            self.assertNotIn("test=-", format_task_lines(root)[0])

    def test_task_goal_and_next_action_are_visible(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "state"
            (root / "tasks").mkdir(parents=True)
            (root / "tasks/task.json").write_text(json.dumps({
                "task_id": "task", "agent": "codex", "phase": "coding", "state": "busy",
                "summary": "parallel review queue", "goal": "internal fallback goal",
                "next_action": "run monitor checks",
            }))
            line = format_task_lines(root)[0]
            self.assertIn("内容=parallel review queue", line)
            self.assertIn("次=run monitor checks", line)

    def test_assignment_pending_tasks_are_not_work_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "state"
            (root / "tasks").mkdir(parents=True)
            (root / "tasks/pending.json").write_text(json.dumps({
                "task_id": "pending", "state": "idle", "placeholder": True,
                "goal": "task assignment pending",
            }))
            lines = format_task_lines(root)
            self.assertIn("割当待ち 1件", lines[0])
            self.assertNotIn("pending idle", lines[0])

    def test_task_context_strips_control_characters(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "state"
            (root / "tasks").mkdir(parents=True)
            (root / "tasks/task.json").write_text(json.dumps({
                "task_id": "task", "state": "busy", "goal": "safe\u001b[2J context",
            }))
            line = format_task_lines(root)[0]
            self.assertIn("内容=safe[2J context", line)
            self.assertNotIn("\x1b", line)

    def test_task_lines_use_terminal_display_width(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "state"
            (root / "tasks").mkdir(parents=True)
            (root / "tasks/task.json").write_text(json.dumps({
                "task_id": "task", "state": "busy", "goal": "日本語の長いタスク内容",
                "error": True,
            }))
            with patch("agent_workflow.monitor_data.shutil.get_terminal_size", return_value=os.terminal_size((20, 24))):
                line = format_task_lines(root)[0]
            self.assertLessEqual(display_width(line), 20)

    def test_long_task_id_is_displayed_without_checkpoint_internals(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "state"
            (root / "tasks").mkdir(parents=True)
            (root / "checkpoints").mkdir()
            task_id = "task-" + "x" * 40
            (root / "tasks" / f"{task_id}.json").write_text(json.dumps({
                "task_id": task_id, "state": "busy",
            }))
            (root / "checkpoints" / f"{task_id}.json").write_text("checkpoint")
            self.assertNotIn("cp=", format_task_lines(root)[0])

    def test_agent_current_task_index_wins_over_task_update_order(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "state"
            (root / "tasks").mkdir(parents=True)
            (root / "agents").mkdir(parents=True)
            (root / "tasks/old.json").write_text(json.dumps({"task_id": "old", "agent": "codex", "state": "busy", "updated_at": "2025-02-02"}))
            (root / "tasks/current.json").write_text(json.dumps({"task_id": "current", "agent": "codex", "state": "busy", "updated_at": "2025-01-01"}))
            (root / "agents/codex.json").write_text(json.dumps({"agent": "codex", "current_task_id": "current"}))
            current = agent_current_tasks(root)
            self.assertEqual(current["codex"]["task_id"], "current")

    def test_agent_current_tasks_ignores_corrupt_indexes_and_task_ids(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "state"
            (root / "tasks").mkdir(parents=True)
            (root / "agents").mkdir(parents=True)
            (root / "tasks/bad.json").write_text(json.dumps({"task_id": [], "state": "busy"}))
            (root / "agents/bad.json").write_text("[]")
            (root / "agents/scalar.json").write_text("null")
            self.assertEqual(agent_current_tasks(root), {})

    def test_active_tasks_are_before_completed_tasks(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "state"
            (root / "tasks").mkdir(parents=True)
            (root / "tasks/done.json").write_text(json.dumps({"task_id": "done", "state": "done", "updated_at": "2025-01-02"}))
            (root / "tasks/active.json").write_text(json.dumps({"task_id": "active", "state": "busy", "updated_at": "2025-01-01"}))
            lines = format_task_lines(root)
            self.assertIn("active", lines[0])

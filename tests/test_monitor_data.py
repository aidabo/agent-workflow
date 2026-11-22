import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from agent_workflow.monitor_data import format_task_lines, task_records


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

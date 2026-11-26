import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from agent_workflow.monitor_data import format_task_lines


class MonitorCheckpointTests(unittest.TestCase):
    def test_checkpoint_size_is_shown_and_large_checkpoint_is_marked(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "state"
            (root / "tasks").mkdir(parents=True)
            (root / "checkpoints").mkdir()
            (root / "tasks/task-1.json").write_text(json.dumps({
                "task_id": "task-1", "agent": "codex", "phase": "coding",
                "state": "busy", "heartbeat_at": "now",
            }))
            (root / "checkpoints/task-1.json").write_text("x" * (512 * 1024 + 1))
            lines = format_task_lines(root)
            self.assertIn("checkpoint=large!", lines[0])


if __name__ == "__main__":
    unittest.main()

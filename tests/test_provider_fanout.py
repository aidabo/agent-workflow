import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from agent_workflow.provider_fanout import main


class ProviderFanoutTests(unittest.TestCase):
    def test_fanout_aggregates_provenance_and_stops_on_disagreement(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            (workspace / "docs").mkdir()
            (workspace / "input.json").write_text(json.dumps({"requirement": "R"}))
            providers = {}
            for name, value in (("one", "A"), ("two", "B")):
                script = workspace / f"{name}.py"
                script.write_text(
                    "import json; print(json.dumps({'schema_version':1,'operation':'critic','result':{'finding':'%s'}}))\n" % value
                )
                providers[name] = [sys.executable, str(script)]
            config = workspace / "providers.json"
            config.write_text(json.dumps({"providers": providers}))
            self.assertEqual(main([
                "critic", "--workspace", tmp, "--provider", "one", "--provider", "two",
                "--config", config.name, "--input", "input.json", "--timeout", "10",
            ]), 0)
            aggregate = json.loads((workspace / "orchestrator-findings/critic-findings.json").read_text())
            self.assertEqual(aggregate["status"], "needs_human")
            self.assertEqual([item["provider"] for item in aggregate["findings"]], ["one", "two"])
            self.assertIn("request_head", aggregate["findings"][0])

    def test_fanout_rejects_interview_operation(self):
        with self.assertRaises(SystemExit):
            main(["interview", "--workspace", ".", "--provider", "one", "--config", "x", "--input", "y"])

    def test_fanout_marks_provider_failure_and_rejects_output_collision(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            (workspace / "docs").mkdir()
            (workspace / "input.json").write_text(json.dumps({"requirement": "R"}))
            good = workspace / "good.py"
            good.write_text("import json; print(json.dumps({'schema_version':1,'operation':'critic','result':{'finding':'A'}}))\n")
            bad = workspace / "bad.py"
            bad.write_text("raise SystemExit(3)\n")
            config = workspace / "providers.json"
            config.write_text(json.dumps({"providers": {
                "good": [sys.executable, str(good)], "bad": [sys.executable, str(bad)],
            }}))
            self.assertEqual(main([
                "critic", "--workspace", tmp, "--provider", "good", "--provider", "bad",
                "--config", config.name, "--input", "input.json", "--timeout", "10",
            ]), 0)
            aggregate = json.loads((workspace / "orchestrator-findings/critic-findings.json").read_text())
            self.assertEqual(aggregate["status"], "needs_human")
            self.assertTrue(any(item.get("error") for item in aggregate["findings"]))
            self.assertEqual(main([
                "critic", "--workspace", tmp, "--provider", "good",
                "--config", config.name, "--input", "input.json", "--output", "orchestrator-findings/good.json",
            ]), 2)
            self.assertEqual(main([
                "critic", "--workspace", tmp, "--provider", "Good", "--provider", "good",
                "--config", config.name, "--input", "input.json",
            ]), 2)


if __name__ == "__main__":
    unittest.main()

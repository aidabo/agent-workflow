import contextlib
import io
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
from agent_workflow.status import atomic_write, latest_review, main, sweep_stale


class StatusTests(unittest.TestCase):
    def test_requirement_create_persists_clarified_artifact_and_questions(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(main([
                "requirement-create", "--workspace", tmp, "--requirement-id", "req-1",
                "--background", "Need it", "--problem", "Too slow", "--desired-outcome", "Fast",
                "--users", "operator", "--acceptance-criteria", "Runs fast",
                "--open-questions", "Which provider?", "--risk-level", "high",
            ]), 0)
            path = Path(tmp) / ".agent-workflow/state/requirements/req-1.json"
            record = json.loads(path.read_text())
            self.assertEqual(record["status"], "needs_clarification")
            self.assertEqual(record["risk_level"], "high")
            self.assertEqual(record["open_questions"], ["Which provider?"])
            self.assertNotIn("completed_at", record["interview"])
            self.assertIn("recorded_at", record["interview"])
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            show_output = io.StringIO()
            with contextlib.redirect_stdout(show_output):
                self.assertEqual(main(["requirement-show", "--workspace", tmp, "--requirement-id", "req-1"]), 0)
            self.assertEqual(json.loads(show_output.getvalue())["requirement_id"], "req-1")
            self.assertEqual(main([
                "requirement-create", "--workspace", tmp, "--requirement-id", "req-open",
                "--background", "B", "--problem", "P", "--desired-outcome", "O",
                "--open-questions", "Q",
            ]), 0)
            self.assertEqual(main([
                "requirement-create", "--workspace", tmp, "--requirement-id", "req-clarified",
                "--background", "B", "--problem", "P", "--desired-outcome", "O",
                "--acceptance-criteria", "C",
            ]), 0)
            list_output = io.StringIO()
            with contextlib.redirect_stdout(list_output):
                self.assertEqual(main(["requirement-list", "--workspace", tmp, "--status", "needs_clarification"]), 0)
            listed = json.loads(list_output.getvalue())
            self.assertEqual([record["requirement_id"] for record in listed], ["req-1", "req-open"])
            self.assertEqual(main(["requirement-show", "--workspace", tmp, "--requirement-id", "missing"]), 2)

    def test_requirement_without_acceptance_criteria_needs_clarification_and_round_is_positive(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(main([
                "requirement-create", "--workspace", tmp, "--requirement-id", "req-1",
                "--background", "B", "--problem", "P", "--desired-outcome", "O",
            ]), 0)
            record = json.loads((Path(tmp) / ".agent-workflow/state/requirements/req-1.json").read_text())
            self.assertEqual(record["status"], "needs_clarification")
            self.assertEqual(main([
                "requirement-create", "--workspace", tmp, "--requirement-id", "req-2",
                "--background", "B", "--problem", "P", "--desired-outcome", "O", "--round", "0",
            ]), 2)

    def test_plan_create_from_clarified_requirement_transfers_lineage_and_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(main([
                "requirement-create", "--workspace", tmp, "--requirement-id", "req-1",
                "--background", "B", "--problem", "P", "--desired-outcome", "O",
                "--users", "operator", "--scope", "src", "--acceptance-criteria", "C",
            ]), 0)
            self.assertEqual(main([
                "plan-create", "--workspace", tmp, "--plan-id", "plan-1",
                "--title", "Plan", "--requirement-id", "req-1",
            ]), 0)
            plan = json.loads((Path(tmp) / ".agent-workflow/state/plans/plan-1.json").read_text())
            self.assertEqual(plan["requirement_id"], "req-1")
            self.assertEqual(plan["requirement"], "O")
            self.assertEqual(plan["acceptance_criteria"], ["C"])
            self.assertEqual(main([
                "plan-create", "--workspace", tmp, "--plan-id", "plan-2",
                "--title", "Blocked", "--requirement-id", "req-missing",
            ]), 2)
            self.assertEqual(main([
                "requirement-create", "--workspace", tmp, "--requirement-id", "req-open",
                "--background", "B", "--problem", "P", "--desired-outcome", "O",
                "--acceptance-criteria", "C", "--open-questions", "Q",
            ]), 0)
            self.assertEqual(main([
                "plan-create", "--workspace", tmp, "--plan-id", "plan-3",
                "--title", "Blocked", "--requirement-id", "req-open",
            ]), 2)
            self.assertEqual(main([
                "plan-create", "--workspace", tmp, "--plan-id", "plan-4",
                "--title", "Blocked",
            ]), 2)
            self.assertFalse((Path(tmp) / ".agent-workflow/state/plans/plan-4.json").exists())

    def test_plan_review_records_critic_and_verifier_findings_without_approval(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(main([
                "plan-create", "--workspace", tmp, "--plan-id", "plan-1",
                "--title", "Plan", "--requirement", "Requirement",
            ]), 0)
            self.assertEqual(main([
                "task-create", "--workspace", tmp, "--task-id", "task-1", "--plan-id", "plan-1",
                "--summary", "Work", "--goal", "Done",
            ]), 0)
            self.assertEqual(main([
                "plan-review", "--workspace", tmp, "--plan-id", "plan-1",
                "--review-status", "changes_requested", "--critic-finding", "Scope too broad",
                "--verifier-finding", "Missing test evidence",
            ]), 0)
            plan = json.loads((Path(tmp) / ".agent-workflow/state/plans/plan-1.json").read_text())
            self.assertEqual(plan["status"], "draft")
            self.assertEqual(plan["ai_review"]["critic_findings"], ["Scope too broad"])
            self.assertEqual(plan["ai_review"]["verifier_findings"], ["Missing test evidence"])
            self.assertEqual(main(["plan-approve", "--workspace", tmp, "--plan-id", "plan-1"]), 2)
            self.assertEqual(main([
                "plan-review", "--workspace", tmp, "--plan-id", "plan-1", "--review-status", "changes_requested",
                "--clear-findings", "--critic-finding", "new finding",
            ]), 2)
            self.assertEqual(main([
                "plan-review", "--workspace", tmp, "--plan-id", "plan-1", "--review-status", "approved",
                "--critic-finding", "new finding",
            ]), 2)
            self.assertEqual(main([
                "plan-review", "--workspace", tmp, "--plan-id", "plan-1", "--review-status", "approved",
            ]), 2)
            self.assertEqual(main([
                "plan-review", "--workspace", tmp, "--plan-id", "plan-1", "--review-status", "approved",
                "--clear-findings",
            ]), 0)
            self.assertEqual(main([
                "plan-create", "--workspace", tmp, "--plan-id", "plan-1", "--title", "Revised",
                "--requirement", "Changed", "--force",
            ]), 0)
            self.assertEqual(main(["plan-approve", "--workspace", tmp, "--plan-id", "plan-1"]), 2)
            self.assertEqual(main([
                "plan-review", "--workspace", tmp, "--plan-id", "plan-1", "--review-status", "approved",
                "--clear-findings",
            ]), 0)
            self.assertEqual(main(["plan-approve", "--workspace", tmp, "--plan-id", "plan-1"]), 0)

    def test_planner_fixture_creates_reproducible_draft_plan_and_tasks(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(main([
                "requirement-create", "--workspace", tmp, "--requirement-id", "req-1",
                "--background", "B", "--problem", "P", "--desired-outcome", "O",
                "--acceptance-criteria", "C",
            ]), 0)
            fixture = Path(tmp) / "planner.json"
            fixture.write_text(json.dumps({"title": "Fixture plan", "tasks": [
                {"task_id": "task-a", "summary": "Inspect", "goal": "Inspection complete", "next_action": "Run checks"},
            ]}))
            self.assertEqual(main([
                "planner-fixture", "--workspace", tmp, "--requirement-id", "req-1",
                "--plan-id", "plan-fixture", "--input", "planner.json",
            ]), 0)
            plan = json.loads((Path(tmp) / ".agent-workflow/state/plans/plan-fixture.json").read_text())
            task = json.loads((Path(tmp) / ".agent-workflow/state/tasks/task-a.json").read_text())
            self.assertEqual((plan["status"], plan["requirement_id"], plan["task_ids"]), ("draft", "req-1", ["task-a"]))
            self.assertEqual((task["task_status"], task["agent"]), ("ready", None))
            self.assertEqual(main([
                "planner-fixture", "--workspace", tmp, "--requirement-id", "req-1",
                "--plan-id", "plan-fixture-2", "--input", "planner.json",
            ]), 2)
            self.assertFalse((Path(tmp) / ".agent-workflow/state/plans/plan-fixture-2.json").exists())
            invalid_risk = Path(tmp) / "invalid-risk.json"
            invalid_risk.write_text(json.dumps({"risk_level": [], "tasks": [
                {"task_id": "task-b", "summary": "Inspect", "goal": "Done"},
            ]}))
            self.assertEqual(main([
                "planner-fixture", "--workspace", tmp, "--requirement-id", "req-1",
                "--plan-id", "plan-invalid-risk", "--input", "invalid-risk.json",
            ]), 2)
            invalid_task = Path(tmp) / "invalid-task.json"
            invalid_task.write_text(json.dumps({"tasks": [
                {"task_id": 1, "summary": "Inspect", "goal": "Done"},
            ]}))
            self.assertEqual(main([
                "planner-fixture", "--workspace", tmp, "--requirement-id", "req-1",
                "--plan-id", "plan-invalid-task", "--input", "invalid-task.json",
            ]), 2)

    def test_requirement_create_rejects_secret_and_duplicate_without_force(self):
        with tempfile.TemporaryDirectory() as tmp:
            args = [
                "requirement-create", "--workspace", tmp, "--requirement-id", "req-1",
                "--background", "Need it", "--problem", "Problem", "--desired-outcome", "Outcome",
            ]
            self.assertEqual(main([*args, "--background", "sk-secret-value-that-must-not-save"]), 2)
            self.assertEqual(main(args), 0)
            self.assertEqual(main(args), 2)

    def test_requirement_interview_converts_answer_fixture_to_artifact(self):
        with tempfile.TemporaryDirectory() as tmp:
            answers = Path(tmp) / "answers.json"
            answers.write_text(json.dumps({
                "background": "B", "problem": "P", "desired_outcome": "O",
                "users": ["operator"], "acceptance_criteria": ["C"],
                "open_questions": [], "risk_level": "low",
            }))
            self.assertEqual(main([
                "requirement-interview", "--workspace", tmp, "--requirement-id", "req-1",
                "--input", "answers.json", "--interview-mode", "full", "--round", "2",
            ]), 0)
            record = json.loads((Path(tmp) / ".agent-workflow/state/requirements/req-1.json").read_text())
            self.assertEqual((record["status"], record["interview"]["mode"], record["interview"]["round"]), ("clarified", "full", 2))

    def test_requirement_interview_rejects_invalid_risk_level(self):
        with tempfile.TemporaryDirectory() as tmp:
            answers = Path(tmp) / "answers.json"
            answers.write_text(json.dumps({
                "background": "B", "problem": "P", "desired_outcome": "O",
                "acceptance_criteria": ["C"], "risk_level": "critical",
            }))
            self.assertEqual(main([
                "requirement-interview", "--workspace", tmp, "--requirement-id", "req-1",
                "--input", "answers.json",
            ]), 2)

    def test_requirement_force_preserves_created_at_and_rejects_clarified(self):
        with tempfile.TemporaryDirectory() as tmp:
            args = [
                "requirement-create", "--workspace", tmp, "--requirement-id", "req-1",
                "--background", "B", "--problem", "P", "--desired-outcome", "O",
            ]
            self.assertEqual(main(args), 0)
            path = Path(tmp) / ".agent-workflow/state/requirements/req-1.json"
            created_at = json.loads(path.read_text())["created_at"]
            self.assertEqual(main([*args, "--acceptance-criteria", "C", "--force"]), 0)
            self.assertEqual(json.loads(path.read_text())["created_at"], created_at)
            self.assertEqual(main([*args, "--background", "B3", "--force"]), 2)

    def test_latest_review_prefers_newer_evidence(self):
        self.assertEqual(latest_review(
            {"status": "approved", "updated_at": "2026-01-01T00:00:00+00:00"},
            {"status": "changes_requested", "updated_at": "2026-01-02T00:00:00+00:00"},
        )["status"], "changes_requested")
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
            self.assertEqual(plan["task_ids"], ["task-1"])
            self.assertEqual(task["task_status"], "ready")
            self.assertTrue(task["pipeline_managed"])

    def test_plan_and_task_drafts_reject_secret_list_and_force_active_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(main([
                "plan-create", "--workspace", tmp, "--plan-id", "plan-1",
                "--title", "Test", "--requirement", "Do thing",
                "--acceptance-criteria", "sk-secret-value-that-must-not-save",
            ]), 2)
            self.assertEqual(main([
                "plan-create", "--workspace", tmp, "--plan-id", "plan-1",
                "--title", "Test", "--requirement", "Do thing",
            ]), 0)
            self.assertEqual(main([
                "task-create", "--workspace", tmp, "--task-id", "task-1",
                "--plan-id", "plan-1", "--summary", "Summary", "--goal", "Goal",
            ]), 0)
            task_path = Path(tmp) / ".agent-workflow/state/tasks/task-1.json"
            task = json.loads(task_path.read_text())
            task.update({"phase": "code_review", "state": "waiting_user", "task_status": "ready_for_review"})
            atomic_write(task_path, task)
            self.assertEqual(main([
                "task-create", "--workspace", tmp, "--task-id", "task-1",
                "--plan-id", "plan-1", "--summary", "Reset", "--goal", "Reset", "--force",
            ]), 2)

    def test_revision_create_preserves_source_task_and_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(main(["plan-create", "--workspace", tmp, "--plan-id", "p", "--title", "P", "--requirement", "R"]), 0)
            self.assertEqual(main(["task-create", "--workspace", tmp, "--task-id", "t", "--plan-id", "p", "--summary", "S", "--goal", "G"]), 0)
            self.assertEqual(main(["plan-approve", "--workspace", tmp, "--plan-id", "p"]), 0)
            source_path = Path(tmp) / ".agent-workflow/state/tasks/t.json"
            source = json.loads(source_path.read_text())
            source.update({"phase": "code_review", "state": "waiting_user", "task_status": "ready_for_review"})
            atomic_write(source_path, source)
            self.assertEqual(main([
                "revision-create", "--workspace", tmp, "--source-task-id", "t", "--task-id", "t-r1",
                "--summary", "Fix", "--goal", "Fixed", "--failure-reason", "verification failed",
                "--previous-evidence", "test log",
            ]), 0)
            root = Path(tmp) / ".agent-workflow/state/tasks"
            source = json.loads((root / "t.json").read_text())
            revision = json.loads((root / "t-r1.json").read_text())
            self.assertEqual((revision["previous_task_id"], revision["revision"]), ("t", 1))
            self.assertEqual(revision["previous_evidence"], ["test log"])
            self.assertIsNone(source["agent"])
            self.assertEqual(source["superseded_by"], "t-r1")
            self.assertEqual(main([
                "revision-create", "--workspace", tmp, "--source-task-id", "t", "--task-id", "t-r2",
                "--summary", "Fix2", "--goal", "Fixed2", "--failure-reason", "again",
            ]), 2)

    def test_force_preserves_plan_task_ids_and_rejects_heartbeat_active_task(self):
        with tempfile.TemporaryDirectory() as tmp:
            create_plan = [
                "plan-create", "--workspace", tmp, "--plan-id", "plan-1",
                "--title", "Test", "--requirement", "Do thing",
            ]
            self.assertEqual(main(create_plan), 0)
            create_task = [
                "task-create", "--workspace", tmp, "--task-id", "task-1",
                "--plan-id", "plan-1", "--summary", "Summary", "--goal", "Goal",
            ]
            self.assertEqual(main(create_task), 0)
            self.assertEqual(main([*create_plan, "--title", "Revised", "--force"]), 0)
            plan_path = Path(tmp) / ".agent-workflow/state/plans/plan-1.json"
            self.assertEqual(json.loads(plan_path.read_text())["task_ids"], ["task-1"])
            self.assertEqual(main([
                "heartbeat", "--workspace", tmp, "--agent", "codex", "--task-id", "task-1",
            ]), 0)
            self.assertEqual(main([*create_task, "--summary", "Reset", "--goal", "Reset", "--force"]), 2)

    def test_force_move_updates_plan_task_ids(self):
        with tempfile.TemporaryDirectory() as tmp:
            for plan_id in ("plan-1", "plan-2"):
                self.assertEqual(main([
                    "plan-create", "--workspace", tmp, "--plan-id", plan_id,
                    "--title", plan_id, "--requirement", "Do thing",
                ]), 0)
            self.assertEqual(main([
                "task-create", "--workspace", tmp, "--task-id", "task-1",
                "--plan-id", "plan-1", "--summary", "Summary", "--goal", "Goal",
            ]), 0)
            self.assertEqual(main([
                "task-create", "--workspace", tmp, "--task-id", "task-1",
                "--plan-id", "plan-2", "--summary", "Moved", "--goal", "New goal", "--force",
            ]), 0)
            root = Path(tmp) / ".agent-workflow/state/plans"
            self.assertEqual(json.loads((root / "plan-1.json").read_text())["task_ids"], [])
            self.assertEqual(json.loads((root / "plan-2.json").read_text())["task_ids"], ["task-1"])

    def test_plan_approve_and_assign_update_task_and_agent_atomically(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(main([
                "plan-create", "--workspace", tmp, "--plan-id", "plan-1",
                "--title", "Test", "--requirement", "Do thing",
            ]), 0)
            self.assertEqual(main([
                "task-create", "--workspace", tmp, "--task-id", "task-1",
                "--plan-id", "plan-1", "--summary", "Summary", "--goal", "Goal",
            ]), 0)
            assign_args = [
                "assign", "--workspace", tmp, "--task-id", "task-1", "--agent", "codex",
            ]
            self.assertEqual(main(assign_args), 2)
            root = Path(tmp) / ".agent-workflow/state"
            atomic_write(root / "agents/claude.json", {
                "agent": "claude", "active_task_ids": ["task-1"], "current_task_id": "task-1",
            })
            self.assertEqual(main(assign_args), 2)
            (root / "agents/claude.json").unlink()
            self.assertEqual(main([
                "plan-approve", "--workspace", tmp, "--plan-id", "plan-1",
            ]), 0)
            self.assertEqual(main(assign_args), 0)
            root = Path(tmp) / ".agent-workflow/state"
            task = json.loads((root / "tasks/task-1.json").read_text())
            agent = json.loads((root / "agents/codex.json").read_text())
            self.assertEqual((task["agent"], task["phase"], task["state"], task["task_status"]),
                             ("codex", "assigned", "busy", "in_progress"))
            self.assertEqual(agent["active_task_ids"], ["task-1"])
            self.assertEqual(agent["current_task_id"], "task-1")

    def test_unassign_clears_current_task_but_does_not_unassign_active_work(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(main([
                "plan-create", "--workspace", tmp, "--plan-id", "plan-1",
                "--title", "Test", "--requirement", "Do thing",
            ]), 0)
            self.assertEqual(main([
                "task-create", "--workspace", tmp, "--task-id", "task-1",
                "--plan-id", "plan-1", "--summary", "Summary", "--goal", "Goal",
            ]), 0)
            self.assertEqual(main(["plan-approve", "--workspace", tmp, "--plan-id", "plan-1"]), 0)
            self.assertEqual(main([
                "assign", "--workspace", tmp, "--task-id", "task-1", "--agent", "codex",
            ]), 0)
            self.assertEqual(main(["unassign", "--workspace", tmp, "--task-id", "task-1"]), 0)
            root = Path(tmp) / ".agent-workflow/state"
            task = json.loads((root / "tasks/task-1.json").read_text())
            agent = json.loads((root / "agents/codex.json").read_text())
            self.assertIsNone(task["agent"])
            self.assertEqual((task["phase"], task["state"], task["task_status"]), ("docs", "idle", "ready"))
            self.assertEqual(agent["active_task_ids"], [])
            self.assertNotIn("current_task_id", agent)

    def test_reconcile_repairs_task_and_agent_sides_idempotently(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(main([
                "plan-create", "--workspace", tmp, "--plan-id", "plan-1",
                "--title", "Test", "--requirement", "Do thing",
            ]), 0)
            self.assertEqual(main([
                "task-create", "--workspace", tmp, "--task-id", "task-1",
                "--plan-id", "plan-1", "--summary", "Summary", "--goal", "Goal",
            ]), 0)
            root = Path(tmp) / ".agent-workflow/state"
            task_path = root / "tasks/task-1.json"
            task = json.loads(task_path.read_text())
            task.update({"phase": "assigned", "state": "busy", "task_status": "in_progress"})
            atomic_write(task_path, task)
            atomic_write(root / "agents/codex.json", {
                "agent": "codex", "active_task_ids": ["task-1"], "current_task_id": "task-1",
            })
            self.assertEqual(main(["reconcile", "--workspace", tmp]), 0)
            task = json.loads((root / "tasks/task-1.json").read_text())
            self.assertEqual(task["agent"], "codex")
            self.assertEqual(json.loads((root / "agents/codex.json").read_text())["active_task_ids"], ["task-1"])
            self.assertEqual(main(["reconcile", "--workspace", tmp]), 0)

    def test_reconcile_does_not_resurrect_pipeline_task_after_unassign_side_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(main([
                "plan-create", "--workspace", tmp, "--plan-id", "plan-1",
                "--title", "Test", "--requirement", "Do thing",
            ]), 0)
            self.assertEqual(main([
                "task-create", "--workspace", tmp, "--task-id", "task-1",
                "--plan-id", "plan-1", "--summary", "Summary", "--goal", "Goal",
            ]), 0)
            root = Path(tmp) / ".agent-workflow/state"
            task_path = root / "tasks/task-1.json"
            task = json.loads(task_path.read_text())
            task["agent"] = None
            task["phase"] = "docs"
            task["state"] = "idle"
            task["task_status"] = "ready"
            atomic_write(task_path, task)
            atomic_write(root / "agents/codex.json", {
                "agent": "codex", "active_task_ids": ["task-1"], "current_task_id": "task-1",
            })
            self.assertEqual(main(["reconcile", "--workspace", tmp]), 0)
            repaired_task = json.loads(task_path.read_text())
            repaired_agent = json.loads((root / "agents/codex.json").read_text())
            self.assertIsNone(repaired_task["agent"])
            self.assertEqual(repaired_agent["active_task_ids"], [])

    def test_plan_approve_rejects_empty_plan(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(main([
                "plan-create", "--workspace", tmp, "--plan-id", "plan-1",
                "--title", "Empty", "--requirement", "Nothing yet",
            ]), 0)
            self.assertEqual(main(["plan-approve", "--workspace", tmp, "--plan-id", "plan-1"]), 2)

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

    def test_review_evidence_is_recorded_on_task(self):
        with tempfile.TemporaryDirectory() as tmp:
            args = ["--workspace", tmp, "--agent", "codex", "--task-id", "task-1"]
            self.assertEqual(main(["begin", *args, "--phase", "coding"]), 0)
            self.assertEqual(main(["update", *args, "--review-status", "changes_requested", "--review-summary", "Fix test"]), 0)
            self.assertEqual(main(["update", *args, "--review-summary", "Fix test 2"]), 0)
            self.assertEqual(main(["heartbeat", *args]), 0)
            task = json.loads((Path(tmp) / ".agent-workflow/state/tasks/task-1.json").read_text())
            self.assertEqual(task["review"]["status"], "changes_requested")
            self.assertEqual(task["review"]["summary"], "Fix test 2")
            checkpoint = json.loads((Path(tmp) / ".agent-workflow/state/checkpoints/task-1.json").read_text())
            self.assertEqual(checkpoint["review"]["status"], "changes_requested")

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

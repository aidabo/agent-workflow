#!/usr/bin/env python3
import json
import os
import shlex
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OBSERVER = ROOT / "bin" / "agent-merge-observe"


class MergeObserverTests(unittest.TestCase):
    def run_observer(self, *, fail_list=False, fail_view=False, existing_log_dir=False):
        with tempfile.TemporaryDirectory() as root_dir:
            root = Path(root_dir)
            fake_bin = root / "bin"
            fake_bin.mkdir()
            fake_gh = fake_bin / "gh"
            fake_gh.write_text(
                """#!/usr/bin/env bash
printf '%s\n' "$*" >> "$GH_ARGS_LOG"
if [[ "$*" == *"pr merge"* ]]; then
  touch "$MERGE_MARK"
  exit 99
fi
if [[ "$1" == pr && "$2" == list ]]; then
  if [[ "${GH_FAIL_LIST:-0}" == 1 ]]; then
    echo 'list unavailable' >&2
    exit 7
  fi
  echo 123
  exit 0
fi
if [[ "$1" == pr && "$2" == view ]]; then
  if [[ "${GH_FAIL_VIEW:-0}" == 1 ]]; then
    echo 'view unavailable' >&2
    exit 8
  fi
  echo '{"state":"OPEN","isDraft":false,"baseRefName":"main","headRefOid":"aaaaaaaaaaaaaaaa","labels":[{"name":"author:codex"}],"author":{"login":"aidabo"}}'
  exit 0
fi
if [[ "$1" == api ]]; then
  echo '[]'
  exit 0
fi
exit 98
""",
                encoding="utf-8",
            )
            fake_gh.chmod(0o755)
            config = root / "config.local.sh"
            config.write_text(
                "REPOS=(\n"
                f"  \"fixture|owner/repo|{shlex.quote(str(root / 'src'))}|{shlex.quote(str(root / 'wt'))}\"\n"
                ")\n"
                f"STATE_DIR={shlex.quote(str(root / 'state'))}\n"
                f"REPORT_DIR={shlex.quote(str(root / 'reports'))}\n",
                encoding="utf-8",
            )
            log_dir = root / "logs"
            if existing_log_dir:
                log_dir.mkdir()
                log_dir.chmod(0o755)
            log_file = log_dir / "observe.jsonl"
            args_log = root / "gh-args.log"
            merge_mark = root / "merge-called"
            env = os.environ.copy()
            env.update({
                "PATH": f"{fake_bin}:{env['PATH']}",
                "CROSS_REVIEW_CONFIG": str(config),
                "AUTO_MERGE_OBSERVE_LOG": str(log_file),
                "MERGE_MARK": str(merge_mark),
                "GH_ARGS_LOG": str(args_log),
                "GH_FAIL_LIST": "1" if fail_list else "0",
                "GH_FAIL_VIEW": "1" if fail_view else "0",
            })
            result = subprocess.run([str(OBSERVER)], env=env, text=True, capture_output=True)
            records = [json.loads(line) for line in log_file.read_text().splitlines()]
            log_mode = stat.S_IMODE(log_file.stat().st_mode)
            log_dir_mode = stat.S_IMODE(log_file.parent.stat().st_mode)
            return result, records, log_mode, log_dir_mode, merge_mark.exists(), args_log.read_text()

    def test_gate_result_is_logged_without_merging(self):
        result, records, log_mode, log_dir_mode, merge_called, gh_args = self.run_observer()
        self.assertEqual(result.returncode, 0)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["kind"], "gate")
        self.assertEqual(records[0]["pr"], 123)
        self.assertEqual(records[0]["exit_code"], 2)
        self.assertFalse(merge_called)
        self.assertIn("--label automation:auto-merge", gh_args)
        self.assertEqual(log_mode, 0o600)
        self.assertEqual(log_dir_mode, 0o700)

    def test_list_failure_is_logged_and_returns_nonzero(self):
        result, records, _log_mode, _log_dir_mode, merge_called, _gh_args = self.run_observer(fail_list=True)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(records[0]["kind"], "list_error")
        self.assertEqual(records[0]["pr"], 0)
        self.assertEqual(records[0]["exit_code"], 7)
        self.assertIn("list unavailable", records[0]["output"])
        self.assertFalse(merge_called)

    def test_gate_failure_is_distinguished_and_returns_nonzero(self):
        result, records, _log_mode, _log_dir_mode, merge_called, _gh_args = self.run_observer(fail_view=True)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(records[0]["kind"], "gate_error")
        self.assertEqual(records[0]["exit_code"], 8)
        self.assertIn("view unavailable", records[0]["output"])
        self.assertFalse(merge_called)

    def test_existing_log_directory_mode_is_unchanged(self):
        result, _records, _log_mode, log_dir_mode, _merge_called, _gh_args = self.run_observer(existing_log_dir=True)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(log_dir_mode, 0o755)


if __name__ == "__main__":
    unittest.main()

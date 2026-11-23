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
    def run_observer(self, *, fail_list=False):
        with tempfile.TemporaryDirectory() as root_dir:
            root = Path(root_dir)
            fake_bin = root / "bin"
            fake_bin.mkdir()
            fake_gh = fake_bin / "gh"
            fake_gh.write_text(
                """#!/usr/bin/env bash
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
            log_file = root / "logs" / "observe.jsonl"
            merge_mark = root / "merge-called"
            env = os.environ.copy()
            env.update({
                "PATH": f"{fake_bin}:{env['PATH']}",
                "CROSS_REVIEW_CONFIG": str(config),
                "AUTO_MERGE_OBSERVE_LOG": str(log_file),
                "MERGE_MARK": str(merge_mark),
                "GH_FAIL_LIST": "1" if fail_list else "0",
            })
            result = subprocess.run([str(OBSERVER)], env=env, text=True, capture_output=True)
            records = [json.loads(line) for line in log_file.read_text().splitlines()]
            log_mode = stat.S_IMODE(log_file.stat().st_mode)
            log_dir_mode = stat.S_IMODE(log_file.parent.stat().st_mode)
            return result, records, log_mode, log_dir_mode, merge_mark.exists()

    def test_gate_result_is_logged_without_merging(self):
        result, records, log_mode, log_dir_mode, merge_called = self.run_observer()
        self.assertEqual(result.returncode, 0)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["kind"], "gate")
        self.assertEqual(records[0]["pr"], 123)
        self.assertEqual(records[0]["exit_code"], 2)
        self.assertFalse(merge_called)
        self.assertEqual(log_mode, 0o600)
        self.assertEqual(log_dir_mode, 0o700)

    def test_list_failure_is_logged_and_returns_nonzero(self):
        result, records, _log_mode, _log_dir_mode, merge_called = self.run_observer(fail_list=True)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(records[0]["kind"], "list_error")
        self.assertEqual(records[0]["pr"], 0)
        self.assertEqual(records[0]["exit_code"], 7)
        self.assertIn("list unavailable", records[0]["output"])
        self.assertFalse(merge_called)


if __name__ == "__main__":
    unittest.main()

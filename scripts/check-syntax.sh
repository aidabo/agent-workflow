#!/usr/bin/env bash
set -euo pipefail

while IFS= read -r -d '' file; do
  bash -n "$file"
done < <(find agent-notify cross-review scripts -type f -name '*.sh' -print0)

for file in bin/agent-start bin/agent-monitor bin/cross-review bin/agent-merge-gate bin/agent-merge-observe bin/agent-workflow; do
  bash -n "$file"
done

node --check agent-notify/hooks/native-hook.mjs
python3 -m py_compile $(find agent-notify cross-review src tests -type f -name '*.py' | sort) bin/agent-orchestrator bin/agent-orchestrator-fanout bin/agent-provider
echo '[OK] shell/node/python syntax'

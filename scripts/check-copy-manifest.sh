#!/usr/bin/env bash
set -euo pipefail

repo_root="${AGENT_WORKFLOW_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
source_root="${AGENT_TOOLS_SOURCE_ROOT:-$repo_root/../10-agent-tools}"
source_ref="${AGENT_TOOLS_SOURCE_REF:-origin/main}"

if ! git -C "$source_root" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  echo "missing source repository: $source_root" >&2
  exit 2
fi

source_manifest="$(mktemp)"
target_manifest="$(mktemp)"
trap 'rm -f "$source_manifest" "$target_manifest"' EXIT

git -C "$source_root" ls-tree -r --name-only "$source_ref" -- agent-notify cross-review | sort >"$source_manifest"
git -C "$repo_root" ls-files -s agent-notify cross-review \
  | awk '{print $4}' | sort >"$target_manifest"

if ! diff -u "$source_manifest" "$target_manifest"; then
  echo "copy manifest differs" >&2
  exit 1
fi
source_sha="$(git -C "$source_root" rev-parse "$source_ref")"
echo "[OK] tracked path manifest matches $source_root@$source_ref ($source_sha)"

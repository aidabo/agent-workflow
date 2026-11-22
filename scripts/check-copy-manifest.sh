#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source_root="${AGENT_TOOLS_SOURCE_ROOT:-$repo_root/../10-agent-tools}"
source_ref="${AGENT_TOOLS_SOURCE_REF:-origin/main}"

if [[ ! -d "$source_root/.git" ]]; then
  echo "missing source repository: $source_root" >&2
  exit 2
fi

source_manifest="$(mktemp)"
target_manifest="$(mktemp)"
trap 'rm -f "$source_manifest" "$target_manifest"' EXIT

git -C "$source_root" ls-tree -r --name-only "$source_ref" agent-notify cross-review | sort >"$source_manifest"
(
  cd "$repo_root"
  find agent-notify cross-review -type f \
    -not -path '*/__pycache__/*' \
    -not -name 'config.local.sh' \
    -print | sed 's#^./##' | sort
) >"$target_manifest"

if ! diff -u "$source_manifest" "$target_manifest"; then
  echo "copy manifest differs" >&2
  exit 1
fi
echo "[OK] tracked agent-notify/cross-review manifest matches $source_root@$source_ref"

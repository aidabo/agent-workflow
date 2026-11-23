#!/usr/bin/env bash
set -euo pipefail

repo_root="${AGENT_WORKFLOW_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
source_root="${AGENT_TOOLS_SOURCE_ROOT:-$repo_root/../10-agent-tools}"
source_ref="${AGENT_TOOLS_SOURCE_REF:-origin/main}"

source_root="$(realpath "$source_root")"
if ! git -C "$source_root" rev-parse --is-inside-work-tree >/dev/null 2>&1 || \
   [[ "$(realpath "$(git -C "$source_root" rev-parse --show-toplevel)")" != "$source_root" ]]; then
  echo "missing source repository: $source_root" >&2
  exit 2
fi

source_manifest="$(mktemp)"
target_manifest="$(mktemp)"
trap 'rm -f "$source_manifest" "$target_manifest"' EXIT

# These files intentionally specialize the copied runtime for this standalone
# repository (storage paths, cron markers, session names, or new gate code).
# Keep the allowlist tracked and explicit so unrelated copy drift still fails.
standalone_paths="$(sed -e '/^[[:space:]]*#/d' -e '/^[[:space:]]*$/d' "$repo_root/scripts/standalone-runtime-paths.txt")"
filter_standalone() {
  while IFS= read -r path; do
    grep -qxF "$path" <<<"$standalone_paths" || echo "$path"
  done
}
git -C "$source_root" ls-tree -r --name-only "$source_ref" -- agent-notify cross-review | \
  filter_standalone | sort >"$source_manifest"
git -C "$repo_root" ls-files -- agent-notify cross-review | while IFS= read -r path; do
  printf '%s\n' "$path"
done | filter_standalone | sort >"$target_manifest"

if ! diff -u "$source_manifest" "$target_manifest"; then
  echo "copy manifest differs" >&2
  exit 1
fi
source_sha="$(git -C "$source_root" rev-parse "$source_ref")"
echo "[OK] tracked path manifest matches $source_root@$source_ref ($source_sha)"

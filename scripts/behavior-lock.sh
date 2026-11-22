#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

./scripts/check-copy-manifest.sh
make check

if [[ -n "${OLD_SNAPSHOT:-}" && -n "${NEW_SNAPSHOT:-}" ]]; then
  ./scripts/compare-snapshots.sh "$OLD_SNAPSHOT" "$NEW_SNAPSHOT"
fi

echo '[OK] behavior-lock prerequisites passed'
echo '[NEXT] run old/new monitor and review fixture snapshots before workspace cutover'

#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

./scripts/check-copy-manifest.sh
make check

echo '[OK] behavior-lock prerequisites passed'
echo '[NEXT] run old/new monitor and review fixture snapshots before workspace cutover'

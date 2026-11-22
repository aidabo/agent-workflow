#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 2 ]]; then
  echo "usage: $0 OLD_SNAPSHOT NEW_SNAPSHOT" >&2
  exit 2
fi

normalize() {
  sed -E \
    -e $'s/\033\\[[0-9;]*m//g' \
    -e 's/[0-9]{2}:[0-9]{2}:[0-9]{2}/TIME/g' \
    -e 's#/home/[^ ]*/10-agent-tools#WORKSPACE/TOOL#g' \
    -e 's#/home/[^ ]*/11-agent-workflow#WORKSPACE/TOOL#g' "$1"
}

if diff -u <(normalize "$1") <(normalize "$2"); then
  echo '[OK] normalized snapshots match'
else
  echo '[DIFF] normalized snapshots differ' >&2
  exit 1
fi

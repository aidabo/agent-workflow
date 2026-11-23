#!/usr/bin/env bash
# Manage the standalone observer cron entry. cross-review/watch cron is
# delegated to cross-review/install.sh so its existing backup behavior remains.
set -euo pipefail

root="$(cd "$(dirname "$(readlink -f "$0")")/.." && pwd)"
mode="${1:-check}"
marker="# agent-workflow-observe"
log_dir="${HOME}/.cache/agent-workflow"
line="*/5 * * * * $root/bin/agent-workflow observe >> \$HOME/.cache/agent-workflow/observe.cron.log 2>&1 $marker"

command -v crontab >/dev/null 2>&1 || {
  echo "crontab is not installed" >&2
  exit 2
}

current_crontab() { crontab -l 2>/dev/null || true; }

case "$mode" in
  check)
    if current_crontab | grep -Fq "$marker"; then
      echo "observer cron: installed"
    else
      echo "observer cron: not installed"
    fi
    ;;
  install)
    mkdir -p "$log_dir"
    chmod 700 "$log_dir"
    current_crontab > "$log_dir/crontab.bak.$(date +%Y%m%d%H%M%S)"
    existing="$(current_crontab | grep -vF "$marker" || true)"
    {
      [[ -n "$existing" ]] && printf '%s\n' "$existing"
      printf '%s\n' "$line"
    } | crontab -
    echo "observer cron: installed (every 5 minutes)"
    ;;
  uninstall)
    current_crontab > "$log_dir/crontab.bak.$(date +%Y%m%d%H%M%S)"
    existing="$(current_crontab | grep -vF "$marker" || true)"
    printf '%s\n' "$existing" | crontab -
    echo "observer cron: uninstalled"
    ;;
  *)
    echo "usage: $0 {check|install|uninstall}" >&2
    exit 64
    ;;
esac

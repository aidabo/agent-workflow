# Phase 2 live smoke

## 目的

既存のcross-review boardとtmux agent表示を残したまま、standalone task sectionが同じmonitor paneに
表示されることを確認する。

## 実行方法

本番workspaceではなく、一時workspaceと一時tmux sessionを使う。

```bash
repo="$HOME/work/legacy/11-agent-workflow"
smoke="$(mktemp -d)"
session="agent-workflow-smoke-$$"
trap 'tmux kill-session -t "=$session" 2>/dev/null || true; rm -rf "$smoke"' EXIT

AGENT_WORKFLOW_WORKSPACE="$smoke" "$repo/bin/agent-status" begin \
  --workspace "$smoke" --agent codex --task-id smoke-a --phase coding \
  --goal "monitor smoke"
AGENT_WORKFLOW_WORKSPACE="$smoke" "$repo/bin/agent-status" begin \
  --workspace "$smoke" --agent claude --task-id smoke-b --phase docs \
  --goal "docs smoke"

AGENTS_MONITOR_SESSION="$session" AGENT_WORKFLOW_WORKSPACE="$smoke" \
  bash "$repo/agent-notify/monitor.sh" --detach
sleep 1
tmux list-panes -t "=$session" -F '#{pane_index} #{pane_title} #{pane_current_command}'
```

boardをcaptureし、次が同じ画面にあることを確認する。

```text
cross-review  no open PRs
エージェント    ThinkAI-Agents ...
タスク         claude [docs] smoke-b ...
               codex [coding] smoke-a ...
```

## 実測結果（2026-11-23）

- unprivileged sandbox: tmux socket `Operation not permitted`（実行環境の制約）
- privileged local smoke: 成功
- cross-review section: 表示
- existing tmux agent section: 表示
- task section: 2 task（codex/claude）表示
- heartbeat、phase、test、PR列: 表示
- 一時session/workspace: cleanup済み

このsmokeはGitHubへの書き込み、PR作成、agentへの入力、実装taskのclaimを行わない。

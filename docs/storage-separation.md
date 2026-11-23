# 10-agent-toolsからの保存領域分離

`10-agent-tools`を停止・削除せずに`11-agent-workflow`へ切り替えられるよう、両runtimeのローカル状態を分離する。

## 分離後の領域

| データ | 10-agent-tools | 11-agent-workflow |
|---|---|---|
| review report | `<workspace>/.agent-tools/reviews/` | `<workspace>/.agent-workflow/reviews/` |
| review state | `~/.cache/cross-review/state/` | `~/.cache/agent-workflow/cross-review/state/` |
| watch/live log | `~/.cache/cross-review/` | `~/.cache/agent-workflow/cross-review/` |
| inbox | `10-agent-tools/cross-review/inbox/` | `11-agent-workflow/cross-review/inbox/` |
| review worktree | `<project>-review` | `<project>-agent-workflow-review` |
| agent tmux session | 旧設定 | `<project>-agent-workflow-agents` |
| monitor tmux session | `agents-monitor` | `agent-workflow-monitor` |

GitHubのPR・コメント・label・branchは共有される。ローカルreport/state/inbox/worktree/cronだけを分ける。

## 切り替え手順

1. 10-agent-toolsの作業を止めずに、11-agent-workflowの`config.local.sh`を作る。
2. `REPOS`の4列目を`<project>-agent-workflow-review`にする。
3. 11-agent-workflowの`agent`/`monitor`を新しいtmux sessionで起動する。
4. 新runtimeの`cross-review/install.sh`を実行する。marker付きの11側cronだけが追加され、10側cronは変更されない。
5. 新runtimeのreview report、state、inboxが専用領域へ書かれることを確認する。
6. 確認後、10-agent-toolsのcronを手動で停止し、旧runtimeをread-only archiveとして残す。

## 切り戻し

新runtimeに問題がある場合は、11側のcronだけを解除する。

```bash
11-agent-workflow/cross-review/install.sh --uninstall
```

10-agent-tools側のcron・state・reportは変更していないため、旧`agent`/`monitor`を起動して戻せる。新runtimeで作成したGitHub PRやコメントはGitHubに残るため、切り戻し時もPRの状態を確認してから続行する。

## 注意

- 10側と11側を同じprojectの同じreview worktreeで同時に動かさない。
- 旧stateを新stateへコピーしない。GitHubのPR headと新inboxを確認して再開する。
- 11側のinstall/uninstallはmarker`# agent-workflow-cross-review-watch`だけを対象にし、10側のcron行を削除しない。

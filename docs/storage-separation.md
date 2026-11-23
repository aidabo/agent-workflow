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
| agent tmux session | 旧設定 | `<workspace folder>-agent-workflow-agents` |
| monitor tmux session | `agents-monitor` | `agent-workflow-monitor` |

GitHubのPR・コメント・label・branchは共有される。ローカルreport/state/inbox/worktree/cronだけを分ける。

## 切り替え手順

1. 10-agent-toolsの作業を止めずに、11-agent-workflowの`config.local.sh`を作る。
2. canary用`REPOS` entryの4列目を`<project>-agent-workflow-review`にする。
3. まず旧10側の`REPOS`にないcanary repositoryを1件だけ11側へ登録する。
4. `11-agent-workflow/cross-review/install.sh`を実行し、canaryだけでreport、state、inbox、tmux session、cronが専用領域になることを確認する。
5. 全repositoryを切り替える前に、10-agent-toolsのcronを停止する。同じPRを10/11で並行reviewすると、コメントと通知が二重になる。
6. 11側の`REPOS`を全repositoryへ広げ、11-agent-workflowの`agent`/`monitor`を新しいtmux sessionで起動する。
7. 旧runtimeはrollback用にread-only保持する。

## 切り戻し

新runtimeに問題がある場合は、11側のcronだけを解除する。

```bash
11-agent-workflow/cross-review/install.sh --uninstall
```

10-agent-tools側のcron・state・reportは変更していないため、旧`agent`/`monitor`を起動して戻せる。新runtimeで作成したGitHub PRやコメントはGitHubに残るため、切り戻し時もPRの状態を確認してから続行する。

## 注意

- 10側と11側を同じprojectの同じreview worktreeで同時に動かさない。
- 移行確認中に同じPRを二重reviewしない。canary repositoryを使うか、対象PRに`no-cross-review`を付ける。
- 旧stateを新stateへコピーしない。GitHubのPR headと新inboxを確認して再開する。
- 11側のinstall/uninstallはmarker`# agent-workflow-cross-review-watch`と、このcloneの旧watch.sh行だけを対象にし、10側のcron行を削除しない。

# Monitor design

## 画面構成

既存cross-reviewの表示は残し、その下または横にagent/task metadataを表示する。monitor paneの
workspaceは`AGENT_WORKFLOW_WORKSPACE`で渡し、未指定時だけ現在のcwdを使う。

```text
┌─────────────────────────────────────────────────────────────┐
│ cross-review: PR / WAITING / IN REVIEW / APPROVED / NEEDS YOU │
├─────────────────────────────────────────────────────────────┤
│ agent   phase       task       PR     test    heartbeat repo  │
│ codex   test        runner-01  #783   passed  12:10     front │
│ codex   coding      stack-042  —      running 12:09     front │
│ claude  code_review docs-014   #793   waiting 12:08     front │
├─────────────────────────────────────────────────────────────┤
│ review live: current reviewer / event / last update           │
└─────────────────────────────────────────────────────────────┘
```

## 情報源の優先順位

1. agent-workflow status JSON: task、phase、heartbeat、test
2. Git: branch、commit、dirty
3. GitHub PR: PR、review、merge state
4. tmux pane: busy/attention/typing/idleの補助情報

更新間隔の初期値は、tmux/statusを3秒、GitHub/cross-reviewを20秒とする。GitHub APIが遅い間も
local task/heartbeat表示は更新する。screenshot/referenceのdirectory scanはtask開始または
設定変更時だけ行い、毎フレーム全folderを走査しない。

同じagentの複数taskはtaskごとに別行で表示する。cross-reviewのreview stateは対象PRのtaskだけに
紐付け、別taskを`blocked`へ変更しない。task間の依存がある場合だけ`blocked_by`を表示する。

task欄はpane高さから表示行数を計算し、最大8件まで表示する（省略行を除く）。低いpaneでは
1件まで自動的に減らし、収まらない履歴は「他N task」とまとめる。review欄とagent欄を押し出さず、
完了taskはactive taskの後に表示する。

agent行には、同じagentのpaneが1つで、`state/agents/<agent>.json`の`current_task_id`が
指す未完了・staleでないtaskがある場合に、そのtaskの`goal`または`next_action`を短く表示する。
複数paneやcurrent taskが無い場合は誤表示を避けるため文脈を表示しない。

タスク欄の`現在の作業task未登録`は、paneの作業内容を推測していない状態を示す。
タスク欄は`state/tasks/*.json`の登録で表示され、agent行の文脈対応には
`state/agents/<agent>.json.current_task_id`を使う。登録とcurrent task更新は
`bin/agent-status begin --workspace … --agent … --task-id … --goal "…"`で行い、agent indexを手編集しない。

取得失敗は`unknown`と表示し、推測で`done`にしない。GitHub APIが遅くてもpane stateの更新を
止めない。

## 表示すべき状態

| 表示 | 意味 |
|---|---|
| `作業中` | heartbeatが有効でagentが実行中 |
| `人確認待ち` | 通常の確認・選択待ち |
| `BLOCKED` | 外部依存、権限、他taskで停止 |
| `STALE` | 設定された`stale_after_seconds`以上heartbeatなし（既定600秒） |
| `NEEDS YOU` | review上限、仕様判断、merge判断 |
| `APPROVED` | cross-reviewは完了、人のmerge待ち |

## monitorがしないこと

- agent paneへ自動入力しない
- PRを自動mergeしない
- taskを人の承認なしにcodingへ進めない
- screenshotを外部APIへ自動uploadしない

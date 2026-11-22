# Monitor design

## 画面構成

既存cross-reviewの表示は残し、その下または横にagent/task metadataを表示する。

```text
┌─────────────────────────────────────────────────────────────┐
│ cross-review: PR / WAITING / IN REVIEW / APPROVED / NEEDS YOU │
├─────────────────────────────────────────────────────────────┤
│ agent   phase       task       PR     test    heartbeat repo  │
│ codex   test        runner-01  #783   passed  12:10     front │
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

取得失敗は`unknown`と表示し、推測で`done`にしない。GitHub APIが遅くてもpane stateの更新を
止めない。

## 表示すべき状態

| 表示 | 意味 |
|---|---|
| `作業中` | heartbeatが有効でagentが実行中 |
| `人確認待ち` | 通常の確認・選択待ち |
| `BLOCKED` | 外部依存、権限、他taskで停止 |
| `STALE` | 600秒以上heartbeatなし |
| `NEEDS YOU` | review上限、仕様判断、merge判断 |
| `APPROVED` | cross-reviewは完了、人のmerge待ち |

## monitorがしないこと

- agent paneへ自動入力しない
- PRを自動mergeしない
- taskを人の承認なしにcodingへ進めない
- screenshotを外部APIへ自動uploadしない

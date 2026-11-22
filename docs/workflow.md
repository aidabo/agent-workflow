# Workflow state machine

## docsから人のmergeまで

```mermaid
stateDiagram-v2
  [*] --> planned
  planned --> docs: 目的と完了条件を確定
  docs --> docs_review: docs PR作成
  docs_review --> docs: CHANGES_REQUESTED
  docs_review --> human_review: APPROVE
  human_review --> assigned: 人がdocsを確認/merge
  human_review --> needs_human: 仕様判断・保留
```

## 実装から人のmergeまで

```mermaid
stateDiagram-v2
  assigned --> coding: agentへ割当
  coding --> test: 実装完了
  test --> coding: test失敗/修正
  test --> code_review: test成功・code PR
  code_review --> coding: CHANGES_REQUESTED
  code_review --> human_review: APPROVE
  human_review --> done: 人が確認/merge
  human_review --> needs_human: review上限/仕様判断
  needs_human --> coding: 人が再開
```

## metadataの意味

`phase`、`state`、`task_status`を混ぜない。

| key | 例 | 意味 |
|---|---|---|
| `phase` | `docs`, `coding`, `test`, `code_review` | 作業の段階 |
| `state` | `busy`, `waiting_user`, `blocked`, `stale`, `needs_human` | agent/taskの現在状態 |
| `task_status` | `planned`, `ready`, `in_progress`, `ready_for_review`, `done` | taskの進行状態 |

通常の人確認待ちは`waiting_user`、レビュー上限・権限・仕様判断のエスカレーションは
`needs_human`とする。

## stale

初期設定:

```yaml
heartbeat_interval_seconds: 60
stale_after_seconds: 600
```

`stale_after_seconds`はheartbeat intervalの10倍以上でなければならず、設定読み込み時に
拒否する。599秒はstaleではなく、600秒以上でstaleになる境界testを持つ。

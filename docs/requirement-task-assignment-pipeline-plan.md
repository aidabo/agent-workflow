# 要件からagent割り当てまでのworkflow企画書

## 1. 目的

現在の`11-agent-workflow`は、task JSON、agent index、heartbeat、monitor、cross-reviewを持つが、
次の流れが未実装である。

```text
要件 → plan → task list → agent割り当て → agent実行 → test/review → 完了
```

本企画では、要件とplanから実行可能なtaskを作り、agentの`current_task_id`へ安全に割り当て、
monitorで「誰が何をしているか」を継続表示できる状態を作る。

## 2. 基準点と範囲

- 基準workflow: `v0.2.0`（PR #27までを含む安定点）
- pipeline実装は、この企画書PRとは別branch・別PRで行う
- 既存のcross-review、checkpoint、resume、monitor表示は壊さない
- agent paneへ勝手に入力する動作は初期範囲に含めない
- 外部API、GitHub issue、LLMによる自動分解は初期範囲に含めず、ローカルJSON契約から始める

## 3. 利用者の操作イメージ

```text
1. 人が要件と完了条件を書く
2. plannerがplanを作成する
3. planからtask listを生成する
4. 人がtaskとagentを確認する
5. assignでagentのcurrent_task_idを更新する
6. agentが同じtask_idで作業し、heartbeat/test/endを更新する
7. monitorがagentごとの内容・phase・次の操作を表示する
8. PR作成後は既存cross-reviewへ渡す
```

## 4. データ契約案

### 4.1 Plan

保存先: `.agent-workflow/plans/<plan_id>.json`

```json
{
  "plan_id": "plan-20261126-example",
  "title": "短い計画名",
  "requirement": "利用者が達成したいこと",
  "acceptance_criteria": ["確認可能な完了条件"],
  "task_ids": ["task-001", "task-002"],
  "status": "draft"
}
```

### 4.2 Task

既存の`.agent-workflow/state/tasks/<task_id>.json`を正本として拡張する。

必須または推奨フィールド:

- `task_id`: 安定したID
- `plan_id`: 所属plan
- `agent`: 割り当てagent。未割り当てはnull
- `summary`: monitorに表示する短い作業概要
- `goal`: 完了時に達成すること
- `next_action`: 次に行う操作
- `acceptance_criteria`: task固有の完了条件
- `phase`, `state`, `task_status`: 既存status契約に従う
- `branch`, `pr`, `test`: 実行後に更新

### 4.3 Agent index

既存の`.agent-workflow/state/agents/<agent>.json`を使用する。

- `active_task_ids`: 現在担当するtask
- `current_task_id`: monitorとresumeが表示・再開に使うtask
- `heartbeat_at`: agentの生存状態

割り当てはtask JSONとagent indexを同じロック・atomic更新単位で更新し、片方だけ更新された状態を
避ける。

## 5. 状態遷移

```text
plan draft
  → plan approved
  → task planned
  → task assigned
  → task in_progress
  → task ready_for_review
  → task done
```

割り当て解除、stale、needs_humanは通常の進行と分ける。

- `planned`: taskは作成済みだがagent未割り当て
- `assigned`: agentとcurrent_task_idが確定したが作業開始前
- `in_progress`: agentが作業中
- `stale`: heartbeat期限超過。自動再割り当てしない
- `needs_human`: 要件・権限・レビュー上限など人の判断が必要

## 6. CLI案

既存`bin/agent-workflow`または新しい`bin/agent-plan`へ段階的に追加する。

```text
agent-plan create --title "..." --requirement "..."
agent-plan add-task --plan plan-... --task-id task-001 --summary "..." --goal "..."
agent-plan list --plan plan-...
agent-plan assign --task task-001 --agent codex
agent-plan unassign --task task-001
agent-plan show --task task-001
```

初期実装では、入力をJSON/CLIから受け取り、LLMによる自動task分解は行わない。

## 7. 安全境界

- taskのagent割り当ては人の明示操作を初期既定にする
- 同じtaskを複数agentへ割り当てない（明示的なparallel taskを除く）
- 完了済みtaskは再割り当てしない。再開は新しいtaskまたはresume契約を使う
- stale taskを自動で別agentへ移さない
- agent indexのcurrent taskとtask JSONのagentが不一致ならmonitorで警告する
- secret、credential、任意のpane入力はplan/task本文に保存しない
- plan/taskの削除は初期範囲に入れず、archiveまたはdone保持にする

## 8. 実装フェーズ

### Phase 1: 契約と読み取り

- plan/taskのschemaとvalidation
- task list表示
- agent indexとの整合性チェック
- monitorでsummary / goal / next_actionを表示

### Phase 2: 明示割り当て

- `assign` / `unassign` CLI
- task JSONとagent indexのatomic更新
- current taskのagent行表示
- 重複割り当て・done/stale割り当て拒否

### Phase 3: agent実行との接続

- `begin`がassigned taskをin_progressへ遷移
- heartbeat/test/endとplan acceptance criteriaの連携
- resume候補にplan/taskの内容を表示

### Phase 4: review連携

- taskのPR/headを記録
- cross-review状態をtaskの完了条件へ反映
- NEEDS YOUをtask stateへ反映するが、自動修正・自動mergeはしない

## 9. 受け入れ条件

- planから複数taskを作成できる
- task listから未割り当てtaskと割り当て済みtaskを区別できる
- assign後、agent indexのcurrent_task_idが正しく更新される
- 同じagentが複数taskを持つ場合もcurrent taskが一意に表示される
- task JSONまたはagent indexの片方が壊れてもmonitorが停止しない
- monitorで各agentのsummary / next_action / phase / stateが表示される
- stale/done taskの誤再割り当てを拒否する
- 既存のcross-reviewとcheckpoint/resumeのテストが成功する

## 10. 実装branch方針

- この文書: `docs/requirement-task-assignment-pipeline-plan`
- pipeline実装: このPRをマージした後、`main`から新しい`feat/requirement-task-assignment-pipeline` branchを作る
- Phaseごとに小さいPRへ分け、各PRでcross-reviewを完了させる
- `v0.2.0`はpipeline実装前のbase tagとして保持する


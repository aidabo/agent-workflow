# Phase 1 人間向けrunbook

## 目的

このrunbookは、要件をOrchestratorへ渡し、plan/taskを確認するまでの人間の操作手順を定義する。
assign、current task表示、reconcile、revision実行のうち、assign/reconcileはPhase 2で実装済みである。
revision実行は後続Phaseの手順であり、Phase 1の完了条件には含めない。

> 注意: `plan-create`、`task-create`、`plan-approve`、`assign`、`unassign`、`reconcile`はPhase 1/2のCLIである。
> planを承認してからassignし、task JSONとagent indexを正本としてpaneへ指示する。

## 1. 開始前の確認

```bash
cd <WORKFLOW_HOME>
git status --short --branch
git tag --points-at HEAD
```

確認事項:

- 対象workspace、repository、branchが明確である
- 作業対象が`v0.2.0`以降のworkflow契約に沿っている
- 既存の未完了task、PR、cross-review、NEEDS YOUがない
- secret、credential、個人情報を要件本文へ書かない

## 2. 要件入力

Orchestratorへ、次の順で要件を渡す。

```text
背景: なぜ必要か
利用者: 誰が使うか
困りごと: 現在何が問題か
期待結果: 何ができれば成功か
対象: 今回変更する範囲
対象外: 今回変更しない範囲
制約: 既存仕様、互換性、期限、権限、性能
完了条件: 実行して確認できる条件
```

Orchestratorは、内容が明確なら短い確認だけで進める。曖昧さやリスクがある場合は、次の
interview modeを選ぶ。

- `skip`: 低riskで完了条件が明確
- `targeted`: 不明点が限定されている
- `full`: scope、利用者、互換性、完了条件が大きく曖昧

## 3. Interviewの回答

人は質問に回答し、仮定を承認または修正する。Orchestratorは会話をそのまま正本にせず、次の
clarified requirementへまとめる。

```json
{
  "problem": "何が困っているか",
  "users": ["誰が使うか"],
  "desired_outcome": "どうなれば成功か",
  "scope": ["含める範囲"],
  "non_goals": ["含めない範囲"],
  "constraints": ["守る条件"],
  "acceptance_criteria": ["確認可能な完了条件"],
  "open_questions": [],
  "assumptions": [],
  "risk_level": "low|medium|high"
}
```

`open_questions`が残る場合は、次のいずれかを人が選ぶ。

1. 追加interviewを行う
2. 仮定を承認して進める
3. 要件を保留する

## 4. Planの確認

Orchestratorがplan draftを作ったら、人は次を確認する。

- 要件とscopeが一致している
- 対象外が明記されている
- acceptance criteriaが検証可能である
- taskの依存関係に循環がない
- work agentが実行できる粒度である
- test/evidenceの方法がある
- data、認証、migration、deployなどの高risk領域が明示されている

planはdocs PRにし、cross-reviewで確認する。cross-reviewがAPPROVEになるまで、実装taskを
assignedにしない。

## 5. Task listと割り当て

plan承認後、task listを確認する。

| 確認項目 | 判断 |
|---|---|
| task summary | 一目で作業内容が分かるか |
| goal | 完了条件と一致しているか |
| next_action | 最初の操作が具体的か |
| acceptance criteria | test/evidenceで確認できるか |
| agent候補 | 必要な技能・repositoryを持つか |
| 依存関係 | 前taskが終わるまで開始してはいけないtaskが明確か |

割り当てはplan承認後にPhase 2 CLIで人が実行する。

```bash
agent-status plan-approve --plan-id plan-001
agent-status assign --task-id task-001 --agent codex
```

assign後の正しい状態は次のとおり。

```text
task:  phase=assigned / task_status=in_progress / state=busy
agent: active_task_idsにtask-001、current_task_id=task-001
```

`pipeline_managed=true`のtaskは、`plan-approve`と`assign`を経てからwork sessionへ渡す。

assign後、work agentは同じtask IDで`begin --phase coding`を実行する。未assignのpipeline taskは
beginできない。複数taskを同じagentが持つ場合、heartbeat/updateはcurrent taskを勝手に切り替えず、
切り替えは同じagentへの明示的な`assign --task-id <task>`で行う。

## 6. Work agentへの引き渡し

Work sessionへ渡す指示は、task IDを必ず含める。

```text
task_id: task-001
summary: monitorのtask表示を改善
goal: agentごとの現在taskを表示する
next_action: agent indexのcurrent_task_idを確認する
acceptance_criteria:
  - monitorでcodexのcurrent taskが表示される
  - testsが成功する
  - 既存のtask表示を壊さない
```

paneへの自然文指示は実行の補助であり、task JSONの代わりにはしない。

## 7. 実行中の確認

monitorで次を確認する。

- agent欄: agent、状態、current taskのsummary
- task欄: phase、state、task_status、内容、次の操作
- heartbeatが更新されている
- test結果が記録されている
- checkpointが必要な段階で保存されている

異常時の判断:

- task未登録: agent-status begin/assignの登録状態を確認する
- stale: 自動再割り当てせず、人が判断する
- task/index不一致: monitorの警告を記録する。Phase 1ではtask JSONとagent indexを手で突き合わせ、reconcileはPhase 2以降で実装する
- 要件不足: work agentに推測させずOrchestratorへ戻す

## 8. 完了・修正

Work agentがPRを作成した後、通常のcode cross-reviewを行う。

1. test/evidenceを確認
2. cross-review結果を確認
3. 人が実行確認・受入確認を行う
4. 問題なければ人がmerge
5. merge後にtaskをdoneへ更新

受入確認に失敗した場合は、元taskを上書きしない。

```text
task-001 revision=0
  → verification failed
  → task-001-r1をOrchestratorが作成
  → failure_reason / previous_evidenceを記録
  → 人が再assign
```

要件やacceptance criteriaが変わる場合は、work agentが勝手に修正せず、Orchestratorへ戻す。

## 9. Phase 1の完了条件

- 人が要件を入力できる
- interviewの質問・回答・未解決事項が成果物になる
- plan draftを人が確認できる
- plan/task docsをcross-reviewへ出せる
- 人がplan/task draftを確認し、assign前の承認判断ができる
- Phase 2以降のassign/current task/revisionへの引き継ぎ条件が記録される
- 既存のwork session、cross-review、checkpoint/resumeを壊さない


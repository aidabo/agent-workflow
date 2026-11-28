# agent-workflow

`11-agent-workflow`は、Claude・Codex・DeepSeekなどのagentをtmuxで動かし、task、test、PR、cross-review、heartbeatを一つのmonitorで確認するためのstandalone runtimeです。

旧`10-agent-tools`の後継ですが、移行中は両方を混ぜずに使い分けます。

## 1. repositoryの役割

| repository | 役割 |
|---|---|
| `10-agent-tools` | 旧runtime。移行中のrollback用に保持 |
| `11-agent-workflow` | 新runtime。task状態、monitor、cross-review、storage分離 |
| application repository | 製品コード、docs、実装PR、test |

新runtimeへの切り替え後も、旧runtimeのcron、report、state、inbox、worktreeは削除しません。

## 2. 最短セットアップ

workspaceを次のようにします。

```text
~/work/legacy/
├── agents.yaml
├── 01-ghost-front/
├── 11-agent-workflow/
└── ...
```

### agents.yamlの探索順

agent起動時は次の順で設定を探します。

1. `AGENTS_YAML`で明示したファイル
2. workspace直下の`agents.yaml`
3. `11-agent-workflow/agent-notify/agents.yaml`のfallback

projectごとにagent構成を管理する場合は、workspace直下の`agents.yaml`を推奨します。
10-agent-toolsと11-agent-workflowを同時に使う期間は、`session:`を明示してtmux sessionを分けます。

### cross-review設定

```bash
cd ~/work/legacy/11-agent-workflow
cp cross-review/config.local.example.sh cross-review/config.local.sh
```

`REPOS`は次の形式です。

```bash
REPOS=(
  "jibunsee-react|aidabo/jibunsee-react|$HOME/work/legacy/01-ghost-front|$HOME/work/legacy/01-ghost-front-agent-workflow-review"
  "agent-workflow|aidabo/agent-workflow|$HOME/work/legacy/11-agent-workflow|$HOME/work/legacy/11-agent-workflow-agent-workflow-review"
)
```

4列目は、10-agent-toolsと共有しないreview専用worktreeです。

### 設定確認

```bash
bin/agent-workflow check
```

`gh`認証、`python3`、`flock`、`tmux`、`REPOS`を確認します。

## 3. 普段使うcommand

通常利用はこの2つです。

```bash
bin/agent-workflow agent
bin/agent-workflow monitor
```

| command | 意味 |
|---|---|
| `agent` | 設定を確認してtmuxのagent paneを起動 |
| `monitor` | agent、task、PR、review状態を表示 |
| `checkpoint` | taskの再開情報を保存 |
| `checkpoint prune` | 古い完了taskのcheckpointをdry-run確認・整理 |
| `resume` | 未完了taskとresume promptを表示 |

application repositoryのpackage.jsonから呼ぶ場合は、次のようにします。

```json
{
  "scripts": {
    "agent": "bash $HOME/work/legacy/11-agent-workflow/bin/agent-workflow agent",
    "monitor": "bash $HOME/work/legacy/11-agent-workflow/bin/agent-workflow monitor"
  }
}
```

## 4. taskの進め方

実装agentのpaneへ要件を自然文で伝えます。

```text
この目的をplanに整理し、独立taskは分割して並列に進めてください。
完了条件、test、PR、review条件もtaskごとに決めてください。
```

現在はagentがplanとtask分割を行い、`agent-status`でdraftを保存します。orchestratorは要件確認前にworkspaceのソース構成・`docs/**`・既存workflow stateを読み取れます。要件回答をartifact化するprovider非依存の`requirement-interview`と、fixture planner、plan review gateも利用できます。plan承認後の明示assignとreconcileも利用できます。実provider adapterと対話型provider sessionは次Phaseです（[AI Orchestrator Phase plan](docs/orchestrator-ai-phase-plan.md)）。

provider adapterはworkspace内の設定で実行します。adapterはstdinのJSONを受け、同じoperationを持つ`schema_version: 1`のJSONをstdoutへ返します。provider固有の認証情報やprompt履歴はworkflow stateへ保存しません。configのcommandはworkspaceの信頼境界内で、現在の環境変数を引き継いで実行するため、信頼できるworkspaceの設定だけを使用します。

task状態の例：

```bash
bin/agent-workflow status begin \
  --workspace "$PWD" --agent codex --task-id task-001 \
  --repo aidabo/jibunsee-react --repo-dir "$PWD" --phase coding \
  --goal "機能を実装する"

bin/agent-workflow status heartbeat \
  --workspace "$PWD" --agent codex --task-id task-001
```

taskの流れは次のとおりです。

```text
planned → ready → in_progress → ready_for_review → done
                                      ↓
                                needs_human
```

## 5. PRとcross-review

通常の流れは次のとおりです。

```text
要件 → plan/docs → task分割 → coding → test → PR → cross-review → 人がmerge
```

Phase 1/2のplan・task操作例：

```bash
bin/agent-workflow status plan-create --workspace "$PWD" --plan-id plan-001 \
  --title "短い計画名" --requirement "達成したいこと"
bin/agent-workflow status requirement-create --workspace "$PWD" --requirement-id req-001 \
  --background "背景" --problem "困りごと" --desired-outcome "期待結果" \
  --acceptance-criteria "確認できる完了条件"
bin/agent-workflow status plan-create --workspace "$PWD" --plan-id plan-002 \
  --title "artifactからの計画" --requirement-id req-001
# open_questionsが残るrequirementはneeds_clarificationのためplan-createできない
bin/agent-workflow status task-create --workspace "$PWD" --task-id task-001 \
  --plan-id plan-001 --summary "作業概要" --goal "完了条件"
bin/agent-workflow status plan-approve --workspace "$PWD" --plan-id plan-001
bin/agent-workflow status assign --workspace "$PWD" --task-id task-001 --agent codex
bin/agent-workflow status reconcile --workspace "$PWD"
```

AI orchestratorのfixture運用例：

```bash
# 要件確認の前に、対象workspaceのsource/docs/stateを確認する（読み取り専用）
bin/agent-workflow status workspace-inspect --workspace "$PWD" --docs-dir docs
# provider wrapperへpreflight付きの要件入力を渡す（入力/configはworkspace相対）
bin/agent-workflow orchestrator run interview --workspace "$PWD" \
  --provider claude --config providers.json --input answers.json \
  --output clarified.json
# orchestrator sessionから回答fixtureをartifactへ変換する場合
# answers.jsonはbackground/problem/desired_outcome、acceptance_criteria、risk_level等を含む
bin/agent-workflow status requirement-interview --workspace "$PWD" \
  --requirement-id req-001 --input clarified.json --interview-mode targeted --round 1
bin/agent-workflow status planner-fixture --workspace "$PWD" \
  --requirement-id req-001 --plan-id plan-001 --input planner.json
bin/agent-workflow status plan-review --workspace "$PWD" --plan-id plan-001 \
  --review-status changes_requested --critic-finding "scopeを分割する"
# findingsを解消した後、明示的にクリアして承認へ進める
bin/agent-workflow status plan-review --workspace "$PWD" --plan-id plan-001 \
  --review-status approved --clear-findings
bin/agent-workflow status plan-approve --workspace "$PWD" --plan-id plan-001
```

このfixtureはprovider非依存のdraft生成で、LLM呼び出し・自動assign・pane入力は行いません。`planner.json`はworkspace相対で、空でない`tasks`配列（`task_id`/`summary`/`goal`）が必要です。

pipeline管理taskの`assign`は承認済みplanの未着手taskだけを割り当てます。legacy taskは既存互換のため
plan承認なしでもassignできます。作業開始前の取り消しは`unassign --task-id task-001`、done/stale taskの
再割り当ては拒否されます。

手動で1件のレビューを開始する場合：

```bash
bin/agent-workflow review jibunsee-react 123
```

NEEDS YOUやレビュー上限後に、人が続行を決めた場合：

```bash
bin/agent-workflow review jibunsee-react 123 --force
```

agent paneへは次のように自然文で指示できます。

```text
NEEDS YOUなので、PR #123を再確認してください。指摘があれば修正し、test後にpushして再レビューしてください。
```

`--force`はレビュー上限を解除するだけで、自動mergeは実行しません。mergeは人が判断します。

## 6. cron

cronは必要な場合だけ設定します。

| 種類 | 役割 |
|---|---|
| cross-review watch | 未レビューPRを定期的に探してreviewerを起動 |
| merge observer | `automation:auto-merge`付きPRをdry-run観測 |

まとめて確認・登録・解除できます。

```bash
bin/agent-workflow cron check
bin/agent-workflow cron install
bin/agent-workflow cron uninstall
```

`agent`や`monitor`を起動するだけならcronは不要です。`cron install`は11側のmarker付き行と11側observerだけを管理し、10-agent-toolsのcron行は変更しません。

## 7. 保存場所と旧runtimeからの切り替え

| データ | 10-agent-tools | 11-agent-workflow |
|---|---|---|
| review report | `.agent-tools/reviews/` | `.agent-workflow/reviews/` |
| review state | `~/.cache/cross-review/state/` | `~/.cache/agent-workflow/cross-review/state/` |
| inbox | `10-agent-tools/cross-review/inbox/` | `11-agent-workflow/cross-review/inbox/` |
| review worktree | `<project>-review` | `<project>-agent-workflow-review` |
| agent session | 旧設定 | `<workspace>-agent-workflow-agents` |
| monitor session | `agents-monitor` | `agent-workflow-monitor` |

切り替えは、canary repositoryで新領域を確認してから全repositoryへ広げます。両runtimeで同じPRを同時にreviewしないでください。

問題があれば、11側のcronを解除して10側へ戻せます。旧report、state、inbox、worktreeは削除しません。

詳細：[docs/storage-separation.md](docs/storage-separation.md)

## 8. 詳細資料

- [docs/usage.md](docs/usage.md)：command・設定・cronの詳細
- [docs/workflow.md](docs/workflow.md)：task state machine
- [docs/architecture.md](docs/architecture.md)：構成とrepository境界
- [docs/context-and-references.md](docs/context-and-references.md)：screenshot/reference設定
- [docs/monitor.md](docs/monitor.md)：monitor設計
- [docs/auto-merge-gate.md](docs/auto-merge-gate.md)：auto-merge dry-run
- [docs/storage-separation.md](docs/storage-separation.md)：旧runtimeとの分離・rollback
- [docs/phase5-resume.md](docs/phase5-resume.md)：再起動後のcheckpoint/resume設計

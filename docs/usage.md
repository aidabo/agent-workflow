# プロジェクトからの利用方法

`11-agent-workflow`を各アプリケーションrepositoryから呼び出す入口は、
`bin/agent-workflow`である。実体を各アプリrepositoryへcopyせず、絶対パスで呼び出す。

## 初回設定

```bash
WORKFLOW_HOME=/path/to/11-agent-workflow
WORKFLOW="$WORKFLOW_HOME/bin/agent-workflow"
```

```bash
cd "$WORKFLOW_HOME"
cp cross-review/config.local.example.sh cross-review/config.local.sh
```

`cross-review/config.local.sh`の`REPOS`に監視するrepositoryを追加する。

```bash
REPOS=(
  "jibunsee-react|aidabo/jibunsee-react|$HOME/work/legacy/01-ghost-front|$HOME/work/legacy/01-ghost-front-agent-workflow-review"
  "agent-workflow|aidabo/agent-workflow|$HOME/work/legacy/11-agent-workflow|$HOME/work/legacy/11-agent-workflow-agent-workflow-review"
)
```

各要素は、表示名、GitHub repository、作者の作業tree、review用worktreeの順番である。

```bash
"$WORKFLOW" check
```

`gh auth status`、`python3`、`flock`、`tmux`、`REPOS`が確認される。

## プロジェクトからの起動

アプリrepositoryのルートから呼び出す。

```bash
"$WORKFLOW" agent
"$WORKFLOW" monitor
"$WORKFLOW" status begin \
  --workspace "$PWD" --agent codex --task-id task-001 \
  --repo aidabo/jibunsee-react --repo-dir "$PWD" --phase coding \
  --goal "実装する"
"$WORKFLOW" review jibunsee-react 123
```

利用者が通常使う入口は`agent`と`monitor`の2つである。`agent`は設定確認後にtmux agentを起動し、`monitor`は監視画面を開く。`status`、`review`、`gate`、`observe`は個別操作やcron用の上級者向け入口として残している。

## command一覧

| command | 用途 | 使う場面 |
|---|---|---|
| `check` | `gh`、`python3`、`flock`、`REPOS`設定を検査する | 初回設定、cron切り分け |
| `agent` | `check`後にtmuxのagent paneを起動する | 毎日の作業開始 |
| `monitor` | agent/task/cross-reviewの監視画面を開く | 作業状況の確認 |
| `status` | taskのbegin、heartbeat、test、context、endを操作する | agentがtask状態を更新するとき |
| `checkpoint` | taskの再開情報を保存する | 作業中の重要イベント、停止前 |
| `checkpoint prune` | 古い完了taskのcheckpoint候補を表示・削除する | サイズ整理（既定dry-run） |
| `resume` | 未完了taskとresume promptをJSONで表示する | tmux/マシン再起動後 |
| `review` | standalone cross-review wrapperを呼び出す | 1件のPRを手動でレビューするとき |
| `gate` | 1件のPRをdry-run判定する | 1件の`ELIGIBLE`/`BLOCKED`確認 |
| `observe` | `automation:auto-merge`ラベル付きopen PRを一括観測する | cron、夜間のdry-run観測 |
| `cron check` | cross-reviewとobserverのcron登録状態を確認する | 初回設定の確認 |
| `cron install` | cross-review watchとobserverをcrontabへ登録する | 自動レビュー・夜間観測を有効化 |
| `cron uninstall` | 上記cron登録を解除する | 自動実行を止める |

`agent`と`monitor`は利用者向けの主要commandである。`check`は破壊的操作をせず、設定不備ならexit `78`で終了する。`gate`はexit `0`がELIGIBLE、exit `2`が通常のBLOCKED、exit `78`が設定不備、その他がgate errorである。`observe`は通常のBLOCKEDでは成功終了し、GitHub一覧取得やgate自体のエラーがある場合だけ非0で終了する。`gate`と`observe`はtmuxを必要としないため、cron環境でも実行できる。

詳細commandの例：

```bash
"$WORKFLOW" check
"$WORKFLOW" status heartbeat --workspace "$PWD" --agent codex --task-id task-001
"$WORKFLOW" review agent-workflow 123
"$WORKFLOW" gate --repo=jibunsee-react --pr=123
"$WORKFLOW" observe
"$WORKFLOW" cron check
"$WORKFLOW" cron install
```

## auto-merge dry-run

対象PRに明示的にラベルを付ける。

```bash
gh pr edit 123 -R aidabo/jibunsee-react --add-label automation:auto-merge
```

1件だけ確認する場合：

```bash
"$WORKFLOW" gate --repo=jibunsee-react --pr=123
```

全repositoryの対象PRを観測する場合：

```bash
"$WORKFLOW" observe
tail -n 20 "$HOME/.cache/agent-workflow/auto-merge-observe.jsonl"
```

`observe`と`gate`は判定・記録だけを行い、`gh pr merge`は呼ばない。

## 任意のログ・lock設定

既定値を使う場合は設定不要である。保存先を変える場合だけ指定する。

```bash
export AUTO_MERGE_OBSERVE_LOG="$HOME/.cache/agent-workflow/observe.jsonl"
export AUTO_MERGE_OBSERVE_LOCK="$HOME/.cache/agent-workflow/observe.lock"
```

## cronの役割と初回設定

cronは2種類ある。

| 種類 | command | 目的 | 必須条件 |
|---|---|---|---|
| cross-review watch | `cross-review/watch.sh` | 未レビューPRを探し、reviewerを起動する | 深夜もPRレビューを自動継続する場合は必要 |
| merge observer | `agent-workflow observe` | opt-in PRのdry-run判定を記録する | 夜間の判定ログを取る場合だけ必要 |

`agent`、`monitor`、手動の`review`/`gate`だけを使う場合、最初からcronを設定する必要はない。

まず設定を確認する。

```bash
"$WORKFLOW_HOME/cross-review/install.sh" --check
```

cross-reviewの自動レビューを有効にする場合は、configを編集してから次を一度実行する。

```bash
"$WORKFLOW_HOME/cross-review/install.sh"
```

このコマンドはcross-reviewのwatchを毎分登録し、既存crontabのバックアップを`$HOME/.cache/agent-workflow/cross-review/`へ保存する。10-agent-toolsのcron行は変更しない。解除は次で行う。

```bash
"$WORKFLOW_HOME/cross-review/install.sh" --uninstall
```

cross-review watchとmerge observerをまとめて管理する場合は、次のcommandを使う。

```bash
"$WORKFLOW" cron check
"$WORKFLOW" cron install
"$WORKFLOW" cron uninstall
```

`cron install`を使わず、merge observerだけを手動登録したい場合は次の行を使う。通常は`cron install`がwatchとobserverの両方を登録するため、この行を追加しない。

```cron
*/5 * * * * /path/to/11-agent-workflow/bin/agent-workflow observe >> $HOME/.cache/agent-workflow/observe.cron.log 2>&1
```

cron環境では`gh`、`python3`、`flock`、reviewer commandがPATHにあることを確認する。observerは重複起動をlockで防ぎ、一覧取得・gate異常時は非0終了する。どちらのcronもmerge操作は実行しない。

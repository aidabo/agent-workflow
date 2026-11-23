# プロジェクトからの利用方法

`11-agent-workflow`を各アプリケーションrepositoryから呼び出す入口は、
`bin/agent-workflow`である。実体を各アプリrepositoryへcopyせず、絶対パスで呼び出す。

## 初回設定

```bash
cd /home/aidabo/work/legacy/11-agent-workflow
cp cross-review/config.local.example.sh cross-review/config.local.sh
```

`cross-review/config.local.sh`の`REPOS`に監視するrepositoryを追加する。

```bash
REPOS=(
  "jibunsee-react|aidabo/jibunsee-react|$HOME/work/legacy/01-ghost-front|$HOME/work/legacy/01-ghost-front-review"
  "agent-workflow|aidabo/agent-workflow|$HOME/work/legacy/11-agent-workflow|$HOME/work/legacy/11-agent-workflow-review"
)
```

各要素は、表示名、GitHub repository、作者の作業tree、review用worktreeの順番である。

```bash
/home/aidabo/work/legacy/11-agent-workflow/bin/agent-workflow check
```

`gh auth status`、`python3`、`flock`、`REPOS`が確認される。

## プロジェクトからの起動

アプリrepositoryのルートから呼び出す。

```bash
WORKFLOW=/home/aidabo/work/legacy/11-agent-workflow/bin/agent-workflow
"$WORKFLOW" agent
"$WORKFLOW" monitor
"$WORKFLOW" status begin \
  --workspace "$PWD" --agent codex --task-id task-001 \
  --repo aidabo/jibunsee-react --repo-dir "$PWD" --phase coding \
  --goal "実装する"
"$WORKFLOW" review
```

利用者が通常使う入口は`agent`と`monitor`の2つである。`agent`は設定確認後にtmux agentを起動し、`monitor`は監視画面を開く。`status`、`review`、`gate`、`observe`は個別操作やcron用の上級者向け入口として残している。

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

## cron

```cron
*/5 * * * * /home/aidabo/work/legacy/11-agent-workflow/bin/agent-workflow observe >> $HOME/.cache/agent-workflow/observe.cron.log 2>&1
```

cron環境では`gh`、`python3`、`flock`がPATHにあることを確認する。observerは重複起動をlockで防ぎ、一覧取得・gate異常時は非0終了する。

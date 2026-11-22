# Migration from 10-agent-tools

`10-agent-tools`は現在安定している移行元であり、`11-agent-workflow`完成後は旧repositoryを
運用から外す。移行は一度に切り替えず、behaviorを比較しながら行う。

## copyするもの

tracked sourceだけをcopyする。

```text
10-agent-tools/agent-notify/
  start-agents.sh
  monitor.sh
  status.py
  monitor-hook-log.py
  hooks/native-hook.mjs
  configure-stop-notify.sh
  sendtmux.sh
  stx
  agents.yaml.template（workspace固有のpath/agent設定はcopyせず、空templateとして再作成）

10-agent-tools/cross-review/
  PROTOCOL.md
  cross-review.sh
  watch.sh / status.sh / live.sh
  notify.sh / secret_scan.py
  install.sh / README.md
```

copy後にagent-workflowのtask/status/context APIを追加し、旧ツールと同じ入力で同じ表示・
review判定になることを確認する。

### copy先の対応表

| 移行元 | 移行先 |
|---|---|
| `agent-notify/start-agents.sh` | `bin/agent-start` / `src/agent_workflow/tmux_adapter.py` |
| `agent-notify/monitor.sh` / `status.py` | `bin/agent-monitor` / `src/agent_workflow/monitor_adapter.py` |
| `agent-notify/hooks/` / `configure-stop-notify.sh` | `src/agent_workflow/notify/` |
| `cross-review/` | `src/agent_workflow/cross_review/` と `bin/cross-review` |
| workspace `agents.yaml` | `${WORKSPACE}/.agent-workflow/agents.json`（環境ごとに作成） |

## copyしないもの

- `.git/`
- `.omc/`、`.omx/`、`.remember/`
- `__pycache__/`
- `config.local.sh`、webhook、AWS credential、secret env
- `inbox/`、review reports、cache、runtime state
- `~/.notify`、`~/.clawhip`などユーザー環境の実体

copy先repositoryの`.gitignore`へ、次も先に追加する。

```text
.agent-workflow/
.cross-review/
inbox/
config.local.sh
*.env
__pycache__/
```

local configは新repositoryの形式で作り直し、secretは既存のsecret managerまたはユーザー環境
から注入する。

## 移行段階

### 現在の進捗

移行段階1のtracked runtime copyは完了している。`agent-notify/`と`cross-review/`のsource-only/
target-only差分をtracked file listで比較し、差分が無いことを確認した。次はbehavior lockである。

### 1. copyとbehavior lock

- launcher、monitor、cross-reviewをcopy
- 既存`10-agent-tools`と同じtmux pane、review status、inbox通知を比較
- 既存`Makefile`の`make test`を拡張し、shell/node/python syntax checkも追加
- `git -C ../10-agent-tools ls-files`とcopy manifestを比較するinventory checkを追加
- 同じfixture PR/inboxで、旧status/monitorと新status/monitorのsnapshotを比較するbehavior lockを実行

### 2. task/status統合

- Phase 1のtask JSON・agent index・context resolverをcopyしたmonitorへ接続
- 既存cross-review表示を残し、agent × task行を追加
- 複数taskを同時に更新し、一方のreviewで他taskが止まらないことを確認

### 3. workspace切替

- package.jsonの`agents`/`monitor` commandを新repositoryへ向ける
- cross-reviewのrepo entryを新repositoryのpathへ変更
- tmuxを再起動し、全paneのidentityとmonitor表示を確認
- 旧repositoryは停止したままrollback用にread-only保持

### 4. 旧repositoryのarchive

- 1週間以上、new toolだけでdocs PR/code PR/review/inboxを運用
- review漏れ、通知漏れ、status欠落がないことを確認
- `10-agent-tools`のcronとworkspace参照を停止
- READMEに移行先を記録してread-only archiveにする

## rollback

問題があればworkspace設定を旧`10-agent-tools`へ戻し、旧cronとmonitorを再起動する。
runtime stateをcopyして戻すのではなく、GitHub PRとinboxの未処理状態を確認してから再開する。

## 完了条件

- [ ] 新repositoryだけでtmux起動できる
- [ ] cross-reviewが作者除外・secret scan・inbox・上限を維持する
- [ ] monitorに既存review状態とagent × task状態が表示される
- [ ] screenshot/reference設定が毎回のpath説明なしで解決される
- [ ] 複数taskと独立reviewが相互に停止しない
- [ ] 旧repositoryへ戻すrollback手順が実行可能

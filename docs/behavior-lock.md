# Behavior lock

移行段階1では、10-agent-toolsを停止・変更せず、同じ入力を旧runtimeとstandalone runtimeへ
与えて、表示とreview状態が一致することを確認する。

## 1. copy manifest

workspaceで次を実行する。

```bash
cd ~/work/legacy/11-agent-workflow
AGENT_TOOLS_SOURCE_ROOT=../10-agent-tools \
AGENT_TOOLS_SOURCE_REF=origin/main \
make migration-check
```

前提として、`../10-agent-tools`がclone済みで、比較対象の`origin/main`をfetchしていることを確認する。
成功時は比較したsource commit SHAが表示され、失敗時はsource-only/target-onlyのpath差分を読む。

trackedな`agent-notify/`と`cross-review/`のsource/target path一覧が一致する。local config、
inbox、report、runtime state、secretは比較対象にしない。

## 2. 静的check

```bash
make check
```

確認対象:

- Phase 1 unittest
- copied cross-review unittest
- shell syntax
- native hook Node syntax
- Python compile

## 3. old/new snapshot

同じfixture workspaceと同じGitHub read-only状態を使う。旧toolを先に、standaloneを後に実行し、
次の出力を保存する。

```bash
LOCK_WORKSPACE="$(mktemp -d)"
mkdir -p "$LOCK_WORKSPACE"/{old,new}

# 旧/新のcross-reviewが同じfixtureを読むよう、両方に同じconfigとinboxを指定する。
# fixture configには同じREPOSとINBOX_DIR="$LOCK_WORKSPACE/inbox"を設定する。
mkdir -p "$LOCK_WORKSPACE/inbox"
export CROSS_REVIEW_CONFIG="$LOCK_WORKSPACE/cross-review.fixture.sh"

# 旧runtime
AGENT_TOOLS_HOME=../10-agent-tools \
  python3 ../10-agent-tools/agent-notify/status.py --once > "$LOCK_WORKSPACE/old/status.txt"
bash ../10-agent-tools/cross-review/status.sh > "$LOCK_WORKSPACE/old/review.txt"

# standalone runtime
python3 agent-notify/status.py --once > "$LOCK_WORKSPACE/new/status.txt"
bash cross-review/status.sh > "$LOCK_WORKSPACE/new/review.txt"
```

環境依存の時刻、API取得順、host pathを正規化して比較する。PRの判定名、author/reviewer、
APPROVED/CHANGES REQUESTED/NEEDS YOU、pane state分類が一致することを確認する。

standalone側だけtask sectionが追加されるため、旧/新snapshotではcross-review sectionとpane
state sectionを比較し、standaloneのtask sectionは新機能として別に確認する。

## 4. 並列taskの確認

```bash
: "${LOCK_WORKSPACE:?セクション3と同じshellで続けて実行する}"
bin/agent-status begin --workspace "$LOCK_WORKSPACE" --agent codex --task-id lock-a --phase coding
bin/agent-status begin --workspace "$LOCK_WORKSPACE" --agent codex --task-id lock-b --phase test
bin/agent-status end --workspace "$LOCK_WORKSPACE" --agent codex --task-id lock-a
```

`lock-b`がactive taskとして残り、current taskが`lock-b`になることを確認する。lock-aのreview
状態やlock-bのtest状態は変更されない。

```bash
bin/agent-status end --workspace "$LOCK_WORKSPACE" --agent codex --task-id lock-b
rm -rf "$LOCK_WORKSPACE"
```

## 5. 切替前の停止条件

- [ ] copy manifest一致
- [ ] old/new snapshot差分を確認済み
- [ ] cross-reviewのauthor除外・secret scan・inboxが一致
- [ ] 並列taskの独立性を確認
- [ ] 旧runtimeのinstall/cron切替はまだ実行していない

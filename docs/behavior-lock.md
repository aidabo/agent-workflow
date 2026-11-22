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

trackedな`agent-notify/`と`cross-review/`のsource/target一覧が一致する。local config、
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
mkdir -p .behavior-lock/{old,new}

# 旧runtime
AGENT_TOOLS_HOME=../10-agent-tools \
  python3 ../10-agent-tools/agent-notify/status.py --once > .behavior-lock/old/status.txt
bash ../10-agent-tools/cross-review/status.sh > .behavior-lock/old/review.txt

# standalone runtime
python3 agent-notify/status.py --once > .behavior-lock/new/status.txt
bash cross-review/status.sh > .behavior-lock/new/review.txt
```

環境依存の時刻、API取得順、host pathを正規化して比較する。PRの判定名、author/reviewer、
APPROVED/CHANGES REQUESTED/NEEDS YOU、pane state分類が一致することを確認する。

## 4. 並列taskの確認

```bash
bin/agent-status begin --workspace "$PWD" --agent codex --task-id lock-a --phase coding
bin/agent-status begin --workspace "$PWD" --agent codex --task-id lock-b --phase test
bin/agent-status end --workspace "$PWD" --agent codex --task-id lock-a
```

`lock-b`がactive taskとして残り、current taskが`lock-b`になることを確認する。lock-aのreview
状態やlock-bのtest状態は変更されない。

## 5. 切替前の停止条件

- [ ] copy manifest一致
- [ ] old/new snapshot差分を確認済み
- [ ] cross-reviewのauthor除外・secret scan・inboxが一致
- [ ] 並列taskの独立性を確認
- [ ] 旧runtimeのinstall/cron切替はまだ実行していない

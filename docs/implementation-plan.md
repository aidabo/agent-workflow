# Implementation plan

## 技術選択

既存の10-agent-toolsと同じtmuxを使うが、実装はshellだけにしない。

| 部分 | 実装 |
|---|---|
| tmux起動・外部コマンド | shell adapter |
| status CLI | Python 3標準ライブラリ |
| status保存 | `${WORKSPACE}/.agent-workflow/state`のJSON、temp file + renameのatomic write |
| monitor | `10-agent-tools/agent-notify/status.py`の既存表示をadapter経由で拡張 |
| cross-review | 10-agent-tools adapter、再実装しない |
| config | YAMLまたはJSON。初期は依存追加を避ける |

## 段階

### 段階1: status/context

- `agent-status begin/update/heartbeat/test/end`
- state/task JSON schema
- `agent-context`のscreenshot/reference解決（workspace外secret pathはdeny）
- stale判定

### 段階2: monitor

- existing cross-review statusを維持
- agent/task/phase/PR/test/heartbeat列を追加
- API遅延時のbackground fetch
- reference folder warning

### 段階3: workflow gate

- docs PRが人mergeされるまでimplementation taskをreadyにしない
- testなしのPRをreview-readyにしない
- review上限をneeds_humanにする
- docs PRとcode PRをparent/childで紐付ける

自動merge・自動deploy・自動task割当はこのrepositoryの初期範囲に含めない。

## test plan

- status schema、enum、atomic write
- heartbeat 599/600秒境界
- `stale_after_seconds >= heartbeat_interval_seconds * 10`
- secret-like key/valueの拒否・redact
- tmuxなしでもcross-review表示が落ちない
- GitHub API timeoutでもagent状態が更新される
- reference/screenshot path不存在のwarning
- docs PR → task → code PRのparent関係

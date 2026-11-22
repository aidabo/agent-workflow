# Implementation plan

## 技術選択

既存の10-agent-toolsと同じtmuxを使うが、実装はshellだけにしない。

| 部分 | 実装 |
|---|---|
| tmux起動・外部コマンド | shell adapter |
| status CLI | Python 3標準ライブラリ |
| status保存 | `${WORKSPACE}/.agent-workflow/state/tasks/<task_id>.json` / `agents/<agent>.json`。directory `0700`、file `0600`、temp file + renameのatomic write |
| monitor | `10-agent-tools/agent-notify/status.py`の既存表示をadapter経由で拡張 |
| cross-review | 10-agent-tools adapter、再実装しない |
| config | JSON + Python標準ライブラリ。初期にYAML依存を追加しない |

## 段階

### 段階1: status/context

- `agent-status begin/update/heartbeat/test/end`
- state/task JSON schema
- `agent-context`のscreenshot/reference解決（workspace外secret pathはdeny）
- `sweep`によるstale判定とheartbeat設定検証

### 段階2: monitor

- existing cross-review statusを維持
- agent/task/phase/PR/test/heartbeat列を追加
- API遅延時のbackground fetch
- reference pathのdeny-by-defaultと、明示許可した非secret workspace外pathだけwarning

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
- reference/screenshot path不存在・secret path・workspace外pathのdeny/warning境界
- docs PR → task → code PRのparent関係

代表的な組み合わせ例:

```text
phase=code_review / task_status=ready_for_review / state=waiting_user
phase=coding      / task_status=in_progress     / state=busy
phase=code_human_review / task_status=ready_for_review / state=waiting_user
```

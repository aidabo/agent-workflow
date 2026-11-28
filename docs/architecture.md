# Architecture

## 全体構成

### 運用全体

```mermaid
flowchart LR
  H[人: 要件・完了条件] --> P[plan / docs]
  P --> T[task JSON]
  T --> A[Claude / Codex / DeepSeek pane]
  A --> S[status / heartbeat / test]
  S --> C[checkpoint]
  A --> G[Git branch / PR]
  G --> R[cross-review]
  R -->|APPROVE| M[人がmerge]
  R -->|CHANGES_REQUESTED| A
  R -->|NEEDS YOU / max rounds| H
  C --> X[tmux・マシン再起動]
  X --> U[resume候補・prompt]
  U --> H
  S --> MON[monitor]
  R --> MON
  C --> MON
  MON --> H
```

taskの状態、reviewの状態、checkpointは別の情報として保存する。monitorはそれらを一つの画面へ集約するが、agent paneへ自動入力はしない。

### 移行中

```mermaid
flowchart TB
  subgraph APP["application repositories"]
    CODE["source / tests / docs"]
    PR["GitHub PR"]
  end
  subgraph AW["11-agent-workflow (standalone)"]
    TASK["task store\nJSON metadata"]
    CTX["context resolver\nrefs / screenshots"]
    HS["heartbeat/status\n11-agent-workflow state"]
    MON["monitor adapter\nagent + task + PR"]
  end
  subgraph TOOLS["10-agent-tools (migration source)"]
    TMUX["tmux launcher / panes"]
    CR["cross-review\nwatch / status / inbox"]
    LIVE["review live log"]
  end
  H["human"]

  H --> TASK
  TASK --> CTX
  CTX --> TMUX
  A["agent / status CLI"] --> HS
  HS --> MON
  CR --> MON
  LIVE --> MON
  CODE --> PR
  PR --> CR
  MON --> H
  H --> PR
```

### 移行後の目標

```mermaid
flowchart TB
  subgraph AW["11-agent-workflow (standalone)"]
    TMUX["tmux launcher / panes"]
    CR["local cross-review\nwatch / status / inbox"]
    LIVE["review live log"]
    TASK["task/status/context"]
    MON["monitor"]
    TMUX --> TASK --> MON
    CR --> MON
    LIVE --> MON
  end
  APP["application repositories\nsource / tests / docs / PR"] --> CR
  H["human"] --> MON
  H --> APP
```

移行後はTMUX/CR/LIVEも`11-agent-workflow`内のcopyが実行主体になり、`10-agent-tools`は
read-only archiveになる。

## 責務境界

### 11-agent-workflowが持つもの

- task ID、目的、完了条件、parent docs PR、code PR
- taskごとのphase/state/task_status/heartbeat
- agent indexの`active_task_ids`と`current_task_id`
- branch、commit、test結果の短い要約
- workspace/projectごとのscreenshot/reference設定
- stale・blocked・needs_humanの判定
- monitor用の集約表示

task JSONが状態の正であり、agent JSONはactive taskの索引である。agentがtaskを切り替えても、
他taskのJSONは上書きしない。

task JSONはtaskごとに分かれるため、複数taskのstatus更新は互いに独立する。monitorのGitHub/
cross-review取得はstatus書き込みと別adapter/cacheで実行し、外部API待ちがagent更新を止めない。

### 移行後にagent-workflowが持つもの

- tmux session/paneの起動
- paneへの通知
- cross-reviewのcron/watch
- reviewer選択、secret scan、inbox、PRコメント
- `PROTOCOL.md`のレビュー運用

移行中はcopy元との差分を小さく保ち、copy後にstandalone codeとして動かす。
`10-agent-tools`のruntime state、local config、secret、`.git`、cacheはcopyしない。

## データの流れ

```mermaid
sequenceDiagram
  participant A as agent
  participant S as status CLI
  participant FS as .agent-workflow state
  participant M as monitor
  participant X as local cross-review
  participant G as GitHub

  A->>S: begin/update/heartbeat/test
  S->>FS: atomic JSON write
  M->>FS: read task/agent metadata
  M->>X: read local review state
  X->>G: read PR/review status
  M-->>A: monitor displays context
  A->>G: docs/code PR
```

### 再起動後のデータフロー

```mermaid
sequenceDiagram
  participant T as task JSON
  participant C as checkpoint JSON
  participant R as resume
  participant H as 人
  participant A as agent pane

  A->>T: heartbeat / phase / test
  A->>C: 重要イベントでcheckpoint
  Note over C: size・mtimeをmonitorに表示
  A--xA: tmux/マシン停止
  H->>R: resume
  R->>T: 未完了・stale taskを読む
  R->>C: 最新checkpointを読む
  R-->>H: branch / PR / test / warning / prompt
  H->>A: 同じbranchで再開を指示
```

checkpointはheartbeatごとには保存しない。phase変更、test結果、review更新、PR操作、next action変更、明示checkpoint、graceful stopを保存契機とする。

### 保存領域の境界

```mermaid
flowchart TB
  subgraph OLD[10-agent-tools]
    OREPORT[.agent-tools/reviews]
    OSTATE[~/.cache/cross-review]
    OWT[project-review]
    OTMUX[旧tmux session]
  end
  subgraph NEW[11-agent-workflow]
    NREPORT[.agent-workflow/reviews]
    NSTATE[~/.cache/agent-workflow/cross-review]
    NCP[.agent-workflow/state/checkpoints]
    NWT[project-agent-workflow-review]
    NTMUX[agent-workflow sessions]
  end
  OLD -. rollback only .- OLD
  NEW -. active runtime .- NEW
```

GitHubのPR、branch、コメント、labelsは共有される。ローカル状態、review worktree、cron、tmux sessionは共有しない。

## 安全境界

- statusへAPI key、token、会話全文、secret envを保存しない
- monitorはagent paneへ自動入力しない
- merge、deploy、AWS writeは人だけが実行する
- screenshot/referenceはbasenameとmetadataを表示し、無断で外部送信しない
- workspace外のpath、secret directory、`.env`、credential directoryは既定で拒否する
- 明示的に許可された非secretのworkspace外referenceだけwarning付きで許可する

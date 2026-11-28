# Provider wrappers

`bin/agent-provider`は、既存のorchestrator runnerが渡すJSON requestをClaude/Codex/DeepSeekのCLIへ接続する標準wrapperです。

設定例（認証情報はconfigへ書かず、各CLIの認証または環境変数で管理する）:

```json
{
  "providers": {
    "claude": ["/path/to/11-agent-workflow/bin/agent-provider", "claude"],
    "codex": ["/path/to/11-agent-workflow/bin/agent-provider", "codex"],
    "deepseek": ["/path/to/11-agent-workflow/bin/agent-provider", "deepseek"]
  }
}
```

DeepSeekはCLI commandを固定せず、`AGENT_WORKFLOW_DEEPSEEK_COMMAND`に利用者のlauncherを設定する。launcherはstdinからpromptを受け、`--print -`を引数に付けた呼び出しでstdoutへJSONだけを返す必要がある。wrapperはrequestのpreflightとpayloadをstdinでpromptへ渡し、resultだけをstructured JSONとして返す。会話全文、認証情報、providerのstderrは保存・転送しない。

Claude wrapperは`--restricted`、`--strict-mcp-config`、`--setting-sources ""`で起動し、OAuth認証を維持しながらsettings/hooks/MCPの影響を抑える。Codexは`-s read-only`で起動する。どちらも非対話で、promptはargvではなくstdinへ渡す。providerが返すJSONは、runner側でschema・secretを再検証してから`--output`へ保存する。runnerはwrapperより5秒長いtimeoutを持ち、wrapperはprovider専用process groupを終了する。`--timeout`は6秒以上にする（例: 300秒ならwrapperは295秒）。DeepSeek launcherは可能なら`exec`で本体を置き換える。

現状のrunnerは通常のinterview/plan/critic/verifierを1回につき1 provider・1 outputで実行する。複数critic/verifierのfan-outは下記の`orchestrator fanout`で実装済みであり、provider名・operation・preflightの`git.head`を持つfindingsを集約する。providerのresult同士を直接上書きせず、相違は`needs_human`へ止める。

runtime fan-outはcritic/verifier専用で、次のように実行する。

```bash
bin/agent-workflow orchestrator fanout critic --workspace "$PWD" \
  --provider claude --provider codex --provider deepseek \
  --config providers.json --input plan.json
```

出力は`orchestrator-findings/critic-findings.json`に0600で保存される。各findingにはprovider、operation、preflightのgit HEAD、resultが含まれる。resultが一致しない場合はstatusが`needs_human`になり、自動approve/assignは行わない。

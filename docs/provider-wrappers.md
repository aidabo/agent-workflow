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

通常のinterview/planは一つのprimary providerで実行する。critic/verifierを複数providerで実行する場合は、各resultを個別に保存してからorchestratorがfindingsとして集約する。providerのresult同士を直接上書きせず、相違はhuman reviewへ回す。

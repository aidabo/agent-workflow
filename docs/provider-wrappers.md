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

DeepSeekはCLI commandを固定せず、`AGENT_WORKFLOW_DEEPSEEK_COMMAND`に利用者のlauncherを設定する。wrapperはrequestのpreflightとpayloadをpromptへ渡し、resultだけをstructured JSONとして返す。会話全文、認証情報、providerのstderrは保存・転送しない。

Claude/Codex wrapperはそれぞれ非対話・read-onlyモードで実行する。providerが返すJSONは、runner側でschema・secretを再検証してから`--output`へ保存する。

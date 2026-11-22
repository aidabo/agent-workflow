# Context and references

## workspace設定

workspace（例: `${WORKSPACE}`）はgit管理外で、repositoryごとの設定をまとめる。

```yaml
workspace: legacy
docs_root: ${WORKSPACE}/01-ghost-front/docs
default_screenshot_dirs:
  - ${WORKSPACE}/22-temp/images
default_reference_dirs:
  - ${WORKSPACE}/01-ghost-front/docs
  - ${WORKSPACE}/10-agent-tools

projects:
  01-ghost-front:
    repo: aidabo/jibunsee-react
    repo_dir: ${WORKSPACE}/01-ghost-front
    screenshot_dirs:
      - ${WORKSPACE}/22-temp/images
    reference_dirs:
      - ${WORKSPACE}/01-ghost-front/docs/ai
      - ${WORKSPACE}/01-ghost-front/docs/development
      - ${WORKSPACE}/01-ghost-front/tenants
```

## task固有設定

```yaml
task_id: stackpage-042
repo: aidabo/jibunsee-react
repo_dir: ${WORKSPACE}/01-ghost-front
screenshots:
  - ${WORKSPACE}/22-temp/images/Screenshot_11.png
  - ${WORKSPACE}/22-temp/images/Screenshot_12.png
reference_dirs:
  - ${WORKSPACE}/06-stackpage
  - ${WORKSPACE}/01-ghost-front/docs/development
```

## 解決ルール

```text
task references override same-kind project references; project references override workspace defaults;
different directories are merged and deduplicated by normalized path.
```

monitorに表示するのは次のmetadataだけにする。

- screenshot folder
- 最新画像のbasenameと更新時刻
- reference folder
- task固有の参照件数

画像ファイルを自動的にagentや外部サービスへ送らない。agentが必要な時に、既知のpathを
開いて確認する。不存在、読み取り不可、workspace外のpath、secret directory、`.env`、
credential directoryは既定で拒否する。明示的に許可された非secretのworkspace外referenceだけ
warning付きで許可する。

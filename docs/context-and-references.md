# Context and references

## workspace設定

workspace（例: `~/work/legacy`）はgit管理外で、repositoryごとの設定をまとめる。

```yaml
workspace: legacy
docs_root: /home/aidabo/work/legacy/01-ghost-front/docs
default_screenshot_dirs:
  - /home/aidabo/work/legacy/22-temp/images
default_reference_dirs:
  - /home/aidabo/work/legacy/01-ghost-front/docs
  - /home/aidabo/work/legacy/10-agent-tools

projects:
  01-ghost-front:
    repo: aidabo/jibunsee-react
    repo_dir: /home/aidabo/work/legacy/01-ghost-front
    screenshot_dirs:
      - /home/aidabo/work/legacy/22-temp/images
    reference_dirs:
      - /home/aidabo/work/legacy/01-ghost-front/docs/ai
      - /home/aidabo/work/legacy/01-ghost-front/docs/development
      - /home/aidabo/work/legacy/01-ghost-front/tenants
```

## task固有設定

```yaml
task_id: stackpage-042
repo: aidabo/jibunsee-react
repo_dir: /home/aidabo/work/legacy/01-ghost-front
screenshots:
  - /home/aidabo/work/legacy/22-temp/images/Screenshot_11.png
  - /home/aidabo/work/legacy/22-temp/images/Screenshot_12.png
reference_dirs:
  - /home/aidabo/work/legacy/06-stackpage
  - /home/aidabo/work/legacy/01-ghost-front/docs/development
```

## 解決ルール

```text
task references > project references > workspace defaults
```

monitorに表示するのは次のmetadataだけにする。

- screenshot folder
- 最新画像のbasenameと更新時刻
- reference folder
- task固有の参照件数

画像ファイルを自動的にagentや外部サービスへ送らない。agentが必要な時に、既知のpathを
開いて確認する。不存在、読み取り不可、workspace外の危険なpathはwarningにする。

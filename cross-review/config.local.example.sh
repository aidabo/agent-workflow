# cross-review のマシン・プロジェクト固有の設定。config.local.sh に写して書き換える
# （config.sh の後に source される。config.local.sh は git に入れない）。

# レビュー結果の置き場。既定はリポジトリのワークスペース（agents.yaml がある上位フォルダ）の .agent-workflow/reviews/。
# 1 か所に固定したいときだけ書く。
# REPORT_DIR="$HOME/work/reviews/cross"

# 旧10-agent-toolsの完了履歴をMERGED/CLOSED表示にだけ使う読み取り専用fallback。
# 未指定なら、各REPOSのworkspace（agents.yamlと.agent-tools/reviewsがある場所）を個別に自動検出する。
# 移行完了後に旧履歴を表示しない場合は空にする。
# CROSS_REVIEW_LEGACY_STATE_DIR="$HOME/.cache/cross-review/state"
# CROSS_REVIEW_LEGACY_REPORT_DIR="$HOME/work/legacy/.agent-tools/reviews"

# 対象リポジトリ: 名前|GitHub repo|作者の作業ツリー|レビュー用 worktree（作業ツリーの隣に作られる）
# ワークスペース（~/work/legacy のように複数リポジトリをまとめたフォルダ）が複数あっても、ここ 1 か所に並べる。
REPOS=(
  "my-backend|me/my-backend|$HOME/work/myws/backend|$HOME/work/myws/backend-agent-workflow-review"
  "my-frontend|me/my-frontend|$HOME/work/myws/frontend|$HOME/work/myws/frontend-agent-workflow-review"
)

# スクリプトが走らせるテスト（1 行 1 コマンド、worktree のルートで実行）
test_cmds_for() {
  case "$1" in
    my-backend)
      echo "npm run typecheck"
      ;;
    my-frontend)
      echo "npm run typecheck"
      ;;
  esac
}

# cron で node / gh / deepseek が見つからないとき（PATH に置き場所を足す）
# EXTRA_PATH="$HOME/.nvm/versions/node/v20.19.0/bin:$HOME/claw"

# deepseek の起動スクリプトが PATH に無いときだけ、絶対パスで指定する（通常は不要）
# DEEPSEEK_LAUNCHER="$HOME/claw/deepseek"

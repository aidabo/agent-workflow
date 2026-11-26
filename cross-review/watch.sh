#!/usr/bin/env bash
# watch.sh — 開いている PR を 1 巡して、未レビューの head だけ cross-review.sh に渡す。
# cross-review.sh はPRごとにworktree/lockを持つため、同じrepoの独立PRも並列に進む。
# 常駐はしない。cron / systemd timer から数分おきに呼ぶ（README 参照）。
set -uo pipefail
here="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
# shellcheck source=config.sh
source "$here/config.sh"
# cron は PATH が最小なので、gh / claude / codex(nvm) / node を明示する
if [[ -z "$EXTRA_PATH" ]]; then
  EXTRA_PATH="$(ls -d "$HOME"/.nvm/versions/node/*/bin 2>/dev/null | sort -V | tail -1)"
fi
export PATH="$HOME/.local/bin${EXTRA_PATH:+:$EXTRA_PATH}:/usr/local/bin:/usr/bin:/bin:$PATH"
mkdir -p "$STATE_DIR"
exec 8>"$STATE_DIR/watch.lock"
flock -n 8 || { echo "[watch] another pass is running"; exit 0; }

pids=()
labels=()
max_parallel="${MAX_PARALLEL_REVIEWS:-4}"
[[ "$max_parallel" =~ ^[1-9][0-9]*$ ]] || max_parallel=4

for entry in "${REPOS[@]}"; do
  IFS='|' read -r name gh_repo _ _ <<<"$entry"
  gh pr list -R "$gh_repo" --state open --json number,isDraft,labels \
    -q '.[] | select(.isDraft|not) | select([.labels[].name] | index("no-cross-review") | not) | .number' 2>/dev/null |
  while read -r pr; do
    "$here/cross-review.sh" "$name" "$pr" &
    pids+=("$!")
    labels+=("$name #$pr")
    while [[ ${#pids[@]} -ge "$max_parallel" ]]; do
      wait -n || true
      for i in "${!pids[@]}"; do
        if ! kill -0 "${pids[$i]}" 2>/dev/null; then
          unset 'pids[i]' 'labels[i]'
        fi
      done
      pids=("${pids[@]}")
      labels=("${labels[@]}")
    done
  done
done

for i in "${!pids[@]}"; do
  wait "${pids[$i]}" || echo "[watch] ${labels[$i]} failed" >&2
done

# 未通知のレビューを、手すきのエージェントに届ける（前の巡回で作業中だった分も）
"$here/notify.sh" || true

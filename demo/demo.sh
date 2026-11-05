#!/usr/bin/env bash
# one card through the lane on a throwaway hermes home and a throwaway repo.
# usage: demo/demo.sh [fake|claude-code|codex]   default fake, which spends no quota
# set LANE_DEMO_DIR to reuse a home. hermes prepares its runtime on a new home's first run.
set -euo pipefail

who=${1:-fake}
root=$(cd "$(dirname "$0")/.." && pwd)
dir=${LANE_DEMO_DIR:-$(mktemp -d)}
export HERMES_HOME="$dir/home"
export CODING_LANE_TMUX_SOCKET="coding-lane-demo-$$"
unset HERMES_KANBAN_DB HERMES_KANBAN_BOARD HERMES_KANBAN_HOME HERMES_KANBAN_TASK HERMES_KANBAN_RUN_ID

mkdir -p "$HERMES_HOME/plugins"
ln -sfn "$root" "$HERMES_HOME/plugins/coding-lane"

assignee=$who
agent_config=""
shown_file=""
if [ "$who" = fake ]; then
  assignee=claude-code
  shown_file=fake.txt
  export CLAUDE_CONFIG_DIR="$dir/claude"
  agent_config="claude: {bin: $root/tests/fake_agent.py}"
elif [ "$who" = claude-code ]; then
  agent_config="claude: {model: ${LANE_DEMO_CLAUDE_MODEL:-haiku}, allowed_tools: [Write, Edit, Read, 'Bash(python3 -c *)', 'Bash(cat *)', 'Bash(ls *)', 'Bash(git status *)', 'Bash(git diff *)']}"
fi
cat > "$HERMES_HOME/config.yaml" <<YAML
plugins:
  enabled: [coding-lane]
  entries:
    coding-lane:
      settings:
        poll_seconds: 1
        auto_trust: true
        $agent_config
YAML

repo="$dir/repo-$$"
git init -q "$repo"
git -C "$repo" -c user.name=demo -c user.email=demo@example.com commit -q --allow-empty -m init
git -C "$repo" config user.name demo
git -C "$repo" config user.email demo@example.com

status() { sqlite3 "$HERMES_HOME/kanban.db" "select status from tasks where id='$card'"; }
wait_status() {
  for _ in $(seq 1 "${2:-150}"); do
    [ "$(status)" = "$1" ] && return 0
    sleep 2
  done
  echo "timed out waiting for $1, card is $(status)" >&2
  hermes kanban show "$card" >&2
  return 1
}
say() { printf '\n== %s\n' "$*"; }

trap 'tmux -L "$CODING_LANE_TMUX_SOCKET" kill-server 2>/dev/null || true' EXIT

say "a plugin that loads"
hermes plugins list 2>&1 | grep -E 'coding-lane' || true

# a slow first step, so a message can land in the middle of the work
slow="Run this exact command first: python3 -c 'import time; time.sleep(30)'."
new_card() {
  hermes kanban create "$1" --assignee "$assignee" --workspace "worktree:$repo" --body "$2" --json \
    | python3 -c 'import json,sys; s=sys.stdin.read(); print(json.loads(s[s.index("{"):])["id"])'
}
tick() {
  hermes kanban dispatch --json | python3 -c 'import json,sys; s=sys.stdin.read(); print("dispatcher skipped_nonspawnable:", json.loads(s[s.index("{"):])["skipped_nonspawnable"])'
}
send() {
  for _ in 1 2 3 4 5 6 7 8 9 10; do
    # a session still starting refuses the message, so the first tries can fail
    hermes coding-lane send "$card" "$1" > "$dir/send.json" || true
    grep -q '"delivery"' "$dir/send.json" && break
    sleep 3
  done
  cat "$dir/send.json"
}

say "a card for $assignee, in its own worktree"
card=$(new_card "Write HELLO.txt" "$slow Then create HELLO.txt containing the word hello. scenario=wait")
echo "$card"

say "the dispatcher skips it and the lane claims it on the same tick"
tick
wait_status running 30
hermes coding-lane status "$card"

say "steer the session mid-run. no hermes model turn is involved"
sleep "${LANE_DEMO_SETTLE:-8}"
send "Also add a second line to HELLO.txt with the word steered."
if [ "$who" = fake ]; then hermes coding-lane send "$card" "please finish now" >/dev/null || true; fi

say "the card goes to review, not done"
wait_status review
hermes kanban show "$card" | sed -n '/Runs/,$p'
git -C "$repo" show "wt/$card:${shown_file:-HELLO.txt}"

say "stop a second card mid-run. it is parked and keeps its session"
card=$(new_card "Write BYE.txt" "$slow Then create BYE.txt containing the word bye. scenario=wait")
echo "$card"
tick
wait_status running 30
sleep "${LANE_DEMO_SETTLE:-8}"
hermes coding-lane stop "$card" "changing the brief"
wait_status scheduled 30

say "resume it with a new instruction, in the same cli session"
hermes coding-lane resume "$card" "Put the word goodbye in BYE.txt instead of bye, and skip the slow command."
wait_status review
hermes coding-lane status "$card"
hermes kanban show "$card" | sed -n '/Runs/,$p'
git -C "$repo" show "wt/$card:${shown_file:-BYE.txt}"

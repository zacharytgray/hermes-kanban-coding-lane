# hermes-kanban-coding-lane

A Hermes Agent plugin that runs Claude Code and Codex as kanban workers.

Your message goes straight into the running CLI's own session, with no Hermes model turn in between. This works the same way on both CLIs. You can also attach to the session, or stop it and resume the same session later. Hermes kanban stays the source of truth for the card.

This is a first version. It is small on purpose, so one person can read it in a sitting.

## How it works

A card assigned to `claude-code` or `codex` is not a Hermes profile, so the dispatcher skips it and leaves it `ready`. The lane picks it up from there.

1. On each dispatcher tick, the `on_kanban_dispatch_tick` hook claims ready lane cards.
2. Hermes creates the card's git worktree. The lane refuses cards with no worktree.
3. The lane starts one supervisor process per card and registers its pid on the claim. The dispatcher's own crash, timeout and reclaim logic now covers the run.
4. The supervisor starts the CLI in its own tmux session, on a private tmux server, and posts the attach command and session link as card comments.
5. The supervisor heartbeats, watches the session and waits for the agent to report a status.
6. When the agent reports done, the lane commits what is in the worktree to the card's branch. It then moves the card to `review`, with the agent's report as the summary. It never moves a card to `done`.

The code is in `coding_lane/`. `board.py` is the only module that touches Hermes. `agents.py` holds everything that differs between the two CLIs.

## Compared with the other routes

Hermes already has a route to these CLIs. Kanban cards can carry `--skill claude-code` or `--skill codex`, and a Hermes worker then drives the CLI. Workers for Hermes ([hermes-workers](https://github.com/KaiyuWang99/hermes-workers)) also runs these CLIs directly from kanban. It already steers Claude Code over stdin from card comments, so this plugin is not the first to steer a running CLI.

| | `--skill claude-code` | Workers for Hermes | This plugin |
|---|---|---|---|
| Model between the card and the CLI | A Hermes model | None | None |
| Mid-run message reaches | The Hermes worker, at its next turn | The running Claude Code process | The running Claude Code or Codex session |
| Codex mid-run messages | Through the Hermes worker | None that I found in its code | Yes |
| Session link and tmux attach | Not on the card in my test | None that I found | Yes for Claude Code. Attach only for Codex |
| Resume the same CLI session after a stop | Up to the model | Only goal-mode turns, as far as I read | Yes |
| CLIs covered | Those with a skill | Claude Code, Codex, OpenCode, Qoder | Claude Code and Codex |
| Setup | A profile and a model | Plugin, settings page | Plugin, tmux |
| Size | Part of Hermes | About 9,000 lines | About 1,200 lines |
| How it hooks into dispatch | Native | Replaces the spawn default | Tick hook and kernel calls |

In one real run of `--skill claude-code` on Hermes v0.22.5, I commented on the card while a foreground `claude -p` was running. The CLI finished its original instruction. The comment then reached the Hermes model as a mid-run note, and the model started more `claude -p` runs to fix the file. The result was correct. The worker was steered, but the CLI process was not. I used a small local model for that test, so it says nothing about how well a stronger model would drive the CLI. I read the skill's tmux mode but did not test it.

### Use the skill instead when

- You want a Hermes model to decide what to do between CLI runs.
- The job is one-shot and nobody will need to redirect it.
- You want a native Hermes worker with no extra plugin, and comment steering at model turns is enough.
- You want Hermes tools, memory and skills in the loop.

### Use Workers for Hermes instead when

- You need OpenCode or Qoder.
- You want the CLI to use Hermes credentials, or a provider that Claude Code cannot reach directly.
- You want a settings page and Hermes context passed into the CLI.
- You only need to steer Claude Code, and you do not need attach or resume.

### Use this plugin when

- You want to redirect a running Codex or Claude Code session from chat.
- You want to open the session yourself, on another device or in a terminal.
- You want to stop work and pick up the same session later.

## Install

Requirements are Hermes 0.22.5 or later, tmux, macOS or Linux, and a logged-in `claude` or `codex` CLI. Real runs were only done on macOS.

```sh
git clone <this repo> ~/.hermes/plugins/coding-lane
hermes plugins enable coding-lane
```

Restart the gateway. Its embedded dispatcher is what ticks the lane. With no gateway, run `hermes kanban dispatch` or `hermes coding-lane tick` yourself.

Do not create Hermes profiles named `claude-code` or `codex`. The dispatcher would then run those cards natively.

## Use

```sh
hermes kanban create "Add a health check" --assignee codex --workspace worktree:/path/to/repo --body "..."
hermes coding-lane status
hermes coding-lane send <task> "Use the existing router instead."
hermes coding-lane stop <task> "Changing the brief"   # parks the card as scheduled
hermes coding-lane resume <task> "New brief is in the card."
```

From chat, the model can call the `coding_lane_status`, `coding_lane_send`, `coding_lane_stop` and `coding_lane_resume` tools. Enable the `coding_lane` toolset for your chat platform. These tools are the only part that spends a Hermes model turn, and only to decide to call them.

After review, a person closes the card with `hermes kanban complete`, or sends it back with `hermes kanban reopen-review`. A reopened card resumes the same CLI session. A card in review keeps its assignee, so the dispatcher will not start a review worker for it. To use a review worker, reassign the card to a review profile.

Settings go under `plugins.entries.coding-lane.settings`. See `plugin.yaml` for the list.

```yaml
plugins:
  entries:
    coding-lane:
      settings:
        max_running: 2
        claude: {model: sonnet, permission_mode: acceptEdits, allowed_tools: ["Bash(pytest *)"]}
        codex: {sandbox: workspace-write, approval: never}
```

## Who can steer

By default, only the chat tools and `hermes coding-lane send` reach a live CLI. New card comments do not. The reason is that a message to a live CLI can lead to code being run, and a comment's author is free text in Hermes that nobody verifies.

- The chat tools rely on Hermes to decide who may talk to the agent. The local command relies on shell access.
- To let comments steer, list authors in `steer_authors`. This stops accidents between agents on a board. It does not stop a hostile process, since anything that can write to the board can pick any author name.
- A listed comment reaches the CLI labelled with its author and a note that the label is not verified.
- Control characters are removed before pasting, so text cannot end the paste early and run as keystrokes.
- Every message is prefixed, so a leading `/` or `!` cannot run as a CLI command.
- A message is held while the session shows a dialog, since the Enter would answer it. The lane checks again right before each Enter. It knows a dialog by a numbered selected row or by the confirm footer the CLI draws under it.
- Each message uses its own tmux paste buffer, so two messages sent at once cannot swap sessions.

Card text is still input to the agent. The first prompt uses Hermes's own worker context, which includes the card body and any comments already on it. A resumed session gets every comment since it stopped, from any author, so that review notes reach it. The prompt tells the agent that this text is context, but that is only a request to a model and not a security control. Treat anyone who can write to your board as someone who can instruct your agent.

## Permissions

The lane never passes `--dangerously-skip-permissions` or `--dangerously-bypass-approvals-and-sandbox`. It refuses `bypassPermissions` and `danger-full-access` in its settings.

- Claude Code runs in `acceptEdits` by default. Anything else asks for approval in the session. The lane comments on the card when that happens. You answer through the session link or by attaching. Add commands to `allowed_tools` to avoid the wait.
- Codex runs with `--sandbox workspace-write --ask-for-approval never` by default. There are no prompts and commands stay inside the sandbox, which has no network. The sandbox also blocks writes to `.git`, which is why the lane does the commit.
- The CLI runs with a short allowlist of environment variables. Hermes keys and `HERMES_*` variables do not reach it. Use `env_passthrough` to add a key on purpose. The CLI uses its own login. The lane does not read or copy credentials.
- The lane does not answer trust prompts by default. A card in an untrusted repo goes to blocked, and you run the CLI there once to accept. The `auto_trust` setting answers the prompt instead. The CLI then saves that answer in its own config for the repo root.
- The agent has no `HERMES_KANBAN_*` variables and reports only through its final message. This is not a sandbox. Claude Code can still run whatever its permissions allow.

## When things go wrong

| What happened | What the lane does | Card ends up |
|---|---|---|
| CLI not logged in | Checks before starting and does not start | `blocked`, kind `capability` |
| Auth error in the session | Stops the session and does not retry | `blocked`, kind `capability` |
| Usage limit | Stops the session. You resume after the reset | `blocked`, kind `transient` |
| CLI crashes | Supervisor exits nonzero and the dispatcher records it | `ready` for a resumed retry, then `blocked` by the Hermes breaker |
| Supervisor is killed | The dispatcher records a crash. The next run adopts the live session | `ready`, then `running` |
| No activity for `stuck_seconds` | Stops the session | `blocked`, kind `transient` |
| Agent waits for a person past `idle_seconds` | Stops the session | `blocked`, kind `needs_input` |
| CLI exits with no status | Stops watching | `blocked`, kind `needs_input` |
| Claim lost, or max runtime reached | Ends the session | Whatever Hermes decided |
| Operator stop | Ends the session | `scheduled`, which Hermes does not count as a block loop |

Hermes sends a card to `triage` when it is blocked twice for the same reason with an unblock in between. That applies to lane cards too, for example a second usage limit after a resume. The lane does not try to undo that. A person moves the card on from `triage`.

Auth and quota errors are read from pane text only on a pane that has ended or gone quiet. Claude Code's `StopFailure` hook is also used. A quiet pane showing a matching phrase, such as a long test run that printed "rate limit exceeded", can block a card by mistake. Resuming it is safe.

## Hermes internals it uses

The CLI's `heartbeat` does not extend a claim, and the CLI cannot register a worker pid. So `coding_lane/board.py` calls the kernel directly. These calls are not a documented public API and could change in any release.

| Module | Calls |
|---|---|
| `kanban_db` | `claim_task`, `heartbeat_claim`, `request_review`, `block_task`, `unblock_task`, `add_comment`, `list_comments`, `list_comments_after`, `get_task`, `list_tasks`, `build_worker_context`, `worker_log_path`, `get_current_board` |
| `kanban_db_dispatch` | `adopt_worker_pid`, `heartbeat_worker` |
| `kanban_db_workspace` | `resolve_workspace`, `set_workspace_path` |
| `kanban_db_connect` | `connect_closing` |

It also uses `load_config` and `get_hermes_home`, and writes the worker exit line that the dispatcher reads from the log.

It patches nothing. `hermes plugins validate` passes, with the `no core override` check green and a warning that lists these imports. The catalog admission rules allow that warning, but they also ask for public surfaces only, so a reviewer could object. A reviewer could also ask about rule 11 on subscription logins and rule 12 on `auto_trust`. Nothing has been submitted.

## Moving to the public lane API

Open PR #146543 proposes a public `KanbanWorkerLane`. `spawn.spawn_supervisor(task, workspace, board)` already has the shape its `spawn` needs, so the move is a small class in place of `spawn.tick`.

```python
class Lane(KanbanWorkerLane):
    name = "coding-lane"
    assignees = ("claude-code", "codex")

    def spawn(self, claim):
        return spawn_supervisor(claim.task, claim.workspace, claim.board)
```

I ran this once with a fake CLI against that PR's head, `d980274a7d`, and the card reached review. It is not in this repo, since the PR has not merged.

## Tests and demo

Tests use real tmux and the real kanban kernel, with `tests/fake_agent.py` in place of the CLI. They use only the standard library. Run them with a Python that has Hermes's dependencies.

```sh
~/.hermes/hermes-agent/venv/bin/python -m unittest tests.test_lane
HERMES_SOURCE=/path/to/hermes-agent ~/.hermes/hermes-agent/venv/bin/python -m unittest tests.test_lane
```

`demo/demo.sh` takes one card through steer and review, and a second through stop and resume, on a throwaway home and repo. With no argument it uses the fake CLI and spends nothing. `demo/demo.sh claude-code` and `demo/demo.sh codex` use the real CLIs on tiny tasks. The demo turns on `auto_trust` for its throwaway repo, so the CLI saves a trust entry for that path in its own config. The first run on a new home is slow, because Hermes prepares its runtime there.

## What was tested

Versions were Hermes v0.22.5 and main at `84a0301415`, Claude Code 2.1.318, Codex 0.166.0, and tmux 3.6b, on macOS.

- All 45 tests pass on both Hermes versions.
- Real Claude Code and real Codex each completed the demo. That covers a mid-run message, review, stop, and resume in the same session id.
- A real Claude Code process killed with `kill -9` was recorded as a crash, retried in the same session, and reached review.
- In one real Claude Code run, a command outside the allowlist raised a permission prompt. The lane commented on the card and approved nothing.
- Real trust prompts were seen on both CLIs. Codex ignores a `-c projects` trust override, which is why the lane does not rely on one.
- Under a real gateway with a fake CLI, the tick claimed a card within seconds. `kill -9` on the supervisor was recorded as a crash, and the next run adopted the live session.
- A real Hermes model turn called `coding_lane_send`, and the message reached a fake CLI session.
- Empty CLI config directories blocked real Claude Code and real Codex with `capability`.

## Limits and what was not tested

- Real quota exhaustion was not tested on either CLI. Those paths have only run against a fake CLI showing phrases I wrote, and the real wording may differ.
- A real `StopFailure` event was not seen. A real auth failure inside a running session was not seen either, only the check before starting.
- Long sessions were not tested. The real runs were tiny, and the stuck and idle timers have only run with a fake CLI.
- Linux, multi-profile gateways, non-default boards through the gateway, and more than a few sessions at once were not tested.
- Steering depends on the CLI's terminal interface. A CLI update could change the input box or dialogs, and delivery would then report `unknown` or `stuck` rather than `sent`. Dialog detection only knows numbered rows.
- Codex has no per-session link here. Its handle is the attach and resume commands.
- If the Remote Control link never appears in the pane, the card only has the attach command. A login with an API key may not get a link.
- The chat tools were called from `hermes chat`, not from a messaging platform.
- Heartbeats add one card event a minute, as native workers do. Hermes has open work to quiet that.
- The dispatcher's `max_spawn` and per-profile caps do not cover the lane. `max_running` is its own cap, per board, and it counts only lane cards.
- Worktrees stay on disk until Hermes cleans them up after completion.

## License

MIT. See `LICENSE`.

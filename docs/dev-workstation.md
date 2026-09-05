# Linux dev-workstation

This repository contains the reproducible, user-local Linux workstation flow. It does not install packages, use `sudo`, change authentication, manage secrets, or deploy anything.

## Setup

Clone the repository and run:

```bash
./bin/install-linux-devstation
```

Use `--dry-run` to inspect the directories, scripts, backups, and links that would be changed. The installer creates `~/agent-workstation/{repos,worktrees,artifacts,runs,locks,scripts}`, installs mode-700 copies of the runner, doctor, and worktree collector, and links all three commands from `~/.local/bin`.

## Sync and rollback

From a clean dotfiles checkout, `bin/workstation-sync` fetches `origin/main`, advances only with `git merge --ff-only`, and runs the installer:

```bash
~/.local/bin/workstation-sync
```

It refuses dirty checkouts. For PR testing, use `--local-current-tree` to skip fetch/pull; `--dry-run` is also available. Sync never changes repositories, worktrees, or task artifacts. When an installed script differs, the installer keeps one timestamped sibling backup before replacing it. To roll back, copy a selected backup back to `~/agent-workstation/scripts/agent-task`, `workstation-doctor`, or `worktree-gc`, then restore mode 700 and rerun the doctor.

## Doctor

```bash
~/.local/bin/workstation-doctor
```

The doctor performs practical CLI, runtime, browser, container, service, and auth checks. Auth checks report only pass/fail and do not print command output. Set `AGENT_WORKSTATION_ROOT` when the workstation root is elsewhere. It also verifies that the installed runner advertises `attach`, `start`, `status`, and `wait`, including JSON output, that `worktree-gc` advertises `inventory`, `collect`, and `inode-check`, and it reports inode/space headroom so exhaustion is visible before it bites.

## Runner lifecycle

Prepare a clean issue worktree, or attach an existing absolute-path worktree:

```bash
agent-task prepare --project spotworkshops --issue SPOT-123 --repo git@github.com:deinte/project.git
agent-task start --issue SPOT-123 --prompt-file ~/agent-workstation/artifacts/SPOT-123/prompt.txt --agent codex
agent-task status --issue SPOT-123 --json
agent-task wait --issue SPOT-123 --json
agent-task stop --issue SPOT-123
```

Codex is the inexpensive default (`gpt-5.6-luna`); use `--agent claude` for the Claude fallback and pass `--model` when needed. `smoke` is available for local tests. Runs are bounded, lock each worktree, record heartbeats/snapshots, and return non-zero for failed, timed-out, stopped, or lost runs.

## Worktree retention

Worktrees accumulate `vendor/` and `node_modules/` trees and are the main source
of inode pressure on this host. `worktree-gc` inventories them and, only under
an explicit manual approval flag, removes stale ones:

```bash
worktree-gc                    # read-only inventory (default command)
worktree-gc collect            # removal plan only; deletes nothing
worktree-gc collect --approve  # human-approved removal, plain `git worktree remove`
worktree-gc inode-check        # 0 ok, 1 warn, 2 critical, 3 unknown
```

Every safety predicate fails closed, local branches and commits are preserved,
and `--approve` must never be scheduled. Three gates in particular are strict:
a worktree stays blocked while any process's `/proc` references are unreadable,
a task-associated worktree needs its external board state recorded in
`task_cleanup_approved`, and `collect --approve` holds the `agent-task`
per-worktree flock from the final check until after `git worktree remove`. See
[Worktree retention and inode pressure](worktree-retention.md) for the full
blocker list, configuration, monitoring setup, and rollout policy.

## No-secrets policy

Never commit tokens, API keys, `.env` files, dumps, customer data, prompts containing credentials, or generated task secrets to this repository or its artifacts. Use the host’s existing authenticated CLIs and local secret stores. This flow makes no auth changes and performs no production operations.

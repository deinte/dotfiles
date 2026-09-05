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
worktree-gc inode-check        # 0 ok, 1 warn, 2 critical, 3 unknown

# human-approved removal of one reviewed worktree; both flags are required
worktree-gc collect --approve \
  --worktree ~/agent-workstation/worktrees/<name> \
  --approve-task-cleanup <task-id-or-worktree-basename>
```

Every safety predicate fails closed, local branches and commits are preserved,
and `--approve` must never be scheduled. `--approve` alone is not enough to
delete anything: it permits removals that are already eligible but supplies no
cleanup identity, which `--approve-task-cleanup` (or the durable
`task_cleanup_approved` config key) must do separately. Four gates in particular
are strict:

- **process coverage** — a single pid whose `/proc` references are unreadable
  blocks *every* worktree with `process-coverage-incomplete`, on the default
  configuration. Only a read-only privileged probe (`sudo -n`, so passwordless
  sudo is required) can clear it; with no such privilege, nothing is removable;
- **task-associated worktrees** need their external board state recorded, which
  includes a worktree associated only by being named after a Kanban task
  (`t_35c15c8a`, `t_3626513e-revert`) whose local metadata may be missing
  entirely;
- **every other managed worktree** (`SPOT-123`, `payments-spike`) is gated on its
  exact basename with `worktree-cleanup-not-approved`, so nothing falls through
  for lack of metadata;
- **the removal lock** — `collect --approve` holds the `agent-task` per-worktree
  flock from the final check until after `git worktree remove`.

Prefer the one-shot `--approve-task-cleanup` flag over a config entry, and
delete any config entry once the removal it authorised succeeded — otherwise a
worktree later recreated with the same name inherits the stale approval. See
[Worktree retention and inode pressure](worktree-retention.md) for the full
blocker list, configuration, monitoring setup, and rollout policy.

## No-secrets policy

Never commit tokens, API keys, `.env` files, dumps, customer data, prompts containing credentials, or generated task secrets to this repository or its artifacts. Use the host’s existing authenticated CLIs and local secret stores. This flow makes no auth changes and performs no production operations.

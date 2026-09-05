# Worktree retention and inode pressure

The dev workstation keeps one git worktree per issue under
`~/agent-workstation/worktrees`. Each one carries its own `vendor/` and
`node_modules/`, so a few hundred thousand inodes accumulate per dozen
worktrees. A stale-worktree pile-up is what drove the filesystem to 100% inode
use; `worktree-gc` exists to make that visible early and to make cleanup
boring, auditable, and human-approved.

`worktree-gc` is installed by `bin/install-linux-devstation` to
`~/agent-workstation/scripts/worktree-gc` and linked as `~/.local/bin/worktree-gc`.

## The approval gate

**Deletion is never automatic.** The tool has one destructive path and it is
opt-in per invocation:

- `worktree-gc inventory` — read-only. This is the default command, so a bare
  `worktree-gc` never deletes anything.
- `worktree-gc collect` — evaluates and prints the removal plan, then stops.
- `worktree-gc collect --approve` — the only form that removes anything, and
  only by running plain `git worktree remove <path>` with no `--force`.

Never put `--approve` in cron, a systemd timer, a doctor run, or an agent
prompt. The rollout below defines when — if ever — that changes.

## What makes a worktree eligible

A worktree is eligible only when **every** check below passes. Any check that
cannot be answered is a blocker, never a pass; this is the fail-closed rule the
whole tool is built on.

| Blocker | Meaning |
| --- | --- |
| `outside-managed-root` | not under `<root>/worktrees` |
| `self` | `worktree-gc` is running from inside it |
| `not-a-worktree`, `not-registered`, `not-a-directory` | git does not recognise it |
| `main-worktree` | the primary working tree of a repo |
| `worktree-locked` | `git worktree lock` was used |
| `dirty` | `git status --untracked-files=all` is non-empty (tracked, staged, or untracked) |
| `status-unknown`, `ignored-scan-failed` | git could not report state |
| `protected-ignored-state` | a git-ignored path matches a protected glob (`.env`, `*.sqlite`, …) |
| `remote-default-ambiguous` | `refs/remotes/origin/HEAD` is unset — fix with `git remote set-head origin -a` |
| `remote-refs-not-fetched`, `fetch-failed` | remote refs are not fresh |
| `not-merged`, `head-unknown` | HEAD is not already reachable from the remote default branch |
| `too-recent`, `age-unknown` | younger than the minimum age, or no usable timestamp |
| `in-use-by-process` | a process has cwd/root/exe/an open fd inside it (or names it in argv) |
| `listener-attached` | a listening socket belongs to a process inside it |
| `systemd-unit-associated` | any user unit — running or merely defined on disk — references the path |
| `task-in-flight` | an `agent-task` run for it has no terminal `result.json` |
| `task-metadata-unreadable` | `artifacts/*/run.json` or `runs/*.env` could not be parsed |
| `worktree-lock-held` | the `agent-task` per-worktree flock is held |
| `protected-task`, `protected-worktree` | explicitly protected by config or flag |
| `process-scan-failed`, `listener-scan-failed`, `unit-scan-failed` | a host scan failed; nothing is removable until it works |

Build output (`vendor/`, `node_modules/`, `public/build/`) is deliberately *not*
a blocker — reclaiming it is the point. Local credentials and databases are,
via `protected_ignored_globs`.

Removal preserves local branches and commits: `git worktree remove` deletes the
checkout directory and the worktree registration only. The branch and every
commit on it stay in the owning repository under `~/agent-workstation/repos`.

Eligibility is re-evaluated immediately before each removal, so a worktree that
becomes dirty or busy between the report and the delete is skipped.

### Process-scan boundary

Some of the workstation user's own processes (`systemd --user`, sshd session
leaders, `php-fpm` workers) are non-dumpable, so `/proc/<pid>/{cwd,root,exe,fd}`
is unreadable even though we own them. Those are matched on `argv` instead, and
the count is printed in every report. Set `strict_process_scan` (or pass
`--strict-process-scan`) to treat their existence as a blocker for everything —
correct but, on this host, permanently blocking.

## Usage

```bash
worktree-gc                                  # read-only inventory, default command
worktree-gc inventory --verbose --measure all
worktree-gc inventory --fetch                # refresh origin refs before judging reachability
worktree-gc inventory --json                 # machine-readable report
worktree-gc collect                          # print the removal plan, delete nothing
worktree-gc collect --approve                # HUMAN-APPROVED removal
worktree-gc inode-check                      # monitoring check
```

Useful flags: `--min-age-days`, `--protect-worktree`, `--protect-task`,
`--protect-ignored-glob`, `--worktree` (limit to one path), `--measure
none|eligible|all`, `--root`, `--config`.

The report lists per-worktree eligibility, every blocker, and the projected
inode/byte reclaim. After an approved run it prints the actual reclaimed inode
and byte counts per worktree and in total.

Measurement defaults to `eligible` because walking every worktree is itself
expensive on a loaded filesystem; use `--measure all` when you want the full
picture.

## Configuration

`~/agent-workstation/config/worktree-gc.json` (override with `--config`):

```json
{
  "min_age_days": 14,
  "warn_percent": 80,
  "critical_percent": 90,
  "strict_process_scan": false,
  "protected_tasks": ["SPOT-123"],
  "protected_worktrees": ["AE-V2-LAUNCH-READINESS"],
  "protected_ignored_globs": [".env", ".env.*", "*.sqlite", "*.sql", "auth.json"]
}
```

`protected_tasks` and `protected_worktrees` exist for associations the
workstation cannot query: a tmux session someone is about to return to, a
preview a colleague is sharing, a branch under review. If you cannot prove a
worktree is idle, list it. Unknown keys are reported as warnings rather than
silently ignored. Command-line `--protect-*` flags add to the config; they never
replace it.

Task names are matched with the same slug rule as `agent-task`, so `SPOT-123`,
`spot-123`, and the worktree directory name all resolve to the same protection.

## Inode alerting

```bash
worktree-gc inode-check [--path P] [--warn-percent 80] [--critical-percent 90] [--quiet] [--json]
```

Exit codes are Nagios-style so any monitor can consume them directly:

| Code | Meaning |
| --- | --- |
| 0 | OK |
| 1 | WARN — at or above the warn threshold |
| 2 | CRITICAL — at or above the critical threshold |
| 3 | UNKNOWN — path unreadable, no inode accounting, or inverted thresholds |

Both inode use and space use are evaluated; the worse of the two sets the level.
OK goes to stdout, alerts go to stderr. `--quiet` prints nothing while OK, which
suits cron's "mail only on output" behaviour. `workstation-doctor` runs it
without `--quiet`, matching the doctor's always-print `OK:`/`FAIL:` convention.

### Scheduling it

A user-level timer is enough; it must only ever run the *check*.

```ini
# ~/.config/systemd/user/worktree-inode-check.service
[Unit]
Description=Worktree inode headroom check

[Service]
Type=oneshot
ExecStart=%h/.local/bin/worktree-gc inode-check
```

```ini
# ~/.config/systemd/user/worktree-inode-check.timer
[Unit]
Description=Hourly worktree inode headroom check

[Timer]
OnCalendar=hourly
Persistent=true

[Install]
WantedBy=timers.target
```

```bash
systemctl --user enable --now worktree-inode-check.timer
systemctl --user list-timers worktree-inode-check.timer
```

A cron equivalent, quiet until it matters:

```cron
17 * * * * $HOME/.local/bin/worktree-gc inode-check --quiet
```

Pairing the check with a scheduled `inventory` is fine and useful — it is
read-only:

```cron
30 6 * * 1 $HOME/.local/bin/worktree-gc inventory > $HOME/agent-workstation/logs/worktree-gc-inventory.txt
```

**Do not schedule `collect --approve`.** Alerting is automatic; deleting is not.

## Rollout

1. **Now — observe.** Run `inventory` and the scheduled `inode-check`. Read the
   reports. Confirm the blockers match reality on this host, in particular that
   every active preview, tmux session, and in-flight task is blocked.
2. **Then — plan.** Run `collect` (no `--approve`) and check the plan against
   what you know is in use. Add anything questionable to `protected_worktrees`
   or `protected_tasks`.
3. **Only then — approve, one at a time.** Run
   `collect --approve --worktree <one path>` for a single reviewed worktree,
   confirm the branch still exists in the owning repo, and repeat. Reclaimed
   inode counts are printed per removal.
4. **Bulk removal stays a human decision.** A full `collect --approve` is
   acceptable only after step 3 has been exercised enough to trust the
   predicates on this host, and only when a person is watching it run.

No production systems are involved: `worktree-gc` touches only
`~/agent-workstation` on the dev workstation, makes no deploys, and changes no
services.

## Recovery

`git worktree remove` deletes the checkout, not the work. To bring a removed
worktree back:

```bash
cd ~/agent-workstation/repos/<project>
git worktree add ~/agent-workstation/worktrees/<name> <branch>
```

Only the reproducible parts — `vendor/`, `node_modules/`, build output — need
rebuilding. If a worktree held something that cannot be recreated, that is a bug
in `protected_ignored_globs`; add the pattern before running the tool again.

## Tests

```bash
tests/worktree-gc.bash        # safety predicates and command behaviour
tests/linux-devstation.bash   # install/link/backup flow, including worktree-gc
```

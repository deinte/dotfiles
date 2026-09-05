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
| `task-cleanup-not-approved` | a task is associated but its **external** (board) state was never confirmed complete |
| `task-metadata-unreadable` | `artifacts/*/run.json` or `runs/*.env` could not be parsed |
| `worktree-lock-held` | the `agent-task` per-worktree flock is held |
| `protected-task`, `protected-worktree` | explicitly protected by config or flag |
| `process-coverage-incomplete` | some process's `/proc` references are unknown, so "nothing is using it" is unproven |
| `process-scan-incomplete` | `strict_process_scan`: a process needed the privileged probe |
| `process-scan-failed`, `listener-scan-failed`, `unit-scan-failed` | a host scan failed; nothing is removable until it works |

Build output (`vendor/`, `node_modules/`, `public/build/`) is deliberately *not*
a blocker — reclaiming it is the point. Local credentials and databases are,
via `protected_ignored_globs`.

Removal preserves local branches and commits: `git worktree remove` deletes the
checkout directory and the worktree registration only. The branch and every
commit on it stay in the owning repository under `~/agent-workstation/repos`.

### The removal lock

Re-evaluating "immediately before" a removal is not enough on its own: an
`agent-task` run could still start between the final check and the delete.
`collect --approve` therefore takes the **exact** per-worktree `flock` that
`bin/agent-task` uses — `<root>/locks/<sha256 of the worktree path>.lock`, one
file per spelling of the path, since agent-task hashes the path as it was
spelled — *before* the final evaluation, and holds it continuously through the
tree measurement and the plain `git worktree remove`. Only then is it released.
An `agent-task` run that tries to start in that window fails to take the lock
and refuses, exactly as it would against another run.

If the lock cannot be taken, the worktree is **skipped**; it is never forced,
and the lock is never broken or removed. The lock files live in `<root>/locks`,
outside the worktree, so holding them does not interfere with the removal
itself.

Eligibility is re-evaluated under that lock, so a worktree that becomes dirty or
busy between the report and the delete is skipped.

### Process coverage fails closed

Two kinds of process cannot be inspected from an unprivileged `worktree-gc`:

- this user's non-dumpable processes (`systemd --user`, sshd session leaders,
  `php-fpm` workers), and
- every process owned by another uid (root daemons, containers, other users).

For both, `/proc/<pid>/{cwd,root,exe,fd}` is unreadable, so "no process has a
cwd or an open writer inside this worktree" is **unproven**. `argv` matching is
a hint, not proof: a process can hold a worktree without naming it on its
command line. Unproven is not the same as absent, so every such pid is recorded
as *uncovered* and, while any remain, `process-coverage-incomplete` blocks every
worktree. Inventory still reports each worktree's other findings, so you can see
what would otherwise be eligible — but nothing is removable.

There is exactly one way to clear an uncovered pid: prove what it references.
`worktree-gc` attempts a **read-only privileged probe** —
`sudo -n -- python3 -c <probe> <pids>` — which only calls `readlink`, `listdir`,
and read-mode `open` under `/proc` and prints what it found. It is
non-interactive: `sudo -n` never prompts, so on a host without passwordless
sudo the probe simply fails and everything stays blocked. Its output is only
trusted when it ends with the `PROBE-OK` sentinel and reports a definite status
(`ok` or `gone`) per pid; anything else clears nothing. References it finds are
merged into the normal evaluation, so a probed process holding a candidate shows
up as an ordinary `in-use-by-process` blocker.

Grant the probe by allowing exactly that read-only command in `sudoers`, or
leave it unavailable and accept that removal stays blocked. Turn the attempt off
with `privileged_process_probe: false` or `--no-privileged-process-probe`.

`strict_process_scan` (or `--strict-process-scan`) is the paranoid setting: it
blocks even when the probe *did* prove absence, on the grounds that some pid was
not directly readable by this user at all.

### Task lifecycle is external, and unknown means blocked

`artifacts/*/run.json` and `runs/*.env` describe the last **local** `agent-task`
execution. They are not the task's lifecycle. A run that reached `COMPLETED`,
`FAILED`, `TIMED_OUT`, or `STOPPED` — or a task with no local run at all — says
nothing about whether the Kanban card is still active, in review, blocked, or
simply unknown to this host. This tool is standalone and deliberately does not
query the board, so it cannot answer that question itself.

Therefore a worktree with **any** task association is blocked with
`task-cleanup-not-approved` until a human records the external decision:

```bash
worktree-gc collect --approve-task-cleanup SPOT-123 --approve --worktree <path>
```

or, durably, `task_cleanup_approved` in the config file. Adding a task there is
an explicit assertion that you looked at the board and it is completed or
otherwise approved for cleanup. Approval never overrides anything else: an
in-flight local run, a dirty tree, a held lock, or `protected_tasks` all still
block, and listing the same task as both protected and cleanup-approved is a
usage error rather than a silent precedence rule.

Names are matched with the `agent-task` slug rule, so `SPOT-123`, `spot-123`,
and `spot_123` are the same task.

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
`--protect-ignored-glob`, `--approve-task-cleanup`, `--worktree` (limit to one
path), `--measure none|eligible|all`, `--strict-process-scan`,
`--no-privileged-process-probe`, `--root`, `--config`.

The report lists per-worktree eligibility, every blocker, and the projected
inode/byte reclaim. That projection is an **estimate**: it is a pre-removal walk
of the tree (inode count and allocated bytes, hardlinks counted once), not an
observation of anything that was freed.

After an approved run, each removal reports two distinct numbers:

- **Estimated tree size** — the same pre-removal measurement, labelled as an
  estimate (`estimated_inodes` / `estimated_bytes` in `--json`).
- **Observed free-space delta** — `os.statvfs` snapshots taken immediately
  before and immediately after each `git worktree remove`, differenced
  (`observed_free_inode_delta` / `observed_free_bytes_delta`). Free inodes come
  from `f_ffree`; free bytes from `f_bavail * f_frsize`, i.e. space available to
  this unprivileged user, excluding root-reserved blocks.

The two are aggregated separately and never conflated. Read the observed delta
honestly: it is filesystem-wide, so anything else writing to or deleting from
the same filesystem during the removal window is included in it. It can
therefore understate or overstate the reclaim attributable to this run, and it
can be **negative** when concurrent allocation outweighs the reclaim. Negative
values are printed and stored raw — never clamped to zero and never replaced by
the estimate. If `statvfs` cannot be sampled, the observed delta is reported as
unavailable (with the error) and that removal is excluded from the observed
totals rather than being backfilled from the estimate.

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
  "privileged_process_probe": true,
  "strict_process_scan": false,
  "task_cleanup_approved": ["SPOT-118", "SPOT-121"],
  "protected_tasks": ["SPOT-123"],
  "protected_worktrees": ["AE-V2-LAUNCH-READINESS"],
  "protected_ignored_globs": [".env", ".env.*", "*.sqlite", "*.sql", "auth.json"]
}
```

`task_cleanup_approved` is the authoritative gate for task-associated
worktrees. Each entry means *a human checked the board and this task is
completed or approved for cleanup*. Anything not listed — active, in review,
blocked, or simply unknown — stays blocked. Keep the list short and prune it:
it is a record of decisions already made, not a standing permission. A task may
not appear in both `task_cleanup_approved` and `protected_tasks`; that is
rejected as a usage error.

`privileged_process_probe` controls whether the read-only `sudo -n` probe of
uninspectable pids is attempted at all. With it off (or with no passwordless
sudo), process coverage stays incomplete and nothing is removable.

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
3. **Only then — approve, one at a time.** For a single reviewed worktree,
   check its task on the board, then run
   `collect --approve --worktree <one path> --approve-task-cleanup <ISSUE>`.
   Confirm the branch still exists in the owning repo, and repeat. The estimated
   tree size and the observed free-space delta are printed per removal.
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

## Known limitations

- **The gate is only as good as the association.** A worktree whose
  `artifacts/*/run.json` and `runs/*.env` were deleted has no task association
  left, so `task-cleanup-not-approved` does not apply to it. It is still subject
  to every other blocker (dirty, unmerged, in use, too recent, locked), but the
  external-state gate cannot fire for a task it cannot see.
- **`task_cleanup_approved` is a human assertion, not a live query.** This tool
  does not talk to the board, so an entry that was true last week is still
  trusted today. Prune the list rather than letting it accumulate.
- **Process coverage depends on the privileged probe.** Without passwordless
  `sudo` for the read-only probe, coverage on a normal Linux host is never
  complete and `collect --approve` will remove nothing. That is the intended
  fail-closed outcome, not a malfunction.
- **The probe is a point-in-time proof.** It runs during the evaluation that the
  removal lock covers, so an `agent-task` run cannot slip in — but an unrelated
  process could still open the worktree in the same window. The lock does not,
  and cannot, exclude arbitrary processes.
- **`argv` matching stays best-effort** for any pid the probe could not cover; it
  can only ever add blockers, never clear them.

## Tests

```bash
tests/worktree-gc.bash        # safety predicates and command behaviour
tests/linux-devstation.bash   # install/link/backup flow, including worktree-gc
```

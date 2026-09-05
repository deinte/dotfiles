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

`--approve` is permission to carry out removals that are *already* eligible.
It is not an identity: every managed worktree also needs a cleanup approval
naming the task it belongs to, or — when nothing can be resolved to a task —
naming its exact directory. See
[Task lifecycle is external](#task-lifecycle-is-external-and-unknown-means-blocked).

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
| `task-cleanup-not-approved` | a task is associated — by local metadata, or by the worktree being named after it — but its **external** (board) state was never confirmed complete |
| `worktree-cleanup-not-approved` | no association and no inferable task id, so the worktree's own basename is the cleanup identity and it was never approved |
| `task-metadata-unreadable` | `artifacts/*/run.json` or `runs/*.env` could not be parsed |
| `worktree-lock-held` | the `agent-task` per-worktree flock is held |
| `protected-task`, `protected-worktree` | explicitly protected by config or flag |
| `process-coverage-incomplete` | some process's `/proc` references are unknown, so "nothing is using it" is unproven |
| `process-scan-incomplete` | `strict_process_scan`: a process needed the privileged probe |
| `process-scan-failed`, `listener-scan-failed`, `unit-scan-failed` | a host scan failed; nothing is removable until it works |

Build output (`vendor/`, `node_modules/`, `public/build/`) is deliberately *not*
a blocker — reclaiming it is the point. Local credentials and databases are,
via `protected_ignored_globs`, whose built-in patterns are a safety invariant
that configuration can extend but never switch off (see
[Ignored-state protection is additive](#ignored-state-protection-is-additive)).

Removal preserves local branches and commits: `git worktree remove` deletes the
checkout directory and the worktree registration only. The branch and every
commit on it stay in the owning repository under `~/agent-workstation/repos`.

### The removal lock

Re-evaluating "immediately before" a removal is not enough on its own: an
`agent-task` run could still start between the final check and the delete.
`collect --approve` therefore takes the **exact** per-worktree `flock` that
`bin/agent-task` uses — `<root>/locks/<sha256 of the worktree path>.lock` —
*before* the final evaluation, and holds it continuously through the plain
`git worktree remove`. Only then is it released. An `agent-task` run that tries
to start in that window fails to take the lock and refuses, exactly as it would
against another run.

**One canonical path, both sides.** The lock name is a hash of a path, so the
two sides only contend if they hash the *same* spelling. `agent-task attach` and
`agent-task start` both canonicalise to `git rev-parse --show-toplevel` resolved
to its real path before hashing — `start` in particular canonicalises the path it
reads out of `run.json`, which is data on disk and can hold `/./`, `//`, or `..`.
`worktree-gc` derives the same canonical path itself rather than assuming
whatever `prepare`/`attach` stored, and additionally probes the path as spelled
and its plain absolute form so a legacy lock taken before canonicalisation, or
by an older `agent-task`, is still seen. Extra probing can only add contention,
never miss it.

If the lock cannot be taken, the worktree is **skipped**; it is never forced,
and the lock is never broken or removed. The lock files live in `<root>/locks`,
outside the worktree, so holding them does not interfere with the removal
itself.

**Order inside the lock.** With the lock already held:

1. the tree is measured (the expensive step, seconds on a large worktree);
2. everything is then re-evaluated — host, process, listener, systemd, task,
   git — including a **fresh `git fetch origin`**, with freshness *required*;
3. the `statvfs` snapshot and the plain, non-`--force` `git worktree remove`
   follow immediately.

Measuring first keeps the slow step out of the recheck-to-removal window instead
of stretching that window by its whole duration. The recheck refetches because
reachability proved during planning can be invalidated afterwards by a
force-push or a moved default branch; no blocker is filtered out of it, so a
failed or missing fetch (`fetch-failed`, `remote-refs-not-fetched`) skips the
worktree rather than falling back to cached refs. A worktree that becomes dirty,
busy, unmerged, or task-blocked between the report and the delete is skipped.

### Process coverage fails closed

Two kinds of process cannot be inspected from an unprivileged `worktree-gc`:

- this user's non-dumpable processes (`systemd --user`, sshd session leaders,
  `php-fpm` workers), and
- every process owned by another uid (root daemons, containers, other users).

For both, `/proc/<pid>/{cwd,root,exe,fd}` is unreadable, so "no process has a
cwd or an open writer inside this worktree" is **unproven**. Coverage is
per-reference, not per-process: failing to resolve a *single* listed fd, or the
`exe` link, leaves that pid uncovered, because the reference we could not read
is exactly the one that might point inside a candidate.

A reference that is **gone** is not a failure. `ENOENT` means the process
exited, the fd was closed between the listing and the `readlink`, or the
reference never existed (a kernel thread has no `exe`) — nothing is left
unproven, so that ordinary race does not become a permanent blocker. Every other
error (`EACCES`/`EPERM` from a non-dumpable or foreign process, `EINVAL`,
anything else) does leave the pid uncovered. The privileged probe below makes
the same distinction and reports `unreadable` for that pid instead of `ok`.

`argv` matching is a hint, not proof: a process can hold a worktree without
naming it on its command line. Unproven is not the same as absent, so every pid
whose references could not be established is recorded as *uncovered* and, while
any remain, `process-coverage-incomplete` blocks every worktree. Inventory still reports each worktree's other findings, so you can see
what would otherwise be eligible — but nothing is removable.

There is exactly one way to clear an uncovered pid: prove what it references.
`worktree-gc` attempts a **read-only privileged probe** —
`sudo -n -- python3 -c <probe> <pids>` — which only calls `readlink`, `listdir`,
and read-mode `open` under `/proc` and prints what it found. It is
non-interactive: `sudo -n` never prompts, so on a host without passwordless
sudo the probe simply fails and everything stays blocked. Its output is only
trusted when it ends with the `PROBE-OK` sentinel, every line parses, and it
reports a definite status (`ok` or `gone`) per pid; partial output, a pid it
listed references for but never gave a final status to, or any line that does
not parse clears nothing. References it finds are merged into the normal
evaluation, so a probed process holding a candidate shows up as an ordinary
`in-use-by-process` blocker.

**Do not grant this with a `sudoers` rule for `python3 -c`.** A rule that lets a
command run arbitrary inline source under `sudo` is a grant of root, not of a
probe: the probe body is passed on the command line, so anything able to invoke
that rule can substitute any other body. The safe enablement path is a *fixed,
root-owned, non-writable helper script* on disk, with a `sudoers` rule naming
that exact path and nothing else — which is future work; the tool does not ship
one today. Until it exists, the honest position is that the probe is unavailable
on a normal host: process coverage stays incomplete and `collect --approve`
deletes nothing. That is the intended outcome, not a malfunction. Turn the
attempt off entirely with `privileged_process_probe: false` or
`--no-privileged-process-probe`.

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

An association is established three ways, and any one of them is enough:

#### 1. Local metadata

`artifacts/*/run.json` or `runs/*.env` names the worktree. This is how named
issues like `SPOT-123` are associated when their metadata still exists.

#### 2. The worktree name is a Kanban task id

A basename that *is* a Kanban task id (`t_[0-9a-f]+`), with or without a purpose
suffix, belongs to that task whether or not any metadata survives. `t_35c15c8a`
infers `t_35c15c8a`; `t_3626513e-revert` and `t_69b6784b-di` infer `t_3626513e`
and `t_69b6784b`. Deleting the artifacts of such a worktree does not make it
removable — the gate follows the name.

Inference is anchored to the whole basename and the hex run is greedy, so
approving one task never leaks to a similarly-named one: `t_3626513e` does not
cover `t_3626513eab` (a different task) or `t_3626513` (another different
task), and it covers `t_3626513e-revert` only because that name *is*
`t_3626513e` plus a suffix. The inferred task is reported in the record's
`inferred_task` field and listed under `tasks` with `source: worktree-name`.

#### 3. The generic basename fallback

`t_<hex>` is the only name shape that can be *inferred* as a Kanban id, but it
is far from the only name in use. Agent-task issues and their worktrees are also
called `SK-123`, `SPOT-123`, `SAL-45`, other arbitrary task keys, or nothing
task-shaped at all (`payments-spike`, a legacy topic directory). If such a
worktree has no `artifacts/*/run.json` or `runs/*.env` entry — deleted, never
written, or written on another host — there is no association *and* no
inference, and the two gates above would both miss it.

So they do not miss it. When a managed worktree has **neither** an
artifact-derived association **nor** a recognised `t_<hex>` inference, the tool
synthesises a cleanup identity from the **exact worktree basename** and blocks
the worktree with `worktree-cleanup-not-approved` until that name is approved:

```bash
worktree-gc collect --approve-task-cleanup SK-123 --approve --worktree <path>
```

The synthesised identity is reported in the record's `cleanup_identity` field
and listed under `tasks` with `source: worktree-name-fallback`, so a report
always shows what an approval would have to name.

This is deliberately conservative for topic and legacy directories: the tool
cannot tell them apart from an active task's worktree, so the operator checks
who owns that exact directory once and approves that exact name once.

Fallback approvals are matched **verbatim**, not through the slug rule that
applies to task ids. A directory name is not a task key, and slugging would
collapse `SK-123`, `sk_123`, and `SK--123` onto a single approval; three
different directories must never share one. `SK-12` therefore does not cover
`SK-123` or `SK-1234`, and `sk-123` does not cover `SK-123`. Approve the name
exactly as the report prints it.

`--approve` on its own is *only* permission to perform removals that are
already eligible. It never supplies a missing identity: a candidate whose
association is unknown or absent cannot become eligible from `--approve` alone.

#### Recording the approval

Every gate above is cleared the same way: `--approve-task-cleanup <name>` for one
run, or, durably, `task_cleanup_approved` in the config file. Adding an entry
there is an explicit assertion that you looked at the board — or, for the generic
fallback, at what owns that directory — and it is completed or otherwise approved
for cleanup. Approval never overrides anything else: an in-flight local run, a
dirty tree, a held lock, `protected_worktrees`, or `protected_tasks` all still
block, and listing the same task as both protected and cleanup-approved is a
usage error rather than a silent precedence rule.

Task ids (gates 1 and 2) are matched with the `agent-task` slug rule, so
`SPOT-123`, `spot-123`, and `spot_123` are the same task. Basename fallback
identities (gate 3) are matched verbatim, as described above. One
`task_cleanup_approved` list feeds both; an entry is used under whichever rule
applies to the worktree it is being tested against.

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
  "task_cleanup_approved": ["SPOT-118", "SPOT-121", "t_35c15c8a", "SK-123"],
  "protected_tasks": ["SPOT-123"],
  "protected_worktrees": ["AE-V2-LAUNCH-READINESS"],
  "protected_ignored_globs": ["*.pem"]
}
```

`protected_ignored_globs` here lists only the *extra* patterns: `*.pem` is added
to the built-in protection, not substituted for it.

`task_cleanup_approved` is the authoritative gate for task-associated
worktrees, including worktrees associated only by name (`t_35c15c8a`,
`t_35c15c8a-revert`) and worktrees with no association at all, which are gated
on their exact basename (`SK-123`, `payments-spike`). Each entry means *a human
checked the board — or checked what owns that directory — and this is completed
or approved for cleanup*. Anything not listed — active, in review,
blocked, or simply unknown — stays blocked. Keep the list short and prune it:
it is a record of decisions already made, not a standing permission. A task may
not appear in both `task_cleanup_approved` and `protected_tasks`; that is
rejected as a usage error.

`privileged_process_probe` controls whether the read-only `sudo -n` probe of
uninspectable pids is attempted at all. With it off (or with no passwordless
sudo), process coverage stays incomplete and nothing is removable.

### Ignored-state protection is additive

`protected_ignored_globs` is not a plain default. The built-in patterns —
`.env`, `.env.*`, `*.sqlite`, `*.sqlite3`, `*.sql`, `*.dump`, `auth.json`,
`.envrc` — are safety invariants: git-ignored local credentials, databases, and
dumps are not reproducible, and losing them to a GC run is not recoverable from
the branch that survives.

Configuration therefore **adds** to them and can never subtract. Both the config
key and the repeatable `--protect-ignored-glob` flag are merged onto the
built-in list (duplicates dropped, order preserved), so:

- `"protected_ignored_globs": []` protects exactly the built-ins — it does not
  disable them;
- `"protected_ignored_globs": ["*.pem"]` protects the built-ins **and** `*.pem`;
- no config value, and no flag, can make a worktree holding a `.env` or a
  SQLite database removable. Use `protected_worktrees` if you need a different
  kind of exception, or move the file out of the worktree.

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
in `protected_ignored_globs`; add the pattern before running the tool again. It
is added to the built-in patterns, so doing so can only widen protection.

## Known limitations

- **Name inference still covers `t_<hex>` worktrees only, so everything else
  costs a per-directory approval.** A worktree whose name is not a recognisable
  task id — a named-issue tree like `SPOT-123`, a topic tree like
  `bold-studio-theme-redesign`, a name that merely *contains* a task id
  (`marvino-demo-t_93841552`), or one spelled with another separator
  (`t-b3824a2f-di`) — cannot be resolved to a task when its
  `artifacts/*/run.json` and `runs/*.env` metadata is gone. That is now a
  blocker rather than a gap: the basename becomes the cleanup identity and
  `worktree-cleanup-not-approved` fires until an operator approves that exact
  name. The cost is real and intended — such worktrees are never removable in
  bulk, and each one needs its own checked, exact approval.
- **`task_cleanup_approved` is a human assertion, not a live query.** This tool
  does not talk to the board, so an entry that was true last week is still
  trusted today. Prune the list rather than letting it accumulate.
- **Process coverage depends on a privileged probe that has no safe enabler
  yet.** Without one, coverage on a normal Linux host is never complete and
  `collect --approve` will remove nothing. Enabling it via a broad `sudoers`
  rule for `python3 -c` is not an option (that is a root grant); a fixed
  root-owned helper with a rule naming its exact path is the safe route and is
  not built yet. No privilege therefore means deletion stays blocked.
- **Unrelated processes are point-in-time checked, and cannot be excluded.**
  The `agent-task` flock covers the managed writers — no `agent-task` run can
  start between the final recheck and the removal. It says nothing about any
  other process on the host: an editor, a shell, a build, a container can open
  or `cd` into the worktree microseconds after the recheck reads `/proc`, and
  there is no kernel mechanism this tool could use to prevent that. The process,
  listener, and unit checks are a snapshot taken as late as possible (which is
  why the tree measurement is moved ahead of them), not an exclusion. `git
  worktree remove` without `--force` is the backstop: it refuses when the tree
  is dirty, which is what a writer that arrived in that window would have made
  it.
- **`argv` matching stays best-effort** for any pid the probe could not cover; it
  can only ever add blockers, never clear them.

## Tests

```bash
tests/worktree-gc.bash             # safety predicates and command behaviour,
                                   # including the agent-task lock-path parity
                                   # regression (a lexical run.json path and a
                                   # GC candidate must contend on one flock)
tests/linux-devstation.bash        # install/link/backup flow, including worktree-gc
tests/integration-agent-task.bash  # the agent-task side of that contract
```

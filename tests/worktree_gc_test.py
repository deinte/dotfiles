#!/usr/bin/env python3
"""Tests for bin/worktree-gc safety predicates and command behaviour.

Run with: tests/worktree-gc.bash  (or python3 -m unittest tests.worktree_gc_test)
"""

import fcntl
import hashlib
import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "bin" / "worktree-gc"

spec = importlib.util.spec_from_loader(
    "worktree_gc", importlib.machinery.SourceFileLoader("worktree_gc", str(SCRIPT))
)
gc = importlib.util.module_from_spec(spec)
sys.modules["worktree_gc"] = gc  # dataclasses resolves annotations through sys.modules
spec.loader.exec_module(gc)

GIT_ENV = {
    **os.environ,
    "GIT_AUTHOR_NAME": "test",
    "GIT_AUTHOR_EMAIL": "test@example.com",
    "GIT_COMMITTER_NAME": "test",
    "GIT_COMMITTER_EMAIL": "test@example.com",
    "GIT_CONFIG_GLOBAL": "/dev/null",
    "GIT_CONFIG_SYSTEM": "/dev/null",
}


def run_git(*args, cwd=None):
    proc = subprocess.run(["git", *args], cwd=cwd, env=GIT_ENV, capture_output=True, text=True)
    if proc.returncode != 0:
        raise AssertionError(f"git {' '.join(args)} failed: {proc.stderr}")
    return proc.stdout


class PurePredicateTest(unittest.TestCase):
    def test_slugify_matches_agent_task(self):
        # bin/agent-task: lowercase, non-alphanumerics squeezed to '-', trimmed, 48 chars
        self.assertEqual(gc.slugify("SPOT-123"), "spot-123")
        self.assertEqual(gc.slugify("t_64503ff4"), "t-64503ff4")
        self.assertEqual(gc.slugify("--Weird__Name--"), "weird-name")
        self.assertEqual(len(gc.slugify("x" * 100)), 48)

    def test_slugify_agrees_with_shell_implementation(self):
        for value in ("SPOT-123", "t_64503ff4", "AE-V2-LAUNCH-READINESS", "a b/c"):
            shell = subprocess.run(
                ["bash", "-c",
                 "printf '%s' \"$1\" | tr '[:upper:]' '[:lower:]' | tr -cs 'a-z0-9' '-' "
                 "| sed 's/^-//;s/-$//' | cut -c1-48", "_", value],
                capture_output=True, text=True, check=True).stdout.strip("\n")
            self.assertEqual(gc.slugify(value), shell, value)

    def test_path_contains(self):
        self.assertTrue(gc.path_contains("/a/b", "/a/b"))
        self.assertTrue(gc.path_contains("/a/b", "/a/b/c"))
        self.assertTrue(gc.path_contains("/a/b/", "/a/b/c"))
        self.assertFalse(gc.path_contains("/a/b", "/a/bc"))
        self.assertFalse(gc.path_contains("/a/b", "/a"))
        self.assertFalse(gc.path_contains("", "/a"))

    def test_protected_ignored_globs_match_at_any_depth(self):
        globs = gc.DEFAULTS["protected_ignored_globs"]
        entries = ["node_modules/", "vendor/", ".env", "storage/db.sqlite", "app/.env.local", "public/build/"]
        self.assertEqual(
            sorted(gc.matches_protected_ignored(entries, globs)),
            sorted([".env", "storage/db.sqlite", "app/.env.local"]),
        )
        self.assertEqual(gc.matches_protected_ignored(["node_modules/", "vendor/"], globs), [])

    def test_human_bytes(self):
        self.assertEqual(gc.human_bytes(0), "0B")
        self.assertEqual(gc.human_bytes(2048), "2.0KiB")
        self.assertTrue(gc.human_bytes(5 * 1024 ** 3).endswith("GiB"))


class MeasureTreeTest(unittest.TestCase):
    def test_counts_inodes_and_dedupes_hardlinks(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "tree"
            (root / "sub").mkdir(parents=True)
            (root / "sub" / "a").write_bytes(b"x" * 4096)
            os.link(root / "sub" / "a", root / "b")  # hardlink: one inode, not two
            os.symlink("a", root / "link")
            inodes, size, errors = gc.measure_tree(str(root))
            self.assertEqual(errors, [])
            # root + sub + a + link (b is a hardlink to a)
            self.assertEqual(inodes, 4)
            self.assertGreaterEqual(size, 4096)

    def test_missing_path_reports_error(self):
        inodes, size, errors = gc.measure_tree("/nonexistent-worktree-gc-path")
        self.assertEqual((inodes, size), (0, 0))
        self.assertTrue(errors)


class FreeSpaceSnapshotTest(unittest.TestCase):
    def test_snapshot_reports_statvfs_free_inodes_and_available_bytes(self):
        with tempfile.TemporaryDirectory() as tmp:
            snapshot, error = gc.fs_free_snapshot(tmp)
            self.assertEqual(error, "")
            raw = os.statvfs(tmp)
            self.assertEqual(snapshot["free_inodes"], raw.f_ffree)
            # f_bavail (not f_bfree): bytes available to this unprivileged user.
            self.assertEqual(snapshot["free_bytes"], raw.f_bavail * raw.f_frsize)

    def test_snapshot_missing_path_reports_error(self):
        snapshot, error = gc.fs_free_snapshot("/nonexistent-worktree-gc-path")
        self.assertIsNone(snapshot)
        self.assertTrue(error)

    def test_anchor_is_the_parent_that_survives_removal(self):
        self.assertEqual(gc.snapshot_anchor("/a/b/c"), "/a/b")
        self.assertEqual(gc.snapshot_anchor("/a/b/c/"), "/a/b")
        self.assertEqual(gc.snapshot_anchor("/a"), "/")


class ProcessScanTest(unittest.TestCase):
    def _fake_proc(self, tmp, pid, cwd=None, fds=None):
        pid_dir = Path(tmp) / str(pid)
        (pid_dir / "fd").mkdir(parents=True)
        (pid_dir / "fdinfo").mkdir()
        if cwd:
            os.symlink(cwd, pid_dir / "cwd")
            os.symlink("/", pid_dir / "root")
            os.symlink("/bin/sh", pid_dir / "exe")
        (pid_dir / "cmdline").write_bytes(b"fake\0proc\0")
        for index, (target, flags) in enumerate(fds or []):
            os.symlink(target, pid_dir / "fd" / str(index))
            (pid_dir / "fdinfo" / str(index)).write_text(f"pos:\t0\nflags:\t0{flags:o}\n")
        return pid_dir

    def test_detects_cwd_and_writable_fd(self):
        with tempfile.TemporaryDirectory() as tmp:
            worktree = Path(tmp) / "wt"
            (worktree / "deep").mkdir(parents=True)
            target = worktree / "deep" / "file"
            target.write_text("x")
            proc = Path(tmp) / "proc"
            proc.mkdir()
            self._fake_proc(proc, 100, cwd=str(worktree))
            self._fake_proc(proc, 200, cwd="/tmp", fds=[(str(target), os.O_RDWR)])
            self._fake_proc(proc, 300, cwd="/tmp", fds=[(str(target), os.O_RDONLY)])
            self._fake_proc(proc, 400, cwd="/tmp")
            scan = gc.scan_processes(str(proc))
            self.assertEqual(scan.error, "")
            hits = gc.processes_using(scan, {str(worktree)})
            self.assertEqual(len(hits), 3, hits)
            self.assertIn("pid 100 cwd", hits[0])
            self.assertIn("read-only", " ".join(hits))
            self.assertEqual(gc.processes_using(scan, {str(Path(tmp) / "other")}), [])

    def test_unreadable_proc_root_is_a_hard_error(self):
        scan = gc.scan_processes("/nonexistent-proc-root")
        self.assertTrue(scan.error)

    def test_restricted_processes_matched_on_argv(self):
        scan = gc.ProcessScan(restricted={"9": "php artisan serve --cwd=/ws/worktrees/x"})
        self.assertTrue(gc.restricted_processes_naming(scan, {"/ws/worktrees/x"}))
        self.assertEqual(gc.restricted_processes_naming(scan, {"/ws/worktrees/y"}), [])


class ProcessCoverageTest(unittest.TestCase):
    """Uninspectable pids must fail closed: absence has to be proven, not assumed."""

    def _foreign_unreadable_proc(self, tmp, pid):
        """A pid dir with no readable cwd/root/exe links, owned by another uid."""
        pid_dir = Path(tmp) / str(pid)
        (pid_dir / "fd").mkdir(parents=True)
        (pid_dir / "fdinfo").mkdir()
        (pid_dir / "cmdline").write_bytes(b"root-daemon\0")
        return pid_dir

    def _scan_as_foreign(self, proc_root):
        # We cannot chown a fixture to another uid, so make our own uid differ.
        real_getuid = os.getuid
        os.getuid = lambda: real_getuid() + 4242
        try:
            return gc.scan_processes(str(proc_root))
        finally:
            os.getuid = real_getuid

    def test_unreadable_foreign_pid_is_recorded_as_uncovered(self):
        with tempfile.TemporaryDirectory() as tmp:
            proc = Path(tmp) / "proc"
            proc.mkdir()
            self._foreign_unreadable_proc(proc, 4242)
            scan = self._scan_as_foreign(proc)
            self.assertEqual(scan.error, "")
            self.assertEqual(scan.unreadable_foreign_pids, ["4242"])
            self.assertIn("4242", scan.uncovered_pids)
            self.assertFalse(scan.coverage_complete)

    def test_unreadable_own_pid_is_recorded_as_uncovered(self):
        with tempfile.TemporaryDirectory() as tmp:
            proc = Path(tmp) / "proc"
            proc.mkdir()
            self._foreign_unreadable_proc(proc, 77)
            scan = gc.scan_processes(str(proc))
            self.assertIn("77", scan.restricted)
            self.assertIn("77", scan.uncovered_pids)
            self.assertFalse(scan.coverage_complete)

    def _canned_probe(self, text):
        return lambda pids: ["printf", "%s", text]

    def _uncovered(self, pid="4242"):
        return gc.ProcessScan(
            unreadable_foreign_pids=[pid],
            uncovered_pids={pid: "foreign-uid pid, /proc links unreadable"},
        )

    def test_probe_clears_a_pid_and_merges_its_references(self):
        scan = gc.resolve_process_coverage(
            self._uncovered(),
            probe=self._canned_probe(
                "REF\t4242\tcwd\t0\t/srv/other\n"
                "REF\t4242\tfd3\t1\t/srv/other/log\n"
                "PID\t4242\tok\n"
                "PROBE-OK\n"
            ),
        )
        self.assertTrue(scan.coverage_complete)
        self.assertEqual(gc.processes_using(scan, {"/ws/worktrees/x"}), [])
        self.assertTrue(gc.processes_using(scan, {"/srv/other"}))

    def test_probe_that_finds_a_holder_reports_it(self):
        scan = gc.resolve_process_coverage(
            self._uncovered(),
            probe=self._canned_probe(
                "REF\t4242\tcwd\t0\t/ws/worktrees/x/sub\nPID\t4242\tok\nPROBE-OK\n"
            ),
        )
        self.assertTrue(scan.coverage_complete)
        self.assertTrue(gc.processes_using(scan, {"/ws/worktrees/x"}))

    def test_exited_pid_counts_as_covered(self):
        scan = gc.resolve_process_coverage(
            self._uncovered(), probe=self._canned_probe("PID\t4242\tgone\nPROBE-OK\n")
        )
        self.assertTrue(scan.coverage_complete)

    def test_probe_output_without_the_sentinel_clears_nothing(self):
        """Truncated or forged output must never be read as proof."""
        scan = gc.resolve_process_coverage(
            self._uncovered(),
            probe=self._canned_probe("REF\t4242\tcwd\t0\t/srv/other\nPID\t4242\tok\n"),
        )
        self.assertFalse(scan.coverage_complete)
        self.assertIn("no usable output", scan.probe)

    def test_probe_reporting_a_pid_unreadable_leaves_it_uncovered(self):
        scan = gc.resolve_process_coverage(
            self._uncovered(), probe=self._canned_probe("PID\t4242\tunreadable\nPROBE-OK\n")
        )
        self.assertFalse(scan.coverage_complete)
        self.assertIn("4242", scan.uncovered_pids)

    def test_probe_covering_only_some_pids_leaves_the_rest_uncovered(self):
        scan = gc.ProcessScan(
            unreadable_foreign_pids=["1", "2"],
            uncovered_pids={"1": "foreign", "2": "foreign"},
        )
        gc.resolve_process_coverage(
            scan, probe=self._canned_probe("PID\t1\tok\nPROBE-OK\n")
        )
        self.assertEqual(set(scan.uncovered_pids), {"2"})

    def test_failed_probe_leaves_coverage_incomplete(self):
        scan = gc.resolve_process_coverage(
            self._uncovered(), probe=lambda pids: ["false"]
        )
        self.assertFalse(scan.coverage_complete)
        self.assertIn("privileged probe unavailable", scan.probe)

    def test_disabled_probe_leaves_coverage_incomplete(self):
        scan = gc.resolve_process_coverage(self._uncovered(), enabled=False)
        self.assertFalse(scan.coverage_complete)
        self.assertIn("disabled", scan.probe)

    def test_probe_is_skipped_when_every_pid_was_readable(self):
        scan = gc.resolve_process_coverage(
            gc.ProcessScan(), probe=lambda pids: ["false"]
        )
        self.assertTrue(scan.coverage_complete)
        self.assertEqual(scan.probe, "not needed")

    def test_default_probe_is_non_interactive_and_read_only(self):
        command = gc.default_privileged_probe(["1", "2"])
        self.assertEqual(command[:3], ["sudo", "-n", "--"])
        self.assertEqual(command[-2:], ["1", "2"])
        source = gc.PRIVILEGED_PROBE_SOURCE
        for forbidden in ("os.remove", "os.kill", "shutil", "subprocess", '"w"', "'w'"):
            self.assertNotIn(forbidden, source, forbidden)

    def test_probe_source_runs_and_reports_this_process(self):
        """The probe body is executed for real against our own pid."""
        proc = subprocess.run(
            [sys.executable, "-c", gc.PRIVILEGED_PROBE_SOURCE, str(os.getpid()), "999999999"],
            capture_output=True, text=True,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        lines = proc.stdout.splitlines()
        self.assertEqual(lines[-1], gc.PROBE_SENTINEL)
        self.assertIn(f"PID\t{os.getpid()}\tok", lines)
        self.assertIn("PID\t999999999\tgone", lines)
        self.assertTrue(any(line.startswith(f"REF\t{os.getpid()}\tcwd\t0\t") for line in lines))


class ListenerScanTest(unittest.TestCase):
    def test_parses_ss_output(self):
        sample = (
            'tcp   LISTEN 0  511  100.85.13.112:8514  0.0.0.0:*    '
            'users:(("php",pid=1119392,fd=8))\n'
        )
        scan = gc.scan_listeners(["printf", "%s", sample])
        self.assertIn("1119392", scan.pids)
        self.assertEqual(scan.error, "")

    def test_failure_is_reported_not_swallowed(self):
        scan = gc.scan_listeners(["false"])
        self.assertTrue(scan.error)
        scan = gc.scan_listeners(["definitely-not-a-command-worktree-gc"])
        self.assertTrue(scan.error)


class UnitScanTest(unittest.TestCase):
    def test_loaded_units_are_matched_by_working_directory(self):
        listing = "preview.service loaded active running Preview\n"
        shown = (
            "Id=preview.service\nWorkingDirectory=/ws/worktrees/x\nExecStart={ path=/usr/bin/php }\n"
            "ActiveState=active\nFragmentPath=/home/u/.config/systemd/user/preview.service\n"
        )
        scan = gc.scan_units(
            config_dir=Path("/nonexistent"),
            list_command=["printf", "%s", listing],
            show=lambda units: (True, shown, ""),
        )
        self.assertEqual(scan.error, "")
        self.assertEqual(gc.units_referencing(scan, {"/ws/worktrees/x"}), ["preview.service (active)"])
        self.assertEqual(gc.units_referencing(scan, {"/ws/worktrees/y"}), [])

    def test_inactive_unit_files_on_disk_still_block(self):
        with tempfile.TemporaryDirectory() as tmp:
            unit_dir = Path(tmp)
            (unit_dir / "stopped-preview.service").write_text(
                "[Service]\nWorkingDirectory=/ws/worktrees/x\nExecStart=/usr/bin/php artisan serve\n"
            )
            scan = gc.scan_units(
                config_dir=unit_dir, list_command=["printf", "%s", ""], show=lambda units: (True, "", "")
            )
            self.assertEqual(
                gc.units_referencing(scan, {"/ws/worktrees/x"}), ["stopped-preview.service (unloaded)"]
            )

    def test_systemctl_failure_is_reported(self):
        scan = gc.scan_units(config_dir=Path("/nonexistent"), list_command=["false"])
        self.assertTrue(scan.error)


class TaskAssociationTest(unittest.TestCase):
    def _root(self, tmp):
        root = Path(tmp)
        for name in ("artifacts", "runs", "locks", "worktrees"):
            (root / name).mkdir(parents=True, exist_ok=True)
        return root

    def test_run_json_and_env_state_are_both_read(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._root(tmp)
            worktree = root / "worktrees" / "SPOT-1"
            worktree.mkdir()
            artifacts = root / "artifacts" / "SPOT-1"
            (artifacts / "runs" / "20260101T000000Z").mkdir(parents=True)
            (artifacts / "run.json").write_text(json.dumps({"issue": "SPOT-1", "worktree": str(worktree)}))
            (root / "runs" / "spot-1.env").write_text(
                f"ISSUE=SPOT-1\nWORKTREE={worktree}\nUNIT=agent-task-spot-1\n"
            )
            associations, problems = gc.read_task_associations(root)
            self.assertEqual(problems, [])
            issues = {a.issue for a in associations[str(worktree)]}
            self.assertEqual(issues, {"SPOT-1"})
            self.assertEqual(len(associations[str(worktree)]), 2)

    def test_unreadable_run_json_is_a_problem_not_silence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._root(tmp)
            (root / "artifacts" / "BAD").mkdir(parents=True)
            (root / "artifacts" / "BAD" / "run.json").write_text("{not json")
            _, problems = gc.read_task_associations(root)
            self.assertEqual(len(problems), 1)

    def test_in_flight_detection(self):
        with tempfile.TemporaryDirectory() as tmp:
            artifacts = Path(tmp) / "SPOT-1"
            runs = artifacts / "runs"
            runs.mkdir(parents=True)
            self.assertEqual(gc.task_is_in_flight(artifacts), (False, "no run directories"))

            (runs / "20260101T000000Z").mkdir()
            in_flight, _ = gc.task_is_in_flight(artifacts)
            self.assertTrue(in_flight)  # no result.json yet

            (runs / "20260101T000000Z" / "result.json").write_text(json.dumps({"state": "RUNNING"}))
            self.assertTrue(gc.task_is_in_flight(artifacts)[0])

            (runs / "20260101T000000Z" / "result.json").write_text(json.dumps({"state": "COMPLETED"}))
            self.assertFalse(gc.task_is_in_flight(artifacts)[0])

            # A newer run supersedes the completed one.
            (runs / "20260202T000000Z").mkdir()
            self.assertTrue(gc.task_is_in_flight(artifacts)[0])

            (runs / "20260202T000000Z" / "result.json").write_text("{corrupt")
            self.assertTrue(gc.task_is_in_flight(artifacts)[0])


class LockProbeTest(unittest.TestCase):
    def test_held_lock_blocks_and_free_lock_does_not(self):
        import fcntl
        import hashlib

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "locks").mkdir()
            worktree = str(root / "worktrees" / "x")
            digest = hashlib.sha256(worktree.encode()).hexdigest()
            lock_file = root / "locks" / f"{digest}.lock"

            self.assertEqual(gc.lock_is_held(root, worktree), (False, ""))  # no lock file

            lock_file.write_text("")
            self.assertFalse(gc.lock_is_held(root, worktree)[0])

            handle = open(lock_file, "a")
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            try:
                held, detail = gc.lock_is_held(root, worktree)
                self.assertTrue(held)
                self.assertIn(digest[:8], detail)
            finally:
                handle.close()
            self.assertFalse(gc.lock_is_held(root, worktree)[0])


# A competitor in a *separate process*: flock conflicts are per open file
# description, so an in-process probe could not tell "we hold it" from
# "somebody else holds it".
TRY_LOCK_SOURCE = """
import fcntl, sys
handle = open(sys.argv[1], 'a')
try:
    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
except OSError:
    sys.exit(3)
sys.exit(0)
"""

HOLD_LOCK_SOURCE = r"""
import fcntl, sys
handle = open(sys.argv[1], 'a')
fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
sys.stdout.write('LOCKED\n')
sys.stdout.flush()
sys.stdin.readline()
"""


def competitor_can_lock(lock_file) -> bool:
    """True when another process is able to take the agent-task flock right now."""
    proc = subprocess.run(
        [sys.executable, "-c", TRY_LOCK_SOURCE, str(lock_file)], capture_output=True
    )
    return proc.returncode == 0


class WorktreeLockGuardTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        (self.root / "locks").mkdir()
        self.worktree = str(self.root / "worktrees" / "x")

    def test_lock_files_cover_every_spelling_of_the_path(self):
        link = self.root / "link"
        link.symlink_to(self.root / "worktrees", target_is_directory=True)
        # agent-task hashes the path as spelled, so both spellings must be covered.
        through_link = str(link / "x")
        self.assertEqual(
            {f.name for f in gc.lock_files_for(self.root, through_link)},
            {
                hashlib.sha256(through_link.encode()).hexdigest() + ".lock",
                hashlib.sha256(self.worktree.encode()).hexdigest() + ".lock",
            },
        )

    def test_acquire_blocks_other_processes_and_release_frees_them(self):
        guard = gc.WorktreeLockGuard(self.root, self.worktree)
        acquired, error = guard.acquire()
        self.assertTrue(acquired, error)
        self.assertTrue(guard.held)
        for lock_file in guard.paths:
            self.assertFalse(competitor_can_lock(lock_file), lock_file)
        guard.release()
        for lock_file in guard.paths:
            self.assertTrue(competitor_can_lock(lock_file), lock_file)

    def test_acquire_fails_when_a_writer_already_holds_the_lock(self):
        lock_file = gc.lock_files_for(self.root, self.worktree)[0]
        holder = open(lock_file, "a")
        self.addCleanup(holder.close)
        fcntl.flock(holder.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        guard = gc.WorktreeLockGuard(self.root, self.worktree)
        acquired, error = guard.acquire()
        self.assertFalse(acquired)
        self.assertIn("held by another writer", error)
        self.assertFalse(guard.held)
        self.assertEqual(guard.lock_files, set())

    def test_a_failed_acquire_releases_whatever_it_already_took(self):
        link = self.root / "link"
        link.symlink_to(self.root / "worktrees", target_is_directory=True)
        spelling = str(link / "x")  # two spellings, so two lock files
        paths = gc.lock_files_for(self.root, spelling)
        self.assertEqual(len(paths), 2)
        holder = open(paths[-1], "a")
        self.addCleanup(holder.close)
        fcntl.flock(holder.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        guard = gc.WorktreeLockGuard(self.root, spelling)
        self.assertFalse(guard.acquire()[0])
        self.assertTrue(competitor_can_lock(paths[0]))

    def test_our_own_lock_is_not_mistaken_for_a_foreign_writer(self):
        guard = gc.WorktreeLockGuard(self.root, self.worktree)
        self.assertTrue(guard.acquire()[0])
        self.addCleanup(guard.release)
        # Without the ownership hint the same-process guard reads as a holder,
        # because flock conflicts across open file descriptions.
        self.assertTrue(gc.lock_is_held(self.root, self.worktree)[0])
        self.assertEqual(gc.lock_is_held(self.root, self.worktree, owned=guard.lock_files), (False, ""))


class GitHelperTest(unittest.TestCase):
    def test_worktree_registry_parsing(self):
        # Parsed from the porcelain format so the main worktree is always index 0.
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            run_git("init", "-q", "-b", "main", ".", cwd=repo)
            (repo / "f").write_text("x")
            run_git("add", "f", cwd=repo)
            run_git("commit", "-qm", "init", cwd=repo)
            run_git("worktree", "add", "-q", "-b", "side", str(Path(tmp) / "side"), cwd=repo)
            registry, error = gc.worktree_registry(str(repo))
            self.assertEqual(error, "")
            self.assertTrue(registry[str(repo)]["main"])
            self.assertFalse(registry[str(Path(tmp) / "side")]["main"])
            self.assertEqual(registry[str(Path(tmp) / "side")]["branch"], "refs/heads/side")

    def test_default_remote_ref_fails_closed_without_origin_head(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            run_git("init", "-q", "-b", "main", ".", cwd=repo)
            ref, error = gc.default_remote_ref(str(repo))
            self.assertEqual(ref, "")
            self.assertIn("origin/HEAD", error)

    def test_fetch_failure_is_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            run_git("init", "-q", "-b", "main", ".", cwd=repo)
            ok, error = gc.fetch_repo(str(repo))
            self.assertFalse(ok)
            self.assertTrue(error)


class WorkstationFixture:
    """A throwaway workstation root with an origin, a clone, and worktrees."""

    def __init__(self, tmp):
        self.root = Path(tmp) / "ws"
        for name in ("worktrees", "artifacts", "runs", "locks", "repos", "config"):
            (self.root / name).mkdir(parents=True)
        self.origin = Path(tmp) / "origin.git"
        run_git("init", "-q", "--bare", "-b", "main", str(self.origin))
        self.repo = self.root / "repos" / "proj"
        run_git("clone", "-q", str(self.origin), str(self.repo))
        run_git("symbolic-ref", "HEAD", "refs/heads/main", cwd=self.repo)
        (self.repo / "README").write_text("hello\n")
        (self.repo / ".gitignore").write_text("node_modules/\n.env\n*.sqlite\n")
        run_git("add", "-A", cwd=self.repo)
        run_git("commit", "-qm", "init", cwd=self.repo)
        run_git("push", "-q", "origin", "main", cwd=self.repo)
        run_git("remote", "set-head", "origin", "-a", cwd=self.repo)

    def add_worktree(self, name, branch, merged=True, commit=False):
        path = self.root / "worktrees" / name
        run_git("worktree", "add", "-q", "-b", branch, str(path), "origin/main", cwd=self.repo)
        if commit:
            (path / name).write_text("work\n")
            run_git("add", "-A", cwd=path)
            run_git("commit", "-qm", f"work {name}", cwd=path)
            if merged:
                run_git("push", "-q", "origin", f"{branch}:main", cwd=self.repo)
                run_git("fetch", "-q", "origin", cwd=self.repo)
        return path


class EndToEndTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.fixture = WorkstationFixture(self._tmp.name)
        # Host scans are stubbed to an empty, healthy machine; their own
        # behaviour is covered by the scan tests above.
        self._saved = (gc.scan_processes, gc.scan_listeners, gc.scan_units)
        gc.scan_processes = lambda *a, **k: gc.ProcessScan()
        gc.scan_listeners = lambda *a, **k: gc.ListenerScan()
        gc.scan_units = lambda *a, **k: gc.UnitScan()
        self.addCleanup(self._restore)

    def _restore(self):
        gc.scan_processes, gc.scan_listeners, gc.scan_units = self._saved

    def run_cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        code = 0
        with redirect_stdout(out), redirect_stderr(err):
            try:
                code = gc.main(["--root", str(self.fixture.root), *argv])
            except SystemExit as exc:
                code = exc.code
        return code, out.getvalue() + err.getvalue()

    def report(self, *argv):
        code, text = self.run_cli("inventory", "--json", "--min-age-days", "0", *argv)
        self.assertEqual(code, 0, text)
        return json.loads(text)

    def record(self, report, name):
        for entry in report["worktrees"]:
            if entry["name"] == name:
                return entry
        raise AssertionError(f"{name} not in report")

    def blockers(self, report, name):
        return {blocker["code"] for blocker in self.record(report, name)["blockers"]}

    # --- eligibility ---------------------------------------------------

    def test_clean_merged_old_worktree_is_eligible(self):
        self.fixture.add_worktree("clean", "feature/clean")
        report = self.report()
        self.assertEqual(self.blockers(report, "clean"), set())
        self.assertTrue(self.record(report, "clean")["eligible"])
        self.assertGreater(report["summary"]["projected_inodes"], 0)
        self.assertGreater(report["summary"]["projected_bytes"], 0)

    def test_untracked_file_blocks(self):
        path = self.fixture.add_worktree("dirty", "feature/dirty")
        (path / "scratch.txt").write_text("notes")
        self.assertIn("dirty", self.blockers(self.report(), "dirty"))

    def test_staged_change_blocks(self):
        path = self.fixture.add_worktree("staged", "feature/staged")
        (path / "README").write_text("changed\n")
        run_git("add", "README", cwd=path)
        self.assertIn("dirty", self.blockers(self.report(), "staged"))

    def test_ignored_build_output_does_not_block(self):
        path = self.fixture.add_worktree("built", "feature/built")
        (path / "node_modules" / "pkg").mkdir(parents=True)
        (path / "node_modules" / "pkg" / "index.js").write_text("//")
        report = self.report()
        self.assertEqual(self.blockers(report, "built"), set())

    def test_ignored_env_file_blocks(self):
        path = self.fixture.add_worktree("secrets", "feature/secrets")
        (path / ".env").write_text("APP_KEY=x")
        self.assertIn("protected-ignored-state", self.blockers(self.report(), "secrets"))

    def test_ignored_sqlite_database_blocks(self):
        path = self.fixture.add_worktree("db", "feature/db")
        (path / "database.sqlite").write_text("")
        self.assertIn("protected-ignored-state", self.blockers(self.report(), "db"))

    def test_unmerged_commit_blocks(self):
        self.fixture.add_worktree("ahead", "feature/ahead", merged=False, commit=True)
        self.assertIn("not-merged", self.blockers(self.report(), "ahead"))

    def test_merged_commit_is_eligible(self):
        self.fixture.add_worktree("merged", "feature/merged", merged=True, commit=True)
        self.assertEqual(self.blockers(self.report(), "merged"), set())

    def test_min_age_blocks_recent_worktrees(self):
        self.fixture.add_worktree("fresh", "feature/fresh")
        code, text = self.run_cli("inventory", "--json", "--min-age-days", "365")
        self.assertEqual(code, 0, text)
        report = json.loads(text)
        self.assertIn("too-recent", self.blockers(report, "fresh"))

    def test_age_defaults_to_fourteen_days(self):
        self.fixture.add_worktree("fresh", "feature/fresh")
        code, text = self.run_cli("inventory", "--json")
        report = json.loads(text)
        self.assertEqual(report["min_age_days"], 14.0)
        self.assertIn("too-recent", self.blockers(report, "fresh"))

    def test_missing_origin_head_fails_closed(self):
        self.fixture.add_worktree("noheadref", "feature/noheadref")
        run_git("symbolic-ref", "-d", "refs/remotes/origin/HEAD", cwd=self.fixture.repo)
        self.assertIn("remote-default-ambiguous", self.blockers(self.report(), "noheadref"))

    def test_non_worktree_directory_is_blocked(self):
        (self.fixture.root / "worktrees" / "junk").mkdir()
        self.assertIn("not-a-worktree", self.blockers(self.report(), "junk"))

    def test_git_locked_worktree_is_blocked(self):
        self.fixture.add_worktree("pinned", "feature/pinned")
        run_git("worktree", "lock", "--reason", "keep", str(self.fixture.root / "worktrees" / "pinned"),
                cwd=self.fixture.repo)
        self.assertIn("worktree-locked", self.blockers(self.report(), "pinned"))

    # --- association and protection ------------------------------------

    def test_in_flight_task_blocks(self):
        path = self.fixture.add_worktree("busy", "feature/busy")
        artifacts = self.fixture.root / "artifacts" / "BUSY"
        (artifacts / "runs" / "20260101T000000Z").mkdir(parents=True)
        (artifacts / "run.json").write_text(json.dumps({"issue": "BUSY", "worktree": str(path)}))
        self.assertIn("task-in-flight", self.blockers(self.report(), "busy"))

    def _task_worktree(self, name, issue, state="COMPLETED"):
        """A worktree whose local agent-task run reached `state` (None: no run at all)."""
        path = self.fixture.add_worktree(name, f"feature/{name}")
        artifacts = self.fixture.root / "artifacts" / issue
        artifacts.mkdir(parents=True, exist_ok=True)
        if state is not None:
            run_dir = artifacts / "runs" / "20260101T000000Z"
            run_dir.mkdir(parents=True)
            (run_dir / "result.json").write_text(json.dumps({"state": state}))
        (artifacts / "run.json").write_text(json.dumps({"issue": issue, "worktree": str(path)}))
        return path

    def test_completed_local_run_still_needs_external_cleanup_approval(self):
        """A terminal LOCAL run says nothing about the external task lifecycle."""
        self._task_worktree("done", "DONE")
        report = self.report()
        self.assertEqual(self.blockers(report, "done"), {"task-cleanup-not-approved"})
        self.assertEqual(self.record(report, "done")["tasks"][0]["issue"], "DONE")
        self.assertFalse(self.record(report, "done")["tasks"][0]["in_flight"])

    def test_absent_local_run_still_needs_external_cleanup_approval(self):
        """No local run at all is unknown external state, not permission to delete."""
        self._task_worktree("norun", "NORUN", state=None)
        self.assertEqual(self.blockers(self.report(), "norun"), {"task-cleanup-not-approved"})

    def test_every_terminal_local_state_still_blocks_without_approval(self):
        for index, state in enumerate(sorted(gc.TERMINAL_RUN_STATES)):
            with self.subTest(state):
                name = f"term{index}"
                self._task_worktree(name, f"TERM-{index}", state=state)
                self.assertIn("task-cleanup-not-approved", self.blockers(self.report(), name))

    def test_external_cleanup_approval_unblocks_a_completed_task(self):
        self._task_worktree("ok", "OK-1")
        code, text = self.run_cli(
            "inventory", "--json", "--min-age-days", "0", "--approve-task-cleanup", "OK-1"
        )
        self.assertEqual(code, 0, text)
        self.assertEqual(self.blockers(json.loads(text), "ok"), set())

    def test_external_cleanup_approval_is_slug_matched(self):
        self._task_worktree("slug", "SPOT-42")
        code, text = self.run_cli(
            "inventory", "--json", "--min-age-days", "0", "--approve-task-cleanup", "spot_42"
        )
        self.assertEqual(self.blockers(json.loads(text), "slug"), set())

    def test_external_cleanup_approval_does_not_leak_to_other_tasks(self):
        self._task_worktree("mine", "MINE-1")
        self._task_worktree("theirs", "THEIRS-1")
        code, text = self.run_cli(
            "inventory", "--json", "--min-age-days", "0", "--approve-task-cleanup", "MINE-1"
        )
        report = json.loads(text)
        self.assertEqual(self.blockers(report, "mine"), set())
        self.assertEqual(self.blockers(report, "theirs"), {"task-cleanup-not-approved"})

    def test_approval_never_overrides_an_in_flight_local_run(self):
        self._task_worktree("both", "BOTH-1", state="RUNNING")
        code, text = self.run_cli(
            "inventory", "--json", "--min-age-days", "0", "--approve-task-cleanup", "BOTH-1"
        )
        self.assertEqual(self.blockers(json.loads(text), "both"), {"task-in-flight"})

    def test_approving_a_protected_task_is_a_usage_error(self):
        code, text = self.run_cli(
            "inventory", "--protect-task", "SPOT-9", "--approve-task-cleanup", "SPOT-9"
        )
        self.assertEqual(code, gc.EXIT_USAGE)
        self.assertIn("both protected and cleanup-approved", text)

    def test_collect_approve_refuses_a_task_without_external_approval(self):
        path = self._task_worktree("pending", "PENDING-1")
        code, text = self.run_cli("collect", "--min-age-days", "0", "--approve")
        self.assertTrue(path.is_dir(), text)
        self.assertIn("task-cleanup-not-approved", text)
        self.assertNotIn("REMOVED", text)

    def test_protected_task_blocks_by_association_and_by_name(self):
        path = self.fixture.add_worktree("keepme", "feature/keepme")
        artifacts = self.fixture.root / "artifacts" / "KEEP-1"
        run_dir = artifacts / "runs" / "20260101T000000Z"
        run_dir.mkdir(parents=True)
        (run_dir / "result.json").write_text(json.dumps({"state": "COMPLETED"}))
        (artifacts / "run.json").write_text(json.dumps({"issue": "KEEP-1", "worktree": str(path)}))
        code, text = self.run_cli("inventory", "--json", "--min-age-days", "0", "--protect-task", "KEEP-1")
        self.assertIn("protected-task", self.blockers(json.loads(text), "keepme"))

        code, text = self.run_cli("inventory", "--json", "--min-age-days", "0", "--protect-task", "keepme")
        self.assertIn("protected-task", self.blockers(json.loads(text), "keepme"))

    def test_protected_worktree_blocks_by_name_and_by_path(self):
        path = self.fixture.add_worktree("pinme", "feature/pinme")
        for value in ("pinme", str(path)):
            code, text = self.run_cli(
                "inventory", "--json", "--min-age-days", "0", "--protect-worktree", value
            )
            self.assertIn("protected-worktree", self.blockers(json.loads(text), "pinme"), value)

    def test_config_file_supplies_protections_and_age(self):
        self.fixture.add_worktree("configured", "feature/configured")
        config = self.fixture.root / "config" / "worktree-gc.json"
        config.write_text(json.dumps({"min_age_days": 0, "protected_worktrees": ["configured"]}))
        code, text = self.run_cli("inventory", "--json")
        report = json.loads(text)
        self.assertEqual(report["min_age_days"], 0.0)
        self.assertIn("protected-worktree", self.blockers(report, "configured"))

    def test_unreadable_config_is_a_usage_error(self):
        (self.fixture.root / "config" / "worktree-gc.json").write_text("{oops")
        code, text = self.run_cli("inventory")
        self.assertEqual(code, gc.EXIT_USAGE)
        self.assertIn("unreadable", text)

    def test_unknown_config_key_is_warned_about(self):
        (self.fixture.root / "config" / "worktree-gc.json").write_text(json.dumps({"delete_everything": True}))
        report = self.report()
        self.assertTrue(report["config_warnings"])

    def test_process_holding_worktree_blocks(self):
        path = self.fixture.add_worktree("held", "feature/held")
        gc.scan_processes = lambda *a, **k: gc.ProcessScan(
            holders={"77": [("cwd", str(path), False)]}
        )
        self.assertIn("in-use-by-process", self.blockers(self.report(), "held"))

    def test_listener_attached_to_worktree_blocks(self):
        path = self.fixture.add_worktree("preview", "feature/preview")
        gc.scan_processes = lambda *a, **k: gc.ProcessScan(holders={"88": [("cwd", str(path), False)]})
        gc.scan_listeners = lambda *a, **k: gc.ListenerScan(pids={"88"}, details={"88": "php :8514"})
        blockers = self.blockers(self.report(), "preview")
        self.assertIn("listener-attached", blockers)

    def test_systemd_unit_referencing_worktree_blocks(self):
        path = self.fixture.add_worktree("unit", "feature/unit")
        gc.scan_units = lambda *a, **k: gc.UnitScan(
            units=[{"id": "preview.service", "active_state": "inactive",
                    "text": f"WorkingDirectory={path}", "source": "x"}]
        )
        self.assertIn("systemd-unit-associated", self.blockers(self.report(), "unit"))

    def test_scan_failures_block_every_worktree(self):
        self.fixture.add_worktree("scanfail", "feature/scanfail")
        for patch, code in (
            ("scan_processes", "process-scan-failed"),
            ("scan_listeners", "listener-scan-failed"),
            ("scan_units", "unit-scan-failed"),
        ):
            with self.subTest(patch):
                self._restore()
                gc.scan_processes = lambda *a, **k: gc.ProcessScan()
                gc.scan_listeners = lambda *a, **k: gc.ListenerScan()
                gc.scan_units = lambda *a, **k: gc.UnitScan()
                broken = {"scan_processes": gc.ProcessScan(error="boom"),
                          "scan_listeners": gc.ListenerScan(error="boom"),
                          "scan_units": gc.UnitScan(error="boom")}[patch]
                setattr(gc, patch, lambda *a, **k: broken)
                self.assertIn(code, self.blockers(self.report(), "scanfail"))

    # --- process coverage fails closed ----------------------------------

    def _uninspectable_host(self, probe_output=None):
        """Pretend one foreign-uid pid cannot be read, with an optional probe result."""
        gc.scan_processes = lambda *a, **k: gc.ProcessScan(
            unreadable_foreign_pids=["4242"],
            uncovered_pids={"4242": "foreign-uid pid, /proc links unreadable"},
        )
        saved_probe = gc.default_privileged_probe
        gc.default_privileged_probe = (
            (lambda pids: ["printf", "%s", probe_output]) if probe_output
            else (lambda pids: ["false"])
        )
        self.addCleanup(lambda: setattr(gc, "default_privileged_probe", saved_probe))

    def test_uninspectable_pid_blocks_every_worktree(self):
        self.fixture.add_worktree("clean", "feature/clean")
        self._uninspectable_host()
        report = self.report()
        self.assertIn("process-coverage-incomplete", self.blockers(report, "clean"))
        self.assertFalse(report["host"]["process_coverage_complete"])
        self.assertEqual(report["host"]["uncovered_pids"], 1)

    def test_collect_approve_refuses_while_process_coverage_is_incomplete(self):
        path = self.fixture.add_worktree("clean", "feature/clean")
        self._uninspectable_host()
        code, text = self.run_cli("collect", "--min-age-days", "0", "--approve")
        self.assertTrue(path.is_dir(), text)
        self.assertIn("process-coverage-incomplete", text)
        self.assertNotIn("REMOVED", text)

    def test_probe_proving_absence_restores_eligibility(self):
        self.fixture.add_worktree("clean", "feature/clean")
        self._uninspectable_host("REF\t4242\tcwd\t0\t/srv/elsewhere\nPID\t4242\tok\nPROBE-OK\n")
        report = self.report()
        self.assertEqual(self.blockers(report, "clean"), set())
        self.assertTrue(report["host"]["process_coverage_complete"])

    def test_probe_proving_presence_blocks_as_in_use(self):
        path = self.fixture.add_worktree("clean", "feature/clean")
        self._uninspectable_host(f"REF\t4242\tcwd\t0\t{path}\nPID\t4242\tok\nPROBE-OK\n")
        self.assertIn("in-use-by-process", self.blockers(self.report(), "clean"))

    def test_probe_can_be_turned_off_and_then_everything_blocks(self):
        self.fixture.add_worktree("clean", "feature/clean")
        self._uninspectable_host("REF\t4242\tcwd\t0\t/srv/elsewhere\nPID\t4242\tok\nPROBE-OK\n")
        code, text = self.run_cli(
            "inventory", "--json", "--min-age-days", "0", "--no-privileged-process-probe"
        )
        self.assertIn("process-coverage-incomplete", self.blockers(json.loads(text), "clean"))

    def test_strict_mode_blocks_even_when_the_probe_proved_absence(self):
        self.fixture.add_worktree("clean", "feature/clean")
        self._uninspectable_host("REF\t4242\tcwd\t0\t/srv/elsewhere\nPID\t4242\tok\nPROBE-OK\n")
        code, text = self.run_cli(
            "inventory", "--json", "--min-age-days", "0", "--strict-process-scan"
        )
        self.assertIn("process-scan-incomplete", self.blockers(json.loads(text), "clean"))

    def test_worktree_lock_blocks(self):
        import fcntl
        import hashlib

        path = self.fixture.add_worktree("locked", "feature/locked")
        digest = hashlib.sha256(str(path).encode()).hexdigest()
        lock_file = self.fixture.root / "locks" / f"{digest}.lock"
        lock_file.write_text("")
        handle = open(lock_file, "a")
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        self.addCleanup(handle.close)
        self.assertIn("worktree-lock-held", self.blockers(self.report(), "locked"))

    # --- collect --------------------------------------------------------

    def test_collect_without_approve_removes_nothing(self):
        path = self.fixture.add_worktree("clean", "feature/clean")
        code, text = self.run_cli("collect", "--min-age-days", "0")
        self.assertEqual(code, 0, text)
        self.assertIn("DRY-RUN", text)
        self.assertTrue(path.is_dir())

    def test_collect_with_approve_removes_only_eligible(self):
        clean = self.fixture.add_worktree("clean", "feature/clean")
        dirty = self.fixture.add_worktree("dirty", "feature/dirty")
        (dirty / "scratch.txt").write_text("notes")
        (clean / "node_modules").mkdir()
        (clean / "node_modules" / "a.js").write_text("//")

        code, text = self.run_cli("collect", "--min-age-days", "0", "--approve")
        self.assertEqual(code, 0, text)
        self.assertFalse(clean.exists(), text)
        self.assertTrue(dirty.is_dir())
        self.assertIn("REMOVED", text)
        self.assertRegex(text, r"estimated tree \d+ inodes")
        self.assertRegex(text, r"observed free-space delta -?\d+ inodes")

    def _collect_json(self, *extra):
        code, text = self.run_cli("collect", "--min-age-days", "0", "--approve", "--json", *extra)
        payload = json.loads(text[text.index("{", text.index("Failed/skipped")):])
        return code, text, payload

    def test_collect_separates_estimates_from_observed_deltas(self):
        self.fixture.add_worktree("clean", "feature/clean")
        code, text, payload = self._collect_json()
        self.assertEqual(code, 0, text)
        self.assertEqual(len(payload["removed"]), 1)
        # Pre-removal measurement is an estimate and is labelled as one.
        self.assertGreater(payload["estimated_inodes"], 0)
        self.assertGreater(payload["estimated_bytes"], 0)
        self.assertNotIn("reclaimed_inodes", payload)
        self.assertNotIn("reclaimed_bytes", payload)
        self.assertEqual(payload["observed_samples"], 1)
        self.assertEqual(payload["observed_unavailable"], 0)
        self.assertIn("f_ffree", payload["observed_delta_caveat"])
        self.assertIn("f_bavail", payload["observed_delta_caveat"])

    def test_observed_delta_is_the_difference_of_statvfs_snapshots(self):
        """Observed values must come from before/after statvfs, not the measurement."""
        self.fixture.add_worktree("clean", "feature/clean")
        saved = gc.fs_free_snapshot
        samples = [
            ({"free_inodes": 1_000, "free_bytes": 8_000}, ""),   # before
            ({"free_inodes": 1_007, "free_bytes": 9_024}, ""),   # after
        ]
        calls = []

        def fake_snapshot(path):
            calls.append(path)
            return samples[min(len(calls) - 1, len(samples) - 1)]

        gc.fs_free_snapshot = fake_snapshot
        self.addCleanup(lambda: setattr(gc, "fs_free_snapshot", saved))
        code, text, payload = self._collect_json()
        self.assertEqual(code, 0, text)
        entry = payload["removed"][0]
        self.assertEqual(entry["observed_free_inode_delta"], 7)     # 1007 - 1000
        self.assertEqual(entry["observed_free_bytes_delta"], 1_024)  # 9024 - 8000
        self.assertEqual(payload["observed_free_inode_delta"], 7)
        self.assertEqual(payload["observed_free_bytes_delta"], 1_024)
        # ...and they are independent of the (much larger) tree estimate.
        self.assertNotEqual(entry["estimated_inodes"], 7)
        # Both snapshots target the same surviving anchor path.
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0], calls[1])
        self.assertTrue(os.path.isdir(calls[0]))

    def test_negative_observed_delta_is_preserved_not_clamped(self):
        """Concurrent allocation can outweigh reclaim; do not fabricate a positive."""
        self.fixture.add_worktree("clean", "feature/clean")
        saved = gc.fs_free_snapshot
        samples = [
            ({"free_inodes": 1_000, "free_bytes": 8_000}, ""),
            ({"free_inodes": 996, "free_bytes": 5_952}, ""),
        ]
        calls = []

        def fake_snapshot(path):
            calls.append(path)
            return samples[min(len(calls) - 1, len(samples) - 1)]

        gc.fs_free_snapshot = fake_snapshot
        self.addCleanup(lambda: setattr(gc, "fs_free_snapshot", saved))
        code, text, payload = self._collect_json()
        self.assertEqual(code, 0, text)
        self.assertEqual(payload["observed_free_inode_delta"], -4)
        self.assertEqual(payload["observed_free_bytes_delta"], -2_048)
        self.assertIn("-4 inodes", text)
        self.assertIn("-2.0KiB", text)

    def test_unavailable_statvfs_sample_is_reported_not_guessed(self):
        self.fixture.add_worktree("clean", "feature/clean")
        saved = gc.fs_free_snapshot
        gc.fs_free_snapshot = lambda path: (None, "statvfs boom")
        self.addCleanup(lambda: setattr(gc, "fs_free_snapshot", saved))
        code, text, payload = self._collect_json()
        self.assertEqual(code, 0, text)
        entry = payload["removed"][0]
        self.assertIsNone(entry["observed_free_inode_delta"])
        self.assertIsNone(entry["observed_free_bytes_delta"])
        self.assertEqual(entry["observed_error"], "statvfs boom")
        self.assertEqual(payload["observed_samples"], 0)
        self.assertEqual(payload["observed_unavailable"], 1)
        self.assertIn("observed delta unavailable", text)

    def test_collect_preserves_branch_and_commits(self):
        self.fixture.add_worktree("merged", "feature/merged", merged=True, commit=True)
        head = run_git("rev-parse", "feature/merged", cwd=self.fixture.repo).strip()
        code, text = self.run_cli("collect", "--min-age-days", "0", "--approve")
        self.assertEqual(code, 0, text)
        self.assertEqual(run_git("rev-parse", "feature/merged", cwd=self.fixture.repo).strip(), head)
        self.assertIn("feature/merged", run_git("branch", "--list", cwd=self.fixture.repo))

    def test_collect_never_touches_the_main_worktree(self):
        code, text = self.run_cli(
            "collect", "--min-age-days", "0", "--approve", "--worktree", str(self.fixture.repo)
        )
        self.assertTrue((self.fixture.repo / "README").exists())
        self.assertIn("outside-managed-root", text)

    def test_collect_rechecks_immediately_before_removing(self):
        """A worktree that goes dirty after the report is skipped, not removed."""
        path = self.fixture.add_worktree("racy", "feature/racy")
        saved = gc.git_status_entries
        calls = {"n": 0}

        def racing_status(worktree):
            calls["n"] += 1
            if calls["n"] == 1:
                return saved(worktree)  # clean during the planning report
            return ["?? raced.txt"], ""  # dirty by the time of the recheck

        gc.git_status_entries = racing_status
        self.addCleanup(lambda: setattr(gc, "git_status_entries", saved))
        code, text = self.run_cli("collect", "--min-age-days", "0", "--approve")
        self.assertTrue(path.is_dir(), text)
        self.assertIn("recheck blocked", text)
        self.assertEqual(code, gc.EXIT_FAILURE)

    # --- the removal lock (time-of-check/time-of-use) --------------------

    def test_collect_holds_the_lock_through_measurement_and_removal(self):
        """The flock is taken before the final check and held until removal returns."""
        path = self.fixture.add_worktree("clean", "feature/clean")
        lock_files = gc.lock_files_for(self.fixture.root, str(path))
        seen = {}

        saved_measure, saved_remove = gc.measure_tree, gc.remove_worktree

        def watched_measure(target):
            seen["at_measure"] = [competitor_can_lock(f) for f in lock_files]
            return saved_measure(target)

        def watched_remove(repo, target):
            seen["before_remove"] = [competitor_can_lock(f) for f in lock_files]
            result = saved_remove(repo, target)
            seen["after_remove"] = [competitor_can_lock(f) for f in lock_files]
            return result

        gc.measure_tree, gc.remove_worktree = watched_measure, watched_remove
        self.addCleanup(lambda: setattr(gc, "measure_tree", saved_measure))
        self.addCleanup(lambda: setattr(gc, "remove_worktree", saved_remove))

        code, text = self.run_cli("collect", "--min-age-days", "0", "--approve")
        self.assertEqual(code, 0, text)
        self.assertFalse(path.exists(), text)
        # No competing writer could take the lock at any point in the window...
        self.assertEqual(seen["at_measure"], [False] * len(lock_files))
        self.assertEqual(seen["before_remove"], [False] * len(lock_files))
        self.assertEqual(seen["after_remove"], [False] * len(lock_files))
        # ...and it is released once collect is done.
        for lock_file in lock_files:
            self.assertTrue(competitor_can_lock(lock_file), lock_file)

    def test_a_writer_appearing_after_the_plan_stops_the_removal(self):
        """The exact race the lock closes: agent-task starts between plan and delete."""
        path = self.fixture.add_worktree("racy", "feature/racy")
        lock_file = gc.lock_files_for(self.fixture.root, str(path))[0]
        saved = gc.build_report
        holders = []

        def planning_then_a_writer_appears(*args, **kwargs):
            report = saved(*args, **kwargs)
            if not holders:  # right after the planning report, before the loop
                child = subprocess.Popen(
                    [sys.executable, "-c", HOLD_LOCK_SOURCE, str(lock_file)],
                    stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True,
                )
                self.assertEqual(child.stdout.readline().strip(), "LOCKED")
                holders.append(child)
            return report

        gc.build_report = planning_then_a_writer_appears
        self.addCleanup(lambda: setattr(gc, "build_report", saved))

        code, text = self.run_cli("collect", "--min-age-days", "0", "--approve")
        for child in holders:
            child.stdin.close()
            child.wait(timeout=30)
            child.stdout.close()
        self.assertTrue(path.is_dir(), text)
        self.assertIn("could not take the worktree lock", text)
        self.assertNotIn("REMOVED", text)
        self.assertEqual(code, gc.EXIT_FAILURE)

    def test_collect_removes_with_plain_git_worktree_remove(self):
        path = self.fixture.add_worktree("clean", "feature/clean")
        saved = gc.git
        commands = []

        def recording_git(args, **kwargs):
            commands.append(list(args))
            return saved(args, **kwargs)

        gc.git = recording_git
        self.addCleanup(lambda: setattr(gc, "git", saved))
        code, text = self.run_cli("collect", "--min-age-days", "0", "--approve")
        self.assertFalse(path.exists(), text)
        removals = [c for c in commands if "worktree" in c and "remove" in c]
        self.assertEqual(len(removals), 1, commands)
        self.assertNotIn("--force", removals[0])
        self.assertNotIn("-f", removals[0])

    def test_collect_requires_fresh_remote_refs(self):
        self.fixture.add_worktree("clean", "feature/clean")
        saved = gc.fetch_repo
        gc.fetch_repo = lambda repo: (False, "network unreachable")
        self.addCleanup(lambda: setattr(gc, "fetch_repo", saved))
        code, text = self.run_cli("collect", "--min-age-days", "0", "--approve")
        self.assertIn("fetch-failed", text)
        self.assertTrue((self.fixture.root / "worktrees" / "clean").is_dir())


class InodeCheckTest(unittest.TestCase):
    def run_check(self, *argv, status=None):
        saved = gc.inode_status
        if status is not None:
            gc.inode_status = lambda path: (status, "")
        out, err = io.StringIO(), io.StringIO()
        try:
            with redirect_stdout(out), redirect_stderr(err):
                code = gc.main(["inode-check", *argv])
        finally:
            gc.inode_status = saved
        return code, out.getvalue() + err.getvalue()

    def status(self, inode_percent, byte_percent=0.0):
        return {
            "path": "/", "inodes_total": 1000, "inodes_used": int(inode_percent * 10),
            "inodes_free": 1000 - int(inode_percent * 10), "inodes_used_percent": inode_percent,
            "bytes_total": 1000, "bytes_used": int(byte_percent * 10), "bytes_free": 1000,
            "bytes_used_percent": byte_percent,
        }

    def test_thresholds_map_to_monitoring_exit_codes(self):
        for percent, expected in ((10.0, gc.CHECK_OK), (85.0, gc.CHECK_WARN), (95.0, gc.CHECK_CRITICAL)):
            code, text = self.run_check(status=self.status(percent))
            self.assertEqual(code, expected, text)

    def test_space_pressure_alone_triggers_the_alert(self):
        code, _ = self.run_check(status=self.status(5.0, 95.0))
        self.assertEqual(code, gc.CHECK_CRITICAL)

    def test_custom_thresholds(self):
        code, _ = self.run_check("--warn-percent", "50", "--critical-percent", "60",
                                 status=self.status(55.0))
        self.assertEqual(code, gc.CHECK_WARN)

    def test_inverted_thresholds_are_unknown(self):
        code, text = self.run_check("--warn-percent", "95", "--critical-percent", "50",
                                    status=self.status(10.0))
        self.assertEqual(code, gc.CHECK_UNKNOWN)

    def test_unreadable_path_is_unknown_not_ok(self):
        code, text = self.run_check("--path", "/nonexistent-worktree-gc-path")
        self.assertEqual(code, gc.CHECK_UNKNOWN)
        self.assertIn("UNKNOWN", text)

    def test_quiet_suppresses_ok_but_not_alerts(self):
        code, text = self.run_check("--quiet", status=self.status(10.0))
        self.assertEqual((code, text), (gc.CHECK_OK, ""))
        code, text = self.run_check("--quiet", status=self.status(95.0))
        self.assertEqual(code, gc.CHECK_CRITICAL)
        self.assertIn("CRITICAL", text)

    def test_json_output_carries_level_and_exit_code(self):
        code, text = self.run_check("--json", status=self.status(85.0))
        payload = json.loads(text)
        self.assertEqual((payload["level"], payload["exit_code"]), ("WARN", gc.CHECK_WARN))

    def test_live_filesystem_reports_plausible_numbers(self):
        status, error = gc.inode_status(str(REPO_ROOT))
        self.assertEqual(error, "")
        self.assertGreater(status["inodes_total"], 0)
        self.assertGreaterEqual(status["inodes_used_percent"], 0.0)
        self.assertLessEqual(status["inodes_used_percent"], 100.0)


class CliSurfaceTest(unittest.TestCase):
    def test_script_is_executable_and_defaults_to_inventory(self):
        self.assertTrue(os.access(SCRIPT, os.X_OK))
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "worktrees").mkdir()
            proc = subprocess.run([str(SCRIPT), "--root", tmp], capture_output=True, text=True)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertIn("dry-run, read-only", proc.stdout)

    def test_help_documents_the_approval_gate(self):
        proc = subprocess.run([str(SCRIPT), "--help"], capture_output=True, text=True)
        self.assertIn("--approve to delete", proc.stdout)

    def test_missing_worktrees_directory_is_a_usage_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            proc = subprocess.run([str(SCRIPT), "--root", tmp, "inventory"], capture_output=True, text=True)
            self.assertEqual(proc.returncode, gc.EXIT_USAGE)

    def test_negative_min_age_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "worktrees").mkdir()
            proc = subprocess.run(
                [str(SCRIPT), "--root", tmp, "inventory", "--min-age-days", "-1"],
                capture_output=True, text=True,
            )
            self.assertEqual(proc.returncode, gc.EXIT_USAGE)


if __name__ == "__main__":
    unittest.main(verbosity=2)

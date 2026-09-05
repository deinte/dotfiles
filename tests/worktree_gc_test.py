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

    def test_task_id_is_inferred_from_a_task_named_worktree(self):
        # The live counterexample: basename is the Kanban task id itself.
        self.assertEqual(gc.task_id_from_worktree_name("t_35c15c8a"), "t_35c15c8a")
        # Suffix worktrees belong to the task they are named after.
        self.assertEqual(gc.task_id_from_worktree_name("t_3626513e-revert"), "t_3626513e")
        self.assertEqual(gc.task_id_from_worktree_name("t_69b6784b-di"), "t_69b6784b")
        self.assertEqual(gc.task_id_from_worktree_name("t_3626513e_revert"), "t_3626513e")
        self.assertEqual(gc.task_id_from_worktree_name("T_3626513E-Revert"), "t_3626513e")

    def test_task_id_inference_does_not_collide_on_prefixes(self):
        # A longer hex run is its own task, never the shorter one's suffix
        # worktree: the hex is greedy and the whole basename must match.
        self.assertEqual(gc.task_id_from_worktree_name("t_3626513eab"), "t_3626513eab")
        self.assertNotEqual(gc.task_id_from_worktree_name("t_3626513eab"), "t_3626513e")
        self.assertNotEqual(gc.task_id_from_worktree_name("t_3626513e"), "t_3626513")

    def test_non_task_worktree_names_are_not_recognised(self):
        # Unrecognised names keep the existing manual worktree-level path.
        for name in ("SPOT-123", "AE-V2-LAUNCH-READINESS", "marvino-demo-t_93841552",
                     "antwerpexpats-v2-t_92fe2b77", "t-b3824a2f-di", "t_", "t_zzzz", "tasks"):
            self.assertEqual(gc.task_id_from_worktree_name(name), "", name)

    def test_merge_globs_is_additive_and_deduplicates(self):
        self.assertEqual(gc.merge_globs([".env"], ["*.pem", ".env"]), [".env", "*.pem"])
        self.assertEqual(gc.merge_globs([".env"], []), [".env"])
        self.assertEqual(gc.merge_globs([".env"], None), [".env"])
        # Built-ins come first and survive every later group.
        merged = gc.merge_globs(gc.DEFAULTS["protected_ignored_globs"], [], ["*.pem"])
        for builtin in gc.DEFAULTS["protected_ignored_globs"]:
            self.assertIn(builtin, merged)
        self.assertIn("*.pem", merged)

    def test_cleanup_name_approvals_are_matched_verbatim(self):
        config = gc.Config(root=Path("/tmp"), task_cleanup_approved=["SK-123", " SAL-45 "])
        self.assertEqual(config.approved_cleanup_names, {"SK-123", "SAL-45"})
        # Not slug-folded: a directory name is compared exactly, so neither a
        # case variant nor a prefix of an approval is covered by it.
        for name in ("sk-123", "SK-12", "SK-1234", "sk_123"):
            self.assertNotIn(name, config.approved_cleanup_names, name)

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


class ReadLinkClassificationTest(unittest.TestCase):
    """ENOENT is an ordinary race; every other error is a failure to inspect."""

    def test_readable_link_is_returned(self):
        with tempfile.TemporaryDirectory() as tmp:
            os.symlink("/srv/x", os.path.join(tmp, "link"))
            self.assertEqual(gc._read_link(os.path.join(tmp, "link")), ("/srv/x", ""))

    def test_missing_link_is_a_disappearance_not_a_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(gc._read_link(os.path.join(tmp, "gone")), (None, ""))

    def test_a_non_symlink_is_a_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "regular").write_text("x")
            target, failure = gc._read_link(os.path.join(tmp, "regular"))
            self.assertIsNone(target)
            self.assertIn("regular", failure)

    @unittest.skipIf(os.getuid() == 0, "root bypasses directory permissions")
    def test_permission_denied_is_a_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            closed = Path(tmp) / "closed"
            closed.mkdir()
            os.symlink("/srv/x", closed / "link")
            os.chmod(closed, 0o000)
            try:
                target, failure = gc._read_link(str(closed / "link"))
            finally:
                os.chmod(closed, 0o700)
            self.assertIsNone(target)
            self.assertIn("Permission denied", failure)


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

    def test_a_listed_fd_that_cannot_be_resolved_leaves_the_pid_uncovered(self):
        """A partial read is not coverage: that fd could point into a candidate."""
        with tempfile.TemporaryDirectory() as tmp:
            proc = Path(tmp) / "proc"
            proc.mkdir()
            pid_dir = self._fake_proc(proc, 500, cwd="/tmp")
            (pid_dir / "fd" / "7").write_text("not a symlink")  # readlink -> EINVAL
            scan = gc.scan_processes(str(proc))
            self.assertFalse(scan.coverage_complete)
            self.assertIn("fd/7", scan.uncovered_pids["500"])

    def test_fd_readlink_permission_error_leaves_the_pid_uncovered(self):
        """Real /proc denies a foreign fd with EACCES; a fixture cannot chown,
        so the error is injected at the readlink boundary the scan calls."""
        with tempfile.TemporaryDirectory() as tmp:
            proc = Path(tmp) / "proc"
            proc.mkdir()
            worktree = Path(tmp) / "wt"
            worktree.mkdir()
            pid_dir = self._fake_proc(
                proc, 600, cwd="/tmp", fds=[(str(worktree / "f"), os.O_RDWR)]
            )
            denied = str(pid_dir / "fd" / "0")
            saved = gc._read_link
            gc._read_link = lambda path: (
                (None, f"{path}: [Errno 13] Permission denied") if path == denied else saved(path)
            )
            self.addCleanup(lambda: setattr(gc, "_read_link", saved))
            scan = gc.scan_processes(str(proc))
            # The fd is not in holders (we never learned its target) - which is
            # exactly why the pid must stay uncovered instead of reading clean.
            self.assertEqual(gc.processes_using(scan, {str(worktree)}), [])
            self.assertFalse(scan.coverage_complete)
            self.assertIn("Permission denied", scan.uncovered_pids["600"])

    def test_fd_closed_between_listing_and_reading_is_not_a_blocker(self):
        """The ordinary close race must not turn into a permanent blocker."""
        with tempfile.TemporaryDirectory() as tmp:
            proc = Path(tmp) / "proc"
            proc.mkdir()
            self._fake_proc(proc, 700, cwd="/tmp")
            saved = os.listdir

            def phantom_fd(path, *args, **kwargs):
                entries = saved(path, *args, **kwargs)
                if str(path).endswith("/700/fd"):
                    return [*entries, "9"]  # listed, then closed before readlink
                return entries

            os.listdir = phantom_fd
            self.addCleanup(lambda: setattr(os, "listdir", saved))
            scan = gc.scan_processes(str(proc))
            self.assertEqual(scan.uncovered_pids, {})
            self.assertTrue(scan.coverage_complete)

    def test_a_process_without_an_exe_link_is_still_covered(self):
        """A kernel thread has no exe; ENOENT there leaves nothing unproven."""
        with tempfile.TemporaryDirectory() as tmp:
            proc = Path(tmp) / "proc"
            proc.mkdir()
            (self._fake_proc(proc, 800, cwd="/tmp") / "exe").unlink()
            self.assertEqual(gc.scan_processes(str(proc)).uncovered_pids, {})

    def test_an_unresolvable_exe_link_leaves_the_pid_uncovered(self):
        with tempfile.TemporaryDirectory() as tmp:
            proc = Path(tmp) / "proc"
            proc.mkdir()
            pid_dir = self._fake_proc(proc, 900, cwd="/tmp")
            (pid_dir / "exe").unlink()
            (pid_dir / "exe").write_text("not a symlink")
            self.assertIn("900", gc.scan_processes(str(proc)).uncovered_pids)

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
        """A pid whose cwd/root/exe cannot be resolved, owned by another uid.

        Real /proc refuses these with EACCES. A fixture cannot chown, so the
        entries are made unresolvable for another non-ENOENT reason (readlink on
        a regular file fails with EINVAL); the classification under test keys on
        "not a disappearance", not on the specific errno. The EACCES case itself
        is covered by ReadLinkClassificationTest.
        """
        pid_dir = Path(tmp) / str(pid)
        (pid_dir / "fd").mkdir(parents=True)
        (pid_dir / "fdinfo").mkdir()
        for kind in ("cwd", "root", "exe"):
            (pid_dir / kind).write_text("not a symlink")
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

    def test_probe_output_with_an_unparsable_line_clears_nothing(self):
        """Output we cannot fully understand is discarded, not partly believed."""
        scan = gc.resolve_process_coverage(
            self._uncovered(),
            probe=self._canned_probe(
                "REF\t4242\tcwd\t0\t/srv/other\nsudo: something went sideways\n"
                "PID\t4242\tok\nPROBE-OK\n"
            ),
        )
        self.assertFalse(scan.coverage_complete)
        self.assertIn("not understood", scan.probe)

    def test_a_pid_with_references_but_no_final_status_stays_uncovered(self):
        """Truncated per-pid output is partial coverage, which is no coverage."""
        scan = gc.resolve_process_coverage(
            self._uncovered(),
            probe=self._canned_probe("REF\t4242\tcwd\t0\t/srv/other\nPROBE-OK\n"),
        )
        self.assertFalse(scan.coverage_complete)
        self.assertIn("4242", scan.uncovered_pids)

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
        self.assertEqual(command[-3:], ["/proc", "1", "2"])
        source = gc.PRIVILEGED_PROBE_SOURCE
        for forbidden in ("os.remove", "os.kill", "shutil", "subprocess", '"w"', "'w'"):
            self.assertNotIn(forbidden, source, forbidden)

    def test_probe_source_runs_and_reports_this_process(self):
        """The probe body is executed for real against the live /proc."""
        proc = subprocess.run(
            [sys.executable, "-c", gc.PRIVILEGED_PROBE_SOURCE, "/proc",
             str(os.getpid()), "999999999"],
            capture_output=True, text=True,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        lines = proc.stdout.splitlines()
        self.assertEqual(lines[-1], gc.PROBE_SENTINEL)
        self.assertIn(f"PID\t{os.getpid()}\tok", lines)
        self.assertIn("PID\t999999999\tgone", lines)
        self.assertTrue(any(line.startswith(f"REF\t{os.getpid()}\tcwd\t0\t") for line in lines))


class ProbeSourceTest(unittest.TestCase):
    """The privileged probe body, executed for real against a fixture proc root.

    Its status must make the same disappearance/failure distinction the
    unprivileged scan makes, on every required reference including exe and each
    individual fd - a `PID ... ok` emitted after a reference it could not read
    would be a false proof of absence.
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.proc = Path(self._tmp.name) / "proc"
        self.proc.mkdir()

    def _pid(self, pid, cwd="/tmp"):
        pid_dir = self.proc / str(pid)
        (pid_dir / "fd").mkdir(parents=True)
        (pid_dir / "fdinfo").mkdir()
        os.symlink(cwd, pid_dir / "cwd")
        os.symlink("/", pid_dir / "root")
        os.symlink("/bin/sh", pid_dir / "exe")
        return pid_dir

    def _add_fd(self, pid_dir, fd, target, flags=os.O_RDWR):
        os.symlink(target, pid_dir / "fd" / str(fd))
        (pid_dir / "fdinfo" / str(fd)).write_text(f"pos:\t0\nflags:\t0{flags:o}\n")

    def _run(self, *pids):
        proc = subprocess.run(
            [sys.executable, "-c", gc.PRIVILEGED_PROBE_SOURCE, str(self.proc), *pids],
            capture_output=True, text=True,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        lines = proc.stdout.splitlines()
        self.assertEqual(lines[-1], gc.PROBE_SENTINEL)
        return lines

    def test_a_fully_readable_pid_is_ok_and_reports_its_references(self):
        pid_dir = self._pid(11, cwd="/ws/worktrees/x")
        self._add_fd(pid_dir, 3, "/ws/worktrees/x/log")
        lines = self._run("11")
        self.assertIn("PID\t11\tok", lines)
        self.assertIn("REF\t11\tcwd\t0\t/ws/worktrees/x", lines)
        self.assertIn("REF\t11\tfd3\t1\t/ws/worktrees/x/log", lines)

    def test_a_missing_pid_is_gone(self):
        self.assertIn("PID\t12\tgone", self._run("12"))

    def test_an_unreadable_cwd_is_unreadable(self):
        pid_dir = self._pid(13)
        (pid_dir / "cwd").unlink()
        (pid_dir / "cwd").write_text("not a symlink")
        self.assertIn("PID\t13\tunreadable", self._run("13"))

    def test_an_unreadable_exe_is_unreadable(self):
        """Regression: exe failures were ignored, so the pid reported ok."""
        pid_dir = self._pid(14)
        (pid_dir / "exe").unlink()
        (pid_dir / "exe").write_text("not a symlink")
        self.assertIn("PID\t14\tunreadable", self._run("14"))

    def test_a_missing_exe_is_still_ok(self):
        (self._pid(15) / "exe").unlink()
        self.assertIn("PID\t15\tok", self._run("15"))

    def test_an_unreadable_fd_is_unreadable(self):
        """Regression: a single unresolvable fd was skipped and the pid was ok."""
        pid_dir = self._pid(16)
        self._add_fd(pid_dir, 3, "/tmp/fine")
        (pid_dir / "fd" / "4").write_text("not a symlink")
        lines = self._run("16")
        self.assertIn("PID\t16\tunreadable", lines)
        self.assertIn("REF\t16\tfd3\t1\t/tmp/fine", lines)

    def test_an_unreadable_fd_directory_is_unreadable(self):
        pid_dir = self._pid(17)
        (pid_dir / "fd").rmdir()
        (pid_dir / "fd").write_text("not a directory")
        self.assertIn("PID\t17\tunreadable", self._run("17"))

    def test_a_pid_that_exits_mid_probe_reports_only_what_vanished(self):
        """Every reference gone at once is the exit race, not an inspection failure."""
        pid_dir = self._pid(18)
        for kind in ("cwd", "root", "exe"):
            (pid_dir / kind).unlink()
        self.assertIn("PID\t18\tok", self._run("18"))


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
        # No association and no inferable task id, so the basename is the
        # cleanup identity and has to be approved before anything else counts.
        report = self.report("--approve-task-cleanup", "clean")
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
        report = self.report("--approve-task-cleanup", "built")
        self.assertEqual(self.blockers(report, "built"), set())

    def test_ignored_env_file_blocks(self):
        path = self.fixture.add_worktree("secrets", "feature/secrets")
        (path / ".env").write_text("APP_KEY=x")
        self.assertIn("protected-ignored-state", self.blockers(self.report(), "secrets"))

    def test_ignored_sqlite_database_blocks(self):
        path = self.fixture.add_worktree("db", "feature/db")
        (path / "database.sqlite").write_text("")
        self.assertIn("protected-ignored-state", self.blockers(self.report(), "db"))

    # --- built-in ignored-state protection is an invariant, not a default --
    # `protected_ignored_globs` in the config file ADDS to the built-ins. An
    # empty or narrowed list must not expose credentials or databases.

    def test_empty_ignored_glob_config_cannot_disable_the_builtins(self):
        path = self.fixture.add_worktree("secrets", "feature/secrets")
        (path / ".env").write_text("APP_KEY=x")
        (self.fixture.root / "config" / "worktree-gc.json").write_text(
            json.dumps({"protected_ignored_globs": []})
        )
        report = self.report("--approve-task-cleanup", "secrets")
        self.assertIn("protected-ignored-state", self.blockers(report, "secrets"))

    def test_custom_ignored_glob_config_cannot_disable_the_builtins(self):
        db = self.fixture.add_worktree("db", "feature/db")
        (db / "database.sqlite").write_text("")
        (self.fixture.root / "config" / "worktree-gc.json").write_text(
            json.dumps({"protected_ignored_globs": ["*.pem"]})
        )
        report = self.report("--approve-task-cleanup", "db")
        self.assertIn("protected-ignored-state", self.blockers(report, "db"))

    def test_custom_ignored_globs_still_add_protection(self):
        path = self.fixture.add_worktree("certs", "feature/certs")
        (path / ".gitignore").write_text("local.pem\n")
        run_git("add", "-A", cwd=path)
        run_git("commit", "-qm", "ignore pem", cwd=path)
        (path / "local.pem").write_text("-----BEGIN PRIVATE KEY-----")
        # Not built-in: without the custom glob this is ordinary ignored output.
        self.assertNotIn(
            "protected-ignored-state",
            self.blockers(self.report("--approve-task-cleanup", "certs"), "certs"),
        )
        (self.fixture.root / "config" / "worktree-gc.json").write_text(
            json.dumps({"protected_ignored_globs": ["*.pem"]})
        )
        report = self.report("--approve-task-cleanup", "certs")
        self.assertIn("protected-ignored-state", self.blockers(report, "certs"))

    def test_unmerged_commit_blocks(self):
        self.fixture.add_worktree("ahead", "feature/ahead", merged=False, commit=True)
        self.assertIn("not-merged", self.blockers(self.report(), "ahead"))

    def test_merged_commit_is_eligible(self):
        self.fixture.add_worktree("merged", "feature/merged", merged=True, commit=True)
        self.assertEqual(
            self.blockers(self.report("--approve-task-cleanup", "merged"), "merged"), set()
        )

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

    # --- task-named worktrees without any local metadata ----------------
    # Regression for the live counterexample: worktree t_35c15c8a reported
    # tasks: [] because its artifacts/runs metadata was absent, while Kanban
    # task t_35c15c8a was still blocked. Missing metadata must not drop the
    # external-state gate for a worktree that is named after a task.

    def test_task_named_worktree_without_metadata_is_blocked(self):
        self.fixture.add_worktree("t_35c15c8a", "feature/t_35c15c8a")
        report = self.report()
        record = self.record(report, "t_35c15c8a")
        # No artifact/run file associates this worktree with anything; the gate
        # now comes from the name alone.
        self.assertEqual([task["source"] for task in record["tasks"]], ["worktree-name"])
        self.assertEqual(self.blockers(report, "t_35c15c8a"), {"task-cleanup-not-approved"})
        self.assertFalse(record["eligible"])

    def test_task_named_worktree_without_metadata_reports_the_inferred_task(self):
        self.fixture.add_worktree("t_35c15c8a", "feature/t_35c15c8a")
        record = self.record(self.report(), "t_35c15c8a")
        self.assertEqual(record["inferred_task"], "t_35c15c8a")
        self.assertEqual([task["issue"] for task in record["tasks"]], ["t_35c15c8a"])
        self.assertEqual(record["tasks"][0]["source"], "worktree-name")
        self.assertFalse(record["tasks"][0]["in_flight"])

    def test_approving_the_inferred_task_clears_the_external_state_gate(self):
        self.fixture.add_worktree("t_35c15c8a", "feature/t_35c15c8a")
        code, text = self.run_cli(
            "inventory", "--json", "--min-age-days", "0", "--approve-task-cleanup", "t_35c15c8a"
        )
        self.assertEqual(code, 0, text)
        self.assertEqual(self.blockers(json.loads(text), "t_35c15c8a"), set())

    def test_approval_reaches_recognised_suffix_worktrees_of_the_same_task(self):
        self.fixture.add_worktree("t_3626513e", "feature/t_3626513e")
        self.fixture.add_worktree("t_3626513e-revert", "feature/t_3626513e-revert")
        report = self.report()
        for name in ("t_3626513e", "t_3626513e-revert"):
            self.assertEqual(self.blockers(report, name), {"task-cleanup-not-approved"}, name)
        code, text = self.run_cli(
            "inventory", "--json", "--min-age-days", "0", "--approve-task-cleanup", "t_3626513e"
        )
        approved = json.loads(text)
        self.assertEqual(self.record(approved, "t_3626513e-revert")["inferred_task"], "t_3626513e")
        for name in ("t_3626513e", "t_3626513e-revert"):
            self.assertEqual(self.blockers(approved, name), set(), name)

    def test_approval_does_not_leak_to_prefix_collision_task_ids(self):
        self.fixture.add_worktree("t_3626513eab", "feature/t_3626513eab")
        self.fixture.add_worktree("t_3626513", "feature/t_3626513")
        code, text = self.run_cli(
            "inventory", "--json", "--min-age-days", "0", "--approve-task-cleanup", "t_3626513e"
        )
        report = json.loads(text)
        for name in ("t_3626513eab", "t_3626513"):
            self.assertEqual(self.blockers(report, name), {"task-cleanup-not-approved"}, name)

    def test_config_approval_also_clears_the_inferred_task_gate(self):
        self.fixture.add_worktree("t_35c15c8a", "feature/t_35c15c8a")
        (self.fixture.root / "config" / "worktree-gc.json").write_text(
            json.dumps({"task_cleanup_approved": ["t_35c15c8a"]})
        )
        self.assertEqual(self.blockers(self.report(), "t_35c15c8a"), set())

    def test_inferred_task_is_not_duplicated_when_metadata_exists(self):
        self._task_worktree("t_35c15c8a", "t_35c15c8a")
        record = self.record(self.report(), "t_35c15c8a")
        self.assertEqual([task["issue"] for task in record["tasks"]], ["t_35c15c8a"])
        self.assertEqual(record["tasks"][0]["source"].endswith("run.json"), True)

    def test_inferred_task_is_added_alongside_an_unrelated_association(self):
        """A named issue association and a task-named worktree both gate."""
        self._task_worktree("t_35c15c8a", "SPOT-123")
        report = self.report()
        record = self.record(report, "t_35c15c8a")
        self.assertEqual(
            sorted(task["issue"] for task in record["tasks"]), ["SPOT-123", "t_35c15c8a"]
        )
        code, text = self.run_cli(
            "inventory", "--json", "--min-age-days", "0", "--approve-task-cleanup", "SPOT-123"
        )
        self.assertEqual(self.blockers(json.loads(text), "t_35c15c8a"), {"task-cleanup-not-approved"})
        code, text = self.run_cli(
            "inventory", "--json", "--min-age-days", "0",
            "--approve-task-cleanup", "SPOT-123", "--approve-task-cleanup", "t_35c15c8a",
        )
        self.assertEqual(self.blockers(json.loads(text), "t_35c15c8a"), set())

    def test_protected_task_also_covers_a_recognised_suffix_worktree(self):
        self.fixture.add_worktree("t_3626513e-revert", "feature/t_3626513e-revert")
        code, text = self.run_cli(
            "inventory", "--json", "--min-age-days", "0", "--protect-task", "t_3626513e"
        )
        self.assertIn("protected-task", self.blockers(json.loads(text), "t_3626513e-revert"))

    def test_unrecognised_worktree_name_is_gated_on_its_own_basename(self):
        """Documented boundary: names that only contain a task id are not inferred.

        Inference stays narrow, but the worktree does not fall out of the gate:
        with no association and no inferable task id, the basename itself is the
        cleanup identity and must be approved verbatim.
        """
        self.fixture.add_worktree("marvino-demo-t_93841552", "feature/marvino")
        report = self.report()
        record = self.record(report, "marvino-demo-t_93841552")
        self.assertEqual(record["inferred_task"], "")
        self.assertEqual(record["cleanup_identity"], "marvino-demo-t_93841552")
        self.assertEqual(
            self.blockers(report, "marvino-demo-t_93841552"), {"worktree-cleanup-not-approved"}
        )

    # --- worktrees with no association and no inferable task id ----------
    # Real agent-task names are not only `t_<hex>`: `SK-123`, `SPOT-123`,
    # `SAL-45`, arbitrary task keys and plain topic names all occur, and any of
    # them can be missing artifacts/runs metadata. None of them may lose the
    # external-state gate; the basename becomes the cleanup identity instead.

    def test_task_key_worktree_without_metadata_is_blocked(self):
        self.fixture.add_worktree("SK-123", "feature/sk-123")
        report = self.report()
        record = self.record(report, "SK-123")
        # Nothing local names this worktree, so the identity is synthesised
        # from the basename rather than read from artifacts/runs metadata.
        self.assertEqual(record["inferred_task"], "")
        self.assertEqual(record["cleanup_identity"], "SK-123")
        self.assertEqual([task["source"] for task in record["tasks"]], ["worktree-name-fallback"])
        self.assertFalse(record["eligible"])
        self.assertEqual(self.blockers(report, "SK-123"), {"worktree-cleanup-not-approved"})

    def test_topic_named_worktree_without_metadata_is_blocked(self):
        self.fixture.add_worktree("payments-spike", "feature/payments-spike")
        report = self.report()
        self.assertEqual(
            self.blockers(report, "payments-spike"), {"worktree-cleanup-not-approved"}
        )
        self.assertFalse(self.record(report, "payments-spike")["eligible"])

    def test_synthesised_identity_is_reported_as_the_cleanup_identity(self):
        self.fixture.add_worktree("SPOT-999", "feature/spot-999")
        record = self.record(self.report(), "SPOT-999")
        self.assertEqual(record["cleanup_identity"], "SPOT-999")
        self.assertEqual([task["issue"] for task in record["tasks"]], ["SPOT-999"])
        self.assertEqual(record["tasks"][0]["source"], "worktree-name-fallback")
        self.assertFalse(record["tasks"][0]["in_flight"])

    def test_exact_basename_approval_unblocks_only_that_worktree(self):
        self.fixture.add_worktree("SK-123", "feature/sk-123")
        self.fixture.add_worktree("SAL-45", "feature/sal-45")
        self.fixture.add_worktree("payments-spike", "feature/payments-spike")
        report = self.report("--approve-task-cleanup", "SK-123")
        self.assertEqual(self.blockers(report, "SK-123"), set())
        self.assertTrue(self.record(report, "SK-123")["eligible"])
        for name in ("SAL-45", "payments-spike"):
            self.assertEqual(self.blockers(report, name), {"worktree-cleanup-not-approved"}, name)

    def test_basename_approval_does_not_leak_across_prefix_collisions(self):
        """Approving `SK-12` must not cover `SK-123`, and vice versa."""
        for name in ("SK-12", "SK-123", "SK-1234"):
            self.fixture.add_worktree(name, f"feature/{name.lower()}")
        report = self.report("--approve-task-cleanup", "SK-12")
        self.assertEqual(self.blockers(report, "SK-12"), set())
        for name in ("SK-123", "SK-1234"):
            self.assertEqual(self.blockers(report, name), {"worktree-cleanup-not-approved"}, name)

    def test_config_approval_also_clears_the_synthesised_identity_gate(self):
        self.fixture.add_worktree("SK-123", "feature/sk-123")
        (self.fixture.root / "config" / "worktree-gc.json").write_text(
            json.dumps({"task_cleanup_approved": ["SK-123"]})
        )
        self.assertEqual(self.blockers(self.report(), "SK-123"), set())

    def test_collect_approve_alone_never_removes_an_unassociated_worktree(self):
        """`--approve` authorises deletion; it never supplies the missing identity."""
        path = self.fixture.add_worktree("SK-123", "feature/sk-123")
        code, text = self.run_cli("collect", "--min-age-days", "0", "--approve")
        self.assertTrue(path.is_dir(), text)
        self.assertIn("worktree-cleanup-not-approved", text)
        self.assertNotIn("REMOVED", text)

    def test_collect_approve_removes_only_the_exactly_approved_basename(self):
        approved = self.fixture.add_worktree("SK-123", "feature/sk-123")
        other = self.fixture.add_worktree("SK-1234", "feature/sk-1234")
        code, text = self.run_cli(
            "collect", "--min-age-days", "0", "--approve", "--approve-task-cleanup", "SK-123"
        )
        self.assertEqual(code, 0, text)
        self.assertFalse(approved.exists(), text)
        self.assertTrue(other.is_dir(), text)

    def test_protected_worktree_still_wins_over_a_basename_approval(self):
        self.fixture.add_worktree("SK-123", "feature/sk-123")
        report = self.report("--approve-task-cleanup", "SK-123", "--protect-worktree", "SK-123")
        self.assertEqual(self.blockers(report, "SK-123"), {"protected-worktree"})

    def test_collect_approve_refuses_a_task_named_worktree_without_approval(self):
        path = self.fixture.add_worktree("t_35c15c8a", "feature/t_35c15c8a")
        code, text = self.run_cli("collect", "--min-age-days", "0", "--approve")
        self.assertTrue(path.is_dir(), text)
        self.assertIn("task-cleanup-not-approved", text)
        self.assertNotIn("REMOVED", text)

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
        report = self.report("--approve-task-cleanup", "clean")
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
        code, text = self.run_cli(
            "collect", "--min-age-days", "0", "--approve-task-cleanup", "clean"
        )
        self.assertEqual(code, 0, text)
        self.assertIn("DRY-RUN", text)
        self.assertTrue(path.is_dir())

    def test_collect_with_approve_removes_only_eligible(self):
        clean = self.fixture.add_worktree("clean", "feature/clean")
        dirty = self.fixture.add_worktree("dirty", "feature/dirty")
        (dirty / "scratch.txt").write_text("notes")
        (clean / "node_modules").mkdir()
        (clean / "node_modules" / "a.js").write_text("//")

        code, text = self.run_cli(
            "collect", "--min-age-days", "0", "--approve",
            "--approve-task-cleanup", "clean", "--approve-task-cleanup", "dirty",
        )
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
        code, text, payload = self._collect_json("--approve-task-cleanup", "clean")
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
        code, text, payload = self._collect_json("--approve-task-cleanup", "clean")
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
        code, text, payload = self._collect_json("--approve-task-cleanup", "clean")
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
        code, text, payload = self._collect_json("--approve-task-cleanup", "clean")
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
        code, text = self.run_cli(
            "collect", "--min-age-days", "0", "--approve", "--approve-task-cleanup", "merged"
        )
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
        code, text = self.run_cli(
            "collect", "--min-age-days", "0", "--approve", "--approve-task-cleanup", "racy"
        )
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

        code, text = self.run_cli(
            "collect", "--min-age-days", "0", "--approve", "--approve-task-cleanup", "clean"
        )
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

        code, text = self.run_cli(
            "collect", "--min-age-days", "0", "--approve", "--approve-task-cleanup", "racy"
        )
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
        code, text = self.run_cli(
            "collect", "--min-age-days", "0", "--approve", "--approve-task-cleanup", "clean"
        )
        self.assertFalse(path.exists(), text)
        removals = [c for c in commands if "worktree" in c and "remove" in c]
        self.assertEqual(len(removals), 1, commands)
        self.assertNotIn("--force", removals[0])
        self.assertNotIn("-f", removals[0])

    # --- the final recheck re-proves reachability ------------------------

    def test_final_recheck_refetches_and_blocks_on_a_changed_remote(self):
        """A remote that moves after planning invalidates the plan's reachability.

        The plan sees HEAD merged into origin's default branch. origin is then
        rewound, exactly as a force-push or a moved default branch would do it.
        The recheck under the lock must fetch again and refuse, instead of
        reusing the reachability proof from the plan.
        """
        base = run_git("rev-parse", "origin/main", cwd=self.fixture.repo).strip()
        path = self.fixture.add_worktree("merged", "feature/merged", merged=True, commit=True)
        saved = gc.build_report
        rewound = []

        def planning_then_the_remote_moves(*args, **kwargs):
            report = saved(*args, **kwargs)
            if not rewound:  # after the planning report, before the removal loop
                run_git("update-ref", "refs/heads/main", base, cwd=self.fixture.origin)
                rewound.append(True)
            return report

        gc.build_report = planning_then_the_remote_moves
        self.addCleanup(lambda: setattr(gc, "build_report", saved))
        code, text = self.run_cli(
            "collect", "--min-age-days", "0", "--approve", "--approve-task-cleanup", "merged"
        )
        self.assertIn("ELIGIBLE merged", text)  # the plan said yes...
        self.assertIn("recheck blocked (not-merged)", text)  # ...the refetch said no
        self.assertTrue(path.is_dir(), text)
        self.assertNotIn("REMOVED", text)
        self.assertEqual(code, gc.EXIT_FAILURE)

    def test_final_recheck_requires_its_own_fetch_to_succeed(self):
        """Freshness blockers are never filtered out of the recheck."""
        path = self.fixture.add_worktree("clean", "feature/clean")
        saved = gc.fetch_repo
        calls = {"n": 0}

        def fetch_then_fail(repo):
            calls["n"] += 1
            return saved(repo) if calls["n"] == 1 else (False, "network unreachable")

        gc.fetch_repo = fetch_then_fail
        self.addCleanup(lambda: setattr(gc, "fetch_repo", saved))
        code, text = self.run_cli(
            "collect", "--min-age-days", "0", "--approve", "--approve-task-cleanup", "clean"
        )
        self.assertIn("recheck blocked (fetch-failed)", text)
        self.assertTrue(path.is_dir(), text)
        self.assertEqual(code, gc.EXIT_FAILURE)

    def test_the_recheck_fetches_and_runs_after_the_tree_measurement(self):
        """Expensive measurement happens first, so it is not inside the
        recheck-to-removal window; the recheck is the last thing before it."""
        self.fixture.add_worktree("clean", "feature/clean")
        order = []
        saved_measure, saved_fetch, saved_remove = gc.measure_tree, gc.fetch_repo, gc.remove_worktree
        gc.measure_tree = lambda target: (order.append("measure"), saved_measure(target))[1]
        gc.fetch_repo = lambda repo: (order.append("fetch"), saved_fetch(repo))[1]
        gc.remove_worktree = lambda repo, target: (order.append("remove"), saved_remove(repo, target))[1]
        self.addCleanup(lambda: setattr(gc, "measure_tree", saved_measure))
        self.addCleanup(lambda: setattr(gc, "fetch_repo", saved_fetch))
        self.addCleanup(lambda: setattr(gc, "remove_worktree", saved_remove))
        code, text = self.run_cli(
            "collect", "--min-age-days", "0", "--approve", "--approve-task-cleanup", "clean"
        )
        self.assertEqual(code, 0, text)
        # plan fetch, plan measurement, then: measure, recheck fetch, remove.
        self.assertEqual(order[-3:], ["measure", "fetch", "remove"])

    def test_collect_requires_fresh_remote_refs(self):
        self.fixture.add_worktree("clean", "feature/clean")
        saved = gc.fetch_repo
        gc.fetch_repo = lambda repo: (False, "network unreachable")
        self.addCleanup(lambda: setattr(gc, "fetch_repo", saved))
        code, text = self.run_cli(
            "collect", "--min-age-days", "0", "--approve", "--approve-task-cleanup", "clean"
        )
        self.assertIn("fetch-failed", text)
        self.assertTrue((self.fixture.root / "worktrees" / "clean").is_dir())


class AgentTaskLockParityTest(unittest.TestCase):
    """bin/agent-task and worktree-gc must contend on one canonical lock file.

    `run.json` is data on disk and can hold a lexical spelling of the worktree
    path (`/./`, `//`, `..`). Hashing it as stored puts `agent-task start` on a
    different lock file from the one `worktree-gc` holds across a removal, and
    the two stop contending at all - which is the whole point of the lock. This
    runs the real bin/agent-task, with systemd stubbed out, against a real flock
    held by a real WorktreeLockGuard.
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        tmp = Path(self._tmp.name)
        self.ws = tmp / "ws"
        for name in ("worktrees", "artifacts", "runs", "locks", "repos"):
            (self.ws / name).mkdir(parents=True)
        (self.ws / "worktrees" / "sub").mkdir()

        self.repo = tmp / "repo"
        run_git("init", "-q", "-b", "main", str(self.repo))
        (self.repo / "file").write_text("base\n")
        run_git("add", "-A", cwd=self.repo)
        run_git("commit", "-qm", "base", cwd=self.repo)
        self.worktree = self.ws / "worktrees" / "lex"
        run_git("worktree", "add", "-q", "-b", "work", str(self.worktree), cwd=self.repo)
        self.canonical = str(self.worktree.resolve())
        # A spelling that stats to the same directory and hashes differently.
        self.lexical = f"{self.ws}/worktrees/./sub/../lex//"
        self.assertNotEqual(self.lexical, self.canonical)

        artifacts = self.ws / "artifacts" / "LEX-1"
        artifacts.mkdir(parents=True)
        (artifacts / "run.json").write_text(json.dumps({
            "project": "p", "issue": "LEX-1", "repo": str(self.repo), "base": "main",
            "branch": "work", "worktree": self.lexical, "artifacts": str(artifacts),
            "mode": "dev", "max_hours": 2,
        }))

        stubs = tmp / "stubs"
        stubs.mkdir()
        # systemd-run runs the wrapper inline; systemctl always reports inactive.
        (stubs / "systemd-run").write_text('#!/usr/bin/env bash\nrunner="${!#}"\n"$runner" || true\n')
        (stubs / "systemctl").write_text("#!/usr/bin/env bash\necho inactive\n")
        (stubs / "claude").write_text("#!/usr/bin/env bash\nexit 0\n")
        for stub in stubs.iterdir():
            os.chmod(stub, 0o755)
        self.env = {**GIT_ENV, "PATH": f"{stubs}:{os.environ['PATH']}",
                    "AGENT_WORKSTATION_ROOT": str(self.ws)}
        self.prompt = tmp / "prompt"
        self.prompt.write_text("hello\n")

    def start(self):
        subprocess.run(
            [str(REPO_ROOT / "bin" / "agent-task"), "start", "--issue", "LEX-1",
             "--prompt-file", str(self.prompt), "--agent", "claude"],
            env=self.env, capture_output=True, text=True, timeout=120,
        )
        runs = sorted((self.ws / "artifacts" / "LEX-1" / "runs").iterdir())
        self.assertTrue(runs, "agent-task start produced no run directory")
        return runs[-1]

    def lock_name(self, path):
        return hashlib.sha256(str(path).encode()).hexdigest() + ".lock"

    def test_a_lexical_run_json_path_contends_with_the_gc_lock(self):
        guard = gc.WorktreeLockGuard(self.ws, self.canonical)
        acquired, error = guard.acquire()
        self.assertTrue(acquired, error)
        self.addCleanup(guard.release)

        run_dir = self.start()

        # 73 is the runner's "could not take the worktree lock" exit. Reaching
        # it proves both sides picked the same file: hashing the stored lexical
        # spelling would have taken a free lock and run the agent.
        self.assertEqual((run_dir / "exit-code").read_text().strip(), "73")
        self.assertEqual(json.loads((run_dir / "result.json").read_text())["state"], "FAILED")
        # No second lock file appeared for the lexical spelling.
        self.assertFalse((self.ws / "locks" / self.lock_name(self.lexical)).exists())
        self.assertTrue((self.ws / "locks" / self.lock_name(self.canonical)).exists())

    def test_the_same_run_proceeds_once_the_gc_lock_is_released(self):
        """Control: the block above is contention, not a broken start path."""
        run_dir = self.start()
        self.assertEqual((run_dir / "exit-code").read_text().strip(), "0")
        self.assertEqual(json.loads((run_dir / "result.json").read_text())["state"], "COMPLETED")

    def test_start_records_the_canonical_worktree_path(self):
        self.start()
        state = (self.ws / "runs" / "lex-1.env").read_text()
        self.assertIn(f"WORKTREE={self.canonical}\n", state)
        self.assertNotIn("/./", state)

    def test_gc_lock_files_cover_the_canonical_path_from_any_spelling(self):
        self.assertEqual(gc.canonical_worktree_path(self.lexical), self.canonical)
        nested = self.worktree / "nested"
        nested.mkdir()
        # Even a path *inside* the worktree resolves to the worktree's own lock.
        for spelling in (self.lexical, self.canonical, str(nested)):
            with self.subTest(spelling):
                names = {f.name for f in gc.lock_files_for(self.ws, spelling)}
                self.assertIn(self.lock_name(self.canonical), names)


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

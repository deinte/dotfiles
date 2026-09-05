#!/usr/bin/env python3
"""Tests for bin/worktree-gc safety predicates and command behaviour.

Run with: tests/worktree-gc.bash  (or python3 -m unittest tests.worktree_gc_test)
"""

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

    def test_completed_task_does_not_block(self):
        path = self.fixture.add_worktree("done", "feature/done")
        artifacts = self.fixture.root / "artifacts" / "DONE"
        run_dir = artifacts / "runs" / "20260101T000000Z"
        run_dir.mkdir(parents=True)
        (run_dir / "result.json").write_text(json.dumps({"state": "COMPLETED"}))
        (artifacts / "run.json").write_text(json.dumps({"issue": "DONE", "worktree": str(path)}))
        report = self.report()
        self.assertEqual(self.blockers(report, "done"), set())
        self.assertEqual(self.record(report, "done")["tasks"][0]["issue"], "DONE")

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
        self.assertRegex(text, r"reclaimed \d+ inodes")

    def test_collect_reports_actual_reclaimed_counts(self):
        self.fixture.add_worktree("clean", "feature/clean")
        code, text = self.run_cli("collect", "--min-age-days", "0", "--approve", "--json")
        self.assertEqual(code, 0, text)
        payload = json.loads(text[text.index("{", text.index("Failed/skipped")):])
        self.assertEqual(len(payload["removed"]), 1)
        self.assertGreater(payload["reclaimed_inodes"], 0)
        self.assertGreater(payload["reclaimed_bytes"], 0)

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

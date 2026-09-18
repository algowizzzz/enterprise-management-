"""Tests for the Windows compatibility layer.

These run on Linux. Where a test needs Windows semantics it *simulates* them by
flipping ``winbench.compat.IS_WINDOWS`` and removing the POSIX API the code is
supposed to stop relying on -- which is exactly the failure mode we are guarding
against. That catches the regression class that matters (code reaching for a
POSIX API that Windows does not have) without needing a Windows runner.

Run with:  python -m pytest tests -v
"""

import os
import subprocess
import sys
import types

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "winbench"))

from winbench import _resource_stub, compat  # noqa: E402


# ---------------------------------------------------------------------------
# resource stub
# ---------------------------------------------------------------------------


def test_resource_stub_matches_the_api_frappe_uses():
	"""frappe/core/doctype/prepared_report uses exactly this expression."""
	usage = _resource_stub.getrusage(_resource_stub.RUSAGE_SELF)
	assert isinstance(usage.ru_maxrss, int)
	assert usage.ru_maxrss > 0, "peak RSS should be a real measurement, not a placeholder"
	assert usage.ru_utime >= 0.0


def test_resource_stub_rusage_is_a_named_tuple():
	usage = _resource_stub.getrusage()
	assert usage.ru_maxrss == usage[2], "field order must match the real struct_rusage"


def test_resource_stub_children_does_not_raise():
	usage = _resource_stub.getrusage(_resource_stub.RUSAGE_CHILDREN)
	assert usage.ru_maxrss >= 0


def test_resource_stub_rlimit_is_inert():
	assert _resource_stub.getrlimit(_resource_stub.RLIMIT_AS) == (
		_resource_stub.RLIM_INFINITY,
		_resource_stub.RLIM_INFINITY,
	)
	assert _resource_stub.setrlimit(_resource_stub.RLIMIT_AS, (1, 2)) is None


def test_module_stub_is_registered_under_the_real_name(monkeypatch):
	"""`import resource` inside Frappe must resolve to the stub on Windows."""
	monkeypatch.setattr(compat, "IS_WINDOWS", True)
	monkeypatch.delitem(sys.modules, "resource", raising=False)

	real_import = __builtins__["__import__"] if isinstance(__builtins__, dict) else __import__

	def fake_import(name, *args, **kwargs):
		if name == "resource":
			raise ImportError("no module named resource")
		return real_import(name, *args, **kwargs)

	monkeypatch.setattr("builtins.__import__", fake_import)
	compat.install_module_stubs()

	assert sys.modules["resource"] is _resource_stub
	monkeypatch.delitem(sys.modules, "resource", raising=False)


# ---------------------------------------------------------------------------
# execute_in_shell
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_frappe_utils(monkeypatch):
	"""A stand-in for frappe.utils carrying the upstream execute_in_shell."""
	module = types.ModuleType("frappe.utils")

	def execute_in_shell(cmd, verbose=False, low_priority=False, check_exit_code=False):
		raise AssertionError("the original should have been replaced")

	module.execute_in_shell = execute_in_shell
	frappe = types.ModuleType("frappe")
	frappe.utils = module
	monkeypatch.setitem(sys.modules, "frappe", frappe)
	monkeypatch.setitem(sys.modules, "frappe.utils", module)
	return module


def test_execute_in_shell_never_passes_preexec_fn_on_windows(fake_frappe_utils, monkeypatch):
	"""preexec_fn raises ValueError on Windows; the patched version must not use it."""
	monkeypatch.setattr(compat, "IS_WINDOWS", True)
	compat._patch_execute_in_shell()

	seen = {}
	real_popen = subprocess.Popen

	class RecordingPopen(real_popen):
		def __init__(self, *args, **kwargs):
			seen.update(kwargs)
			kwargs.pop("creationflags", None)
			kwargs.pop("executable", None)
			super().__init__(*args, **kwargs)

	monkeypatch.setattr(subprocess, "Popen", RecordingPopen)
	# CREATE_NO_WINDOW etc. only exist on Windows builds of subprocess.
	monkeypatch.setattr(subprocess, "CREATE_NO_WINDOW", 0x08000000, raising=False)
	monkeypatch.setattr(subprocess, "BELOW_NORMAL_PRIORITY_CLASS", 0x00004000, raising=False)

	err, out = fake_frappe_utils.execute_in_shell("echo hello", low_priority=True)

	assert b"hello" in out
	assert "preexec_fn" not in seen, "preexec_fn is not supported on Windows"
	assert "executable" not in seen, "must not hard-code /bin/bash on Windows"
	assert seen.get("creationflags")


def test_execute_in_shell_keeps_posix_behaviour(fake_frappe_utils, monkeypatch):
	monkeypatch.setattr(compat, "IS_WINDOWS", False)
	compat._patch_execute_in_shell()
	err, out = fake_frappe_utils.execute_in_shell(["echo", "posix"])
	assert b"posix" in out


def test_execute_in_shell_raises_on_failure_when_asked(fake_frappe_utils, monkeypatch):
	monkeypatch.setattr(compat, "IS_WINDOWS", False)
	compat._patch_execute_in_shell()
	with pytest.raises(Exception):
		fake_frappe_utils.execute_in_shell("exit 3", check_exit_code=True)


def test_restore_file_probe_is_answered_without_the_file_utility_on_windows(
	fake_frappe_utils, monkeypatch, tmp_path
):
	"""`bench restore` runs `file <backup>` first; Windows has no `file`."""
	import gzip

	monkeypatch.setattr(compat, "IS_WINDOWS", True)
	compat._patch_execute_in_shell()

	def no_shell(*args, **kwargs):
		raise AssertionError("must not shell out: there is no `file` on Windows")

	monkeypatch.setattr(subprocess, "Popen", no_shell)

	dump = tmp_path / "20260101-site-database.sql.gz"
	dump.write_bytes(gzip.compress(b"CREATE TABLE x ();"))
	err, out = fake_frappe_utils.execute_in_shell(f"file {dump}", check_exit_code=True)
	assert err == b"" and out.decode().endswith("gzip compressed data")
	assert "AES" not in out.decode().split(":")[-1]

	encrypted = tmp_path / "encrypted.sql.gz"
	encrypted.write_bytes(b"\x8c\x0d\x04\x09\x03\x02rest")
	err, out = fake_frappe_utils.execute_in_shell(f"file {encrypted}")
	assert "AES" in out.decode().split(":")[-1], "frappe decides to decrypt on this word"

	with pytest.raises(Exception):
		fake_frappe_utils.execute_in_shell(f"file {tmp_path / 'missing.sql.gz'}", check_exit_code=True)


def test_restore_file_probe_uses_the_real_utility_on_posix(fake_frappe_utils, monkeypatch, tmp_path):
	import shutil

	if not shutil.which("file"):
		pytest.skip("no `file` utility on this machine")
	monkeypatch.setattr(compat, "IS_WINDOWS", False)
	compat._patch_execute_in_shell()
	plain = tmp_path / "plain.sql"
	plain.write_text("select 1;\n")
	err, out = fake_frappe_utils.execute_in_shell(f"file {plain}")
	assert b"text" in out.lower()


# ---------------------------------------------------------------------------
# fault handler -- the blocker that fires on every frappe.init()
# ---------------------------------------------------------------------------


def test_fault_handler_survives_missing_sigusr1(monkeypatch):
	"""Simulate Windows: SIGUSR1 absent. frappe.init() must still complete."""
	import signal

	calls = []

	frappe = types.ModuleType("frappe")

	def _register_fault_handler():
		# upstream body, reduced to the part that breaks
		calls.append("original")
		signal.SIGUSR1  # noqa: B018

	frappe._register_fault_handler = _register_fault_handler
	monkeypatch.setitem(sys.modules, "frappe", frappe)
	monkeypatch.setattr(compat, "IS_WINDOWS", True)
	monkeypatch.delattr(signal, "SIGUSR1", raising=False)
	monkeypatch.setattr(signal, "SIGBREAK", signal.SIGINT, raising=False)

	compat._patch_fault_handler()
	frappe._register_fault_handler()  # must not raise

	assert calls == [], "the original (SIGUSR1) path must not run on Windows"


def test_fault_handler_delegates_on_posix(monkeypatch):
	calls = []
	frappe = types.ModuleType("frappe")
	frappe._register_fault_handler = lambda: calls.append("original")
	monkeypatch.setitem(sys.modules, "frappe", frappe)
	monkeypatch.setattr(compat, "IS_WINDOWS", False)

	compat._patch_fault_handler()
	frappe._register_fault_handler()

	assert calls == ["original"]


# ---------------------------------------------------------------------------
# commands.popen
# ---------------------------------------------------------------------------


def test_commands_popen_drops_preexec_fn(monkeypatch):
	commands = types.ModuleType("frappe.commands")
	commands.popen = lambda *a, **k: pytest.fail("original should be replaced")
	frappe = types.ModuleType("frappe")
	frappe.commands = commands
	monkeypatch.setitem(sys.modules, "frappe", frappe)
	monkeypatch.setitem(sys.modules, "frappe.commands", commands)
	monkeypatch.setattr(compat, "IS_WINDOWS", True)

	seen = {}
	real_popen = subprocess.Popen

	class RecordingPopen(real_popen):
		def __init__(self, *args, **kwargs):
			seen.update(kwargs)
			super().__init__(*args, **kwargs)

	monkeypatch.setattr(subprocess, "Popen", RecordingPopen)
	compat._patch_commands_popen()

	rc = commands.popen("exit 0", output=False)

	assert rc == 0
	assert "preexec_fn" not in seen


# ---------------------------------------------------------------------------
# symlink -> junction
# ---------------------------------------------------------------------------


def test_symlink_falls_back_to_copy_when_linking_is_denied(tmp_path, monkeypatch):
	"""Windows without Developer Mode raises OSError from os.symlink.

	`frappe build` must still produce a usable sites/assets/<app> directory."""
	build = types.ModuleType("frappe.build")
	build.symlink = lambda *a, **k: pytest.fail("original should be replaced")
	frappe = types.ModuleType("frappe")
	frappe.build = build
	monkeypatch.setitem(sys.modules, "frappe", frappe)
	monkeypatch.setitem(sys.modules, "frappe.build", build)
	monkeypatch.setattr(compat, "IS_WINDOWS", True)

	target = tmp_path / "public"
	target.mkdir()
	(target / "app.css").write_text("body{}")
	link = tmp_path / "assets" / "frappe"

	def denied(*args, **kwargs):
		raise OSError(1314, "A required privilege is not held by the client")

	monkeypatch.setattr(os, "symlink", denied)
	monkeypatch.setitem(sys.modules, "_winapi", types.ModuleType("_winapi"))

	compat._patch_symlink()
	build.symlink(str(target), str(link), overwrite=True)

	assert (link / "app.css").read_text() == "body{}"


def test_symlink_overwrite_replaces_existing(tmp_path, monkeypatch):
	build = types.ModuleType("frappe.build")
	build.symlink = lambda *a, **k: None
	frappe = types.ModuleType("frappe")
	frappe.build = build
	monkeypatch.setitem(sys.modules, "frappe", frappe)
	monkeypatch.setitem(sys.modules, "frappe.build", build)
	monkeypatch.setattr(compat, "IS_WINDOWS", True)
	monkeypatch.setitem(sys.modules, "_winapi", types.ModuleType("_winapi"))

	target = tmp_path / "public"
	target.mkdir()
	(target / "v2.css").write_text("new")
	link = tmp_path / "assets" / "frappe"
	link.mkdir(parents=True)
	(link / "stale.css").write_text("old")

	monkeypatch.setattr(os, "symlink", lambda *a, **k: (_ for _ in ()).throw(OSError(1314, "denied")))

	compat._patch_symlink()
	build.symlink(str(target), str(link), overwrite=True)

	assert (link / "v2.css").exists()
	assert not (link / "stale.css").exists()


# ---------------------------------------------------------------------------
# bench id
# ---------------------------------------------------------------------------


def test_bench_id_is_a_clean_redis_namespace(monkeypatch):
	"""A Windows path must not leak `C:\\` into RQ queue names and redis keys."""
	utils = types.ModuleType("frappe.utils")
	utils.get_bench_path = lambda: "C:\\frappe\\winbench"
	utils.get_bench_id = lambda: pytest.fail("original should be replaced")
	frappe = types.ModuleType("frappe")
	frappe.utils = utils
	frappe.get_conf = lambda: {}
	monkeypatch.setitem(sys.modules, "frappe", frappe)
	monkeypatch.setitem(sys.modules, "frappe.utils", utils)
	monkeypatch.setattr(compat, "IS_WINDOWS", True)

	compat._patch_bench_id()
	bench_id = utils.get_bench_id()

	assert bench_id == "C-frappe-winbench"
	assert "\\" not in bench_id and ":" not in bench_id


def test_bench_id_honours_explicit_config(monkeypatch):
	utils = types.ModuleType("frappe.utils")
	utils.get_bench_path = lambda: "C:\\frappe\\winbench"
	utils.get_bench_id = lambda: None
	frappe = types.ModuleType("frappe")
	frappe.utils = utils
	frappe.get_conf = lambda: {"bench_id": "prod-bench"}
	monkeypatch.setitem(sys.modules, "frappe", frappe)
	monkeypatch.setitem(sys.modules, "frappe.utils", utils)
	monkeypatch.setattr(compat, "IS_WINDOWS", True)

	compat._patch_bench_id()
	assert utils.get_bench_id() == "prod-bench"


# ---------------------------------------------------------------------------
# worker
# ---------------------------------------------------------------------------


def test_windows_worker_never_forks(monkeypatch):
	"""The Windows worker class must not be the forking one, and must use a
	timer-based death penalty rather than SIGALRM."""
	from rq import SimpleWorker
	from rq.timeouts import TimerDeathPenalty

	from winbench import worker as worker_mod

	monkeypatch.setattr(worker_mod, "IS_WINDOWS", True)
	cls = worker_mod.build_worker_class()

	assert issubclass(cls, SimpleWorker)
	assert cls.death_penalty_class is TimerDeathPenalty
	assert not hasattr(cls, "fork_work_horse") or cls.execute_job is SimpleWorker.execute_job


def test_posix_worker_keeps_upstream_semantics(monkeypatch):
	from rq import Worker

	from winbench import worker as worker_mod

	monkeypatch.setattr(worker_mod, "IS_WINDOWS", False)
	assert worker_mod.build_worker_class() is Worker


# ---------------------------------------------------------------------------
# backup restore without the `tar` binary
# ---------------------------------------------------------------------------


def _fake_installer(monkeypatch, site_dir):
	installer = types.ModuleType("frappe.installer")
	installer.extract_files = lambda *a, **k: pytest.fail("original should be replaced")
	frappe = types.ModuleType("frappe")
	frappe.installer = installer
	frappe.init = lambda site: None
	frappe.destroy = lambda: None
	frappe.get_site_path = lambda: str(site_dir)
	monkeypatch.setitem(sys.modules, "frappe", frappe)
	monkeypatch.setitem(sys.modules, "frappe.installer", installer)
	return installer


def test_extract_files_strips_two_components_without_tar(tmp_path, monkeypatch):
	"""Windows tar.exe rejects `--strip`; the patch must use tarfile instead."""
	import tarfile

	payload = tmp_path / "src" / "a" / "b" / "private" / "files"
	payload.mkdir(parents=True)
	(payload / "policy.pdf").write_bytes(b"%PDF-1.4")

	archive_path = tmp_path / "backup.tgz"
	with tarfile.open(archive_path, "w:gz") as archive:
		archive.add(tmp_path / "src" / "a", arcname="a")

	site_dir = tmp_path / "site"
	site_dir.mkdir()
	installer = _fake_installer(monkeypatch, site_dir)

	# Prove we are not relying on an external binary.
	monkeypatch.setattr(
		subprocess, "check_output", lambda *a, **k: pytest.fail("must not shell out to tar")
	)
	monkeypatch.setattr(compat, "IS_WINDOWS", True)
	compat._patch_extract_files()

	installer.extract_files("win.localhost", str(archive_path))

	assert (site_dir / "private" / "files" / "policy.pdf").read_bytes() == b"%PDF-1.4"


def test_extract_files_refuses_path_traversal(tmp_path, monkeypatch):
	import tarfile

	archive_path = tmp_path / "evil.tar"
	victim = tmp_path / "payload.txt"
	victim.write_text("pwned")
	with tarfile.open(archive_path, "w") as archive:
		archive.add(victim, arcname="a/b/../../../../escaped.txt")

	site_dir = tmp_path / "site"
	site_dir.mkdir()
	installer = _fake_installer(monkeypatch, site_dir)
	monkeypatch.setattr(compat, "IS_WINDOWS", True)
	compat._patch_extract_files()

	with pytest.raises(ValueError, match="outside the site directory"):
		installer.extract_files("win.localhost", str(archive_path))


# ---------------------------------------------------------------------------
# pdf temp directory
# ---------------------------------------------------------------------------


def test_pdf_patch_preserves_the_html_options_tuple_order(monkeypatch, tmp_path):
	"""`read_options_from_html` returns (html, options), not (options, html).

	Getting this backwards makes every PDF raise
	``AttributeError: 'str' object has no attribute 'get'`` from get_pdf().
	"""
	pdf = types.ModuleType("frappe.utils.pdf")

	def read_options_from_html(html):
		return html + "<!--seen-->", {"header-html": "/tmp/frappe-pdf-abc.html"}

	pdf.read_options_from_html = read_options_from_html
	frappe = types.ModuleType("frappe")
	utils = types.ModuleType("frappe.utils")
	utils.pdf = pdf
	frappe.utils = utils
	monkeypatch.setitem(sys.modules, "frappe", frappe)
	monkeypatch.setitem(sys.modules, "frappe.utils", utils)
	monkeypatch.setitem(sys.modules, "frappe.utils.pdf", pdf)
	monkeypatch.setattr(compat, "IS_WINDOWS", True)
	# On Linux gettempdir() *is* /tmp, so force a Windows-shaped temp dir to
	# prove the rewrite actually happens.
	win_temp = str(tmp_path / "Temp")
	monkeypatch.setattr("tempfile.gettempdir", lambda: win_temp)

	compat._patch_pdf_tempdir()
	html, options = pdf.read_options_from_html("<h1>Policy</h1>")

	assert isinstance(html, str) and html.endswith("<!--seen-->")
	assert isinstance(options, dict)
	assert options["header-html"] == os.path.join(win_temp, "frappe-pdf-abc.html"), (
		"the literal /tmp path must be rewritten into the platform temp dir"
	)

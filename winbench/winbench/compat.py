"""Windows compatibility layer for the Frappe framework.

`install()` must be called *before* ``import frappe``.  It does two things:

1. Registers stand-ins for POSIX-only stdlib modules Frappe imports at module
   scope (currently just ``resource``), so the import graph resolves at all.
2. Replaces the handful of Frappe functions that shell out to POSIX-only APIs
   with cross-platform equivalents.

Every patch is idempotent, is a no-op on POSIX, and records itself in
:data:`APPLIED` so `winbench doctor` can report exactly what is active.
"""

import os
import sys

IS_WINDOWS = os.name == "nt"

APPLIED: list[str] = []
SKIPPED: list[tuple[str, str]] = []


def _record(name: str) -> None:
	if name not in APPLIED:
		APPLIED.append(name)


# --------------------------------------------------------------------------
# Stage 1: stdlib stand-ins. Must run before `import frappe`.
# --------------------------------------------------------------------------


def install_module_stubs() -> None:
	if not IS_WINDOWS:
		return
	if "resource" not in sys.modules:
		try:
			import resource  # noqa: F401 -- real module, nothing to do
		except ImportError:
			from winbench import _resource_stub

			sys.modules["resource"] = _resource_stub
			_record("stdlib:resource")


# --------------------------------------------------------------------------
# Stage 2: Frappe function replacements.
# --------------------------------------------------------------------------


def _patch_execute_in_shell() -> None:
	"""`frappe.utils.execute_in_shell` hard-codes bash and uses ``preexec_fn``.

	``preexec_fn`` is POSIX-only (it runs between fork and exec, and Windows has
	no fork), and ``executable="/bin/bash"`` cannot be honoured either.  We keep
	the exact same signature and return contract and swap in the platform shell,
	lowering priority through the Windows API instead of ``os.nice``.
	"""
	import frappe.utils

	if getattr(frappe.utils.execute_in_shell, "_winbench_patched", False):
		return

	import shlex
	import subprocess
	import tempfile

	def execute_in_shell(cmd, verbose=False, low_priority=False, check_exit_code=False):
		if isinstance(cmd, list):
			cmd = subprocess.list2cmdline(cmd) if IS_WINDOWS else shlex.join(cmd)

		if IS_WINDOWS and isinstance(cmd, str) and cmd.startswith("file "):
			# `bench restore` asks the Unix `file` utility what a backup is --
			# gzip, encrypted, or plain SQL -- before it does anything else.
			# Windows has no `file`, so every restore failed at that first
			# step. Answer the one question it asks, from the file's first bytes.
			err, out = _describe_file(cmd[5:].strip().strip('"'))
			if check_exit_code and err:
				raise Exception("Command failed")
			return err, out

		with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
			kwargs = {"shell": True, "stdout": stdout, "stderr": stderr}

			if IS_WINDOWS:
				# CREATE_NO_WINDOW keeps report/print jobs from flashing consoles
				# when the site runs as a Windows Service.
				kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
				if low_priority:
					kwargs["creationflags"] |= subprocess.BELOW_NORMAL_PRIORITY_CLASS
			else:
				import shutil

				kwargs["executable"] = shutil.which("bash") or "/bin/bash"
				if low_priority:
					kwargs["preexec_fn"] = lambda: os.nice(10)

			p = subprocess.Popen(cmd, **kwargs)
			exit_code = p.wait()

			stdout.seek(0)
			out = stdout.read()
			stderr.seek(0)
			err = stderr.read()

		failed = check_exit_code and exit_code

		if verbose or failed:
			if err:
				print(err.decode(errors="replace"))
			if out:
				print(out.decode(errors="replace"))

		if failed:
			raise Exception("Command failed")

		return err, out

	execute_in_shell._winbench_patched = True
	frappe.utils.execute_in_shell = execute_in_shell
	_record("frappe.utils.execute_in_shell")


def _describe_file(path: str) -> tuple[bytes, bytes]:
	"""What `file <path>` would say, for the three kinds of backup frappe restores.

	Frappe reads only two things from the answer: whether the part after the
	last colon mentions AES (an encrypted backup, which it decrypts first), and
	otherwise nothing -- it decompresses by file extension. So the wording
	matches `file`'s for those cases and is plain otherwise.
	"""
	try:
		with open(path, "rb") as fh:
			head = fh.read(4)
	except OSError as e:
		return f"{path}: cannot open ({e})".encode(), b""
	if head[:2] == b"\x1f\x8b":
		kind = "gzip compressed data"
	elif head[:1] in (b"\x8c", b"\xc3"):
		# OpenPGP symmetric-key packet: `gpg -c`, which is how frappe encrypts.
		kind = "GPG symmetrically encrypted data (AES256 cipher)"
	else:
		kind = "ASCII text"
	return b"", f"{path}: {kind}".encode()


def _patch_set_niceness() -> None:
	"""`set_niceness` calls ``os.nice``, which does not exist on Windows.

	The intent -- background workers should yield to web workers -- maps cleanly
	onto Windows priority classes, so we express it that way instead of skipping.
	"""
	import frappe.utils.background_jobs as bj

	if getattr(bj.set_niceness, "_winbench_patched", False):
		return

	def set_niceness():
		if not IS_WINDOWS:
			return _original_set_niceness()

		import frappe

		conf = frappe.get_conf()
		configured = conf.get("background_process_niceness")
		increment = bj.BACKGROUND_PROCESS_NICENESS if configured is None else int(configured)

		if increment <= 0:
			return

		try:
			import psutil

			cls = (
				psutil.IDLE_PRIORITY_CLASS if increment >= 15 else psutil.BELOW_NORMAL_PRIORITY_CLASS
			)
			psutil.Process(os.getpid()).nice(cls)
		except Exception:
			# Priority is an optimisation, never a correctness requirement.
			pass

	_original_set_niceness = bj.set_niceness
	set_niceness._winbench_patched = True
	bj.set_niceness = set_niceness
	_record("frappe.utils.background_jobs.set_niceness")


def _patch_symlink() -> None:
	"""`frappe.build.symlink` links ``sites/assets/<app>`` at each app's public dir.

	``os.symlink`` on Windows needs either Developer Mode or SeCreateSymbolicLink,
	neither of which we can assume.  Directory junctions need no privilege at all
	and are transparent to every reader, so we prefer them and fall back to a copy.
	"""
	import frappe.build

	if getattr(frappe.build.symlink, "_winbench_patched", False):
		return

	import shutil

	def symlink(target, link_name, overwrite=False):
		if not IS_WINDOWS:
			return _original_symlink(target, link_name, overwrite=overwrite)

		if os.path.lexists(link_name):
			if not overwrite:
				raise FileExistsError(link_name)
			_remove_link(link_name)

		parent = os.path.dirname(os.path.abspath(link_name))
		if parent:
			os.makedirs(parent, exist_ok=True)

		abs_target = target if os.path.isabs(target) else os.path.join(parent, target)

		if os.path.isdir(abs_target):
			try:
				import _winapi

				_winapi.CreateJunction(os.path.abspath(abs_target), os.path.abspath(link_name))
				return
			except Exception:
				pass
			try:
				os.symlink(abs_target, link_name, target_is_directory=True)
				return
			except OSError:
				pass
			shutil.copytree(abs_target, link_name)
			return

		try:
			os.symlink(abs_target, link_name)
		except OSError:
			shutil.copy2(abs_target, link_name)

	def _remove_link(path):
		if os.path.isdir(path) and not os.path.islink(path):
			try:
				os.rmdir(path)  # junctions and empty dirs
			except OSError:
				shutil.rmtree(path, ignore_errors=True)
		else:
			try:
				os.remove(path)
			except OSError:
				pass

	_original_symlink = frappe.build.symlink
	symlink._winbench_patched = True
	frappe.build.symlink = symlink
	_record("frappe.build.symlink")


def _patch_pdf_tempdir() -> None:
	"""`frappe.utils.pdf` writes header/footer HTML and cookie jars into a literal
	``/tmp``. That path does not exist on Windows, so PDF generation dies on the
	first ``open()``. Route it through ``tempfile.gettempdir()`` instead."""
	try:
		import frappe.utils.pdf as pdf
	except Exception as e:  # pragma: no cover - optional (needs wkhtmltopdf/weasyprint)
		SKIPPED.append(("frappe.utils.pdf", str(e)))
		return

	if getattr(pdf, "_winbench_patched", False):
		return

	import tempfile

	tmp = tempfile.gettempdir()
	# The module reads `/tmp` inline rather than from a constant, so expose a
	# module-level TEMP_DIR and rewrite the two call sites via wrappers.
	pdf.TEMP_DIR = tmp

	if hasattr(pdf, "read_options_from_html"):
		_orig_read = pdf.read_options_from_html

		def read_options_from_html(html):
			# Upstream returns (html, options) -- in that order.
			html, options = _orig_read(html)
			for key in ("header-html", "footer-html"):
				value = options.get(key)
				if isinstance(value, str) and value.startswith("/tmp"):
					options[key] = os.path.join(tmp, os.path.basename(value))
			return html, options

		pdf.read_options_from_html = read_options_from_html

	pdf._winbench_patched = True
	_record("frappe.utils.pdf:tempdir")


def _patch_bench_id() -> None:
	"""`get_bench_id` builds a Redis key namespace out of the bench path.

	On Windows that yields e.g. ``C:\\frappe\\winbench`` -- backslashes and a
	colon inside a Redis key prefix, which then shows up verbatim in RQ queue
	names and job keys. Normalise to the same shape a POSIX bench produces."""
	import frappe.utils

	if getattr(frappe.utils.get_bench_id, "_winbench_patched", False):
		return

	def get_bench_id():
		import frappe

		configured = frappe.get_conf().get("bench_id")
		if configured:
			return configured
		path = frappe.utils.get_bench_path().replace("\\", "/")
		path = path.replace(":", "")
		return path.strip("/").replace("/", "-")

	get_bench_id._winbench_patched = True
	frappe.utils.get_bench_id = get_bench_id
	_record("frappe.utils.get_bench_id")


def _patch_fault_handler() -> None:
	"""`frappe._register_fault_handler` registers ``faulthandler`` on SIGUSR1.

	It is called from ``frappe.init()`` -- i.e. on every request, job and CLI
	command -- and ``signal.SIGUSR1`` does not exist on Windows, so this is an
	AttributeError before a single line of application code runs.  It is the one
	blocker that makes Frappe unusable on Windows out of the box.

	SIGBREAK is the closest Windows analogue that a developer can actually send
	(``taskkill``/Ctrl+Break), so we register there and fall back to leaving
	faulthandler unregistered rather than failing init.
	"""
	import frappe

	if getattr(frappe._register_fault_handler, "_winbench_patched", False):
		return

	def _register_fault_handler():
		if not IS_WINDOWS:
			return _original_register()

		import faulthandler
		import io
		import signal
		import sys

		if not isinstance(sys.__stderr__, io.TextIOWrapper):
			return

		sigbreak = getattr(signal, "SIGBREAK", None)
		if sigbreak is None:
			return
		try:
			faulthandler.register(sigbreak, file=sys.__stderr__)
		except (RuntimeError, ValueError, OSError):
			# Registering is a debugging nicety; never let it break init().
			pass

	_original_register = frappe._register_fault_handler
	_register_fault_handler._winbench_patched = True
	frappe._register_fault_handler = _register_fault_handler
	_record("frappe._register_fault_handler")


def _patch_commands_popen() -> None:
	"""`frappe.commands.popen` passes ``preexec_fn=set_low_prio``.

	``preexec_fn`` is rejected outright by ``subprocess.Popen`` on Windows
	(``ValueError: preexec_fn is not supported on Windows``), which breaks
	``build``, ``backup`` and anything else that shells out.

	The irony is that the callback it passes already has a Windows branch -- it
	just cannot run between fork and exec because there is no fork.  We keep the
	same behaviour by applying the priority change to the child from the parent
	immediately after spawn.
	"""
	import frappe.commands

	if getattr(frappe.commands.popen, "_winbench_patched", False):
		return

	import subprocess

	def popen(command, *args, **kwargs):
		if not IS_WINDOWS:
			return _original_popen(command, *args, **kwargs)

		output = kwargs.get("output", True)
		shell = kwargs.get("shell", True)
		low_prio = kwargs.get("low_prio", False)
		cwd = kwargs.get("cwd")
		env = kwargs.get("env")
		raise_err = kwargs.get("raise_err")

		proc = subprocess.Popen(
			command,
			stdout=None if output else subprocess.PIPE,
			stderr=None if output else subprocess.PIPE,
			shell=shell,
			cwd=cwd,
			env=env,
		)

		if low_prio:
			try:
				import psutil

				child = psutil.Process(proc.pid)
				child.nice(psutil.IDLE_PRIORITY_CLASS)
				child.ionice(psutil.IOPRIO_VERYLOW)
			except Exception:
				pass

		return_ = proc.wait()

		if return_ and raise_err:
			raise subprocess.CalledProcessError(return_, command)

		return return_

	_original_popen = frappe.commands.popen
	popen._winbench_patched = True
	frappe.commands.popen = popen
	_record("frappe.commands.popen")


def _patch_extract_files() -> None:
	"""`frappe.installer.extract_files` shells out to ``tar`` with ``--strip 2``.

	Windows 10+ does ship a ``tar.exe`` (bsdtar), but it spells the option
	``--strip-components`` and rejects the GNU abbreviation ``--strip``, so
	restoring a backup with files fails with a non-obvious usage error.  Python's
	own :mod:`tarfile` handles both ``.tar`` and ``.tgz`` and needs no external
	binary at all, so use it and strip the leading components ourselves.
	"""
	import frappe.installer as installer

	if getattr(installer.extract_files, "_winbench_patched", False):
		return

	def extract_files(site_name, file_path):
		import shutil
		import tarfile

		import frappe

		frappe.init(site=site_name)
		abs_site_path = os.path.abspath(frappe.get_site_path())

		shutil.copy2(os.path.abspath(file_path), abs_site_path)
		tar_name = os.path.split(file_path)[1]
		tar_path = os.path.join(abs_site_path, tar_name)

		try:
			if not file_path.endswith((".tar", ".tgz")):
				return tar_path

			mode = "r:gz" if file_path.endswith(".tgz") else "r:"
			with tarfile.open(tar_path, mode) as archive:
				for member in archive.getmembers():
					# Reproduce `--strip 2`: drop the first two path components.
					parts = member.name.split("/")[2:]
					if not parts:
						continue
					member.name = "/".join(parts)
					_assert_within(abs_site_path, member.name)
					archive.extract(member, path=abs_site_path)
		finally:
			frappe.destroy()

		return tar_path

	def _assert_within(base: str, relative: str) -> None:
		"""Refuse path-traversal entries -- tarfile does not check this for us."""
		destination = os.path.realpath(os.path.join(base, relative))
		if not destination.startswith(os.path.realpath(base) + os.sep):
			raise ValueError(f"Refusing to extract outside the site directory: {relative!r}")

	extract_files._winbench_patched = True
	installer.extract_files = extract_files
	_record("frappe.installer.extract_files")


PATCHES = (
	_patch_fault_handler,
	_patch_commands_popen,
	_patch_execute_in_shell,
	_patch_set_niceness,
	_patch_symlink,
	_patch_pdf_tempdir,
	_patch_bench_id,
	_patch_extract_files,
)


def install(force: bool = False) -> list[str]:
	"""Install the compatibility layer. Safe to call more than once.

	On POSIX this is a near no-op (patches short-circuit to the originals) so the
	same entry points can be used on a Linux CI box and a Windows workstation.
	"""
	install_module_stubs()

	if not IS_WINDOWS and not force:
		return APPLIED

	for patch in PATCHES:
		try:
			patch()
		except Exception as e:
			SKIPPED.append((patch.__name__, f"{type(e).__name__}: {e}"))

	return APPLIED

#!/usr/bin/env python3
"""Static audit for Windows portability of a Frappe app.

Run this against `apps/<app>` before trying to bring an app across. It parses
every Python file with `ast` (no imports, no execution) and reports constructs
that do not exist or behave differently on Windows.

    python audit_windows_compat.py apps/frappe apps/hrms

Exit code is 1 if any BLOCKER is found, 0 otherwise, so it drops into CI.

Categories:
  BLOCKER  -- raises on Windows (AttributeError/ModuleNotFoundError/OSError)
  WARNING  -- runs, but behaves differently or needs an external Windows binary
  NOTE     -- worth eyeballing; usually fine

A finding inside a platform guard (``if os.name == "nt"``, ``if IS_WINDOWS``,
``try: import fcntl except ImportError``) is deliberate portability code, not a
bug, so it is downgraded to NOTE rather than reported as a blocker.
"""

import argparse
import ast
import json
import os
import sys
from collections import Counter
from dataclasses import asdict, dataclass

# Stdlib modules that simply do not exist on Windows.
POSIX_ONLY_MODULES = {
	"fcntl": "BLOCKER",
	"pwd": "BLOCKER",
	"grp": "BLOCKER",
	"resource": "BLOCKER",
	"termios": "BLOCKER",
	"tty": "BLOCKER",
	"pty": "BLOCKER",
	"posix": "BLOCKER",
	"syslog": "BLOCKER",
	"crypt": "BLOCKER",
	"spwd": "BLOCKER",
	"nis": "BLOCKER",
	"readline": "WARNING",  # present via pyreadline3 only
	"curses": "WARNING",
}

# os.<attr> that is POSIX-only.
POSIX_ONLY_OS_ATTRS = {
	"fork": "BLOCKER",
	"forkpty": "BLOCKER",
	"setsid": "BLOCKER",
	"setpgid": "BLOCKER",
	"setpgrp": "BLOCKER",
	"getpgid": "BLOCKER",
	"getpgrp": "BLOCKER",
	"killpg": "BLOCKER",
	"nice": "BLOCKER",
	"getuid": "BLOCKER",
	"geteuid": "BLOCKER",
	"getgid": "BLOCKER",
	"getegid": "BLOCKER",
	"setuid": "BLOCKER",
	"setgid": "BLOCKER",
	"getgroups": "BLOCKER",
	"chown": "BLOCKER",
	"lchown": "BLOCKER",
	"fchown": "BLOCKER",
	"mkfifo": "BLOCKER",
	"uname": "BLOCKER",
	"wait3": "BLOCKER",
	"wait4": "BLOCKER",
	"WIFEXITED": "BLOCKER",
	"symlink": "WARNING",  # needs Developer Mode or admin
	"link": "WARNING",
	"chmod": "NOTE",  # only the read-only bit is honoured
	"statvfs": "BLOCKER",
	"sync": "BLOCKER",
}

# signal.<attr> that Windows does not deliver.
POSIX_ONLY_SIGNALS = {
	"SIGKILL": "BLOCKER",
	"SIGUSR1": "BLOCKER",
	"SIGUSR2": "BLOCKER",
	"SIGALRM": "BLOCKER",
	"SIGHUP": "BLOCKER",
	"SIGQUIT": "BLOCKER",
	"SIGCHLD": "BLOCKER",
	"SIGWINCH": "BLOCKER",
	"setitimer": "BLOCKER",
	"alarm": "BLOCKER",
	"pause": "BLOCKER",
	"SIGPIPE": "BLOCKER",
}

# Kwargs that only work on POSIX.
POSIX_ONLY_KWARGS = {
	"preexec_fn": "BLOCKER",
	"start_new_session": "WARNING",
	"restore_signals": "NOTE",
	"pass_fds": "BLOCKER",
}

# External binaries invoked by name that are not present on a stock Windows box.
POSIX_BINARIES = {
	"bash": "BLOCKER",
	"sh": "BLOCKER",
	"tar": "WARNING",  # Win10+ ships bsdtar, but flags differ
	"gzip": "WARNING",
	"gunzip": "WARNING",
	"chmod": "BLOCKER",
	"chown": "BLOCKER",
	"sudo": "BLOCKER",
	"supervisorctl": "BLOCKER",
	"nginx": "BLOCKER",
	"gunicorn": "BLOCKER",
	"mysql": "WARNING",
	"mysqldump": "WARNING",
	"wkhtmltopdf": "WARNING",
	"which": "WARNING",
	"rm": "WARNING",
	"cp": "WARNING",
	"ln": "WARNING",
}

ABS_POSIX_PATH_PREFIXES = ("/tmp", "/var/", "/etc/", "/usr/", "/opt/", "/home/", "/bin/", "/proc/")


# Names that, when tested, mean the author is already branching on platform.
PLATFORM_NAMES = {
	"IS_WINDOWS",
	"IS_POSIX",
	"IS_LINUX",
	"WINDOWS",
	"POSIX",
	"ON_WINDOWS",
	"is_windows",
	"WIN32",
}


def _is_platform_test(node: ast.AST) -> bool:
	"""True if this expression branches on the operating system."""
	for sub in ast.walk(node):
		if isinstance(sub, ast.Name) and sub.id in PLATFORM_NAMES:
			return True
		if isinstance(sub, ast.Attribute):
			value = sub.value
			if isinstance(value, ast.Name):
				if (value.id, sub.attr) in {
					("os", "name"),
					("sys", "platform"),
					("psutil", "WINDOWS"),
					("psutil", "LINUX"),
					("psutil", "MACOS"),
					("psutil", "POSIX"),
				}:
					return True
			if sub.attr in {"system", "platform"} and isinstance(value, ast.Name):
				if value.id == "platform":
					return True
	return False


@dataclass
class Finding:
	severity: str
	category: str
	file: str
	line: int
	detail: str


class Visitor(ast.NodeVisitor):
	def __init__(self, path: str, root: str):
		self.path = path
		self.rel = os.path.relpath(path, root)
		self.findings: list[Finding] = []
		self.guard_depth = 0

	def add(self, severity, category, node, detail):
		if self.guard_depth:
			# Deliberate portability code: a POSIX call behind a platform check,
			# or an import already wrapped in try/except ImportError.
			severity = "NOTE"
			detail = f"{detail} (inside a platform guard)"
		self.findings.append(
			Finding(severity, category, self.rel, getattr(node, "lineno", 0), detail)
		)

	def visit_If(self, node):
		guarded = _is_platform_test(node.test)
		self.guard_depth += guarded
		for child in (*node.body, *node.orelse):
			self.visit(child)
		self.guard_depth -= guarded

	def visit_Try(self, node):
		# `try: import fcntl / except ImportError:` is the canonical way to make
		# an optional POSIX dependency optional.
		handled = {
			h.type.id
			for h in node.handlers
			if isinstance(h.type, ast.Name)
		} | {
			elt.id
			for h in node.handlers
			if isinstance(h.type, ast.Tuple)
			for elt in h.type.elts
			if isinstance(elt, ast.Name)
		}
		guarded = bool(handled & {"ImportError", "ModuleNotFoundError", "AttributeError", "OSError", "Exception"})
		self.guard_depth += guarded
		for child in node.body:
			self.visit(child)
		self.guard_depth -= guarded
		for child in (*node.handlers, *node.orelse, *node.finalbody):
			self.visit(child)

	# -- imports ----------------------------------------------------------
	def visit_Import(self, node):
		for alias in node.names:
			top = alias.name.split(".")[0]
			if sev := POSIX_ONLY_MODULES.get(top):
				self.add(sev, "posix-module", node, f"import {alias.name}")
		self.generic_visit(node)

	def visit_ImportFrom(self, node):
		if node.module:
			top = node.module.split(".")[0]
			if sev := POSIX_ONLY_MODULES.get(top):
				self.add(sev, "posix-module", node, f"from {node.module} import ...")
		self.generic_visit(node)

	# -- attribute access -------------------------------------------------
	def visit_Attribute(self, node):
		base = node.value
		if isinstance(base, ast.Name):
			if base.id == "os":
				if sev := POSIX_ONLY_OS_ATTRS.get(node.attr):
					self.add(sev, "posix-os-api", node, f"os.{node.attr}")
			elif base.id == "signal":
				if sev := POSIX_ONLY_SIGNALS.get(node.attr):
					self.add(sev, "posix-signal", node, f"signal.{node.attr}")
		self.generic_visit(node)

	# -- calls ------------------------------------------------------------
	def visit_Call(self, node):
		for kw in node.keywords:
			if kw.arg and (sev := POSIX_ONLY_KWARGS.get(kw.arg)):
				self.add(sev, "posix-kwarg", node, f"{kw.arg}=...")

		# subprocess/Popen with a POSIX-only binary as argv[0]
		if node.args:
			first = node.args[0]
			names: list[str] = []
			if isinstance(first, ast.Constant) and isinstance(first.value, str):
				names = [first.value.split()[0]] if first.value.strip() else []
			elif isinstance(first, ast.List) and first.elts:
				head = first.elts[0]
				if isinstance(head, ast.Constant) and isinstance(head.value, str):
					names = [head.value]
			for name in names:
				binary = os.path.basename(name)
				if sev := POSIX_BINARIES.get(binary):
					if _is_process_call(node):
						self.add(sev, "posix-binary", node, f"invokes `{binary}`")
		self.generic_visit(node)

	# -- literals ---------------------------------------------------------
	def visit_Constant(self, node):
		if isinstance(node.value, str):
			v = node.value
			if v.startswith(ABS_POSIX_PATH_PREFIXES) and len(v) > 5:
				self.add("WARNING", "abs-posix-path", node, f"hard-coded path {v!r}")
		self.generic_visit(node)


def _is_process_call(node: ast.Call) -> bool:
	func = node.func
	if isinstance(func, ast.Attribute):
		return func.attr in {
			"run",
			"call",
			"check_call",
			"check_output",
			"Popen",
			"system",
			"popen",
			"getoutput",
		}
	if isinstance(func, ast.Name):
		return func.id in {"popen", "system"}
	return False


def audit_file(path: str, root: str) -> list[Finding]:
	try:
		source = open(path, encoding="utf-8", errors="replace").read()
		tree = ast.parse(source, filename=path)
	except SyntaxError as e:
		return [Finding("NOTE", "parse-error", os.path.relpath(path, root), e.lineno or 0, str(e))]

	visitor = Visitor(path, root)
	visitor.visit(tree)
	return visitor.findings


def audit_tree(root: str, skip_tests: bool = True) -> list[Finding]:
	findings: list[Finding] = []
	for dirpath, dirnames, filenames in os.walk(root):
		dirnames[:] = [
			d
			for d in dirnames
			if d not in {".git", "node_modules", "__pycache__", ".venv", "env", "dist"}
		]
		for filename in filenames:
			if not filename.endswith(".py"):
				continue
			if skip_tests and (filename.startswith("test_") or filename == "conftest.py"):
				continue
			findings.extend(audit_file(os.path.join(dirpath, filename), root))
	return findings


def main() -> int:
	parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
	parser.add_argument("paths", nargs="+", help="App directories to audit")
	parser.add_argument("--include-tests", action="store_true")
	parser.add_argument("--json", dest="as_json", action="store_true")
	parser.add_argument(
		"--severity",
		default="WARNING",
		choices=["BLOCKER", "WARNING", "NOTE"],
		help="Minimum severity to print (default: WARNING)",
	)
	args = parser.parse_args()

	order = {"BLOCKER": 0, "WARNING": 1, "NOTE": 2}
	threshold = order[args.severity]

	all_findings: list[Finding] = []
	for path in args.paths:
		all_findings.extend(audit_tree(path, skip_tests=not args.include_tests))

	shown = [f for f in all_findings if order[f.severity] <= threshold]
	shown.sort(key=lambda f: (order[f.severity], f.file, f.line))

	if args.as_json:
		print(json.dumps([asdict(f) for f in shown], indent=2))
	else:
		for f in shown:
			print(f"{f.severity:8} {f.category:16} {f.file}:{f.line}  {f.detail}")

		counts = Counter(f.severity for f in all_findings)
		by_category = Counter(f.category for f in all_findings if f.severity == "BLOCKER")
		print(
			f"\n{len(all_findings)} findings: "
			f"{counts['BLOCKER']} blocker, {counts['WARNING']} warning, {counts['NOTE']} note"
		)
		if by_category:
			print("blockers by category: " + ", ".join(f"{k}={v}" for k, v in by_category.most_common()))

	return 1 if any(f.severity == "BLOCKER" for f in all_findings) else 0


if __name__ == "__main__":
	sys.exit(main())

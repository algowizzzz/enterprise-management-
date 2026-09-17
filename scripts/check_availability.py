#!/usr/bin/env python3
"""Check whether this machine can obtain everything Frappe needs.

Run this on the locked-down box (managed laptop, on-prem server, build agent). It
reports what is reachable and what is blocked, so you can hand a specific list
to your network team instead of "pip didn't work".

    python check_availability.py                  # check everything
    python check_availability.py --pypi-only      # skip GitHub / binaries
    python check_availability.py --target-windows # ask PyPI for win_amd64 wheels

Nothing is installed and nothing is written outside a temp directory.
Exit code 0 if every REQUIRED item is available, 1 otherwise.

It deliberately uses whatever pip is configured to use, so an internal package
mirror is exercised exactly as a real install would be.
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent

GITHUB_ARTIFACTS = [
	(
		"frappe framework",
		"https://github.com/frappe/frappe/archive/refs/tags/v15.121.0.zip",
		True,
		"The framework itself. PyPI only has a 0.0.1 placeholder.",
	),
	(
		"PyPika (frappe fork)",
		"https://github.com/frappe/pypika/archive/2c50e6142b2d61d2d243e466fdd5dc03b3d918f2.zip",
		True,
		"Do NOT substitute PyPI's PyPika -- same version number, different library.",
	),
	(
		"air-datepicker (npm)",
		"https://codeload.github.com/frappe/air-datepicker/tar.gz/ed37b94d95c68d8544357e330be0c89d044a3eea",
		False,
		"Build-time only. Skippable if you ship prebuilt sites/assets/.",
	),
]

# Packages with no win_amd64 wheel on PyPI. All were inspected for C extensions
# and are pure Python, so pip builds them locally on Windows with no compiler.
# Knowing them up front keeps this to two pip invocations instead of one per
# failure; anything unexpected still falls back to the retry loop below.
KNOWN_SDIST_ONLY = {
	"cairocffi",
	"docopt",
	"maxminddb-geolite2",
	"pyqrcode",
	"rauth",  # ships only a py2-none-any wheel, which pip rejects for 3.11
	"traceback-with-variables",
	"zxcvbn",
}

BINARIES = [
	("python", True, "3.11 recommended"),
	("psql", True, "PostgreSQL client; the server may be remote (RDS is fine)"),
	("node", False, "Only for `winbench build` and the realtime server"),
	("yarn", False, "Only for `winbench build`"),
	("git", False, "Optional -- use `winbench init --from-archive` instead"),
	("wkhtmltopdf", False, "Only for PDF print formats"),
]


class Report:
	def __init__(self):
		self.rows: list[tuple[str, str, bool, bool, str]] = []

	def add(self, section, name, ok, required, detail=""):
		self.rows.append((section, name, ok, required, detail))
		mark = "ok  " if ok else ("FAIL" if required else "warn")
		print(f"  [{mark}] {name}" + (f" -- {detail}" if detail else ""))

	def blocking(self):
		return [r for r in self.rows if r[3] and not r[2]]

	def optional_missing(self):
		return [r for r in self.rows if not r[3] and not r[2]]


def check_pip_config(report: Report):
	print("\n== pip configuration (what your install will actually talk to) ==")
	index = os.environ.get("PIP_INDEX_URL") or os.environ.get("PIP_EXTRA_INDEX_URL")
	if not index:
		try:
			out = subprocess.run(
				[sys.executable, "-m", "pip", "config", "list"],
				capture_output=True,
				text=True,
				timeout=60,
			).stdout
			index = next(
				(l.split("=", 1)[1].strip().strip("'\"") for l in out.splitlines() if "index-url" in l),
				None,
			)
		except Exception:
			index = None
	print(f"  index-url: {index or 'https://pypi.org/simple (default)'}")
	for var in ("HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY"):
		if os.environ.get(var):
			print(f"  {var}={os.environ[var]}")


def _parse_requirements(path: Path) -> list[str]:
	lines = []
	for raw in path.read_text().splitlines():
		line = raw.split("#", 1)[0].strip()
		if line:
			lines.append(line)
	return lines


def _pip_download(specs: list[str], dest: str, platform_args: list[str]) -> tuple[int, str, list[str]]:
	"""Download `specs`; return (rc, output, packages pip could not resolve)."""
	with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as fh:
		fh.write("\n".join(specs) + "\n")
		req_file = fh.name
	try:
		proc = subprocess.run(
			[sys.executable, "-m", "pip", "download", "-r", req_file, "-d", dest, *platform_args],
			capture_output=True,
			text=True,
		)
	finally:
		os.unlink(req_file)

	output = proc.stdout + proc.stderr
	unresolved = []
	for line in output.splitlines():
		low = line.lower()
		if "could not find a version that satisfies the requirement" in low:
			# "...requirement cairocffi==1.5.1 (from versions: ...)"
			part = line.split("requirement", 1)[1].strip()
			unresolved.append(part.split(" ")[0])
	# pip stops at the first failure, so treat a non-zero rc with no parsed name
	# as an unknown/transport failure rather than silently reporting success.
	return proc.returncode, output, unresolved


def check_pypi(report: Report, target_windows: bool, requirements: Path):
	print(f"\n== PyPI packages ({requirements.name}) ==")
	if not requirements.exists():
		report.add("pypi", str(requirements), False, True, "file not found")
		return

	specs = _parse_requirements(requirements)
	print(f"  {len(specs)} pinned packages")

	# --no-deps is essential, not an optimisation. requirements.txt is already a
	# complete flattened set (it came from a freeze), and without --no-deps pip
	# chases transitive dependencies -- so under --only-binary=:all: it fails on
	# a sdist-only package (docopt) pulled in by another package (num2words)
	# even when that package is excluded from the file. Downloading each pinned
	# spec independently is both correct and ~100x faster.
	base = ["--no-deps"]

	with tempfile.TemporaryDirectory() as tmp:
		if not target_windows:
			rc, output, unresolved = _pip_download(specs, tmp, base)
			if rc == 0:
				report.add(
					"pypi", "PyPI packages", True, True,
					f"{len(list(Path(tmp).iterdir()))} distributions resolved",
				)
			else:
				detail = ", ".join(unresolved) if unresolved else _first_interesting(output)
				report.add("pypi", "PyPI packages", False, True, detail[:200])
			return

		# Windows target: wheels for everything that has one, sdists for the rest.
		print("  resolving win_amd64 / cp311 wheels\n")
		wheel_specs = [r for r in specs if _norm(r) not in KNOWN_SDIST_ONLY]
		sdist_specs = [r for r in specs if _norm(r) in KNOWN_SDIST_ONLY]

		rc, output, unresolved = _pip_download(
			wheel_specs,
			tmp,
			[*base, "--platform", "win_amd64", "--python-version", "3.11", "--only-binary=:all:"],
		)
		if rc != 0:
			# A package we expected to have a Windows wheel does not. Retry it as
			# an sdist rather than calling it unavailable -- but say so, because
			# it means this list needs updating.
			if unresolved:
				print(f"         no win_amd64 wheel (not in the known list): {', '.join(unresolved)}")
				sdist_specs += [r for r in wheel_specs if _norm(r) in {_norm(u) for u in unresolved}]
				wheel_specs = [r for r in wheel_specs if _norm(r) not in {_norm(u) for u in unresolved}]
				rc, output, unresolved = _pip_download(
					wheel_specs,
					tmp,
					[*base, "--platform", "win_amd64", "--python-version", "3.11", "--only-binary=:all:"],
				)
			if rc != 0:
				detail = ", ".join(unresolved) if unresolved else _first_interesting(output)
				report.add("pypi", "win_amd64 wheels", False, True, detail[:200])
				return

		wheels = len(list(Path(tmp).iterdir()))

		rc2, output2, unresolved2 = _pip_download(sdist_specs, tmp, base)
		if rc2 != 0:
			detail = ", ".join(unresolved2) if unresolved2 else _first_interesting(output2)
			report.add("pypi", "pure-Python sdists", False, True, detail[:200])
			return

		report.add(
			"pypi", "PyPI packages", True, True,
			f"{wheels} win_amd64 wheels + {len(sdist_specs)} pure-Python sdists",
		)
		print(f"         no win_amd64 wheel, but pure Python (no compiler needed):")
		print(f"           {', '.join(sorted(_norm(r) for r in sdist_specs))}")


def _norm(spec: str) -> str:
	return spec.split("==")[0].strip().lower().replace("_", "-")


def _first_interesting(output: str) -> str:
	for line in output.splitlines():
		low = line.lower()
		if any(k in low for k in ("connection", "proxy", "403", "timed out", "certificate", "ssl", "no matching")):
			return line.strip()
	tail = [l for l in output.splitlines() if l.strip()]
	return tail[-1] if tail else "pip failed with no output"


def check_url(name, url, required, note, report: Report):
	req = urllib.request.Request(url, method="GET", headers={"User-Agent": "frappe-availability-check"})
	try:
		with urllib.request.urlopen(req, timeout=60) as r:
			# Read a little to confirm the body actually flows, not just the headers.
			chunk = r.read(2048)
			ok = r.status == 200 and len(chunk) > 0
			report.add("github", name, ok, required, f"HTTP {r.status}, body flowing" if ok else f"HTTP {r.status}")
	except urllib.error.HTTPError as e:
		report.add("github", name, False, required, f"HTTP {e.code} -- {note}")
	except Exception as e:
		report.add("github", name, False, required, f"{type(e).__name__}: {str(e)[:80]} -- {note}")


def check_github(report: Report):
	print("\n== GitHub artifacts (not available on PyPI) ==")
	for name, url, required, note in GITHUB_ARTIFACTS:
		check_url(name, url, required, note, report)


def check_binaries(report: Report):
	print("\n== external programs ==")
	for name, required, note in BINARIES:
		path = shutil.which(name)
		report.add("binary", name, bool(path), required, path or f"not on PATH -- {note}")
	print("\n  Redis is not checked here: it has no official Windows build.")
	print("  Install Memurai (https://www.memurai.com) and run `winbench doctor`")
	print("  against a real bench to test the live connections.")


def main() -> int:
	parser = argparse.ArgumentParser()
	parser.add_argument("--pypi-only", action="store_true")
	parser.add_argument("--skip-pypi", action="store_true", help="Skip the slow download step")
	parser.add_argument(
		"--target-windows",
		action="store_true",
		help="Resolve win_amd64 wheels instead of this machine's platform",
	)
	parser.add_argument("--requirements", default=str(ROOT / "requirements.txt"))
	args = parser.parse_args()

	print("Frappe dependency availability check")
	print(f"python  : {sys.version.split()[0]} ({sys.executable})")
	print(f"platform: {sys.platform}")

	report = Report()
	check_pip_config(report)
	if not args.skip_pypi:
		check_pypi(report, args.target_windows, Path(args.requirements))
	if not args.pypi_only:
		check_github(report)
		check_binaries(report)

	print("\n" + "=" * 70)
	blocking = report.blocking()
	optional = report.optional_missing()

	if blocking:
		print(f"BLOCKED -- {len(blocking)} required item(s) unavailable:\n")
		for _, name, _, _, detail in blocking:
			print(f"  * {name}\n      {detail}")
		print("\nTake this list to your network team. Everything above is needed to")
		print("install Frappe; nothing else in the stack is.")
	else:
		print("All required dependencies are reachable from this machine.")

	if optional:
		print(f"\nOptional and missing ({len(optional)}) -- not blockers:")
		for _, name, _, _, detail in optional:
			print(f"  - {name}: {detail}")

	return 1 if blocking else 0


if __name__ == "__main__":
	sys.exit(main())

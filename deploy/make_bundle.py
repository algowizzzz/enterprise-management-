#!/usr/bin/env python3
"""Build a self-contained installation bundle for an offline target.

The deployment target has no internet access. Nothing may be fetched during
installation — not a Python package, not a front-end library, not a font. So
everything the target needs is collected here, on a machine that does have
network access, into a single archive that is carried across.

    # for a machine like this one
    python deploy/make_bundle.py --frappe-src <framework source> --out dist/

    # for a Linux server, built on any machine (a Mac, a Windows laptop, ...)
    python deploy/make_bundle.py --frappe-src <framework source> --out dist/ \\
        --target-platform linux_x86_64 --target-python 3.12

What goes in:

  wheelhouse/     every Python dependency as a built wheel, including the
                  framework itself, this application and its launcher
  assets/         the prebuilt front-end asset bundle, so the target needs
                  neither node nor a package manager
  install/        the deployment kit (install, upgrade, backup, restore,
                  verify), the health check, the reference data and its loader,
                  the acceptance checks, the pinned requirement set the
                  installer resolves against, and the service and
                  reverse-proxy templates
  vendor/         the PDF engine (wkhtmltopdf 0.12.6 with patched Qt) as the
                  project's official .deb and .rpm packages for the target's
                  architecture, each checked against a pinned SHA-256
  docs/           the guides the built-in help assistant answers from. The
                  application reads them at runtime; a wheel does not carry
                  them, so without this the assistant answers from the page map
                  alone and says nothing about how anything works
  MANIFEST.json   what is in the bundle, which versions, which interpreter and
                  platform the wheels are for, and a checksum for every file
  SHA256SUMS      checksums again, in the standard format, so the target can
                  verify with `sha256sum -c` and no special tooling

**A bundle is built for one target**: one operating system, one processor
architecture, one Python minor version. Most dependencies are pure Python, but
about twenty ship compiled code (the database driver, the image library, the
cryptography library, ...), and a wheel for one platform will not install on
another. The installer checks the manifest against the host before it changes
anything, so a mismatch is a clear refusal rather than a cryptic pip error.

Cross-building (``--target-platform``) downloads the target's published wheels
for every dependency that has them and builds the rest — only pure-Python
packages, whose wheels run anywhere — locally. A dependency that has neither a
wheel for the target nor a pure-Python build fails the build here: it would
need a compiler on the target, and the target has none.

The bundle is verified on the way out: the script re-resolves the wheelhouse
with `--no-index` (for the target's platform and Python) and fails if pip
cannot satisfy the installer's two steps from local files alone. A bundle that
cannot install offline here will not install offline there, and finding that
out on the target — where there is no way to fetch the missing piece — is
expensive.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DEPLOY = REPO / "deploy"

# The framework's own fork of PyPika. The package of the same name on PyPI
# reports the same version but is a different library: the fork rewrites much
# of terms.py, queries.py and dialects.py, which are the modules the framework
# leans on most. The wrong one installs cleanly and answers simple queries
# correctly, so the failure is silent and turns up much later.
PYPIKA_FORK = (
    "PyPika @ git+https://github.com/frappe/pypika@2c50e6142b2d61d2d243e466fdd5dc03b3d918f2"
)
# sha256 of pypika/terms.py in the fork at the pinned commit (the first 16 hex
# digits, as docs/KNOWLEDGE-BASE.md §2.1 records it). PyPI's package of the same
# version has a different terms.py.
PYPIKA_FORK_TERMS_SHA256_PREFIX = "a9764727b433119d"

# Platforms a bundle can be cross-built for, and the pip platform tags that
# match them. Linux wheels are published against a minimum glibc; the range
# 2.17 to 2.34 covers every current enterprise distribution (RHEL 8 and 9 and
# their rebuilds, Ubuntu 20.04 onwards, Debian 11 onwards). pip does not widen
# an explicit manylinux_2_x tag to the older ones itself, so each is listed.
_GLIBC = range(17, 35)
TARGETS = {
    "linux_x86_64": ("linux", "x86_64",
                     [f"manylinux_2_{n}_x86_64" for n in _GLIBC] + ["manylinux2014_x86_64"]),
    "linux_aarch64": ("linux", "aarch64",
                      [f"manylinux_2_{n}_aarch64" for n in _GLIBC] + ["manylinux2014_aarch64"]),
    "win_amd64": ("win32", "AMD64", ["win_amd64"]),
}

# The PDF engine. The framework renders every PDF with wkhtmltopdf 0.12.6 built
# against its patched Qt (the distributions' own packages are unpatched and
# lose headers, footers and page breaks). These are the project's official
# release packages; it publishes no checksums, so the SHA-256 of each was
# recorded when first fetched and every later build must match it byte for
# byte. The .deb is built on Ubuntu 22.04 and installs on 24.04; the .rpm
# builds are for RHEL 8 and 9 and their rebuilds.
WKHTMLTOPDF_VERSION = "0.12.6.1-3"
WKHTMLTOPDF_URL = "https://github.com/wkhtmltopdf/packaging/releases/download/0.12.6.1-3/"
WKHTMLTOPDF_PACKAGES = {
    # file name: (target machine, sha256)
    "wkhtmltox_0.12.6.1-3.jammy_amd64.deb":
        ("x86_64", "4f723b2691ad8638a9df960e0421d346d7315083e3583a334f33362280ddba15"),
    "wkhtmltox_0.12.6.1-3.jammy_arm64.deb":
        ("aarch64", "2095f20256661ebf0983b9311168596c9d012666e21a94bc24f304db6ac69ec5"),
    "wkhtmltox-0.12.6.1-3.almalinux8.x86_64.rpm":
        ("x86_64", "049e40347bddec37a03ad61766135e1b190484949dbecff84d1435bbb63e8b0d"),
    "wkhtmltox-0.12.6.1-3.almalinux8.aarch64.rpm":
        ("aarch64", "410cb67e4ea4293baf538a5af6bd403107c82bc28c6fdc193a107ecd0169300b"),
    "wkhtmltox-0.12.6.1-3.almalinux9.x86_64.rpm":
        ("x86_64", "357a587c82f1c8a5faf78cebb0a387f780ca51db81d9d8350af27e0bc603524b"),
    "wkhtmltox-0.12.6.1-3.almalinux9.aarch64.rpm":
        ("aarch64", "fa3545bfb64666f0492b7673e0b58feefe56f34af0bf88916d0269f57ae36479"),
}


def collect_pdf_engine(destination: Path, target: "Target", cache: Path) -> list[dict]:
    """Copy the PDF engine packages for the target's architecture into the bundle."""
    if target.sys_platform != "linux":
        print(f"  no packaged PDF engine for {target.sys_platform}; install wkhtmltopdf "
              f"{WKHTMLTOPDF_VERSION} (with patched Qt) on the target separately")
        return []
    import urllib.request

    destination.mkdir(parents=True, exist_ok=True)
    cache.mkdir(parents=True, exist_ok=True)
    records = []
    for name, (machine, digest) in sorted(WKHTMLTOPDF_PACKAGES.items()):
        if machine != target.machine:
            continue
        cached = cache / name
        if not cached.exists() or sha256(cached) != digest:
            print(f"  fetching {name} from the project's release page")
            with urllib.request.urlopen(WKHTMLTOPDF_URL + name, timeout=120) as r, cached.open("wb") as fh:
                shutil.copyfileobj(r, fh)
        actual = sha256(cached)
        if actual != digest:
            cached.unlink()
            raise SystemExit(f"{name} does not match its recorded checksum (got {actual}); refusing to ship it")
        shutil.copy2(cached, destination / name)
        records.append({"name": name, "version": WKHTMLTOPDF_VERSION, "url": WKHTMLTOPDF_URL + name,
                        "sha256": digest})
    print(f"  PDF engine: {len(records)} packages for {target.machine}, checksums verified")
    return records


# The deployment kit: what travels in install/. Each is optional here only so
# an older checkout can still be bundled; the installer names what it needs.
KIT_FILES = (
    ("deploy/install.sh", "install.sh"),
    ("deploy/install.ps1", "install.ps1"),
    ("deploy/upgrade.sh", "upgrade.sh"),
    ("deploy/backup.sh", "backup.sh"),
    ("deploy/restore.sh", "restore.sh"),
    ("deploy/verify.sh", "verify.sh"),
    ("deploy/kit.py", "kit.py"),
    ("deploy/consilium.conf.example", "consilium.conf.example"),
    ("deploy/healthcheck.py", "healthcheck.py"),
    ("deploy/seed.py", "seed.py"),
    ("deploy/configure_site.py", "configure_site.py"),
    ("deploy/acceptance.py", "acceptance.py"),
    ("scripts/smoke_test.py", "smoke_test.py"),
    ("scripts/ui_regression.py", "ui_regression.py"),
    ("scripts/load_test.py", "load_test.py"),
)

# The documents the help assistant reads at runtime, relative to docs/. The
# assistant looks for the first three by these names under the directory the
# site's `assistant_docs_path` names. The guides folder is the illustrated
# onboarding guide: its chapters are what the in-platform guide reader (/guide)
# shows and the assistant cites, and guides/images holds every picture they use.
ASSISTANT_DOCS = ("USER-GUIDE.md", "ADMIN-GUIDE.md", "product/05-glossary.md", "guides")


def run(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    printable = " ".join(str(c) for c in cmd)
    print(f"  $ {printable[:150]}")
    return subprocess.run(cmd, check=True, **kw)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def requirement_lines(path: Path) -> list[str]:
    lines = []
    for raw in path.read_text().splitlines():
        line = raw.split("#", 1)[0].strip()
        if line:
            lines.append(line)
    return lines


def requirement_name(line: str) -> str:
    return re.split(r"[<>=!~\[; @]", line, maxsplit=1)[0].strip()


def canonical(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def verify_pypika_fork(wheelhouse: Path) -> None:
    """Check the PyPika wheel is the fork by its content, not its version string."""
    wheels = sorted(wheelhouse.glob("[Pp]y[Pp]ika-*.whl"))
    if len(wheels) != 1:
        raise SystemExit(f"expected exactly one PyPika wheel, found {[w.name for w in wheels]}")
    with zipfile.ZipFile(wheels[0]) as zf:
        digest = hashlib.sha256(zf.read("pypika/terms.py")).hexdigest()
    if not digest.startswith(PYPIKA_FORK_TERMS_SHA256_PREFIX):
        raise SystemExit(
            f"{wheels[0].name} is not the framework's fork of PyPika (terms.py hashes to "
            f"{digest[:16]}, the fork to {PYPIKA_FORK_TERMS_SHA256_PREFIX}). It would install "
            f"cleanly and build subtly different queries."
        )
    print(f"  {wheels[0].name} verified as the framework's fork by content")


class Target:
    """Which interpreter and platform the wheels are for."""

    def __init__(self, platform_name: str | None, python_version: str | None, python: str):
        self.python = python  # the interpreter that runs pip here
        self.cross = platform_name is not None
        if self.cross:
            if platform_name not in TARGETS:
                raise SystemExit(f"--target-platform must be one of {sorted(TARGETS)}")
            self.sys_platform, self.machine, self.tags = TARGETS[platform_name]
            self.name = platform_name
            if not python_version or not re.fullmatch(r"3\.\d+", python_version):
                raise SystemExit("--target-python is required with --target-platform, e.g. 3.12")
            self.python_version = python_version
        else:
            out = subprocess.run(
                [python, "-c", "import sys, platform; print(sys.platform, platform.machine(), "
                               "'%d.%d' % sys.version_info[:2])"],
                capture_output=True, text=True, check=True).stdout.split()
            self.sys_platform, self.machine, self.python_version = out
            self.tags = []
            self.name = f"{self.sys_platform}_{self.machine}"

    def pip_target_args(self) -> list[str]:
        """Flags that make pip resolve for the target rather than this machine."""
        if not self.cross:
            return []
        nodot = self.python_version.replace(".", "")
        args = ["--only-binary=:all:", "--implementation", "cp",
                "--python-version", self.python_version, "--abi", f"cp{nodot}",
                "--abi", "abi3", "--abi", "none"]
        for tag in self.tags:
            args += ["--platform", tag]
        return args


def collect_dependency_wheels(wheelhouse: Path, requirements: Path, target: Target) -> None:
    python = target.python
    if not target.cross:
        # `pip wheel` rather than `pip download --only-binary`, because a handful
        # of the pinned dependencies publish no wheel for the pinned version —
        # the framework pins cairocffi to a version that exists only as an
        # sdist, for one. Those are pure Python, so building a wheel here needs
        # no compiler and leaves the target with a wheelhouse it can install
        # from directly. If this step ever fails for want of a compiler, that is
        # a dependency that must not ship: the target cannot build it either.
        run([python, "-m", "pip", "wheel", "--no-deps", "-r", str(requirements), "-w", str(wheelhouse)],
            stdout=subprocess.DEVNULL)
        return

    # Cross-build. Download the target's wheels for everything that publishes
    # them. pip stops at the first requirement with no wheel, so each refusal
    # moves that one requirement to the build-it-here list and the download is
    # repeated; files already fetched are not fetched again.
    pending = requirement_lines(requirements)
    build_here: list[str] = []
    with tempfile.TemporaryDirectory(prefix="bundle-reqs-") as scratch:
        for _ in range(len(pending) + 1):
            req_file = Path(scratch) / "pending.txt"
            req_file.write_text("\n".join(pending) + "\n")
            result = subprocess.run(
                [python, "-m", "pip", "download", "--no-deps", "-d", str(wheelhouse),
                 *target.pip_target_args(), "-r", str(req_file)],
                capture_output=True, text=True)
            if result.returncode == 0:
                break
            missing = re.search(r"No matching distribution found for (\S+)", result.stderr)
            if not missing:
                tail = "\n".join(result.stderr.strip().splitlines()[-10:])
                raise SystemExit(f"pip download failed for the target:\n{tail}")
            name = canonical(requirement_name(missing.group(1)))
            match = [line for line in pending if canonical(requirement_name(line)) == name]
            if not match:
                raise SystemExit(f"pip could not find {missing.group(1)} and it is not in the requirement set")
            pending.remove(match[0])
            build_here.append(match[0])
        else:
            raise SystemExit("could not settle which dependencies need building")
    print(f"  {len(pending)} downloaded as {target.name} wheels; "
          f"{len(build_here)} publish none and are built here: {', '.join(build_here) or '(none)'}")

    for line in build_here:
        with tempfile.TemporaryDirectory(prefix="bundle-build-") as out:
            run([python, "-m", "pip", "wheel", "--no-deps", "-w", out, line], stdout=subprocess.DEVNULL)
            for wheel in Path(out).glob("*.whl"):
                # Only a pure-Python wheel runs on another platform. Anything
                # else means compiled code, which the target cannot build.
                if not wheel.name.endswith("-none-any.whl"):
                    raise SystemExit(
                        f"{line} publishes no {target.name} wheel and builds to {wheel.name}, "
                        f"which is platform-specific: it needs a compiler. It cannot ship.")
                shutil.move(str(wheel), wheelhouse / wheel.name)


def collect_wheels(wheelhouse: Path, frappe_src: Path, source: Path, target: Target) -> None:
    wheelhouse.mkdir(parents=True, exist_ok=True)
    python = target.python

    print(f"\n[1/4] Collecting dependency wheels for {target.name}, Python {target.python_version}")
    collect_dependency_wheels(wheelhouse, source / "requirements.txt", target)

    print("\n[2/4] Building the framework fork of PyPika")
    run([python, "-m", "pip", "wheel", "--no-deps", "-w", str(wheelhouse), PYPIKA_FORK],
        stdout=subprocess.DEVNULL)
    # pip also leaves the upstream sdist behind; it must not ship, or a target
    # resolving from the wheelhouse could pick the wrong PyPika.
    for stray in wheelhouse.glob("PyPika-*.tar.gz"):
        print(f"  removing upstream sdist that must not ship: {stray.name}")
        stray.unlink()
    verify_pypika_fork(wheelhouse)

    print("\n[3/4] Building the framework, the application and the launcher")
    for src in (frappe_src, source / "apps" / "consilium", REPO / "winbench"):
        if not src.exists():
            raise SystemExit(f"cannot build a wheel: {src} does not exist")
        with tempfile.TemporaryDirectory(prefix="bundle-src-") as scratch:
            # Built from a copy: a setuptools build writes build/ and *.egg-info
            # into the tree it builds, and this checkout tracks winbench/build.
            copy = Path(scratch) / src.name
            skip = [".git", "__pycache__", "*.egg-info", "node_modules"]
            if src.name == "winbench":
                skip.append("build")
            shutil.copytree(src, copy, symlinks=True, ignore=shutil.ignore_patterns(*skip))
            run([python, "-m", "pip", "wheel", "--no-deps", "-w", str(wheelhouse), str(copy)],
                stdout=subprocess.DEVNULL)


# The three wheels installed with --no-deps. The framework's metadata names
# dependencies deliberately not shipped (its gunicorn fork, replaced by waitress;
# the geo-IP data package, see requirements.txt) and git URLs.
NO_DEPS = {"frappe", "consilium", "winbench"}


def verify_closure(wheelhouse: Path, target: Target, fetch_missing: bool = True) -> list[str]:
    """Every dependency of every wheel, for the target, is in the wheelhouse.

    pip cannot check this for another platform: it evaluates environment
    markers (``; sys_platform == "linux"``) against the machine it runs on, so a
    dependency needed only on Linux is invisible from a Mac, and one needed only
    on a Mac is demanded for Linux. So read each wheel's declared dependencies
    and evaluate the markers for the target instead.
    """
    try:
        from packaging.markers import default_environment
        from packaging.requirements import Requirement
    except ImportError:  # pip always carries a copy
        from pip._vendor.packaging.markers import default_environment
        from pip._vendor.packaging.requirements import Requirement

    base_env = default_environment()
    base_env.update({
        "sys_platform": target.sys_platform,
        "platform_system": {"linux": "Linux", "win32": "Windows", "darwin": "Darwin"}[target.sys_platform],
        "os_name": "nt" if target.sys_platform == "win32" else "posix",
        "platform_machine": target.machine,
        "python_version": target.python_version,
        "implementation_name": "cpython",
        "platform_python_implementation": "CPython",
    })
    # A distribution may ship any patch release of the minor version — Ubuntu
    # 22.04's python3.11 is 3.11.0 — and some dependencies differ by patch
    # release (redis needs async-timeout up to 3.11.2). Check the first and a
    # late one.
    envs = [dict(base_env, python_full_version=f"{target.python_version}.{patch}") for patch in (0, 99)]

    def scan() -> tuple[list[str], list[str]]:
        available = {}
        for wheel in wheelhouse.glob("*.whl"):
            name, version = wheel.name.split("-")[:2]
            available[canonical(name)] = version
        missing, fetchable = [], []
        for wheel in sorted(wheelhouse.glob("*.whl")):
            owner = canonical(wheel.name.split("-")[0])
            if owner in NO_DEPS:
                continue
            with zipfile.ZipFile(wheel) as zf:
                meta_name = next(n for n in zf.namelist() if n.endswith(".dist-info/METADATA"))
                metadata = zf.read(meta_name).decode("utf-8", "replace")
            for line in metadata.splitlines():
                if not line.startswith("Requires-Dist:"):
                    continue
                req = Requirement(line.split(":", 1)[1].strip())
                if req.marker and not any(req.marker.evaluate({**e, "extra": ""}) for e in envs):
                    continue
                have = available.get(canonical(req.name))
                if have is None:
                    missing.append(f"{req.name} (needed by {wheel.name.split('-')[0]}: {req})")
                    fetchable.append(f"{req.name}{req.specifier}")
                elif req.specifier and not req.specifier.contains(have, prereleases=True):
                    missing.append(f"{req.name} {have} does not satisfy {req} (needed by {wheel.name.split('-')[0]})")
        return sorted(set(missing)), sorted(set(fetchable))

    added: list[str] = []
    for _ in range(5):
        missing, fetchable = scan()
        if not missing:
            break
        if not (fetch_missing and target.cross and len(fetchable) == len(missing)):
            raise SystemExit("The bundle is missing dependencies the target will ask for:\n  "
                             + "\n  ".join(missing))
        # Needed only on some patch releases of the target Python, so absent
        # from a requirement set frozen on another. Carried anyway: unused, a
        # wheel costs a few kilobytes; missing, it stops an offline install.
        for spec in fetchable:
            run([target.python, "-m", "pip", "download", "--no-deps", "-d", str(wheelhouse),
                 *target.pip_target_args(), spec], stdout=subprocess.DEVNULL)
            added.append(spec)
    else:
        raise SystemExit("could not complete the dependency set")
    count = len(list(wheelhouse.glob("*.whl")))
    print(f"  every dependency of {count} wheels is present for {target.name}, any Python "
          f"{target.python_version}.x" + (f"; added for older patch releases: {', '.join(added)}" if added else ""))
    return added


def verify_offline(wheelhouse: Path, requirements: Path, target: Target) -> None:
    """Prove the wheelhouse alone can satisfy what the installer asks of it.

    Two resolutions, mirroring the installer's two steps. The dependency set
    resolves with dependencies followed; the framework, the application and the
    launcher resolve with ``--no-deps``, because the framework's own metadata
    names two dependencies by git URL and pip honours those even under
    ``--no-index`` — following them would make the "offline" install reach for
    the network, and fail on a host that has none.
    """
    print("\n[4/4] Verifying the bundle resolves with no index")
    # A temporary directory rather than a literal /tmp path, which does not
    # exist on Windows.
    with tempfile.TemporaryDirectory(prefix="bundle-check-") as scratch:
        # Cross-built: pip would judge environment markers by this machine, so
        # resolve without following dependencies and check them separately.
        follow = ["--no-deps"] if target.cross else []
        checks = (
            ("the requirement set",
             [*follow, "-r", str(requirements), "PyPika==0.48.9"]),
            ("the framework, application and launcher",
             ["--no-deps", "frappe", "consilium", "winbench"]),
        )
        for label, args in checks:
            result = subprocess.run(
                [target.python, "-m", "pip", "install", "--dry-run", "--ignore-installed",
                 "--no-index", "--find-links", str(wheelhouse),
                 "--target", scratch, *target.pip_target_args(), *args],
                capture_output=True, text=True,
            )
            if result.returncode != 0:
                tail = "\n".join(result.stderr.strip().splitlines()[-15:])
                raise SystemExit(
                    f"The bundle cannot install {label} offline. Fix this here — on "
                    f"the target there is no way to fetch what is missing.\n\n{tail}"
                )
            print(f"  {label}: resolves from local files alone")
    verify_closure(wheelhouse, target)


def guide_image_gaps(guides: Path) -> list[str]:
    """Pictures a guide chapter refers to that are not in the folder.

    The guide reader serves a chapter's pictures from guides/images; one left
    out of the bundle is a broken picture on every installation made from it.
    """
    gaps = []
    for chapter in sorted(guides.glob("[0-9][0-9]-*.md")):
        for ref in re.findall(r"!\[[^\]]*\]\(\s*(images/[^)\s]+)", chapter.read_text(encoding="utf-8")):
            if not (guides / ref).is_file():
                gaps.append(f"{chapter.name}: {ref}")
    return gaps


def copy_assistant_docs(source: Path, destination: Path) -> int:
    docs = source / "docs"
    copied = 0
    for rel in ASSISTANT_DOCS:
        path = docs / rel
        if not path.exists():
            if source != REPO:
                # Bundling an earlier release that predates the document.
                print(f"  note: {source.name} has no docs/{rel}; that release's assistant goes without it")
                continue
            raise SystemExit(
                f"docs/{rel} is missing. The help assistant and the guide reader read it at "
                f"runtime; without it the platform cannot explain how anything works."
            )
        target = destination / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        if path.is_dir():
            shutil.copytree(path, target)
            copied += sum(1 for p in target.rglob("*") if p.is_file())
            gaps = guide_image_gaps(target) if rel == "guides" else []
            if gaps and source == REPO:
                raise SystemExit("guide pictures are missing from docs/guides/images:\n  " + "\n  ".join(gaps))
        else:
            shutil.copy2(path, target)
            copied += 1
    return copied


def wheel_version(wheelhouse: Path, name: str) -> str | None:
    for wheel in wheelhouse.glob("*.whl"):
        parts = wheel.name.split("-")
        if canonical(parts[0]) == canonical(name):
            return parts[1]
    return None


def build_manifest(staging: Path, target: Target, source: Path) -> dict:
    files = sorted(p for p in staging.rglob("*") if p.is_file())
    entries = []
    for path in files:
        entries.append({
            "path": path.relative_to(staging).as_posix(),
            "bytes": path.stat().st_size,
            "sha256": sha256(path),
        })

    wheelhouse = staging / "wheelhouse"
    wheels = sorted(p.name for p in wheelhouse.glob("*.whl"))
    try:
        commit = subprocess.run(["git", "-C", str(source), "rev-parse", "--short", "HEAD"],
                                capture_output=True, text=True).stdout.strip()
        dirty = bool(subprocess.run(["git", "-C", str(source), "status", "--porcelain", "--", "apps"],
                                    capture_output=True, text=True).stdout.strip())
    except OSError:
        commit, dirty = "", False
    return {
        "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "python": target.python_version,
        "platform": target.sys_platform,
        "machine": target.machine,
        "target": target.name,
        "source_commit": commit + ("+uncommitted" if dirty else ""),
        "versions": {name: wheel_version(wheelhouse, name)
                     for name in ("frappe", "consilium", "winbench", "PyPika")},
        "wheel_count": len(wheels),
        "wheels": wheels,
        "file_count": len(entries),
        "total_bytes": sum(e["bytes"] for e in entries),
        "files": entries,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", default=str(REPO / "dist"), help="where to write the bundle")
    parser.add_argument("--frappe-src", required=True, help="path to the framework source tree")
    parser.add_argument("--source", default=str(REPO),
                        help="the checkout to take the application, its requirement set, reference "
                             "data, documents and assets from (default: this one). The kit itself "
                             "always comes from this checkout. Use it to bundle an earlier release, "
                             "for example a git worktree, to rehearse an upgrade from it.")
    parser.add_argument("--target-platform", choices=sorted(TARGETS), default=None,
                        help="cross-build for this platform instead of the machine running this")
    parser.add_argument("--target-python", default=None, help="with --target-platform: e.g. 3.12")
    parser.add_argument("--python", default=sys.executable, help="the interpreter that runs pip here")
    parser.add_argument("--name", default="consilium-bundle", help="archive name, without .tar.gz")
    parser.add_argument("--cache", default=str(REPO / "dist" / "cache"),
                        help="where downloaded PDF engine packages are kept between builds")
    parser.add_argument("--skip-verify", action="store_true",
                        help="skip the offline resolution check (not recommended)")
    args = parser.parse_args()

    source = Path(args.source).resolve()
    target = Target(args.target_platform, args.target_python, args.python)
    out = Path(args.out).resolve()
    staging = out / args.name
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)

    collect_wheels(staging / "wheelhouse", Path(args.frappe_src).resolve(), source, target)
    if not args.skip_verify:
        verify_offline(staging / "wheelhouse", source / "requirements.txt", target)

    # Prebuilt front-end assets, so the target needs no node and no package manager.
    assets_src = source / "assets"
    if not any(assets_src.glob("frappe-assets-*.tar.gz")):
        raise SystemExit(f"no prebuilt asset bundle in {assets_src}; the interface would render blank")
    shutil.copytree(assets_src, staging / "assets")

    # The deployment kit travels with the bundle.
    install_dir = staging / "install"
    install_dir.mkdir()
    for rel, name in KIT_FILES:
        candidate = REPO / rel
        if candidate.exists():
            shutil.copy2(candidate, install_dir / name)
    # The installer resolves the dependency set against this file, then installs
    # the framework with --no-deps. Without it the installer would have to let
    # pip read the framework's own metadata, which names git URLs.
    shutil.copy2(source / "requirements.txt", install_dir / "requirements.txt")
    # Service definitions and the reverse-proxy template, rendered on the target.
    service_src = DEPLOY / "service"
    if service_src.is_dir():
        shutil.copytree(service_src, install_dir / "service",
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))

    vendor = collect_pdf_engine(staging / "vendor" / "wkhtmltopdf", target, Path(args.cache))

    docs_count = copy_assistant_docs(source, staging / "docs")
    print(f"  bundled {docs_count} help-assistant documents")

    # The seed script is useless without the data it loads, and the failure is
    # quiet: it finds no files, loads nothing, and the installation completes
    # with an empty system that looks fine until someone tries to create a
    # record and finds every dropdown empty.
    reference_src = source / "deploy" / "reference"
    if not reference_src.is_dir():
        raise SystemExit("deploy/reference is missing; the bundle would install an empty system")
    shutil.copytree(reference_src, install_dir / "reference")
    loaded = len(list((install_dir / "reference").glob("*.json")))
    if not loaded:
        raise SystemExit("deploy/reference contains no data files")
    print(f"  bundled {loaded} reference data files")

    manifest = build_manifest(staging, target, source)
    manifest["vendor"] = vendor
    (staging / "MANIFEST.json").write_text(json.dumps(manifest, indent=2) + "\n")
    (staging / "SHA256SUMS").write_text(
        "".join(f"{e['sha256']}  {e['path']}\n" for e in manifest["files"])
    )

    archive = out / f"{args.name}.tar.gz"
    print(f"\nWriting {archive}")
    with tarfile.open(archive, "w:gz") as tar:
        tar.add(staging, arcname="consilium-bundle")

    size_mb = archive.stat().st_size / (1024 * 1024)
    print(f"\nBundle ready: {archive} ({size_mb:.1f} MB)")
    print(f"  for {target.name}, Python {target.python_version}; "
          f"{manifest['wheel_count']} wheels, {manifest['file_count']} files; "
          f"source {manifest['source_commit'] or 'unknown'}")
    print(f"  checksum: {sha256(archive)}")
    print("\nCarry this one file to the target, then: install/install.sh --config <file> --bundle <this file>")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

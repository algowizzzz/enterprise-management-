#!/usr/bin/env python3
"""Build a self-contained installation bundle for an offline target.

The deployment target has no internet access. Nothing may be fetched during
installation — not a Python package, not a front-end library, not a font. So
everything the target needs is collected here, on a machine that does have
network access, into a single archive that is carried across.

    python deploy/make_bundle.py --out dist/

What goes in:

  wheelhouse/     every Python dependency as a built wheel, including the
                  framework itself and this application
  assets/         the prebuilt front-end asset bundle, so the target needs
                  neither node nor a package manager
  install/        the installation scripts and this repository's deployment
                  tooling
  MANIFEST.json   what is in the bundle, which versions, and a checksum for
                  every file
  SHA256SUMS      checksums again, in the standard format, so the target can
                  verify with `sha256sum -c` and no special tooling

The bundle is verified on the way out: the script re-resolves the wheelhouse
with `--no-index` and fails if pip cannot satisfy the requirement set from
local files alone. A bundle that cannot install offline here will not install
offline there, and finding that out on the target — where there is no way to
fetch the missing piece — is expensive.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tarfile
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

# The framework's own fork of PyPika. The package of the same name on PyPI
# reports the same version but is a different library: the fork rewrites much
# of terms.py, queries.py and dialects.py, which are the modules the framework
# leans on most. The wrong one installs cleanly and answers simple queries
# correctly, so the failure is silent and turns up much later.
PYPIKA_FORK = (
    "PyPika @ git+https://github.com/frappe/pypika@2c50e6142b2d61d2d243e466fdd5dc03b3d918f2"
)


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


def collect_wheels(wheelhouse: Path, frappe_src: Path, python: str) -> None:
    wheelhouse.mkdir(parents=True, exist_ok=True)

    print("\n[1/4] Building dependency wheels")
    # `pip wheel` rather than `pip download --only-binary`, because a handful of
    # the pinned dependencies publish no wheel for the pinned version — the
    # framework pins cairocffi to a version that exists only as an sdist, for
    # one. Those are pure Python, so building a wheel here needs no compiler and
    # leaves the target with a wheelhouse it can install from directly. If this
    # step ever fails for want of a compiler, that is a dependency that must not
    # ship: the target cannot build it either.
    run([python, "-m", "pip", "wheel",
         "-r", str(REPO / "requirements.txt"),
         "-w", str(wheelhouse)],
        stdout=subprocess.DEVNULL)

    print("\n[2/4] Building the framework fork of PyPika")
    run([python, "-m", "pip", "wheel", "--no-deps", "-w", str(wheelhouse), PYPIKA_FORK],
        stdout=subprocess.DEVNULL)
    # pip also leaves the upstream sdist behind; it must not ship, or a target
    # resolving from the wheelhouse could pick the wrong PyPika.
    for stray in wheelhouse.glob("PyPika-*.tar.gz"):
        print(f"  removing upstream sdist that must not ship: {stray.name}")
        stray.unlink()

    print("\n[3/4] Building the framework and the application")
    for source in (frappe_src, REPO / "apps" / "consilium", REPO / "winbench"):
        if not source.exists():
            raise SystemExit(f"cannot build a wheel: {source} does not exist")
        run([python, "-m", "pip", "wheel", "--no-deps", "-w", str(wheelhouse), str(source)],
            stdout=subprocess.DEVNULL)


def verify_offline(wheelhouse: Path, python: str) -> None:
    """Prove the wheelhouse alone can satisfy the requirement set."""
    print("\n[4/4] Verifying the bundle resolves with no index")
    result = subprocess.run(
        [python, "-m", "pip", "install",
         "--dry-run", "--no-index", "--find-links", str(wheelhouse),
         "--target", "/tmp/__bundle_check__",
         "-r", str(REPO / "requirements.txt")],
        capture_output=True, text=True,
    )
    shutil.rmtree("/tmp/__bundle_check__", ignore_errors=True)
    if result.returncode != 0:
        tail = "\n".join(result.stderr.strip().splitlines()[-15:])
        raise SystemExit(
            "The bundle cannot install offline. Fix this here — on the target "
            f"there is no way to fetch what is missing.\n\n{tail}"
        )
    print("  the requirement set resolves from local files alone")


def build_manifest(staging: Path) -> dict:
    files = sorted(p for p in staging.rglob("*") if p.is_file())
    entries = []
    for path in files:
        entries.append({
            "path": str(path.relative_to(staging)),
            "bytes": path.stat().st_size,
            "sha256": sha256(path),
        })

    wheels = sorted(p.name for p in (staging / "wheelhouse").glob("*.whl"))
    return {
        "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "python": f"{sys.version_info.major}.{sys.version_info.minor}",
        "platform": sys.platform,
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
    parser.add_argument("--python", default=sys.executable)
    parser.add_argument("--skip-verify", action="store_true",
                        help="skip the offline resolution check (not recommended)")
    args = parser.parse_args()

    out = Path(args.out).resolve()
    staging = out / "consilium-bundle"
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)

    collect_wheels(staging / "wheelhouse", Path(args.frappe_src).resolve(), args.python)
    if not args.skip_verify:
        verify_offline(staging / "wheelhouse", args.python)

    # Prebuilt front-end assets, so the target needs no node and no package manager.
    assets_src = REPO / "assets"
    if assets_src.exists():
        shutil.copytree(assets_src, staging / "assets")

    # The deployment tooling travels with the bundle.
    install_dir = staging / "install"
    install_dir.mkdir()
    for name in ("install.sh", "install.ps1", "healthcheck.py", "seed.py"):
        candidate = REPO / "deploy" / name
        if candidate.exists():
            shutil.copy2(candidate, install_dir / name)

    # The seed script is useless without the data it loads, and the failure is
    # quiet: it finds no files, loads nothing, and the installation completes
    # with an empty system that looks fine until someone tries to create a
    # record and finds every dropdown empty.
    reference_src = REPO / "deploy" / "reference"
    if not reference_src.is_dir():
        raise SystemExit("deploy/reference is missing; the bundle would install an empty system")
    shutil.copytree(reference_src, install_dir / "reference")
    loaded = len(list((install_dir / "reference").glob("*.json")))
    if not loaded:
        raise SystemExit("deploy/reference contains no data files")
    print(f"  bundled {loaded} reference data files")
    if (REPO / "winbench").exists():
        shutil.copytree(REPO / "winbench", staging / "winbench")

    manifest = build_manifest(staging)
    (staging / "MANIFEST.json").write_text(json.dumps(manifest, indent=2) + "\n")
    (staging / "SHA256SUMS").write_text(
        "".join(f"{e['sha256']}  {e['path']}\n" for e in manifest["files"])
    )

    archive = out / "consilium-bundle.tar.gz"
    print(f"\nWriting {archive}")
    with tarfile.open(archive, "w:gz") as tar:
        tar.add(staging, arcname="consilium-bundle")

    size_mb = archive.stat().st_size / (1024 * 1024)
    print(f"\nBundle ready: {archive} ({size_mb:.1f} MB)")
    print(f"  {manifest['wheel_count']} wheels, {manifest['file_count']} files")
    print(f"  checksum: {sha256(archive)}")
    print("\nCarry this one file to the target and follow install/install.sh.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

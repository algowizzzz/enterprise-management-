#!/usr/bin/env python3
"""Enforce the rules this repository is built on.

platform-rules: exempt — this file names every forbidden string in order to find it.

The constraints in CLAUDE.md are the ones that make this software installable
where it has to go. They are also the easiest things to break by accident: a
CDN link pasted from a tutorial, a dependency that quietly needs a compiler, a
client's name left in a comment. None of those fail a unit test, and all of
them fail on the target — or, in the last case, fail in public.

So they are checked mechanically.

    python scripts/check_platform_rules.py

Exit code 0 if every rule holds, 1 otherwise.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

RED, GREEN, YELLOW, DIM, RESET = "\033[31m", "\033[32m", "\033[33m", "\033[2m", "\033[0m"

# Directories whose contents are third-party and must not be edited: their
# checksums are recorded, and changing a byte breaks verification on the target.
VENDORED = ("public/vendor", "assets/")

SKIP_DIRS = {".git", "__pycache__", "node_modules", ".pytest_cache", "dist", ".venv", "env"}

TEXT_SUFFIXES = {".py", ".js", ".css", ".html", ".md", ".txt", ".json", ".yml",
                 ".yaml", ".sh", ".ps1", ".toml", ".cfg", ".ini"}

# A file that must name a forbidden string in order to detect or document it
# carries this marker. Kept as a convention rather than a filename list, so a
# new checker or a runbook does not need this script edited to be exempt.
EXEMPT = "platform-rules: exempt"

failures: list[tuple[str, list[str]]] = []
passes: list[tuple[str, str]] = []


def walk_text_files():
    for path in REPO.rglob("*"):
        if not path.is_file() or path.suffix not in TEXT_SUFFIXES:
            continue
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        rel = str(path.relative_to(REPO))
        if any(v in rel for v in VENDORED):
            continue
        yield path, rel


def rule(name: str):
    def decorator(fn):
        problems = fn()
        if problems:
            failures.append((name, problems))
        else:
            passes.append((name, fn.__doc__ or ""))
        return fn
    return decorator


@rule("No CDN or external asset references")
def _():
    """Every asset is vendored; the target has no internet access."""
    markers = ("//cdn.", "cdnjs.cloudflare", "jsdelivr.net", "unpkg.com",
               "fonts.googleapis.com", "ajax.googleapis.com", "code.jquery.com",
               "stackpath.bootstrapcdn", "maxcdn.bootstrapcdn")
    found = []
    for path, rel in walk_text_files():
        text = path.read_text(errors="ignore")
        if EXEMPT in text:
            continue
        for marker in markers:
            if marker in text:
                for i, line in enumerate(text.splitlines(), 1):
                    if marker in line:
                        found.append(f"{rel}:{i}  {marker}")
    return found


@rule("No package manager in the build")
def _():
    """No npm or yarn step: those pull hundreds of packages the target cannot reach."""
    found = []
    patterns = (re.compile(r"\b(npm|yarn)\s+(install|ci|add|run\s+build)\b"),)
    for path, rel in walk_text_files():
        text = path.read_text(errors="ignore")
        if rel.startswith("docs/") or EXEMPT in text:
            continue  # prose may legitimately discuss why these are absent
        for i, line in enumerate(text.splitlines(), 1):
            if line.lstrip().startswith("#") or line.lstrip().startswith("//"):
                continue
            for pattern in patterns:
                if pattern.search(line):
                    found.append(f"{rel}:{i}  {line.strip()[:80]}")
    return found


@rule("Vendored files match their recorded checksums")
def _():
    """A changed vendored file breaks verification on the target."""
    found = []
    for sums in REPO.rglob("SHA256SUMS"):
        if any(part in SKIP_DIRS for part in sums.parts):
            continue
        base = sums.parent
        for line in sums.read_text().splitlines():
            if not line.strip():
                continue
            digest, _, rel = line.partition("  ")
            target = base / rel.lstrip("./")
            if not target.exists():
                found.append(f"{target.relative_to(REPO)} is missing")
            elif hashlib.sha256(target.read_bytes()).hexdigest() != digest:
                found.append(f"{target.relative_to(REPO)} does not match its checksum")
    return found


@rule("No client-identifying content")
def _():
    """This repository is public. Nothing may identify who it was built for."""
    terms = ("bmo", "servicenow", "riskgpt", "ashutosh", "algowizzzz",
             "bank of montreal", "cmrods", "grce")
    found = []
    for path, rel in walk_text_files():
        text = path.read_text(errors="ignore")
        if EXEMPT in text:
            continue
        lowered = text.lower()
        for term in terms:
            if term in lowered:
                for i, line in enumerate(lowered.splitlines(), 1):
                    if term in line:
                        found.append(f"{rel}:{i}  contains {term!r}")
                        break
    return found


@rule("Workflow state names do not appear in conditionals")
def _():
    """State machines change by configuration; logic reads semantic flags instead."""
    states = ("Pending Compliance Review", "Non-Compliant", "Not Applicable",
              "Pending Approval", "Under Review")
    found = []
    for path, rel in walk_text_files():
        if path.suffix != ".py" or "/doctype/" not in rel:
            continue
        for i, line in enumerate(path.read_text(errors="ignore").splitlines(), 1):
            stripped = line.strip()
            if not (stripped.startswith(("if ", "elif ")) or " if " in stripped):
                continue
            for state in states:
                if state in line:
                    found.append(f"{rel}:{i}  branches on the state {state!r}; read a semantic flag")
    return found


@rule("Declared dependencies are all available as wheels")
def _():
    """A dependency needing a compiler cannot be installed on the target."""
    requirements = REPO / "requirements.txt"
    if not requirements.exists():
        return []
    # Checking this properly means resolving against an index, which is slow and
    # needs a network. The bundle builder does it for real. Here we only assert
    # that the file has not grown a git or URL dependency, which cannot be
    # vendored into a wheelhouse the same way.
    found = []
    for i, line in enumerate(requirements.read_text().splitlines(), 1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if "git+" in stripped or stripped.startswith(("http://", "https://")):
            found.append(
                f"requirements.txt:{i}  {stripped[:60]} — a direct reference. "
                f"pip honours these even with --no-index, so an offline install "
                f"will silently try to reach the network."
            )
    return found


def main() -> int:
    width = max(len(n) for n, _ in passes + failures) + 2 if (passes or failures) else 40
    print()
    for name, detail in passes:
        print(f"  {GREEN}pass{RESET}  {name:<{width}} {DIM}{detail}{RESET}")
    for name, problems in failures:
        print(f"  {RED}FAIL{RESET}  {name}")
        for problem in problems[:12]:
            print(f"        {RED}{problem}{RESET}")
        if len(problems) > 12:
            print(f"        {DIM}... and {len(problems) - 12} more{RESET}")
    total = len(passes) + len(failures)
    print()
    if failures:
        print(f"  {RED}{len(passes)}/{total} rules hold.{RESET}\n")
        return 1
    print(f"  {GREEN}{total}/{total} rules hold.{RESET}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

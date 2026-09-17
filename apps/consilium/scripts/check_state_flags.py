#!/usr/bin/env python3
"""Fail the build if business logic branches on a workflow state name.

Structural decision M-4 says nothing keys off a state string: a workflow-bearing
record carries semantic flags — `is_editable`, `is_active`, `requires_review` and
the rest — and all logic reads those. That is what lets a state be renamed, or an
approval step inserted, by configuration.

A rule nobody checks is a comment, so this is the check. It:

1. learns the state vocabulary from the seed table in
   `consilium/consilium_core/setup/state_flag_seed.py` — the one place state
   names legitimately live as data;
2. parses every Python file in the app;
3. reports any state name used *as a test*: inside an `if`/`while`/`assert`
   condition, either side of a comparison, in a boolean operator, in a
   comprehension filter, or as a `match` case pattern.

Assigning a state name is fine — something has to set the label. Comparing one is
not.

    python scripts/check_state_flags.py            # whole app
    python scripts/check_state_flags.py path/…     # named paths
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parent.parent
PACKAGE = APP_ROOT / "consilium"
SEED_MODULE = PACKAGE / "consilium_core" / "setup" / "state_flag_seed.py"

#: Files that hold the vocabulary itself, or this checker's own fixtures.
EXEMPT = {SEED_MODULE, Path(__file__).resolve()}


def state_vocabulary() -> set[str]:
    """Every state label the platform configures, read from the seed table."""
    tree = ast.parse(SEED_MODULE.read_text())
    values: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "STATE_FLAGS":
                    for row in node.value.elts:
                        # (doctype, state_field, state_value, *flags)
                        state_value = row.elts[2]
                        if isinstance(state_value, ast.Constant):
                            values.add(state_value.value)
    return values


class _TestVisitor(ast.NodeVisitor):
    """Collects string constants used as part of a test expression."""

    def __init__(self, vocabulary: set[str]):
        self.vocabulary = vocabulary
        self.hits: list[tuple[int, str]] = []

    def visit_Constant(self, node: ast.Constant) -> None:
        if isinstance(node.value, str) and node.value in self.vocabulary:
            self.hits.append((node.lineno, node.value))


def _scan_expression(expression, vocabulary: set[str]) -> list[tuple[int, str]]:
    visitor = _TestVisitor(vocabulary)
    visitor.visit(expression)
    return visitor.hits


def check_file(path: Path, vocabulary: set[str]) -> list[str]:
    tree = ast.parse(path.read_text(), filename=str(path))
    problems: list[str] = []

    try:
        shown = path.relative_to(APP_ROOT)
    except ValueError:
        shown = path

    def report(line: int, value: str, context: str) -> None:
        problems.append(
            f"{shown}:{line}: state name {value!r} used in {context}. "
            "Read a semantic flag instead (see 02-data-model.md M-4)."
        )

    for node in ast.walk(tree):
        tests: list[tuple[ast.AST, str]] = []
        if isinstance(node, ast.If):
            tests.append((node.test, "an if condition"))
        elif isinstance(node, ast.While):
            tests.append((node.test, "a while condition"))
        elif isinstance(node, ast.IfExp):
            tests.append((node.test, "a conditional expression"))
        elif isinstance(node, ast.Assert):
            tests.append((node.test, "an assertion"))
        elif isinstance(node, ast.Compare):
            tests.append((node, "a comparison"))
        elif isinstance(node, ast.BoolOp):
            tests.append((node, "a boolean expression"))
        elif isinstance(node, ast.comprehension):
            for condition in node.ifs:
                tests.append((condition, "a comprehension filter"))
        elif isinstance(node, ast.match_case):
            tests.append((node.pattern, "a match case"))

        for expression, context in tests:
            for line, value in _scan_expression(expression, vocabulary):
                report(line, value, context)

    return problems


def main(argv: list[str]) -> int:
    vocabulary = state_vocabulary()
    if not vocabulary:
        print("No state vocabulary found; the seed table is empty.", file=sys.stderr)
        return 2

    if argv:
        paths = [Path(a).resolve() for a in argv]
        files = [p for p in paths if p.suffix == ".py"]
        for p in paths:
            if p.is_dir():
                files.extend(sorted(p.rglob("*.py")))
    else:
        files = sorted(PACKAGE.rglob("*.py"))

    problems: list[str] = []
    for path in files:
        if path.resolve() in EXEMPT or "__pycache__" in path.parts:
            continue
        problems.extend(check_file(path, vocabulary))

    if problems:
        print(
            f"Business logic must not branch on a workflow state name "
            f"({len(problems)} occurrence(s)):\n  " + "\n  ".join(problems),
            file=sys.stderr,
        )
        return 1

    print(f"No state-name branching in {len(files)} file(s); vocabulary of {len(vocabulary)} state name(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

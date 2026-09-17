"""Install and migrate entry points for Core.

Core also drives the business modules' own setup. Each module needs
configuration rows and database objects the framework's migrate does not create,
and the hook that runs them lives in the shared `hooks.py`, which module
development does not touch. Driving them from here keeps that wiring in one
place, and keeps every module optional: one that is not installed contributes
nothing.
"""

from __future__ import annotations

import importlib

import frappe

from consilium.consilium_core.setup import constraints, seed

# Module, and the callables to run at install and at migrate.
_MODULE_SETUP = (
    ("consilium.governance.setup", ("ensure_configuration",)),
    ("consilium.governance.constraints", ("apply",)),
    ("consilium.policy.setup.install", ("after_migrate",)),
    ("consilium.escalation.setup.install", ("after_migrate",)),
)


def _run_module_setup() -> list[str]:
    done = []
    for module_path, functions in _MODULE_SETUP:
        try:
            module = importlib.import_module(module_path)
        except ModuleNotFoundError:
            continue
        for name in functions:
            fn = getattr(module, name, None)
            if fn is None:
                continue
            try:
                fn()
                done.append(f"{module_path}.{name}")
            except Exception:
                # One module failing must not leave the others unconfigured, and
                # must not fail the migration outright — but it must be visible.
                frappe.log_error(
                    title=f"Consilium: {module_path}.{name} failed during setup",
                    message=frappe.get_traceback(),
                )
                print(f"  WARNING: {module_path}.{name} failed; see the error log")
    return done


def after_install() -> None:
    seed.seed_all()
    constraints.apply()
    _run_module_setup()
    frappe.db.commit()


def after_migrate() -> None:
    seed.seed_all()
    applied = constraints.apply()
    modules = _run_module_setup()
    frappe.db.commit()
    if applied:
        print(f"Consilium Core: {len(applied)} database objects re-applied.")
    if modules:
        print(f"Consilium: {len(modules)} module setup steps ran.")

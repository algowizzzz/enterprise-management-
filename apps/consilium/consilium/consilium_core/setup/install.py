"""Install and migrate entry points for Core."""

from __future__ import annotations

import frappe

from consilium.consilium_core.setup import constraints, seed


def after_install() -> None:
    seed.seed_all()
    constraints.apply()
    frappe.db.commit()


def after_migrate() -> None:
    seed.seed_all()
    applied = constraints.apply()
    frappe.db.commit()
    if applied:
        print(f"Consilium Core: {len(applied)} database objects re-applied.")

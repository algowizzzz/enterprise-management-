"""Backfill the `is_affirmative` flag on state-flag rows that predate it.

The seeder deliberately never updates a state-flag row that already exists, so
that an administrator's change to the map survives a migration. That is right,
but it has a consequence: a flag column added later never reaches a site that is
already installed. The rows sit at the column default, which for a Check is 0.

For this flag that is not a cosmetic problem. `is_affirmative` is what separates
an approval from an abstention, and before it existed those two decisions were
flag-identical — an abstention on a mandatory approval step counted as consent
and the document published. A site that migrates without this patch keeps that
behaviour silently.

The column is new, so no administrator can have set it deliberately, which makes
a blanket backfill safe here. That will not be true of the next flag: a patch
that adds one should compare against the seeded row rather than assume.
"""

import frappe

from consilium.consilium_core import state_flags
from consilium.consilium_core.setup.state_flag_seed import STATE_FLAGS


def execute():
    if not frappe.db.table_exists("Workflow State Flag"):
        return

    columns = set(frappe.db.get_table_columns("Workflow State Flag"))
    if "is_affirmative" not in columns:
        return

    updated = 0
    for row in STATE_FLAGS:
        doctype, state_field, state_value = row[0], row[1], row[2]
        affirmative = row[-1]
        if not affirmative:
            continue
        name = frappe.db.get_value(
            "Workflow State Flag",
            {"target_doctype": doctype, "state_field": state_field, "state_value": state_value},
            "name",
        )
        if not name:
            continue
        if frappe.db.get_value("Workflow State Flag", name, "is_affirmative"):
            continue
        frappe.db.set_value("Workflow State Flag", name, "is_affirmative", 1, update_modified=False)
        updated += 1

    if updated:
        state_flags.clear_cache()
        print(f"Consilium: is_affirmative set on {updated} state-flag row(s).")

"""Share every existing formation request with its originator.

New requests are shared as they are saved (``formation.share_with_originator``,
called from the controller). Requests raised before that existed were readable
only by role, so an originator without a governance role could not open the
request they had raised — nor answer its questions or withdraw it. This gives
those requests the same share a new one gets. Safe to run again: a share that
is already in place is left as it is.
"""

import frappe


def execute():
    if not frappe.db.table_exists("Committee Formation Request"):
        return
    from consilium.governance import formation

    for row in frappe.get_all(
        "Committee Formation Request", filters={"requester": ["is", "set"]}, fields=["name", "requester"]
    ):
        formation.share_with_originator(frappe._dict(doctype="Committee Formation Request", **row))

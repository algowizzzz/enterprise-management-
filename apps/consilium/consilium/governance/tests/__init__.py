


def task_for(result, forum_name: str) -> str:
    """The task this test's forum was given, out of everything the campaign made.

    An inventory attestation covers every forum on the inventory, so taking
    `created[0]` only works while the test's forum is the only one there. It is
    not: other tests, and any seeded data, put forums alongside it. Select by
    subject rather than by position.
    """
    import frappe

    for name in result["created"]:
        if frappe.db.get_value("Attestation Task", name, "subject_name") == forum_name:
            return name
    raise AssertionError(f"the campaign generated no task for {forum_name}")

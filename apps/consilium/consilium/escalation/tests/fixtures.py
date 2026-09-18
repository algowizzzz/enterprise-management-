"""Fixture helpers for the escalation portal, participant and revision tests.

The test site is shared by several people running suites at once. Creating a
user writes a site-wide default row, so two suites building fixtures at the
same moment can deadlock; two suites can also pick the same derived username or
claim a naming series' first number in the same instant. PostgreSQL then
aborts one transaction, and the test that owned it fails for a reason that has
nothing to do with the code under test. Fixture building is therefore retried,
from a clean transaction, a few times before the failure is allowed to stand.
"""

from __future__ import annotations

import time

import frappe


def retry_on_deadlock(build, attempts: int = 8):
    for attempt in range(attempts):
        try:
            return build()
        except (frappe.QueryDeadlockError, frappe.UniqueValidationError, frappe.DuplicateEntryError):
            frappe.db.rollback()
            if attempt == attempts - 1:
                raise
            time.sleep(min(1.0 * (attempt + 1), 5.0))
    return None


"""Throwaway people for the portal tests, created once per class and committed.

Creating a user rewrites one shared framework default row (the list of users
with stored mail passwords) on every save. A test that creates users inside its
own transaction holds that row locked until it rolls back, and when several
test runs share a site — as they do while modules are developed in parallel —
those long-held locks deadlock one another. So these tests create their people
up front, commit at once (holding the lock for milliseconds, not a whole test),
retry the rare collision, and delete them when the class is done.

The framework also throttles user creation site-wide (sixty a minute) as a
guard against sign-up abuse. Several test runs sharing a site pass that easily,
and the throttle is not what these tests are about, so it is stood aside for
the moment a persona is inserted — the flag the framework itself checks.

The users are ``<hash>@example.com``: reserved for examples, and unique per run.
"""

from __future__ import annotations

import time

import frappe

from consilium.consilium_core.tests.utils import make_user


def committed_user(*roles: str) -> str:
    """A user holding ``roles``, committed. Retries a deadlock with a concurrent run."""
    for attempt in range(6):
        previous = frappe.flags.in_import
        frappe.flags.in_import = True
        try:
            name = make_user(roles[0] if roles else None)
            if len(roles) > 1:
                frappe.get_doc("User", name).add_roles(*roles[1:])
            frappe.db.commit()
            return name
        except frappe.QueryDeadlockError:
            frappe.db.rollback()
            time.sleep(0.5 + attempt)
        finally:
            frappe.flags.in_import = previous
    raise RuntimeError("could not create a test user: the site is deadlocked by concurrent runs")


def remove_users(names: list[str]) -> None:
    """Delete the class's people. Their records were all rolled back per test.

    Deleting a user is not the whole of it: the framework made an address-book
    contact and a time-zone default for each one, and on deletion it only
    unlinks the contact and leaves both. Measured on a test site, every run left
    one orphaned contact and one orphaned default per person, so they go too.
    """
    frappe.db.rollback()
    frappe.set_user("Administrator")
    for name in names:
        for attempt in range(6):
            try:
                if frappe.db.exists("User", name):
                    frappe.delete_doc("User", name, force=True, ignore_permissions=True)
                for contact in frappe.get_all("Contact", filters={"email_id": name}, pluck="name"):
                    frappe.delete_doc("Contact", contact, force=True, ignore_permissions=True)
                frappe.db.delete("DefaultValue", {"parent": name})
                frappe.db.commit()
                break
            except frappe.QueryDeadlockError:
                frappe.db.rollback()
                time.sleep(0.5 + attempt)


class PersonaPool:
    """People shared by every test class in one module, removed when it ends.

    One set per module rather than per class: each person is a committed user,
    and the fewer made, the less a run adds to the site-wide creation count
    other engineers' runs are throttled by.
    """

    def __init__(self):
        self.people: dict[str, str] = {}

    def attach(self, cls, personas: dict[str, tuple]) -> None:
        frappe.set_user("Administrator")
        for attribute, roles in personas.items():
            if attribute not in self.people:
                self.people[attribute] = committed_user(*roles)
            setattr(cls, attribute, self.people[attribute])

    def remove(self) -> None:
        remove_users(list(self.people.values()))
        self.people.clear()

"""Keep the interface to what the requirements ask for.

The framework ships a general-purpose business application around the parts
this platform uses: a website with a blog, a contacts book, social features,
integrations, a no-code builder. None of it is in scope, and every screen of it
an everyday user can reach is something to explain, support and secure. This
module hides it — from everyone except system administrators, who still need
the builder and the integrations to run the platform — and it does so as
configuration applied on every migrate, so an upgrade cannot quietly bring any
of it back.

Nothing is deleted and no framework file is changed: workspaces are restricted
by role, modules are blocked through a module profile, and public pages are
redirected by the ``website_redirects`` hook.
"""

from __future__ import annotations

import frappe

ADMIN_ROLES = ("System Manager",)

#: The framework's own workspaces: administration tooling, not governance.
FRAMEWORK_WORKSPACES = ("Users", "Website", "Tools", "Integrations", "Build", "Welcome Workspace")

#: Each Consilium workspace is shown to the roles that can use what is on it.
#: A role that can read nothing a workspace lists only meets refusals there.
CONSILIUM_WORKSPACES = {
    "Governance": "Governance Forum",
    "Policy": "Governing Document",
    "Escalation": "Escalation Matter",
}
ADMINISTRATION_WORKSPACE = "Consilium Administration"
ADMINISTRATION_ROLES = ("System Manager", "Consilium Administrator", "Taxonomy Administrator", "Records Manager")

#: Framework modules with no place in the platform's scope. Blocking a module
#: removes its record types from the workspace, search and lists; the server
#: code the platform relies on (mail queue, workflow, printing) is untouched.
BLOCKED_MODULES = ("Website", "Social", "Contacts", "Geo", "Integrations", "Custom", "Automation")
MODULE_PROFILE = "Consilium Standard User"


def _set_workspace_roles(workspace: str, roles: list[str]) -> None:
    """Replace a workspace's role list without saving the Workspace document.

    Saving a standard workspace in developer mode writes it back into its
    app's source folder, and for the framework's own workspaces that folder is
    the framework — which must stay pristine. The role rows are plain child
    rows, so they are written directly.
    """
    if not frappe.db.exists("Workspace", workspace):
        return
    wanted = sorted(set(roles))
    current = sorted(frappe.get_all("Has Role", filters={"parent": workspace, "parenttype": "Workspace"}, pluck="role"))
    if current == wanted:
        return
    frappe.db.delete("Has Role", {"parent": workspace, "parenttype": "Workspace"})
    for idx, role in enumerate(wanted, start=1):
        frappe.get_doc(
            {"doctype": "Has Role", "parent": workspace, "parenttype": "Workspace",
             "parentfield": "roles", "role": role, "idx": idx}
        ).db_insert()


def _roles_that_read(doctype: str) -> list[str]:
    roles = frappe.get_all("DocPerm", filters={"parent": doctype, "read": 1, "permlevel": 0}, pluck="role")
    roles += frappe.get_all("Custom DocPerm", filters={"parent": doctype, "read": 1, "permlevel": 0}, pluck="role")
    return sorted({r for r in roles if r not in ("All", "Guest")} | set(ADMIN_ROLES))


def restrict_workspaces() -> None:
    for workspace in FRAMEWORK_WORKSPACES:
        _set_workspace_roles(workspace, list(ADMIN_ROLES))
    for workspace, doctype in CONSILIUM_WORKSPACES.items():
        _set_workspace_roles(workspace, _roles_that_read(doctype))
    _set_workspace_roles(ADMINISTRATION_WORKSPACE, list(ADMINISTRATION_ROLES))


def ensure_module_profile() -> str:
    installed = set(frappe.get_all("Module Def", pluck="name"))
    blocked = [m for m in BLOCKED_MODULES if m in installed]
    if frappe.db.exists("Module Profile", MODULE_PROFILE):
        profile = frappe.get_doc("Module Profile", MODULE_PROFILE)
    else:
        profile = frappe.new_doc("Module Profile")
        profile.module_profile_name = MODULE_PROFILE
    if sorted(row.module for row in profile.block_modules) != sorted(blocked):
        profile.set("block_modules", [{"module": m} for m in blocked])
        profile.save(ignore_permissions=True)
    return profile.name


def _is_platform_administrator(user: str) -> bool:
    return user in ("Administrator",) or bool(
        set(ADMIN_ROLES) & set(frappe.get_all("Has Role", filters={"parent": user, "parenttype": "User"}, pluck="role"))
    )


def apply_module_profile(user_doc, method=None) -> None:
    """``User`` validate hook: everyday users get the standard profile.

    An administrator keeps full access, and a profile someone set by hand is
    left alone — this only fills the gap for accounts that have none.
    """
    if user_doc.user_type != "System User" or user_doc.module_profile:
        return
    if user_doc.name == "Administrator" or set(ADMIN_ROLES) & {r.role for r in user_doc.get("roles") or []}:
        return
    if frappe.db.exists("Module Profile", MODULE_PROFILE):
        user_doc.module_profile = MODULE_PROFILE
        # The framework copies a profile's blocked modules onto the user in its
        # own validate, which has already run by the time this hook does. Copy
        # them now, or a new user carries the profile's name but is blocked from
        # nothing until someone happens to save them again.
        user_doc.validate_allowed_modules()


def apply_to_existing_users(profile: str) -> int:
    changed = 0
    # Filtered in Python: an "empty or null" filter compiles to a comparison the
    # database may refuse, and the user list is small.
    rows = frappe.get_all("User", filters={"user_type": "System User"}, fields=["name", "module_profile"])
    for user in (row.name for row in rows if not row.module_profile):
        if _is_platform_administrator(user):
            continue
        doc = frappe.get_doc("User", user)
        doc.module_profile = profile
        doc.flags.ignore_permissions = True
        doc.save(ignore_permissions=True)
        changed += 1
    return changed


def after_migrate() -> None:
    restrict_workspaces()
    profile = ensure_module_profile()
    apply_to_existing_users(profile)
    frappe.clear_cache()


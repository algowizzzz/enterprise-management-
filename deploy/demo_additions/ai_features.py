"""DEMONSTRATION data for the governance analysis features (O-6, O-7).

    from deploy.demo_additions import ai_features
    ai_features.run(frappe)          # inside a connected site; the caller commits

Builds on records ``deploy/demo_data.py`` has already made and changes nothing
else. Idempotent: every step looks for what it would create and skips it when
it is there. Every step is taken as the persona who would take it, through the
same entry points the portal calls.

* **The regulatory-change import profile.** ``Regulatory changes — file
  import`` on Core's import pipeline, keyed on the requirement code and set to
  update, so ``/imports`` accepts a file of changes and each committed row
  notifies the requirement's citers exactly as a change made by hand does.
* **A recorded regulatory change.** The Risk Governance Office Lead (who holds
  Taxonomy Administrator) records a change to the operational resilience
  guideline's summary on ``/regulatory-updates``. The requirement's own
  controller dates it and tells the owner of every citing document and forum;
  the page then shows the change, the citing records and the rule-based
  candidates.

The AI layer is **not** switched on: the demonstration shows every feature's
rule-based result, which is the whole of each feature on a site with no
internet access. ``Assistant Settings`` is left as it is.

Everything is fictitious, and records are owned by ``@demo.example`` personas
like the rest of the demonstration data.
"""

from __future__ import annotations

DOMAIN = "demo.example"
REQUIREMENT_TITLE = "Operational Resilience Guideline"
CHANGED_SUMMARY = (
    "Identify critical operations, set impact tolerances for their disruption, map their third-party "
    "dependencies and test recovery against severe but plausible scenarios at least annually."
)


def U(key: str) -> str:
    return f"{key}@{DOMAIN}"


class _As:
    """Act as a persona for the length of a block, then restore the caller."""

    def __init__(self, frappe, user: str):
        self.frappe, self.user = frappe, user

    def __enter__(self):
        self.previous = self.frappe.session.user
        self.frappe.set_user(self.user)

    def __exit__(self, *exc):
        self.frappe.set_user(self.previous)


def _import_profile(frappe, report: dict) -> None:
    from consilium.consilium_core.ai import regulatory

    existed = frappe.db.get_value("Import Profile", {"profile_title": regulatory.PROFILE_TITLE}, "name")
    name = regulatory.ensure_profile()
    report["import_profile"] = f"exists: {name}" if existed else f"created: {name}"


def _regulatory_change(frappe, report: dict) -> None:
    from consilium.consilium_core.ai import regulatory

    requirement = frappe.db.get_value("Regulatory Requirement", {"regulatory_requirement_name": REQUIREMENT_TITLE}, "name")
    if not requirement:
        report["regulatory_change"] = f"skipped: no requirement titled {REQUIREMENT_TITLE!r}"
        return
    if (frappe.db.get_value("Regulatory Requirement", requirement, "summary") or "").strip() == CHANGED_SUMMARY:
        report["regulatory_change"] = f"exists: {requirement} already carries the changed summary"
        return
    editor = U("risk.governance.lead")
    if not frappe.db.exists("User", editor):
        report["regulatory_change"] = f"skipped: no persona {editor}"
        return
    with _As(frappe, editor):
        out = regulatory.record_change(requirement, {"summary": CHANGED_SUMMARY})
    report["regulatory_change"] = (
        f"recorded on {requirement} by {editor}; {out['citing_notified']} citing record(s) notified by the "
        f"requirement's controller; {len(out['candidates'])} rule-based candidate document(s)"
    )


def run(frappe) -> dict:
    """Apply the additions. Returns what was done; the caller commits."""
    report: dict = {}
    if not frappe.db.exists("DocType", "Regulatory Requirement"):
        report["skipped"] = "the site is not migrated"
        return report
    _import_profile(frappe, report)
    _regulatory_change(frappe, report)
    settings = frappe.get_cached_doc("Assistant Settings") if frappe.db.exists("DocType", "Assistant Settings") else None
    report["ai_layer"] = "on" if settings and settings.get("features_enabled") else "off (rule-based results only)"
    return report

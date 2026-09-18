"""DEMONSTRATION data for the policy portal's actions (/policy, /policy-intake).

    from deploy.demo_additions import policy_actions
    policy_actions.run(frappe)   # inside a connected site; the caller commits

Builds on the policy library ``deploy/demo_data.py`` has already made (documents
found by name, not by reference, so a fresh site's numbering does not matter)
and changes nothing else. Idempotent: every step looks for what it would create
and skips it when it is there. Every step is taken **as the persona who would
take it**, through the same entry points the portal calls, so ownership, the
role and stage checks and the audit trail are the ones a real user leaves.

What each step leaves demonstrable, and as whom:

* **A document in review whose approval steps are not yet raised.** The Head of
  Technology Risk submits the "Artificial Intelligence Use Standard" for review.
  Signed in as the Enterprise Policy Office Lead, its page offers **Raise
  approval steps** and shows the three steps the major-change route would raise
  (first line: the Chief Risk Officer; second line: the sponsor; the office).
* **A step decidable by a delegate.** The Chief Compliance Officer delegates the
  approval of the "Customer Data Privacy Procedure" (in review, its approver
  step waiting on them) to the Second Line Reviewer for a month. Either of them
  sees the step under *Waiting on your decision* on ``/policies`` and can
  decide it; the delegate's decision records the delegation. The office lead
  can instead **Authorise a bypass** of it, with a written justification.
* **A request awaiting classification.** The Chief Information Officer asks for
  a "Cloud Service Usage Standard". Signed in as them, ``/policy-intake`` shows
  the classification questions drawn from the rule set in force.
* **A classified request awaiting its document.** The Head of Model Risk asks
  for a "Model Validation Standard" and answers the questions (a minor change).
  Signed in as the office lead, the request offers **Create the document** and
  **Override the classification**; signed in as the Head of Model Risk it offers
  **Challenge the classification**.

Already demonstrable from ``demo_data.py`` and left alone: upload and revert on
the "Information Security Policy" (in drafting, two versions captured in
drafting), publication and withdrawal on any document in force, concluding the
open review of the "Code of Conduct", horizon scans, monitoring results on
"Alert disposition quality assurance" (the Second Line Reviewer is responsible)
and violations.

Everything is fictitious, and every record is owned by an ``@demo.example``
persona like the rest of the demonstration data.
"""

from __future__ import annotations

DOMAIN = "demo.example"

AI_STANDARD = "Artificial Intelligence Use Standard"
PRIVACY_PROCEDURE = "Customer Data Privacy Procedure"
CLOUD_STANDARD = "Cloud Service Usage Standard"
MODEL_STANDARD = "Model Validation Standard"

DELEGATION_REASON = (
    "Out of office for the quarter-end regulatory submissions; the Second Line Reviewer decides the privacy "
    "procedure's approval in my place."
)
MINOR_ANSWERS = {"q_scope": "local", "q_obligation": "no", "q_control": "no"}


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


def _document(frappe, title: str) -> str | None:
    return frappe.db.get_value("Governing Document", {"document_name": title}, "name")


def review_awaiting_raise(frappe, notes: list[str]) -> None:
    from consilium.policy import lifecycle

    name = _document(frappe, AI_STANDARD)
    if not name:
        notes.append(f"skipped: no document named {AI_STANDARD!r}")
        return
    doc = frappe.get_doc("Governing Document", name)
    if int(doc.requires_review or 0):
        notes.append(f"exists: {name} already under review")
        return
    if not int(doc.is_editable or 0):
        notes.append(f"skipped: {name} is not in drafting")
        return
    with _As(frappe, doc.document_owner):
        lifecycle.take_action(name, "Submit for Review")
    notes.append(f"created: {name} submitted for review by {doc.document_owner}; steps left to raise")


def delegated_step(frappe, notes: list[str]) -> None:
    name = _document(frappe, PRIVACY_PROCEDURE)
    if not name:
        notes.append(f"skipped: no document named {PRIVACY_PROCEDURE!r}")
        return
    delegator, delegate = U("chief.compliance.officer"), U("second.line.reviewer")
    existing = frappe.db.get_value(
        "Authority Delegation",
        {"delegator": delegator, "delegate": delegate, "scope_doctype": "Governing Document", "scope_record": name},
        "name",
    )
    if existing:
        notes.append(f"exists: {existing} ({delegator} to {delegate} on {name})")
        return
    today = frappe.utils.getdate(frappe.utils.nowdate())
    with _As(frappe, delegator):
        # Recorded by the delegator, in their own name; the DocType is the
        # administrators' to edit, so the insert does not ask the delegator's role.
        row = frappe.get_doc(
            {
                "doctype": "Authority Delegation",
                "delegator": delegator,
                "delegate": delegate,
                "scope_type": "Record",
                "scope_doctype": "Governing Document",
                "scope_record": name,
                "valid_from": str(today),
                "valid_to": str(frappe.utils.add_days(today, 30)),
                "reason": DELEGATION_REASON,
                "delegated_actions": [{"delegable_action": "APPROVE"}],
            }
        ).insert(ignore_permissions=True)
    notes.append(f"created: {row.name}, {delegator} to {delegate} on {name}")


def _request(frappe, proposed: str) -> str | None:
    return frappe.db.get_value("Document Intake Request", {"proposed_document_name": proposed}, "name")


def request_awaiting_classification(frappe, notes: list[str]) -> None:
    from consilium.policy import intake

    existing = _request(frappe, CLOUD_STANDARD)
    if existing:
        notes.append(f"exists: {existing} ({CLOUD_STANDARD})")
        return
    with _As(frappe, U("chief.information.officer")):
        ctx = intake.raise_request(
            "Create",
            "Business units are adopting cloud services faster than the outsourcing policy's approval path can "
            "follow. A standard is needed that says which services may be used for which data, and who approves "
            "an exception.",
            proposed_document_name=CLOUD_STANDARD,
            proposed_document_type="STANDARD",
            primary_risk_category=frappe.db.get_value("Governing Document", _document(frappe, AI_STANDARD),
                                                      "primary_risk_category"),
        )
    notes.append(f"created: {ctx['request']['name']} ({CLOUD_STANDARD}) awaiting classification")


def request_awaiting_document(frappe, notes: list[str]) -> None:
    from consilium.policy import intake

    existing = _request(frappe, MODEL_STANDARD)
    if existing:
        notes.append(f"exists: {existing} ({MODEL_STANDARD})")
        return
    requester = U("head.model.risk")
    with _As(frappe, requester):
        ctx = intake.raise_request(
            "Create",
            "Model validation is described only in the model risk policy's appendix. A standard would set the "
            "validation depth for each model tier and the evidence a validator keeps.",
            proposed_document_name=MODEL_STANDARD,
            proposed_document_type="STANDARD",
        )
        name = ctx["request"]["name"]
        intake.classify_request(name, MINOR_ANSWERS)
    notes.append(f"created: {name} ({MODEL_STANDARD}) classified minor, awaiting its document")


def run(frappe) -> list[str]:
    """Load the demonstration. Returns one note per step; the caller commits."""
    notes: list[str] = []
    for step in (review_awaiting_raise, delegated_step, request_awaiting_classification, request_awaiting_document):
        savepoint = f"policy_actions_{step.__name__}"
        frappe.db.savepoint(savepoint)
        try:
            step(frappe, notes)
        except Exception as exc:  # one step failing must not undo the others
            frappe.db.rollback(save_point=savepoint)
            notes.append(f"failed: {step.__name__}: {type(exc).__name__}: {exc}")
    return notes

"""Conditional approval routing.

E12-S3 asks for three things: routing that depends on policy type, change type
and risk level; routing that is configuration; and the resulting path visible on
the record **before** submission. The third is the one that makes the first two
worth having — an approver who cannot see the path until they are in it cannot
challenge it.

So a route is an ``Approval Route`` record. Selection is: every active route for
the DocType, most specific first, first match wins. Resolution turns each step
into an assignee by reading the record, so a change of owner does not strand a
route. ``preview`` returns the resolved path without writing anything;
``instantiate`` writes it as Core ``Approval Decision`` rows.

Lineage adds one more step that no route carries: where the lineage edge to a
parent is marked ``owner_approval_required``, the parent's owner approves the
child's change (P-8, E12-S4). It is appended as a distinct step so it is visible
as its own approval rather than folded into someone else's.
"""

from __future__ import annotations

import frappe
from frappe import _

from consilium.consilium_core import approvals, classification, state_flags
from consilium.policy import lineage

DOCTYPE = "Governing Document"

PARENT_OWNER_STEP = "Parent Document Owner Approval"

#: Where a step's assignee comes from. The label is the field it reads.
ASSIGNEE_FIELD = {
    "Document Owner": "document_owner",
    "Document Approver": "document_approver",
    "Document Sponsor": "document_sponsor",
    "Document Liaison": "document_liaison",
}


def _risk_category_family(category: str | None) -> list[str]:
    """A category and all of its ancestors, so a route on a parent category matches."""
    if not category:
        return []
    family = [category]
    seen = {category}
    current = category
    while True:
        parent = frappe.db.get_value("Risk Category", current, "parent_risk_category")
        if not parent or parent in seen:
            break
        family.append(parent)
        seen.add(parent)
        current = parent
    return family


def _matches(route: dict, doc) -> bool:
    if route.get("document_type") and route["document_type"] != doc.get("document_type"):
        return False
    if route.get("change_classification"):
        if route["change_classification"] != (change_classification_of(doc) or ""):
            return False
    if route.get("primary_risk_category"):
        if route["primary_risk_category"] not in _risk_category_family(doc.get("primary_risk_category")):
            return False
    if route.get("handling_classification"):
        if route["handling_classification"] != doc.get("handling_classification"):
            return False
    return True


def _specificity(route: dict) -> int:
    return sum(
        1
        for key in ("document_type", "change_classification", "primary_risk_category", "handling_classification")
        if route.get(key)
    )


def change_classification_of(doc) -> str | None:
    """The classification this document's pending change was given.

    Read from the intake request that produced it, through the Core assessment,
    so the value used for routing is the same one the audit trail explains. An
    override on the assessment wins, because that is what was decided.
    """
    request = frappe.db.get_value(
        "Document Intake Request",
        {"created_document": doc.name, "docstatus": ["<", 2]},
        ["name", "classification_assessment", "change_classification"],
        as_dict=True,
    ) if doc.get("name") else None
    if not request:
        request = frappe.db.get_value(
            "Document Intake Request",
            {"subject_document": doc.get("name"), "docstatus": ["<", 2], "is_open": 1},
            ["name", "classification_assessment", "change_classification"],
            as_dict=True,
        ) if doc.get("name") else None
    if not request:
        return None
    if request.get("classification_assessment"):
        return classification.effective_outcome(request["classification_assessment"])
    return request.get("change_classification")


def select_route(doc) -> dict | None:
    routes = frappe.get_all(
        "Approval Route",
        filters={"target_doctype": doc.doctype, "is_active": 1},
        fields=["name", "priority", "document_type", "change_classification",
                "primary_risk_category", "handling_classification"],
        order_by="priority asc, modified asc",
    )
    candidates = [route for route in routes if _matches(route, doc)]
    if not candidates:
        return None
    candidates.sort(key=lambda route: (int(route["priority"] or 0), -_specificity(route)))
    return candidates[0]


def _resolve_assignee(step, doc) -> str | None:
    source = step.get("assignee_source")
    if source == "Named User":
        return step.get("assignee")
    if source == "Parent Document Owner":
        entries = lineage.parent_owner_approvals(doc)
        return entries[0]["owner"] if entries else None
    fieldname = ASSIGNEE_FIELD.get(source)
    return doc.get(fieldname) if fieldname else None


def resolved_steps(doc) -> list[dict]:
    """The approval path for this record, resolved but not written.

    A step whose assignee cannot be resolved falls back to the document
    approver, who is mandatory on every document; the fallback is reported in
    the step so it is visible rather than silent.
    """
    route = select_route(doc)
    steps: list[dict] = []

    if route:
        rows = frappe.get_all(
            "Approval Route Step",
            filters={"parent": route["name"], "parenttype": "Approval Route"},
            fields=["step_sequence", "approval_step", "required_role", "assignee_source",
                    "assignee", "mode", "is_mandatory", "condition"],
            order_by="step_sequence asc",
        )
        for row in rows:
            assignee = _resolve_assignee(row, doc)
            fallback = False
            if not assignee:
                assignee = doc.get("document_approver")
                fallback = True
            steps.append(
                {
                    "step_sequence": int(row["step_sequence"] or 0),
                    "approval_step": row["approval_step"],
                    "required_role": row["required_role"],
                    "assigned_to": assignee,
                    "mode": row["mode"] or "Sequential",
                    "is_mandatory": int(row["is_mandatory"] or 0),
                    "source": f"route:{route['name']}",
                    "assignee_fallback": fallback,
                }
            )

    next_sequence = max([step["step_sequence"] for step in steps], default=0) + 1
    for entry in lineage.parent_owner_approvals(doc):
        steps.append(
            {
                "step_sequence": next_sequence,
                "approval_step": f"{PARENT_OWNER_STEP} ({entry['document']})",
                "required_role": None,
                "assigned_to": entry["owner"],
                "mode": "Sequential",
                "is_mandatory": 1,
                "source": f"lineage:{entry['document']}",
                "assignee_fallback": False,
            }
        )
        next_sequence += 1

    return steps


@frappe.whitelist()
def preview(document: str) -> dict:
    """The approval path, visible on the record before it is submitted (E12-S3)."""
    frappe.has_permission(DOCTYPE, "read", doc=document, throw=True)
    doc = frappe.get_doc(DOCTYPE, document)
    route = select_route(doc)
    return {
        "document": document,
        "route": route["name"] if route else None,
        "change_classification": change_classification_of(doc),
        "steps": resolved_steps(doc),
    }


def _cycle_decisions(doc, fields: list[str]) -> list[dict]:
    """The approval decisions that belong to the version now in the chain.

    Every decision records the version it was taken on. Counting decisions from
    an earlier version meant a document reopened after publication still found
    last cycle's approvals, so it could be published again without anyone
    approving what had changed. An approval is of a version, not of a title.
    """
    current = frappe.db.get_value(
        "Document Version", {"subject_doctype": doc.doctype, "subject_name": doc.name, "is_current": 1}, "name"
    )
    rows = frappe.get_all(
        "Approval Decision",
        filters={"subject_doctype": doc.doctype, "subject_name": doc.name, "docstatus": ["<", 2]},
        fields=list(dict.fromkeys([*fields, "based_on_version"])),
    )
    return [row for row in rows if (row["based_on_version"] or None) == (current or None)]


def instantiate(doc) -> list[str]:
    """Write the resolved path as Core Approval Decision rows.

    Idempotent: a step that already has a decision row for this document is left
    alone, so re-routing after a change of owner does not duplicate history.
    """
    existing = {row["approval_step"] for row in _cycle_decisions(doc, ["approval_step"])}
    classification_label = change_classification_of(doc)
    written = []
    for step in resolved_steps(doc):
        if step["approval_step"] in existing:
            continue
        if not step["assigned_to"]:
            frappe.throw(
                _("Approval step {0} has no assignee and the document has no approver to fall back to.").format(
                    step["approval_step"]
                )
            )
        decision = approvals.request_decision(
            subject_doctype=doc.doctype,
            subject_name=doc.name,
            approval_step=step["approval_step"],
            step_sequence=step["step_sequence"],
            mode=step["mode"],
            required_role=step["required_role"],
            assigned_to=step["assigned_to"],
            classification_at_decision=classification_label,
        )
        written.append(decision.name)
    return written


def chain_status(doc) -> dict:
    """Whether the approval chain is complete, and why not if it is not.

    Completeness is read from the semantic flags, never from the decision label.
    ``is_open`` is carried on the decision row itself; ``requires_review`` — which
    marks an objection, whether a rejection, a request for changes or a bypass —
    is not a column on ``Approval Decision``, so it is read out of the configured
    flag map for the value the row holds. That is still a configuration lookup
    rather than a comparison: no decision name appears here.

    An objection is tolerated only when the row names an ``Exception
    Authorisation``, which is what P-25 demands.
    """
    steps = resolved_steps(doc)
    rows = _cycle_decisions(doc, ["name", "approval_step", "decision", "is_open", "exception_authorisation",
                                  "assigned_to", "step_sequence"])
    by_step = {row["approval_step"]: row for row in rows}

    missing, outstanding, objections = [], [], []
    for step in steps:
        if not step["is_mandatory"]:
            continue
        row = by_step.get(step["approval_step"])
        if not row:
            missing.append(step["approval_step"])
            continue
        if int(row["is_open"] or 0):
            outstanding.append(step["approval_step"])
            continue
        flags = state_flags.flags_for("Approval Decision", "decision", row["decision"]) or {}
        if int(flags.get("requires_review") or 0) and not row.get("exception_authorisation"):
            objections.append(step["approval_step"])

    return {
        "complete": not (missing or outstanding or objections),
        "expected_steps": [step["approval_step"] for step in steps if step["is_mandatory"]],
        "missing": missing,
        "outstanding": outstanding,
        "objections": objections,
    }


# --------------------------------------------------------------------------
# Portal entry points: raising the chain and deciding its steps (P-8, P-25, P-26)
#
# ``instantiate`` had no caller, so no screen could ever ask anyone to approve a
# document, and the "Complete Approval Chain" gate could only be satisfied from
# a console. These are the thin, checked doors onto it. Who may do what is
# settled in ``lifecycle`` (roles and stage, shared with every other portal
# action) and in Core (who may decide a step: its assignee or a live delegate).
# --------------------------------------------------------------------------

#: The decisions a step's assignee may record from the portal. ``Pending`` is
#: where a step starts and ``Bypassed`` is reachable only through an exception
#: authorisation. ``Abstained`` is withheld: Core counts it as no objection, so
#: offering it would let a step complete the chain without anyone approving.
#: These are values handed to Core, never compared.
STEP_DECISIONS = ("Approved", "Rejected", "Changes Requested")

DECISION_FIELDS = [
    "name", "approval_step", "step_sequence", "mode", "required_role", "assigned_to", "acted_by",
    "acting_delegation", "decision", "is_open", "requires_review", "decided_on", "comments",
    "exception_authorisation", "based_on_version", "creation",
]


def _current_version_name(doc) -> str | None:
    return frappe.db.get_value(
        "Document Version", {"subject_doctype": doc.doctype, "subject_name": doc.name, "is_current": 1}, "name"
    )


def _may_decide(row, user: str, doc) -> bool:
    from consilium.consilium_core import delegation

    return delegation.resolve_actor(
        row["assigned_to"], delegation.ACTION_APPROVE, acting_user=user, doctype=doc.doctype, name=doc.name
    )["permitted"]


def is_participant(doc, user: str | None = None) -> bool:
    """Whether the user is assigned a step on this document, or acts for someone who is."""
    user = user or frappe.session.user
    for row in frappe.get_all(
        "Approval Decision",
        filters={"subject_doctype": doc.doctype, "subject_name": doc.name},
        fields=["name", "assigned_to"],
    ):
        if _may_decide(row, user, doc):
            return True
    return False


def decidable_steps(doc, user: str | None = None) -> list[str]:
    """Open steps of the version now in the chain that this user may decide."""
    user = user or frappe.session.user
    return [
        row["name"]
        for row in _cycle_decisions(doc, ["name", "assigned_to", "is_open", "step_sequence"])
        if int(row["is_open"] or 0) and _may_decide(row, user, doc)
    ]


def decision_choice(decision: str) -> dict:
    """A decision the screen may offer, and whether it must carry a reason — read
    from the configured flag, so a new objection-type decision needs no code."""
    flags = state_flags.flags_for("Approval Decision", "decision", decision) or {}
    return {"decision": decision, "needs_reason": bool(flags.get("requires_review"))}


def approval_context(doc, user: str | None = None) -> dict:
    """The approval panel: the chain, its steps (raised or not yet), and who may act."""
    user = user or frappe.session.user
    current = _current_version_name(doc)
    rows = frappe.get_all(
        "Approval Decision",
        filters={"subject_doctype": doc.doctype, "subject_name": doc.name, "docstatus": ["<", 2]},
        fields=DECISION_FIELDS,
        order_by="creation desc, step_sequence asc",
    )
    decidable = set(decidable_steps(doc, user))
    for row in rows:
        row["current_cycle"] = (row["based_on_version"] or None) == (current or None)
        # A sequential step behind an open one is not offered: Core refuses it
        # until the steps ahead are decided (E7-S4). Said, not hidden.
        row["waiting_on"] = (
            [ahead.approval_step for ahead in approvals.waiting_on(row["name"])]
            if row["name"] in decidable else []
        )
        row["can_decide"] = row["name"] in decidable and not row["waiting_on"]
    decidable = {row["name"] for row in rows if row["can_decide"]}
    raised = {row["approval_step"] for row in rows if row["current_cycle"]}
    steps = resolved_steps(doc)
    route = select_route(doc)
    return {
        "route": route["name"] if route else None,
        "change_classification": change_classification_of(doc),
        "current_version": current,
        "chain": chain_status(doc),
        "planned_steps": steps,
        "unraised": [step["approval_step"] for step in steps if step["approval_step"] not in raised],
        "decisions": rows,
        "open_steps": [row["name"] for row in rows if row["current_cycle"] and int(row["is_open"] or 0)],
        # Nobody waives their own step (``bypass_step``), so the steps this
        # viewer could be offered to bypass exclude those assigned to them.
        "bypassable": [row["name"] for row in rows
                       if row["current_cycle"] and int(row["is_open"] or 0) and row["assigned_to"] != user],
        "decidable": sorted(decidable),
        "step_decisions": [decision_choice(d) for d in STEP_DECISIONS],
    }


def _open_step_of(doc, approval_decision: str) -> dict:
    """The decision row, if it is an open step of this document's current version."""
    row = frappe.db.get_value(
        "Approval Decision", approval_decision,
        ["name", "subject_doctype", "subject_name", "is_open", "approval_step", "assigned_to",
         "based_on_version"],
        as_dict=True,
    )
    if not row or (row.subject_doctype, row.subject_name) != (doc.doctype, doc.name):
        frappe.throw(
            _("Approval step {0} does not belong to {1}.").format(approval_decision, doc.name),
            title=_("Wrong Step"),
        )
    if not int(row.is_open or 0):
        frappe.throw(
            _("Approval step {0} has already been decided.").format(row.approval_step),
            title=_("Step Already Decided"),
        )
    if (row.based_on_version or None) != (_current_version_name(doc) or None):
        frappe.throw(
            _("Approval step {0} was raised on an earlier version of {1}. Raise the steps again for the "
              "version now in the chain.").format(row.approval_step, doc.name),
            title=_("Step Belongs To An Earlier Version"),
        )
    return row


def _tell(event_code: str, recipients, context: dict, doc) -> None:
    """A Core dispatch, so "was the approver told" has an answer (P-14).

    Through a template, so the wording and the channel are the administrator's
    to change, like every other notice the platform sends.
    """
    from consilium.consilium_core import notification

    recipients = sorted({r for r in recipients if r})
    if recipients:
        notification.notify(event_code, recipients, context, subject_doctype=doc.doctype, subject_name=doc.name)


@frappe.whitelist(methods=["POST"])
def raise_steps(document: str) -> dict:
    """Raise the resolved approval path as decisions, and tell each approver.

    Refused without a version: an approval is of a version (``_cycle_decisions``),
    and a decision raised against none would silently vanish from the chain the
    moment the first version is uploaded.
    """
    from consilium.policy import lifecycle

    doc = frappe.get_doc(DOCTYPE, document)
    frappe.has_permission(DOCTYPE, "read", doc=doc, throw=True)
    lifecycle.authorise(doc, "raise_approval_steps")
    if not _current_version_name(doc):
        frappe.throw(
            _("{0} has no version in its chain. Approvals are given against a version, so upload one first.")
            .format(doc.name),
            title=_("No Version To Approve"),
        )
    written = instantiate(doc)
    if not written:
        frappe.throw(
            _("Every approval step for the current version of {0} has already been raised.").format(doc.name),
            title=_("Already Raised"),
        )
    for name in written:
        row = frappe.db.get_value("Approval Decision", name, ["approval_step", "assigned_to"], as_dict=True)
        _tell(
            "policy.approval.requested", [row.assigned_to],
            {"approval_step": row.approval_step, "version_label": doc.version_label or ""}, doc,
        )
    return lifecycle.portal_context(frappe.get_doc(DOCTYPE, doc.name))


@frappe.whitelist(methods=["POST"])
def decide_step(document: str, approval_decision: str, decision: str, comments: str | None = None) -> dict:
    """A step's assignee (or their live delegate) decides it.

    No policy role and no document permission is asked for: the right to decide
    comes from being assigned the step, and Core refuses — and audits — anyone
    who is neither the assignee nor holding a live delegation.
    """
    from consilium.consilium_core import approvals
    from consilium.policy import lifecycle

    doc = frappe.get_doc(DOCTYPE, document)
    row = _open_step_of(doc, approval_decision)
    if decision not in STEP_DECISIONS:
        frappe.throw(_("{0} is not a decision a step can record.").format(decision), title=_("Unknown Decision"))
    if decision_choice(decision)["needs_reason"] and not (comments or "").strip():
        frappe.throw(
            _("A decision of \"{0}\" is recorded with its reason.").format(decision), title=_("Reason Required")
        )
    approvals.record_decision(row.name, decision, comments=comments, acting_user=frappe.session.user)
    _tell(
        "policy.approval.decided", [doc.document_owner],
        {"approval_step": row.approval_step, "decision": decision, "decided_by": frappe.session.user,
         "comments": comments or ""},
        doc,
    )
    return lifecycle.portal_context(frappe.get_doc(DOCTYPE, doc.name))


@frappe.whitelist(methods=["POST"])
def bypass_step(document: str, approval_decision: str, justification: str) -> dict:
    """Skip a step — only with a Core Exception Authorisation recording why (P-25).

    Refused without a justification (and audited, because an attempted
    unexplained bypass is exactly what an auditor asks about), and refused to
    the step's own assignee: waiving your own approval is not an exception, it
    is a missing one.
    """
    from consilium.consilium_core import approvals, audit
    from consilium.policy import lifecycle

    doc = frappe.get_doc(DOCTYPE, document)
    frappe.has_permission(DOCTYPE, "read", doc=doc, throw=True)
    lifecycle.authorise(doc, "authorise_bypass")
    row = _open_step_of(doc, approval_decision)
    if not (justification or "").strip():
        audit.refuse(
            _("A step cannot be bypassed without a documented exception authorisation."),
            subject_doctype=doc.doctype,
            subject_name=doc.name,
            attempted_action="Other",
            control="approval bypass authorisation",
            exc=frappe.ValidationError,
        )
    if row.assigned_to == frappe.session.user:
        audit.refuse(
            _("{0} is assigned the step \"{1}\" and so may not authorise bypassing it.").format(
                frappe.session.user, row.approval_step
            ),
            subject_doctype=doc.doctype,
            subject_name=doc.name,
            attempted_action="Other",
            control="approval bypass segregation",
        )
    authorisation = frappe.get_doc(
        {
            "doctype": "Exception Authorisation",
            "subject_doctype": doc.doctype,
            "subject_name": doc.name,
            "exception_type": "Approval Bypass",
            "justification": justification,
            "requested_by": frappe.session.user,
            "approved_by": frappe.session.user,
            "approved_on": frappe.utils.now(),
        }
    ).insert(ignore_permissions=True)
    # Marked bypassed against its own assignee: the step is being skipped, not
    # decided by someone else. Who authorised the skip is on the authorisation.
    approvals.record_decision(
        row.name, "Bypassed", comments=justification, acting_user=row.assigned_to,
        exception_authorisation=authorisation.name,
    )
    _tell(
        "policy.approval.bypassed", [row.assigned_to, doc.document_owner],
        {"approval_step": row.approval_step, "authorisation": authorisation.name, "justification": justification},
        doc,
    )
    return lifecycle.portal_context(frappe.get_doc(DOCTYPE, doc.name))


@frappe.whitelist(methods=["GET"])
def my_open_steps() -> list[dict]:
    """Open approval steps on governing documents that the caller may decide now.

    ``Approval Decision`` is readable only by administrators and audit, so an
    approver cannot find their own queue over the REST interface; this reads it
    for them, and returns only the rows they may act on.
    """
    user = frappe.session.user
    out = []
    documents: dict[str, object] = {}
    for row in frappe.get_all(
        "Approval Decision",
        filters={"subject_doctype": DOCTYPE, "is_open": 1, "docstatus": ["<", 2]},
        fields=["name", "subject_name", "approval_step", "assigned_to", "based_on_version", "creation"],
        order_by="creation asc",
    ):
        doc = documents.get(row["subject_name"])
        if doc is None:
            doc = documents[row["subject_name"]] = frappe.get_doc(DOCTYPE, row["subject_name"])
        if (row["based_on_version"] or None) != (_current_version_name(doc) or None):
            continue
        if not _may_decide(row, user, doc):
            continue
        out.append(
            {
                "approval_decision": row["name"],
                "document": doc.name,
                "document_name": doc.document_name,
                "lifecycle_phase": doc.lifecycle_phase,
                "approval_step": row["approval_step"],
                "assigned_to": row["assigned_to"],
                "on_behalf": row["assigned_to"] != user,
                "raised_on": row["creation"],
            }
        )
    return out

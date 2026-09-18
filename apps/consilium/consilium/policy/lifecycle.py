"""The document lifecycle, and the gates that guard it.

Two rules shape this module.

**Nothing here compares a state name.** The states and the transitions between
them are rows in the framework's own ``Workflow`` tables — configuration an
administrator edits in a screen that already exists. A transition is performed
by naming an *action*; the configuration says what state that action leads to.
Semantic flags are then set from the new state by Core's ``state_flags``.

**A state can carry preconditions, and those are configuration too.** A
``Document Lifecycle Gate`` row says "entering this state requires this gate to
pass". The gate names a check, and the checks live in a registry here. That is
what makes E12-S6 — publication refused without a complete approval chain —
configuration rather than an ``if`` on the word Published: the gate row is what
binds the check to the state, and removing the row is an audited configuration
change rather than a code change.

A refused transition is written to the refusal log on its own connection, so the
refusal survives the rollback that the refusal itself causes.
"""

from __future__ import annotations

from collections.abc import Callable

import frappe
from frappe import _
from frappe.model.workflow import apply_workflow, get_workflow_name
from frappe.utils import nowdate

from consilium.consilium_core import audit, versioning
from consilium.policy import applicability, metadata, routing

DOCTYPE = "Governing Document"

#: gate code -> callable(doc) -> (passed, reason)
GATES: dict[str, Callable] = {}


def gate(code: str):
    def decorator(fn):
        GATES[code] = fn
        return fn

    return decorator


@gate("Complete Approval Chain")
def _complete_approval_chain(doc):
    status = routing.chain_status(doc)
    if status["complete"]:
        return True, ""
    parts = []
    if status["missing"]:
        parts.append("no approval has been requested for: " + ", ".join(status["missing"]))
    if status["outstanding"]:
        parts.append("still awaiting a decision: " + ", ".join(status["outstanding"]))
    if status["objections"]:
        parts.append(
            "carrying an objection or an unauthorised bypass: " + ", ".join(status["objections"])
        )
    return False, "; ".join(parts)


@gate("Current Version Required")
def _current_version_required(doc):
    if versioning.current_version(doc.doctype, doc.name):
        return True, ""
    return False, "the document has no version in its chain, so there is nothing to publish"


@gate("Publication Record Required")
def _publication_record_required(doc):
    # `["is", "not set"]` compiles to a comparison with the empty string, which
    # PostgreSQL rejects for a date column — so this gate failed outright and no
    # document could reach Implemented. Ask for NULL directly, as inventory.py does.
    publication = frappe.qb.DocType("Document Publication")
    exists = (
        frappe.qb.from_(publication)
        .select(publication.name)
        .where(
            (publication.document == doc.name)
            & (publication.docstatus < 2)
            & publication.withdrawn_on.isnull()
        )
        .limit(1)
        .run()
    )
    if exists:
        return True, ""
    return False, "no publication record exists for this document"


@gate("Implementation Plan Required")
def _implementation_plan_required(doc):
    if frappe.db.exists("Implementation Plan", {"document": doc.name, "docstatus": ["<", 2]}):
        return True, ""
    return False, "no implementation plan has been recorded"


@gate("Required Metadata Complete")
def _required_metadata_complete(doc):
    missing = metadata.missing_fields(doc)
    if not missing:
        return True, ""
    return False, "required metadata is missing: " + ", ".join(missing)


@gate("Applicability Recorded")
def _applicability_recorded(doc):
    if applicability.applicable_scopes(doc.name):
        return True, ""
    return False, (
        "no applicability is recorded, so no affected party could be identified or notified"
    )


def gates_for(doctype: str, state_field: str, state_value: str) -> list[dict]:
    return frappe.get_all(
        "Document Lifecycle Gate",
        filters={
            "target_doctype": doctype,
            "state_field": state_field,
            "state_value": state_value,
            "is_active": 1,
        },
        fields=["name", "gate", "notes"],
        order_by="creation asc",
    )


# --------------------------------------------------------------------------
# The phase, derived from the state (optional, per site)
#
# The lifecycle's workflow runs on ``lifecycle_phase`` out of the box, and that
# field is a Select with a fixed set of phases — the vocabulary lists, filters,
# reports and service levels group by. Its options are the schema, so a new
# workflow state ("Legal Review") was refused: "Lifecycle Phase cannot be
# 'Legal Review'", and Customize Form will not edit a standard field's options.
#
# A site that wants its own states switches the workflow onto the free-text
# ``workflow_state`` field once (``derive_phase_from_state``). From then on the
# phase is *derived*: each state's Workflow State Flag row names the phase it
# belongs to, the controller writes that phase on every save, and gates — which
# are configured per phase — are asked of the phase the next state belongs to.
# Adding a state is then a Workflow row and a flag row; no schema changes.
#
# A site that has not switched behaves exactly as before: the state *is* the
# phase, and nothing below reads the flag table's phase column.
# --------------------------------------------------------------------------

#: The business-facing phase field. Gates are configured against it.
PHASE_FIELD = "lifecycle_phase"

#: The field the workflow runs on once the phase is derived.
DERIVED_STATE_FIELD = "workflow_state"


def phase_of(doctype: str, state_field: str, state_value: str) -> str | None:
    """The phase a state belongs to. A state of the phase field is its own phase;
    any other state's phase is what its Workflow State Flag row names."""
    if state_field == PHASE_FIELD:
        return state_value
    if not state_value:
        return None
    return frappe.db.get_value(
        "Workflow State Flag",
        {"target_doctype": doctype, "state_field": state_field, "state_value": state_value},
        "phase",
    ) or None


def gate_key(doctype: str, state_field: str, state_value: str) -> tuple[str, str]:
    """The (field, value) gates are configured under for entering this state:
    the state itself on a site where the state is the phase, otherwise the
    phase its flag row names."""
    if state_field == PHASE_FIELD or not frappe.get_meta(doctype).has_field(PHASE_FIELD):
        return state_field, state_value
    phase = phase_of(doctype, state_field, state_value)
    return (PHASE_FIELD, phase) if phase else (state_field, state_value)


def sync_phase(doc) -> None:
    """Write the phase the record's workflow state belongs to. Called on save.

    Does nothing where the workflow runs on the phase field itself. Otherwise a
    state whose flag row names no phase is a configuration gap and is refused,
    as a state with no flag row is; and a phase written directly, disagreeing
    with the state, is refused rather than silently put back — the phase moves
    only with the state, through the workflow and its gates.
    """
    name = get_workflow_name(doc.doctype)
    if not name:
        return
    workflow = frappe.get_cached_doc("Workflow", name)
    field = workflow.workflow_state_field
    if field == PHASE_FIELD or not doc.meta.has_field(PHASE_FIELD):
        return
    state = doc.get(field) or (workflow.states[0].state if workflow.states else None)
    phase = phase_of(doc.doctype, field, state)
    if not phase:
        frappe.throw(
            _("Workflow state {0} of {1} names no phase. Set Phase on its Workflow State Flag row to one of: "
              "{2}.").format(state, doc.doctype, ", ".join(_phase_options(doc.doctype))),
            title=_("Phase Not Configured"),
        )
    before = None if doc.is_new() else doc.get_doc_before_save()
    written = doc.get(PHASE_FIELD)
    if before is not None and written != before.get(PHASE_FIELD) and written != phase:
        audit.refuse(
            _("The lifecycle phase of {0} follows its workflow state ({1}, phase {2}); it is not written "
              "directly.").format(doc.name, state, phase),
            subject_doctype=doc.doctype,
            subject_name=doc.name,
            attempted_action="Modify",
            control="lifecycle phase",
            context={"state": state, "phase": phase, "written": written},
            exc=frappe.ValidationError,
        )
    doc.set(PHASE_FIELD, phase)


def _phase_options(doctype: str) -> list[str]:
    field = frappe.get_meta(doctype).get_field(PHASE_FIELD)
    return [option for option in (field.options or "").split("\n") if option] if field else []


def derive_phase_from_state(doctype: str = DOCTYPE) -> dict:
    """Switch a lifecycle onto ``workflow_state``, with the phase derived. Run once.

        bench --site <site> execute consilium.policy.lifecycle.derive_phase_from_state

    In one transaction:

    1. every record's ``workflow_state`` is set to its current phase, so no
       record moves (the framework would otherwise put every record with an
       empty state back to the first one when the workflow's field changes);
    2. each flag row keyed on the phase field is copied onto ``workflow_state``,
       with the same flags and naming itself as its phase — the six seeded
       states are their own phases. The phase rows stay (the seeders keep
       them, and they describe the phases); where both apply, the workflow's
       own state field is applied last and decides (``state_flags``);
    3. the workflow's state field becomes ``workflow_state``.

    Gates, service levels, reports and lists keep reading the phase field,
    which the controller now writes from the state. Safe to run again.
    """
    if frappe.session.user != "Administrator" and "System Manager" not in frappe.get_roles():
        frappe.throw(_("Only a system manager changes what the lifecycle runs on."), frappe.PermissionError)
    workflow = frappe.get_doc("Workflow", get_workflow_name(doctype))
    if workflow.workflow_state_field == DERIVED_STATE_FIELD:
        return {"switched": False, "reason": "already derived"}
    if workflow.workflow_state_field != PHASE_FIELD:
        frappe.throw(_("The {0} workflow runs on {1}, not the phase field; nothing to switch.").format(
            workflow.name, workflow.workflow_state_field))

    table = frappe.qb.DocType(doctype)
    frappe.qb.update(table).set(table.workflow_state, table.lifecycle_phase).run()

    from consilium.consilium_core import state_flags

    copied = 0
    for row in frappe.get_all(
        "Workflow State Flag",
        filters={"target_doctype": doctype, "state_field": PHASE_FIELD},
        fields=["name", "state_value"],
    ):
        existing = frappe.db.get_value(
            "Workflow State Flag",
            {"target_doctype": doctype, "state_field": DERIVED_STATE_FIELD, "state_value": row.state_value},
            ["name", "phase"], as_dict=True,
        )
        if existing:
            if not existing.phase:
                frappe.db.set_value("Workflow State Flag", existing.name, "phase", row.state_value)
            continue
        flag = frappe.copy_doc(frappe.get_doc("Workflow State Flag", row.name))
        flag.state_field = DERIVED_STATE_FIELD
        flag.phase = row.state_value
        flag.insert(ignore_permissions=True)
        copied += 1

    workflow.workflow_state_field = DERIVED_STATE_FIELD
    workflow.save(ignore_permissions=True)
    state_flags.clear_cache(doctype)
    frappe.clear_cache(doctype=doctype)
    return {"switched": True, "flag_rows": copied}


def check_gates(doc, state_field: str, state_value: str) -> list[str]:
    """Every failure reason for entering a state. Empty means the way is clear.

    Gates are configured per phase; a state that is not itself a phase is
    gated as the phase it belongs to (see `gate_key`).
    """
    state_field, state_value = gate_key(doc.doctype, state_field, state_value)
    failures = []
    for row in gates_for(doc.doctype, state_field, state_value):
        check = GATES.get(row["gate"])
        if not check:
            frappe.throw(
                _("Lifecycle gate {0} names no known check. Gates are configuration; the check is code.").format(
                    row["gate"]
                )
            )
        passed, reason = check(doc)
        if not passed:
            failures.append(f"{row['gate']}: {reason}")
    return failures


def _workflow(doctype: str):
    name = get_workflow_name(doctype)
    if not name:
        frappe.throw(
            _("No active workflow is configured for {0}. The lifecycle is configuration and must be seeded.")
            .format(doctype)
        )
    return frappe.get_cached_doc("Workflow", name)


def available_actions(doc) -> list[dict]:
    """The transitions configuration offers from this record's current state."""
    workflow = _workflow(doc.doctype)
    current = doc.get(workflow.workflow_state_field)
    roles = set(frappe.get_roles())
    return [
        {
            "action": row.action,
            "next_state": row.next_state,
            "allowed_role": row.allowed,
            "permitted": row.allowed in roles or "Administrator" in roles,
        }
        for row in workflow.transitions
        if row.state == current
    ]


def _transition_for(workflow, doc, action: str):
    current = doc.get(workflow.workflow_state_field)
    for row in workflow.transitions:
        if row.state == current and row.action == action:
            return row
    return None


def perform(doc, action: str, *, exception_authorisation: str | None = None):
    """Take a configured action on a record, after its gates have passed.

    ``doc`` may be a document or a name. The action is looked up in
    configuration; there is no list of actions in this function.
    """
    if isinstance(doc, str):
        doc = frappe.get_doc(DOCTYPE, doc)

    workflow = _workflow(doc.doctype)
    transition = _transition_for(workflow, doc, action)
    if not transition:
        frappe.throw(
            _("{0} is not an action configured from this record's current state.").format(action),
            title=_("Transition Not Configured"),
        )

    failures = check_gates(doc, workflow.workflow_state_field, transition.next_state)
    if failures and not exception_authorisation:
        audit.refuse(
            _("{0} of {1} is refused. {2}").format(action, doc.name, " | ".join(failures)),
            subject_doctype=doc.doctype,
            subject_name=doc.name,
            attempted_action="Other",
            control="lifecycle gate",
            context={"action": action, "next_state": transition.next_state, "failures": failures},
            exc=frappe.ValidationError,
        )
    if failures and exception_authorisation:
        _validate_exception(doc, exception_authorisation, failures)

    # The document re-checks its gates on save; this transition has just been
    # checked (or authorised by exception), so it is marked cleared for that save.
    # Marked by the phase the transition enters, which is what the controller
    # compares; on a site where the state is the phase the two are the same.
    frappe.flags.consilium_gates_cleared = (
        doc.name, gate_key(doc.doctype, workflow.workflow_state_field, transition.next_state)[1]
    )
    try:
        apply_workflow(doc, action)
    finally:
        frappe.flags.consilium_gates_cleared = None
    doc.reload()
    return doc


def _validate_exception(doc, exception_authorisation: str, failures: list[str]) -> None:
    """A bypass is only a bypass if someone authorised it, in writing, in advance."""
    row = frappe.db.get_value(
        "Exception Authorisation",
        exception_authorisation,
        ["subject_doctype", "subject_name", "requested_by", "approved_by", "valid_to"],
        as_dict=True,
    )
    if not row:
        frappe.throw(_("Exception authorisation {0} does not exist.").format(exception_authorisation))
    if (row["subject_doctype"], row["subject_name"]) != (doc.doctype, doc.name):
        frappe.throw(
            _("Exception authorisation {0} was issued for a different record.").format(exception_authorisation)
        )
    if not row.get("approved_by"):
        audit.refuse(
            _("Exception authorisation {0} has not been approved, so it cannot excuse: {1}").format(
                exception_authorisation, " | ".join(failures)
            ),
            subject_doctype=doc.doctype,
            subject_name=doc.name,
            attempted_action="Other",
            control="exception authorisation",
            exc=frappe.ValidationError,
        )
    unfit = approval_unfit(row)
    if unfit:
        audit.refuse(
            _("Exception authorisation {0} cannot excuse a lifecycle gate: {1}").format(exception_authorisation, unfit),
            subject_doctype=doc.doctype,
            subject_name=doc.name,
            attempted_action="Other",
            control="exception authorisation approver",
            context={"exception_authorisation": exception_authorisation, "failures": failures},
            exc=frappe.ValidationError,
        )
    if row.get("valid_to") and frappe.utils.getdate(row["valid_to"]) < frappe.utils.getdate(nowdate()):
        frappe.throw(_("Exception authorisation {0} has expired.").format(exception_authorisation))


def approval_unfit(row) -> str | None:
    """Why an approved exception authorisation may not excuse a gate, or None.

    Having ``approved_by`` filled in is not enough. Whoever approved it must
    hold the standing that excuses a gate — the same roles that may authorise a
    bypass (``ACTION_ROLES["authorise_bypass"]``), read at the time of use so a
    person who has since lost the role no longer clears anything — and must not
    be the person who asked for it. Without the second rule the policy office's
    own step bypass, which it requests and approves in one act, would also
    excuse every gate on the document.
    """
    approver = row.get("approved_by")
    if not approver:
        return _("it has not been approved")
    if not _holds(ACTION_ROLES["authorise_bypass"], approver):
        return _("it was approved by {0}, who does not hold the standing to excuse a gate ({1})").format(
            approver, ", ".join(ACTION_ROLES["authorise_bypass"])
        )
    if row.get("requested_by") and row.get("requested_by") == approver:
        return _("it was approved by the person who requested it, {0}; nobody approves their own exception").format(
            approver
        )
    return None


@frappe.whitelist(methods=["POST"])
def transition(document: str, action: str, exception_authorisation: str | None = None) -> dict:
    """Perform a lifecycle action. Permission is the framework's; gates are ours.

    POST only: a state change reachable by GET can be triggered by a link or an
    image tag in anything a signed-in user opens, and GET requests are not
    committed by the framework anyway. The portal takes actions through
    ``take_action``, which is POST-only for the same reason.
    """
    doc = frappe.get_doc(DOCTYPE, document)
    doc.check_permission("write")
    perform(doc, action, exception_authorisation=exception_authorisation)
    return {
        "document": doc.name,
        "lifecycle_phase": doc.lifecycle_phase,
        "is_editable": int(doc.is_editable or 0),
        "is_active": int(doc.is_active or 0),
        "requires_review": int(doc.requires_review or 0),
    }


@frappe.whitelist()
def readiness(document: str) -> dict:
    """What stands between this record and each action available to it.

    This is what makes a refusal explicable before it happens rather than after.
    """
    frappe.has_permission(DOCTYPE, "read", doc=document, throw=True)
    doc = frappe.get_doc(DOCTYPE, document)
    workflow = _workflow(doc.doctype)
    out = []
    for entry in available_actions(doc):
        failures = check_gates(doc, workflow.workflow_state_field, entry["next_state"])
        out.append({**entry, "blocked_by": failures})
    return {"document": document, "actions": out, "approval_chain": routing.chain_status(doc)}


# --------------------------------------------------------------------------
# Portal actions
#
# The document page on the portal takes every action the policy module offers.
# It never works out for itself what is allowed: ``document_actions`` tells it,
# and every entry point below asks the same two questions again on the way in —
# does the caller's standing carry the action, and does the document's stage
# offer it now. That is the shape ``governance/formation.py`` set, and for the
# same reason: a button the screen shows is one the server will accept, and a
# request built by hand gets the same answer the screen would have given.
#
# Lifecycle transitions are the exception to the role table. Who may take a
# transition is already configuration — the ``allowed`` role on the Workflow
# row — so it is read from there rather than restated here.
# --------------------------------------------------------------------------

POLICY_OFFICE = "Enterprise Policy Office"
POLICY_OWNER = "Policy Owner"
POLICY_REVIEWER = "Policy Reviewer"

#: The DocTypes already grant this role every right, so refusing it here would
#: only move the same work to the workspace, without the stage checks.
SUPERUSER_ROLES = ("System Manager",)

#: Roles are access configuration, not workflow states. The approval steps
#: themselves are absent: a step is decided by whoever it is assigned to (or
#: their delegate), whatever roles they hold, and Core answers that question.
ACTION_ROLES = {
    "raise_approval_steps": (POLICY_OFFICE, POLICY_OWNER),
    # The authority that may excuse a step. Deliberately not the owner: the
    # person who wants the document published is not the one who waives its
    # approvals.
    "authorise_bypass": (POLICY_OFFICE,),
    "upload_version": (POLICY_OWNER, POLICY_OFFICE),
    "revert_version": (POLICY_OWNER, POLICY_OFFICE),
    # Document Publication is written by the policy office only (its DocPerm),
    # and the existing test pins a reviewer's refusal.
    "record_publication": (POLICY_OFFICE,),
    "withdraw_publication": (POLICY_OFFICE,),
    "open_review_cycle": (POLICY_OWNER, POLICY_OFFICE),
    "conclude_review_cycle": (POLICY_OWNER, POLICY_OFFICE),
    "record_horizon_scan": (POLICY_OWNER, POLICY_OFFICE),
    "record_monitoring_result": (POLICY_OWNER, POLICY_OFFICE),
    # The second line finds violations as often as the first line does, so a
    # reviewer may log one even though they may not edit the document.
    "log_violation": (POLICY_OWNER, POLICY_OFFICE, POLICY_REVIEWER),
    # Moving a violation on — investigating, remediating, closing — is a write
    # on the violation, which the reviewer does not hold (its DocPerm).
    "update_violation": (POLICY_OWNER, POLICY_OFFICE),
    # Asking for a failing gate to be excused, and granting it, are separate
    # acts by separate people: the owner or the office asks, the office grants,
    # and nobody grants their own request (``approval_unfit``).
    "request_gate_exception": (POLICY_OWNER, POLICY_OFFICE),
    "approve_gate_exception": (POLICY_OFFICE,),
    # E15-S5: correcting metadata in place is a write on the record, so it is
    # the roles that hold write on Governing Document.
    "correct_metadata": (POLICY_OWNER, POLICY_OFFICE),
    # Attestation campaigns are run by the policy office for its documents.
    "open_attestation_campaign": (POLICY_OFFICE,),
}

#: The exception type a request to excuse a lifecycle gate is recorded with.
GATE_EXCEPTION_TYPE = "Gate Bypass"

ACTION_LABELS = {
    "take_action": _("Take a lifecycle action"),
    "raise_approval_steps": _("Raise approval steps"),
    "record_step_decision": _("Record step decision"),
    "authorise_bypass": _("Authorise a bypass"),
    "upload_version": _("Upload a new version"),
    "revert_version": _("Revert to an earlier version"),
    "record_publication": _("Record a publication"),
    "withdraw_publication": _("Withdraw a publication"),
    "open_review_cycle": _("Open a review cycle"),
    "conclude_review_cycle": _("Conclude a review cycle"),
    "record_horizon_scan": _("Record a horizon scan"),
    "record_monitoring_result": _("Record a monitoring result"),
    "log_violation": _("Log a violation"),
    "update_violation": _("Move a violation on"),
    "request_gate_exception": _("Ask for a gate to be excused"),
    "approve_gate_exception": _("Approve an exception"),
    "correct_metadata": _("Correct metadata"),
    "open_attestation_campaign": _("Open an attestation campaign"),
}

#: What each stage offers, whoever is asking. Stage-free actions are listed
#: once in ``ANY_STAGE``: a violation or a monitoring result is a fact about
#: the world, recorded when it is found, and an open review cycle or a live
#: publication can be closed whatever the document has done since.
STAGE_ACTIONS = {
    # Drafting and review are the two editable stages; a version taken in
    # review supersedes the one the approvers were looking at, and the chain
    # (which is per version) says so.
    "drafting": ("upload_version", "revert_version"),
    "review": ("upload_version", "revert_version", "raise_approval_steps", "authorise_bypass"),
    # Approved and awaiting publication: open steps can still be settled.
    "settled": ("authorise_bypass",),
    "in_force": ("record_publication", "open_review_cycle", "record_horizon_scan", "open_attestation_campaign"),
}
#: Correcting metadata is not a change of content and makes no new version, so
#: it is open at every stage — the published document is the case E15-S5 is
#: for. A gate exception is asked for and granted where a gate is failing, which
#: can be any stage; whether one is failing is checked by the entry point.
ANY_STAGE = ("withdraw_publication", "conclude_review_cycle", "record_monitoring_result", "log_violation",
             "update_violation", "correct_metadata", "request_gate_exception", "approve_gate_exception")


def stage_of(doc) -> str:
    """Where a document stands, in this module's own vocabulary, from its flags.

    * in force — published or implemented (``is_active``);
    * review — ``requires_review``;
    * drafting — editable and not under review;
    * settled — none of the three: approved and awaiting publication, or
      retired. The flags do not tell those apart, and nothing offered here
      needs them to — the lifecycle actions for each come from configuration.

    The keys are never written to the record and never compared with a state
    label; they exist so the screen can say where the document is.
    """
    if int(doc.get("is_active") or 0):
        return "in_force"
    if int(doc.get("requires_review") or 0):
        return "review"
    if int(doc.get("is_editable") or 0):
        return "drafting"
    return "settled"


def stage_actions(doc) -> set[str]:
    return set(STAGE_ACTIONS.get(stage_of(doc), ())) | set(ANY_STAGE)


def _holds(roles, user: str | None = None) -> bool:
    held = set(frappe.get_roles(user or frappe.session.user))
    return bool(held & (set(roles) | set(SUPERUSER_ROLES)))


def may_take(doc, action: str, user: str | None = None) -> bool:
    """Whether the user's standing carries the action. Says nothing about stage."""
    return _holds(ACTION_ROLES.get(action, ()), user)


def authorise(doc, action: str, *, also_permitted: bool = False) -> None:
    """Refuse, with an audit record, an action the caller's role does not carry;
    then refuse one the document's stage does not offer.

    ``also_permitted`` lets a caller that has already established a right of
    its own — the person a monitoring activity names as responsible — past the
    role check. The stage check still applies to them.
    """
    if not (also_permitted or may_take(doc, action)):
        audit.refuse(
            _("{0} may not take the action \"{1}\" on {2}. It belongs to: {3}.").format(
                frappe.session.user, ACTION_LABELS.get(action, action), doc.name,
                ", ".join(ACTION_ROLES.get(action, ()))
            ),
            subject_doctype=doc.doctype,
            subject_name=doc.name,
            attempted_action="Other",
            control="policy action role",
            context={"action": action},
        )
    if action not in stage_actions(doc):
        frappe.throw(
            _("\"{0}\" is not available while {1} is {2}.").format(
                ACTION_LABELS.get(action, action), doc.name, doc.lifecycle_phase
            ),
            title=_("Not Available At This Stage"),
        )


def may_view(doc, user: str | None = None) -> bool:
    """Read access, or a part in the document's approval.

    An approver often holds no policy role at all — a chief executive approving
    a framework — and still has to see what they are approving, and decide it.
    """
    user = user or frappe.session.user
    if frappe.has_permission(DOCTYPE, "read", doc=doc, user=user):
        return True
    return routing.is_participant(doc, user)


def load_for_portal(document: str):
    doc = frappe.get_doc(DOCTYPE, document)
    if not may_view(doc):
        frappe.throw(
            _("You do not have access to governing document {0}.").format(document), frappe.PermissionError
        )
    return doc


def usable_exception_authorisations(doc) -> list[dict]:
    """Approved, unexpired exception authorisations issued for this document.

    These are what ``perform`` will accept to excuse a failing gate, so the
    screen can offer exactly these and nothing it would then refuse.
    """
    rows = frappe.get_all(
        "Exception Authorisation",
        filters={"subject_doctype": doc.doctype, "subject_name": doc.name},
        fields=["name", "exception_type", "justification", "requested_by", "approved_by", "approved_on",
                "valid_to"],
        order_by="creation desc",
    )
    today = frappe.utils.getdate(nowdate())
    return [
        row for row in rows
        if row.get("approved_by") and not approval_unfit(row)
        and not (row.get("valid_to") and frappe.utils.getdate(row["valid_to"]) < today)
    ]


def pending_exception_authorisations(doc, user: str | None = None) -> list[dict]:
    """Requests to excuse a gate that nobody has approved yet, and whether this viewer may approve each."""
    user = user or frappe.session.user
    rows = frappe.get_all(
        "Exception Authorisation",
        filters={"subject_doctype": doc.doctype, "subject_name": doc.name, "exception_type": GATE_EXCEPTION_TYPE},
        fields=["name", "exception_type", "justification", "requested_by", "approved_by", "valid_to", "creation"],
        order_by="creation desc",
    )
    out = []
    for row in rows:
        if row.get("approved_by"):
            continue
        row["can_approve"] = bool(
            _holds(ACTION_ROLES["approve_gate_exception"], user) and row.get("requested_by") != user
        )
        out.append(row)
    return out


def lifecycle_offers(doc) -> list[dict]:
    """The configured transitions from here, who takes them, and what would refuse them."""
    workflow = _workflow(doc.doctype)
    readable = frappe.has_permission(DOCTYPE, "read", doc=doc)
    rows = []
    for entry in available_actions(doc):
        failures = check_gates(doc, workflow.workflow_state_field, entry["next_state"])
        rows.append({**entry, "blocked_by": failures, "offered": bool(entry["permitted"] and readable),
                     "comments_required": comments_required(doc, entry["next_state"])})
    return rows


def comments_required(doc, next_state: str) -> str | None:
    """Why a transition must carry comments, or None when they are optional.

    Read from the flags the target state is configured with, compared with the
    record's own now — never from the state's name:

    * leaving review back into drafting is a review returned (P-26), and a
      return without the reviewer's comments tells the drafter nothing;
    * leaving force for good is a retirement, and a disposition records why.
    """
    from consilium.consilium_core import state_flags

    workflow = _workflow(doc.doctype)
    after = state_flags.flags_for(doc.doctype, workflow.workflow_state_field, next_state) or {}
    if int(doc.get("requires_review") or 0) and not after.get("requires_review") and after.get("is_editable"):
        return _("A document returned from review carries the reviewer's comments, which are sent to its owner.")
    if int(doc.get("is_active") or 0) and not after.get("is_active") and not after.get("is_editable"):
        return _("A retirement is recorded with its reason, which is sent to everyone the document applies to.")
    return None


def document_summary(doc) -> dict:
    """The few fields every panel needs — enough for an approver without read access."""
    return {
        "name": doc.name,
        "document_name": doc.document_name,
        "document_type": doc.document_type,
        "document_abstract": doc.document_abstract,
        "lifecycle_phase": doc.lifecycle_phase,
        "version_label": doc.version_label,
        "current_version": doc.current_version,
        "document_owner": doc.document_owner,
        "document_approver": doc.document_approver,
        "is_editable": int(doc.is_editable or 0),
        "is_active": int(doc.is_active or 0),
        "requires_review": int(doc.requires_review or 0),
        "allow_print": int(doc.allow_print or 0),
        "allow_download": int(doc.allow_download or 0),
        "handling_classification": doc.handling_classification,
    }


def portal_context(doc) -> dict:
    """Everything the document page's action panels show, and what each may offer."""
    from consilium.policy import publication

    user = frappe.session.user
    readable = bool(frappe.has_permission(DOCTYPE, "read", doc=doc))
    stage = stage_actions(doc)
    actions = {action: action in stage and may_take(doc, action, user) for action in ACTION_ROLES}
    approval = routing.approval_context(doc, user)
    # Approvals are of a version, so there is nothing to raise them against without one.
    actions["raise_approval_steps"] = (
        actions["raise_approval_steps"] and bool(approval["unraised"]) and bool(approval["current_version"])
    )
    actions["authorise_bypass"] = actions["authorise_bypass"] and bool(approval["bypassable"])
    actions["record_step_decision"] = bool(approval["decidable"])
    versions = publication.version_rows(doc)
    actions["revert_version"] = actions["revert_version"] and any(row["revertible"] for row in versions)
    publications = publication.publication_rows(doc)
    actions["withdraw_publication"] = actions["withdraw_publication"] and any(
        not row["withdrawn_on"] for row in publications
    )
    # Review cycles and monitoring results are offered by their own panels'
    # payloads, which know which cycle is open and whose activity it is.
    actions.pop("conclude_review_cycle", None)
    actions.pop("record_monitoring_result", None)
    # Only the lifecycle and approval panels are shown to someone who reads the
    # document through their approval step alone; the rest stay closed to them.
    if not readable:
        for key in ("upload_version", "revert_version", "record_publication", "withdraw_publication",
                    "open_review_cycle", "record_horizon_scan", "log_violation", "update_violation",
                    "correct_metadata", "request_gate_exception", "approve_gate_exception",
                    "open_attestation_campaign"):
            actions[key] = False
    offers = lifecycle_offers(doc) if readable else []
    pending = pending_exception_authorisations(doc, user) if readable else []
    # An exception is asked for only while a gate is refusing one of the
    # configured actions from here — whoever takes that action: the owner may
    # ask on behalf of the office that will publish.
    actions["request_gate_exception"] = actions["request_gate_exception"] and any(
        row["blocked_by"] for row in offers
    )
    actions["approve_gate_exception"] = actions["approve_gate_exception"] and any(
        row["can_approve"] for row in pending
    )
    # Violations are moved on from the monitoring panel, which knows which are open.
    actions.pop("update_violation", None)
    return {
        "document": document_summary(doc),
        "readable": readable,
        "stage": stage_of(doc),
        "lifecycle": offers,
        "exception_authorisations": usable_exception_authorisations(doc),
        "pending_exception_authorisations": pending,
        "approval": approval,
        "versions": versions,
        "publications": publications,
        "rendition_defaults": {
            "allow_print": int(doc.allow_print or 0),
            "allow_download": int(doc.allow_download or 0),
        },
        "audience_types": _select_options("Document Publication", "audience_type"),
        "audience_kinds": _select_options("Publication Audience", "audience_kind"),
        "actions": actions,
        "action_labels": ACTION_LABELS,
    }


def _select_options(doctype: str, fieldname: str) -> list[str]:
    field = frappe.get_meta(doctype).get_field(fieldname)
    return [option for option in (field.options or "").split("\n") if option] if field else []


@frappe.whitelist(methods=["GET"])
def document_actions(document: str) -> dict:
    """The document page's action payload: what may be done now, by this viewer."""
    return portal_context(load_for_portal(document))


@frappe.whitelist(methods=["POST"])
def take_action(
    document: str, action: str, exception_authorisation: str | None = None, comments: str | None = None
) -> dict:
    """Take a configured lifecycle action from the portal, through the gates.

    Who may take a transition is the Workflow row's ``allowed`` role, and that
    is the grant this honours. The framework's save would additionally demand
    write permission, which a reviewer — configured to return a document to
    drafting — does not hold; so the write happens without the DocType check,
    and only after the configured role, read access, and every gate (through
    ``perform``, and again in ``GoverningDocument.validate``) have passed.

    That is also why a reviewer can return a document and still cannot edit it:
    the only write made on their behalf is the transition itself. The content
    stays behind the DocType's write permission, which the reviewer does not
    hold, and the version upload behind ``ACTION_ROLES``.

    ``comments`` travel with the transition to the disposition it produces
    (``consilium.policy.disposition``): a review's comments to the owner, a
    retirement's reason to the audience. Where ``comments_required`` says a
    transition must carry them, it is refused without them.
    """
    from consilium.policy import disposition
    doc = frappe.get_doc(DOCTYPE, document)
    frappe.has_permission(DOCTYPE, "read", doc=doc, throw=True)
    offered = {entry["action"]: entry for entry in available_actions(doc)}
    entry = offered.get(action)
    if not entry:
        frappe.throw(
            _("\"{0}\" is not an action configured from {1}'s current phase ({2}).").format(
                action, doc.name, doc.lifecycle_phase
            ),
            title=_("Not Available At This Stage"),
        )
    if not entry["permitted"]:
        audit.refuse(
            _("{0} may not take the action \"{1}\" on {2}. It belongs to: {3}.").format(
                frappe.session.user, action, doc.name, entry["allowed_role"]
            ),
            subject_doctype=doc.doctype,
            subject_name=doc.name,
            attempted_action="Other",
            control="lifecycle action role",
            context={"action": action},
        )
    if exception_authorisation and exception_authorisation not in {
        row["name"] for row in usable_exception_authorisations(doc)
    }:
        frappe.throw(
            _("Exception authorisation {0} is not an approved, current authorisation for {1}.").format(
                exception_authorisation, doc.name
            ),
            title=_("Not A Usable Exception"),
        )
    comments = (comments or "").strip() or None
    needs = comments_required(doc, entry["next_state"])
    if needs and not comments:
        frappe.throw(needs + " " + _("Enter them to continue."), title=_("Comments Required"))
    doc.flags.ignore_permissions = True
    frappe.flags[disposition.COMMENTS_FLAG] = (doc.name, comments)
    try:
        perform(doc, action, exception_authorisation=exception_authorisation or None)
    finally:
        frappe.flags[disposition.COMMENTS_FLAG] = None
    return portal_context(frappe.get_doc(DOCTYPE, doc.name))


# --------------------------------------------------------------------------
# Excusing a gate: the request, and its approval (P-25)
#
# ``perform`` has always accepted an Exception Authorisation to excuse a
# failing gate, but nothing on the portal could ask for one, and anything with
# ``approved_by`` filled in was accepted — whoever had approved it. Now the
# owner or the office asks, with the justification; the office approves; and
# the approval counts only if the approver holds that standing and is not the
# person who asked (``approval_unfit``). The request is a Core Exception
# Authorisation, so the evidence sits where every other exception's does.
# --------------------------------------------------------------------------


@frappe.whitelist(methods=["POST"])
def request_gate_exception(document: str, justification: str, valid_to: str | None = None) -> dict:
    doc = load_for_portal(document)
    frappe.has_permission(DOCTYPE, "read", doc=doc, throw=True)
    authorise(doc, "request_gate_exception")
    blocked = [row for row in lifecycle_offers(doc) if row["blocked_by"]]
    if not blocked:
        frappe.throw(_("No lifecycle gate is refusing an action on {0}, so there is nothing to excuse.").format(
            doc.name), title=_("Nothing To Excuse"))
    if not (justification or "").strip():
        audit.refuse(
            _("A gate cannot be excused without a documented justification."),
            subject_doctype=doc.doctype,
            subject_name=doc.name,
            attempted_action="Other",
            control="gate exception justification",
            exc=frappe.ValidationError,
        )
    if valid_to and frappe.utils.getdate(valid_to) < frappe.utils.getdate(nowdate()):
        frappe.throw(_("An exception cannot expire before it is granted."), title=_("Dates Out Of Order"))
    failing = sorted({failure.split(":", 1)[0] for row in blocked for failure in row["blocked_by"]})
    frappe.get_doc(
        {
            "doctype": "Exception Authorisation",
            "subject_doctype": doc.doctype,
            "subject_name": doc.name,
            "exception_type": GATE_EXCEPTION_TYPE,
            "justification": justification.strip(),
            "requested_by": frappe.session.user,
            "valid_to": valid_to or None,
            "conditions": _("Requested while failing: {0}").format(", ".join(failing)),
        }
    ).insert(ignore_permissions=True)
    return portal_context(frappe.get_doc(DOCTYPE, doc.name))


@frappe.whitelist(methods=["POST"])
def approve_gate_exception(exception_authorisation: str) -> dict:
    from consilium.consilium_core import notification

    row = frappe.db.get_value(
        "Exception Authorisation",
        exception_authorisation,
        ["name", "subject_doctype", "subject_name", "requested_by", "approved_by", "justification"],
        as_dict=True,
    )
    if not row or row.subject_doctype != DOCTYPE:
        frappe.throw(_("Exception authorisation {0} is not a request on a governing document.").format(
            exception_authorisation))
    doc = load_for_portal(row.subject_name)
    frappe.has_permission(DOCTYPE, "read", doc=doc, throw=True)
    authorise(doc, "approve_gate_exception")
    if row.approved_by:
        frappe.throw(_("Exception authorisation {0} has already been approved.").format(row.name),
                     title=_("Already Approved"))
    if row.requested_by == frappe.session.user:
        audit.refuse(
            _("{0} asked for exception {1} and so may not approve it. Nobody approves their own exception.").format(
                frappe.session.user, row.name
            ),
            subject_doctype=doc.doctype,
            subject_name=doc.name,
            attempted_action="Other",
            control="exception authorisation segregation",
            context={"exception_authorisation": row.name},
        )
    # A save, not a column write: Exception Authorisation tracks changes, and the
    # change log entry is the record of who approved it and when.
    authorisation = frappe.get_doc("Exception Authorisation", row.name)
    authorisation.approved_by = frappe.session.user
    authorisation.approved_on = frappe.utils.now()
    authorisation.save(ignore_permissions=True)
    notification.notify(
        "policy.gate_exception.approved",
        [row.requested_by],
        {"exception_authorisation": row.name, "approved_by": frappe.utils.get_fullname(frappe.session.user),
         "justification": row.justification},
        DOCTYPE,
        doc.name,
    )
    return portal_context(frappe.get_doc(DOCTYPE, doc.name))

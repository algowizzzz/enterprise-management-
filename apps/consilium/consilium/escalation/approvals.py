"""The explicit approval a risk acceptance requires (E16-S4).

A risk acceptance is a decision to carry a risk rather than fix it, so it may
not take effect on one person's say-so: the approval is a separate, recorded act.
Core owns the approval engine — delegation resolution, the bypass rule, the
version the decision was given against — so this module only asks it for a
decision and then stamps the outcome onto the acceptance.

The approval fields on `Risk Acceptance` are read-only in the schema precisely so
that this is the only path that can set them.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import now

from consilium.consilium_core import approvals as core_approvals
from consilium.consilium_core import audit
from consilium.escalation import flags

APPROVAL_STEP = "Risk Acceptance"


def request_approval(risk_acceptance: str, approver: str, required_role: str | None = None):
    """Open a decision for the named approver. The acceptance stays without effect."""
    acceptance = frappe.get_doc("Risk Acceptance", risk_acceptance)
    decision = core_approvals.request_decision(
        subject_doctype="Risk Acceptance",
        subject_name=acceptance.name,
        approval_step=APPROVAL_STEP,
        assigned_to=approver,
        required_role=required_role,
    )
    frappe.db.set_value("Risk Acceptance", acceptance.name, "approval_decision", decision.name)
    return decision


def record_approval(risk_acceptance: str, decision_value: str, *, comments: str | None = None,
                    acting_user: str | None = None):
    """Record the approver's decision and stamp an approval onto the acceptance.

    ``decision_value`` is a configured `Approval Decision` value, passed through
    to Core as data. Whether it *means* approval is read from the flag map, not
    from the string.
    """
    acceptance = frappe.get_doc("Risk Acceptance", risk_acceptance)
    if not acceptance.approval_decision:
        frappe.throw(
            _("No approval has been requested for {0}.").format(acceptance.name),
            title=_("Nothing To Decide"),
        )

    decision = core_approvals.record_decision(
        acceptance.approval_decision, decision_value, comments=comments, acting_user=acting_user
    )
    approving = decision.decision in flags.approving_decisions()
    frappe.db.set_value(
        "Risk Acceptance",
        acceptance.name,
        {
            "approved_by": decision.acted_by if approving else None,
            "approved_on": decision.decided_on if approving else None,
        },
    )
    return decision


def is_approved(acceptance) -> bool:
    """An acceptance is approved when an approval was recorded against it.

    A forum motion is the other accepted route: an approval taken in a meeting is
    evidenced by the motion, not by an in-system decision.
    """
    if acceptance.approval_motion:
        return True
    if not (acceptance.approved_by and acceptance.approved_on):
        return False
    if not acceptance.approval_decision:
        return False
    decision = frappe.db.get_value(
        "Approval Decision", acceptance.approval_decision, ["decision", "is_open"], as_dict=True
    )
    return bool(decision) and not decision.is_open and decision.decision in flags.approving_decisions()


# ============================================================ portal actions
#
# The acceptance is proposed and its approval requested by the first line, and
# decided by the person the request names — or by someone holding a live
# delegation from them, which is Core's question to answer, so Core is asked
# and Core audits a refusal. Which state an acceptance moves to at each step is
# read from the flag map, never named.

#: The role an approver is drawn from, and that the decision records as required.
APPROVER_ROLE = "Head of Risk Governance"

#: The decisions an approver may record. Values handed to Core; what each one
#: *means* is read from its flags (`flags.approving_decisions`), never compared.
DECISION_CHOICES = ("Approved", "Rejected")

ACCEPTANCE_FIELDS = ("risk_acceptance_name", "external_acceptance_id", "start_date", "end_date",
                     "accountable_executive", "rationale", "reassessment_frequency_months",
                     "next_reassessment_on", "governance_forums")


def _state(**wanted) -> str:
    """The one Risk Acceptance state whose flags are ``wanted``. Configuration, found by meaning."""
    values = flags.values_meaning("Risk Acceptance", "status", **wanted)
    if not values:
        frappe.throw(
            _("No Risk Acceptance state is configured with the flags {0}.").format(wanted),
            title=_("State Flags Not Configured"),
        )
    return values[0]


def pending_state() -> str:
    """Awaiting its approver: still open, and asking for review."""
    return _state(is_open=1, requires_review=1)


def approved_state() -> str:
    """In effect: committed and active."""
    return _state(is_committable=1, is_active=1)


def returned_state() -> str:
    """Back with its author: open and editable, asking for nothing, not in effect."""
    return _state(is_open=1, is_editable=1, requires_review=0, is_active=0)


def decision_choices() -> list[dict]:
    """The decisions the screen may offer, and whether each must carry its reason."""
    from consilium.consilium_core import state_flags

    return [
        {"decision": value,
         "needs_reason": bool((state_flags.flags_for("Approval Decision", "decision", value) or {}).get("requires_review"))}
        for value in DECISION_CHOICES
    ]


def approver_candidates(matter=None) -> list[dict]:
    """Enabled people holding the approver role — and, given the matter, able to read it.

    An approver decides from the matter's own page and has to see what they are
    approving, so someone who cannot read the matter is not offered. For a
    sensitive matter that is also what keeps the choice to people cleared for it.
    """
    holders = frappe.get_all("Has Role", filters={"role": APPROVER_ROLE, "parenttype": "User"}, pluck="parent")
    if not holders:
        return []
    people = frappe.get_all(
        "User",
        filters={"name": ["in", holders], "enabled": 1, "user_type": "System User"},
        fields=["name", "full_name"],
        order_by="full_name asc",
    )
    if matter is None:
        return people
    return [p for p in people if frappe.has_permission("Escalation Matter", "read", doc=matter, user=p.name)]


def _open_decision(acceptance) -> dict | None:
    if not acceptance.get("approval_decision"):
        return None
    row = frappe.db.get_value(
        "Approval Decision", acceptance.approval_decision,
        ["name", "assigned_to", "is_open", "decision", "decided_on", "acted_by", "comments"], as_dict=True,
    )
    return row


def _may_decide(decision: dict | None, acceptance: str, user: str) -> bool:
    if not decision or not decision.is_open:
        return False
    from consilium.consilium_core import delegation

    return bool(delegation.resolve_actor(
        decision.assigned_to, delegation.ACTION_APPROVE, acting_user=user,
        doctype="Risk Acceptance", name=acceptance,
    )["permitted"])


def acceptances_for(matter, stage: set[str], user: str) -> list[dict]:
    """The matter's acceptances the caller may read, with what they may do to each."""
    from consilium.escalation import resolution

    can_request = "request_approval" in stage and resolution.may_take(matter, "request_approval", user)
    decide_stage = "decide_approval" in stage
    rows = frappe.get_list(
        "Risk Acceptance",
        filters={"escalation_matter": matter.name},
        fields=["name", "risk_acceptance_name", "status", "is_editable", "requires_review", "is_open",
                "is_active", "approval_decision", "approval_motion", "approved_by", "approved_on",
                "accountable_executive", "start_date", "end_date", "rationale"],
        order_by="start_date desc",
    )
    for row in rows:
        decision = _open_decision(row)
        waiting = bool(decision and decision.is_open)
        row["decision"] = decision
        row["can_request"] = bool(can_request and row.is_editable and not row.requires_review and not waiting)
        row["can_decide"] = bool(decide_stage and _may_decide(decision, row.name, user))
    return rows


def _load_acceptance(name: str):
    if not name or not frappe.db.exists("Risk Acceptance", name):
        frappe.throw(_("Risk acceptance {0} is not available to you.").format(name), frappe.PermissionError)
    doc = frappe.get_doc("Risk Acceptance", name)
    if not frappe.has_permission("Risk Acceptance", "read", doc=doc):
        frappe.throw(_("Risk acceptance {0} is not available to you.").format(name), frappe.PermissionError)
    return doc


@frappe.whitelist(methods=["POST"])
def add_risk_acceptance(escalation_matter: str, values) -> dict:
    """Propose a risk acceptance on the matter (E16-S4). Escalation Owner, while it is worked.

    It starts without effect; the template for the matter's type and severity is
    applied by the acceptance's own controller.
    """
    from consilium.escalation import resolution

    matter = resolution.load_matter(escalation_matter, "write")
    resolution.authorise(matter, "add_risk_acceptance")
    doc = frappe.get_doc({"doctype": "Risk Acceptance", **resolution._clean(values, ACCEPTANCE_FIELDS),
                          "escalation_matter": matter.name, "status": returned_state()})
    doc.insert(ignore_permissions=True)
    return resolution.workbench(matter.name)


@frappe.whitelist(methods=["POST"])
def request_risk_acceptance_approval(risk_acceptance: str, approver: str) -> dict:
    """Ask a named approver to decide an acceptance. Escalation Owner.

    Four eyes: the approver may be neither the person asking nor the executive
    accountable for the acceptance, because an acceptance approved by its own
    author has not been approved at all.
    """
    from consilium.escalation import resolution

    acceptance = _load_acceptance(risk_acceptance)
    matter = resolution.load_matter(acceptance.escalation_matter, "write")
    resolution.authorise(matter, "request_approval")
    if not acceptance.is_editable or acceptance.requires_review or (
        (_open_decision(acceptance) or {}).get("is_open")
    ):
        frappe.throw(
            _("Risk acceptance {0} is {1}; approval can be requested only while it is with its author.").format(
                acceptance.name, acceptance.status),
            title=_("Not Available At This Stage"),
        )
    if approver in (frappe.session.user, acceptance.accountable_executive):
        audit.refuse(
            _("{0} cannot approve risk acceptance {1}: an approver must be independent of the person "
              "asking and of the accountable executive.").format(approver, acceptance.name),
            subject_doctype="Risk Acceptance",
            subject_name=acceptance.name,
            attempted_action="Other",
            control="four eyes",
        )
    if approver not in [row.name for row in approver_candidates(matter)]:
        frappe.throw(
            _("{0} cannot be asked to approve: an approver holds the {1} role and can see the matter.").format(
                approver, APPROVER_ROLE),
            title=_("Not An Approver"),
        )
    request_approval(acceptance.name, approver, required_role=APPROVER_ROLE)
    acceptance.reload()
    acceptance.status = pending_state()
    acceptance.save(ignore_permissions=True)
    return resolution.workbench(matter.name)


@frappe.whitelist(methods=["POST"])
def decide_risk_acceptance(risk_acceptance: str, decision: str, comments: str | None = None) -> dict:
    """The named approver (or their live delegate) decides the acceptance.

    No escalation role is asked for: the right to decide comes from being asked,
    and Core refuses — audited — anyone who is neither the assignee nor holding
    a delegation from them. The approver must still be able to see the matter,
    so a sensitive matter can be decided only by someone cleared for it. An
    approval gives the acceptance effect; anything else returns it to its author.
    """
    from consilium.consilium_core import state_flags
    from consilium.escalation import resolution

    acceptance = _load_acceptance(risk_acceptance)
    matter = resolution.load_matter(acceptance.escalation_matter, "read")
    if "decide_approval" not in resolution.stage_actions(matter):
        frappe.throw(
            _("Escalation {0} is {1}; its acceptances cannot be decided now.").format(matter.name, matter.status),
            title=_("Not Available At This Stage"),
        )
    if decision not in DECISION_CHOICES:
        frappe.throw(_("{0} is not a decision an approver can record.").format(decision), title=_("Unknown Decision"))
    open_decision = _open_decision(acceptance)
    if not (open_decision and open_decision.is_open):
        frappe.throw(_("No approval is waiting on risk acceptance {0}.").format(acceptance.name),
                     title=_("Nothing To Decide"))
    if (state_flags.flags_for("Approval Decision", "decision", decision) or {}).get("requires_review") \
            and not (comments or "").strip():
        frappe.throw(_("A decision of {0} is recorded with its reason.").format(decision), title=_("Reason Required"))

    recorded = record_approval(acceptance.name, decision, comments=comments, acting_user=frappe.session.user)
    acceptance.reload()
    acceptance.status = approved_state() if recorded.decision in flags.approving_decisions() else returned_state()
    acceptance.save(ignore_permissions=True)
    return resolution.workbench(matter.name)

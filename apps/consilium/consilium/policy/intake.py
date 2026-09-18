"""Intake, and the classification that routes it.

P-16 wants a dynamic question set whose answers produce a major/minor
classification, with a full audit trail. Core already has that engine, versioned
rule sets and an immutable assessment included, so this module writes none of it.
What it does is decide *which* rule set applies, hand the answers over, and copy
the outcome onto the request so routing and service levels can read it.

The property that matters, and that the tests pin down: a classification made
under one rule-set version does not change when the rules are later edited. Core
seals a rule set the first time it classifies anything and stores the version
label and the full evaluation trace on the assessment; a rule change is therefore
a new rule set, and the old assessment keeps answering for itself.
"""

from __future__ import annotations

import json

import frappe
from frappe import _
from frappe.utils import now, nowdate

from consilium.consilium_core import classification, sla
from consilium.policy import naming

REQUEST_DOCTYPE = "Document Intake Request"
DOCUMENT_DOCTYPE = "Governing Document"


def active_rule_set(doctype: str = REQUEST_DOCTYPE) -> str | None:
    """The rule set in force for a DocType today: active, effective, newest first."""
    rows = frappe.get_all(
        "Classification Rule Set",
        filters={
            "applies_to_doctype": doctype,
            "is_active": 1,
            "effective_from": ["<=", nowdate()],
        },
        fields=["name", "effective_to", "effective_from", "version_label"],
        order_by="effective_from desc, creation desc",
    )
    for row in rows:
        if row.get("effective_to") and frappe.utils.getdate(row["effective_to"]) < frappe.utils.getdate(nowdate()):
            continue
        return row["name"]
    return None


def classify(request: str, answers: dict | str, *, rule_set: str | None = None):
    """Classify a request through Core's engine and copy the outcome onto it."""
    if isinstance(answers, str):
        answers = json.loads(answers)
    doc = frappe.get_doc(REQUEST_DOCTYPE, request)
    naming.check_intake(doc)
    rule_set = rule_set or active_rule_set()
    if not rule_set:
        frappe.throw(
            _("No active classification rule set applies to {0}. The questions and rules are data and "
              "must be configured before intake can be classified.").format(REQUEST_DOCTYPE)
        )

    assessment = classification.classify(
        rule_set,
        answers,
        subject_doctype=REQUEST_DOCTYPE,
        subject_name=doc.name,
    )
    doc.classification_assessment = assessment.name
    doc.change_classification = classification.effective_outcome(assessment.name)
    doc.workflow_state = "Classified"
    doc.save(ignore_permissions=True)
    start_service_level(doc)
    return assessment


def override(request: str, outcome: str, justification: str, approved_by: str | None = None):
    """Override an outcome through Core, then re-copy the effective outcome."""
    doc = frappe.get_doc(REQUEST_DOCTYPE, request)
    if not doc.classification_assessment:
        frappe.throw(_("{0} has not been classified, so there is nothing to override.").format(request))
    classification.override(doc.classification_assessment, outcome, justification, approved_by)
    doc.change_classification = classification.effective_outcome(doc.classification_assessment)
    doc.save(ignore_permissions=True)
    return doc


@frappe.whitelist()
def challenge(request: str, statement: str) -> dict:
    """Record a requester's challenge to their classification (E13-S3).

    A challenge is recorded, not acted on: it does not move the outcome. Moving
    the outcome is an override, which is a separate, approved act.
    """
    doc = frappe.get_doc(REQUEST_DOCTYPE, request)
    doc.check_permission("write")
    if not (statement or "").strip():
        frappe.throw(_("A challenge needs a statement; that statement is the record of it."))
    doc.classification_challenge = statement
    doc.challenged_by = frappe.session.user
    doc.challenged_on = now()
    doc.save()
    return {"request": doc.name, "challenged_on": doc.challenged_on}


@frappe.whitelist()
def explain(request: str) -> dict:
    """The outcome, the rule that fired and the trace — what the requester sees."""
    frappe.has_permission(REQUEST_DOCTYPE, "read", doc=request, throw=True)
    doc = frappe.get_doc(REQUEST_DOCTYPE, request)
    if not doc.classification_assessment:
        return {"request": request, "classified": False}
    assessment = frappe.get_doc("Classification Assessment", doc.classification_assessment)
    return {
        "request": request,
        "classified": True,
        "rule_set": assessment.rule_set,
        "rule_set_version_label": assessment.rule_set_version_label,
        "matched_rule_code": assessment.matched_rule_code,
        "outcome": assessment.outcome,
        "effective_outcome": classification.effective_outcome(assessment.name),
        "outcome_rationale": assessment.outcome_rationale,
        "evaluation_trace": assessment.evaluation_trace,
        "challenge": doc.classification_challenge,
    }


def start_service_level(doc) -> str | None:
    """E13-S4: classification drives the service level, not only the route."""
    for name in frappe.get_all(
        "SLA Definition", filters={"target_doctype": REQUEST_DOCTYPE, "is_active": 1}, pluck="name"
    ):
        definition = frappe.get_doc("SLA Definition", name)
        if not sla.applies_to(definition, REQUEST_DOCTYPE, doc.name):
            continue
        clock = sla.start_clock(name, REQUEST_DOCTYPE, doc.name)
        frappe.db.set_value(REQUEST_DOCTYPE, doc.name, "sla_clock", clock.name)
        return clock.name
    return None


def create_document(request: str, **overrides) -> str:
    """Turn a classified request into a repository record.

    The request keeps the link, so the classification that routed the document's
    approval can always be traced back from the document itself.
    """
    doc = frappe.get_doc(REQUEST_DOCTYPE, request)
    if doc.created_document:
        return doc.created_document
    naming.check_intake(doc)

    values = {
        "doctype": DOCUMENT_DOCTYPE,
        "document_name": doc.proposed_document_name or doc.name,
        "document_type": doc.proposed_document_type,
        "document_owner": doc.requester,
        "document_approver": doc.requester,
        "primary_risk_category": doc.primary_risk_category,
        "effective_on": doc.proposed_effective_date,
    }
    values.update(overrides)
    document = frappe.get_doc(values).insert(ignore_permissions=True)

    doc.created_document = document.name
    doc.workflow_state = "Fulfilled"
    doc.save(ignore_permissions=True)
    # A fulfilled request has met its service level; left running, its clock
    # would breach later and report a finished request as late.
    if doc.sla_clock and frappe.db.get_value("SLA Clock", doc.sla_clock, "is_open"):
        sla.stop_clock(doc.sla_clock)
    return document.name


# --------------------------------------------------------------------------
# Portal entry points: the intake screen (P-16, E13)
#
# ``classify``, ``override`` and ``create_document`` had no caller from any
# screen, and ``explain`` and ``challenge`` were whitelisted but unused. The
# intake page (``/policy-intake``) raises a request, renders the active rule
# set's questions from the rule set itself, classifies, shows the outcome with
# the rule that fired, takes a challenge, and — for the policy office — records
# an override or creates the document.
#
# What may be done is decided here from facts on the request (classified or
# not, a document created or not, open or not) and the caller's standing, never
# from the label in ``workflow_state``.
# --------------------------------------------------------------------------

POLICY_OFFICE = "Enterprise Policy Office"
SUPERUSER_ROLES = ("System Manager",)

#: The state a new request is written in, and the one a withdrawal writes.
#: Values handed to the record; the flags they map to are what logic reads.
STATE_REQUESTED = "Requested"
STATE_WITHDRAWN = "Withdrawn"
STATE_FULFILLED = "Fulfilled"

#: A request of this type proposes a new document rather than naming one.
REQUEST_CREATE = "Create"

#: Who may take each intake action besides the requester. The requester
#: answers their own questions, challenges their own outcome and may withdraw
#: their own request; the policy office may do all of that on their behalf and,
#: alone, override an outcome or create the document.
INTAKE_ROLES = {
    "classify": (POLICY_OFFICE,),
    "challenge": (POLICY_OFFICE,),
    "withdraw": (POLICY_OFFICE,),
    "override": (POLICY_OFFICE,),
    "create_document": (POLICY_OFFICE,),
}
REQUESTER_ACTIONS = ("classify", "challenge", "withdraw")

INTAKE_LABELS = {
    "classify": _("Answer the classification questions"),
    "challenge": _("Challenge the classification"),
    "withdraw": _("Withdraw the request"),
    "override": _("Override the classification"),
    "create_document": _("Create the document"),
}


def _holds(roles, user: str | None = None) -> bool:
    held = set(frappe.get_roles(user or frappe.session.user))
    return bool(held & (set(roles) | set(SUPERUSER_ROLES)))


def intake_stage_actions(doc) -> set[str]:
    """What the request's facts allow, whoever is asking."""
    if not int(doc.get("is_open") or 0):
        return set()
    if not doc.classification_assessment:
        return {"classify", "withdraw"}
    actions = {"override", "withdraw"}
    if not doc.classification_challenge:
        actions.add("challenge")
    # A change or retirement names the document it concerns; only a request
    # that names none produces a new record.
    if not doc.created_document and not doc.subject_document:
        actions.add("create_document")
    return actions


def may_take_intake(doc, action: str, user: str | None = None) -> bool:
    user = user or frappe.session.user
    if action in REQUESTER_ACTIONS and user == doc.requester:
        return True
    return _holds(INTAKE_ROLES.get(action, ()), user)


def _authorise_intake(doc, action: str) -> None:
    from consilium.consilium_core import audit

    if not may_take_intake(doc, action):
        holders = list(INTAKE_ROLES.get(action, ()))
        if action in REQUESTER_ACTIONS:
            holders.insert(0, _("the requester"))
        audit.refuse(
            _("{0} may not take the action \"{1}\" on intake request {2}. It belongs to: {3}.").format(
                frappe.session.user, INTAKE_LABELS[action], doc.name, ", ".join(holders)
            ),
            subject_doctype=doc.doctype,
            subject_name=doc.name,
            attempted_action="Other",
            control="intake action role",
            context={"action": action},
        )
    if action not in intake_stage_actions(doc):
        frappe.throw(
            _("\"{0}\" is not available on intake request {1} now.").format(INTAKE_LABELS[action], doc.name),
            title=_("Not Available At This Stage"),
        )


def questions_for(rule_set: str | None) -> dict | None:
    """The rule set's questions and answer options, in display order, for rendering.

    The screen writes no question of its own: add a question or an option to the
    rule set (as a new version) and the form follows.
    """
    if not rule_set:
        return None
    doc = frappe.get_doc("Classification Rule Set", rule_set)
    options: dict[str, list[dict]] = {}
    for option in sorted(doc.answer_options, key=lambda o: (int(o.display_order or 0), o.idx)):
        options.setdefault(option.question_code, []).append(
            {"code": option.option_code, "text": option.option_text or option.option_code}
        )
    return {
        "rule_set": doc.name,
        "title": doc.rule_set_title,
        "version_label": doc.version_label,
        "outcomes": sorted({r.outcome for r in doc.rules if r.outcome} | {doc.default_outcome}),
        "questions": [
            {
                "code": q.question_code,
                "text": q.question_text,
                "mode": q.answer_mode,
                "required": int(q.is_required or 0),
                "depends_on_question": q.depends_on_question,
                "depends_on_answer": q.depends_on_answer,
                "options": options.get(q.question_code, []),
            }
            for q in sorted(doc.questions, key=lambda q: (int(q.display_order or 0), q.idx))
        ],
    }


def _explanation(doc) -> dict | None:
    if not doc.classification_assessment:
        return None
    assessment = frappe.get_doc("Classification Assessment", doc.classification_assessment)
    # A JSON column comes back parsed on one path and raw on another.
    trace = assessment.evaluation_trace or {}
    if isinstance(trace, str):
        try:
            trace = json.loads(trace)
        except ValueError:
            trace = {}
    return {
        "assessment": assessment.name,
        "rule_set": assessment.rule_set,
        "rule_set_version_label": assessment.rule_set_version_label,
        "matched_rule_code": assessment.matched_rule_code,
        "outcome": assessment.outcome,
        "effective_outcome": classification.effective_outcome(assessment.name),
        "outcome_rationale": assessment.outcome_rationale,
        "overridden": int(assessment.get("overridden") or 0),
        "override_justification": assessment.get("override_justification"),
        "override_approved_by": assessment.get("override_approved_by"),
        "evaluated_by": assessment.evaluated_by,
        "evaluated_on": str(assessment.evaluated_on or ""),
        "answers": trace.get("answers") or {},
        "rules": trace.get("rules") or [],
    }


def intake_context(doc) -> dict:
    user = frappe.session.user
    stage = intake_stage_actions(doc)
    explanation = _explanation(doc)
    rule_set = explanation["rule_set"] if explanation else active_rule_set()
    clock = None
    if doc.sla_clock:
        clock = frappe.db.get_value(
            "SLA Clock", doc.sla_clock, ["name", "is_open", "status", "target_on", "breached_on"], as_dict=True
        ) if frappe.db.exists("SLA Clock", doc.sla_clock) else None
    return {
        "request": doc.as_dict(convert_dates_to_str=True),
        "is_requester": user == doc.requester,
        "questions": questions_for(rule_set),
        "explanation": explanation,
        "sla_clock": clock,
        "created_document_name": frappe.db.get_value(DOCUMENT_DOCTYPE, doc.created_document, "document_name")
        if doc.created_document else None,
        "subject_document_name": frappe.db.get_value(DOCUMENT_DOCTYPE, doc.subject_document, "document_name")
        if doc.subject_document else None,
        "actions": {action: action in stage and may_take_intake(doc, action, user) for action in INTAKE_LABELS},
        "action_labels": INTAKE_LABELS,
    }


def _load_request(request: str):
    doc = frappe.get_doc(REQUEST_DOCTYPE, request)
    doc.check_permission("read")
    return doc


def _fresh_request(doc) -> dict:
    return intake_context(frappe.get_doc(REQUEST_DOCTYPE, doc.name))


@frappe.whitelist(methods=["GET"])
def request_context(request: str) -> dict:
    return intake_context(_load_request(request))


@frappe.whitelist(methods=["GET"])
def form_options() -> dict:
    """What the new-request form offers, from the DocType and the rule set in force."""
    field = frappe.get_meta(REQUEST_DOCTYPE).get_field("request_type")
    return {
        "request_types": [o for o in (field.options or "").split("\n") if o],
        "create_type": REQUEST_CREATE,
        "can_raise": bool(frappe.has_permission(REQUEST_DOCTYPE, "create")),
        "rule_set": questions_for(active_rule_set()),
    }


@frappe.whitelist(methods=["POST"])
def raise_request(
    request_type: str,
    business_justification: str,
    proposed_document_name: str | None = None,
    proposed_document_type: str | None = None,
    subject_document: str | None = None,
    primary_risk_category: str | None = None,
    proposed_effective_date: str | None = None,
) -> dict:
    """Raise an intake request in the caller's name.

    Inserted through the framework's permission check, not round it: raising a
    request is a create, and who may create one is the DocType's to say.
    """
    field = frappe.get_meta(REQUEST_DOCTYPE).get_field("request_type")
    if request_type not in [o for o in (field.options or "").split("\n") if o]:
        frappe.throw(_("{0} is not a kind of request.").format(request_type), title=_("Unknown Request Type"))
    if not (business_justification or "").strip():
        frappe.throw(_("Say why the request is needed: the justification is what the policy office reads first."),
                     title=_("Justification Required"))
    if request_type == REQUEST_CREATE:
        if not (proposed_document_name or "").strip() or not proposed_document_type:
            frappe.throw(_("A request for a new document proposes its name and type."),
                         title=_("Proposal Incomplete"))
        subject_document = None
    else:
        if not subject_document:
            frappe.throw(_("A change or retirement names the document it concerns."),
                         title=_("Document Required"))
        frappe.has_permission(DOCUMENT_DOCTYPE, "read", doc=subject_document, throw=True)
    doc = frappe.get_doc(
        {
            "doctype": REQUEST_DOCTYPE,
            "request_type": request_type,
            "requester": frappe.session.user,
            "business_justification": business_justification.strip(),
            "proposed_document_name": (proposed_document_name or "").strip() or None,
            "proposed_document_type": proposed_document_type or None,
            "subject_document": subject_document or None,
            "primary_risk_category": primary_risk_category or None,
            "proposed_effective_date": proposed_effective_date or None,
            "workflow_state": STATE_REQUESTED,
        }
    ).insert()
    return intake_context(doc)


@frappe.whitelist(methods=["POST"])
def classify_request(request: str, answers) -> dict:
    """Answer the questions and classify, through Core's engine (which validates the answers)."""
    doc = _load_request(request)
    _authorise_intake(doc, "classify")
    answers = frappe.parse_json(answers) if isinstance(answers, str) else (answers or {})
    answers = {code: value for code, value in answers.items() if value not in (None, "", [])}
    classify(doc.name, answers)
    return _fresh_request(doc)


@frappe.whitelist(methods=["POST"])
def challenge_request(request: str, statement: str) -> dict:
    """The requester's challenge (E13-S3). Recorded, not acted on; see ``challenge``."""
    doc = _load_request(request)
    _authorise_intake(doc, "challenge")
    if not (statement or "").strip():
        frappe.throw(_("A challenge needs a statement; that statement is the record of it."),
                     title=_("Statement Required"))
    doc.classification_challenge = statement.strip()
    doc.challenged_by = frappe.session.user
    doc.challenged_on = now()
    doc.save(ignore_permissions=True)
    return _fresh_request(doc)


@frappe.whitelist(methods=["POST"])
def override_request(request: str, outcome: str, justification: str) -> dict:
    """The policy office overrides an outcome; Core keeps the original and refuses an unjustified one."""
    doc = _load_request(request)
    _authorise_intake(doc, "override")
    allowed = (questions_for(frappe.db.get_value(
        "Classification Assessment", doc.classification_assessment, "rule_set")) or {}).get("outcomes", [])
    if outcome not in allowed:
        frappe.throw(_("{0} is not an outcome this rule set can give.").format(outcome), title=_("Unknown Outcome"))
    override(doc.name, outcome, justification or "", approved_by=frappe.session.user)
    return _fresh_request(doc)


@frappe.whitelist(methods=["POST"])
def create_from_request(
    request: str,
    document_name: str,
    document_type: str,
    owning_operating_group: str,
    primary_risk_category: str,
    document_owner: str,
    document_approver: str,
    handling_classification: str | None = None,
) -> dict:
    """The policy office turns a classified request into a repository record."""
    doc = _load_request(request)
    _authorise_intake(doc, "create_document")
    values = {
        "document_name": (document_name or "").strip(),
        "document_type": document_type,
        "owning_operating_group": owning_operating_group,
        "primary_risk_category": primary_risk_category,
        "document_owner": document_owner,
        "document_approver": document_approver,
    }
    missing = [key for key, value in values.items() if not value]
    if missing:
        frappe.throw(_("The new document needs: {0}.").format(", ".join(missing)), title=_("Details Required"))
    if handling_classification:
        values["handling_classification"] = handling_classification
    create_document(doc.name, **values)
    return _fresh_request(doc)


@frappe.whitelist(methods=["POST"])
def withdraw_request(request: str, reason: str) -> dict:
    """Withdraw an open request, keeping the reason on its timeline."""
    doc = _load_request(request)
    _authorise_intake(doc, "withdraw")
    if not (reason or "").strip():
        frappe.throw(_("A withdrawal is recorded with its reason."), title=_("Reason Required"))
    doc.workflow_state = STATE_WITHDRAWN
    doc.save(ignore_permissions=True)
    doc.add_comment("Comment", _("Withdrawn by {0}: {1}").format(frappe.session.user, reason.strip()))
    if doc.sla_clock and frappe.db.get_value("SLA Clock", doc.sla_clock, "is_open"):
        sla.stop_clock(doc.sla_clock)
    return _fresh_request(doc)


# --------------------------------------------------------------------------
# Fulfilling change and retirement requests
#
# A request to create a document is fulfilled by ``create_document``, which
# makes the record. A request to *change* or *retire* one names a document that
# already exists, and nothing used to close it: the change was made and the
# document retired, and the request stayed open with its service-level clock
# running until it reported a finished request as late. The document's own
# movement closes it now — ``disposition.on_document_update`` calls this when a
# version comes into force (a change) or the document leaves force for good (a
# retirement).
# --------------------------------------------------------------------------


def fulfil_for_document(document: str, request_type: str, note: str) -> list[str]:
    """Fulfil every open request of one type that names this document.

    Open is the request's ``is_open`` flag, whatever its state is called. Each
    request fulfilled has its clock stopped and a comment saying what fulfilled
    it, so the requester can see why their request closed.
    """
    fulfilled = []
    for name in frappe.get_all(
        REQUEST_DOCTYPE,
        filters={"subject_document": document, "request_type": request_type, "is_open": 1},
        pluck="name",
        order_by="creation asc",
    ):
        request = frappe.get_doc(REQUEST_DOCTYPE, name)
        request.workflow_state = STATE_FULFILLED
        request.save(ignore_permissions=True)
        request.add_comment("Comment", _("Fulfilled: {0}").format(note))
        if request.sla_clock and frappe.db.get_value("SLA Clock", request.sla_clock, "is_open"):
            sla.stop_clock(request.sla_clock)
        fulfilled.append(name)
    return fulfilled

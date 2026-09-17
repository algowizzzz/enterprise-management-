"""Configuration the Policy module ships with.

Everything here is configuration, not code: the semantic flag map, the lifecycle
workflow with its states and transitions, the gates that guard entry to a state,
the default approval routes and the intake classification rule set. An
administrator can change any of it without a deployment, which is the point —
E12-S2 and E12-S3 both require the lifecycle and the routing to be configuration.

Seeds are idempotent, and a row an administrator has edited is left alone.
"""

from __future__ import annotations

# Seeded configuration is in force from installation. See the note at its use.
CONFIGURATION_EPOCH = "2000-01-01"


import json

import frappe

from consilium.consilium_core import state_flags
from consilium.policy.setup.state_flag_seed import FLAG_COLUMNS, STATE_FLAGS

WORKFLOW_NAME = "Governing Document Lifecycle"
DOCUMENT_DOCTYPE = "Governing Document"
STATE_FIELD = "lifecycle_phase"

#: (state, docstatus, roles allowed to edit in this state)
LIFECYCLE_STATES = [
    ("Draft", "0", "Policy Owner"),
    ("Review", "0", "Policy Reviewer"),
    ("Approved", "0", "Enterprise Policy Office"),
    ("Published", "0", "Enterprise Policy Office"),
    ("Implemented", "0", "Policy Owner"),
    ("Retired", "0", "Enterprise Policy Office"),
]

#: (from state, action, next state, role allowed, allow self approval)
LIFECYCLE_TRANSITIONS = [
    ("Draft", "Submit for Review", "Review", "Policy Owner", 1),
    ("Review", "Return to Drafting", "Draft", "Policy Reviewer", 1),
    ("Review", "Record Approval", "Approved", "Enterprise Policy Office", 1),
    ("Approved", "Return to Drafting", "Draft", "Enterprise Policy Office", 1),
    ("Approved", "Publish", "Published", "Enterprise Policy Office", 1),
    ("Published", "Confirm Implementation", "Implemented", "Policy Owner", 1),
    ("Published", "Reopen for Change", "Draft", "Policy Owner", 1),
    ("Published", "Retire", "Retired", "Enterprise Policy Office", 1),
    ("Implemented", "Reopen for Change", "Draft", "Policy Owner", 1),
    ("Implemented", "Retire", "Retired", "Enterprise Policy Office", 1),
    ("Retired", "Reinstate", "Draft", "Enterprise Policy Office", 1),
]

#: (state value, gate, note)
LIFECYCLE_GATES = [
    ("Approved", "Required Metadata Complete",
     "A document cannot be approved while a field its template requires is empty."),
    ("Published", "Complete Approval Chain",
     "P-25 / E12-S6. Publication is refused unless every step of the routed approval path has been "
     "decided without an outstanding objection. A bypass needs a recorded Exception Authorisation."),
    ("Published", "Current Version Required",
     "There is nothing to publish without a version in the chain."),
    ("Published", "Applicability Recorded",
     "E11-S5. Notification of affected parties derives from applicability, so publishing with no "
     "applicability recorded would notify nobody and leave no record of who was in scope."),
    ("Implemented", "Publication Record Required",
     "Implementation is confirmed against what was published."),
]

#: route_title, priority, document_type, change_classification, steps
#: step = (sequence, label, required role, assignee source)
APPROVAL_ROUTES = [
    (
        "Major Change Route", 10, None, "Major",
        "A major change carries first-line, second-line and policy-office approval.",
        [
            (1, "First Line Approval", "Policy Owner", "Document Approver"),
            (2, "Second Line Approval", "Policy Reviewer", "Document Sponsor"),
            (3, "Enterprise Policy Office Approval", "Enterprise Policy Office", "Document Liaison"),
        ],
    ),
    (
        "Minor Change Route", 20, None, "Minor",
        "A minor change is approved by the document approver alone.",
        [
            (1, "Document Approver Approval", "Policy Owner", "Document Approver"),
        ],
    ),
    (
        "Default Route", 900, None, None,
        "Applies when no more specific route matches. Conservative by design.",
        [
            (1, "Document Approver Approval", "Policy Owner", "Document Approver"),
            (2, "Enterprise Policy Office Approval", "Enterprise Policy Office", "Document Approver"),
        ],
    ),
]

RULE_SET_TITLE = "Policy Change Classification"
RULE_SET_VERSION = "1.0"

CLASSIFICATION_QUESTIONS = [
    ("q_scope", "What is the reach of the change?", "Single", 1, 10,
     [("enterprise", "Enterprise-wide"), ("local", "A single business unit")]),
    ("q_obligation", "Does the change alter a regulatory obligation?", "Single", 1, 20,
     [("yes", "Yes"), ("no", "No")]),
    ("q_control", "Does the change alter a control or an accountability?", "Single", 1, 30,
     [("yes", "Yes"), ("no", "No")]),
]

CLASSIFICATION_RULES = [
    ("R10", 10,
     {"any": [{"question": "q_scope", "equals": "enterprise"},
              {"question": "q_obligation", "equals": "yes"}]},
     "Major",
     "The change is enterprise-wide or alters a regulatory obligation, so it is a major change."),
    ("R20", 20,
     {"all": [{"question": "q_scope", "equals": "local"},
              {"question": "q_obligation", "equals": "no"},
              {"question": "q_control", "equals": "no"}]},
     "Minor",
     "The change is local and alters neither a regulatory obligation nor a control."),
]

#: sla_code, title, target doctype, measure, target hours
SLA_DEFINITIONS = [
    ("POL-INTAKE-MAJOR", "Major intake request turnaround", "Document Intake Request",
     "Total Open Time", 240.0, {"change_classification": "Major"}),
    ("POL-INTAKE-MINOR", "Minor intake request turnaround", "Document Intake Request",
     "Total Open Time", 720.0, {"change_classification": "Minor"}),
]


def _ensure(doctype: str, name: str, values: dict):
    if frappe.db.exists(doctype, name):
        return frappe.get_doc(doctype, name)
    return frappe.get_doc({"doctype": doctype, **values}).insert(ignore_permissions=True)


def seed_state_flags() -> None:
    """Load the Policy flag map. A row an administrator has edited is left alone."""
    for row in STATE_FLAGS:
        doctype, state_field, state_value = row[0], row[1], row[2]
        if not frappe.db.exists("DocType", doctype):
            continue
        if frappe.db.get_value(
            "Workflow State Flag",
            {"target_doctype": doctype, "state_field": state_field, "state_value": state_value},
            "name",
        ):
            continue
        frappe.get_doc(
            {
                "doctype": "Workflow State Flag",
                "target_doctype": doctype,
                "state_field": state_field,
                "state_value": state_value,
                **dict(zip(FLAG_COLUMNS, row[3:], strict=True)),
            }
        ).insert(ignore_permissions=True)
    state_flags.clear_cache()


def seed_lifecycle_workflow() -> None:
    """The lifecycle, as a framework Workflow record.

    Using the framework's own workflow tables rather than inventing a second set
    means the transition rules are enforced by the framework on every save, and
    an administrator edits them in a screen that already exists.
    """
    for state, _docstatus, _role in LIFECYCLE_STATES:
        _ensure("Workflow State", state, {"workflow_state_name": state, "style": ""})
    for _state, action, _next_state, _role, _self in LIFECYCLE_TRANSITIONS:
        _ensure("Workflow Action Master", action, {"workflow_action_name": action})

    if frappe.db.exists("Workflow", WORKFLOW_NAME):
        return

    frappe.get_doc(
        {
            "doctype": "Workflow",
            "workflow_name": WORKFLOW_NAME,
            "document_type": DOCUMENT_DOCTYPE,
            "workflow_state_field": STATE_FIELD,
            "is_active": 1,
            "send_email_alert": 0,
            "states": [
                {"state": state, "doc_status": docstatus, "allow_edit": role}
                for state, docstatus, role in LIFECYCLE_STATES
            ],
            "transitions": [
                {
                    "state": state,
                    "action": action,
                    "next_state": next_state,
                    "allowed": role,
                    "allow_self_approval": self_approval,
                }
                for state, action, next_state, role, self_approval in LIFECYCLE_TRANSITIONS
            ],
        }
    ).insert(ignore_permissions=True)


def seed_lifecycle_gates() -> None:
    for state_value, gate, notes in LIFECYCLE_GATES:
        if frappe.db.exists(
            "Document Lifecycle Gate",
            {
                "target_doctype": DOCUMENT_DOCTYPE,
                "state_field": STATE_FIELD,
                "state_value": state_value,
                "gate": gate,
            },
        ):
            continue
        frappe.get_doc(
            {
                "doctype": "Document Lifecycle Gate",
                "target_doctype": DOCUMENT_DOCTYPE,
                "state_field": STATE_FIELD,
                "state_value": state_value,
                "gate": gate,
                "is_active": 1,
                "notes": notes,
            }
        ).insert(ignore_permissions=True)


def seed_approval_routes() -> None:
    for title, priority, document_type, classification, description, steps in APPROVAL_ROUTES:
        _ensure(
            "Approval Route",
            title,
            {
                "route_title": title,
                "target_doctype": DOCUMENT_DOCTYPE,
                "document_type": document_type,
                "change_classification": classification,
                "priority": priority,
                "is_active": 1,
                "description": description,
                "steps": [
                    {
                        "step_sequence": sequence,
                        "approval_step": label,
                        "required_role": role,
                        "assignee_source": source,
                        "mode": "Sequential",
                        "is_mandatory": 1,
                    }
                    for sequence, label, role, source in steps
                ],
            },
        )


def seed_classification_rule_set() -> str | None:
    """The intake rule set. Questions and rules are data; the version is fixed."""
    existing = frappe.db.get_value(
        "Classification Rule Set",
        {"rule_set_title": RULE_SET_TITLE, "version_label": RULE_SET_VERSION},
        "name",
    )
    if existing:
        return existing

    questions, options = [], []
    for code, text, mode, required, order, choices in CLASSIFICATION_QUESTIONS:
        questions.append(
            {
                "question_code": code,
                "question_text": text,
                "answer_mode": mode,
                "is_required": required,
                "display_order": order,
            }
        )
        for index, (option_code, option_text) in enumerate(choices, start=1):
            options.append(
                {
                    "question_code": code,
                    "option_code": option_code,
                    "option_text": option_text,
                    "display_order": index * 10,
                }
            )

    return frappe.get_doc(
        {
            "doctype": "Classification Rule Set",
            "rule_set_title": RULE_SET_TITLE,
            "applies_to_doctype": "Document Intake Request",
            "version_label": RULE_SET_VERSION,
            # Deliberately not `nowdate()`. Seeded configuration is meant to be in
            # force from the moment it is installed, and "today" does not reliably
            # mean that: the seed and the query that reads it can resolve the date
            # under different timezones — an install a few minutes before midnight
            # UTC seeded tomorrow's date, and the rule set was then never in force,
            # so intake could not be classified at all and the error said only that
            # no rule set applied. A fixed past date says what is meant.
            "effective_from": CONFIGURATION_EPOCH,
            "is_active": 1,
            "default_outcome": "Major",
            "questions": questions,
            "answer_options": options,
            "rules": [
                {
                    "rule_code": code,
                    "priority": priority,
                    "condition": json.dumps(condition),
                    "outcome": outcome,
                    "outcome_rationale": rationale,
                    "is_active": 1,
                }
                for code, priority, condition, outcome, rationale in CLASSIFICATION_RULES
            ],
        }
    ).insert(ignore_permissions=True).name


def seed_service_levels() -> None:
    """E13-S4: classification drives service levels as well as routing."""
    for code, title, doctype, measure, hours, applies_when in SLA_DEFINITIONS:
        _ensure(
            "SLA Definition",
            code,
            {
                "sla_code": code,
                "title": title,
                "target_doctype": doctype,
                "measure": measure,
                "target_hours": hours,
                "warning_threshold_pct": 80,
                "calendar": "24x7",
                "applies_when": json.dumps(applies_when),
                "is_active": 1,
            },
        )


def seed_all() -> None:
    seed_state_flags()
    seed_lifecycle_workflow()
    seed_lifecycle_gates()
    seed_approval_routes()
    seed_classification_rule_set()
    seed_service_levels()

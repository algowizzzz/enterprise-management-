"""Semantic state flags for the Policy module.

This module and the ``Workflow State Flag`` table are the only places a Policy
state name appears. Everything else reads the flags — structural decision M-4.

The contract is the one documented in
``consilium/consilium_core/setup/state_flag_seed.py``: a module that introduces
workflow states ships the matching flag rows, because
``state_flags.apply_state_flags`` refuses a state it has no configuration for.

Columns: DocType, state field, state value, then the flags —
is_editable, is_active, requires_review, is_open, is_committable, requires_statement.

> **Core change requested.** These rows belong in Core's seed table so that
> ``scripts/check_state_flags.py`` — which learns its forbidden vocabulary from
> Core's seed alone — also polices the Policy state names. Until that happens
> the checker does not see them, and the discipline here is held by hand.
"""

FLAG_COLUMNS = (
    "is_editable",
    "is_active",
    "requires_review",
    "is_open",
    "is_committable",
    "requires_statement",
    "is_affirmative",
)

STATE_FLAGS = [
    # Governing Document — the deck's lifecycle. Active means "in force", which
    # begins at publication and survives implementation; editable stops at
    # review sign-off and resumes only on re-entry to drafting.
    ("Governing Document", "lifecycle_phase", "Draft",                 1, 0, 0, 1, 0, 0, 0),
    ("Governing Document", "lifecycle_phase", "Review",                1, 0, 1, 1, 0, 0, 0),
    ("Governing Document", "lifecycle_phase", "Approved",              0, 0, 0, 1, 0, 0, 0),
    ("Governing Document", "lifecycle_phase", "Published",             0, 1, 0, 0, 0, 0, 0),
    ("Governing Document", "lifecycle_phase", "Implemented",           0, 1, 0, 0, 0, 0, 0),
    ("Governing Document", "lifecycle_phase", "Retired",               0, 0, 0, 0, 0, 0, 0),

    # Document Intake Request.
    ("Document Intake Request", "workflow_state", "Requested",         1, 1, 0, 1, 0, 0, 0),
    ("Document Intake Request", "workflow_state", "Classified",        1, 1, 0, 1, 0, 0, 0),
    ("Document Intake Request", "workflow_state", "Triaged",           1, 1, 0, 1, 0, 0, 0),
    ("Document Intake Request", "workflow_state", "Fulfilled",         0, 1, 0, 0, 0, 0, 0),
    ("Document Intake Request", "workflow_state", "Withdrawn",         0, 0, 0, 0, 0, 0, 0),

    # Applicability Exemption — only an authorised exemption suppresses a
    # notification or excuses a scope, and `is_active` is what says so.
    ("Applicability Exemption", "exemption_status", "Requested",       1, 0, 0, 1, 0, 0, 0),
    ("Applicability Exemption", "exemption_status", "Endorsed",        1, 0, 1, 1, 0, 0, 0),
    ("Applicability Exemption", "exemption_status", "Authorised",      0, 1, 0, 0, 0, 0, 0),
    ("Applicability Exemption", "exemption_status", "Refused",         0, 0, 1, 0, 0, 1, 0),
    ("Applicability Exemption", "exemption_status", "Withdrawn",       0, 0, 0, 0, 0, 0, 0),
    ("Applicability Exemption", "exemption_status", "Lapsed",          0, 0, 1, 0, 0, 0, 0),

    # Document Review Cycle.
    ("Document Review Cycle", "cycle_status", "Planned",               1, 1, 0, 1, 0, 0, 0),
    ("Document Review Cycle", "cycle_status", "Underway",              1, 1, 1, 1, 0, 0, 0),
    ("Document Review Cycle", "cycle_status", "Concluded",             0, 0, 0, 0, 0, 0, 0),
    ("Document Review Cycle", "cycle_status", "Abandoned",             0, 0, 0, 0, 0, 0, 0),

    # Policy Violation — open until resolved or dismissed.
    ("Policy Violation", "violation_status", "Logged",                 1, 1, 1, 1, 0, 0, 0),
    ("Policy Violation", "violation_status", "Under Investigation",    1, 1, 1, 1, 0, 0, 0),
    ("Policy Violation", "violation_status", "Remediating",            1, 1, 1, 1, 0, 0, 0),
    ("Policy Violation", "violation_status", "Resolved",               0, 0, 0, 0, 0, 1, 0),
    ("Policy Violation", "violation_status", "Dismissed",              0, 0, 0, 0, 0, 1, 0),

    # Glossary Term — a term is in force only once published.
    ("Glossary Term", "term_status", "Proposed",                       1, 0, 0, 1, 0, 0, 0),
    ("Glossary Term", "term_status", "Published",                      0, 1, 0, 0, 0, 0, 0),
    ("Glossary Term", "term_status", "Deprecated",                     0, 0, 0, 0, 0, 0, 0),

    # Horizon Scan Finding.
    ("Horizon Scan Finding", "finding_status", "Raised",               1, 1, 1, 1, 0, 0, 0),
    ("Horizon Scan Finding", "finding_status", "In Hand",              1, 1, 1, 1, 0, 0, 0),
    ("Horizon Scan Finding", "finding_status", "Concluded",            0, 0, 0, 0, 0, 0, 0),

    # Implementation Plan.
    ("Implementation Plan", "plan_status", "Planned",                  1, 1, 0, 1, 0, 0, 0),
    ("Implementation Plan", "plan_status", "Underway",                 1, 1, 0, 1, 0, 0, 0),
    ("Implementation Plan", "plan_status", "Concluded",                0, 0, 0, 0, 0, 0, 0),
    ("Implementation Plan", "plan_status", "Abandoned",                0, 0, 0, 0, 0, 0, 0),

    # Metadata Remediation Task.
    ("Metadata Remediation Task", "task_status", "Raised",             1, 1, 1, 1, 0, 0, 0),
    ("Metadata Remediation Task", "task_status", "In Hand",            1, 1, 1, 1, 0, 0, 0),
    ("Metadata Remediation Task", "task_status", "Resolved",           0, 0, 0, 0, 0, 0, 0),
    ("Metadata Remediation Task", "task_status", "Dismissed",          0, 0, 0, 0, 0, 0, 0),
]

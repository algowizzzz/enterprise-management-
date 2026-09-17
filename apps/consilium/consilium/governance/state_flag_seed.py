"""Semantic state flags for the Governance module.

Core's ``setup/state_flag_seed.py`` holds the contract: **the seed table and the
``Workflow State Flag`` rows it produces are the only places a state name
appears.** Every other line of code reads the flags.

Core's seed covers Core's own records. This table covers the Governance
module's, in exactly the same shape, and ``setup.ensure_state_flags`` loads it.

> **Core change requested.** ``scripts/check_state_flags.py`` learns the
> vocabulary it forbids from Core's seed module alone, so it does not yet know
> the state names below and cannot catch a Governance state used in a
> conditional. The fix is one import: Core's ``STATE_FLAGS`` should absorb this
> table (or the checker should read both). Until then the rule is kept by
> construction here, not by the checker.

Columns: DocType, state field, state value, then the flags —
is_editable, is_active, requires_review, is_open, is_committable, requires_statement.
"""

from __future__ import annotations

FLAG_COLUMNS = (
    "is_editable",
    "is_active",
    "requires_review",
    "is_open",
    "is_committable",
    "requires_statement",
    "is_affirmative",
)

GOVERNANCE_STATE_FLAGS = [
    # ---------------------------------------------------------------------
    # Governance Forum — the five-state compliance flow (D-3), plus the
    # terminal state a controlled disbandment leaves behind. `is_active` is
    # derived from the state, and a disbanded forum is inactive but not
    # deleted, so the lifecycle needs a state to carry that.
    ("Governance Forum", "compliance_status", "Draft",              1, 1, 1, 1, 0, 0, 0),
    ("Governance Forum", "compliance_status", "Pending",            0, 1, 1, 1, 0, 0, 0),
    ("Governance Forum", "compliance_status", "Compliant",          1, 1, 0, 0, 1, 0, 0),
    ("Governance Forum", "compliance_status", "Non-Compliant",      1, 1, 1, 1, 0, 0, 0),
    ("Governance Forum", "compliance_status", "Not Applicable",     1, 1, 0, 0, 1, 0, 0),
    ("Governance Forum", "compliance_status", "Disbanded",          0, 0, 0, 0, 0, 0, 0),

    # ---------------------------------------------------------------------
    # Committee Formation Request — the nine-state formation flow (D-3).
    # `is_committable` marks the one state from which a forum may be created.
    ("Committee Formation Request", "workflow_state", "Draft",                  1, 1, 0, 1, 0, 0, 0),
    ("Committee Formation Request", "workflow_state", "Submitted",              0, 1, 0, 1, 0, 0, 0),
    ("Committee Formation Request", "workflow_state", "Under Evaluation",       0, 1, 1, 1, 0, 0, 0),
    ("Committee Formation Request", "workflow_state", "Returned To Originator", 1, 1, 1, 1, 0, 1, 0),
    ("Committee Formation Request", "workflow_state", "Pending Approval",       0, 1, 0, 1, 0, 0, 0),
    ("Committee Formation Request", "workflow_state", "Exception Review",       0, 1, 1, 1, 0, 1, 0),
    ("Committee Formation Request", "workflow_state", "Approved",               0, 1, 0, 0, 1, 0, 0),
    ("Committee Formation Request", "workflow_state", "Rejected",               0, 0, 0, 0, 0, 1, 0),
    ("Committee Formation Request", "workflow_state", "Withdrawn",              0, 0, 0, 0, 0, 1, 0),

    # ---------------------------------------------------------------------
    # Forum Compliance Review — the decision label, and what it means.
    # `requires_statement` is what makes a return to the creator impossible
    # without questions.
    ("Forum Compliance Review", "decision", "Compliant",            0, 1, 0, 0, 0, 0, 0),
    ("Forum Compliance Review", "decision", "Non-Compliant",        0, 1, 1, 0, 0, 1, 0),
    ("Forum Compliance Review", "decision", "Not Applicable",       0, 1, 0, 0, 0, 0, 0),
    ("Forum Compliance Review", "decision", "Returned To Creator",  1, 1, 1, 1, 0, 1, 0),

    # ---------------------------------------------------------------------
    # Committee Charter — the risk governance office's effective challenge.
    ("Committee Charter", "rgo_challenge_status", "Not Reviewed",      1, 1, 1, 0, 0, 0, 0),
    ("Committee Charter", "rgo_challenge_status", "Changes Requested", 1, 1, 1, 0, 0, 1, 0),
    ("Committee Charter", "rgo_challenge_status", "Cleared",           0, 1, 0, 0, 0, 0, 0),

    # ---------------------------------------------------------------------
    # Forum Meeting — `is_committable` is true only where the meeting sat,
    # which is when attendance and quorum may be recorded.
    ("Forum Meeting", "status", "Scheduled",                        1, 1, 0, 1, 0, 0, 0),
    ("Forum Meeting", "status", "Held",                             1, 1, 0, 0, 1, 0, 0),
    ("Forum Meeting", "status", "Cancelled",                        0, 0, 0, 0, 0, 0, 0),
    ("Forum Meeting", "status", "Adjourned",                        1, 1, 1, 1, 0, 0, 0),

    # ---------------------------------------------------------------------
    # Forum Motion — the outcome label. `is_editable` false is what freezes a
    # motion's votes and its stored quorum once the outcome is recorded.
    ("Forum Motion", "outcome", "Carried",                          0, 1, 0, 0, 0, 0, 0),
    ("Forum Motion", "outcome", "Not Carried",                      0, 1, 0, 0, 0, 0, 0),
    ("Forum Motion", "outcome", "Deferred",                         1, 1, 1, 1, 0, 0, 0),
    ("Forum Motion", "outcome", "Withdrawn",                        0, 0, 0, 0, 0, 0, 0),
    ("Forum Motion", "outcome", "Inquorate",                        0, 1, 1, 0, 0, 0, 0),
]

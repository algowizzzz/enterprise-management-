"""Seed data for semantic state flags.

**This module and the Workflow State Flag table are the only places a state name
appears.** Everything else reads the flags. ``scripts/check_state_flags.py``
reads this table to learn the vocabulary it then forbids in conditionals.

Columns: DocType, state field, state value, then the flags —
is_editable, is_active, requires_review, is_open, is_committable,
requires_statement, is_affirmative.

``is_affirmative`` exists because an approval and an abstention were otherwise
flag-identical, and an approval chain that counts abstentions as consent will
publish a policy nobody approved. Only a state that expresses positive consent
carries it.
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
    # Attestation Campaign — a campaign generates tasks only while it is open.
    ("Attestation Campaign", "status", "Draft",                     1, 0, 0, 0, 0, 0, 0),
    ("Attestation Campaign", "status", "Open",                      1, 1, 0, 1, 0, 0, 0),
    ("Attestation Campaign", "status", "Closed",                    0, 0, 0, 0, 0, 0, 0),
    ("Attestation Campaign", "status", "Cancelled",                 0, 0, 0, 0, 0, 0, 0),

    # Attestation Task — an open task is one regeneration must not duplicate.
    ("Attestation Task", "status", "Pending",                       1, 1, 0, 1, 0, 0, 0),
    ("Attestation Task", "status", "In Progress",                   1, 1, 0, 1, 0, 0, 0),
    ("Attestation Task", "status", "Attested",                      0, 1, 0, 0, 0, 0, 0),
    ("Attestation Task", "status", "Attested With Exceptions",      0, 1, 1, 0, 0, 1, 0),
    ("Attestation Task", "status", "Declined",                      0, 1, 1, 0, 0, 1, 0),
    ("Attestation Task", "status", "Expired",                       0, 0, 1, 0, 0, 0, 0),

    # Disposition Event — disposal is scheduled, may be held, then approved.
    ("Disposition Event", "status", "Scheduled",                    1, 1, 0, 1, 0, 0, 0),
    ("Disposition Event", "status", "Held",                         1, 1, 1, 1, 0, 0, 0),
    ("Disposition Event", "status", "Approved",                     1, 1, 0, 1, 0, 0, 0),
    ("Disposition Event", "status", "Executed",                     0, 0, 0, 0, 0, 0, 0),
    ("Disposition Event", "status", "Cancelled",                    0, 0, 0, 0, 0, 0, 0),

    # Import Batch — editable until it has been committed.
    ("Import Batch", "status", "Uploaded",                          1, 1, 0, 1, 0, 0, 0),
    ("Import Batch", "status", "Validated",                         1, 1, 0, 1, 0, 0, 0),
    ("Import Batch", "status", "Partially Committed",               0, 1, 1, 0, 0, 0, 0),
    ("Import Batch", "status", "Committed",                         0, 0, 0, 0, 0, 0, 0),
    ("Import Batch", "status", "Rejected",                          0, 0, 1, 0, 0, 0, 0),

    # Import Row — only a row the flags mark committable is written to a target.
    ("Import Row", "status", "Valid",                               1, 1, 0, 1, 1, 0, 0),
    ("Import Row", "status", "Warning",                             1, 1, 1, 1, 1, 0, 0),
    ("Import Row", "status", "Error",                               1, 1, 1, 1, 0, 0, 0),
    ("Import Row", "status", "Committed",                           0, 1, 0, 0, 0, 0, 0),
    ("Import Row", "status", "Skipped",                             0, 0, 0, 0, 0, 0, 0),

    # Notification Dispatch — an open dispatch is one retry may pick up.
    ("Notification Dispatch", "status", "Queued",                   1, 1, 0, 1, 0, 0, 0),
    ("Notification Dispatch", "status", "Sent",                     0, 1, 0, 0, 0, 0, 0),
    ("Notification Dispatch", "status", "Failed",                   1, 1, 1, 1, 0, 0, 0),
    ("Notification Dispatch", "status", "Suppressed",               0, 0, 0, 0, 0, 0, 0),

    # SLA Clock.
    ("SLA Clock", "status", "Running",                              1, 1, 0, 1, 0, 0, 0),
    ("SLA Clock", "status", "Paused",                               1, 1, 0, 1, 0, 0, 0),
    ("SLA Clock", "status", "Met",                                  0, 0, 0, 0, 0, 0, 0),
    ("SLA Clock", "status", "Breached",                             0, 0, 1, 0, 0, 0, 0),
    ("SLA Clock", "status", "Cancelled",                            0, 0, 0, 0, 0, 0, 0),

    # Approval Decision.
    ("Approval Decision", "decision", "Pending",                    1, 1, 0, 1, 0, 0, 0),
    ("Approval Decision", "decision", "Approved",                   0, 1, 0, 0, 0, 0, 1),
    ("Approval Decision", "decision", "Rejected",                   0, 1, 1, 0, 0, 0, 0),
    ("Approval Decision", "decision", "Changes Requested",          1, 1, 1, 1, 0, 0, 0),
    ("Approval Decision", "decision", "Abstained",                  0, 1, 0, 0, 0, 0, 0),
    ("Approval Decision", "decision", "Bypassed",                   0, 1, 1, 0, 0, 0, 0),
]


# --------------------------------------------------------------------------
# Module state vocabularies
#
# Each business module declares the states it introduces, and Core collects
# them here. Two things depend on this being one list rather than three:
#
#   `apply_state_flags` throws on a state it has no mapping for, so a module's
#   states must be seeded or its records cannot be saved at all.
#
#   `scripts/check_state_flags.py` learns the forbidden vocabulary from this
#   file. A state name it does not know about is a state name that can be
#   written into a conditional with nothing to catch it — which is exactly the
#   rule the checker exists to enforce.
#
# Modules are optional by construction: a site that installs only Core still
# works, and a module that is not present simply contributes nothing.
# --------------------------------------------------------------------------

_MODULE_SEEDS = (
    ("consilium.governance.state_flag_seed", "GOVERNANCE_STATE_FLAGS"),
    ("consilium.policy.setup.state_flag_seed", "STATE_FLAGS"),
    ("consilium.escalation.state_flag_seed", "ESCALATION_STATE_FLAGS"),
)


def _collect_module_flags() -> list:
    import importlib

    rows = []
    for module_path, attribute in _MODULE_SEEDS:
        try:
            module = importlib.import_module(module_path)
        except ModuleNotFoundError:
            continue
        rows.extend(getattr(module, attribute, ()))
    return rows


STATE_FLAGS = STATE_FLAGS + _collect_module_flags()

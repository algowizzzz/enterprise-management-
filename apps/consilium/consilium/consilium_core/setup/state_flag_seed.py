"""Seed data for semantic state flags.

**This module and the Workflow State Flag table are the only places a state name
appears.** Everything else reads the flags. ``scripts/check_state_flags.py``
reads this table to learn the vocabulary it then forbids in conditionals.

Columns: DocType, state field, state value, then the flags —
is_editable, is_active, requires_review, is_open, is_committable, requires_statement.
"""

FLAG_COLUMNS = (
    "is_editable",
    "is_active",
    "requires_review",
    "is_open",
    "is_committable",
    "requires_statement",
)

STATE_FLAGS = [
    # Attestation Campaign — a campaign generates tasks only while it is open.
    ("Attestation Campaign", "status", "Draft",                     1, 0, 0, 0, 0, 0),
    ("Attestation Campaign", "status", "Open",                      1, 1, 0, 1, 0, 0),
    ("Attestation Campaign", "status", "Closed",                    0, 0, 0, 0, 0, 0),
    ("Attestation Campaign", "status", "Cancelled",                 0, 0, 0, 0, 0, 0),

    # Attestation Task — an open task is one regeneration must not duplicate.
    ("Attestation Task", "status", "Pending",                       1, 1, 0, 1, 0, 0),
    ("Attestation Task", "status", "In Progress",                   1, 1, 0, 1, 0, 0),
    ("Attestation Task", "status", "Attested",                      0, 1, 0, 0, 0, 0),
    ("Attestation Task", "status", "Attested With Exceptions",      0, 1, 1, 0, 0, 1),
    ("Attestation Task", "status", "Declined",                      0, 1, 1, 0, 0, 1),
    ("Attestation Task", "status", "Expired",                       0, 0, 1, 0, 0, 0),

    # Disposition Event — disposal is scheduled, may be held, then approved.
    ("Disposition Event", "status", "Scheduled",                    1, 1, 0, 1, 0, 0),
    ("Disposition Event", "status", "Held",                         1, 1, 1, 1, 0, 0),
    ("Disposition Event", "status", "Approved",                     1, 1, 0, 1, 0, 0),
    ("Disposition Event", "status", "Executed",                     0, 0, 0, 0, 0, 0),
    ("Disposition Event", "status", "Cancelled",                    0, 0, 0, 0, 0, 0),

    # Import Batch — editable until it has been committed.
    ("Import Batch", "status", "Uploaded",                          1, 1, 0, 1, 0, 0),
    ("Import Batch", "status", "Validated",                         1, 1, 0, 1, 0, 0),
    ("Import Batch", "status", "Partially Committed",               0, 1, 1, 0, 0, 0),
    ("Import Batch", "status", "Committed",                         0, 0, 0, 0, 0, 0),
    ("Import Batch", "status", "Rejected",                          0, 0, 1, 0, 0, 0),

    # Import Row — only a row the flags mark committable is written to a target.
    ("Import Row", "status", "Valid",                               1, 1, 0, 1, 1, 0),
    ("Import Row", "status", "Warning",                             1, 1, 1, 1, 1, 0),
    ("Import Row", "status", "Error",                               1, 1, 1, 1, 0, 0),
    ("Import Row", "status", "Committed",                           0, 1, 0, 0, 0, 0),
    ("Import Row", "status", "Skipped",                             0, 0, 0, 0, 0, 0),

    # Notification Dispatch — an open dispatch is one retry may pick up.
    ("Notification Dispatch", "status", "Queued",                   1, 1, 0, 1, 0, 0),
    ("Notification Dispatch", "status", "Sent",                     0, 1, 0, 0, 0, 0),
    ("Notification Dispatch", "status", "Failed",                   1, 1, 1, 1, 0, 0),
    ("Notification Dispatch", "status", "Suppressed",               0, 0, 0, 0, 0, 0),

    # SLA Clock.
    ("SLA Clock", "status", "Running",                              1, 1, 0, 1, 0, 0),
    ("SLA Clock", "status", "Paused",                               1, 1, 0, 1, 0, 0),
    ("SLA Clock", "status", "Met",                                  0, 0, 0, 0, 0, 0),
    ("SLA Clock", "status", "Breached",                             0, 0, 1, 0, 0, 0),
    ("SLA Clock", "status", "Cancelled",                            0, 0, 0, 0, 0, 0),

    # Approval Decision.
    ("Approval Decision", "decision", "Pending",                    1, 1, 0, 1, 0, 0),
    ("Approval Decision", "decision", "Approved",                   0, 1, 0, 0, 0, 0),
    ("Approval Decision", "decision", "Rejected",                   0, 1, 1, 0, 0, 0),
    ("Approval Decision", "decision", "Changes Requested",          1, 1, 1, 1, 0, 0),
    ("Approval Decision", "decision", "Abstained",                  0, 1, 0, 0, 0, 0),
    ("Approval Decision", "decision", "Bypassed",                   0, 1, 1, 0, 0, 0),
]

"""Semantic state flags for the Escalation module.

**This module is the only place an Escalation state name appears.** Everything
else reads the flags, exactly as `consilium_core/setup/state_flag_seed.py`
requires (structural decision M-4).

These rows belong in Core's seed table: that module documents itself as the one
place state names live, and `scripts/check_state_flags.py` learns its forbidden
vocabulary from it. They are staged here because the Escalation module may not
edit Core. **Core change requested:** append `ESCALATION_STATE_FLAGS` below to
`STATE_FLAGS` in `consilium/consilium_core/setup/state_flag_seed.py`, after
which `consilium.escalation.setup.install.ensure_state_flags` becomes a no-op
and can be dropped.

Columns: DocType, state field, state value, then the flags —
is_editable, is_active, requires_review, is_open, is_committable, requires_statement.

What the flags mean on these records:

* ``is_open`` — the matter or plan is still being worked. A matter whose flag is
  clear is at rest and must carry a recorded outcome.
* ``is_active`` — the record has effect. A withdrawn or expired risk acceptance
  does not.
* ``requires_review`` — the record is awaiting second-line challenge or approval.
* ``is_committable`` — the state commits the record to a system of record
  outside the platform, so it must carry the external reference that identifies
  it there.
* ``requires_statement`` — the state requires a recorded narrative: a closure
  summary, or the rationale behind an approved acceptance.
* ``is_editable`` — the record may still be changed.
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

ESCALATION_STATE_FLAGS = [
    # Escalation Matter — open, in progress, under/pending review, closed.
    # A matter that is not open must carry a closure; one whose state commits it
    # to an external system of record must carry the external reference too.
    ("Escalation Matter", "status", "Open",                          1, 1, 0, 1, 0, 0, 0),
    ("Escalation Matter", "status", "In Progress",                   1, 1, 0, 1, 0, 0, 0),
    ("Escalation Matter", "status", "Under Review",                  1, 1, 1, 1, 0, 0, 0),
    ("Escalation Matter", "status", "Pending Review",                1, 1, 1, 1, 0, 0, 0),
    ("Escalation Matter", "status", "Closed",                        0, 0, 0, 0, 0, 1, 0),
    ("Escalation Matter", "status", "Closed — Tracked Externally",   0, 0, 0, 0, 1, 1, 0),

    # Action Plan.
    ("Action Plan", "status", "Draft",                               1, 0, 0, 1, 0, 0, 0),
    ("Action Plan", "status", "Open",                                1, 1, 0, 1, 0, 0, 0),
    ("Action Plan", "status", "In Progress",                         1, 1, 0, 1, 0, 0, 0),
    ("Action Plan", "status", "Completed",                           0, 1, 0, 0, 0, 0, 0),
    ("Action Plan", "status", "Cancelled",                           0, 0, 0, 0, 0, 0, 0),

    # Risk Acceptance — an accepted risk takes effect only once approved, which
    # is why the approved state is the one that is committable and requires its
    # statement of rationale.
    ("Risk Acceptance", "status", "Draft",                           1, 0, 0, 1, 0, 0, 0),
    ("Risk Acceptance", "status", "Pending Approval",                1, 0, 1, 1, 0, 0, 0),
    ("Risk Acceptance", "status", "Approved",                        0, 1, 0, 0, 1, 1, 0),
    ("Risk Acceptance", "status", "Expired",                         0, 0, 1, 0, 0, 0, 0),
    ("Risk Acceptance", "status", "Withdrawn",                       0, 0, 0, 0, 0, 0, 0),

    # Periodic Submission — E-11's periodic return, including the nil return.
    ("Periodic Submission", "status", "Draft",                       1, 1, 0, 1, 0, 0, 0),
    ("Periodic Submission", "status", "Submitted",                   0, 1, 1, 0, 0, 0, 0),
    ("Periodic Submission", "status", "Accepted",                    0, 1, 0, 0, 0, 0, 0),
]

"""Reading other records' states without naming them.

Sometimes this module needs to know whether *another* record is in a state that
means something — most often, whether an `Approval Decision` is an approval.
Core's `Approval Decision` carries only the `is_open` flag as a column, and
`is_open` is clear for an approval and for a rejection alike, so the obvious
filter cannot tell them apart.

Naming the decision label in a condition is exactly what M-4 forbids. So this
module asks the flag map instead: which values of that field carry the flags
that mean what we are asking about, and then filters on that set of values. The
state names stay in the `Workflow State Flag` table, which is where they live.
"""

from __future__ import annotations

from consilium.consilium_core import state_flags


def values_meaning(doctype: str, state_field: str, **wanted_flags: int) -> list[str]:
    """Every configured value of ``state_field`` whose flags match ``wanted_flags``."""
    by_value = state_flags.get_flag_map(doctype).get(state_field, {})
    return [
        value
        for value, flags in by_value.items()
        if all(int(flags.get(flag, 0)) == int(expected) for flag, expected in wanted_flags.items())
    ]


def approving_decisions() -> list[str]:
    """The decision values that mean the subject was approved.

    An approval is settled (not open), has effect (active) and asks for nothing
    further (no review outstanding). A rejection is settled too, but asks for
    review; a pending decision is still open.
    """
    return values_meaning(
        "Approval Decision", "decision", is_open=0, is_active=1, requires_review=0
    )

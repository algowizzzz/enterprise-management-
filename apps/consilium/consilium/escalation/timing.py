"""Time on an escalation matter: in each status, and under challenge (E-9, E-13).

Both measures are Core's service-level framework, configured rather than coded:

* **Status durations (E-13).** How long the matter has spent in each status,
  rebuilt from its change log by ``consilium_core.state_durations``, each
  stretch judged against the *Time In State* ``SLA Definition`` configured for
  that status (state field ``status``). Which statuses have a target, and how
  long it is, is an administrator's choice; this module names none of them.
* **The second-line challenge (E-9, E33-S7).** A *Time In State* definition on
  the semantic flag ``requires_review`` — the flag that says the second line
  has the matter — times each stretch under review. Scoped with ``Applies
  When`` (``{"systemic": 1}``, say), it is the challenge service level of
  systemic matters. Core starts the clock the moment the matter goes to the
  second line and stops it when the matter is handed back; a review round
  recorded meanwhile is stamped with the clock it was answered against.

A breach of either is Core's to record and warn about; neither raises the
matter's severity, which only its resolution threshold does (see
``resolution.sweep_breaches``).
"""

from __future__ import annotations

import frappe

from consilium.consilium_core import sla, state_durations

MATTER = "Escalation Matter"

#: The field whose values the status durations are measured over.
STATUS_FIELD = "status"

#: The semantic flag that is true while the second line has the matter. A flag,
#: not a status: which statuses set it is the state-flag map's business.
CHALLENGE_FLAG = "requires_review"


def challenge_definitions() -> list[str]:
    """Active definitions that time the matter while the second line has it."""
    return frappe.get_all(
        "SLA Definition",
        filters={"target_doctype": MATTER, "is_active": 1, "measure": sla.MEASURE_TIME_IN_STATE,
                 "state_field": CHALLENGE_FLAG, "state_value": ["in", ["1", "true", "True"]]},
        pluck="name",
    )


def open_challenge_clock(matter_name: str) -> str | None:
    """The challenge clock running on the matter now, if one applies to it."""
    definitions = challenge_definitions()
    if not definitions:
        return None
    clocks = frappe.get_all(
        "SLA Clock",
        filters={"subject_doctype": MATTER, "subject_name": matter_name, "is_open": 1,
                 "sla_definition": ["in", definitions]},
        pluck="name",
        order_by="started_on desc",
        limit=1,
    )
    return clocks[0] if clocks else None


def time_in_state(matter_name: str, as_of=None) -> dict:
    """The page's payload: status durations with their targets, and the clocks."""
    clocks = state_durations.status_driven_clocks(MATTER, matter_name)
    challenge = set(challenge_definitions())
    return {
        "status": state_durations.summary(MATTER, matter_name, STATUS_FIELD, as_of=as_of),
        "clocks": clocks,
        "challenge": [clock for clock in clocks if clock["definition"] in challenge],
    }


@frappe.whitelist(methods=["GET"])
def get_time_in_state(escalation_matter: str) -> dict:
    """Time in each status and under challenge. Anyone who may read the matter.

    The history is read directly, after the permission check on the matter:
    the change log is not readable by every role that may read the matter, and
    how long a matter a person may read sat in each status tells them nothing
    the matter does not.
    """
    from consilium.escalation import resolution

    matter = resolution.load_matter(escalation_matter, "read")
    return time_in_state(matter.name)

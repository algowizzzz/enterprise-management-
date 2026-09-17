# Governance (module CGF)

The committee and governance forum module. It owns the forum inventory that the
policy and escalation modules link to, the intake that creates a forum, the
forum's compliance lifecycle, its membership, and the record of what it decided.

It builds on `Consilium Core` and duplicates none of it: attestation, retention,
versioning, notification, approval decisions, delegation, exception
authorisation and the semantic state-flag map are Core's, used as supplied.

## Where things are

| File | What it holds |
|---|---|
| `state_flag_seed.py` | Every workflow state this module uses, with its semantic flags. **The only place a state name appears.** |
| `setup.py` | The module's configuration: state flags, the watched-field set, the default approval route. All data. |
| `membership.py` | Membership as at a date, the derived officer fields and their reconciliation sweep, quorum. |
| `voting.py` | Opening a motion, casting a vote, recording an outcome. |
| `lifecycle.py` | Compliance reviews, the watched-field trigger, disbandment. |
| `formation.py` | The nine-state intake flow, the configurable approval route, the exception path, forum creation. |
| `reviews.py` | The two annual attestation events, run on Core's engine. |
| `charters.py` | Charters, held in Core's version chain. |
| `inventory.py` | Reading the inventory: search, filter, hierarchy, interconnectivity. |
| `constraints.py` | The indexes and unique constraints PostgreSQL does not get for free. |

## Two state machines, never one

Decision D-3: the formation flow lives on `Committee Formation Request`
(nine states), the compliance flow lives on `Governance Forum` (five, plus a
terminal `Disbanded`). An approved request creates the forum in `Draft`. Neither
record is ever asked what the other's state is.

## Nothing branches on a state name

Every workflow-bearing record carries semantic flags — `is_editable`,
`is_active`, `requires_review`, `is_open`, `is_committable`,
`requires_statement` — set from `Workflow State Flag` rows on every save. All
logic reads those. `scripts/check_state_flags.py` enforces it for Core's
vocabulary; see the note at the top of `state_flag_seed.py` for the one-line
Core change that extends it to this module's.

## Deviations from `02-data-model.md` §6

Recorded here so a reviewer can see them without a diff.

* **`compliance_status` carries a sixth value, `Disbanded`.** `is_active` is
  derived from the state, and a disbanded forum is inactive but not deleted, so
  the lifecycle needs a state to carry that. §6.2 lists five.
* **`compliance_contact` on the forum.** The dual-signed annual review has no
  second signatory without a field naming one.
* **`decision_date` on the motion.** §6.7 gives `opened_on` and `closed_on`;
  neither is the date entitlement is assessed against, which E10-S2 requires.

* **`Formation Approval Route` and its step child.** Not in §6.8. E7-S4 requires
  the approval steps to be configuration, and configuration needs somewhere to
  live.
* **`Formation Child Forum`.** §6.4 gives the request a multi-valued
  `child_forums`; it cannot reuse `Forum Link`, whose rows hang off a forum that
  does not exist yet.
* **Organisational ownership uses Core's `Organization Unit`.** §6.2 names
  `Operating Group`, `Line of Business` and `Business Unit` as three taxonomies;
  Core built one tree with a `unit_level` discriminator, and this module follows
  Core.
* **The watched-field default list omits `risk_types`.** Core compares a watched
  field with `before != after`, and a child table never compares equal, so a
  watched table field would fire on every save.

"""The classification rules engine.

Questions, answer options and the rules that map answers to an outcome are all
data. Rule sets are versioned and locked the first time they classify anything,
and a classified record stores the version label that classified it together with
the full evaluation trace — so a rule change later cannot silently rewrite the
history of a decision taken under the old rules.

A rule's ``condition`` is a structured expression, never free-form code::

    {"all": [{"question": "q_scope", "equals": "enterprise"},
             {"any": [{"question": "q_cost", "greater_than": 100000},
                      {"question": "q_risk", "in": ["high", "severe"]}]}]}

Supported leaf operators: equals, not_equals, in, not_in, includes,
greater_than, less_than, is_set, is_not_set. Supported groups: all, any, none.
"""

from __future__ import annotations

import json

import frappe
from frappe import _
from frappe.utils import now

from consilium.consilium_core import audit


class RuleConditionError(frappe.ValidationError):
    pass


def _loads(value, default=None):
    if not value:
        return default if default is not None else {}
    if isinstance(value, dict | list):
        return value
    return json.loads(value)


# --------------------------------------------------------------------- matching


def _leaf(condition: dict, answers: dict) -> tuple[bool, str]:
    question = condition.get("question")
    if not question:
        raise RuleConditionError(_("A condition leaf must name a question."))
    given = answers.get(question)

    if "is_set" in condition:
        result = bool(given) == bool(condition["is_set"])
        return result, f"{question} is_set={bool(given)}"
    if "is_not_set" in condition:
        result = (not given) == bool(condition["is_not_set"])
        return result, f"{question} is_not_set={not given}"
    if "equals" in condition:
        return given == condition["equals"], f"{question}={given!r} equals {condition['equals']!r}"
    if "not_equals" in condition:
        return given != condition["not_equals"], f"{question}={given!r} not_equals {condition['not_equals']!r}"
    if "in" in condition:
        return given in condition["in"], f"{question}={given!r} in {condition['in']!r}"
    if "not_in" in condition:
        return given not in condition["not_in"], f"{question}={given!r} not_in {condition['not_in']!r}"
    if "includes" in condition:
        values = given if isinstance(given, list | tuple) else [given]
        return condition["includes"] in values, f"{question}={given!r} includes {condition['includes']!r}"
    if "greater_than" in condition:
        try:
            return float(given) > float(condition["greater_than"]), f"{question}={given!r} > {condition['greater_than']!r}"
        except (TypeError, ValueError):
            return False, f"{question}={given!r} is not numeric"
    if "less_than" in condition:
        try:
            return float(given) < float(condition["less_than"]), f"{question}={given!r} < {condition['less_than']!r}"
        except (TypeError, ValueError):
            return False, f"{question}={given!r} is not numeric"

    raise RuleConditionError(_("Condition {0} uses no known operator.").format(json.dumps(condition)))


def matches(condition, answers: dict) -> tuple[bool, list[str]]:
    """Evaluate a condition tree. Returns the result and a human-readable trace."""
    condition = _loads(condition)
    if not condition:
        return True, ["empty condition matches everything"]

    if "all" in condition:
        notes, result = [], True
        for child in condition["all"]:
            child_result, child_notes = matches(child, answers)
            notes.extend(child_notes)
            result = result and child_result
        return result, [f"all({'; '.join(notes)})"]
    if "any" in condition:
        notes, result = [], False
        for child in condition["any"]:
            child_result, child_notes = matches(child, answers)
            notes.extend(child_notes)
            result = result or child_result
        return result, [f"any({'; '.join(notes)})"]
    if "none" in condition:
        notes, result = [], True
        for child in condition["none"]:
            child_result, child_notes = matches(child, answers)
            notes.extend(child_notes)
            result = result and not child_result
        return result, [f"none({'; '.join(notes)})"]

    result, note = _leaf(condition, answers)
    return result, [note]


# ------------------------------------------------------------------ evaluation


def _validate_answers(rule_set, answers: dict) -> None:
    codes = {q.question_code for q in rule_set.questions}
    unknown = set(answers) - codes
    if unknown:
        frappe.throw(
            _("Rule set {0} has no question(s) {1}.").format(rule_set.name, ", ".join(sorted(unknown))),
            title=_("Unknown Question"),
        )

    options: dict[str, set[str]] = {}
    for option in rule_set.answer_options:
        options.setdefault(option.question_code, set()).add(option.option_code)

    for question in rule_set.questions:
        given = answers.get(question.question_code)
        if question.is_required and given in (None, "", []):
            if question.depends_on_question and answers.get(question.depends_on_question) != question.depends_on_answer:
                continue
            frappe.throw(
                _("Question {0} is required by rule set {1}.").format(question.question_code, rule_set.name),
                title=_("Answer Required"),
            )
        if given in (None, "", []):
            continue
        allowed = options.get(question.question_code)
        if allowed and question.answer_mode in ("Single", "Multiple"):
            values = given if isinstance(given, list | tuple) else [given]
            invalid = [v for v in values if v not in allowed]
            if invalid:
                frappe.throw(
                    _("{0} is not an answer option for question {1}.").format(
                        ", ".join(str(v) for v in invalid), question.question_code
                    ),
                    title=_("Invalid Answer"),
                )


def classify(
    rule_set: str,
    answers: dict,
    *,
    subject_doctype: str,
    subject_name: str,
    user: str | None = None,
):
    """Evaluate a rule set and write the immutable ``Classification Assessment``."""
    rule_set_doc = frappe.get_doc("Classification Rule Set", rule_set)
    if not rule_set_doc.is_active:
        frappe.throw(_("Rule set {0} is not active.").format(rule_set))

    _validate_answers(rule_set_doc, answers)

    trace, outcome, rationale, matched_code = [], None, None, None
    rules = sorted(
        [r for r in rule_set_doc.rules if r.is_active], key=lambda r: (int(r.priority or 0), r.idx)
    )
    for rule in rules:
        if matched_code:
            trace.append(
                {"rule_code": rule.rule_code, "priority": rule.priority, "matched": False,
                 "reason": "not evaluated: an earlier rule matched first"}
            )
            continue
        result, notes = matches(rule.condition, answers)
        trace.append(
            {"rule_code": rule.rule_code, "priority": rule.priority, "matched": bool(result),
             "reason": "; ".join(notes)}
        )
        if result:
            matched_code = rule.rule_code
            outcome = rule.outcome
            rationale = rule.outcome_rationale

    if not matched_code:
        outcome = rule_set_doc.default_outcome
        rationale = _("No rule matched; the rule set's default outcome applied.")

    assessment = frappe.get_doc(
        {
            "doctype": "Classification Assessment",
            "subject_doctype": subject_doctype,
            "subject_name": subject_name,
            "rule_set": rule_set_doc.name,
            "rule_set_version_label": rule_set_doc.version_label,
            "matched_rule_code": matched_code,
            "outcome": outcome,
            "outcome_rationale": rationale,
            "evaluation_trace": json.dumps(
                {"answers": answers, "rules": trace, "default_outcome": rule_set_doc.default_outcome},
                default=str,
            ),
            "evaluated_on": now(),
            "evaluated_by": user or frappe.session.user,
            "answers": [
                {
                    "question_code": code,
                    "answer_code": value if isinstance(value, str) else None,
                    "answer_text": json.dumps(value) if not isinstance(value, str) else value,
                    "numeric_value": float(value) if isinstance(value, int | float) else None,
                }
                for code, value in answers.items()
            ],
        }
    ).insert(ignore_permissions=True)

    if not rule_set_doc.is_sealed:
        # A rule set that has classified something is frozen: a change is a new
        # version, so a past decision stays explicable against the rules that
        # produced it.
        frappe.db.set_value("Classification Rule Set", rule_set_doc.name, "is_sealed", 1)

    return assessment


def override(assessment: str, outcome: str, justification: str, approved_by: str | None = None):
    """Override an outcome. The original outcome, rule and trace are untouched."""
    doc = frappe.get_doc("Classification Assessment", assessment)
    if not (justification or "").strip():
        audit.refuse(
            f"Override of classification assessment {assessment} is refused: an override carries a "
            "mandatory justification.",
            subject_doctype=doc.subject_doctype,
            subject_name=doc.subject_name,
            attempted_action="Other",
            control="classification override",
            exc=frappe.ValidationError,
        )
    doc.flags.consilium_override = True
    doc.overridden = 1
    doc.override_outcome = outcome
    doc.override_justification = justification
    doc.override_approved_by = approved_by or frappe.session.user
    doc.save(ignore_permissions=True)
    return doc


def effective_outcome(assessment: str) -> str:
    doc = frappe.get_doc("Classification Assessment", assessment)
    return doc.override_outcome if doc.overridden else doc.outcome

"""Classification Rule Set — controller.

A rule set that has classified something is locked. Changing the rules of a past
decision is exactly what the version label exists to prevent, so an edit to a
locked set is refused and audited; the way forward is a new version.
"""

import json

import frappe
from frappe import _
from frappe.model.document import Document

from consilium.consilium_core import audit, classification

SEAL_EXEMPT_FIELDS = ("is_active", "effective_to", "is_sealed")


class ClassificationRuleSet(Document):
    def validate(self):
        self._refuse_edit_when_sealed()
        self._validate_questions()
        self._validate_rules()

    def _refuse_edit_when_sealed(self):
        if self.is_new():
            return
        before = self.get_doc_before_save()
        if not before or not before.is_sealed:
            return
        changed = [
            field
            for field in self.meta.get_valid_columns()
            if field not in SEAL_EXEMPT_FIELDS
            and field not in ("modified", "modified_by")
            and before.get(field) != self.get(field)
        ]
        children_changed = json.dumps(
            [[row.as_dict(no_default_fields=True) for row in before.get(table)] for table in ("questions", "answer_options", "rules")],
            default=str, sort_keys=True,
        ) != json.dumps(
            [[row.as_dict(no_default_fields=True) for row in self.get(table)] for table in ("questions", "answer_options", "rules")],
            default=str, sort_keys=True,
        )
        if changed or children_changed:
            audit.refuse(
                f"Rule set {self.name} has already classified records and is sealed. "
                "Publish a new version instead: a past classification must stay explicable "
                "against the rules that produced it.",
                subject_doctype=self.doctype,
                subject_name=self.name,
                attempted_action="Modify",
                control="rule set lock",
                context={"fields": changed, "children_changed": children_changed},
            )

    def _validate_questions(self):
        codes = set()
        for question in self.questions:
            if question.question_code in codes:
                frappe.throw(_("Question code {0} appears twice.").format(question.question_code))
            codes.add(question.question_code)
        for option in self.answer_options:
            if option.question_code not in codes:
                frappe.throw(
                    _("Answer option {0} refers to question {1}, which this rule set does not ask.").format(
                        option.option_code, option.question_code
                    )
                )

    def _validate_rules(self):
        rule_codes = set()
        for rule in self.rules:
            if rule.rule_code in rule_codes:
                frappe.throw(_("Rule code {0} appears twice.").format(rule.rule_code))
            rule_codes.add(rule.rule_code)
            try:
                condition = json.loads(rule.condition) if isinstance(rule.condition, str) else rule.condition
            except ValueError as exc:
                frappe.throw(_("Rule {0} has an unreadable condition: {1}").format(rule.rule_code, exc))
            try:
                classification.matches(condition, {})
            except classification.RuleConditionError as exc:
                frappe.throw(_("Rule {0} is not a valid condition: {1}").format(rule.rule_code, exc))

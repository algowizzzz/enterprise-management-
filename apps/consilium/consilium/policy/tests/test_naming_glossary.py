"""Naming conventions (P-15, P-16) and glossary enforcement (P-24).

Each rule is tested on its failure path first: the refusal, and the refusal
record it leaves in the Governance Refusal Log.
"""

from __future__ import annotations

import frappe

from consilium.policy import glossary, intake, naming
from consilium.policy.tests.utils import (
    DOCTYPE,
    PolicyTestCase,
    as_user,
    make_document,
    make_document_type,
    make_user,
    refusals_for,
    unique,
)

REQUEST = "Document Intake Request"
MINOR_ANSWERS = {"q_scope": "local", "q_obligation": "no", "q_control": "no"}


def make_template(document_type: str, pattern: str, *, action: str = "New", is_active: int = 1) -> str:
    return frappe.get_doc({
        "doctype": "Document Template",
        "template_title": unique("Template"),
        "document_type": document_type,
        "action": action,
        "naming_convention_pattern": pattern,
        "is_active": is_active,
    }).insert(ignore_permissions=True).name


def unsaved_document(document_type: str, document_name: str):
    """A document object whose ``insert`` the test attempts, so its name is known."""
    from consilium.policy.tests.utils import make_org_unit, make_risk_category

    return frappe.get_doc({
        "doctype": DOCTYPE,
        "document_name": document_name,
        "document_type": document_type,
        "document_owner": make_user("Policy Owner"),
        "document_approver": make_user("Policy Owner"),
        "owning_operating_group": make_org_unit(),
        "primary_risk_category": make_risk_category(),
        "handling_classification": "Internal",
    })


def make_term(term: str, *, synonyms=(), enforce: int = 1, publish: bool = True, **values) -> str:
    doc = frappe.get_doc({
        "doctype": "Glossary Term",
        "term": term,
        "definition": f"The meaning of {term}.",
        "scope_level": values.pop("scope_level", "Enterprise"),
        "enforce_usage": enforce,
        "synonyms": [{"synonym": value} for value in synonyms],
        **values,
    }).insert(ignore_permissions=True)
    if publish:
        glossary.publish(doc.name, change_summary="Agreed.")
    return doc.name


class TestNamingPattern(PolicyTestCase):
    def test_placeholders_and_literals(self):
        regex = naming.pattern_regex("&lt;Subject&gt; Policy")  # as the framework stores it
        self.assertTrue(regex.match("Anti-Money Laundering Policy"))
        self.assertFalse(regex.match("Code of Conduct"))
        self.assertFalse(regex.match("Policy"))
        self.assertFalse(regex.match("Anti-Money Laundering Policy v2"))
        self.assertFalse(regex.match("Anti-Money Laundering policy"))

        review = naming.pattern_regex("<Subject> Policy — review <year>")
        self.assertTrue(review.match("Conduct Policy — review 2026"))
        self.assertFalse(review.match("Conduct Policy — review next year"))

        coded = naming.pattern_regex("POL-{unit}-{sequence}")
        self.assertTrue(coded.match("POL-RISK-0042"))
        self.assertFalse(coded.match("POL-RISK-forty"))


class TestNamingEnforcement(PolicyTestCase):
    def test_a_new_document_with_a_nonconforming_name_is_refused_and_logged(self):
        document_type = make_document_type()
        make_template(document_type, "<Subject> Standard")
        doc = unsaved_document(document_type, unique("Vendor Exit Guide"))
        with self.assertRaises(frappe.ValidationError) as caught:
            doc.insert(ignore_permissions=True)
        self.purge_on_teardown(DOCTYPE, doc.name)
        self.assertIn("<Subject> Standard", str(caught.exception))
        self.assertTrue(any(row["control"] == "naming convention" for row in refusals_for(DOCTYPE, doc.name)))

    def test_a_conforming_name_is_accepted(self):
        document_type = make_document_type()
        make_template(document_type, "<Subject> Standard")
        doc = unsaved_document(document_type, f"{unique('Vendor Exit')} Standard").insert(ignore_permissions=True)
        self.assertTrue(frappe.db.exists(DOCTYPE, doc.name))

    def test_only_an_active_new_template_names_a_document(self):
        document_type = make_document_type()
        make_template(document_type, "<Subject> Standard", action="Review")
        make_template(document_type, "<Subject> Standard", is_active=0)
        doc = unsaved_document(document_type, unique("Anything goes")).insert(ignore_permissions=True)
        self.assertTrue(frappe.db.exists(DOCTYPE, doc.name))

    def test_a_legacy_name_survives_an_unrelated_edit_but_not_a_rename(self):
        document_type = make_document_type()
        doc = make_document(document_type=document_type, document_name=unique("Code of Conduct"))
        make_template(document_type, "<Subject> Policy")

        doc.reload()
        doc.document_abstract = "An unrelated edit."
        doc.save(ignore_permissions=True)

        self.purge_on_teardown(DOCTYPE, doc.name)
        doc.reload()
        doc.document_name = unique("Conduct Code")
        with self.assertRaises(frappe.ValidationError):
            doc.save(ignore_permissions=True)
        doc.reload()
        doc.document_name = f"{unique('Conduct')} Policy"
        doc.save(ignore_permissions=True)

    def test_intake_refuses_a_nonconforming_proposed_name_when_classified(self):
        document_type = make_document_type()
        make_template(document_type, "<Subject> Policy")
        request = frappe.get_doc({
            "doctype": REQUEST,
            "request_type": "Create",
            "requester": make_user("Policy Owner"),
            "business_justification": "A new obligation.",
            "proposed_document_type": document_type,
            "proposed_document_name": unique("Conduct rules"),
        }).insert(ignore_permissions=True)
        self.purge_on_teardown(REQUEST, request.name)
        with self.assertRaises(frappe.ValidationError):
            intake.classify(request.name, MINOR_ANSWERS)
        with self.assertRaises(frappe.ValidationError):
            intake.create_document(request.name)
        controls = [row["control"] for row in refusals_for(REQUEST, request.name)]
        self.assertEqual(controls.count("naming convention"), 2)
        self.assertFalse(frappe.db.get_value(REQUEST, request.name, "created_document"))

    def test_a_conforming_proposed_name_passes_intake(self):
        document_type = make_document_type()
        make_template(document_type, "<Subject> Policy")
        request = frappe.get_doc({
            "doctype": REQUEST,
            "request_type": "Create",
            "requester": make_user("Policy Owner"),
            "business_justification": "A new obligation.",
            "proposed_document_type": document_type,
            "proposed_document_name": f"{unique('Conduct')} Policy",
        }).insert(ignore_permissions=True)
        naming.check_intake(request.name)  # does not raise

    def test_the_form_check_reports_the_pattern(self):
        document_type = make_document_type()
        make_template(document_type, "<Subject> Policy")
        self.assertEqual(naming.validate_name("Conduct Policy", document_type),
                         {"valid": True, "patterns": ["<Subject> Policy"]})
        self.assertFalse(naming.validate_name("Conduct rules", document_type)["valid"])
        with as_user("Guest"), self.assertRaises(frappe.PermissionError):
            naming.validate_name("Conduct rules", document_type)


class TestGlossaryEnforcement(PolicyTestCase):
    def test_a_synonym_used_instead_of_an_enforced_term_is_refused_and_logged(self):
        official = unique("Critical Operation")
        synonym = unique("Key Service")
        make_term(official, synonyms=[synonym])
        doc = make_document()
        self.purge_on_teardown(DOCTYPE, doc.name)
        doc.document_abstract = f"Every {synonym} must have a tested recovery plan."
        with self.assertRaises(frappe.ValidationError) as caught:
            doc.save(ignore_permissions=True)
        self.assertIn(official, str(caught.exception))
        self.assertTrue(any(row["control"] == "glossary enforcement" for row in refusals_for(DOCTYPE, doc.name)))

    def test_a_new_document_is_checked_too(self):
        official = unique("Critical Operation")
        synonym = unique("Key Service")
        make_term(official, synonyms=[synonym])
        doc = unsaved_document(make_document_type(), unique("Resilience"))
        doc.document_abstract = f"Covers each {synonym.lower()}."  # matching ignores case
        with self.assertRaises(frappe.ValidationError):
            doc.insert(ignore_permissions=True)
        self.purge_on_teardown(DOCTYPE, doc.name)

    def test_a_synonym_alongside_the_official_term_is_accepted(self):
        official = unique("Politically Exposed Person")
        make_term(official, synonyms=["PEPX"])
        doc = make_document()
        doc.document_abstract = f"A {official} (PEPX) needs enhanced due diligence; every PEPX is reviewed yearly."
        doc.save(ignore_permissions=True)

    def test_an_unenforced_or_unpublished_term_does_not_refuse(self):
        loose = unique("Risk Tolerance")
        proposed = unique("Operational Resilience")
        make_term(loose, synonyms=["tolerance band"], enforce=0)
        make_term(proposed, synonyms=["resilience posture"], publish=False)
        doc = make_document()
        doc.document_abstract = "Our tolerance band and resilience posture are reviewed yearly."
        doc.save(ignore_permissions=True)

    def test_retired_wording_superseded_by_an_enforced_term_is_refused(self):
        official = unique("Material Third-Party Arrangement")
        retired = unique("Material Outsourcing")
        new_name = make_term(official)
        old_name = make_term(retired, publish=False)
        frappe.db.set_value("Glossary Term", old_name, {"superseded_by": new_name, "is_active": 0})
        doc = make_document()
        self.purge_on_teardown(DOCTYPE, doc.name)
        doc.document_abstract = f"Each {retired} is approved by the committee."
        with self.assertRaises(frappe.ValidationError):
            doc.save(ignore_permissions=True)

    def test_a_document_scoped_term_applies_to_its_document_only(self):
        official = unique("Emergency Change")
        synonym = unique("urgent fix")
        scoped_to = make_document()
        other = make_document()
        make_term(official, synonyms=[synonym], scope_level="Document", scope_document=scoped_to.name)

        other.document_abstract = f"An {synonym} follows the standard route."
        other.save(ignore_permissions=True)

        self.purge_on_teardown(DOCTYPE, scoped_to.name)
        scoped_to.reload()
        scoped_to.document_abstract = f"An {synonym} follows the standard route."
        with self.assertRaises(frappe.ValidationError):
            scoped_to.save(ignore_permissions=True)

    def test_text_that_did_not_change_is_not_rechecked(self):
        doc = make_document()
        synonym = unique("Key Service")
        frappe.db.set_value(DOCTYPE, doc.name, "document_abstract", f"Legacy text naming a {synonym}.")
        make_term(unique("Critical Operation"), synonyms=[synonym])
        doc.reload()
        doc.review_frequency_months = 12
        doc.save(ignore_permissions=True)

    def test_in_context_counts_use_and_reports_findings(self):
        official = unique("Key Risk Indicator")
        synonym = unique("KRIX")
        make_term(official, synonyms=[synonym])
        unused = unique("Effective Challenge")
        make_term(unused, enforce=0)
        doc = make_document()
        frappe.db.set_value(DOCTYPE, doc.name, "body_text",
                            f"<p>Each {official} has a threshold. A {official} breach is escalated.</p>")
        result = glossary.in_context(doc.name)
        by_term = {row["term"]: row for row in result["terms"]}
        self.assertEqual(by_term[official]["occurrences"], 2)
        self.assertTrue(by_term[official]["used"])
        self.assertFalse(by_term[unused]["used"])
        # Used terms come first. Asserted as an ordering rather than "official is
        # first": a site's own enterprise terms (a shorter term inside this one,
        # say) may be used by the same text and sort ahead of it.
        used_flags = [row["used"] for row in result["terms"]]
        self.assertEqual(used_flags, sorted(used_flags, reverse=True))
        self.assertEqual(result["findings"], [])

        frappe.db.set_value(DOCTYPE, doc.name, "body_text", f"<p>Each {synonym} has a threshold.</p>")
        findings = glossary.in_context(doc.name)["findings"]
        self.assertEqual([(item["found"], item["use"]) for item in findings], [(synonym, official)])

    def test_in_context_is_refused_to_someone_who_cannot_read_the_document(self):
        doc = make_document(handling_classification="Restricted")
        with as_user(make_user("Policy Owner")), self.assertRaises(frappe.PermissionError):
            glossary.in_context(doc.name)

"""Import batch review from the portal (CS-11): the gate over Core's pipeline.

The pipeline itself is tested in `test_import_pipeline`. These tests are about
the screen's way in: who may upload, look, commit and discard; that a reviewer's
decisions (leave a row out, discard the batch) hold; and that nothing is written
to a target record except by a commit the reviewer could have made by hand.

Each test brings its own external system and profile, so no filter here can
match a record the site already holds.
"""

import os
from unittest import mock

import frappe

from consilium.consilium_core import importing
from consilium.consilium_core.tests.portal_personas import PersonaPool
from consilium.consilium_core.tests.utils import CoreTestCase, unique



#: Committed people shared by the classes below, removed when the module ends.
PEOPLE = PersonaPool()


def tearDownModule():
    PEOPLE.remove()

class ImportPortalCase(CoreTestCase):
    #: Made once per class and committed (see portal_personas).
    PERSONAS = {
        # Import rights and the right to create what the batch writes.
        "reviewer": ("Consilium Administrator", "Taxonomy Administrator"),
        # Import rights, but not the right to create risk types.
        "administrator": ("Consilium Administrator",),
        "auditor": ("Consilium Audit",),
        "taxonomist": ("Taxonomy Administrator",),
        "stranger": (),
    }

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        PEOPLE.attach(cls, cls.PERSONAS)

    def setUp(self):
        self.system = frappe.get_doc(
            {"doctype": "External System", "system_code": unique("SYS"), "title": "Upstream register"}
        ).insert(ignore_permissions=True)
        self.profile = self.make_profile()

    def tearDown(self):
        frappe.set_user("Administrator")
        # The uploaded files are written to disk, which a rollback does not undo.
        for url in getattr(self, "_uploaded", []):
            path = frappe.get_site_path(url.lstrip("/"))
            if os.path.exists(path):
                os.remove(path)
        super().tearDown()

    def make_profile(self, **overrides):
        values = {
            "doctype": "Import Profile",
            "profile_title": unique("profile"),
            "source_system": self.system.name,
            "target_doctype": "Risk Type",
            "key_strategy": "External Key",
            "external_key_column": "id",
            "on_missing_required": "Reject Row",
            "on_unknown_taxonomy": "Reject Row",
            "on_duplicate_key": "Update",
            "is_active": 1,
            "mappings": [
                {"source_column": "code", "target_fieldname": "risk_type_code", "transform": "Trim", "is_required": 1},
                {"source_column": "name", "target_fieldname": "risk_type_name", "transform": "Trim", "is_required": 1},
                {"source_column": "tier", "target_fieldname": "tier", "transform": "None", "is_required": 1},
            ],
        }
        values.update(overrides)
        return frappe.get_doc(values).insert(ignore_permissions=True)

    def csv(self, *, good=2, bad=1) -> str:
        lines = ["id,code,name,tier"]
        for index in range(good):
            lines.append(f"{unique('X')},{unique('RT').upper()},Imported risk {index},1")
        for _index in range(bad):
            lines.append(f"{unique('X')},{unique('RT').upper()},,1")  # no name: required
        return "\n".join(lines) + "\n"

    def upload(self, user=None, content=None, profile=None, **kwargs):
        frappe.set_user(user or self.reviewer)
        context = importing.upload_batch(
            (profile or self.profile).name, kwargs.pop("file_name", "register.csv"),
            content if content is not None else self.csv(), **kwargs
        )
        self._uploaded = [*getattr(self, "_uploaded", []), context["batch"]["source_file"]]
        return context


class TestUpload(ImportPortalCase):
    def test_an_upload_is_kept_hashed_and_validated_without_writing_anything(self):
        content = self.csv(good=2, bad=1)
        context = self.upload(content=content, batch_reference="REF-1")
        batch = context["batch"]
        self.assertEqual((batch["row_count"], batch["valid_count"], batch["error_count"]), (3, 2, 1))
        self.assertEqual(batch["batch_reference"], "REF-1")
        self.assertEqual(batch["imported_by"], self.reviewer)
        self.assertEqual(batch["source_file_sha256"], importing.sha256_of(content))

        stored = frappe.get_doc("File", {"file_url": batch["source_file"]})
        self.assertTrue(stored.is_private)
        self.assertEqual((stored.attached_to_doctype, stored.attached_to_name), ("Import Batch", batch["name"]))
        self.assertEqual(frappe.db.count("Import Row", {"import_batch": batch["name"]}), 3)
        self.assertFalse(frappe.db.exists("Import Row", {"import_batch": batch["name"], "target_name": ["is", "set"]}))
        self.assertEqual(context["committable"], 2)
        self.assertTrue(context["actions"]["commit"])

    def test_only_those_who_may_create_a_batch_may_upload(self):
        for user in (self.auditor, self.taxonomist, self.stranger):
            with self.assertRaises(frappe.PermissionError):
                self.upload(user=user)
            frappe.set_user("Administrator")
        with self.assertRaises(frappe.PermissionError):
            frappe.set_user(self.stranger)
            importing.import_profiles()

    def test_bad_files_are_refused(self):
        with self.assertRaises(frappe.ValidationError):
            self.upload(content="   ")
        with self.assertRaises(frappe.ValidationError):
            self.upload(file_name="register.xlsx")
        with self.assertRaises(frappe.ValidationError):
            self.upload(content="x" * (importing.MAX_UPLOAD_BYTES + 1))
        frappe.set_user("Administrator")
        inactive = self.make_profile(is_active=0)
        with self.assertRaises(frappe.ValidationError):
            self.upload(profile=inactive)

    def test_a_batch_level_rejection_keeps_the_batch_and_its_reason(self):
        strict = self.make_profile(on_missing_required="Reject Batch")
        context = self.upload(profile=strict, content=self.csv(good=1, bad=1))
        batch = frappe.get_doc("Import Batch", context["batch"]["name"])
        self.assertFalse(batch.is_editable)
        self.assertIn("rejected", context["batch"]["validation_report"])
        self.assertFalse(context["actions"]["commit"])

    def test_the_profiles_list_says_which_columns_a_file_needs(self):
        frappe.set_user(self.reviewer)
        listed = {p["name"]: p for p in importing.import_profiles()}
        columns = [c["column"] for c in listed[self.profile.name]["columns"]]
        self.assertEqual(columns, ["id", "code", "name", "tier"])
        self.assertTrue(listed[self.profile.name]["may_create_target"])


class TestReview(ImportPortalCase):
    def test_review_is_read_with_the_batch_permission(self):
        name = self.upload()["batch"]["name"]
        frappe.set_user(self.auditor)
        context = importing.get_batch_review(name)
        self.assertEqual(len(context["rows"]), 3)
        self.assertFalse(any(context["actions"].values()), "audit may look, not act")
        error_row = next(r for r in context["rows"] if not r["is_committable"])
        self.assertIn("risk_type_name: required value missing", error_row["messages"])
        self.assertIn("name", error_row["raw_payload"])

        for user in (self.stranger, self.taxonomist):
            frappe.set_user(user)
            with self.assertRaises(frappe.PermissionError):
                importing.get_batch_review(name)

    def test_a_row_left_out_is_not_committed_and_the_rest_are(self):
        name = self.upload(content=self.csv(good=3, bad=1))["batch"]["name"]
        rows = importing.get_batch_review(name)["rows"]
        left_out = next(r for r in rows if r["is_committable"])
        context = importing.exclude_row(left_out["name"], reason="Duplicate of an existing record")
        self.assertEqual(context["committable"], 2)
        row = frappe.get_doc("Import Row", left_out["name"])
        self.assertFalse(row.is_committable)
        self.assertTrue(any("Duplicate of an existing record" in m for m in frappe.parse_json(row.messages)))

        outcome = importing.commit_reviewed_batch(name)["outcome"]
        self.assertEqual(outcome["committed"], 2)
        self.assertFalse(frappe.db.get_value("Import Row", left_out["name"], "target_name"))
        committed = frappe.get_all("Import Row", filters={"import_batch": name, "target_name": ["is", "set"]},
                                   pluck="target_name")
        self.assertEqual(len(committed), 2)
        for risk_type in committed:
            self.assertTrue(frappe.db.exists("Risk Type", risk_type))

        batch = frappe.get_doc("Import Batch", name)
        self.assertFalse(batch.is_editable)
        with self.assertRaises(frappe.ValidationError):
            importing.commit_reviewed_batch(name)
        with self.assertRaises(frappe.ValidationError):
            importing.discard_batch(name, "too late")

    def test_validating_again_restores_a_row_left_out(self):
        name = self.upload()["batch"]["name"]
        row = next(r for r in importing.get_batch_review(name)["rows"] if r["is_committable"])
        importing.exclude_row(row["name"])
        context = importing.revalidate_batch(name)
        self.assertEqual(context["committable"], 2)

    def test_commit_needs_the_right_to_create_what_the_batch_writes(self):
        name = self.upload()["batch"]["name"]
        frappe.set_user(self.administrator)
        self.assertFalse(importing.get_batch_review(name)["actions"]["commit"])
        with self.assertRaises(frappe.PermissionError):
            importing.commit_reviewed_batch(name)
        frappe.set_user("Administrator")
        self.assertFalse(frappe.db.exists("Import Row", {"import_batch": name, "target_name": ["is", "set"]}))

    def test_those_who_may_only_read_cannot_act(self):
        name = self.upload()["batch"]["name"]
        row = importing.get_batch_review(name)["rows"][0]["name"]
        frappe.set_user(self.auditor)
        for call in (
            lambda: importing.commit_reviewed_batch(name),
            lambda: importing.discard_batch(name, "no"),
            lambda: importing.revalidate_batch(name),
            lambda: importing.exclude_row(row),
        ):
            with self.assertRaises(frappe.PermissionError):
                call()

    def test_a_batch_with_nothing_committable_is_not_committed(self):
        name = self.upload(content=self.csv(good=1, bad=2))["batch"]["name"]
        row = next(r for r in importing.get_batch_review(name)["rows"] if r["is_committable"])
        importing.exclude_row(row["name"])
        with self.assertRaises(frappe.ValidationError):
            importing.commit_reviewed_batch(name)

    def test_a_module_preparer_runs_before_the_commit(self):
        name = self.upload()["batch"]["name"]
        seen = []
        with mock.patch.object(importing, "_preparers", return_value=[lambda batch: seen.append(batch.name)]):
            importing.commit_reviewed_batch(name)
        self.assertEqual(seen, [name])


class TestDiscard(ImportPortalCase):
    def test_a_discarded_batch_writes_nothing_and_keeps_its_reason(self):
        name = self.upload()["batch"]["name"]
        with self.assertRaises(frappe.ValidationError):
            importing.discard_batch(name, "  ")
        context = importing.discard_batch(name, "The sender will resend with corrected codes.")
        self.assertEqual(context["batch"]["validation_report"]["discarded"]["reason"],
                         "The sender will resend with corrected codes.")
        self.assertEqual(context["batch"]["validation_report"]["discarded"]["by"], self.reviewer)
        batch = frappe.get_doc("Import Batch", name)
        self.assertFalse(batch.is_editable)
        self.assertFalse(batch.is_open)
        self.assertFalse(any(context["actions"].values()))
        with self.assertRaises(frappe.ValidationError):
            importing.commit_reviewed_batch(name)
        self.assertFalse(frappe.db.exists("Import Row", {"import_batch": name, "target_name": ["is", "set"]}))


class TestMethods(ImportPortalCase):
    def test_acting_endpoints_accept_post_only(self):
        allowed = frappe.allowed_http_methods_for_whitelisted_func
        for fn in (importing.upload_batch, importing.revalidate_batch, importing.exclude_row,
                   importing.commit_reviewed_batch, importing.discard_batch):
            self.assertEqual(allowed[fn], ["POST"], fn.__name__)
        for fn in (importing.get_batch_review, importing.import_profiles):
            self.assertEqual(allowed[fn], ["GET"], fn.__name__)

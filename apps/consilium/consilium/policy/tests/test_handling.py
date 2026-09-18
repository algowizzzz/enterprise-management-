"""Confidential and restricted handling, and the document viewer (P-1, P-13, P-19).

Every rule is tested by attempting the action as a user who must not have it,
through the path the framework itself uses: the permission check, the list
query, the REST read, the private-file download, the print view, the share, and
the viewer's own endpoint and page. The Governing Document hooks are registered
in ``hooks.py``. The Document Version and File hooks are not yet (see
``consilium/policy/handling.py``), so ``version_hooks`` registers them for the
tests that need them, the same way the escalation tests once did.
"""

from __future__ import annotations

import contextlib

import frappe
from werkzeug.exceptions import Forbidden

from consilium.consilium_core import versioning
from consilium.policy import handling
from consilium.policy.tests.utils import (
    DOCTYPE,
    PolicyTestCase,
    as_user,
    make_document,
    make_org_unit,
    make_user,
    make_user_group,
    refusals_for,
    unique,
)

VERSION = "Document Version"


@contextlib.contextmanager
def version_hooks():
    """Register the Document Version hooks the module asks ``hooks.py`` for."""
    real = frappe.get_hooks

    def patched(hook=None, *args, **kwargs):
        value = real(hook, *args, **kwargs)
        if hook == "permission_query_conditions":
            return {**(value or {}), VERSION: ["consilium.policy.handling.version_query_conditions"]}
        if hook == "has_permission":
            return {**(value or {}), VERSION: ["consilium.policy.handling.version_has_permission"]}
        return value

    frappe.get_hooks = patched
    try:
        yield
    finally:
        frappe.get_hooks = real


@contextlib.contextmanager
def request_to(path: str, **form):
    """Run inside a GET request for ``path``, as the framework would.

    The framework's access log commits during any GET request, test mode or not,
    and that would commit this test's own fixtures to the shared test database.
    Commits are therefore held for the duration, so tearDown's rollback still
    removes everything the test made.
    """
    from unittest import mock

    from werkzeug.test import EnvironBuilder
    from werkzeug.wrappers import Request

    had_request = hasattr(frappe.local, "request")
    previous_request = getattr(frappe.local, "request", None)
    previous_form = frappe.local.form_dict
    frappe.local.request = Request(EnvironBuilder(path=path, base_url="http://" + frappe.local.site).get_environ())
    frappe.local.form_dict = frappe._dict(form)
    try:
        with mock.patch.object(frappe.db, "commit", lambda *args, **kwargs: None):
            yield
    finally:
        frappe.local.form_dict = previous_form
        if had_request:
            frappe.local.request = previous_request
        else:
            del frappe.local.request


def restricted(level: str = "Restricted", **values):
    return make_document(handling_classification=level, **values)


def tiny_pdf() -> bytes:
    """A valid one-page PDF. The framework parses uploaded PDFs (it refuses
    ones carrying script), so a fixture has to be a real one."""
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 200 200] >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % number + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    out += b"".join(b"%010d 00000 n \n" % offset for offset in offsets)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objects) + 1, xref)
    return bytes(out)


def attach_file(doc_name: str, *, private: int = 1, doctype: str = DOCTYPE, suffix: str = "pdf"):
    return frappe.get_doc({
        "doctype": "File",
        "file_name": f"{unique('body')}.{suffix}",
        "attached_to_doctype": doctype,
        "attached_to_name": doc_name,
        "is_private": private,
        "content": tiny_pdf() if suffix == "pdf" else b"<p>a test body</p>",
    }).insert(ignore_permissions=True)


def version_with_file(doc, **values):
    body = attach_file(doc.name)
    version = versioning.create_version(
        frappe.get_doc(DOCTYPE, doc.name), change_summary="Uploaded for the test.", origin="Uploaded",
        body_file=body.file_url, version_label=values.pop("label", "1.0"),
    )
    return version, body


def publish(doc_name: str, version: str, *, audiences=None, view_only=0, print_=1, download=1, withdrawn_on=None):
    return frappe.get_doc({
        "doctype": "Document Publication",
        "document": doc_name,
        "document_version": version,
        "published_on": frappe.utils.now(),
        "audience_type": "Targeted Groups" if audiences else "All Employees",
        "audiences": audiences or [],
        "rendition_view_only": view_only,
        "rendition_print": print_,
        "rendition_download": download,
        "withdrawn_on": withdrawn_on,
    }).insert(ignore_permissions=True)


def can_read(user: str, name: str) -> bool:
    with as_user(user):
        return bool(frappe.has_permission(DOCTYPE, "read", doc=name))


def listed(user: str, name: str) -> bool:
    with as_user(user):
        return name in frappe.get_list(DOCTYPE, filters={"name": name}, pluck="name")


class TestVisibility(PolicyTestCase):
    def test_a_restricted_document_is_invisible_to_an_unnamed_policy_owner(self):
        doc = restricted()
        outsider = make_user("Policy Owner")
        self.assertFalse(can_read(outsider, doc.name))
        self.assertFalse(listed(outsider, doc.name))
        with as_user(outsider), self.assertRaises(frappe.PermissionError):
            frappe.client.get(DOCTYPE, doc.name)  # the REST read

    def test_an_internal_document_is_not_narrowed(self):
        doc = make_document()
        reader = make_user("Policy Reviewer")
        self.assertTrue(can_read(reader, doc.name))
        self.assertTrue(listed(reader, doc.name))

    def test_the_people_named_on_the_record_see_it(self):
        sponsor = make_user("Policy Reviewer")
        doc = restricted(document_sponsor=sponsor)
        for user in (doc.document_owner, doc.document_approver, sponsor):
            self.assertTrue(can_read(user, doc.name), user)
            self.assertTrue(listed(user, doc.name), user)

    def test_an_accountability_role_names_a_person_or_a_group_while_it_is_in_force(self):
        monitor = make_user("Policy Reviewer")
        member = make_user("Policy Reviewer")
        lapsed = make_user("Policy Reviewer")
        group = make_user_group([member])
        doc = restricted(accountability_roles=[
            {"role": "MONITOR", "user": monitor},
            {"role": "PARTNER", "user_group": group},
            {"role": "MONITOR", "user": lapsed, "from_date": "2020-01-01", "to_date": "2020-12-31"},
        ])
        self.assertTrue(can_read(monitor, doc.name))
        self.assertTrue(listed(member, doc.name))
        self.assertFalse(can_read(lapsed, doc.name))
        self.assertFalse(listed(lapsed, doc.name))

    def test_oversight_sees_every_document_and_a_platform_administrator_does_not(self):
        doc = restricted()
        self.assertTrue(can_read(make_user("Enterprise Policy Office"), doc.name))
        self.assertTrue(listed(make_user("Consilium Audit"), doc.name))
        administrator = make_user("Consilium Administrator")
        self.assertFalse(can_read(administrator, doc.name))
        self.assertFalse(listed(administrator, doc.name))

    def test_the_applicability_audience_sees_a_confidential_document_but_not_a_restricted_one(self):
        member = make_user("Policy Reviewer")
        group = make_user_group([member])
        rows = [{"scope_type": "Organization Unit", "scope_value": make_org_unit(), "notification_group": group}]
        confidential = restricted("Confidential", applicability=rows)
        tighter = restricted("Restricted", applicability=rows)
        self.assertTrue(can_read(member, confidential.name))
        self.assertTrue(listed(member, confidential.name))
        self.assertFalse(can_read(member, tighter.name))
        self.assertFalse(listed(member, tighter.name))

    def test_a_publication_audience_group_sees_it_until_the_publication_is_withdrawn(self):
        member = make_user("Policy Reviewer")
        group = make_user_group([member])
        doc = restricted()
        version, _body = version_with_file(doc)
        publication = publish(doc.name, version.name, audiences=[{"audience_kind": "User Group", "audience_value": group}])
        self.assertTrue(can_read(member, doc.name))
        self.assertTrue(listed(member, doc.name))

        frappe.db.set_value("Document Publication", publication.name, "withdrawn_on", "2020-01-01")
        self.assertFalse(can_read(member, doc.name))
        self.assertFalse(listed(member, doc.name))

    def test_a_role_audience_reaches_a_confidential_document_only(self):
        role_holder = make_user("Policy Reviewer")
        audience = [{"audience_kind": "Role", "audience_value": "Policy Reviewer"}]
        confidential = restricted("Confidential")
        tighter = restricted("Restricted")
        for doc in (confidential, tighter):
            version, _body = version_with_file(doc)
            publish(doc.name, version.name, audiences=audience)
        self.assertTrue(can_read(role_holder, confidential.name))
        self.assertFalse(can_read(role_holder, tighter.name))


class TestActions(PolicyTestCase):
    def test_print_is_refused_to_a_reader_when_print_is_closed_and_allowed_to_the_owner(self):
        from frappe.www.printview import validate_print_permission

        doc = restricted("Confidential")  # a new confidential document starts with print closed
        reader = doc.document_approver
        with as_user(reader):
            self.assertTrue(frappe.has_permission(DOCTYPE, "read", doc=doc.name))
            self.assertFalse(frappe.has_permission(DOCTYPE, "print", doc=doc.name))
            # The framework's print view accepts *read* as well as print; the
            # hook recognises the print request and answers for print.
            with request_to("/printview", doctype=DOCTYPE, name=doc.name), self.assertRaises(frappe.PermissionError):
                validate_print_permission(frappe.get_doc(DOCTYPE, doc.name))
        with as_user(doc.document_owner), request_to("/printview", doctype=DOCTYPE, name=doc.name):
            validate_print_permission(frappe.get_doc(DOCTYPE, doc.name))

    def test_print_follows_the_flag_on_an_internal_document_too(self):
        doc = make_document(allow_print=0)
        reader = make_user("Policy Owner")  # a role that may print at all
        with as_user(reader):
            self.assertFalse(frappe.has_permission(DOCTYPE, "print", doc=doc.name))
        frappe.db.set_value(DOCTYPE, doc.name, "allow_print", 1)
        with as_user(reader):
            self.assertTrue(frappe.has_permission(DOCTYPE, "print", doc=doc.name))

    def test_share_and_email_are_refused_to_a_reader_when_share_is_closed(self):
        # Only steward roles carry "share" on this DocType today, so the role
        # permissions already refuse most readers. The hook's own decision is
        # what holds if a role that may share is ever given to a non-steward.
        doc = restricted("Confidential")
        document = frappe.get_doc(DOCTYPE, doc.name)
        reader = doc.document_approver
        for ptype in ("share", "email"):
            self.assertIs(handling.has_permission(document, ptype, reader), False)
        frappe.db.set_value(DOCTYPE, doc.name, "allow_share", 1)
        document.reload()
        self.assertIsNone(handling.has_permission(document, "share", reader))

    def test_the_policy_office_may_share_a_closed_document(self):
        doc = restricted("Confidential")
        colleague = make_user("Policy Owner")
        with as_user(make_user("Enterprise Policy Office")):
            frappe.share.add(DOCTYPE, doc.name, colleague, read=1)
        self.assertTrue(can_read(colleague, doc.name))

    def test_an_attached_private_file_is_not_downloadable_by_someone_who_cannot_read_the_document(self):
        from frappe.utils.response import download_private_file

        doc = restricted()
        body = attach_file(doc.name)
        outsider = make_user("Policy Owner")
        with as_user(outsider), request_to(body.file_url), self.assertRaises(Forbidden):
            download_private_file(body.file_url)

    def test_an_attached_file_follows_the_download_flag_and_the_owner_may_always_download(self):
        from frappe.utils.response import download_private_file

        doc = restricted("Confidential")  # download closed by default
        body = attach_file(doc.name)
        reader = doc.document_approver
        with as_user(reader):
            # Reading the record is allowed; fetching the file is not.
            self.assertTrue(frappe.has_permission(DOCTYPE, "read", doc=doc.name))
        with as_user(reader), request_to(body.file_url), self.assertRaises(Forbidden):
            download_private_file(body.file_url)
        with as_user(doc.document_owner), request_to(body.file_url):
            self.assertEqual(download_private_file(body.file_url).status_code, 200)

        frappe.db.set_value(DOCTYPE, doc.name, "allow_download", 1)
        with as_user(reader), request_to(body.file_url):
            self.assertEqual(download_private_file(body.file_url).status_code, 200)

    def test_a_view_only_rendition_closes_download_even_when_the_document_allows_it(self):
        doc = restricted("Confidential")
        frappe.db.set_value(DOCTYPE, doc.name, "allow_download", 1)
        version, _body = version_with_file(doc)
        publish(doc.name, version.name, view_only=1, print_=0, download=0)
        reader = doc.document_approver
        self.purge_on_teardown(VERSION, version.name)
        with as_user(reader):
            document = frappe.get_doc(DOCTYPE, doc.name)
            self.assertFalse(handling.may_download(document, version=version.name))
            with self.assertRaises(frappe.PermissionError):
                handling.version_body(version.name, download=1)
        self.assertTrue(any(row["control"] == "restricted handling" for row in refusals_for(VERSION, version.name)))


class TestVersionBody(PolicyTestCase):
    def test_a_reader_gets_the_body_inline_and_uncached_when_it_may_not_be_downloaded(self):
        doc = restricted("Confidential")
        version, _body = version_with_file(doc)
        with as_user(doc.document_approver):
            response = handling.version_body(version.name)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.headers["Content-Disposition"].startswith("inline"))
        self.assertIn("no-store", response.headers["Cache-Control"])
        self.assertEqual(response.mimetype, "application/pdf")
        self.assertTrue(response.get_data().startswith(b"%PDF"))

    def test_someone_who_cannot_read_the_document_cannot_read_its_body(self):
        doc = restricted()
        version, _body = version_with_file(doc)
        self.purge_on_teardown(VERSION, version.name)
        with as_user(make_user("Policy Owner")), self.assertRaises(frappe.PermissionError):
            handling.version_body(version.name)
        self.assertTrue(refusals_for(VERSION, version.name))

    def test_a_file_that_could_run_script_is_never_served_inline(self):
        doc = make_document()
        body = attach_file(doc.name, suffix="html")
        version = versioning.create_version(
            frappe.get_doc(DOCTYPE, doc.name), change_summary="HTML body.", body_file=body.file_url
        )
        self.purge_on_teardown(VERSION, version.name)
        with self.assertRaises(frappe.PermissionError):
            handling.version_body(version.name)

    def test_a_guest_is_refused(self):
        doc = make_document()
        version, _body = version_with_file(doc)
        with as_user("Guest"), self.assertRaises(frappe.PermissionError):
            handling.version_body(version.name)


class TestVersionHooks(PolicyTestCase):
    """The Document Version hooks, registered for the test (see the module docstring)."""

    def test_a_version_carries_its_documents_handling(self):
        doc = restricted()
        version, _body = version_with_file(doc)
        administrator = make_user("Consilium Administrator")  # reads versions by role
        with version_hooks(), as_user(administrator):
            self.assertFalse(frappe.has_permission(VERSION, "read", doc=version.name))
            self.assertNotIn(version.name, frappe.get_list(VERSION, filters={"name": version.name}, pluck="name"))
        with version_hooks(), as_user(make_user("Consilium Audit")):
            self.assertTrue(frappe.has_permission(VERSION, "read", doc=version.name))

    def test_a_body_file_attached_to_the_version_is_guarded_too(self):
        from frappe.utils.response import download_private_file

        doc = restricted()
        version, body = version_with_file(doc)
        # The framework attaches a version's body file to the version as well,
        # so the same URL is reachable through a second File row.
        self.assertTrue(frappe.db.exists("File", {"file_url": body.file_url, "attached_to_doctype": VERSION}))
        administrator = make_user("Consilium Administrator")
        with version_hooks(), as_user(administrator), request_to(body.file_url), self.assertRaises(Forbidden):
            download_private_file(body.file_url)


class TestHandlingChanges(PolicyTestCase):
    def test_the_owner_may_not_lower_a_restricted_document_and_the_refusal_is_logged(self):
        doc = restricted()
        self.purge_on_teardown(DOCTYPE, doc.name)
        with as_user(doc.document_owner):
            fetched = frappe.get_doc(DOCTYPE, doc.name)
            fetched.handling_classification = "Internal"
            with self.assertRaises(frappe.PermissionError):
                fetched.save()
        self.assertTrue(any(row["control"] == "restricted handling" for row in refusals_for(DOCTYPE, doc.name)))

    def test_the_owner_may_not_reopen_download_on_a_confidential_document(self):
        doc = restricted("Confidential")
        self.purge_on_teardown(DOCTYPE, doc.name)
        with as_user(doc.document_owner):
            fetched = frappe.get_doc(DOCTYPE, doc.name)
            fetched.allow_download = 1
            with self.assertRaises(frappe.PermissionError):
                fetched.save()

    def test_the_policy_office_may_loosen_the_handling(self):
        doc = restricted()
        with as_user(make_user("Enterprise Policy Office")):
            fetched = frappe.get_doc(DOCTYPE, doc.name)
            fetched.handling_classification = "Internal"
            fetched.allow_download = 1
            fetched.save()
        self.assertEqual(frappe.db.get_value(DOCTYPE, doc.name, "handling_classification"), "Internal")

    def test_raising_a_document_closes_the_three_actions(self):
        doc = make_document()
        self.assertTrue(int(doc.allow_download) and int(doc.allow_print) and int(doc.allow_share))
        with as_user(doc.document_owner):
            fetched = frappe.get_doc(DOCTYPE, doc.name)
            fetched.handling_classification = "Confidential"
            fetched.save()
        values = frappe.db.get_value(DOCTYPE, doc.name, ["allow_download", "allow_print", "allow_share"])
        self.assertEqual([int(v) for v in values], [0, 0, 0])

    def test_raising_a_document_moves_its_public_attachments_to_private_storage(self):
        doc = make_document()
        public = attach_file(doc.name, private=0)
        self.assertTrue(public.file_url.startswith("/files/"))
        fetched = frappe.get_doc(DOCTYPE, doc.name)
        fetched.handling_classification = "Restricted"
        fetched.save(ignore_permissions=True)
        self.assertTrue(frappe.db.get_value("File", public.name, "file_url").startswith("/private/files/"))

    def test_a_new_upload_to_a_restricted_document_is_stored_private(self):
        doc = restricted()
        file_doc = frappe.get_doc({
            "doctype": "File", "file_name": f"{unique('up')}.pdf", "attached_to_doctype": DOCTYPE,
            "attached_to_name": doc.name, "is_private": 0, "content": tiny_pdf(),
        })
        handling.guard_file_privacy(file_doc)
        file_doc.insert(ignore_permissions=True)
        self.assertTrue(file_doc.file_url.startswith("/private/files/"))

        open_doc = make_document()
        other = frappe.get_doc({
            "doctype": "File", "file_name": f"{unique('up')}.pdf", "attached_to_doctype": DOCTYPE,
            "attached_to_name": open_doc.name, "is_private": 0, "content": tiny_pdf(),
        })
        handling.guard_file_privacy(other)
        self.assertFalse(int(other.is_private))


class TestViewerPage(PolicyTestCase):
    def _render(self, user: str, query: dict):
        from urllib.parse import urlencode

        from frappe.website.serve import get_response

        with as_user(user), request_to("/document-view?" + urlencode(query), **query):
            response = get_response("document-view")
            return response.status_code, response.get_data(as_text=True)

    def test_a_named_reader_sees_the_body_with_a_watermark_and_no_download(self):
        doc = restricted()
        version, _body = version_with_file(doc)
        status, html = self._render(doc.document_approver, {"version": version.name})
        self.assertEqual(status, 200)
        self.assertIn("consilium.policy.handling.version_body?version=" + version.name, html)
        self.assertIn("cns-docview-watermark", html)
        self.assertIn(doc.document_approver, html)
        self.assertNotIn("download=1", html)
        self.assertIn("cannot prevent", html)

    def test_the_owner_is_offered_a_download(self):
        doc = restricted()
        version, _body = version_with_file(doc)
        status, html = self._render(doc.document_owner, {"version": version.name})
        self.assertEqual(status, 200)
        self.assertIn("download=1", html)

    def test_an_authored_body_is_rendered_sanitised(self):
        doc = make_document()
        version = versioning.create_version(
            frappe.get_doc(DOCTYPE, doc.name), change_summary="Authored.",
            body_text="<h3>Purpose</h3><p>Plain words.</p><script>alert(1)</script>",
        )
        status, html = self._render(make_user("Policy Reviewer"), {"version": version.name})
        self.assertEqual(status, 200)
        self.assertIn("<h3>Purpose</h3>", html)
        self.assertNotIn("<script>alert(1)</script>", html)
        self.assertNotIn("cns-docview-watermark\"", html)

    def test_someone_who_cannot_read_the_document_is_refused(self):
        doc = restricted()
        version, _body = version_with_file(doc)
        self.purge_on_teardown(VERSION, version.name)
        status, html = self._render(make_user("Policy Owner"), {"version": version.name})
        self.assertEqual(status, 403)
        self.assertNotIn(doc.document_name, html)

    def test_an_unknown_version_and_a_missing_one_are_stated(self):
        reader = make_user("Policy Reviewer")
        status, html = self._render(reader, {"version": "DVER-NOPE<b>"})
        self.assertEqual(status, 200)
        self.assertIn("That version is not available", html)
        self.assertNotIn("NOPE<b>", html)
        status, html = self._render(reader, {})
        self.assertIn("No version was named", html)

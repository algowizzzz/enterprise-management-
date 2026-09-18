"""DEMONSTRATION data for restricted handling, the document viewer and glossary enforcement.

    from deploy.demo_additions import handling
    handling.run(frappe)          # inside a connected site; the caller commits

Builds on records ``deploy/demo_data.py`` has already made, and changes nothing
else. Idempotent: every step looks for what it would create and skips it when
it exists.

* **GDOC-00017, Artificial Intelligence Use Standard** (a draft) becomes
  **Restricted**: visible only to the people named on it and to oversight, with
  download, print and share closed. A new version 0.2 is taken from an uploaded
  PDF, so ``/document-view`` has a real file to show under the watermark.
* **GDOC-00012, Anti-Money Laundering Policy** is already Confidential with a
  view-only publication. It is left as it is: it demonstrates a view-only
  rendition of an authored (HTML) body.
* An enforced, document-scoped glossary term, **Artificial Intelligence Use
  Case**, with the synonyms "AI use case" and "AI initiative". The new version
  uses the official term, so the viewer's definitions panel counts it. Editing
  the document's abstract to say "AI initiative" alone is refused.

The PDF is written here by hand: a few hundred bytes of PDF 1.4 with the two
standard fonts every viewer carries. There is no new dependency and nothing is
fetched. Everything is fictitious, and records are owned by ``@demo.example``
personas like the rest of the demonstration data.
"""

from __future__ import annotations

DOCUMENT_NAME = "Artificial Intelligence Use Standard"
OWNER = "head.technology.risk@demo.example"
POLICY_OFFICE = "policy.office.lead@demo.example"
PDF_FILE_NAME = "ai-use-standard-v0-2-demo.pdf"
VERSION_LABEL = "0.2"
TERM = "Artificial Intelligence Use Case"
SYNONYMS = ("AI use case", "AI initiative")

PAGES = [
    (
        "Artificial Intelligence Use Standard",
        [
            "Version 0.2 - draft for review. DEMONSTRATION DOCUMENT: fictitious content.",
            "",
            "1. Purpose",
            "This standard sets the minimum requirements for the approved use of",
            "artificial intelligence across the group.",
            "",
            "2. Scope",
            "Every Artificial Intelligence Use Case, whether built in-house or",
            "supplied by a third party, in every business line and legal entity.",
            "",
            "3. Registration",
            "3.1 Each Artificial Intelligence Use Case is registered before any",
            "    pilot begins, with a named business owner.",
            "3.2 The register records purpose, data used, affected customers and",
            "    the decision the output informs.",
            "",
            "4. Risk tiering",
            "4.1 Each use case is assigned a tier (1 high to 3 low) by the model",
            "    risk function before approval.",
            "4.2 Tier 1 use cases require approval by the Technology Risk Committee.",
        ],
    ),
    (
        "Artificial Intelligence Use Standard (continued)",
        [
            "5. Human oversight",
            "5.1 A named person reviews every output that affects a customer",
            "    outcome before it takes effect.",
            "",
            "6. Data protection",
            "6.1 No customer personal information is sent to an external service",
            "    without a completed privacy impact assessment.",
            "",
            "7. Monitoring",
            "7.1 Owners report performance, drift and incidents quarterly.",
            "",
            "8. Exceptions",
            "Deviations require an approved exemption with an expiry date.",
            "",
            "RESTRICTED - circulation limited to the people named on the record.",
        ],
    ),
]


def _pdf_text(value: str) -> str:
    return value.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def build_pdf(pages=PAGES) -> bytes:
    """A small, valid PDF 1.4: one content stream per page, Helvetica only.

    The cross-reference table needs the byte offset of every object, so the
    objects are assembled first and the offsets counted as they are written.
    """
    fonts = {"F1": "Helvetica", "F2": "Helvetica-Bold"}
    objects: list[bytes] = []

    def add(body: bytes) -> int:
        objects.append(body)
        return len(objects)

    catalog = add(b"")  # filled once the page tree's number is known
    pages_obj = add(b"")
    font_ids = {key: add(f"<< /Type /Font /Subtype /Type1 /BaseFont /{name} >>".encode()) for key, name in fonts.items()}
    resources = "<< /Font << " + " ".join(f"/{k} {v} 0 R" for k, v in font_ids.items()) + " >> >>"

    page_ids = []
    for number, (title, lines) in enumerate(pages, 1):
        stream = [f"BT /F2 16 Tf 56 780 Td ({_pdf_text(title)}) Tj ET", "BT /F1 11 Tf 15 TL 56 748 Td"]
        for line in lines:
            stream.append(f"({_pdf_text(line)}) Tj T*")
        stream.append("ET")
        stream.append(f"BT /F1 9 Tf 56 40 Td (Page {number} of {len(pages)}) Tj ET")
        content = "\n".join(stream).encode("latin-1")
        content_id = add(b"<< /Length %d >>\nstream\n" % len(content) + content + b"\nendstream")
        page_ids.append(add(
            f"<< /Type /Page /Parent {pages_obj} 0 R /MediaBox [0 0 595 842] "
            f"/Resources {resources} /Contents {content_id} 0 R >>".encode()
        ))
    objects[catalog - 1] = f"<< /Type /Catalog /Pages {pages_obj} 0 R >>".encode()
    objects[pages_obj - 1] = (
        f"<< /Type /Pages /Kids [{' '.join(f'{p} 0 R' for p in page_ids)}] /Count {len(page_ids)} >>".encode()
    )

    out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = []
    for number, body in enumerate(objects, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % number + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    for offset in offsets:
        out += b"%010d 00000 n \n" % offset
    out += b"trailer\n<< /Size %d /Root %d 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objects) + 1, catalog, xref)
    return bytes(out)


def _plain_text(pages=PAGES) -> str:
    return "\n".join(title + "\n" + "\n".join(lines) for title, lines in pages)


def _as(frappe, user: str):
    """Run a step as a persona, so the record carries a demo owner."""
    class _Switch:
        def __enter__(self):
            self.previous = frappe.session.user
            frappe.set_user(user if frappe.db.exists("User", user) else "Administrator")

        def __exit__(self, *exc):
            frappe.set_user(self.previous)
            return False

    return _Switch()


def _restrict(frappe, name: str, report: dict) -> None:
    from consilium.policy import handling

    doc = frappe.get_doc("Governing Document", name)
    if doc.handling_classification == handling.RESTRICTED:
        report["restricted"] = "already"
        return
    # As the administrator: raising the handling is open to any writer, but
    # the demo should not depend on which persona that is.
    doc.handling_classification = handling.RESTRICTED
    doc.save(ignore_permissions=True)
    report["restricted"] = name


def _pdf_version(frappe, name: str, report: dict) -> None:
    from consilium.policy import publication

    # Matched on the stem, not the exact name: the framework appends a suffix
    # when a file of that name is already on disk (a restored or re-created
    # site keeps its files directory), and an exact match would then miss the
    # file this step made and attach a second copy on every run.
    stem, _dot, extension = PDF_FILE_NAME.rpartition(".")
    existing = frappe.get_all(
        "File",
        filters={"attached_to_doctype": "Governing Document", "attached_to_name": name,
                 "file_name": ["like", f"{stem}%.{extension}"]},
        fields=["name", "file_url"],
        order_by="creation asc",
        limit=1,
    )
    with _as(frappe, OWNER):
        if existing:
            file_url = existing[0]["file_url"]
        else:
            file_doc = frappe.get_doc({
                "doctype": "File",
                "file_name": PDF_FILE_NAME,
                "attached_to_doctype": "Governing Document",
                "attached_to_name": name,
                "is_private": 1,
                "content": build_pdf(),
            }).insert(ignore_permissions=True)
            file_url = file_doc.file_url
            report["file"] = file_url

        if frappe.db.exists("Document Version", {"subject_doctype": "Governing Document", "subject_name": name,
                                                 "body_file": file_url}):
            report["version"] = "already"
            return
        if not int(frappe.db.get_value("Governing Document", name, "is_editable") or 0):
            report["version"] = "skipped: the document is not editable"
            return
        version = publication.upload_version(
            name,
            change_summary="Draft 0.2 uploaded from the editor: adds registration, risk tiering and "
                           "human-oversight requirements for review.",
            body_file=file_url,
            body_text=_plain_text(),
            version_label=VERSION_LABEL,
        )
        report["version"] = version.name


def _term(frappe, name: str, report: dict) -> None:
    from consilium.policy import glossary

    existing = frappe.db.get_value("Glossary Term", {"term": TERM, "scope_document": name}, "name")
    with _as(frappe, POLICY_OFFICE):
        if not existing:
            term = frappe.get_doc({
                "doctype": "Glossary Term",
                "term": TERM,
                "definition": "A distinct business purpose for which an artificial intelligence technique is "
                              "used, registered and approved as one unit of risk assessment.",
                "scope_level": "Document",
                "scope_document": name,
                "term_status": "Proposed",
                "enforce_usage": 1,
                "synonyms": [{"synonym": value} for value in SYNONYMS],
            }).insert(ignore_permissions=True)
            existing = term.name
            report["term"] = existing
        if not int(frappe.db.get_value("Glossary Term", existing, "is_active") or 0):
            glossary.publish(existing, approved_by=POLICY_OFFICE,
                             change_summary="Defined for the Artificial Intelligence Use Standard.")
            report["term_published"] = existing

    doc = frappe.get_doc("Governing Document", name)
    if not any(row.glossary_term == existing for row in doc.get("glossary_terms") or []):
        doc.append("glossary_terms", {"glossary_term": existing,
                                      "context_note": "Registration and tiering are per use case."})
        doc.save(ignore_permissions=True)
        report["term_linked"] = name


def run(frappe) -> dict:
    """Apply the additions. Returns what was done; the caller commits."""
    report: dict = {}
    name = frappe.db.get_value("Governing Document", {"document_name": DOCUMENT_NAME}, "name")
    if not name:
        report["skipped"] = f"no document named {DOCUMENT_NAME!r}; run deploy/demo_data.py first"
        return report
    report["document"] = name
    _restrict(frappe, name, report)
    _pdf_version(frappe, name, report)
    _term(frappe, name, report)
    return report

"""Naming conventions for governing documents (P-15, and P-16's "enforce ... naming conventions").

A ``Document Template`` carries a ``naming_convention_pattern`` such as
``<Subject> Policy``. Until now it was stored and never read. This module makes
it a rule: a document's name must match the pattern of the template that
applies to it, and a refusal is logged like every other refusal on the platform.

The pattern language
--------------------
A pattern is literal text with placeholders. A placeholder is written
``<Name>`` (the form the reference templates use) or ``{name}`` (the form older
templates use). The placeholder name decides what it matches:

* ``year`` matches a four-digit year;
* ``number``, ``no``, ``n``, ``seq`` and ``sequence`` match digits;
* anything else (``Subject``, ``Process``, ``unit``) matches any non-empty text
  that does not begin or end with a space.

Literal text must appear exactly, including its case. Runs of spaces are
treated as one. The whole name must match, not just part of it.

Which template applies
----------------------
A template is chosen by document type and action. Only the **New** template
names a document. The Edit, Retire and Review templates' patterns name what
those actions produce, a review record for example (``<Subject> Policy — review
<year>``), and not the document. Where several active New templates exist for a
type, a name that matches any one of them is accepted. A type with no active New
template, or one with no pattern, is not checked.

When it is checked
------------------
* On a Governing Document save, when the record is new or its name or type has
  changed. A document named before its convention existed is not refused on an
  unrelated edit. It must conform the next time someone renames it.
* At intake, on the proposed name, when the request is classified and again
  when it is turned into a document. The second check applies when a template
  changes between the two.

Imports, migrations and patches are not checked. P-20 gives imported data its
own handling rules for invalid values, and a legacy name brought across as it
stands is not a new naming decision.
"""

from __future__ import annotations

import html
import re

import frappe
from frappe import _

DOCTYPE = "Governing Document"
TEMPLATE_DOCTYPE = "Document Template"
REQUEST_DOCTYPE = "Document Intake Request"

#: The template action whose pattern names the document itself.
NAMING_ACTION = "New"

_PLACEHOLDER = re.compile(r"<\s*([^<>]+?)\s*>|\{\s*([^{}]+?)\s*\}")
_DIGITS = {"number", "no", "n", "seq", "sequence"}


def pattern_regex(pattern: str) -> re.Pattern:
    """Compile a naming pattern to an anchored regular expression.

    The stored pattern is HTML-escaped by the framework's sanitiser (``<`` is
    kept as ``&lt;``), so it is unescaped first.
    """
    text = html.unescape(pattern or "").strip()
    parts: list[str] = []
    position = 0
    for match in _PLACEHOLDER.finditer(text):
        parts.append(_literal(text[position:match.start()]))
        name = (match.group(1) or match.group(2) or "").strip().lower()
        if name == "year":
            parts.append(r"\d{4}")
        elif name in _DIGITS:
            parts.append(r"\d+")
        else:
            parts.append(r"\S(?:.*\S)?")
        position = match.end()
    parts.append(_literal(text[position:]))
    return re.compile("^" + "".join(parts) + "$")


def _literal(text: str) -> str:
    """Literal text, with any run of whitespace matching any run of whitespace."""
    return "".join(r"\s+" if piece.isspace() else re.escape(piece) for piece in re.split(r"(\s+)", text) if piece)


def display_pattern(pattern: str) -> str:
    return html.unescape(pattern or "").strip()


def applicable_patterns(document_type: str | None) -> list[dict]:
    """The active New templates of a type that carry a pattern."""
    if not document_type:
        return []
    return [
        row for row in frappe.get_all(
            TEMPLATE_DOCTYPE,
            filters={"document_type": document_type, "action": NAMING_ACTION, "is_active": 1},
            fields=["name", "naming_convention_pattern"],
            order_by="name asc",
        )
        if (row.get("naming_convention_pattern") or "").strip()
    ]


def check_name(name: str | None, document_type: str | None) -> dict | None:
    """``None`` when the name conforms (or nothing applies), else what it missed."""
    templates = applicable_patterns(document_type)
    if not templates:
        return None
    candidate = (name or "").strip()
    for row in templates:
        if pattern_regex(row["naming_convention_pattern"]).match(candidate):
            return None
    return {
        "name": candidate,
        "document_type": document_type,
        "templates": [row["name"] for row in templates],
        "patterns": [display_pattern(row["naming_convention_pattern"]) for row in templates],
    }


def _skipped() -> bool:
    flags = frappe.flags
    return bool(flags.in_import or flags.in_migrate or flags.in_patch or flags.in_install)


def _refuse(miss: dict, *, subject_doctype: str, subject_name: str, route: str) -> None:
    from consilium.consilium_core import audit

    audit.refuse(
        _("The name “{0}” does not follow the naming convention for this document type. "
          "It should read {1} (template {2}).").format(
            miss["name"],
            _(" or ").join(f"“{pattern}”" for pattern in miss["patterns"]),
            ", ".join(miss["templates"]),
        ),
        subject_doctype=subject_doctype,
        subject_name=subject_name,
        attempted_action="Modify",
        control="naming convention",
        context={**miss, "route": route},
        exc=frappe.ValidationError,
    )


def enforce_on_document(doc) -> None:
    """Called from the Governing Document ``validate``."""
    if _skipped():
        return
    if not doc.is_new():
        before = doc.get_doc_before_save()
        if before is not None and before.document_name == doc.document_name \
                and before.document_type == doc.document_type:
            return
    miss = check_name(doc.document_name, doc.document_type)
    if miss:
        _refuse(miss, subject_doctype=DOCTYPE, subject_name=doc.name or doc.document_name, route="document save")


def check_intake(request) -> None:
    """The intake check on a request's proposed name. Takes the request or its name.

    A change request that proposes no new name keeps the document's current
    name, which is checked (if at all) when the document itself is renamed.
    """
    if _skipped():
        return
    if isinstance(request, str):
        request = frappe.get_doc(REQUEST_DOCTYPE, request)
    name = (request.get("proposed_document_name") or "").strip()
    if not name:
        return
    document_type = request.get("proposed_document_type")
    if not document_type and request.get("subject_document"):
        document_type = frappe.db.get_value(DOCTYPE, request.subject_document, "document_type")
    miss = check_name(name, document_type)
    if miss:
        _refuse(miss, subject_doctype=REQUEST_DOCTYPE, subject_name=request.name, route="intake")


@frappe.whitelist()
def validate_name(document_name: str, document_type: str) -> dict:
    """What a form can ask before it saves: does this name follow the convention?"""
    frappe.has_permission(TEMPLATE_DOCTYPE, "read", throw=True)
    miss = check_name(document_name, document_type)
    patterns = [display_pattern(row["naming_convention_pattern"]) for row in applicable_patterns(document_type)]
    return {"valid": miss is None, "patterns": patterns}

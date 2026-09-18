"""What follows when a governing document moves: dispositions and the notices they owe.

Three requirements meet at the same moment — the save on which a document's
semantic flags change — and so they are handled together, from the document's
``on_update``:

* **P-26, the review disposition.** A review round ends when the document stops
  requiring review. If it went back to being editable it was *returned*; if not,
  it was *accepted*. Either way a ``Document Disposition`` records who, when,
  against which version and with what comments, and the originator — the
  document's owner — is told.
* **E11-S5, the audience.** A document that comes back into force with a new
  version has *changed*, and one that leaves force for good has been *retired*.
  Both are told to everyone the document's applicability reaches, resolved at
  that moment (``applicability.affected_parties``), never from a list kept here.
  First publication is told by ``publication.record_publication``, which knows
  the audience and renditions it was published with; it is not repeated here.
* **P-26/G-16, retirement.** A retired document is recorded as disposed of:
  who retired it, when, why, and what retention now holds the record to —
  its retention class, when that retention ends, what is then to happen, and
  any legal hold. Nothing is deleted. Disposal at the end of retention is
  Core's separate, approved act (``retention.execute_disposition``).

It also closes the intake loop (E13): a *Change* request naming the document is
fulfilled when a version comes into force, a *Retire* request when the document
is retired. See ``intake.fulfil_for_document``.

Every decision here reads the flags — ``is_active``, ``is_editable``,
``requires_review`` — before and after the save. The phase labels are copied
onto the disposition for the reader and never compared.

Why the comments arrive through ``frappe.flags``: the portal's
``lifecycle.take_action`` takes them from the person acting and the framework's
``apply_workflow`` then saves the document; there is no argument to carry them
through that save. The flag is keyed to the document's name, so it cannot
attach to some other record saved in the same request.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import cint, now, nowdate

from consilium.consilium_core import notification, versioning

DOCTYPE = "Governing Document"
DISPOSITION_DOCTYPE = "Document Disposition"

#: Values written to ``disposition_kind``. Labels for the reader; nothing
#: branches on them after they are written.
REVIEW_RETURNED = "Review Returned"
REVIEW_ACCEPTED = "Review Accepted"
RETIRED = "Retired"

#: Intake request types a movement fulfils. Request types are kinds of request,
#: not workflow states: a "Change" names a document to change, a "Retire" one to
#: retire.
REQUEST_CHANGE = "Change"
REQUEST_RETIRE = "Retire"

EVENT_CHANGED = "policy.document.changed"
EVENT_RETIRED = "policy.document.retired"
EVENT_REVIEW = "policy.review.disposition"

#: ``frappe.flags`` key for the comments given with a transition.
COMMENTS_FLAG = "consilium_transition_comments"


def _flags(doc) -> dict:
    return {
        "is_active": cint(doc.get("is_active")),
        "is_editable": cint(doc.get("is_editable")),
        "requires_review": cint(doc.get("requires_review")),
    }


def comments_for(doc) -> str | None:
    """The comments the person moving this document gave, if they gave any."""
    held = frappe.flags.get(COMMENTS_FLAG)
    if held and held[0] == doc.name:
        return (held[1] or "").strip() or None
    return None


def on_document_update(doc) -> None:
    """Called from ``GoverningDocument.on_update``. Acts only on a change of flags."""
    before = doc.get_doc_before_save()
    if before is None:
        return
    was, now_ = _flags(before), _flags(doc)
    comments = comments_for(doc)

    if was["requires_review"] and not now_["requires_review"]:
        record_review(doc, before, returned=bool(now_["is_editable"]), comments=comments)

    if not was["is_active"] and now_["is_active"]:
        notify_change_in_force(doc)
        _fulfil(doc, REQUEST_CHANGE, _("A version of {0} came into force.").format(doc.name))

    if was["is_active"] and not now_["is_active"] and not now_["is_editable"]:
        reason = comments or _retire_request_reason(doc.name)
        disposition = record_retirement(doc, before, reason=reason)
        _fulfil(doc, REQUEST_RETIRE, _("{0} was retired (disposition {1}).").format(doc.name, disposition))


def _fulfil(doc, request_type: str, note: str) -> None:
    from consilium.policy import intake

    intake.fulfil_for_document(doc.name, request_type, note)


def _retire_request_reason(document: str) -> str | None:
    """The justification of an open retirement request, when nobody gave a reason at the time."""
    rows = frappe.get_all(
        "Document Intake Request",
        filters={"subject_document": document, "request_type": REQUEST_RETIRE, "is_open": 1},
        fields=["name", "business_justification"],
        order_by="creation asc",
        limit=1,
    )
    if rows and rows[0].get("business_justification"):
        return _("As requested in {0}: {1}").format(rows[0]["name"], rows[0]["business_justification"])
    return None


def _current_version(doc):
    return versioning.current_version(DOCTYPE, doc.name)


# --------------------------------------------------------------------- review


def record_review(doc, before, *, returned: bool, comments: str | None) -> str:
    """P-26: the disposition of one review round, and the originator told."""
    version = _current_version(doc)
    kind = REVIEW_RETURNED if returned else REVIEW_ACCEPTED
    originator = doc.document_owner
    dispatched = notification.notify(
        EVENT_REVIEW,
        [originator] if originator else [],
        {
            "disposition": kind,
            "decided_by": frappe.utils.get_fullname(frappe.session.user),
            "comments": comments or "",
            "version_label": version.version_label if version else doc.version_label,
        },
        DOCTYPE,
        doc.name,
    )
    return _insert(
        doc,
        before,
        kind=kind,
        reason=comments,
        version=version,
        originator=originator,
        notified=len(dispatched),
    )


# ------------------------------------------------------------------ audience


def _previously_in_force(doc) -> bool:
    """Whether some *other* version of this document was published before.

    A publication record, or a version marked published, other than the one now
    current. The first time a document comes into force is its publication, not
    a change.
    """
    current = doc.current_version or ""
    if frappe.db.exists(
        "Document Publication",
        {"document": doc.name, "document_version": ["!=", current], "docstatus": ["<", 2]},
    ):
        return True
    return bool(
        frappe.db.exists(
            "Document Version",
            {"subject_doctype": DOCTYPE, "subject_name": doc.name, "published": 1, "name": ["!=", current]},
        )
    )


def notify_change_in_force(doc) -> list[str]:
    """E11-S5: a new version is in force. Told to everyone applicability reaches."""
    from consilium.policy import applicability

    if not _previously_in_force(doc):
        return []
    version = _current_version(doc)
    if version and cint(version.get("published")):
        # The version now in force is one already published: the document came
        # back without its text changing, so there is no change to announce.
        return []
    recipients = applicability.affected_parties(doc.name)
    if not recipients:
        return []
    return notification.notify(
        EVENT_CHANGED,
        recipients,
        {
            "version_label": (version.version_label if version else doc.version_label) or "",
            "change_summary": (version.change_summary if version else "") or "",
            "effective_on": str(doc.effective_on or ""),
        },
        DOCTYPE,
        doc.name,
    )


# ---------------------------------------------------------------- retirement


def retention_outcome(doc) -> dict:
    """What retention holds a retired document to. Reads Core; changes nothing.

    The class is the one on the document, or failing that the winning retention
    assignment. The end of retention is Core's own calculation from the class's
    trigger event, which for a governing document is usually its retirement.
    """
    from consilium.consilium_core import retention

    retention_class = doc.get("retention_class")
    if not retention_class:
        assignment = retention.effective_retention(DOCTYPE, doc.name)
        retention_class = assignment["retention_class"] if assignment else None
    hold = retention.active_legal_hold(DOCTYPE, doc.name)

    out = {
        "retention_class": retention_class,
        "disposition_action": None,
        "disposition_due_on": None,
        "legal_hold": hold,
    }
    if retention_class and frappe.db.exists("Retention Class", retention_class):
        cls = frappe.db.get_value(
            "Retention Class", retention_class, ["title", "disposition_action", "retention_period_months"],
            as_dict=True,
        )
        out["disposition_action"] = cls.disposition_action
        out["disposition_due_on"] = str(retention.disposition_due_date(retention_class, DOCTYPE, doc.name))
        text = _(
            "retained under {0} ({1}) for {2} months; when that ends, the action is {3}, due {4}, and it "
            "happens only once a named person approves it."
        ).format(retention_class, cls.title or retention_class, cint(cls.retention_period_months),
                 cls.disposition_action or _("a review"), out["disposition_due_on"])
    else:
        text = _("no retention class is recorded, so the record is kept until one is assigned.")
    if hold:
        text += " " + _("Legal hold {0} is in force: disposal is suspended until it is released.").format(hold)
    out["text"] = text[0].upper() + text[1:]
    return out


def record_retirement(doc, before, *, reason: str | None) -> str:
    """The retirement disposition, and the notice to the audience and the owner."""
    from consilium.policy import applicability

    outcome = retention_outcome(doc)
    recipients = set(applicability.affected_parties(doc.name))
    if doc.document_owner:
        recipients.add(doc.document_owner)
    dispatched = notification.notify(
        EVENT_RETIRED,
        sorted(recipients),
        {
            "reason": reason or "",
            "retired_on": str(doc.retired_on or nowdate()),
            "retention_outcome": outcome["text"],
        },
        DOCTYPE,
        doc.name,
    )
    return _insert(
        doc,
        before,
        kind=RETIRED,
        reason=reason,
        version=_current_version(doc),
        originator=doc.document_owner,
        notified=len(dispatched),
        outcome=outcome,
    )


def _insert(doc, before, *, kind, reason, version, originator, notified, outcome=None) -> str:
    outcome = outcome or {}
    return frappe.get_doc(
        {
            "doctype": DISPOSITION_DOCTYPE,
            "document": doc.name,
            "disposition_kind": kind,
            "document_version": version.name if version else None,
            "version_label": (version.version_label if version else doc.version_label) or None,
            "from_phase": before.get("lifecycle_phase"),
            "to_phase": doc.get("lifecycle_phase"),
            "decided_by": frappe.session.user,
            "decided_on": now(),
            "reason": reason or None,
            "originator": originator,
            "notified_count": notified,
            "retention_class": outcome.get("retention_class"),
            "disposition_action": outcome.get("disposition_action"),
            "disposition_due_on": outcome.get("disposition_due_on"),
            "legal_hold": outcome.get("legal_hold"),
            "retention_outcome": outcome.get("text"),
        }
    ).insert(ignore_permissions=True).name


# -------------------------------------------------------------------- portal


@frappe.whitelist(methods=["GET"])
def document_dispositions(document: str) -> list[dict]:
    """The dispositions of one document, for its page.

    ``Document Disposition`` is readable directly only by oversight, because a
    disposition names the document and quotes its reviewers. Anyone who may see
    the document itself — its handling rules included — may see its
    dispositions here.
    """
    from consilium.policy import lifecycle

    lifecycle.load_for_portal(document)
    if not frappe.has_permission(DOCTYPE, "read", doc=document):
        return []
    return frappe.get_all(
        DISPOSITION_DOCTYPE,
        filters={"document": document},
        fields=["name", "disposition_kind", "version_label", "from_phase", "to_phase", "decided_by",
                "decided_on", "reason", "originator", "notified_count", "retention_class",
                "disposition_action", "disposition_due_on", "legal_hold", "retention_outcome"],
        order_by="decided_on desc, creation desc",
    )

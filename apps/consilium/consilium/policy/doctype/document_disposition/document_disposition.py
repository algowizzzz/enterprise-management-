"""Document Disposition — controller.

The recorded outcome of a governing document leaving a stage for good: a review
round returned or accepted (P-26), or the document retired, with what retention
then holds it to (G-16). Written by ``consilium.policy.disposition`` as the
document moves, and never by hand: no role holds create or write.

It is an audit artefact, so it is append-only in the same way as the refusal
log: a changed field or a delete is refused and the refusal is itself logged.
Retiring a document deletes nothing — the disposition says what will happen to
the record when its retention ends, and that disposal is a separate, approved
act in Core's retention engine.

    Specified by: 01-requirements-baseline.md P-26 (disposition record and its notification); G-16 (retention outcome on retirement).
"""

from frappe.model.document import Document

from consilium.consilium_core import append_only


class DocumentDisposition(Document):
    def validate(self):
        append_only.guard_update(self, control="disposition append-only")

    def on_trash(self):
        append_only.guard_delete(self, control="disposition append-only")

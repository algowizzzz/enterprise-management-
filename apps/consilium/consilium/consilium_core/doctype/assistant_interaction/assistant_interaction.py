"""Assistant Interaction — controller.

One row per question answered by the help assistant. It is the audit trail for
the assistant and the counter its per-person rate limit reads, so it is
append-only: an edited row would falsify both. Nobody holds create or write on
it; the assistant writes it on the asker's behalf.

Why a separate log rather than ``AI Service Request``: that record is a
data-boundary control — it says what *left the platform*. Most answers never
leave the platform at all, and logging them there would dilute the one record
an auditor reads to answer "what did we send out". So every question lands
here, and only an answer that actually called an external endpoint also writes
an ``AI Service Request``, linked from this row.

    Specified by: 01-requirements-baseline.md O-6/O-7 (AI integration); help assistant audit.
"""

from frappe.model.document import Document

from consilium.consilium_core import append_only


class AssistantInteraction(Document):
    def validate(self):
        append_only.guard_update(self, control="assistant log append-only")

    def on_trash(self):
        append_only.guard_delete(self, control="assistant log append-only")

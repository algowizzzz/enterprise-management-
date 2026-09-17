"""Meeting Attendance — controller.

Who was present at a meeting. counts_toward_quorum is snapshotted from the seat at the time attendance was taken, so a later seat-role change cannot rewrite whether the meeting was quorate.
"""

from frappe.model.document import Document


class MeetingAttendance(Document):
    def validate(self):
        pass

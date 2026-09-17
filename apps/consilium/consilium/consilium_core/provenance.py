"""AI provenance.

Two records around every call to the external AI platform, because they answer
two different questions and neither is derivable from the other:

* ``AI Service Request`` — what data left the platform, to which capability, and
  what came back. A data-boundary control.
* ``AI Suggestion Acceptance`` — who took responsibility for machine-generated
  content, and against which version. An accountability control.

Nothing here calls anything; the caller does the call and records what happened.
"""

from __future__ import annotations

import frappe
from frappe.utils import now

from consilium.consilium_core import versioning


def record_request(
    *,
    capability: str,
    context_sent: str,
    context_classification: str = "Internal",
    subject_doctype: str | None = None,
    subject_name: str | None = None,
    request_reference: str | None = None,
):
    return frappe.get_doc(
        {
            "doctype": "AI Service Request",
            "request_reference": request_reference or frappe.generate_hash(length=12),
            "capability": capability,
            "subject_doctype": subject_doctype,
            "subject_name": subject_name,
            "requested_by": frappe.session.user,
            "requested_on": now(),
            "context_sent": context_sent,
            "context_classification": context_classification,
            "status": "Sent",
        }
    ).insert(ignore_permissions=True)


def record_response(request, *, status: str, payload: str | None = None, error: str | None = None,
                    duration_ms: int | None = None):
    """Record the one response a request may receive. A second attempt is refused."""
    if isinstance(request, str):
        request = frappe.get_doc("AI Service Request", request)
    request.response_received_on = now()
    request.response_payload = payload
    request.error_detail = error
    request.duration_ms = duration_ms
    request.status = status
    request.save(ignore_permissions=True)
    return request


def record_acceptance(
    *,
    ai_service_request: str,
    subject_doctype: str,
    subject_name: str,
    target_fieldname: str,
    suggested_value: str,
    accepted_value: str,
    applied_to_version: str | None = None,
):
    """Record that a person took responsibility for machine-generated content."""
    if applied_to_version is None:
        current = versioning.current_version(subject_doctype, subject_name)
        applied_to_version = current.name if current else None
    return frappe.get_doc(
        {
            "doctype": "AI Suggestion Acceptance",
            "ai_service_request": ai_service_request,
            "subject_doctype": subject_doctype,
            "subject_name": subject_name,
            "target_fieldname": target_fieldname,
            "suggested_value": suggested_value,
            "accepted_value": accepted_value,
            "accepted_by": frappe.session.user,
            "accepted_on": now(),
            "edited_before_accept": 1 if suggested_value != accepted_value else 0,
            "applied_to_version": applied_to_version,
        }
    ).insert(ignore_permissions=True)

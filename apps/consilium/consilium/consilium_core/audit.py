"""Out-of-band audit of refusals.

A refused modification, deletion or disposal has to leave a record. The obvious
implementation — insert a row, then raise — does not work: the exception rolls
the transaction back and takes the audit row with it.

So the refusal log is written on a **second database connection**, which commits
independently of the transaction being refused. The write is best effort in the
sense that it must never mask the refusal itself: if the audit write fails, the
failure is logged and the refusal still propagates.
"""

from __future__ import annotations

import json

import frappe
from frappe.utils import now


def _open_side_connection():
    from frappe.database import get_db

    conf = frappe.conf
    db = get_db(
        socket=conf.get("db_socket"),
        host=conf.get("db_host"),
        user=conf.get("db_name"),
        password=conf.get("db_password"),
        port=conf.get("db_port"),
        cur_db_name=conf.get("db_name"),
    )
    db.connect()
    return db


def _next_name(db, series: str) -> str:
    current = db.sql(
        """INSERT INTO "tabSeries" ("name", "current") VALUES (%s, 1)
           ON CONFLICT ("name") DO UPDATE SET "current" = "tabSeries"."current" + 1
           RETURNING "current" """,
        (series,),
    )[0][0]
    return f"{series}{int(current):05d}"


def record_refusal(
    *,
    subject_doctype: str,
    subject_name: str,
    attempted_action: str,
    control: str,
    reason: str,
    retention_class: str | None = None,
    legal_hold: str | None = None,
    context: dict | None = None,
    user: str | None = None,
) -> str | None:
    """Write one ``Governance Refusal Log`` row and commit it independently."""
    user = user or frappe.session.user
    stamp = now()
    db = None
    try:
        db = _open_side_connection()
        name = _next_name(db, "GREF-")
        db.sql(
            """INSERT INTO "tabGovernance Refusal Log"
               ("name", "creation", "modified", "owner", "modified_by", "docstatus", "idx",
                "subject_doctype", "subject_name", "attempted_action", "control",
                "refusal_reason", "refused_on", "refused_for", "retention_class",
                "legal_hold", "context")
               VALUES (%s, %s, %s, %s, %s, 0, 0, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
            (
                name, stamp, stamp, user, user,
                subject_doctype, subject_name, attempted_action, control,
                reason, stamp, user, retention_class, legal_hold,
                json.dumps(context or {}),
            ),
        )
        db.commit()
        return name
    except Exception:
        frappe.log_error(
            title="Consilium: refusal could not be audited",
            message=frappe.get_traceback(with_context=True),
        )
        return None
    finally:
        if db is not None:
            try:
                db.close()
            except Exception:
                pass


def refuse(
    message: str,
    *,
    subject_doctype: str,
    subject_name: str,
    attempted_action: str,
    control: str,
    exc=frappe.PermissionError,
    **kwargs,
):
    """Audit a refusal and then raise it. The reason travels with the exception."""
    record_refusal(
        subject_doctype=subject_doctype,
        subject_name=subject_name,
        attempted_action=attempted_action,
        control=control,
        reason=message,
        **kwargs,
    )
    frappe.throw(message, exc=exc, title="Refused")

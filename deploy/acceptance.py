#!/usr/bin/env python3
"""Acceptance checks that need the framework, for deploy/kit.py verify.

    cd <install_dir>/sites
    ../env/bin/python ../deploy/acceptance.py --site <site> mint
    ../env/bin/python ../deploy/acceptance.py --site <site> workflow
    ../env/bin/python ../deploy/acceptance.py --site <site> pdf
    ../env/bin/python ../deploy/acceptance.py --site <site> scheduler
    ../env/bin/python ../deploy/acceptance.py --site <site> logout --sid <sid>

Each prints one JSON line. They are the milestone criteria from HANDOVER.md §6
turned into checks:

  mint       Phase 1's sign-in, without a password: a session is created on the
             server exactly as a sign-in creates one, and its id handed to the
             smoke test and the interface checks. The Administrator's password
             never has to be known to the verifier, or written anywhere.
  workflow   Phase 2, the governance primitives: a throwaway workflow on ToDo
             with two states and one gated transition; a document created in
             the first state, approved into the second; and the evidence the
             audit trail depends on — an open Workflow Action for the pending
             state, completed by the approval, and a Version row recording the
             change. Everything it creates is removed afterwards, including the
             workflow-state column the framework adds to ToDo.
  pdf        A governing document rendered to PDF through the framework's own
             print path (the PDF engine, the print format, the fonts), and the
             bytes checked to be a real PDF. An existing document is used when
             there is one; otherwise an unsaved one built in memory from the
             reference data, so the check writes nothing.
  scheduler  Whether the scheduler is enabled, and what it has run recently.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path


def connect(site: str, sites_path: str):
    import frappe

    frappe.init(site=site, sites_path=str(Path(sites_path).resolve()))
    frappe.connect()
    frappe.set_user("Administrator")
    return frappe


def fake_request(frappe, path: str = "/") -> None:
    """Some framework paths read the current request; give them an empty one
    from the loopback address, as a script has none of its own."""
    from werkzeug.test import EnvironBuilder
    from werkzeug.wrappers import Request

    frappe.local.request = Request(EnvironBuilder(path=path, base_url=f"http://{frappe.local.site}").get_environ())
    frappe.local.request_ip = "127.0.0.1"


def mint(frappe, user: str) -> dict:
    from frappe.sessions import Session

    fake_request(frappe)
    full_name, user_type = frappe.db.get_value("User", user, ["full_name", "user_type"])
    session = Session(user, resume=False, full_name=full_name, user_type=user_type)
    frappe.db.commit()
    return {"ok": True, "user": user, "sid": session.sid}


def logout(frappe, sid: str) -> dict:
    from frappe.sessions import delete_session

    delete_session(sid, reason="Acceptance check finished")
    frappe.db.commit()
    return {"ok": True}


def workflow(frappe) -> dict:
    """Phase 2 of HANDOVER.md §6, end to end, then cleaned up."""
    from frappe.model.workflow import apply_workflow

    tag = f"Readiness {frappe.generate_hash(length=6)}"
    pending, approved, action = f"{tag} Pending", f"{tag} Approved", f"{tag} Approve"
    created: list[tuple[str, str]] = []
    result: dict = {"ok": False, "workflow": tag}
    had_state_field = bool(frappe.db.exists("Custom Field", {"dt": "ToDo", "fieldname": "workflow_state"}))
    try:
        for state, style in ((pending, "Warning"), (approved, "Success")):
            frappe.get_doc({"doctype": "Workflow State", "workflow_state_name": state, "style": style}).insert()
            created.append(("Workflow State", state))
        frappe.get_doc({"doctype": "Workflow Action Master", "workflow_action_name": action}).insert()
        created.append(("Workflow Action Master", action))
        wf = frappe.get_doc({
            "doctype": "Workflow", "workflow_name": tag, "document_type": "ToDo", "is_active": 1,
            "workflow_state_field": "workflow_state", "send_email_alert": 0,
            "states": [
                {"state": pending, "doc_status": "0", "allow_edit": "System Manager"},
                {"state": approved, "doc_status": "0", "allow_edit": "System Manager"},
            ],
            "transitions": [
                {"state": pending, "action": action, "next_state": approved, "allowed": "System Manager",
                 "allow_self_approval": 1},
            ],
        }).insert()
        created.append(("Workflow", wf.name))
        frappe.db.commit()

        todo = frappe.get_doc({"doctype": "ToDo", "description": f"{tag}: acceptance check"}).insert()
        created.append(("ToDo", todo.name))
        frappe.db.commit()
        result["created_in_state"] = todo.workflow_state
        open_actions = frappe.get_all("Workflow Action", filters={"reference_doctype": "ToDo",
                                      "reference_name": todo.name, "status": "Open"}, pluck="name")
        result["open_workflow_actions_before"] = len(open_actions)

        todo = apply_workflow(todo, action)
        frappe.db.commit()
        todo.reload()
        result["state_after_approve"] = todo.workflow_state
        actions = frappe.get_all("Workflow Action", filters={"reference_doctype": "ToDo", "reference_name": todo.name},
                                 fields=["name", "status", "workflow_state", "completed_by"])
        result["workflow_actions"] = [dict(a) for a in actions]
        versions = frappe.get_all("Version", filters={"ref_doctype": "ToDo", "docname": todo.name},
                                  fields=["name", "data"])
        changed = [v for v in versions if "workflow_state" in (v.data or "")]
        result["version_rows"] = len(versions)
        result["version_records_state_change"] = bool(changed)
        result["ok"] = (
            result["created_in_state"] == pending
            and result["open_workflow_actions_before"] >= 1
            and todo.workflow_state == approved
            and any(a.status == "Completed" and a.completed_by == "Administrator" for a in actions)
            and bool(changed)
        )
    except Exception as e:  # noqa: BLE001 -- a check that crashes is a failure, reported
        frappe.db.rollback()
        result["error"] = f"{type(e).__name__}: {e}"
    finally:
        result["cleanup"] = cleanup(frappe, created, remove_state_field=not had_state_field)
    return result


def cleanup(frappe, created: list[tuple[str, str]], remove_state_field: bool) -> str:
    problems = []
    for doctype, name in reversed(created):
        try:
            if doctype == "ToDo":
                for table, field in (("Workflow Action", "reference_name"), ("Version", "docname"),
                                     ("Comment", "reference_name")):
                    frappe.db.delete(table, {field: name})
            frappe.delete_doc(doctype, name, force=True, ignore_permissions=True, delete_permanently=True)
        except Exception as e:  # noqa: BLE001
            problems.append(f"{doctype} {name}: {type(e).__name__}")
    if remove_state_field:
        field = frappe.db.get_value("Custom Field", {"dt": "ToDo", "fieldname": "workflow_state"})
        if field and not frappe.get_all("Workflow", filters={"document_type": "ToDo"}):
            try:
                frappe.delete_doc("Custom Field", field, force=True, ignore_permissions=True)
                if frappe.db.has_column("ToDo", "workflow_state"):
                    frappe.db.sql_ddl('alter table "tabToDo" drop column if exists "workflow_state"')
                frappe.clear_cache(doctype="ToDo")
            except Exception as e:  # noqa: BLE001
                problems.append(f"workflow_state column: {type(e).__name__}")
    frappe.db.commit()
    return "removed everything it created" if not problems else "left behind: " + "; ".join(problems)


def pdf(frappe) -> dict:
    from frappe.utils.pdf import get_wkhtmltopdf_version

    result: dict = {"ok": False}
    try:
        result["engine"] = get_wkhtmltopdf_version()
    except Exception as e:  # noqa: BLE001
        result["engine"] = f"not found: {e}"
    name = frappe.db.get_value("Governing Document", {}, "name", order_by="modified desc")
    fake_request(frappe, "/printview")
    started = time.time()
    try:
        if name:
            data = frappe.get_print("Governing Document", name, as_pdf=True)
            result["document"] = name
        else:
            doc = frappe.new_doc("Governing Document")
            doc.update({
                "document_name": "Acceptance check (not saved)",
                "document_type": frappe.db.get_value("Governing Document Type", {}, "name"),
                "lifecycle_phase": "Draft",
                "document_owner": "Administrator",
                "document_approver": "Administrator",
                "owning_operating_group": frappe.db.get_value("Organization Unit", {}, "name"),
                "primary_risk_category": frappe.db.get_value("Risk Category", {}, "name"),
                "handling_classification": "Internal",
            })
            doc.name = "GDOC-ACCEPTANCE"
            data = frappe.get_print("Governing Document", doc=doc, as_pdf=True)
            result["document"] = "an unsaved document built in memory (the site has none yet)"
        result["seconds"] = round(time.time() - started, 2)
        result["bytes"] = len(data)
        result["starts_with_pdf_header"] = data[:5] == b"%PDF-"
        result["ends_with_eof"] = b"%%EOF" in data[-1024:]
        result["pages"] = data.count(b"/Type /Page") - data.count(b"/Type /Pages")
        result["ok"] = result["starts_with_pdf_header"] and result["ends_with_eof"] and result["pages"] >= 1
    except Exception as e:  # noqa: BLE001
        result["error"] = f"{type(e).__name__}: {str(e)[:300]}"
    return result


def scheduler(frappe) -> dict:
    from frappe.utils import add_to_date, now_datetime
    from frappe.utils.scheduler import is_scheduler_disabled

    since = add_to_date(now_datetime(), hours=-24)
    jobs = frappe.get_all("Scheduled Job Type", filters={"method": ["like", "consilium.%"], "stopped": 0},
                          fields=["method", "frequency", "last_execution"])
    logs = frappe.get_all("Scheduled Job Log", filters={"creation": [">", since]},
                          fields=["scheduled_job_type", "status", "creation"], order_by="creation desc")
    by_status: dict = {}
    for row in logs:
        by_status[row.status] = by_status.get(row.status, 0) + 1
    last = max((j.last_execution for j in jobs if j.last_execution), default=None)
    return {
        "ok": True,
        "enabled": not is_scheduler_disabled(verbose=False),
        "consilium_jobs": len(jobs),
        "recent_runs": by_status,
        "last_run": str(last) if last else None,
        "jobs": {j.method.rsplit(".", 2)[-2] + "." + j.method.rsplit(".", 1)[-1]: str(j.last_execution or "")
                 for j in jobs},
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--site", required=True)
    parser.add_argument("--sites-path", default=".")
    sub = parser.add_subparsers(dest="check", required=True)
    p = sub.add_parser("mint")
    p.add_argument("--user", default="Administrator")
    p = sub.add_parser("logout")
    p.add_argument("--sid", required=True)
    sub.add_parser("workflow")
    sub.add_parser("pdf")
    sub.add_parser("scheduler")
    args = parser.parse_args()

    frappe = connect(args.site, args.sites_path)
    try:
        if args.check == "mint":
            out = mint(frappe, args.user)
        elif args.check == "logout":
            out = logout(frappe, args.sid)
        elif args.check == "workflow":
            out = workflow(frappe)
        elif args.check == "pdf":
            out = pdf(frappe)
        else:
            out = scheduler(frappe)
    finally:
        frappe.destroy()
    print(json.dumps(out, default=str))
    return 0 if out.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())

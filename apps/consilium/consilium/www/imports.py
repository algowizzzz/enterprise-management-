"""Context for the import batch review screen (CS-11).

One screen, two views: the list of batches with an upload form, and — when the
address names a batch — that batch's rows with their validation outcome and the
reviewer's decisions. Everything is read and done through the governed
pipeline's endpoints in `consilium_core.importing`, which apply the Import Batch
permissions again on every call; this module only decides which view to draw
and whether to offer the upload form.
"""

import frappe

no_cache = 1


def get_context(context):
	context.no_cache = 1
	batch = (frappe.form_dict.get("batch") or "").strip()
	context.batch_name = batch
	context.page_title = f"Import batch {batch}" if batch else "Imports"
	context.page_description = (
		"Every row as the file gave it, what the profile made of it, and why any row was refused. "
		"Nothing is written until you commit."
		if batch
		else "Files brought in through the governed import pipeline. Upload a file against a profile, "
		"review its rows, then commit or discard it."
	)
	context.active_nav = "admin"
	context.user_display = frappe.session.user
	crumbs = [{"label": "Home", "url": "/"}, {"label": "Administration", "url": "/admin"}]
	if batch:
		crumbs += [{"label": "Imports", "url": "/imports"}, {"label": batch}]
	else:
		crumbs.append({"label": "Imports"})
	context.breadcrumbs = crumbs
	signed_in = frappe.session.user != "Guest"
	context.can_read = signed_in and bool(frappe.has_permission("Import Batch", "read"))
	context.can_upload = signed_in and bool(frappe.has_permission("Import Batch", "create"))
	context.found = bool(batch and frappe.db.exists("Import Batch", batch))
	return context

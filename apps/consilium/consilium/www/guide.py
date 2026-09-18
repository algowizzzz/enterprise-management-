"""Context for the guide reader (/guide).

The onboarding guide, chapter by chapter, inside the platform. Everything is
worked out in ``consilium.consilium_core.guide``: which chapters the viewer may
read, the chapter rendered and cleaned, its sections, and the search. This page
only arranges it.

The address carries ``?chapter=`` and ``?q=``. A chapter value is only ever
compared against the real list of chapters (an unknown one is a 404, the
administrators' chapter a 403 for anyone else), and the search text is printed
escaped; neither is used to build a path.
"""

import frappe

from consilium.consilium_core import guide

no_cache = 1


def get_context(context):
	context.no_cache = 1
	context.active_nav = "home"
	context.title = "Guide"
	context.breadcrumbs = [{"label": "Home", "url": "/"}, {"label": "Guide"}]
	context.guide = None
	if frappe.session.user == "Guest":
		# The shell shows the sign-in card; nothing about the guide is read.
		return context

	form = frappe.form_dict
	chapter = form.get("chapter")
	query = form.get("q")
	data = guide.page(
		chapter if isinstance(chapter, str) and chapter.strip() else None,
		query if isinstance(query, str) else None,
	)
	context.guide = data
	context.title = data["title"]
	if data["current_admin"]:
		context.active_nav = "admin"
	if data["results"] is not None:
		context.breadcrumbs = [
			{"label": "Home", "url": "/"},
			{"label": "Guide", "url": "/guide"},
			{"label": "Search"},
		]
	elif data["current"] != guide.INDEX:
		context.breadcrumbs = [
			{"label": "Home", "url": "/"},
			{"label": "Guide", "url": "/guide"},
			{"label": data["title"]},
		]
	return context

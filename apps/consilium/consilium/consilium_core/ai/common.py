"""Small helpers every analysis shares: permitted reads, links, dates.

Every read an analysis makes about records goes through ``readable()``, which
is the framework's permitted query (``frappe.get_list``). A role that cannot
read a DocType sees an empty list rather than an error, because an analysis
page is read by many roles and each should get the part it may see; the page
says that the figures are "over records you may read".
"""

from __future__ import annotations

import frappe
from frappe.utils import add_months, get_first_day, getdate, nowdate

#: The value list for an ``in`` filter over nothing. Not ``[""]``: the framework
#: reads ``in ("")`` as "is empty", which matches every row with the field unset.
NONE = ["__consilium_no_match__"]

PAGES = {
	"Governing Document": "/policy?name=",
	"Governance Forum": "/forum?name=",
	"Escalation Matter": "/escalation?name=",
	"Regulatory Requirement": "/regulatory-updates?requirement=",
}


def href(doctype: str, name: str) -> str | None:
	base = PAGES.get(doctype)
	return base + frappe.utils.quote(name, safe="") if base and name else None


def can_read(doctype: str) -> bool:
	return frappe.session.user != "Guest" and bool(frappe.has_permission(doctype, "read"))


def readable(doctype: str, *, filters=None, fields=None, or_filters=None, order_by=None, limit=0,
             pluck=None) -> list:
	"""``frappe.get_list`` for the session user; ``[]`` if the DocType is
	missing or unreadable. ``limit=0`` means no limit."""
	if not frappe.db.exists("DocType", doctype) or not can_read(doctype):
		return []
	try:
		return frappe.get_list(
			doctype, filters=filters or {}, or_filters=or_filters, fields=fields or ["name"],
			order_by=order_by, limit_page_length=limit or 0, pluck=pluck,
		)
	except frappe.PermissionError:
		return []


def require_signed_in() -> None:
	if frappe.session.user == "Guest":
		frappe.throw(frappe._("Sign in to use the governance analysis."), frappe.PermissionError)


def today():
	return getdate(nowdate())


def month_key(value) -> str | None:
	if not value:
		return None
	d = getdate(value)
	return f"{d.year:04d}-{d.month:02d}"


def month_keys(months: int, end=None) -> list[str]:
	"""The last ``months`` calendar months, oldest first, ending with ``end``'s month."""
	end = get_first_day(getdate(end or nowdate()))
	return [month_key(add_months(end, -i)) for i in range(months - 1, -1, -1)]


def as_int(value, default: int = 0) -> int:
	try:
		return int(value)
	except (TypeError, ValueError):
		return default


def loads(value, default=None):
	import json

	if not value:
		return default
	if isinstance(value, dict | list):
		return value
	try:
		return json.loads(value)
	except ValueError:
		return default

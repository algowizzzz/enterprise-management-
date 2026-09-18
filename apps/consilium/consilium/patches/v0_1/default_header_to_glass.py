"""Move sites on the old default header to the new one, Glass.

The portal's look changed (theme-hybrid.css), and its header with it: the new
default is a frosted light header the page scrolls under, and the old default,
a bar in the brand colour, became one of three choices.

A single-record DocType stores every field when it is saved, so a site that
never touched Header Style holds "Primary colour" exactly as one that chose it
deliberately; the two cannot be told apart. The patch treats the stored value
as the old default and moves it to the new one, because that is what almost
every site has, and the look the product ships should be the look a site gets.
The trade-off is that a site which had deliberately chosen the coloured bar
loses that choice once; an administrator restores it by picking "Primary
colour" again in Portal Branding, and this patch never runs a second time.
"White" is always a deliberate choice (it was never the default) and is left
alone.
"""

import frappe


def execute():
	if not frappe.db.exists("DocType", "Portal Branding"):
		return
	if frappe.db.get_single_value("Portal Branding", "header_style") in (None, "", "Primary colour"):
		frappe.db.set_single_value("Portal Branding", "header_style", "Glass")
		frappe.cache.delete_value("consilium:portal_branding")
		frappe.clear_document_cache("Portal Branding", "Portal Branding")

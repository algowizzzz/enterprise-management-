"""Rename Assistant Settings' "OpenAI-compatible (internal gateway)" format.

The option was named for the case it was written for, a gateway an
organisation runs in front of a model. Hosted providers speak the same
chat-completions format, and an administrator configuring one read the old
label as "not for me". The option is now "OpenAI-compatible API".

A Select stores its label, so a site that chose the old option holds the old
string. The client treats anything other than the Messages API as this format,
so nothing breaks before this runs; it runs so the desk form and the
integrations page show the option that is actually selected, and so a save
does not fail the Select's option check.
"""

import frappe

from consilium.consilium_core.ai import client


def execute():
	current = frappe.db.get_single_value("Assistant Settings", "provider")
	if current == client.LEGACY_OPENAI_COMPATIBLE:
		frappe.db.set_single_value("Assistant Settings", "provider", client.OPENAI_COMPATIBLE)

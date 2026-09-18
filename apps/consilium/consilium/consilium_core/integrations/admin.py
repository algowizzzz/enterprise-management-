"""The Integrations page's endpoints (``/integrations``).

One card per integration — the AI endpoint, Doc AI, horizon scanning and
email — each with a status, its settings and a Save button. This module reads
and writes the settings records behind those cards; it adds no settings of its
own. The records are the same ones the desk shows (Assistant Settings, External
Tools Settings, Email Delivery Settings), so an administrator can use either
screen and see the same values.

Rules every endpoint here keeps:

* **Administrators only.** Consilium Administrator or System Manager, checked
  on the way in, and a refusal is audited like every other refusal. The
  records' own permissions are then applied again by ``save()``.
* **Secrets are write-only.** An API key or client secret can be set or
  removed, never read back: the page is told only whether one is saved.
* **Only named fields are written.** Each card lists the fields it may set, so
  a crafted request cannot reach a field the page does not show.
* **Nothing is tested on unsaved values.** "Test connection" and "Send a test
  email" use what is saved, so what was tested is what runs.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import cint, now_datetime

from consilium.consilium_core import state_flags
from consilium.consilium_core.ai import client
from consilium.consilium_core.integrations import external_tools, graph_mail

AI = "Assistant Settings"
TOOLS = external_tools.SETTINGS
EMAIL = graph_mail.SETTINGS

CONNECTED, NOT_CONNECTED, OFF = external_tools.CONNECTED, external_tools.NOT_CONNECTED, external_tools.OFF

#: The capability a connection test is recorded under in AI Service Request.
TEST_CAPABILITY = "Connection test"

AI_CHECKS = ("ai_enabled", "features_enabled", "ai_policy_impact", "ai_governance_gaps",
             "ai_regulatory_updates", "ai_emerging_risks", "ai_risk_assessment")
AI_INTS = ("timeout_seconds", "max_tokens", "feature_max_tokens")
AI_TEXT = ("provider", "endpoint_url", "model", "data_sharing", "classification_ceiling")

SECTIONS = {
	"ai": {"doctype": AI, "checks": AI_CHECKS, "ints": AI_INTS, "text": AI_TEXT, "secret": "api_key"},
	"doc_ai": {"doctype": TOOLS, "checks": ("doc_ai_enabled", "doc_ai_new_tab"), "ints": (),
	           "text": ("doc_ai_label", "doc_ai_url_template"), "secret": None},
	"horizon": {"doctype": TOOLS, "checks": ("horizon_enabled", "horizon_new_tab"), "ints": (),
	            "text": ("horizon_label", "horizon_url"), "secret": None},
	"email": {"doctype": EMAIL, "checks": (), "ints": ("graph_timeout_seconds",),
	          "text": ("delivery_route", "graph_tenant_id", "graph_client_id", "graph_sender",
	                   "graph_authority_url", "graph_api_url"),
	          "secret": "graph_client_secret"},
}

#: Roles a Doc AI role list may not name: every signed-in person holds them,
#: so listing one would look like a restriction and be none.
UNLISTABLE_ROLES = ("All", "Guest", "Desk User", "Administrator")

#: The modules whose record types say which roles are this platform's own.
APP_MODULES = ("Consilium Core", "Governance", "Policy", "Escalation")

#: Offered alongside the platform's roles: the framework's administrator role,
#: which holds every right here and is a role administrators expect to see.
ALSO_OFFERED = ("System Manager",)


# ------------------------------------------------------------------ access


def require_admin(subject_doctype: str, attempted_action: str = "Other") -> None:
	"""Refuse (audited) anyone but an administrator."""
	if frappe.session.user == "Guest":
		raise frappe.PermissionError(_("Sign in to manage integrations."))
	if external_tools.is_admin():
		return
	from consilium.consilium_core import audit

	audit.refuse(
		_("Integrations are managed by administrators. Ask the governance office if a connection needs changing."),
		subject_doctype=subject_doctype,
		subject_name=subject_doctype,
		attempted_action=attempted_action,
		control="integrations administration",
		exc=frappe.PermissionError,
	)


# ------------------------------------------------------------------- state


def _has_secret(doctype: str, fieldname: str) -> bool:
	from frappe.utils.password import get_decrypted_password

	return bool(get_decrypted_password(doctype, doctype, fieldname, raise_exception=False))


def _options(doctype: str, fieldname: str) -> list[str]:
	field = frappe.get_meta(doctype).get_field(fieldname)
	return [o for o in (field.options or "").split("\n") if o] if field else []


def _last_test() -> dict | None:
	"""The most recent "Test connection", with its outcome and time.

	Every test is kept as an AI Service Request (capability "Connection test"),
	like every other request to the AI service, so the card remembers the last
	test across sessions and servers without a setting of its own, and the
	record it reads is the audited one.
	"""
	row = frappe.get_all(
		"AI Service Request",
		filters={"capability": TEST_CAPABILITY},
		fields=["name", "status", "requested_on", "duration_ms", "error_detail", "requested_by"],
		order_by="creation desc",
		limit=1,
	)
	if not row:
		return None
	row = row[0]
	# The request's own status vocabulary (Sent, Succeeded, Failed, ...) is a
	# configuration value, not a workflow state; ``ok`` says what it means.
	return {"status": row.status, "ok": row.status == "Succeeded", "when": str(row.requested_on or ""),
	        "duration_ms": row.duration_ms, "error": row.error_detail, "by": row.requested_by,
	        "reference": row.name}


def ai_card() -> dict:
	s = frappe.get_single(AI)
	on = bool(cint(s.ai_enabled) or cint(s.features_enabled))
	configured = client.is_configured(s)
	has_key = _has_secret(AI, "api_key")
	status = OFF if not on else (CONNECTED if configured else NOT_CONNECTED)
	warnings = []
	if on and not has_key:
		warnings.append(_("A switch is on but no API key is saved. Most hosted providers refuse every request "
		                  "without one, and the built-in answers are shown instead. Paste the key and save. "
		                  "(A gateway that authenticates this server another way needs no key.)"))
	if on and not configured:
		warnings.append(_("A switch is on but the endpoint address or the model is missing."))
	return {
		"status": status,
		"has_key": has_key,
		"warnings": warnings,
		"values": {field: s.get(field) for field in AI_CHECKS + AI_INTS + AI_TEXT},
		"options": {field: _options(AI, field) for field in ("provider", "data_sharing", "classification_ceiling")},
		"request_url": client.endpoint_url(s) if (s.endpoint_url or "").strip() else "",
		"last_test": _last_test(),
	}


def platform_roles() -> list[str]:
	"""The roles this platform itself uses, plus System Manager.

	"Who sees the button" used to list every role on the site, which includes
	the framework's own roles for features this platform does not use (a
	blogger, an accounts manager, a website manager). Ticking one of those
	restricted nothing meaningful and made the list hard to read. A role is the
	platform's own when a permission rule on one of its record types names it,
	which is also what makes the role mean anything here.
	"""
	doctypes = frappe.get_all("DocType", filters={"module": ["in", APP_MODULES]}, pluck="name")
	names = set(ALSO_OFFERED)
	if doctypes:
		for table in ("DocPerm", "Custom DocPerm"):
			names.update(frappe.get_all(table, filters={"parent": ["in", doctypes]}, pluck="role", distinct=True))
	names.difference_update(UNLISTABLE_ROLES)
	return sorted(frappe.get_all("Role", filters={"disabled": 0, "name": ["in", sorted(names) or [""]]},
	                             pluck="name"))


def _roles_offered(current: list[str] | None = None) -> list[str]:
	"""The platform's roles, and any role already chosen (so saving the card
	never silently drops a choice an administrator made before)."""
	offered = set(platform_roles())
	offered.update(role for role in (current or []) if role not in UNLISTABLE_ROLES)
	return sorted(offered)


def doc_ai_card() -> dict:
	s = frappe.get_single(TOOLS)
	return {
		"status": external_tools.doc_ai_state(s),
		"values": {field: s.get(field) for field in SECTIONS["doc_ai"]["checks"] + SECTIONS["doc_ai"]["text"]},
		"roles": external_tools.doc_ai_roles(s),
		"roles_offered": _roles_offered(external_tools.doc_ai_roles(s)),
		"placeholders": list(external_tools.PLACEHOLDERS),
	}


def horizon_card() -> dict:
	s = frappe.get_single(TOOLS)
	return {
		"status": external_tools.horizon_state(s),
		"values": {field: s.get(field) for field in SECTIONS["horizon"]["checks"] + SECTIONS["horizon"]["text"]},
	}


def _smtp_account() -> dict | None:
	"""The outgoing Email Account the framework's queue would use, read-only."""
	rows = frappe.get_all(
		"Email Account",
		filters={"enable_outgoing": 1},
		fields=["name", "email_id", "smtp_server", "smtp_port", "use_tls", "use_ssl_for_outgoing",
		        "login_id", "login_id_is_different", "no_smtp_authentication", "default_outgoing"],
		order_by="default_outgoing desc, modified desc",
		limit=1,
	)
	if not rows:
		return None
	row = rows[0]
	security = "SSL" if cint(row.use_ssl_for_outgoing) else ("STARTTLS" if cint(row.use_tls) else _("None"))
	if cint(row.no_smtp_authentication):
		login = _("None (the relay accepts this server without signing in)")
	else:
		login = (row.login_id if cint(row.login_id_is_different) and row.login_id else row.email_id) or ""
	return {
		"name": row.name,
		"sender": row.email_id,
		"host": row.smtp_server,
		"port": row.smtp_port,
		"security": security,
		"login": login,
		"is_default": bool(cint(row.default_outgoing)),
		"edit_url": "/app/email-account/" + frappe.utils.quote(row.name),
	}


def _email_channel():
	from consilium.consilium_core.setup.notification_templates import DEFAULT_TEMPLATE_CHANNEL

	if not frappe.db.exists("Notification Channel", DEFAULT_TEMPLATE_CHANNEL):
		return None
	return frappe.get_doc("Notification Channel", DEFAULT_TEMPLATE_CHANNEL)


def email_card() -> dict:
	s = frappe.get_single(EMAIL)
	route = s.delivery_route or graph_mail.SMTP_ROUTE
	channel = _email_channel()
	smtp = _smtp_account()
	absent = graph_mail.missing(s)
	if channel is None or not cint(channel.is_active):
		status = OFF
	elif route == graph_mail.GRAPH_ROUTE:
		status = NOT_CONNECTED if absent else CONNECTED
	else:
		status = CONNECTED if smtp else NOT_CONNECTED
	values = {field: s.get(field) for field in SECTIONS["email"]["ints"] + SECTIONS["email"]["text"]}
	return {
		"status": status,
		"route": route,
		"route_label": graph_mail.route_label(route),
		"routes": _options(EMAIL, "delivery_route"),
		"route_labels": {option: graph_mail.route_label(option) for option in _options(EMAIL, "delivery_route")},
		"graph_route": graph_mail.GRAPH_ROUTE,
		"values": values,
		"has_secret": _has_secret(EMAIL, "graph_client_secret"),
		"graph_missing": absent,
		"smtp": smtp,
		"new_account_url": "/app/email-account/new",
		"channel_active": bool(channel and cint(channel.is_active)),
		"muted": bool(frappe.are_emails_muted()),
	}


#: Where the framework sends a person back after signing in at an OpenID
#: Connect provider added as "Custom" — frappe.integrations.oauth2_logins.custom,
#: which reads the provider from the last path segment. The deployment kit
#: stores exactly this on the Social Login Key it creates (configure_site.py).
OIDC_CALLBACK = "/api/method/frappe.integrations.oauth2_logins.custom/{0}"
#: The kit's default [sso] oidc_provider_name.
KIT_DEFAULT_PROVIDER = "Corporate SSO"


def _redirect_uri(key: str, stored: str | None) -> str:
	"""The exact redirect URI the identity provider must have registered.

	The framework's own rule (``frappe.utils.oauth.get_redirect_uri``): a
	``<provider>_login.redirect_uri`` in the site configuration wins; otherwise
	the provider's stored redirect address, made absolute with this site's URL.
	"""
	keys = frappe.conf.get(f"{key}_login")
	if isinstance(keys, dict) and keys.get("redirect_uri"):
		return keys["redirect_uri"]
	return frappe.utils.get_url(stored or OIDC_CALLBACK.format(key))


def sso_card() -> dict:
	"""Single sign-on, read only. Switched on and off in the deployment config.

	Why read only: a wrong provider address or client secret saved from a web
	page would lock everyone out, including the administrator who saved it,
	with no page left to put it right from. The deployment configuration is
	applied by the installer, checked before it is applied, and reverted the
	same way.
	"""
	providers = []
	for row in frappe.get_all(
		"Social Login Key",
		# Providers an administrator added (the kit adds one as Custom), and
		# any built-in one that someone switched on.
		or_filters=[["social_login_provider", "=", "Custom"], ["enable_social_login", "=", 1]],
		fields=["name", "provider_name", "enable_social_login", "social_login_provider", "base_url",
		        "authorize_url", "redirect_url", "sign_ups", "client_id"],
		order_by="enable_social_login desc, modified desc",
	) if frappe.db.table_exists("Social Login Key") else []:
		linked = frappe.db.sql(
			"""SELECT COUNT(*), MAX("creation") FROM "tabUser Social Login"
			   WHERE "provider" = %s AND "parenttype" = 'User'""",
			(row.name,),
		)[0]
		providers.append({
			"key": row.name,
			"name": row.provider_name or row.name,
			"enabled": bool(cint(row.enable_social_login)),
			"kind": row.social_login_provider,
			"issuer": row.base_url or "",
			"authorize_url": row.authorize_url or "",
			"redirect_uri": _redirect_uri(row.name, row.redirect_url),
			"sign_ups": row.sign_ups or "",
			"client_id": row.client_id or "",
			"people_linked": int(linked[0] or 0),
			"last_linked": str(linked[1] or ""),
		})
	ldap = None
	if frappe.db.exists("DocType", "LDAP Settings"):
		l = frappe.get_single("LDAP Settings")
		if cint(l.enabled) or (l.ldap_server_url or "").strip():
			ldap = {
				"enabled": bool(cint(l.enabled)),
				"server": l.ldap_server_url or "",
				"directory": l.ldap_directory_server or "",
				"bind_dn": l.base_dn or "",
				"user_search": l.ldap_search_path_user or "",
				"tls": l.ssl_tls_mode or "",
				"creates_accounts": not cint(l.do_not_create_new_user),
			}
	enabled = any(p["enabled"] for p in providers) or bool(ldap and ldap["enabled"])
	default_key = frappe.scrub(KIT_DEFAULT_PROVIDER)
	return {
		"status": CONNECTED if enabled else OFF,
		"providers": providers,
		"ldap": ldap,
		"expected_redirect_uri": _redirect_uri(default_key, None),
		"default_provider": KIT_DEFAULT_PROVIDER,
		"default_key": default_key,
	}


@frappe.whitelist(methods=["GET"])
def state() -> dict:
	"""Every card's status and saved values. Secrets are never included."""
	require_admin(TOOLS)
	return {"ai": ai_card(), "doc_ai": doc_ai_card(), "horizon": horizon_card(), "email": email_card(),
	        "sso": sso_card()}


# -------------------------------------------------------------------- save


def _card(section: str) -> dict:
	return {"ai": ai_card, "doc_ai": doc_ai_card, "horizon": horizon_card, "email": email_card}[section]()


@frappe.whitelist(methods=["POST"])
def save(section: str, values=None) -> dict:
	"""Save one card. Returns the card's fresh state.

	``values`` holds the card's fields. A secret field is written only when a
	new value is given; ``clear_<field>`` removes the saved one.
	"""
	spec = SECTIONS.get(section)
	if not spec:
		frappe.throw(_("There is no integration called {0}.").format(section))
	require_admin(spec["doctype"], "Modify")
	values = frappe.parse_json(values) if values else {}
	if not isinstance(values, dict):
		frappe.throw(_("Send the card's values as an object."))

	doc = frappe.get_single(spec["doctype"])
	for field in spec["checks"]:
		if field in values:
			doc.set(field, 1 if cint(values[field]) else 0)
	for field in spec["ints"]:
		if field in values:
			doc.set(field, cint(values[field]))
	for field in spec["text"]:
		if field in values:
			doc.set(field, (str(values[field]) if values[field] is not None else "").strip())
	secret = spec["secret"]
	if secret:
		new = (values.get(secret) or "").strip() if isinstance(values.get(secret), str) else ""
		if new:
			doc.set(secret, new)
		elif cint(values.get("clear_" + secret)):
			doc.set(secret, None)
	if section == "doc_ai" and "doc_ai_roles" in values:
		wanted = [r for r in (values.get("doc_ai_roles") or []) if isinstance(r, str)]
		offered = set(_roles_offered(external_tools.doc_ai_roles(doc)))
		doc.set("doc_ai_roles", [{"role": role} for role in sorted(set(wanted)) if role in offered])
	doc.save()
	frappe.clear_document_cache(spec["doctype"], spec["doctype"])
	return _card(section)


# -------------------------------------------------------------------- tests


@frappe.whitelist(methods=["POST"])
def test_ai_connection() -> dict:
	"""Send one tiny request through the audited AI client and report the outcome.

	Uses the saved settings whether or not either switch is on, so an
	administrator can prove the connection before turning anything on. The
	request is recorded as an AI Service Request like any other; nothing about
	any record is in it. The configured maximum length is used rather than a
	small one: a model that reasons before answering spends part of it on
	reasoning, and a test that starves it would fail a working connection.
	"""
	require_admin(AI)
	s = frappe.get_single(AI)
	if not client.is_configured(s):
		return {"ok": False, "status": "Not Configured",
		        "message": _("Enter the endpoint address and the model, and save, before testing.")}
	result = client.audited(
		s,
		capability=TEST_CAPABILITY,
		system="This is an automated connection test. Reply with the single word OK.",
		user_text="Connection test from the platform's Integrations page. Reply with OK.",
		classification="Public",
		max_tokens=int(s.max_tokens or 800),
	)
	ok = result["status"] == "Succeeded"
	if ok:
		message = _("Connected: {0} answered in {1} ms.").format(s.model, result["duration_ms"])
	else:
		message = _("{0}: {1}").format(result["status"], result["error"] or _("no usable answer"))
	return {
		"ok": ok,
		"status": result["status"],
		"latency_ms": result["duration_ms"],
		"error": result["error"],
		"reply": (result["text"] or "")[:200],
		"message": message,
		"service_request": result["service_request"],
		"request_url": client.endpoint_url(s),
		"card": ai_card(),
	}


@frappe.whitelist(methods=["POST"])
def send_test_email() -> dict:
	"""Send a test email to the administrator asking, through the chosen route, now.

	It goes through the notification layer like any notification, so it
	leaves a Notification Dispatch saying whether it was sent — the same
	evidence a real notification leaves — and exercises the same checks.
	"""
	from consilium.consilium_core import notification
	from consilium.consilium_core.branding import get_brand

	require_admin(EMAIL)
	user = frappe.session.user
	address = frappe.db.get_value("User", user, "email")
	route = graph_mail.route()
	base = {"ok": False, "route": route, "to": address}
	channel = _email_channel()
	if channel is None or not cint(channel.is_active):
		return dict(base, message=_("The email notification channel is switched off, so no email is sent."))
	unavailable = notification._email_available(channel)
	if unavailable:
		return dict(base, message=unavailable)
	refusal = notification._email_refusal(user, channel)
	if refusal:
		return dict(base, message=refusal)

	portal = get_brand().get("portal_name") or "the portal"
	subject = _("Test email from {0}").format(portal)
	body = _("This is a test email, sent from the Integrations page by {0} at {1} through {2}.\n\n"
	         "If you are reading it, notification email reaches you. No action is needed.").format(
		frappe.utils.get_fullname(user), now_datetime().strftime("%Y-%m-%d %H:%M"), graph_mail.route_label(route))
	previous = frappe.flags.cns_mail_inline
	frappe.flags.cns_mail_inline = True
	try:
		row = notification.dispatch(channel.name, user, subject=subject, body=body,
		                            subject_doctype="User", subject_name=user)
	finally:
		frappe.flags.cns_mail_inline = previous
	if row.channel != channel.name and row.fallback_of:
		row = frappe.get_doc("Notification Dispatch", row.fallback_of)
	# Delivered is a closed dispatch that needs no review — read from the
	# status's flags, never its name, like every other status in the platform.
	flags = state_flags.flags_for("Notification Dispatch", "status", row.status) or {}
	ok = row.channel == channel.name and bool(flags) and not flags.get("is_open") and not flags.get("requires_review")
	if ok and route != graph_mail.GRAPH_ROUTE and frappe.are_emails_muted():
		message = _("Queued, but email is muted on this site, so nothing left the server.")
		ok = False
	elif ok:
		message = _("Sent to {0} through {1}. Check that inbox.").format(address, graph_mail.route_label(route))
	else:
		message = row.failure_reason or _("The message was not sent.")
	return dict(base, ok=ok, message=message, dispatch=row.name, status=row.status)

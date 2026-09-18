"""What may leave the platform for an analysis feature, and whether to ask at all.

Every analysis feature computes its result from the data first, with no model
(CLAUDE.md rule 5: the platform must be useful with no internet access). The
model is an optional second pass, and this module is the gate in front of it.
The gate has four questions, asked in this order:

1. **Is AI on for this capability?** ``Assistant Settings`` has one switch for
   the analysis features (independent of the help assistant's), one toggle per
   capability, and needs an endpoint and a model to be named.
2. **May this person spend a request?** Only the governance, policy and risk
   offices and administrators may ask (``ANALYST_ROLES``), within the same
   hourly limit the help assistant uses, counted over the ``AI Service
   Request`` rows they caused.
3. **May the subject leave?** A record classified above the configured
   ceiling — and anything Restricted, and any sensitive escalation, whatever
   the ceiling — is never sent. If the *subject* of an analysis is such a
   record, the analysis is not sent at all and the refusal is recorded; other
   records above the ceiling are simply left out of the payload, and the page
   says how many.
4. **How much of each record?** The data-sharing mode decides. In *Guidance
   only* a record is sent as an opaque token (``D-3f9a2c1b``) with its
   taxonomy (type, risk category, jurisdiction), never its title or any of its
   text. In *Include visible record summary* the titles and short summaries of
   records the person may read are sent as well. Either way the model refers to
   records by token and the platform maps tokens back to links locally, so a
   suggestion is actionable even when the model never saw a title.

Tokens are a keyed hash of the record's name under the site's encryption key:
stable (a suggestion made yesterday still resolves today, with nothing stored),
one-way (the endpoint cannot recover the name), and site-specific.
"""

from __future__ import annotations

import hashlib
import hmac
import re

import frappe
from frappe import _

from consilium.consilium_core.ai import client

SETTINGS = "Assistant Settings"
GUIDANCE_MODE = "Guidance only"
SUMMARY_MODE = "Include visible record summary"

PUBLIC, INTERNAL, CONFIDENTIAL, RESTRICTED = "Public", "Internal", "Confidential", "Restricted"
CLASS_RANK = {PUBLIC: 0, INTERNAL: 1, CONFIDENTIAL: 2, RESTRICTED: 3}

#: capability key -> (settings toggle, the name recorded on AI Service Request)
CAPABILITIES = {
	"impact": ("ai_policy_impact", "Policy-change impact assessment"),
	"gaps": ("ai_governance_gaps", "Governance gap commentary"),
	"regulatory": ("ai_regulatory_updates", "Regulatory update suggestions"),
	"trends": ("ai_emerging_risks", "Emerging-risk narrative"),
	"scores": ("ai_risk_assessment", "Governance risk rationale"),
}

#: Who may cause an outbound request. A paid endpoint is spent on behalf of the
#: offices that act on the analysis; everyone else still sees the rule-based
#: result, which is the whole of the feature without AI.
ANALYST_ROLES = (
	"System Manager", "Consilium Administrator", "Risk Governance Office", "Head of Risk Governance",
	"Enterprise Policy Office", "Compliance Reviewer", "Policy Owner", "Taxonomy Administrator",
)

TOKEN_PREFIX = {
	"Governing Document": "D",
	"Governance Forum": "F",
	"Escalation Matter": "E",
	"Policy Violation": "V",
	"Monitoring Activity": "M",
	"Organization Unit": "U",
}
TOKEN_PATTERN = re.compile(r"\b([A-Z])-([0-9a-f]{8})\b")


def settings():
	"""The settings, or a stand-in with AI off when the DocType is not migrated."""
	if frappe.db.exists("DocType", SETTINGS):
		return frappe.get_cached_doc(SETTINGS)
	return frappe._dict(ai_enabled=0, features_enabled=0, data_sharing=GUIDANCE_MODE,
	                    classification_ceiling=INTERNAL, rate_limit_per_hour=30)


def capability_name(key: str) -> str:
	return CAPABILITIES[key][1]


# -------------------------------------------------------------- availability


def availability(key: str, cfg=None) -> dict:
	"""Whether a person could ask the endpoint for this capability now.

	``{"available": bool, "reason": str | None, "mode": str}``. The reason is
	worded for the page, which always shows the rule-based result regardless.
	"""
	cfg = cfg or settings()
	mode = cfg.get("data_sharing") or GUIDANCE_MODE
	toggle = CAPABILITIES[key][0]
	if not int(cfg.get("features_enabled") or 0):
		return {"available": False, "reason": _("AI is not switched on for the analysis features."), "mode": mode}
	if not int(cfg.get(toggle) if cfg.get(toggle) is not None else 1):
		return {"available": False, "reason": _("AI is switched off for this analysis."), "mode": mode}
	if not client.is_configured(cfg):
		return {"available": False, "reason": _("No AI endpoint is configured."), "mode": mode}
	if not may_request():
		return {"available": False, "reason": _("Your role may not send analyses to the AI service."), "mode": mode}
	return {"available": True, "reason": None, "mode": mode}


def may_request(user: str | None = None) -> bool:
	user = user or frappe.session.user
	if user == "Guest":
		return False
	return user == "Administrator" or bool(set(frappe.get_roles(user)) & set(ANALYST_ROLES))


def check_rate(cfg=None) -> None:
	"""One hourly limit for everything a person sends out, help questions included."""
	cfg = cfg or settings()
	limit = int(cfg.get("rate_limit_per_hour") or 30)
	since = frappe.utils.add_to_date(frappe.utils.now_datetime(), hours=-1)
	used = frappe.db.count(client.SERVICE_REQUEST, {"requested_by": frappe.session.user, "requested_on": [">", since]})
	if used >= limit:
		frappe.throw(
			_("You have sent {0} requests to the AI service in the last hour, which is the limit. "
			  "The rule-based result is unaffected.").format(used),
			frappe.TooManyRequestsError, title=_("AI Limit Reached"),
		)


# ------------------------------------------------------------ classification


def ceiling(cfg=None) -> str:
	value = (cfg or settings()).get("classification_ceiling") or INTERNAL
	# Restricted is never a permitted ceiling, whatever was stored.
	return value if value in (PUBLIC, INTERNAL, CONFIDENTIAL) else INTERNAL


def classification_of(doctype: str, row) -> str:
	"""The handling class of a record, for the purpose of sending it out.

	A sensitive escalation (or anything that inherits the flag) counts as
	Restricted: it never leaves, which is what E-16 asks of it everywhere else.
	"""
	get = row.get if hasattr(row, "get") else (lambda k, d=None: getattr(row, k, d))
	if doctype == "Governing Document":
		value = get("handling_classification")
		if value == RESTRICTED:
			return RESTRICTED
		if value == CONFIDENTIAL or int(get("confidential") or 0):
			return CONFIDENTIAL
		return value if value in CLASS_RANK else INTERNAL
	if doctype == "Governance Forum":
		return CONFIDENTIAL if int(get("confidential") or 0) else INTERNAL
	if doctype in ("Escalation Matter", "Action Plan", "Risk Acceptance"):
		return RESTRICTED if int(get("sensitive") or 0) else INTERNAL
	if doctype == "Regulatory Requirement":
		return PUBLIC
	return INTERNAL


def may_leave(classification: str, cfg=None) -> bool:
	if classification == RESTRICTED:
		return False
	return CLASS_RANK.get(classification, 1) <= CLASS_RANK[ceiling(cfg)]


def highest(*classes: str) -> str:
	present = [c for c in classes if c in CLASS_RANK]
	return max(present, key=CLASS_RANK.get) if present else INTERNAL


# -------------------------------------------------------------------- tokens


def _key() -> bytes:
	from frappe.utils.password import get_encryption_key

	return get_encryption_key().encode()


def token(doctype: str, name: str) -> str:
	digest = hmac.new(_key(), f"{doctype}\x00{name}".encode(), hashlib.sha256).hexdigest()
	return f"{TOKEN_PREFIX.get(doctype, 'R')}-{digest[:8]}"


def token_map(doctype: str, names) -> dict[str, str]:
	"""token -> name for the given records."""
	return {token(doctype, name): name for name in names}


def tokens_in(text: str) -> list[str]:
	return [f"{m.group(1)}-{m.group(2)}" for m in TOKEN_PATTERN.finditer(text or "")]


# ------------------------------------------------------------------ payloads


class Payload:
	"""The facts an analysis sends, built record by record through the gate.

	Each ``add_record`` call either admits the record (as a token, plus its
	title and summary when the mode allows) or withholds it, and the payload
	keeps the highest classification it admitted: that is what the audit row
	records as ``context_classification``.
	"""

	def __init__(self, cfg=None):
		self.cfg = cfg or settings()
		self.summary = (self.cfg.get("data_sharing") or GUIDANCE_MODE) == SUMMARY_MODE
		self.lines: list[str] = []
		self.classification = PUBLIC
		self.withheld = 0
		self.links: dict[str, dict] = {}  # token -> {doctype, name, label, href}

	def line(self, text: str) -> None:
		self.lines.append(text)

	def admit(self, doctype: str, name: str, classification: str, *, label: str | None = None,
	          href: str | None = None) -> str | None:
		"""The record's token if it may be sent, else None (and it is counted)."""
		if not may_leave(classification, self.cfg):
			self.withheld += 1
			return None
		self.classification = highest(self.classification, classification)
		tok = token(doctype, name)
		self.links[tok] = {"doctype": doctype, "name": name, "label": label or name, "href": href}
		return tok

	def record(self, doctype: str, name: str, classification: str, *, title: str | None = None,
	           summary: str | None = None, tags: dict | None = None, href: str | None = None,
	           prefix: str = "- ") -> str | None:
		"""Admit a record and write its line. Returns its token, or None if withheld."""
		tok = self.admit(doctype, name, classification, label=title or name, href=href)
		if not tok:
			return None
		parts = [f"[{tok}]"]
		if self.summary and title:
			parts.append(_clip(title, 160))
		for key, value in (tags or {}).items():
			if value not in (None, "", []):
				parts.append(f"{key}: {value if not isinstance(value, list) else ', '.join(map(str, value))}")
		if self.summary and summary:
			parts.append("summary: " + _clip(summary, 400))
		self.lines.append(prefix + "; ".join(parts))
		return tok

	def text(self) -> str:
		out = list(self.lines)
		if self.withheld:
			out.append(f"({self.withheld} further record(s) were withheld by the platform's data-sharing rules.)")
		return "\n".join(out)


def _clip(value: str, limit: int) -> str:
	value = " ".join(str(value or "").split())
	return value if len(value) <= limit else value[: limit - 1] + "…"


# ------------------------------------------------------------------- running


REFERENCE_RULE = (
	"Records are identified by tokens in square brackets such as [D-1a2b3c4d]. Refer to a record only by "
	"its token, written in square brackets exactly as given; never invent a token, a record, a name or a figure "
	"that the facts do not contain."
)


def run(key: str, *, system: str, payload: Payload, subject: dict | None = None,
        subject_classification: str | None = None, accept=None, max_tokens: int | None = None) -> dict:
	"""Ask the endpoint for one capability, through every gate. Never raises for
	an endpoint fault; raises only for a person who may not ask or is over the limit.

	Returns ``{"used", "status", "notice", "service_request", "value", "withheld", "links"}``.
	"""
	if not may_request():
		frappe.throw(_("Your role may not send analyses to the AI service."), frappe.PermissionError)
	cfg = settings()
	state = availability(key, cfg)
	out = {"used": False, "status": None, "notice": state["reason"], "service_request": None,
	       "value": None, "withheld": payload.withheld, "links": payload.links, "mode": state["mode"]}
	if not state["available"]:
		return out
	check_rate(cfg)

	name = capability_name(key)
	if subject_classification and not may_leave(subject_classification, cfg):
		reason = (f"The subject is classified {subject_classification}; the most that may be sent is "
		          f"{ceiling(cfg)}, and Restricted or sensitive records are never sent.")
		out.update(status="Refused", notice=_("Nothing was sent: {0}").format(reason),
		           service_request=client.record_refusal(name, subject_classification, reason, subject))
		return out

	limit = min(8192, max(256, int(cfg.get("feature_max_tokens") or 2000)))
	result = client.audited(
		cfg, capability=name, system=system + "\n" + REFERENCE_RULE, user_text=payload.text(),
		classification=highest(payload.classification, subject_classification or PUBLIC),
		subject=subject, max_tokens=limit, accept=accept,
	)
	out.update(status=result["status"], service_request=result["service_request"], value=result["value"])
	if result["value"] is not None:
		out.update(used=True, notice=None)
	else:
		out["notice"] = _("The AI service did not produce a usable answer ({0}), so only the rule-based "
		                  "result is shown.").format(result["error"] or result["status"])
	return out


def narrative_blocks(text: str, links: dict[str, dict]) -> list[dict]:
	"""Model text as display blocks, with every known token turned into a link.

	A token the platform did not send is left as plain text; a URL the model
	wrote is dropped (the assistant's renderer already does both).
	"""
	from consilium.consilium_core.assistant.remote import to_blocks

	hrefs = {}

	def swap(match):
		tok = f"{match.group(1)}-{match.group(2)}"
		info = links.get(tok)
		if not info:
			return tok
		href = info.get("href") or f"#{tok}"
		hrefs[href] = info["label"]
		return f"[{_clip(info['label'], 110)}]({href})"

	text = re.sub(r"\[?\b([A-Z])-([0-9a-f]{8})\b\]?", swap, text or "")
	blocks = to_blocks(text, hrefs)
	if not blocks:
		raise client.AIServiceError("the answer had no usable text")
	return blocks

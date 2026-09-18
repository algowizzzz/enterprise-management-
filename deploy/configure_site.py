#!/usr/bin/env python3
"""Apply the deployment configuration's site settings. Idempotent.

    cd <install_dir>/sites
    ../env/bin/python ../deploy/configure_site.py --settings settings.json

Run by the deployment kit (deploy/kit.py) after the site exists and the
reference data is loaded, on every install and upgrade. It takes the settings
the operator put in the one configuration file and writes them where the
framework and the application read them:

  scheduler        enabled. A site created without the setup wizard (which this
                   product skips) has it off, and a site whose scheduler is off
                   looks healthy and quietly never sends a reminder.
  host name        the public https:// address, so links in notifications work
  time zone        System Settings
  admin email      the Administrator account's address
  outgoing email   an Email Account, when [email] enabled = yes; the framework
                   tests the connection to the mail server when it is saved
  SSO              an OpenID Connect provider (Social Login Key) or LDAP
                   Settings, only when [sso] mode says so; otherwise any
                   provider this kit configured earlier is switched off
  AI endpoint      Assistant Settings: on/off, provider, endpoint and model.
                   Never the API key, which an administrator enters in the
                   interface.

Secrets arrive as a *reference* (a file path or an environment variable name),
never as a value, and are read here, so no secret passes through a command line
or a temporary file.

Prints one JSON line summarising what it did.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path


def read_secret(spec: dict | None) -> str | None:
    if not spec:
        return None
    if "env" in spec:
        return os.environ.get(spec["env"]) or None
    path = Path(spec["file"])
    return path.read_text().strip() if path.exists() else None


def configure_scheduler(frappe) -> str:
    from frappe.utils.scheduler import is_scheduler_disabled

    if is_scheduler_disabled(verbose=False):
        frappe.db.set_single_value("System Settings", "enable_scheduler", 1)
        return "enabled"
    return "already enabled"


def configure_system(frappe, s: dict) -> str:
    from frappe.installer import update_site_config

    update_site_config("host_name", s["public_url"])
    settings = frappe.get_single("System Settings")
    changed = settings.time_zone != s["timezone"]
    settings.time_zone = s["timezone"]
    settings.flags.ignore_mandatory = True
    settings.save(ignore_permissions=True)
    frappe.db.set_value("User", "Administrator", "email", s["admin_email"], update_modified=False)
    return f"{s['timezone']}{' (changed)' if changed else ''}; links use {s['public_url']}"


def configure_email(frappe, e: dict) -> str:
    name = "Consilium Outgoing"
    exists = frappe.db.exists("Email Account", name)
    if not e.get("enabled"):
        if exists:
            frappe.db.set_value("Email Account", name, {"enable_outgoing": 0, "default_outgoing": 0})
            return "off (kit account disabled)"
        return "off"
    doc = frappe.get_doc("Email Account", name) if exists else frappe.new_doc("Email Account")
    password = read_secret(e.get("password"))
    doc.update({
        "email_account_name": name,
        "email_id": e["sender"],
        "email_sync_option": "UNSEEN",
        "enable_incoming": 0,
        "enable_outgoing": 1,
        "default_outgoing": 1,
        "always_use_account_email_id_as_sender": 1,
        "always_use_account_name_as_sender_name": 1,
        "name_of_sender": e.get("sender_name") or "",
        "smtp_server": e["smtp_host"],
        "smtp_port": e["smtp_port"],
        "use_tls": 1 if e["security"] == "starttls" else 0,
        "use_ssl_for_outgoing": 1 if e["security"] == "ssl" else 0,
        "login_id_is_different": 1 if e.get("login") and e["login"] != e["sender"] else 0,
        "login_id": e.get("login") or None,
        "no_smtp_authentication": 0 if e.get("login") else 1,
        "awaiting_password": 0,
    })
    if password:
        doc.password = password
    # Saving connects to the mail server to check the settings, which is the
    # point: a wrong port or password is reported now, not at the first
    # overdue reminder.
    doc.save(ignore_permissions=True) if exists else doc.insert(ignore_permissions=True)
    return f"on via {e['smtp_host']}:{e['smtp_port']} ({e['security']}), from {e['sender']}"


def configure_oidc(frappe, sso: dict) -> str:
    provider_name = sso.get("oidc_provider_name") or "Corporate SSO"
    key = frappe.scrub(provider_name)
    enabled = sso.get("mode") == "oidc"
    exists = frappe.db.exists("Social Login Key", key)
    if not enabled:
        # Switch off only the provider this configuration names; leave any
        # other an administrator set up by hand alone.
        if exists and frappe.db.get_value("Social Login Key", key, "enable_social_login"):
            frappe.db.set_value("Social Login Key", key, "enable_social_login", 0)
            return f"off (provider {key!r} disabled)"
        return "off"
    from urllib.parse import urlsplit

    authorize = urlsplit(sso["oidc_authorize_url"])
    doc = frappe.get_doc("Social Login Key", key) if exists else frappe.new_doc("Social Login Key")
    doc.update({
        "provider_name": provider_name,
        "social_login_provider": "Custom",
        "enable_social_login": 1,
        "client_id": sso["oidc_client_id"],
        "custom_base_url": 1,
        "base_url": sso.get("oidc_base_url") or f"{authorize.scheme}://{authorize.netloc}",
        # Absolute URLs are used as given, whatever the base URL.
        "authorize_url": sso["oidc_authorize_url"],
        "access_token_url": sso["oidc_token_url"],
        "api_endpoint": sso["oidc_userinfo_url"],
        "redirect_url": f"/api/method/frappe.integrations.oauth2_logins.custom/{key}",
        "auth_url_data": json.dumps({"response_type": "code", "scope": sso.get("oidc_scope") or "openid email profile"}),
        "user_id_property": sso.get("oidc_user_id_claim") or "sub",
        # Deny: SSO signs in only people who already have an account, matched
        # by email. Allow: it may create one.
        "sign_ups": "Allow" if sso.get("allow_signup") else "Deny",
    })
    secret = read_secret(sso.get("oidc_client_secret"))
    if secret:
        doc.client_secret = secret
    doc.save(ignore_permissions=True) if exists else doc.insert(ignore_permissions=True)
    return f"OpenID Connect provider {key!r} on; sign-ups {'allowed' if sso.get('allow_signup') else 'denied'}"


def configure_ldap(frappe, sso: dict) -> str:
    enabled = sso.get("mode") == "ldap"
    settings = frappe.get_single("LDAP Settings")
    if not enabled:
        if settings.enabled:
            frappe.db.set_single_value("LDAP Settings", "enabled", 0)
            return "off (disabled)"
        return "off"
    import ldap3  # noqa: F401 -- fail here, clearly, if the wheel is missing

    url = sso["ldap_server_url"]
    settings.update({
        "enabled": 1,
        "ldap_server_url": url,
        "ldap_directory_server": sso.get("ldap_directory") or "Active Directory",
        "base_dn": sso["ldap_bind_dn"],
        "ldap_search_path_user": sso["ldap_user_search_path"],
        "ldap_search_path_group": sso["ldap_group_search_path"],
        "ldap_search_string": sso["ldap_search_filter"],
        "ldap_email_field": sso.get("ldap_email_attribute") or "mail",
        "ldap_username_field": sso["ldap_username_attribute"],
        "ldap_first_name_field": sso.get("ldap_first_name_attribute") or "givenName",
        "ldap_last_name_field": sso.get("ldap_last_name_attribute") or "",
        "ssl_tls_mode": "Off" if url.startswith("ldaps://") else "StartTLS",
        "require_trusted_certificate": "Yes",
        "local_ca_certs_file": sso.get("ldap_ca_file") or "",
        "default_user_type": "System User",
        "do_not_create_new_user": 0 if sso.get("allow_signup") else 1,
    })
    password = read_secret(sso.get("ldap_bind_password"))
    if password:
        settings.password = password
    # Saving binds to the directory to check the settings.
    settings.save(ignore_permissions=True)
    return f"LDAP on: {url}"


def configure_assistant(frappe, a: dict) -> str:
    providers = {"anthropic": "Anthropic Messages API", "openai-compatible": "OpenAI-compatible (internal gateway)"}
    if not frappe.db.exists("DocType", "Assistant Settings"):
        return "not present in this release"
    values = {"ai_enabled": 1 if a.get("ai_enabled") else 0}
    if a.get("ai_endpoint_url"):
        values["endpoint_url"] = a["ai_endpoint_url"]
    if a.get("ai_model"):
        values["model"] = a["ai_model"]
    if a.get("ai_provider"):
        values["provider"] = providers[a["ai_provider"]]
    for field, value in values.items():
        frappe.db.set_single_value("Assistant Settings", field, value)
    if a.get("ai_enabled"):
        has_key = bool(frappe.db.get_single_value("Assistant Settings", "api_key"))
        return (f"AI on: {a['ai_model']} at {a['ai_endpoint_url']}; API key "
                f"{'set' if has_key else 'NOT SET — an administrator enters it in Assistant Settings'}")
    return "AI off (built-in answers only)"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--settings", required=True)
    parser.add_argument("--sites-path", default=".")
    args = parser.parse_args()
    s = json.loads(Path(args.settings).read_text())

    import frappe

    frappe.init(site=s["site"], sites_path=str(Path(args.sites_path).resolve()))
    frappe.connect()
    frappe.set_user("Administrator")
    summary = {}
    try:
        for label, fn in (("scheduler", lambda: configure_scheduler(frappe)),
                          ("site", lambda: configure_system(frappe, s)),
                          ("email", lambda: configure_email(frappe, s["email"])),
                          ("sso (oidc)", lambda: configure_oidc(frappe, s["sso"])),
                          ("sso (ldap)", lambda: configure_ldap(frappe, s["sso"])),
                          ("assistant", lambda: configure_assistant(frappe, s["assistant"]))):
            try:
                summary[label] = fn()
                frappe.db.commit()
            except Exception as e:  # noqa: BLE001 -- report every section, then fail
                frappe.db.rollback()
                summary[label] = f"FAILED: {type(e).__name__}: {str(e)[:300]}"
        frappe.clear_cache()
    finally:
        frappe.destroy()
    print(json.dumps(summary))
    return 1 if any(str(v).startswith("FAILED") for v in summary.values()) else 0


if __name__ == "__main__":
    raise SystemExit(main())

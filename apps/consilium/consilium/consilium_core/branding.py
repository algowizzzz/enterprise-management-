"""The portal's look, from one settings record.

Everything a deploying organisation would change to make the portal its own —
name, logo, colours, typeface, the home page banner — is data on the
``Portal Branding`` record, not code. Two reasons:

* The repository is shared and must not carry anyone's brand. A deployment
  uploads its own logo and font files through the interface; they are stored as
  site files, served from the same host, and never committed.
* One brand has to reach two surfaces: the portal pages, which read it here, and
  the framework's own screens (sign-in, workspace, browser tab), which read a
  handful of framework settings. ``apply_framework_branding`` writes those, so
  saving the record is the only step.

The framework's name is taken out of what people see as a side effect: every
place it would appear is a setting the framework falls back from, and this sets
them all.
"""

from __future__ import annotations

import hashlib
import os
import re

import frappe

CACHE_KEY = "consilium:portal_branding"

DEFAULT_LOGO = "/assets/consilium/images/portal-mark.svg"
DEFAULT_FAVICON = "/assets/consilium/images/portal-favicon.svg"

DEFAULTS = {
    "portal_name": "Governance Portal",
    "organisation_name": "",
    "logo": "",
    "favicon": "",
    "primary_colour": "#1d3557",
    "accent_colour": "#0f6c8c",
    "header_style": "Primary colour",
    "font_family": "",
    "font_regular": "",
    "font_bold": "",
    "hero_title": "Governance, risk and policy in one place",
    "hero_text": (
        "Find a forum, check where a policy stands, or raise a matter that needs "
        "attention — every record with its owner, its history and its next step."
    ),
    "hero_image": "",
    "hero_primary_label": "Browse the forum inventory",
    "hero_primary_url": "/forums",
    "hero_secondary_label": "Request a new forum",
    "hero_secondary_url": "/create-forum",
    "footer_text": "",
}

_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")


# ------------------------------------------------------------------ reading


def get_brand() -> dict:
    """The effective brand: the saved record over the defaults.

    Read on every portal page, so it is cached and cleared when the record is
    saved. A site that has never saved the record, or predates it, gets the
    defaults rather than an error.
    """
    cached = frappe.cache.get_value(CACHE_KEY)
    if cached:
        return cached
    brand = dict(DEFAULTS)
    # A single-record DocType has no table of its own (its values live in the
    # framework's shared singles table), so "does the table exist" is always
    # false for it and the saved brand would never be read. Ask whether the
    # DocType is installed instead.
    if frappe.db.exists("DocType", "Portal Branding"):
        saved = frappe.get_cached_doc("Portal Branding")
        for key in DEFAULTS:
            value = saved.get(key)
            if value not in (None, ""):
                brand[key] = value
    brand["logo_url"] = _safe_url(brand["logo"]) or DEFAULT_LOGO
    brand["favicon_url"] = _safe_url(brand["favicon"]) or DEFAULT_FAVICON
    brand["hero_image_url"] = _safe_url(brand["hero_image"])
    brand["has_custom_logo"] = bool(_safe_url(brand["logo"]))
    frappe.cache.set_value(CACHE_KEY, brand)
    return brand


def clear_cache() -> None:
    frappe.cache.delete_value(CACHE_KEY)
    # The record's own cached copy too: the record's save hook re-reads the brand
    # before the framework drops that copy, and would otherwise push the previous
    # brand onto the framework's screens.
    frappe.clear_document_cache("Portal Branding", "Portal Branding")


def _safe_url(value: str | None) -> str:
    """Only same-host paths. An external URL here would be a runtime fetch, which
    the target network does not allow, and a quote or bracket would break out of
    the CSS it is written into."""
    value = (value or "").strip()
    if not value.startswith(("/files/", "/assets/")):
        return ""
    if re.search(r"[\"'()<>\\\s;{}]", value):
        return ""
    return value


# ------------------------------------------------------------------ assets


def asset_url(path: str) -> str:
    """A portal asset URL that changes whenever the file does.

    Assets are served with a twelve-hour cache lifetime and the same URL every
    release, so without this a browser keeps the old stylesheet and script for
    half a day after an upgrade — the page loads, looks almost right, and quietly
    runs yesterday's code.
    """
    return f"{path}?v={_asset_version()}"


_version_cache: dict[str, str] = {}


def _asset_version() -> str:
    # Production workers are restarted on deployment, so the fingerprint is taken
    # once per process. In developer mode files change under a running server, so
    # it is taken per request; it is a stat of a few dozen files.
    if not frappe.conf.developer_mode and "v" in _version_cache:
        return _version_cache["v"]
    public = os.path.join(frappe.get_app_path("consilium"), "public")
    digest = hashlib.sha1()
    for folder in ("css", "js"):
        base = os.path.join(public, folder)
        for name in sorted(os.listdir(base)) if os.path.isdir(base) else []:
            stat = os.stat(os.path.join(base, name))
            digest.update(f"{name}:{stat.st_mtime_ns}:{stat.st_size}".encode())
    _version_cache["v"] = digest.hexdigest()[:10]
    return _version_cache["v"]


@frappe.whitelist()
def people() -> dict[str, str]:
    """Display names for the organisation's people, for the portal to show
    instead of account IDs.

    Only signed-in colleagues may ask, and only names come back — no email
    addresses beyond the ID the record already shows, no roles, no status. The
    user list itself stays closed to anyone without the right to read it.
    """
    if frappe.session.user == "Guest":
        raise frappe.PermissionError
    rows = frappe.get_all(
        "User",
        filters={"user_type": "System User", "name": ["not in", ["Guest"]]},
        fields=["name", "full_name"],
        limit_page_length=0,
    )
    return {row.name: row.full_name or row.name for row in rows}


def cns_can_read(doctype: str) -> bool:
    """For templates: whether the viewer may read a record type at all."""
    if frappe.session.user == "Guest":
        return False
    return bool(frappe.has_permission(doctype, "read"))


def cns_has_any_role(*roles: str) -> bool:
    """For templates, whose sandbox does not expose the framework's role lookup."""
    if frappe.session.user == "Guest":
        return False
    return bool(set(roles) & set(frappe.get_roles()))


def system_time_zone() -> str:
    """The zone the server stores times in, for the portal to convert from."""
    return frappe.db.get_single_value("System Settings", "time_zone") or "UTC"


def cns_here() -> str:
    """The current page with its query string, for a sign-in link to return to.

    Templates see only ``frappe.request.path``: the sandbox exposes nothing
    else of the request. A link from "/forums?standing=overdue" that came back
    to "/forums" would lose the view someone was sent to look at. Only a local
    path is ever returned, so the value cannot become an open redirect.
    """
    request = getattr(frappe.local, "request", None)
    if not request:
        return "/"
    path = request.path if request.path.startswith("/") and not request.path.startswith("//") else "/"
    query = request.query_string.decode("latin-1") if request.query_string else ""
    return f"{path}?{query}" if query else path


# ------------------------------------------------------------------ styling


def brand_style() -> str:
    """CSS custom properties for the saved brand, written into each portal page.

    Only the tokens change; every component already reads them, so a new colour
    or typeface reaches the whole portal without a stylesheet being edited.
    """
    brand = get_brand()
    primary = brand["primary_colour"] if _HEX.match(brand["primary_colour"] or "") else DEFAULTS["primary_colour"]
    accent = brand["accent_colour"] if _HEX.match(brand["accent_colour"] or "") else DEFAULTS["accent_colour"]

    light = {
        "--cns-primary-050": _mix(primary, "#ffffff", 0.92),
        "--cns-primary-100": _mix(primary, "#ffffff", 0.82),
        "--cns-primary-200": _mix(primary, "#ffffff", 0.64),
        "--cns-primary-300": _mix(primary, "#ffffff", 0.44),
        "--cns-primary-400": _mix(primary, "#ffffff", 0.24),
        "--cns-primary-500": _mix(primary, "#ffffff", 0.08),
        "--cns-primary-600": primary,
        "--cns-primary-700": _mix(primary, "#000000", 0.18),
        "--cns-primary-800": _mix(primary, "#000000", 0.36),
        "--cns-primary-900": _mix(primary, "#000000", 0.55),
        "--cns-on-primary": "#111111" if _luminance(primary) > 0.45 else "#ffffff",
        "--cns-accent": accent,
        "--cns-accent-subtle": _mix(accent, "#ffffff", 0.88),
        "--cns-on-accent": "#111111" if _luminance(accent) > 0.45 else "#ffffff",
    }
    # Dark theme keeps its own surfaces and lifts the brand colour so it still
    # reads against them.
    dark = {
        "--cns-primary": _mix(primary, "#ffffff", 0.5),
        "--cns-primary-hover": _mix(primary, "#ffffff", 0.62),
        "--cns-primary-active": _mix(primary, "#ffffff", 0.72),
        "--cns-primary-500": _mix(primary, "#ffffff", 0.42),
        "--cns-primary-600": _mix(primary, "#ffffff", 0.5),
        "--cns-accent": _mix(accent, "#ffffff", 0.4),
    }

    # Selectors one step more specific than the stylesheet's own, so the brand
    # wins in each theme without the light scale leaking into the dark one.
    css = [':root:not([data-theme="dark"]){' + "".join(f"{k}:{v};" for k, v in light.items()) + "}"]
    css.append(':root[data-theme="dark"]{' + "".join(f"{k}:{v};" for k, v in dark.items()) + "}")

    family = re.sub(r"[^A-Za-z0-9 \-]", "", brand["font_family"] or "").strip()
    regular, bold = _safe_url(brand["font_regular"]), _safe_url(brand["font_bold"])
    if family and regular:
        css.append(_font_face(family, regular, 400))
        if bold:
            css.append(_font_face(family, bold, 700))
        css.append(f':root{{--cns-font-sans:"{family}",-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,"Helvetica Neue",Arial,sans-serif;}}')
    return "".join(css)


def _font_face(family: str, url: str, weight: int) -> str:
    fmt = {"woff2": "woff2", "woff": "woff", "ttf": "truetype", "otf": "opentype"}.get(url.rsplit(".", 1)[-1].lower(), "woff2")
    return (f'@font-face{{font-family:"{family}";src:url("{url}") format("{fmt}");'
        f"font-weight:{weight};font-style:normal;font-display:swap;}}")


def _rgb(hex_colour: str) -> tuple[int, int, int]:
    h = hex_colour.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _mix(colour: str, towards: str, amount: float) -> str:
    a, b = _rgb(colour), _rgb(towards)
    return "#" + "".join(f"{round(x + (y - x) * amount):02x}" for x, y in zip(a, b))


def _luminance(colour: str) -> float:
    def channel(c):
        c = c / 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (channel(c) for c in _rgb(colour))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def validate_colour(value: str | None, label: str) -> None:
    if value and not _HEX.match(value):
        frappe.throw(f"{label} must be a six-digit colour such as #1d3557.", title="Colour Not Recognised")


# ------------------------------------------------------- framework screens

#: Framework menu entries that lead to the framework's own site or version
#: dialog. Hidden rather than deleted, so an administrator can bring one back.
_HIDDEN_HELP_ACTIONS = ("frappe.ui.toolbar.show_about()",)
_HIDDEN_HELP_HOSTS = ("frappe.io", "frappeframework.com", "frappe.school", "discuss.frappe.io", "github.com/frappe")
_HIDDEN_SETTINGS_LABELS = ("Apps",)


def apply_framework_branding() -> None:
    """Carry the brand onto the screens the framework draws itself.

    The sign-in page, the workspace header, the browser tab and the website
    footer each fall back to the framework's own name and logo when their
    setting is empty. Setting them is what removes that name; it is idempotent
    and runs on every migrate as well as on save.
    """
    brand = get_brand()
    name = brand["portal_name"]

    ws = frappe.get_single("Website Settings")
    ws.app_name = name
    ws.app_logo = brand["logo_url"]
    ws.favicon = brand["favicon_url"]
    # The loading screen shown while the workspace starts.
    ws.splash_image = brand["logo_url"]
    # Non-empty, or the footer says what the site is built on.
    ws.footer_powered = brand["organisation_name"] or name
    ws.flags.ignore_mandatory = True
    ws.save(ignore_permissions=True)

    frappe.db.set_single_value("System Settings", "app_name", name)

    navbar = frappe.get_single("Navbar Settings")
    navbar.app_logo = brand["logo_url"]
    for row in navbar.help_dropdown:
        target = (row.route or "") + (row.action or "")
        if row.action in _HIDDEN_HELP_ACTIONS or any(host in target for host in _HIDDEN_HELP_HOSTS):
            row.hidden = 1
    for row in navbar.settings_dropdown:
        if row.item_label in _HIDDEN_SETTINGS_LABELS:
            row.hidden = 1
    navbar.save(ignore_permissions=True)

    clear_cache()
    frappe.clear_cache()


def after_migrate() -> None:
    apply_framework_branding()

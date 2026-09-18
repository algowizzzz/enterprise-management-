app_name = "consilium"
app_title = "Consilium"
app_publisher = "Consilium"
app_description = "Enterprise Governance, Risk & Policy platform"
app_email = "dev@example.com"
app_license = "MIT"

# All front-end assets are vendored. Nothing is fetched from a CDN at build
# or run time, because the target environment has no internet access.
# Deliberately no app_include_*: the portal stylesheet and scripts are for the
# custom screens. The framework's own administration interface is left as it
# comes, and loading our assets into every one of its pages would buy nothing.

web_include_css = [
    "/assets/consilium/css/tokens.css",
    "/assets/consilium/css/consilium.css",
]
# The workspace (desk) forms: the automatic status check boxes are hidden from
# business users. Plain JavaScript, served as it is — no build step.
app_include_js = ["/assets/consilium/js/consilium-desk.js"]

web_include_js = [
    "/assets/consilium/js/consilium.js",
    "/assets/consilium/js/consilium-table.js",
    "/assets/consilium/js/consilium-reference.js",
]

# Signed-in users are sent to the framework's own landing page otherwise, and
# never see ours.
home_page = "index"

after_install = "consilium.consilium_core.setup.install.after_install"

# Seeds the semantic state-flag map and re-applies the partial unique indexes,
# lookup indexes and check constraints the framework's ALTER path does not
# preserve. See consilium/consilium_core/setup/constraints.py.
after_migrate = [
    "consilium.consilium_core.setup.install.after_migrate",
    # The framework's sign-in page, workspace and browser tab fall back to the
    # framework's own name and logo unless told otherwise; this tells them.
    "consilium.consilium_core.branding.after_migrate",
    # Everything the framework ships beyond this platform's scope is hidden
    # from everyday users: see consilium/consilium_core/scope.py.
    "consilium.consilium_core.scope.after_migrate",
]

# Rows an import commits into Escalation Matter need their impacted entities
# attached before insert; the pipeline calls these per target DocType.
consilium_import_preparers = {
    "Escalation Matter": ["consilium.escalation.importing.attach_impacted_entities"],
    # A regulatory-change file carries only what changed: a blank cell leaves the
    # field alone, and a row that changes nothing is left out (P-6, O-7).
    "Regulatory Requirement": ["consilium.policy.regulatory_import.prepare_changes"],
}

# Attestation populations neither a record field nor a seat table can express,
# resolved by name. A campaign names the source; the code path lives here, never
# in a database row.
consilium_attestation_participants = {
    "Document Audience": "consilium.policy.attestation.audience_participants",
}

# A retired taxonomy value must not be offered for new records, while records
# that already carry it still load and save. Written out as a literal: hooks
# are read before the app is importable (see consilium_core/taxonomy.py).
_ACTIVE_ONLY = "consilium.consilium_core.taxonomy.active_only_search"
standard_queries = {
    doctype: _ACTIVE_ONLY
    for doctype in (
        "Risk Category", "Risk Type", "Legal Entity", "Organization Unit", "Jurisdiction",
        "Material Entity", "Line Of Defence", "Organizational Level", "Governing Document Type",
        "Governance Forum Type", "Governance Forum Role", "Governance Responsibility",
        "Escalation Type", "Horizon Scanning Coverage Area", "Regulatory Requirement",
        "Delegable Action", "Document Role",
    )
}

# The framework's public website pages (blog, contact, search…) are out of
# scope; each goes to the portal's home instead.
website_redirects = [
    {"source": r"/blog(/.*)?", "target": "/"},
    {"source": "/contact", "target": "/"},
    {"source": "/about", "target": "/"},
    {"source": r"/newsletters(/.*)?", "target": "/"},
    {"source": "/apps", "target": "/app"},
    {"source": "/third_party_apps", "target": "/"},
    {"source": "/search", "target": "/"},
    {"source": "/list", "target": "/"},
]

# Portal templates read the brand and version their asset URLs through these.
jinja = {
    "methods": [
        "consilium.consilium_core.branding.get_brand",
        "consilium.consilium_core.branding.brand_style",
        "consilium.consilium_core.branding.asset_url",
        "consilium.consilium_core.branding.system_time_zone",
        "consilium.consilium_core.branding.viewer_time_zone",
        "consilium.consilium_core.branding.cns_has_any_role",
        # The "Advanced view" (workspace) links on business pages: administrators only.
        "consilium.consilium_core.branding.cns_advanced_view",
        "consilium.consilium_core.branding.cns_can_read",
        "consilium.consilium_core.branding.cns_here",
        # The header's menus, filtered to what the viewer may use.
        "consilium.consilium_core.navigation.cns_nav",
        # The Doc AI and horizon-scanning buttons: labels, states, who sees them.
        "consilium.consilium_core.integrations.external_tools.cns_external_tools",
    ]
}

# Core controls apply to every record in the platform, including ones the
# business modules add later, so they are wired as wildcard document events.
# Each guard is a cached no-op for a DocType no retention rule or watched-field
# set refers to.
doc_events = {
    "*": {
        "before_validate": [
            "consilium.consilium_core.jsonfields.normalise",
            "consilium.consilium_core.retention.guard_modification",
        ],
        # A JSON field holding a list cannot be sent to the desk form as read
        # from PostgreSQL; see jsonfields.normalise_loaded.
        "onload": "consilium.consilium_core.jsonfields.normalise_loaded",
        "on_trash": "consilium.consilium_core.retention.guard_deletion",
        "on_update": [
            "consilium.consilium_core.watched_fields.on_update",
            # Status-driven service-level clocks follow the record as it moves,
            # rather than waiting for the hourly catch-up.
            "consilium.consilium_core.sla.on_subject_update",
        ],
    },
    # A file attached to a confidential or restricted document is kept private.
    "File": {"before_insert": "consilium.policy.handling.guard_file_privacy"},
    # New everyday users get the module profile that hides out-of-scope modules.
    "User": {"validate": "consilium.consilium_core.scope.apply_module_profile"},
    # Forums and escalations keep a revision chain so either can be reverted.
    "Governance Forum": {"on_update": "consilium.consilium_core.revision.snapshot"},
    "Escalation Matter": {"on_update": "consilium.consilium_core.revision.snapshot"},
}

# Restricted records.
#
# A sensitive escalation must be invisible to anyone without the right — not
# only in the interface, but in list views, reports, search and the REST API.
# The framework enforces that through these two hooks, and **only** through
# these two hooks: the module's logic is inert until it is registered here.
# There is no partial state. Either these entries exist and the restriction
# holds on every read path, or they do not and it holds on none.
permission_query_conditions = {
    "Escalation Matter": "consilium.escalation.sensitivity.matter_conditions",
    "Action Plan": "consilium.escalation.sensitivity.action_plan_conditions",
    "Risk Acceptance": "consilium.escalation.sensitivity.risk_acceptance_conditions",
    "Escalation Closure": "consilium.escalation.sensitivity.closure_conditions",
    # Confidential and restricted documents: who may see them at all.
    "Governing Document": "consilium.policy.handling.query_conditions",
    # A version's body carries its document's handling; without these a
    # restricted body would be readable through the version or its file.
    "Document Version": "consilium.policy.handling.version_query_conditions",
}

has_permission = {
    "Escalation Matter": "consilium.escalation.sensitivity.has_permission",
    "Action Plan": "consilium.escalation.sensitivity.has_permission",
    "Risk Acceptance": "consilium.escalation.sensitivity.has_permission",
    "Escalation Closure": "consilium.escalation.sensitivity.has_permission",
    "Governing Document": "consilium.policy.handling.has_permission",
    "Document Version": "consilium.policy.handling.version_has_permission",
}

scheduler_events = {
    "daily": [
        "consilium.consilium_core.delegation.refresh_all",
        "consilium.consilium_core.attestation.expire_overdue",
        "consilium.consilium_core.sla.sweep",
        # Matters past their time threshold are raised and their forums notified.
        "consilium.escalation.resolution.sweep_breaches",
        # Officer fields on a forum are derived from its membership. Concurrent
        # membership saves can interleave and leave them stale, so they are
        # reconciled daily rather than trusted to always be right.
        "consilium.governance.membership.officer_drift",
        # Horizon scans that are due, chased to the owner and then the sponsor.
        "consilium.policy.horizon.remind_due",
        # Applicability exemptions that have reached their expiry.
        "consilium.policy.doctype.applicability_exemption.applicability_exemption.lapse_expired",
        # Due and overdue reminders across the modules, and service-level warnings.
        "consilium.consilium_core.reminders.daily",
        # Records past their retention period are put up for disposal review
        # (a Disposition Event awaiting approval). Nothing is deleted on a schedule.
        "consilium.consilium_core.retention.flag_due_for_disposal",
    ],
    "hourly": [
        "consilium.consilium_core.notification.retry_failed",
        "consilium.consilium_core.reminders.hourly",
    ],
}

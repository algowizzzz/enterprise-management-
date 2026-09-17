app_name = "consilium"
app_title = "Consilium"
app_publisher = "Consilium"
app_description = "Enterprise Governance, Risk & Policy platform"
app_email = "dev@example.com"
app_license = "MIT"

# All front-end assets are vendored. Nothing is fetched from a CDN at build
# or run time, because the target environment has no internet access.
app_include_css = "/assets/consilium/css/consilium.css"
app_include_js = "/assets/consilium/js/consilium.js"

web_include_css = "/assets/consilium/css/consilium.css"
web_include_js = "/assets/consilium/js/consilium.js"

after_install = "consilium.consilium_core.setup.install.after_install"

# Seeds the semantic state-flag map and re-applies the partial unique indexes,
# lookup indexes and check constraints the framework's ALTER path does not
# preserve. See consilium/consilium_core/setup/constraints.py.
after_migrate = "consilium.consilium_core.setup.install.after_migrate"

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
        "on_trash": "consilium.consilium_core.retention.guard_deletion",
        "on_update": "consilium.consilium_core.watched_fields.on_update",
    }
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
}

has_permission = {
    "Escalation Matter": "consilium.escalation.sensitivity.has_permission",
    "Action Plan": "consilium.escalation.sensitivity.has_permission",
    "Risk Acceptance": "consilium.escalation.sensitivity.has_permission",
    "Escalation Closure": "consilium.escalation.sensitivity.has_permission",
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
        # Forums and policies whose periodic review has fallen due.
        "consilium.governance.reviews.overdue_reviews",
        # Horizon scans that are due, chased to the owner and then the sponsor.
        "consilium.policy.horizon.remind_due",
        # Applicability exemptions that have reached their expiry.
        "consilium.policy.doctype.applicability_exemption.applicability_exemption.lapse_expired",
    ],
    "hourly": [
        "consilium.consilium_core.notification.retry_failed",
    ],
}

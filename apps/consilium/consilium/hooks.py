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

scheduler_events = {
    "daily": [
        "consilium.consilium_core.delegation.refresh_all",
        "consilium.consilium_core.attestation.expire_overdue",
        "consilium.consilium_core.sla.sweep",
    ],
    "hourly": [
        "consilium.consilium_core.notification.retry_failed",
    ],
}

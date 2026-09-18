"""Portal Branding — controller.

How the portal looks to the people who use it: its name, logo, colours, typeface
and home page. Brand assets are uploaded here by the deploying organisation, so
none of them live in the code. See consilium/consilium_core/branding.py.
"""

from frappe.model.document import Document

from consilium.consilium_core import branding


class PortalBranding(Document):
    def validate(self):
        branding.validate_colour(self.primary_colour, "Primary Colour")
        branding.validate_colour(self.accent_colour, "Accent Colour")
        if self.font_regular and not self.font_family:
            self.font_family = "Brand"

    def on_update(self):
        # The framework's own screens read their own settings, so the brand is
        # pushed to them here; saving this record is the only step.
        branding.clear_cache()
        branding.apply_framework_branding()

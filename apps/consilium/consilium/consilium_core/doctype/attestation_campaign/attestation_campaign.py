"""Attestation Campaign — controller.

One attestation event. Three campaign types, one engine (02-data-model.md §5.1). The population is derived from live data at generation time; the stored filter is what makes that derivation reproducible.
"""

from frappe.model.document import Document


class AttestationCampaign(Document):
    def validate(self):
        pass

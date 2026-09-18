"""Governance analysis features (O-6, O-7): rule-based first, AI optional.

Five capabilities, each built the same way:

=====================================  ===================  ==========================
capability                             module               page
=====================================  ===================  ==========================
policy-change impact assessment (O-6)  ``impact.py``        Impact panel on ``/policy``
governance gap detection (O-6)         ``gaps.py``          ``/governance-gaps``
regulatory updates (O-7)               ``regulatory.py``    ``/regulatory-updates``
predictive analytics, emerging risks   ``trends.py``        ``/emerging-risks``
automated governance risk assessment   ``scoring.py``       ``/governance-gaps``
=====================================  ===================  ==========================

1. **A deterministic engine** computes the result from the records, through
   the permitted query, with no network. This is the feature: the platform
   runs where there is no internet access (CLAUDE.md rule 5), so nothing here
   may depend on a model to be useful.
2. **An optional AI layer**, off by default, adds narrative and suggestions
   when an administrator has switched it on in ``Assistant Settings``. Its
   payload is built through ``guard.py`` (what may leave, at what
   classification, in what detail) and sent through ``client.py`` (one
   audited path, shared with the help assistant; any failure falls back).
3. **Human acceptance.** Machine text is shown labelled as machine-generated
   and is never written into a record by the platform. Where a suggestion can
   be applied (regulatory updates), a person with write access accepts or
   rejects it, and the decision is recorded as an ``AI Suggestion Acceptance``.
"""

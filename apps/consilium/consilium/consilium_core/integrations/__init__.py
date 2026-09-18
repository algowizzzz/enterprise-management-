"""Connections to services outside the platform.

Each module here is one integration an administrator switches on from the
portal's Integrations page (``/integrations``):

* ``external_tools`` — the Doc AI and horizon-scanning hand-offs: buttons that
  send a person to another tool with identifiers in the address, never content;
* ``graph_mail`` — notification email through Microsoft Graph, for an
  organisation that does not allow SMTP;
* ``admin`` — the Integrations page's endpoints: read the state of every
  integration, save it, test the AI connection and send a test email.

The AI endpoint itself lives in ``consilium_core.ai.client``, which the
Integrations page configures and tests but does not duplicate.

Every address an administrator gives is checked by ``check_url`` in
``external_tools``: http(s) only, so a saved ``javascript:`` address can never
end up behind a button.
"""

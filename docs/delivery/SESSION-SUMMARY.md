# Where this got to

Written at the end of the build session, for whoever picks it up next.

## What exists

**A working product.** Four modules on one platform — 136 entities over 371
PostgreSQL tables, 724 automated tests passing against a real database, and five
screens exercised in a browser in both themes at desktop and phone width.

| | |
|---|---|
| Consilium Core | 57 entities: taxonomy, identity, and the engines all three modules share — versioning and revert, attestation, retention and legal hold, the classification rules engine, notifications, imports, SLA timing |
| Governance | 24 entities: forum inventory, committee formation, the compliance lifecycle, membership with history, meetings, motions, votes |
| Policy | 37 entities: repository, lineage, applicability, lifecycle and approval routing, intake classification, horizon scanning, monitoring, violations, glossary |
| Escalation | 18 entities: matters, three configurable templates, action plans, risk acceptances, routing matrices, resolution |

**A proven deployment path.** One bundle carries every dependency as a built
wheel, the framework, the application, prebuilt front-end assets and the
installer. It has been installed into a clean target **with every proxy variable
pointed at a dead port**, so nothing could have reached the network. Fifteen
health checks pass, the site serves, and every asset the interface references
returns 200. A backup was taken, restored into a separate empty database, and
verified by row count and by the health check on the restored site.

**Documentation** for the stakeholder (data model, schema, architecture), for the
engineering team, and for the deploying team — plus a 40-slide deck.

## The decisions that shaped it

- **Nothing branches on a workflow state name.** Logic reads semantic flags a
  configuration table sets. A checker enforces it over 82 state names and fails
  the build. This is what makes a state rename, or an inserted approval step,
  configuration rather than a code change.
- **Entities are generated from short specs**, so conventions hold across all 136
  rather than being reapplied by hand.
- **The engines are built once**, in Core. All three modules need attestation,
  retention, versioning and notification; three implementations would have meant
  three subtly different answers to the same question.
- **Everything is vendored and checksummed.** No CDN, no package manager, no
  dependency needing a compiler — enforced by an automated check, because the
  target has no internet access and a CDN link pasted from a tutorial fails
  there and nowhere else.

## What is not done

1. **No migration rehearsal on a target server.** The framework describes its
   PostgreSQL support as second-class in this major version; four divergences
   between the two database backends were found and fixed during this build, and
   there is no basis for assuming that list is complete. **This is the largest
   remaining unknown and it can only be closed on the target.**
2. **No upgrade rehearsal** from a previous release.
3. **No load rehearsal.** Paging and search happen in the database rather than
   the browser, so the design is sound, but there are no numbers.
4. **No measured accessibility audit.** Keyboard paths, focus and ARIA were
   verified programmatically; contrast ratios are eyeballed.
5. **Certificates, ports and service accounts** are undecided, and service
   definitions for systemd and Windows are not written.
6. **Single sign-on is not enabled.** It is configuration for LDAP or OIDC —
   but **SAML is not implemented in this framework at all**, verified in source.
   If SAML is mandated it is a separate build and needs separate estimation.

Nothing in that list blocks building. Items 1–3 and 5 block going live.

## Questions that still need a person

The full list is maintained outside this repository. The ones that change work
rather than detail:

- **Which SSO protocol**, specifically. Not "we use SSO" — LDAP and OIDC are
  configuration, SAML is a build.
- **Which taxonomy values are real.** The seeded set is a generic starting point
  and is meant to be replaced.
- **The classification rules** for major versus minor policy change. The rules
  engine is built and the rules are data; the actual decision rules have to come
  from the business.
- **Whether the assumptions in `docs/product/07-assumptions-and-gaps.md` hold.**
  That document exists to be argued with. The entity marked most consequential
  there should be the first thing a reviewer pushes back on.

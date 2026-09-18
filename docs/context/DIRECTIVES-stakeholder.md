# Stakeholder directives — WhatsApp thread with the sponsor (the client)

Captured from screenshots, 2:21–2:33 PM. These are **binding build constraints**
and sit alongside `PRD-frappe-build.md`. Where they conflict with the PRD, these
are newer.

---

## 1. Frontend stack — mandated

| Directive | Detail |
|---|---|
| **Bootstrap** | "Bootstrap is crazy good" — the mandated CSS framework |
| **jQuery** | mandated |
| **NO CDN** | **Vendor Bootstrap and jQuery locally.** Stated twice: *"Do not use CDN"* and *"Vendored bootstrap and jQuery - so not use cdn"* |
| **NO DataTables** | explicitly excluded — *"Also tell not to use datatable"* |
| **Bootstrap table** | use Bootstrap's own table, not a table plugin |

> ✅ **RESOLVED.** The first message reads "Do not use CDN - vendered sql".
> Confirmed by the author: this means **vendored JavaScript and CSS**, not SQL.
> It is a restatement of the vendoring directive for Bootstrap and jQuery.
> **There is no database directive in this thread.**

### Table behaviour — every table, no exceptions
- Pagination
- Sort
- Search
- **Page size configurable**

Since DataTables is banned, this is a hand-rolled (or Frappe-native) implementation
on Bootstrap markup.

### Accessibility / display
- **Font size changeable on every page via a dropdown.**

### Theming
- Light theme based on **www.the client's public website** branding.
- **Dark theme using a dark blue background.**
- **Theme switchable from the UI.**

---

## 2. AI / integration features (new scope, beyond the 64 requirements)

- **the AI services platform behind the scenes** providing AI-driven values — *summarization etc.*
  (Consistent with PRD §7's already-built the AI services platform adapter, but broader: the PRD
  scoped the AI services platform to P-26 and Horizon Scanning only. This widens it.)
- **Push notices and alerts via Microsoft Teams** — *"now that we are able to
  integrate with Microsoft"*. **New integration, not in the PRD or §8 connector
  inventory.**
- **Interactive experience from the AI services platform and Copilot.** Copilot is **new** — not
  mentioned anywhere in the PRD.
- Strategic framing: *"That is where we will kill the incumbent GRC platform"* — the AI +
  Teams/Copilot layer is positioned as the competitive differentiator against
  the incumbent GRC platform, not the CRUD/workflow layer.

---

## 3. Explicit ask directed at Claude

> *"Also please tell Claude to document data model and data schema"*

→ See `DATA-MODEL.md`.

---

## Open items raised by these directives

1. ~~**"vendered sql"** — confirm intent.~~ ✅ Closed: means vendored JS/CSS.
2. **Teams integration** — no connector defined; needs an owner, auth model
   (Graph API? incoming webhook?) and its own row in the PRD §8 inventory.
3. **Copilot** — undefined. Which Copilot (M365, Studio, custom)? What does
   "interactive experience" mean concretely?
4. **the AI services platform scope widening** — PRD §7 notes the adapter is **text-only**
   (multimodal returns HTTP 500). Any summarization feature must stay within
   text-in/text-out.
5. **Bootstrap/jQuery vs Frappe's own UI** — Frappe's Desk is its own SPA and
   already bundles Bootstrap 4 + jQuery. Confirm whether these directives apply
   to (a) custom Web Forms / portal pages built on top of Frappe, or (b) a
   replacement of the Desk UI entirely. **This materially changes the build.**

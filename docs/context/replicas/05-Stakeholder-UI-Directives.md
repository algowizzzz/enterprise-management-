# Stakeholder Directives — UI Look & Feel, AI Layer
## Source: WhatsApp thread with the sponsor (the client), 2:21–2:33 PM

**Fidelity:** 🟢 transcribed from screenshots. Quoted text is verbatim.
These are stated as build constraints and are **newer than the PRD**.

---

## 1. Front-end stack

| Directive | Detail |
|---|---|
| **Bootstrap** | mandated CSS framework — *"Bootstrap is crazy good"* |
| **jQuery** | mandated |
| **No CDN** | vendor Bootstrap and jQuery locally. Stated twice: *"Do not use CDN"*, *"Vendored bootstrap and jQuery - so not use cdn"* |
| **No DataTables** | *"Also tell not to use datatable"* |
| **Bootstrap table** | use Bootstrap's own table markup, not a table plugin |

### Table behaviour — every table, no exceptions
- Pagination
- Sort
- Search
- Page size configurable

### Accessibility / display
- Font size changeable on **every page**, via a dropdown.

### Theming
- Light theme based on **www.the client's public website** branding.
- Dark theme using a **dark blue** background.
- Theme **switchable from the UI**.

---

## 2. AI / integration layer *(scope beyond the 64 documented requirements)*

- **the AI services platform behind the scenes**, providing AI-driven values — summarization etc.
- **Push notices and alerts via Microsoft Teams** — *"now that we are able to
  integrate with Microsoft"*.
- **Interactive experience from the AI services platform and Copilot.**
- Strategic framing: *"That is where we will kill the incumbent GRC platform"* — the AI +
  Teams/Copilot layer is positioned as the differentiator, not the
  CRUD/workflow layer.

---

## 3. Direct ask

> *"Also please tell Claude to document data model and data schema"*

Delivered as `../DATA-MODEL.md`.

---

## 4. Clarification on record

The first message reads: *"Do not use CDN - vendered sql"*.

**Confirmed by the author:** this means **vendored JavaScript and CSS** — a
restatement of the Bootstrap/jQuery vendoring directive above. It is **not** a
database or SQL directive. No database instruction exists in this thread.

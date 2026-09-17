# Front-end foundation

The shared shell, theme system and components every portal screen is built on.

## Ground rules

* **No CDN, no network access.** Bootstrap 5.3.3, jQuery 3.7.1 and Bootstrap
  Icons 1.11.3 are vendored under `vendor/` and verified by `vendor/SHA256SUMS`.
  Reference them only by their `/assets/consilium/vendor/...` paths.
* **No build step.** No npm, no bundler, no preprocessor. Everything here is
  hand-written and served as-is.
* **No third-party table plugin.** `js/consilium-table.js` is the only table
  implementation in the project.
* This CSS is for the custom portal pages. It must not restyle the Desk: every
  rule is scoped under `.cns-portal` or a `cns-` prefixed class.

## Files

| File | Purpose |
|---|---|
| `css/tokens.css` | All design tokens, for both themes. The only file with literal colours. |
| `css/consilium.css` | The portal stylesheet, written entirely against the tokens. |
| `js/consilium.js` | Theme, font size, API client, toasts, announcements. |
| `js/consilium-table.js` | The table component. |
| `../templates/base_portal.html` | The layout every page extends. |
| `../www/ui-kit.html` | Live reference and manual test surface for all of the above. |

## The token system

Tokens are CSS custom properties on `:root`, re-declared under
`[data-theme="dark"]`. Names describe a role, never an appearance or an owner
(`--cns-surface-raised`, not `--cns-light-grey`), so a palette swap is a change
to `tokens.css` alone.

Groups: typography (`--cns-font-root`, `--cns-text-*`, weights, leading),
spacing (`--cns-space-0` … `--cns-space-8`), radius, borders, motion, layout,
z-index, and the colour sets — primary ramp, surfaces, text, borders, and the
semantic status triplets `--cns-{success,warning,danger,info,neutral}` each with
a matching `-bg`, `-border` and `-fg` so a status pill is always contrast-safe
in both themes.

### Font size

`--cns-font-root` is the single knob. `html.cns-root` sets
`font-size: var(--cns-font-root)` and every other size is in `rem`, so changing
that one variable rescales the page coherently. The header control writes it
through `Consilium.fontSize`, which persists the chosen step in `localStorage`
under `cns:fontsize`. Six steps: extra small (13px) through largest (22px).

Because of this, **never use `px` for type or type-derived spacing** in new CSS.
Use the `--cns-text-*` and `--cns-space-*` tokens.

### Theme

`Consilium.theme` writes `data-theme="light|dark"` on `<html>` and persists it
under `cns:theme`. With no stored choice the OS preference is used. A small
inline script in `<head>` of `base_portal.html` applies both the stored theme
and the stored font size before first paint, so there is no flash of the wrong
theme; it duplicates a few lines of `consilium.js` on purpose, because it has to
run before that file is fetched.

To change the palette, edit `tokens.css`. Nothing else should need touching.

## Adding a screen

1. Create `consilium/www/<route>.html`:

   ```jinja
   {% extends "consilium/templates/base_portal.html" %}
   {% block page_content %}
     <section class="cns-card">
       <div class="cns-card-header"><h2 class="cns-card-title">Section</h2></div>
       <div class="cns-card-body"> ... </div>
     </section>
   {% endblock %}
   ```

2. Optionally add `consilium/www/<route>.py` (hyphens become underscores) with a
   `get_context(context)` that sets `page_title`, `page_description`,
   `active_nav` (one of `home`, `forums`, `policies`, `escalations`, `reports`,
   `admin`) and `breadcrumbs` (a list of `{"label", "url"}`; the last entry is
   rendered as the current page).

3. Blocks available: `title`, `head_extra`, `header`, `breadcrumbs`,
   `page_header`, `page_actions`, `page_content`, `footer`, `footer_text`,
   `user_menu_items`, `scripts`.

The layout already provides the navigation, the theme switcher, the font-size
control, the user menu, the skip link and the footer. Do not re-implement them.

### Component classes

`cns-card` / `cns-card-header` / `cns-card-body` / `cns-card-footer`,
`cns-btn` with `cns-btn-{primary,secondary,ghost,danger}` and `-sm` / `-lg`,
`cns-field` + `cns-label` + `cns-input` / `cns-select` / `cns-textarea` +
`cns-help` / `cns-error-text`, `cns-badge` and `cns-pill` with
`cns-status-{success,warning,danger,info,neutral,primary}`, `cns-state` for
empty and error panels, `cns-spinner`, `cns-skeleton`, `cns-workflow` with
`cns-workflow-step[data-state=done|current|pending|blocked]`, and the utilities
`cns-visually-hidden`, `cns-text-muted`, `cns-mono`, `cns-eyebrow`.

`/ui-kit` renders all of them; use it as the reference and check a change there
in both themes before shipping it.

## Configuring a table

Every table gets pagination, column sort, search and a page-size selector. A
screen author writes an options object, not code:

```html
<div id="policy-table"></div>
<script>
  Consilium.Table.create({
    target: "#policy-table",
    doctype: "Policy",                      // or: data: [ ...rows ]
    title: "Policies",
    storageKey: "policy-list",              // namespace for persisted prefs
    filters: { status: ["!=", "Archived"] },
    searchFields: ["name", "title"],
    defaultSort: { field: "modified", order: "desc" },
    pageSize: 25,                           // options: 10 / 25 / 50 / 100
    columns: [
      { field: "name",  label: "Reference", sortable: true,
        formatter: Consilium.Table.formatters.link("/policies/") },
      { field: "title", label: "Title", sortable: true, searchable: true },
      { field: "status", label: "Status",
        formatter: Consilium.Table.formatters.status({
          Active: "success", Draft: "neutral", Expired: "danger" }) },
      { field: "modified", label: "Updated", sortable: true,
        formatter: Consilium.Table.formatters.datetime }
    ]
  });
</script>
```

Or declaratively — put the options in a global and tag the element; the page
wires itself up on load:

```html
<div id="policy-table" data-cns-table="policyTableConfig"></div>
<script>var policyTableConfig = { doctype: "Policy", columns: [ ... ] };</script>
```

**Column options:** `field`, `label`, `sortable`, `searchable`, `formatter`,
`align` (`"end"` for numbers), `width`, `className`, `headerTitle`.

**Formatters** receive `(value, row, column)` and return an HTML string or a DOM
node; they own their escaping. Built in: `text`, `date`, `datetime`, `number`,
`boolean`, `link(prefix)`, `status(map)`, `truncate(length)`. A custom formatter
must escape anything it interpolates — use `Consilium.util.escapeHtml`.

**Where the work happens.** With a `doctype`, pagination, sorting and search all
run on the server: the component sends `limit_start`, `limit_page_length`,
`order_by`, `filters` and `or_filters` to `/api/resource/<DocType>` and asks
`frappe.desk.reportview.get_count` for the total, so it stays correct on large
datasets. It never fetches everything and filters in the browser. Passing `data`
instead switches to an in-memory source with the same behaviour and the same
markup.

**Persistence.** Page size and sort are stored per table under
`cns:table:<storageKey>:*`. Give each table a distinct `storageKey`.

**Accessibility.** The table renders a caption, `scope="col"` headers,
`aria-sort` on sortable columns, labelled pagination buttons with
`aria-current="page"`, a labelled search field, and announces row ranges, sort
changes and page-size changes through a polite live region. Loading, empty and
error states are explicit panels, not blank space.

**Instance methods:** `load()`, `refresh()`, `setPage(n)`, `setPageSize(n)`,
`setSearch(term)`, `toggleSort(field)`, `setFilters(f)`, `setData(rows)`,
`destroy()`.

## The API client

```js
Consilium.api.list("Policy", { fields: ["name"], filters: [], limit_page_length: 20 });
Consilium.api.count("Policy", { filters: [] });
Consilium.api.get("Policy", name);
Consilium.api.create("Policy", doc);
Consilium.api.update("Policy", name, changes);
Consilium.api.remove("Policy", name);
Consilium.api.call("module.method", args, { method: "POST" });
```

It adds the CSRF token to writes, normalises the framework's several error
shapes into a single `Consilium.ApiError` with `message`, `status` and
`payload`, and maintains a loading counter (`data-cns-loading` on `<html>`, plus
a `consilium:loading` event) so pages can show progress consistently.

## Notifications and announcements

```js
Consilium.toast.success("Saved.");
Consilium.toast.error("Could not save.", { title: "Error" });
Consilium.announce("Filtered to 12 records.");   // screen readers only
```

## Events

`consilium:themechange`, `consilium:fontsizechange`, `consilium:loading` — all
dispatched on `document`.

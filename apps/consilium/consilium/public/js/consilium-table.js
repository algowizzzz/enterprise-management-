/* ==========================================================================
   Table component
   --------------------------------------------------------------------------
   A dependency-free, accessible data table. No third-party table plugin is
   used anywhere in this project; this file is the only table implementation.

   Two data sources:
     1. A DocType, read through the REST API. Pagination, sorting and search
        are all done on the server (`limit_start`, `limit_page_length`,
        `order_by`, `filters`, `or_filters`), so behaviour stays correct on
        datasets far larger than a page.
     2. A static array passed as `data`, handled in memory.

   Every table gets pagination, column sort, search and a page-size selector
   that persists per table.

   Minimal use:

     Consilium.Table.create({
       target: "#policy-table",
       doctype: "Policy",
       storageKey: "policy-list",
       columns: [
         { field: "name", label: "Reference", sortable: true,
           formatter: Consilium.Table.formatters.link("/policies/") },
         { field: "title", label: "Title", sortable: true },
         { field: "status", label: "Status",
           formatter: Consilium.Table.formatters.status({ Active: "success" }) },
         { field: "modified", label: "Updated", sortable: true,
           formatter: Consilium.Table.formatters.datetime }
       ]
     });

   Options
     target            (required) element or CSS selector to render into
     doctype           DocType to read; omit when passing `data`
     data              static array of row objects; omit when using `doctype`
     columns           (required) array of column configs, see below
     fields            explicit field list for the API (default: from columns)
     filters           base filters always applied (array or object)
     searchFields      fields the search box matches (default: sortable text
                       columns; falls back to the first column)
     searchPlaceholder placeholder text for the search box
     initialSearch     search text to start with, e.g. the page's ?q= (the
                       header search's "See all" link hands its words over
                       this way)
     pageSize          initial page size (default 25)
     pageSizeOptions   default [10, 25, 50, 100]
     defaultSort       { field: "modified", order: "desc" }
     storageKey        namespace for persisted page size / sort / page
     caption           table caption (visually hidden unless showCaption)
     showCaption       render the caption visibly (default false)
     title             heading shown in the toolbar
     searchable        set false to hide the search box (default true)
     emptyTitle/emptyMessage/emptyIcon   empty-state copy
     exportable        show an "Export CSV" button: every row matching the
                       filters and search, as shown (default false)
     exportName        file name stem for the export (default: storageKey)
     emptyAction       { label, href } or { label, onClick }: the next step an
                       empty list offers (a search offers "Clear the search")
     rowKey            field used as the row key (default "name")
     onRowClick        function(row, event) — makes rows activatable
     compact / striped booleans
     autoLoad          set false to render chrome without loading (default true)

   Column config
     field       field name on the row (and the sort field)
     label       header text
     sortable    boolean
     formatter   function(value, row, column) -> string of HTML, or a
                 DOM node. Formatters own their own escaping; the built-in
                 ones escape everything they interpolate.
     align       "start" | "end"
     width       any CSS width for the column
     className   extra class on the cells
     headerTitle optional title attribute on the header
     searchable  include this field in search (overrides the default)
   ========================================================================== */

(function (window, document) {
  "use strict";

  var NS = (window.Consilium = window.Consilium || {});
  var util = NS.util;

  var DEFAULT_PAGE_SIZES = [10, 25, 50, 100];
  var instanceSeq = 0;

  /* ----------------------------------------------------------------------
     Built-in formatters
     ---------------------------------------------------------------------- */

  var formatters = {
    text: function (value) {
      return util.escapeHtml(value);
    },

    /** A person, shown by name once names are in (see Consilium.person). */
    person: function (value) {
      return NS.person ? NS.person(value) : util.escapeHtml(value);
    },

    date: function (value) {
      return util.escapeHtml(util.formatDate(value, false));
    },

    datetime: function (value) {
      return util.escapeHtml(util.formatDate(value, true));
    },

    /** Right-aligned number with grouping. */
    number: function (value) {
      if (value === null || value === undefined || value === "") return "";
      var n = Number(value);
      return util.escapeHtml(isNaN(n) ? value : n.toLocaleString());
    },

    boolean: function (value) {
      return value
        ? '<span class="cns-pill cns-status-success">Yes</span>'
        : '<span class="cns-pill cns-status-neutral">No</span>';
    },

    /** Link whose href is `prefix + rowKeyValue`. */
    link: function (prefix, keyField) {
      var base = prefix || "";
      var key = keyField || "name";
      return function (value, row) {
        var href = base + encodeURIComponent(row[key] === undefined ? value : row[key]);
        return (
          '<a href="' + util.escapeAttr(href) + '">' + util.escapeHtml(value) + "</a>"
        );
      };
    },

    /**
     * Status pill. `map` maps a raw value to one of
     * success | warning | danger | info | neutral | primary.
     */
    status: function (map, fallback) {
      var lookup = map || {};
      var defaultTone = fallback || "neutral";
      return function (value) {
        if (value === null || value === undefined || value === "") return "";
        var tone = lookup[value] || defaultTone;
        return (
          '<span class="cns-pill cns-status-' +
          util.escapeAttr(tone) +
          '">' +
          util.escapeHtml(value) +
          "</span>"
        );
      };
    },

    /** Truncate long free text, keeping the full value in a title attribute. */
    truncate: function (length) {
      var max = length || 80;
      return function (value) {
        var text = value === null || value === undefined ? "" : String(value);
        if (text.length <= max) return util.escapeHtml(text);
        return (
          '<span title="' +
          util.escapeAttr(text) +
          '">' +
          util.escapeHtml(text.slice(0, max - 1)) +
          "…</span>"
        );
      };
    }
  };

  /* ----------------------------------------------------------------------
     Table
     ---------------------------------------------------------------------- */

  function Table(options) {
    var opts = options || {};

    this.el =
      typeof opts.target === "string" ? document.querySelector(opts.target) : opts.target;
    if (!this.el) throw new Error("Consilium.Table: target element not found");

    if (!opts.columns || !opts.columns.length) {
      throw new Error("Consilium.Table: at least one column is required");
    }
    if (!opts.doctype && !opts.data) {
      throw new Error("Consilium.Table: either `doctype` or `data` is required");
    }

    this.id = "cns-dt-" + ++instanceSeq;
    this.options = opts;
    this.columns = opts.columns;
    this.doctype = opts.doctype || null;
    this.staticData = opts.data || null;
    this.rowKey = opts.rowKey || "name";
    this.searchable = opts.searchable !== false;
    this.storageKey = "table:" + (opts.storageKey || opts.doctype || this.id);

    this.pageSizeOptions = opts.pageSizeOptions || DEFAULT_PAGE_SIZES;

    var storedSize = parseInt(NS.store.get(this.storageKey + ":pageSize", ""), 10);
    this.pageSize =
      this.pageSizeOptions.indexOf(storedSize) !== -1
        ? storedSize
        : opts.pageSize || this.pageSizeOptions[1] || this.pageSizeOptions[0];

    var defaultSort = opts.defaultSort || {};
    this.sortField = NS.store.get(this.storageKey + ":sortField", defaultSort.field || null);
    this.sortOrder =
      NS.store.get(this.storageKey + ":sortOrder", defaultSort.order || "desc") === "asc"
        ? "asc"
        : "desc";

    this.page = 1;
    this.search = this.searchable ? String(opts.initialSearch || "").trim().slice(0, 200) : "";
    this.rows = [];
    this.total = 0;
    this.state = "idle"; // idle | loading | ready | empty | error
    this.error = null;
    this.requestSeq = 0;

    this.searchFields = opts.searchFields || this._defaultSearchFields();

    this._buildChrome();

    if (opts.autoLoad !== false) this.load();
  }

  Table.prototype._defaultSearchFields = function () {
    var explicit = this.columns
      .filter(function (c) {
        return c.searchable === true;
      })
      .map(function (c) {
        return c.field;
      });
    if (explicit.length) return explicit;
    // Fall back to the key field only — matching every column blindly would
    // produce invalid filters on link/date/number fields.
    return [this.rowKey];
  };

  /* --- chrome ---------------------------------------------------------- */

  Table.prototype._buildChrome = function () {
    var self = this;
    var opts = this.options;

    this.el.classList.add("cns-datatable");
    this.el.innerHTML = "";

    /* Toolbar: title + search + page size */
    var toolbarChildren = [];

    /* The title carries the record count once it is known, so every list
       says how many rows match in the same place. */
    this.countBadge = util.el("span", { class: "cns-badge cns-badge--count cns-dt-count", hidden: "hidden" });
    var toolbarStart = util.el("div", { class: "cns-dt-toolbar-start" }, [
      opts.title
        ? util.el("h2", { class: "cns-card-title", id: this.id + "-title" }, [
            document.createTextNode(opts.title + " "),
            this.countBadge
          ])
        : null,
      opts.description
        ? util.el("p", { class: "cns-card-subtitle", text: opts.description })
        : null
    ]);
    toolbarChildren.push(toolbarStart);

    var toolbarEnd = util.el("div", { class: "cns-dt-toolbar-end" });

    if (this.searchable) {
      var searchId = this.id + "-search";
      this.searchInput = util.el("input", {
        type: "search",
        id: searchId,
        class: "cns-input",
        placeholder: opts.searchPlaceholder || "Search",
        autocomplete: "off"
      });
      if (this.search) this.searchInput.value = this.search;
      this.searchInput.addEventListener(
        "input",
        util.debounce(function () {
          self.setSearch(self.searchInput.value);
        }, 300)
      );
      // Enter searches immediately rather than waiting out the debounce.
      this.searchInput.addEventListener("keydown", function (event) {
        if (event.key === "Enter") {
          event.preventDefault();
          self.setSearch(self.searchInput.value);
        }
      });
      toolbarEnd.appendChild(
        util.el("div", { class: "cns-search" }, [
          util.el("label", {
            class: "cns-visually-hidden",
            for: searchId,
            text: opts.searchLabel || "Search this table"
          }),
          util.el("i", { class: "bi bi-search", "aria-hidden": "true" }),
          this.searchInput
        ])
      );
    }

    if (opts.exportable) {
      this.exportButton = util.el("button", {
        type: "button",
        class: "cns-btn cns-btn-ghost cns-btn-sm",
        title: "Download the rows that match the filters and search as a CSV file"
      }, [
        util.el("i", { class: "bi bi-download", "aria-hidden": "true" }),
        document.createTextNode(" Export CSV")
      ]);
      this.exportButton.addEventListener("click", function () { self.exportCsv(); });
      toolbarEnd.appendChild(this.exportButton);
    }

    var sizeId = this.id + "-pagesize";
    this.pageSizeSelect = util.el("select", { id: sizeId, class: "cns-select" });
    this.pageSizeOptions.forEach(function (size) {
      var option = util.el("option", { value: String(size), text: String(size) });
      if (size === self.pageSize) option.selected = true;
      self.pageSizeSelect.appendChild(option);
    });
    this.pageSizeSelect.addEventListener("change", function () {
      self.setPageSize(parseInt(self.pageSizeSelect.value, 10));
    });
    toolbarEnd.appendChild(
      util.el("div", { class: "cns-dt-pagesize" }, [
        util.el("label", { for: sizeId, text: "Rows per page" }),
        this.pageSizeSelect
      ])
    );

    toolbarChildren.push(toolbarEnd);
    this.el.appendChild(util.el("div", { class: "cns-dt-toolbar" }, toolbarChildren));

    /* Table */
    this.tableWrap = util.el("div", { class: "cns-table-wrap" });
    this.table = util.el("table", {
      class:
        "cns-table" +
        (opts.striped ? " cns-table--striped" : "") +
        (opts.compact ? " cns-table--compact" : ""),
      id: this.id + "-table"
    });

    var caption = opts.caption || opts.title || "Data table";
    this.caption = util.el("caption", {
      class: opts.showCaption ? "cns-text-sm cns-text-muted" : "cns-visually-hidden",
      text: caption
    });
    this.table.appendChild(this.caption);

    this.thead = util.el("thead");
    this.headerRow = util.el("tr");
    this.thead.appendChild(this.headerRow);
    this.table.appendChild(this.thead);

    this.tbody = util.el("tbody");
    this.table.appendChild(this.tbody);

    this._renderHeader();
    this.tableWrap.appendChild(this.table);
    this.el.appendChild(this.tableWrap);

    /* State panel (loading / empty / error) replaces the table body area */
    this.statePanel = util.el("div", { class: "cns-dt-state", hidden: true });
    this.el.appendChild(this.statePanel);

    /* Footer: status + pagination */
    this.statusEl = util.el("div", { class: "cns-dt-status" });
    this.pagerNav = util.el("nav", { "aria-label": caption + " pagination" });
    this.pagerList = util.el("ul", { class: "cns-pagination" });
    this.pagerNav.appendChild(this.pagerList);
    this.el.appendChild(
      util.el("div", { class: "cns-dt-footer" }, [this.statusEl, this.pagerNav])
    );
  };

  Table.prototype._renderHeader = function () {
    var self = this;
    this.headerRow.innerHTML = "";

    this.columns.forEach(function (column) {
      var th = util.el("th", { scope: "col" });
      if (column.width) th.style.width = column.width;
      if (column.align === "end") th.classList.add("cns-num");
      if (column.headerTitle) th.title = column.headerTitle;

      if (column.sortable) {
        var isSorted = self.sortField === column.field;
        th.setAttribute(
          "aria-sort",
          isSorted ? (self.sortOrder === "asc" ? "ascending" : "descending") : "none"
        );
        var indicator = util.el("span", {
          class: "cns-sort-indicator bi " +
            (isSorted
              ? self.sortOrder === "asc"
                ? "bi-sort-up-alt"
                : "bi-sort-down"
              : "bi-arrow-down-up"),
          "aria-hidden": "true"
        });
        var button = util.el(
          "button",
          {
            type: "button",
            class: "cns-sort-btn",
            "aria-label":
              "Sort by " +
              column.label +
              (isSorted && self.sortOrder === "asc" ? ", descending" : ", ascending")
          },
          [document.createTextNode(column.label), indicator]
        );
        button.addEventListener("click", function () {
          self.toggleSort(column.field);
        });
        th.appendChild(button);
      } else {
        th.textContent = column.label;
      }
      self.headerRow.appendChild(th);
    });
  };

  /* --- state rendering -------------------------------------------------- */

  Table.prototype._showState = function (kind, title, message, actionLabel, action) {
    this.statePanel.hidden = false;
    this.statePanel.innerHTML = "";
    this.tableWrap.hidden = true;

    var icon;
    if (kind === "loading") {
      icon = util.el("span", { class: "cns-spinner cns-spinner--lg", "aria-hidden": "true" });
    } else {
      icon = util.el("span", { class: "cns-state-icon" }, [
        util.el("i", {
          class: "bi " + (kind === "error" ? "bi-exclamation-triangle"
            : (this.search ? "bi-search" : this.options.emptyIcon || "bi-inbox")),
          "aria-hidden": "true"
        })
      ]);
    }

    var children = [
      icon,
      util.el("p", { class: "cns-state-title", text: title }),
      message ? util.el("p", { class: "cns-state-message", text: message }) : null
    ];

    if (actionLabel && action) {
      var btn = util.el("button", {
        type: "button",
        class: "cns-btn cns-btn-secondary",
        text: actionLabel
      });
      btn.addEventListener("click", action);
      children.push(btn);
    }

    this.statePanel.appendChild(
      util.el(
        "div",
        {
          class: "cns-state" + (kind === "error" ? " cns-state--error" : ""),
          role: kind === "error" ? "alert" : "status",
          "aria-live": kind === "error" ? "assertive" : "polite"
        },
        children
      )
    );
  };

  Table.prototype._hideState = function () {
    this.statePanel.hidden = true;
    this.statePanel.innerHTML = "";
    this.tableWrap.hidden = false;
  };

  /* --- query building --------------------------------------------------- */

  Table.prototype._fields = function () {
    if (this.options.fields) return this.options.fields;
    var fields = this.columns
      .map(function (c) {
        return c.field;
      })
      .filter(function (f) {
        return !!f;
      });
    if (fields.indexOf(this.rowKey) === -1) fields.push(this.rowKey);
    // Extra fields a formatter might need but that have no column of their own.
    (this.options.extraFields || []).forEach(function (f) {
      if (fields.indexOf(f) === -1) fields.push(f);
    });
    return fields;
  };

  Table.prototype._baseFilters = function () {
    var filters = this.options.filters;
    if (!filters) return [];
    if (Array.isArray(filters)) return filters.slice();
    // Object form { field: value } or { field: [operator, value] }
    return Object.keys(filters).map(function (field) {
      var value = filters[field];
      return Array.isArray(value) ? [field, value[0], value[1]] : [field, "=", value];
    });
  };

  Table.prototype._orFilters = function () {
    if (!this.search) return null;
    var term = "%" + this.search + "%";
    return this.searchFields.map(function (field) {
      return [field, "like", term];
    });
  };

  Table.prototype._orderBy = function () {
    if (!this.sortField) return undefined;
    return this.sortField + " " + (this.sortOrder === "asc" ? "asc" : "desc");
  };

  /* --- loading ---------------------------------------------------------- */

  Table.prototype.load = function () {
    return this.staticData ? this._loadStatic() : this._loadRemote();
  };

  Table.prototype.refresh = function () {
    return this.load();
  };

  Table.prototype._loadRemote = function () {
    var self = this;
    var seq = ++this.requestSeq;

    this.state = "loading";
    this._showState(
      "loading",
      "Loading data",
      this.options.loadingMessage || "Fetching records from the server."
    );
    this._renderFooter();

    var filters = this._baseFilters();
    var orFilters = this._orFilters();
    var start = (this.page - 1) * this.pageSize;

    var listPromise = NS.api.list(this.doctype, {
      fields: this._fields(),
      filters: filters,
      or_filters: orFilters,
      order_by: this._orderBy(),
      limit_start: start,
      limit_page_length: this.pageSize
    });

    var countPromise = NS.api.count(this.doctype, {
      filters: filters,
      or_filters: orFilters
    });

    return Promise.all([listPromise, countPromise])
      .then(function (results) {
        if (seq !== self.requestSeq) return; // a newer request superseded this one
        self.rows = results[0] || [];
        self.total = results[1] || 0;
        // A page beyond the end (after a search narrowed the result set)
        // silently falls back to the last page.
        var lastPage = Math.max(1, Math.ceil(self.total / self.pageSize));
        if (self.page > lastPage && self.total > 0) {
          self.page = lastPage;
          return self._loadRemote();
        }
        self.error = null;
        self.state = self.rows.length ? "ready" : "empty";
        self._render();
      })
      .catch(function (error) {
        if (seq !== self.requestSeq) return;
        if (error && error.name === "AbortError") return;
        self.error = error;
        self.state = "error";
        self._render();
      });
  };

  Table.prototype._loadStatic = function () {
    var self = this;
    var rows = this.staticData.slice();

    if (this.search) {
      var needle = this.search.toLowerCase();
      var fields = this.options.searchFields || this.columns.map(function (c) {
        return c.field;
      });
      rows = rows.filter(function (row) {
        return fields.some(function (field) {
          var value = row[field];
          return (
            value !== null &&
            value !== undefined &&
            String(value).toLowerCase().indexOf(needle) !== -1
          );
        });
      });
    }

    if (this.sortField) {
      var field = this.sortField;
      var dir = this.sortOrder === "asc" ? 1 : -1;
      rows.sort(function (a, b) {
        var av = a[field];
        var bv = b[field];
        if (av === bv) return 0;
        if (av === null || av === undefined) return 1;
        if (bv === null || bv === undefined) return -1;
        if (typeof av === "number" && typeof bv === "number") return (av - bv) * dir;
        return String(av).localeCompare(String(bv)) * dir;
      });
    }

    this.total = rows.length;
    var lastPage = Math.max(1, Math.ceil(this.total / this.pageSize));
    if (this.page > lastPage) this.page = lastPage;
    var start = (this.page - 1) * this.pageSize;
    this.rows = rows.slice(start, start + this.pageSize);
    this.error = null;
    this.state = this.rows.length ? "ready" : "empty";
    this._render();
    return Promise.resolve(self.rows);
  };

  /* --- rendering -------------------------------------------------------- */

  Table.prototype._render = function () {
    if (this.state === "error") {
      var self = this;
      this._showState(
        "error",
        this.options.errorTitle || "Could not load data",
        (this.error && this.error.message) || "An unexpected error occurred.",
        "Try again",
        function () {
          self.load();
        }
      );
      this._renderFooter();
      NS.announce("Error loading table data.");
      return;
    }

    if (this.state === "empty") {
      /* An empty list always offers a way on: clearing the search when there
         is one, otherwise the page's own next step (``emptyAction``: a label
         with an ``href`` or an ``onClick``) when it gives one. */
      var that = this;
      var next = this.options.emptyAction;
      var label = null;
      var act = null;
      if (this.search && this.searchInput) {
        label = "Clear the search";
        act = function () {
          that.searchInput.value = "";
          that.setSearch("");
          that.searchInput.focus();
        };
      } else if (next && next.label && (next.href || typeof next.onClick === "function")) {
        label = next.label;
        act = next.onClick || function () { window.location.href = next.href; };
      }
      this._showState(
        "empty",
        this.search ? "No matching records" : this.options.emptyTitle || "Nothing here yet",
        this.search
          ? 'No records match "' + this.search + '"' +
            (this.options.emptyMessage ? ". " + this.options.emptyMessage : ".")
          : this.options.emptyMessage || "There are no records to display.",
        label,
        act
      );
      this._renderFooter();
      NS.announce("No records found.");
      return;
    }

    this._hideState();
    this._renderHeader();
    this._renderBody();
    this._renderFooter();

    var first = (this.page - 1) * this.pageSize + 1;
    var last = first + this.rows.length - 1;
    NS.announce(
      "Showing rows " + first + " to " + last + " of " + this.total + "."
    );
  };

  Table.prototype._renderBody = function () {
    var self = this;
    var fragment = document.createDocumentFragment();

    this.rows.forEach(function (row) {
      var tr = util.el("tr");
      if (row[self.rowKey] !== undefined) {
        tr.setAttribute("data-row-key", row[self.rowKey]);
      }

      self.columns.forEach(function (column) {
        var td = util.el("td");
        if (column.align === "end") td.classList.add("cns-num");
        if (column.className) td.className += " " + column.className;

        var value = row[column.field];
        if (typeof column.formatter === "function") {
          var out = column.formatter(value, row, column);
          if (out && out.nodeType === 1) td.appendChild(out);
          else td.innerHTML = out === undefined || out === null ? "" : out;
        } else {
          td.textContent = value === null || value === undefined ? "" : String(value);
        }
        tr.appendChild(td);
      });

      if (typeof self.options.onRowClick === "function") {
        tr.tabIndex = 0;
        tr.style.cursor = "pointer";
        tr.addEventListener("click", function (event) {
          self.options.onRowClick(row, event);
        });
        tr.addEventListener("keydown", function (event) {
          if (event.key === "Enter" || event.key === " ") {
            event.preventDefault();
            self.options.onRowClick(row, event);
          }
        });
      }

      fragment.appendChild(tr);
    });

    this.tbody.innerHTML = "";
    this.tbody.appendChild(fragment);
  };

  Table.prototype._renderFooter = function () {
    var self = this;
    var lastPage = Math.max(1, Math.ceil(this.total / this.pageSize));

    if (this.countBadge) {
      var known = this.state === "ready" || this.state === "empty";
      this.countBadge.hidden = !known;
      this.countBadge.textContent = known ? String(this.total) : "";
      this.countBadge.setAttribute("aria-label", this.total + (this.total === 1 ? " record" : " records"));
    }
    if (this.exportButton) this.exportButton.disabled = !(this.state === "ready" && this.total > 0);

    if (this.state === "loading") {
      this.statusEl.textContent = "Loading…";
    } else if (!this.total) {
      this.statusEl.textContent = "No records";
    } else {
      var first = (this.page - 1) * this.pageSize + 1;
      var last = Math.min(this.total, first + this.pageSize - 1);
      this.statusEl.textContent =
        "Showing " + first + "–" + last + " of " + this.total +
        (this.total === 1 ? " record" : " records");
    }

    this.pagerList.innerHTML = "";
    if (this.state === "loading" || this.total === 0) return;

    function pageButton(label, page, options) {
      var opts = options || {};
      var li = util.el("li");
      var btn = util.el("button", {
        type: "button",
        class: "cns-page-btn",
        "aria-label": opts.ariaLabel || "Page " + page
      });
      btn.innerHTML = label;
      if (opts.current) btn.setAttribute("aria-current", "page");
      if (opts.disabled) btn.disabled = true;
      btn.addEventListener("click", function () {
        self.setPage(page);
      });
      li.appendChild(btn);
      return li;
    }

    function ellipsis() {
      return util.el("li", {
        class: "cns-page-ellipsis",
        "aria-hidden": "true",
        text: "…"
      });
    }

    this.pagerList.appendChild(
      pageButton('<i class="bi bi-chevron-double-left" aria-hidden="true"></i>', 1, {
        ariaLabel: "First page",
        disabled: this.page === 1
      })
    );
    this.pagerList.appendChild(
      pageButton('<i class="bi bi-chevron-left" aria-hidden="true"></i>', this.page - 1, {
        ariaLabel: "Previous page",
        disabled: this.page === 1
      })
    );

    // A compact window of page numbers around the current page.
    var windowSize = 2;
    var pages = [];
    for (var p = 1; p <= lastPage; p++) {
      if (p === 1 || p === lastPage || Math.abs(p - this.page) <= windowSize) pages.push(p);
    }
    var previous = 0;
    pages.forEach(function (p) {
      if (previous && p - previous > 1) self.pagerList.appendChild(ellipsis());
      self.pagerList.appendChild(
        pageButton(String(p), p, { current: p === self.page })
      );
      previous = p;
    });

    this.pagerList.appendChild(
      pageButton('<i class="bi bi-chevron-right" aria-hidden="true"></i>', this.page + 1, {
        ariaLabel: "Next page",
        disabled: this.page === lastPage
      })
    );
    this.pagerList.appendChild(
      pageButton(
        '<i class="bi bi-chevron-double-right" aria-hidden="true"></i>',
        lastPage,
        { ariaLabel: "Last page", disabled: this.page === lastPage }
      )
    );
  };

  /* --- public state changes -------------------------------------------- */

  Table.prototype.setPage = function (page) {
    var lastPage = Math.max(1, Math.ceil(this.total / this.pageSize));
    var next = Math.max(1, Math.min(lastPage, page));
    if (next === this.page) return;
    this.page = next;
    this.load();
  };

  Table.prototype.setPageSize = function (size) {
    if (!size || size === this.pageSize) return;
    this.pageSize = size;
    this.page = 1;
    NS.store.set(this.storageKey + ":pageSize", size);
    if (this.pageSizeSelect) this.pageSizeSelect.value = String(size);
    NS.announce("Page size set to " + size + " rows.");
    this.load();
  };

  Table.prototype.setSearch = function (term) {
    var value = (term || "").trim();
    if (value === this.search) return;
    this.search = value;
    this.page = 1;
    this.load();
  };

  Table.prototype.toggleSort = function (field) {
    if (this.sortField === field) {
      this.sortOrder = this.sortOrder === "asc" ? "desc" : "asc";
    } else {
      this.sortField = field;
      this.sortOrder = "asc";
    }
    this.page = 1;
    NS.store.set(this.storageKey + ":sortField", this.sortField);
    NS.store.set(this.storageKey + ":sortOrder", this.sortOrder);
    NS.announce(
      "Sorted by " + field + ", " + (this.sortOrder === "asc" ? "ascending" : "descending") + "."
    );
    this.load();
  };

  Table.prototype.setFilters = function (filters) {
    this.options.filters = filters;
    this.page = 1;
    this.load();
  };

  /* --- export ------------------------------------------------------------ */

  /** A cell as the screen shows it: the formatter's text, not its markup. */
  Table.prototype._cellText = function (column, row) {
    var value = row[column.field];
    if (typeof column.exportValue === "function") return column.exportValue(value, row, column);
    if (typeof column.formatter === "function") {
      var out = column.formatter(value, row, column);
      if (out && out.nodeType === 1) return out.textContent.trim();
      var scratch = document.createElement("div");
      scratch.innerHTML = out === undefined || out === null ? "" : String(out);
      return scratch.textContent.replace(/\s+/g, " ").trim();
    }
    return value === null || value === undefined ? "" : String(value);
  };

  /**
   * Download every row matching the current filters and search, in the
   * current order, as CSV. The rows are read through the same list API and
   * the same filters as the table, so the file holds nothing the screen would
   * not show. Capped at EXPORT_LIMIT rows, and says so when the cap bites.
   */
  Table.prototype.exportCsv = function () {
    var self = this;
    var EXPORT_LIMIT = 5000;
    var columns = this.columns.filter(function (c) { return c.field && c.exportable !== false; });
    var rowsPromise = this.staticData
      ? Promise.resolve(this.staticData)
      : NS.api.list(this.doctype, {
          fields: this._fields(),
          filters: this._baseFilters(),
          or_filters: this._orFilters(),
          order_by: this._orderBy(),
          limit_start: 0,
          limit_page_length: EXPORT_LIMIT
        });
    if (this.exportButton) this.exportButton.disabled = true;
    return rowsPromise
      .then(function (rows) {
        rows = rows || [];
        function cell(text) {
          var value = String(text === null || text === undefined ? "" : text);
          // A leading = + - @ would be run as a formula by a spreadsheet.
          if (/^[=+\-@\t\r]/.test(value)) value = "'" + value;
          return /[",\n\r]/.test(value) ? '"' + value.replace(/"/g, '""') + '"' : value;
        }
        var lines = [columns.map(function (c) { return cell(c.label || c.field); }).join(",")];
        rows.forEach(function (row) {
          lines.push(columns.map(function (c) { return cell(self._cellText(c, row)); }).join(","));
        });
        var blob = new Blob(["\ufeff" + lines.join("\r\n")], { type: "text/csv;charset=utf-8" });
        var d = new Date();
        var stamp = d.getFullYear() + "-" + String(d.getMonth() + 1).padStart(2, "0") + "-" +
          String(d.getDate()).padStart(2, "0");
        var name = String(self.options.exportName || self.options.storageKey || self.doctype || "table")
          .toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
        var link = document.createElement("a");
        link.href = URL.createObjectURL(blob);
        link.download = name + "-" + stamp + ".csv";
        document.body.appendChild(link);
        link.click();
        window.setTimeout(function () { URL.revokeObjectURL(link.href); link.remove(); }, 0);
        var capped = !self.staticData && self.total > rows.length;
        NS.toast[capped ? "warning" : "success"](
          capped
            ? "The first " + rows.length + " of " + self.total + " rows were exported. Narrow the filters to export the rest."
            : rows.length + (rows.length === 1 ? " row" : " rows") + " exported."
        );
      })
      .catch(function (error) {
        NS.toast.error((error && error.message) || "The rows could not be read.", { title: "Export failed" });
      })
      .then(function () {
        if (self.exportButton) self.exportButton.disabled = !(self.total > 0);
      });
  };

  Table.prototype.setData = function (rows) {
    this.staticData = rows || [];
    this.page = 1;
    this.load();
  };

  Table.prototype.destroy = function () {
    this.requestSeq++;
    this.el.innerHTML = "";
    this.el.classList.remove("cns-datatable");
  };

  /* ----------------------------------------------------------------------
     Public surface
     ---------------------------------------------------------------------- */

  NS.Table = {
    Table: Table,
    formatters: formatters,

    create: function (options) {
      return new Table(options);
    },

    /**
     * Declarative init: any element carrying `data-cns-table="<globalName>"`
     * is rendered from the options object at `window[globalName]`. Screen
     * authors can therefore write configuration in a <script> block and let
     * the page wire itself up.
     */
    autoInit: function (root) {
      var scope = root || document;
      Array.prototype.forEach.call(
        scope.querySelectorAll("[data-cns-table]"),
        function (node) {
          if (node.hasAttribute("data-cns-table-ready")) return;
          var name = node.getAttribute("data-cns-table");
          var config = name ? window[name] : null;
          if (!config) return;
          node.setAttribute("data-cns-table-ready", "");
          config.target = node;
          node.cnsTable = new Table(config);
        }
      );
    }
  };
})(window, document);

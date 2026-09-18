/* ==========================================================================
   Core portal runtime
   --------------------------------------------------------------------------
   No build step, no bundler, no dependencies. This file is served as written.
   It exposes a single global namespace, `Consilium`, with four parts:

     Consilium.theme     light/dark switching, persisted
     Consilium.fontSize  root font-size scaling, persisted
     Consilium.api       thin client over the framework REST endpoints
     Consilium.toast     transient notifications

   The theme and font size are also applied by a tiny inline bootstrap in the
   page <head> (see `Consilium.boot` below and base_portal.html) so the stored
   preference is on <html> before first paint and there is no flash.
   ========================================================================== */

(function (window, document) {
  "use strict";

  var NS = (window.Consilium = window.Consilium || {});

  /* ----------------------------------------------------------------------
     Storage — localStorage can throw (private mode, blocked site data), so
     every read and write is guarded and the app works without it.
     ---------------------------------------------------------------------- */

  var STORAGE_PREFIX = "cns:";

  var store = (NS.store = {
    get: function (key, fallback) {
      try {
        var v = window.localStorage.getItem(STORAGE_PREFIX + key);
        return v === null ? fallback : v;
      } catch (e) {
        return fallback;
      }
    },
    set: function (key, value) {
      try {
        window.localStorage.setItem(STORAGE_PREFIX + key, String(value));
        return true;
      } catch (e) {
        return false;
      }
    },
    remove: function (key) {
      try {
        window.localStorage.removeItem(STORAGE_PREFIX + key);
      } catch (e) {
        /* ignore */
      }
    }
  });

  /* ----------------------------------------------------------------------
     Tiny helpers
     ---------------------------------------------------------------------- */

  /* Wall-clock time in the site's zone -> the instant it names. Uses only the
     browser's own zone data (Intl), so nothing is fetched. */
  function fromSiteZone(m) {
    var zone = (document.querySelector('meta[name="cns-time-zone"]') || {}).content || "UTC";
    var asUtc = Date.UTC(+m[1], +m[2] - 1, +m[3], +m[4], +m[5], +(m[6] || 0));
    try {
      var probe = new Date(asUtc);
      var there = new Date(probe.toLocaleString("en-US", { timeZone: zone }));
      var utc = new Date(probe.toLocaleString("en-US", { timeZone: "UTC" }));
      return new Date(asUtc - (there.getTime() - utc.getTime()));
    } catch (e) {
      return new Date(asUtc); // an unknown zone name: treat as UTC, still labelled
    }
  }

  var util = (NS.util = {
    /** Escape a value for safe insertion as HTML text. */
    escapeHtml: function (value) {
      if (value === null || value === undefined) return "";
      return String(value)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#39;");
    },

    /** Escape a value for use inside an HTML attribute. */
    escapeAttr: function (value) {
      return util.escapeHtml(value);
    },

    /** Debounce — used by the table's search box. */
    debounce: function (fn, wait) {
      var timer = null;
      return function () {
        var self = this;
        var args = arguments;
        if (timer) window.clearTimeout(timer);
        timer = window.setTimeout(function () {
          timer = null;
          fn.apply(self, args);
        }, wait || 250);
      };
    },

    /** Create an element with attributes and children in one call. */
    el: function (tag, attrs, children) {
      var node = document.createElement(tag);
      if (attrs) {
        Object.keys(attrs).forEach(function (name) {
          var value = attrs[name];
          if (value === null || value === undefined || value === false) return;
          if (name === "text") {
            node.textContent = value;
          } else if (name === "html") {
            node.innerHTML = value;
          } else if (name === "class") {
            node.className = value;
          } else if (name.indexOf("on") === 0 && typeof value === "function") {
            node.addEventListener(name.slice(2).toLowerCase(), value);
          } else {
            node.setAttribute(name, value === true ? "" : value);
          }
        });
      }
      (children || []).forEach(function (child) {
        if (child === null || child === undefined) return;
        node.appendChild(typeof child === "string" ? document.createTextNode(child) : child);
      });
      return node;
    },

    /** ISO / framework datetime string -> locale date string. */
    formatDate: function (value, withTime) {
      if (!value) return "";
      /* A bare date is a calendar day, not an instant. `new Date("2026-09-17")`
         reads it as midnight UTC, which west of UTC is the previous evening —
         so every due date, review date and seat date showed a day early. Build
         it from its parts in local time instead. */
      var text = String(value);
      var ymd = /^(\d{4})-(\d{2})-(\d{2})$/.exec(text);
      /* A timestamp from the server carries no zone: it is in the site's time
         zone. Read as the browser's own zone it was hours out and unlabelled,
         so it is converted from the site's zone and shown with the reader's. */
      var naive = /^(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2})(?::(\d{2}))?/.exec(text);
      var zoned = /(?:Z|[+-]\d{2}:?\d{2})$/.test(text);
      var d = value instanceof Date ? value
        : ymd ? new Date(+ymd[1], +ymd[2] - 1, +ymd[3])
        : naive && !zoned ? fromSiteZone(naive)
        : new Date(text.replace(" ", "T"));
      if (isNaN(d.getTime())) return text;
      var opts = { year: "numeric", month: "short", day: "2-digit" };
      if (withTime) {
        opts.hour = "2-digit";
        opts.minute = "2-digit";
        opts.timeZoneName = "short";
      }
      return d.toLocaleString(undefined, opts);
    }
  });

  /* ----------------------------------------------------------------------
     Theme
     ---------------------------------------------------------------------- */

  var THEME_KEY = "theme";
  var THEMES = ["light", "dark"];

  var theme = (NS.theme = {
    /** The stored preference, or the OS preference, or light. */
    resolve: function () {
      var stored = store.get(THEME_KEY, null);
      if (THEMES.indexOf(stored) !== -1) return stored;
      try {
        if (window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches) {
          return "dark";
        }
      } catch (e) {
        /* ignore */
      }
      return "light";
    },

    current: function () {
      return document.documentElement.getAttribute("data-theme") || theme.resolve();
    },

    /** Apply without persisting (used by the pre-paint bootstrap). */
    apply: function (name) {
      var value = THEMES.indexOf(name) === -1 ? "light" : name;
      document.documentElement.setAttribute("data-theme", value);
      return value;
    },

    /** Apply and persist, then notify listeners. */
    set: function (name) {
      var value = theme.apply(name);
      store.set(THEME_KEY, value);
      theme.syncControls();
      document.dispatchEvent(
        new CustomEvent("consilium:themechange", { detail: { theme: value } })
      );
      return value;
    },

    toggle: function () {
      return theme.set(theme.current() === "dark" ? "light" : "dark");
    },

    /** Keep every [data-cns-theme-toggle] button labelled and pressed-state correct. */
    syncControls: function () {
      var isDark = theme.current() === "dark";
      var nodes = document.querySelectorAll("[data-cns-theme-toggle]");
      Array.prototype.forEach.call(nodes, function (node) {
        node.setAttribute("aria-pressed", isDark ? "true" : "false");
        node.setAttribute(
          "aria-label",
          isDark ? "Switch to light theme" : "Switch to dark theme"
        );
        node.setAttribute("title", isDark ? "Switch to light theme" : "Switch to dark theme");
        var icon = node.querySelector("[data-cns-theme-icon]");
        if (icon) icon.className = isDark ? "bi bi-sun-fill" : "bi bi-moon-stars-fill";
        var label = node.querySelector("[data-cns-theme-label]");
        if (label) label.textContent = isDark ? "Light" : "Dark";
      });
    },

    bind: function (root) {
      var scope = root || document;
      Array.prototype.forEach.call(
        scope.querySelectorAll("[data-cns-theme-toggle]"),
        function (node) {
          if (node.hasAttribute("data-cns-bound")) return;
          node.setAttribute("data-cns-bound", "");
          node.addEventListener("click", function (event) {
            event.preventDefault();
            theme.toggle();
          });
        }
      );
      theme.syncControls();
    }
  });

  /* ----------------------------------------------------------------------
     Font size
     The control writes --cns-font-root on <html>; every dimension in the
     stylesheets is in rem, so one variable rescales the page.
     ---------------------------------------------------------------------- */

  var FONT_KEY = "fontsize";

  var FONT_STEPS = [
    { id: "xs", label: "Extra small", px: 13 },
    { id: "sm", label: "Small", px: 15 },
    { id: "md", label: "Default", px: 16 },
    { id: "lg", label: "Large", px: 18 },
    { id: "xl", label: "Extra large", px: 20 },
    { id: "xxl", label: "Largest", px: 22 }
  ];
  var FONT_DEFAULT_INDEX = 2;

  function fontIndexOf(id) {
    for (var i = 0; i < FONT_STEPS.length; i++) {
      if (FONT_STEPS[i].id === id) return i;
    }
    return -1;
  }

  var fontSize = (NS.fontSize = {
    steps: FONT_STEPS,

    resolve: function () {
      var idx = fontIndexOf(store.get(FONT_KEY, null));
      return idx === -1 ? FONT_DEFAULT_INDEX : idx;
    },

    currentIndex: function () {
      var idx = fontIndexOf(document.documentElement.getAttribute("data-font-size"));
      return idx === -1 ? fontSize.resolve() : idx;
    },

    current: function () {
      return FONT_STEPS[fontSize.currentIndex()];
    },

    /** Apply without persisting (used by the pre-paint bootstrap). */
    apply: function (index) {
      var i = Math.max(0, Math.min(FONT_STEPS.length - 1, Number(index)));
      if (isNaN(i)) i = FONT_DEFAULT_INDEX;
      var step = FONT_STEPS[i];
      document.documentElement.setAttribute("data-font-size", step.id);
      document.documentElement.style.setProperty("--cns-font-root", step.px + "px");
      return step;
    },

    set: function (index) {
      var step = fontSize.apply(index);
      store.set(FONT_KEY, step.id);
      fontSize.syncControls();
      document.dispatchEvent(
        new CustomEvent("consilium:fontsizechange", { detail: { step: step } })
      );
      return step;
    },

    setById: function (id) {
      var idx = fontIndexOf(id);
      return fontSize.set(idx === -1 ? FONT_DEFAULT_INDEX : idx);
    },

    increase: function () {
      return fontSize.set(fontSize.currentIndex() + 1);
    },
    decrease: function () {
      return fontSize.set(fontSize.currentIndex() - 1);
    },
    reset: function () {
      return fontSize.set(FONT_DEFAULT_INDEX);
    },

    syncControls: function () {
      var idx = fontSize.currentIndex();
      var step = FONT_STEPS[idx];
      Array.prototype.forEach.call(
        document.querySelectorAll("[data-cns-fontsize-label]"),
        function (node) {
          node.textContent = step.label;
        }
      );
      Array.prototype.forEach.call(
        document.querySelectorAll("[data-cns-fontsize-value]"),
        function (node) {
          node.setAttribute("aria-valuenow", String(idx + 1));
          node.setAttribute("aria-valuetext", step.label + " text size");
        }
      );
      Array.prototype.forEach.call(
        document.querySelectorAll('[data-cns-fontsize="decrease"]'),
        function (node) {
          node.disabled = idx <= 0;
        }
      );
      Array.prototype.forEach.call(
        document.querySelectorAll('[data-cns-fontsize="increase"]'),
        function (node) {
          node.disabled = idx >= FONT_STEPS.length - 1;
        }
      );
      Array.prototype.forEach.call(
        document.querySelectorAll("select[data-cns-fontsize-select]"),
        function (node) {
          node.value = step.id;
        }
      );
    },

    bind: function (root) {
      var scope = root || document;
      Array.prototype.forEach.call(
        scope.querySelectorAll("[data-cns-fontsize]"),
        function (node) {
          if (node.hasAttribute("data-cns-bound")) return;
          node.setAttribute("data-cns-bound", "");
          node.addEventListener("click", function (event) {
            event.preventDefault();
            var action = node.getAttribute("data-cns-fontsize");
            if (action === "increase") fontSize.increase();
            else if (action === "decrease") fontSize.decrease();
            else if (action === "reset") fontSize.reset();
            else fontSize.setById(action);
          });
        }
      );
      Array.prototype.forEach.call(
        scope.querySelectorAll("select[data-cns-fontsize-select]"),
        function (node) {
          if (node.hasAttribute("data-cns-bound")) return;
          node.setAttribute("data-cns-bound", "");
          node.addEventListener("change", function () {
            fontSize.setById(node.value);
          });
        }
      );
      fontSize.syncControls();
    }
  });

  /* ----------------------------------------------------------------------
     Pre-paint bootstrap
     Called from an inline <script> in <head> before any content renders.
     ---------------------------------------------------------------------- */

  NS.boot = function () {
    theme.apply(theme.resolve());
    fontSize.apply(fontSize.resolve());
  };

  /* ----------------------------------------------------------------------
     API client
     Wraps the framework REST surface:
       /api/resource/<DocType>            list / create
       /api/resource/<DocType>/<name>     read / update / delete
       /api/method/<dotted.path>          whitelisted methods
     Handles the CSRF token, consistent error objects and a loading-state
     counter that pages can hook into.
     ---------------------------------------------------------------------- */

  function ApiError(message, options) {
    var opts = options || {};
    this.name = "ApiError";
    this.message = message || "Request failed";
    this.status = opts.status || 0;
    this.payload = opts.payload || null;
    this.exception = opts.exception || "";
  }
  ApiError.prototype = Object.create(Error.prototype);
  ApiError.prototype.constructor = ApiError;
  NS.ApiError = ApiError;

  var pending = 0;

  function setBusy(delta) {
    pending = Math.max(0, pending + delta);
    document.documentElement.setAttribute("data-cns-loading", pending > 0 ? "true" : "false");
    document.dispatchEvent(
      new CustomEvent("consilium:loading", { detail: { pending: pending } })
    );
  }

  function csrfToken() {
    // The framework injects `frappe.csrf_token` into the page. On a site with
    // CSRF disabled it injects the literal "None", which must not be sent.
    var token = window.frappe && window.frappe.csrf_token;
    if (!token) {
      var meta = document.querySelector('meta[name="csrf-token"]');
      token = meta ? meta.getAttribute("content") : null;
    }
    if (!token || token === "None" || token === "null") return null;
    return token;
  }

  function buildQuery(params) {
    var parts = [];
    Object.keys(params || {}).forEach(function (key) {
      var value = params[key];
      if (value === null || value === undefined || value === "") return;
      if (typeof value === "object") value = JSON.stringify(value);
      parts.push(encodeURIComponent(key) + "=" + encodeURIComponent(value));
    });
    return parts.length ? "?" + parts.join("&") : "";
  }

  function extractMessage(payload, status) {
    if (!payload) return "Request failed (" + status + ")";
    // The framework returns errors in several shapes depending on the layer
    // that raised them; normalise all of them to a single string.
    if (typeof payload === "string") {
      var stripped = payload.replace(/<[^>]*>/g, " ").replace(/\s+/g, " ").trim();
      return stripped.slice(0, 400) || "Request failed (" + status + ")";
    }
    if (payload.message && typeof payload.message === "string") return payload.message;
    if (payload._server_messages) {
      try {
        var list = JSON.parse(payload._server_messages);
        var first = typeof list[0] === "string" ? JSON.parse(list[0]) : list[0];
        if (first && first.message) return String(first.message).replace(/<[^>]*>/g, " ").trim();
      } catch (e) {
        /* fall through */
      }
    }
    if (payload.exc_type) return String(payload.exc_type);
    if (payload.exception) return String(payload.exception);
    return "Request failed (" + status + ")";
  }

  var api = (NS.api = {
    /** Prefix for all endpoints; overridable for sub-path deployments. */
    basePath: "",

    /** How many requests are in flight. */
    pending: function () {
      return pending;
    },

    request: function (options) {
      var opts = options || {};
      var method = (opts.method || "GET").toUpperCase();
      var url = api.basePath + opts.path + buildQuery(opts.params);

      var headers = { Accept: "application/json" };
      if (opts.body !== undefined && opts.body !== null) {
        headers["Content-Type"] = "application/json";
      }
      var token = csrfToken();
      if (token && method !== "GET") headers["X-Frappe-CSRF-Token"] = token;
      Object.keys(opts.headers || {}).forEach(function (k) {
        headers[k] = opts.headers[k];
      });

      var init = {
        method: method,
        headers: headers,
        credentials: "same-origin"
      };
      if (opts.body !== undefined && opts.body !== null) {
        init.body = typeof opts.body === "string" ? opts.body : JSON.stringify(opts.body);
      }
      if (opts.signal) init.signal = opts.signal;

      if (opts.trackLoading !== false) setBusy(1);

      return window
        .fetch(url, init)
        .then(function (response) {
          var contentType = response.headers.get("content-type") || "";
          var parse = contentType.indexOf("application/json") !== -1
            ? response.json()
            : response.text();
          return parse.then(
            function (payload) {
              if (!response.ok) {
                throw new ApiError(extractMessage(payload, response.status), {
                  status: response.status,
                  payload: payload,
                  exception: (payload && payload.exception) || ""
                });
              }
              return payload;
            },
            function () {
              if (!response.ok) {
                throw new ApiError("Request failed (" + response.status + ")", {
                  status: response.status
                });
              }
              return null;
            }
          );
        })
        .catch(function (error) {
          if (error instanceof ApiError) throw error;
          if (error && error.name === "AbortError") throw error;
          throw new ApiError(
            "The server could not be reached. Check your connection and try again.",
            { status: 0 }
          );
        })
        .then(
          function (value) {
            if (opts.trackLoading !== false) setBusy(-1);
            return value;
          },
          function (error) {
            if (opts.trackLoading !== false) setBusy(-1);
            throw error;
          }
        );
    },

    /**
     * List records.
     * @param {string} doctype
     * @param {object} options fields, filters, order_by, limit_start,
     *                         limit_page_length, or_filters, parent
     * @returns {Promise<Array>}
     */
    list: function (doctype, options) {
      var opts = options || {};
      return api
        .request({
          path: "/api/resource/" + encodeURIComponent(doctype),
          params: {
            fields: opts.fields || ["name"],
            filters: opts.filters,
            or_filters: opts.or_filters,
            order_by: opts.order_by,
            limit_start: opts.limit_start,
            limit_page_length: opts.limit_page_length,
            parent: opts.parent
          },
          signal: opts.signal,
          trackLoading: opts.trackLoading
        })
        .then(function (payload) {
          return (payload && payload.data) || [];
        });
    },

    /**
     * Count matching records.
     * Uses the report-view count endpoint because, unlike the simpler client
     * count, it honours `or_filters` — which the table's search relies on.
     */
    count: function (doctype, options) {
      var opts = options || {};
      return api
        .request({
          path: "/api/method/frappe.desk.reportview.get_count",
          params: {
            doctype: doctype,
            filters: opts.filters || [],
            or_filters: opts.or_filters,
            distinct: false
          },
          signal: opts.signal,
          trackLoading: opts.trackLoading
        })
        .then(function (payload) {
          var value = payload && payload.message;
          return typeof value === "number" ? value : parseInt(value, 10) || 0;
        });
    },

    get: function (doctype, name, options) {
      var opts = options || {};
      return api
        .request({
          path:
            "/api/resource/" + encodeURIComponent(doctype) + "/" + encodeURIComponent(name),
          signal: opts.signal
        })
        .then(function (payload) {
          return (payload && payload.data) || null;
        });
    },

    create: function (doctype, doc) {
      return api
        .request({
          method: "POST",
          path: "/api/resource/" + encodeURIComponent(doctype),
          body: doc
        })
        .then(function (payload) {
          return (payload && payload.data) || null;
        });
    },

    update: function (doctype, name, changes) {
      return api
        .request({
          method: "PUT",
          path:
            "/api/resource/" + encodeURIComponent(doctype) + "/" + encodeURIComponent(name),
          body: changes
        })
        .then(function (payload) {
          return (payload && payload.data) || null;
        });
    },

    remove: function (doctype, name) {
      return api.request({
        method: "DELETE",
        path: "/api/resource/" + encodeURIComponent(doctype) + "/" + encodeURIComponent(name)
      });
    },

    /** Call a whitelisted server method. GET by default. */
    call: function (method, args, options) {
      var opts = options || {};
      var httpMethod = (opts.method || "GET").toUpperCase();
      var config = {
        method: httpMethod,
        path: "/api/method/" + method,
        signal: opts.signal,
        trackLoading: opts.trackLoading
      };
      if (httpMethod === "GET") config.params = args || {};
      else config.body = args || {};
      return api.request(config).then(function (payload) {
        return payload && Object.prototype.hasOwnProperty.call(payload, "message")
          ? payload.message
          : payload;
      });
    }
  });

  /* ----------------------------------------------------------------------
     Toasts
     One live region per politeness level, created on demand.
     ---------------------------------------------------------------------- */

  var toastRegions = {};

  function getToastRegion(assertive) {
    var key = assertive ? "assertive" : "polite";
    if (toastRegions[key] && document.body.contains(toastRegions[key])) {
      return toastRegions[key];
    }
    var region = util.el("div", {
      class: "cns-toast-region",
      role: assertive ? "alert" : "status",
      "aria-live": assertive ? "assertive" : "polite",
      "aria-atomic": "false"
    });
    document.body.appendChild(region);
    toastRegions[key] = region;
    return region;
  }

  /**
   * Show a transient notification.
   * @param {object|string} options message, or {message, title, type, timeout}
   *        type: "info" | "success" | "warning" | "danger"
   */
  NS.toast = function (options) {
    var opts = typeof options === "string" ? { message: options } : options || {};
    var type = opts.type || "info";
    var timeout = opts.timeout === undefined ? 5000 : opts.timeout;
    var assertive = type === "danger" || opts.assertive === true;

    var closeBtn = util.el("button", {
      type: "button",
      class: "cns-toast-close",
      "aria-label": "Dismiss notification",
      html: "&times;"
    });

    var body = util.el("div", { class: "cns-toast-body" }, [
      opts.title ? util.el("div", { class: "cns-toast-title", text: opts.title }) : null,
      util.el("div", { text: opts.message || "" })
    ]);

    var toast = util.el("div", { class: "cns-toast cns-toast--" + type }, [body, closeBtn]);

    function dismiss() {
      if (toast.parentNode) toast.parentNode.removeChild(toast);
    }
    closeBtn.addEventListener("click", dismiss);
    if (timeout > 0) window.setTimeout(dismiss, timeout);

    getToastRegion(assertive).appendChild(toast);
    return { dismiss: dismiss, element: toast };
  };

  NS.toast.success = function (message, options) {
    return NS.toast(Object.assign({ message: message, type: "success" }, options || {}));
  };
  NS.toast.error = function (message, options) {
    return NS.toast(Object.assign({ message: message, type: "danger" }, options || {}));
  };
  NS.toast.warning = function (message, options) {
    return NS.toast(Object.assign({ message: message, type: "warning" }, options || {}));
  };
  NS.toast.info = function (message, options) {
    return NS.toast(Object.assign({ message: message, type: "info" }, options || {}));
  };

  /* ----------------------------------------------------------------------
     Screen-reader announcements (non-visual, used by the table component)
     ---------------------------------------------------------------------- */

  var announcer = null;

  NS.announce = function (message) {
    if (!announcer || !document.body.contains(announcer)) {
      announcer = util.el("div", {
        class: "cns-visually-hidden",
        role: "status",
        "aria-live": "polite",
        "aria-atomic": "true"
      });
      document.body.appendChild(announcer);
    }
    // Clearing first makes repeated identical messages announce again.
    announcer.textContent = "";
    window.setTimeout(function () {
      announcer.textContent = message;
    }, 60);
  };

  /* ----------------------------------------------------------------------
     Init
     ---------------------------------------------------------------------- */

  NS.init = function (root) {
    theme.bind(root);
    fontSize.bind(root);
    // Auto-initialise any declaratively configured tables on the page.
    if (NS.Table && typeof NS.Table.autoInit === "function") NS.Table.autoInit(root);
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", function () {
      NS.init();
    });
  } else {
    NS.init();
  }
})(window, document);

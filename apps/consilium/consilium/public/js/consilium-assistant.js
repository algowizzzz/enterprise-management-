/*!
 * Consilium help assistant — the floating Help button and its chat panel.
 *
 * Plain JavaScript, no library: the portal runs where nothing can be fetched
 * at run time, and a chat panel does not need one.
 *
 * What it sends. Only where the person is: the path, the query string, the
 * page title and any JSON a page exposes in a `data-cns-context` attribute.
 * The server treats all of it as a hint. Roles, permissions, and whether the
 * record in the address may be described at all are decided there
 * (consilium/consilium_core/assistant/context.py).
 *
 * What it renders. Answers arrive as structure — paragraphs and lists whose
 * parts are text or links — never as HTML. Every part is written with
 * textContent, and a link is drawn only if its target is a same-origin path
 * ("/forums", "/policy?name=…"); anything else is shown as plain text. So an
 * answer cannot inject markup, whatever the server or an AI endpoint said.
 *
 * Accessibility. The button is a real <button> with aria-expanded; the panel
 * is a dialog that traps focus while open and gives it back on close; Escape
 * closes it; new answers are announced through a polite live region. Sizes
 * are in rem so the portal's text-size control scales the panel, and colours
 * are the portal's tokens so the dark theme applies.
 *
 * The conversation is kept for the browser tab's session in sessionStorage,
 * guarded because storage can be disabled or full. It is never sent back to
 * the server.
 */
(function () {
  "use strict";

  var ASK = "/api/method/consilium.consilium_core.assistant.ask";
  var SUGGEST = "/api/method/consilium.consilium_core.assistant.suggestions";
  var STORE_KEY = "cns:assistant:history";
  var OPEN_KEY = "cns:assistant:open";
  var MAX_HISTORY = 40;

  // ------------------------------------------------------------- utilities

  function el(tag, attrs, text) {
    var node = document.createElement(tag);
    if (attrs) {
      Object.keys(attrs).forEach(function (key) {
        if (key === "className") node.className = attrs[key];
        else node.setAttribute(key, attrs[key]);
      });
    }
    if (text !== undefined && text !== null) node.textContent = String(text);
    return node;
  }

  /** Same-origin path only: "/x", never "//host", "javascript:", or "http…". */
  function safePath(href) {
    return typeof href === "string" && /^\/(?!\/)[^\s\\]*$/.test(href) ? href : null;
  }

  function readStore(key, fallback) {
    try {
      var raw = window.sessionStorage.getItem(key);
      return raw === null ? fallback : JSON.parse(raw);
    } catch (e) {
      return fallback;
    }
  }

  function writeStore(key, value) {
    try {
      window.sessionStorage.setItem(key, JSON.stringify(value));
    } catch (e) {
      /* storage disabled or full: the conversation just is not kept */
    }
  }

  function csrfToken() {
    var token = window.frappe && window.frappe.csrf_token;
    if (!token) {
      var meta = document.querySelector('meta[name="csrf-token"]');
      token = meta ? meta.getAttribute("content") : null;
    }
    return token && token !== "None" && token !== "null" ? token : null;
  }

  function pageContext() {
    var hint = {};
    var holder = document.querySelector("[data-cns-context]");
    if (holder) {
      try {
        var parsed = JSON.parse(holder.getAttribute("data-cns-context") || "{}");
        if (parsed && typeof parsed === "object") hint = parsed;
      } catch (e) {
        hint = {};
      }
    }
    return {
      route: window.location.pathname,
      query: window.location.search,
      title: document.title,
      page_context: hint
    };
  }

  function errorMessage(payload, status) {
    if (payload && payload._server_messages) {
      try {
        var list = JSON.parse(payload._server_messages);
        var first = typeof list[0] === "string" ? JSON.parse(list[0]) : list[0];
        if (first && first.message) {
          // Parsed in an inert document (no scripts run, no images load) and
          // only its text is kept.
          var doc = new window.DOMParser().parseFromString(String(first.message), "text/html");
          return (doc.body.textContent || "").trim();
        }
      } catch (e) {
        /* fall through */
      }
    }
    if (status === 429) return "You have reached the hourly question limit. Please try again later.";
    if (status === 403) return "Sign in again to use the help assistant.";
    return "The assistant could not answer just now. Please try again.";
  }

  function request(method, url, body) {
    var headers = { Accept: "application/json" };
    var init = { method: method, headers: headers, credentials: "same-origin" };
    if (body) {
      headers["Content-Type"] = "application/json";
      init.body = JSON.stringify(body);
    }
    var token = csrfToken();
    if (token && method !== "GET") headers["X-Frappe-CSRF-Token"] = token;
    return window.fetch(url, init).then(
      function (response) {
        return response
          .json()
          .catch(function () {
            return null;
          })
          .then(function (payload) {
            if (!response.ok) throw new Error(errorMessage(payload, response.status));
            return payload ? payload.message : null;
          });
      },
      function () {
        throw new Error("The server could not be reached. Check your connection and try again.");
      }
    );
  }

  // ------------------------------------------------------------- rendering

  function renderParts(parent, parts) {
    (parts || []).forEach(function (part) {
      if (!part || typeof part.text !== "string") return;
      var href = safePath(part.href);
      if (href) {
        parent.appendChild(el("a", { href: href }, part.text));
      } else {
        parent.appendChild(document.createTextNode(part.text));
      }
    });
  }

  function renderBlocks(parent, blocks) {
    (blocks || []).forEach(function (block) {
      if (!block) return;
      if (block.type === "p") {
        var p = el("p");
        renderParts(p, block.parts);
        parent.appendChild(p);
      } else if (block.type === "ul" || block.type === "ol") {
        var list = el(block.type);
        (block.items || []).forEach(function (item) {
          var li = el("li");
          renderParts(li, item);
          list.appendChild(li);
        });
        parent.appendChild(list);
      }
    });
  }

  // ----------------------------------------------------------------- widget

  function Assistant() {
    this.history = readStore(STORE_KEY, []);
    if (!Array.isArray(this.history)) this.history = [];
    this.busy = false;
    this.suggested = null;
    this.build();
  }

  Assistant.prototype.build = function () {
    var self = this;

    this.button = el("button", {
      type: "button",
      className: "cns-assistant-toggle",
      "aria-expanded": "false",
      "aria-controls": "cns-assistant-panel",
      "aria-haspopup": "dialog"
    });
    this.button.appendChild(el("i", { className: "bi bi-question-circle", "aria-hidden": "true" }));
    this.button.appendChild(el("span", { className: "cns-assistant-toggle-label" }, "Help"));
    this.button.addEventListener("click", function () {
      self.toggle();
    });

    this.panel = el("section", {
      id: "cns-assistant-panel",
      className: "cns-assistant-panel",
      role: "dialog",
      "aria-modal": "true",
      "aria-labelledby": "cns-assistant-title",
      hidden: "hidden"
    });

    var header = el("div", { className: "cns-assistant-header" });
    var heading = el("div");
    heading.appendChild(el("h2", { id: "cns-assistant-title", className: "cns-assistant-title" }, "Help"));
    this.modeLine = el("p", { className: "cns-assistant-mode" }, "Answers from the built-in guides");
    heading.appendChild(this.modeLine);
    header.appendChild(heading);

    var tools = el("div", { className: "cns-assistant-tools" });
    this.clearButton = el("button", { type: "button", className: "cns-assistant-icon-btn", title: "Clear the conversation" });
    this.clearButton.appendChild(el("i", { className: "bi bi-trash3", "aria-hidden": "true" }));
    this.clearButton.appendChild(el("span", { className: "cns-visually-hidden" }, "Clear the conversation"));
    this.clearButton.addEventListener("click", function () {
      self.clear();
    });
    var close = el("button", { type: "button", className: "cns-assistant-icon-btn", title: "Close help" });
    close.appendChild(el("i", { className: "bi bi-x-lg", "aria-hidden": "true" }));
    close.appendChild(el("span", { className: "cns-visually-hidden" }, "Close help"));
    close.addEventListener("click", function () {
      self.close();
    });
    tools.appendChild(this.clearButton);
    tools.appendChild(close);
    header.appendChild(tools);

    this.log = el("div", { className: "cns-assistant-log", role: "log", "aria-live": "polite", "aria-relevant": "additions", tabindex: "0", "aria-label": "Conversation" });
    this.starters = el("div", { className: "cns-assistant-starters", "aria-label": "Suggested questions" });

    this.form = el("form", { className: "cns-assistant-form", novalidate: "novalidate" });
    var label = el("label", { className: "cns-visually-hidden", for: "cns-assistant-input" }, "Ask a question about this page");
    this.input = el("input", {
      id: "cns-assistant-input",
      className: "cns-assistant-input",
      type: "text",
      maxlength: "500",
      autocomplete: "off",
      placeholder: "Ask about this page…"
    });
    this.send = el("button", { type: "submit", className: "cns-btn cns-btn-primary cns-assistant-send" });
    this.send.appendChild(el("i", { className: "bi bi-send", "aria-hidden": "true" }));
    this.send.appendChild(el("span", { className: "cns-visually-hidden" }, "Ask"));
    this.form.appendChild(label);
    this.form.appendChild(this.input);
    this.form.appendChild(this.send);
    this.form.addEventListener("submit", function (event) {
      event.preventDefault();
      self.ask(self.input.value);
    });

    this.status = el("p", { className: "cns-visually-hidden", role: "status", "aria-live": "polite" });

    this.panel.appendChild(header);
    this.panel.appendChild(this.log);
    this.panel.appendChild(this.starters);
    this.panel.appendChild(this.form);
    this.panel.appendChild(this.status);
    this.panel.addEventListener("keydown", function (event) {
      self.onKeydown(event);
    });

    document.body.appendChild(this.button);
    document.body.appendChild(this.panel);

    this.renderHistory();
    if (readStore(OPEN_KEY, false)) this.open(false);
  };

  Assistant.prototype.focusables = function () {
    return Array.prototype.filter.call(
      this.panel.querySelectorAll("a[href], button:not([disabled]), input:not([disabled]), [tabindex]:not([tabindex='-1'])"),
      function (node) {
        return node.offsetWidth > 0 || node.offsetHeight > 0 || node === document.activeElement;
      }
    );
  };

  Assistant.prototype.onKeydown = function (event) {
    if (event.key === "Escape") {
      event.preventDefault();
      this.close();
      return;
    }
    if (event.key !== "Tab") return;
    // Keep focus inside the dialog while it is open.
    var nodes = this.focusables();
    if (!nodes.length) return;
    var first = nodes[0];
    var last = nodes[nodes.length - 1];
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  };

  Assistant.prototype.toggle = function () {
    if (this.panel.hasAttribute("hidden")) this.open(true);
    else this.close();
  };

  Assistant.prototype.open = function (focus) {
    this.returnFocus = document.activeElement;
    this.panel.removeAttribute("hidden");
    this.button.setAttribute("aria-expanded", "true");
    document.documentElement.classList.add("cns-assistant-open");
    writeStore(OPEN_KEY, true);
    this.loadSuggestions();
    this.scrollToEnd();
    if (focus !== false) this.input.focus();
  };

  Assistant.prototype.close = function () {
    this.panel.setAttribute("hidden", "hidden");
    this.button.setAttribute("aria-expanded", "false");
    document.documentElement.classList.remove("cns-assistant-open");
    writeStore(OPEN_KEY, false);
    // Back to whatever opened the panel; the Help button if that was nothing
    // in particular (the page body) or has since gone.
    var back = this.returnFocus;
    var target = back && back !== document.body && document.body.contains(back) && !this.panel.contains(back)
      ? back : this.button;
    target.focus();
  };

  Assistant.prototype.loadSuggestions = function () {
    var self = this;
    if (this.suggested) return;
    this.suggested = true;
    // Starters depend on the page alone. Only the path goes in the address:
    // a query string or title can name a record, and addresses end up in logs.
    var url = SUGGEST + "?context=" + encodeURIComponent(JSON.stringify({ route: window.location.pathname }));
    request("GET", url)
      .then(function (data) {
        if (!data) return;
        self.setMode(data.mode);
        self.renderStarters(data.starters || []);
      })
      .catch(function () {
        self.renderStarters(["What can I do here?"]);
      });
  };

  Assistant.prototype.setMode = function (mode) {
    this.modeLine.textContent =
      mode === "ai" ? "AI-assisted, grounded in the built-in guides" : "Answers from the built-in guides";
  };

  Assistant.prototype.renderStarters = function (starters) {
    var self = this;
    this.starters.textContent = "";
    starters.slice(0, 4).forEach(function (question) {
      var chip = el("button", { type: "button", className: "cns-assistant-chip" }, question);
      chip.addEventListener("click", function () {
        self.ask(question);
      });
      self.starters.appendChild(chip);
    });
  };

  Assistant.prototype.scrollToEnd = function () {
    this.log.scrollTop = this.log.scrollHeight;
  };

  /** Starter questions help an empty panel; once talking, each answer offers its own next steps. */
  Assistant.prototype.syncStarters = function () {
    if (this.history.length) this.starters.setAttribute("hidden", "hidden");
    else this.starters.removeAttribute("hidden");
  };

  Assistant.prototype.renderHistory = function () {
    var self = this;
    this.syncStarters();
    this.log.textContent = "";
    if (!this.history.length) {
      var intro = el("div", { className: "cns-assistant-msg cns-assistant-msg-answer" });
      intro.appendChild(
        el("p", null, "Ask how to do something on this page, why something is not available to you, where to find something, or what a term means.")
      );
      this.log.appendChild(intro);
    }
    this.history.forEach(function (entry) {
      self.log.appendChild(self.renderEntry(entry));
    });
    this.scrollToEnd();
  };

  Assistant.prototype.renderEntry = function (entry) {
    var self = this;
    if (entry.kind === "question") {
      var q = el("div", { className: "cns-assistant-msg cns-assistant-msg-question" });
      q.appendChild(el("span", { className: "cns-visually-hidden" }, "You asked: "));
      q.appendChild(document.createTextNode(entry.text));
      return q;
    }
    if (entry.kind === "error") {
      return el("div", { className: "cns-assistant-msg cns-assistant-msg-error", role: "alert" }, entry.text);
    }
    var data = entry.data || {};
    var box = el("div", { className: "cns-assistant-msg cns-assistant-msg-answer" });
    box.appendChild(el("span", { className: "cns-visually-hidden" }, "Answer: "));
    if (data.notice) box.appendChild(el("p", { className: "cns-assistant-notice" }, data.notice));
    renderBlocks(box, data.blocks);

    if (data.sources && data.sources.length) {
      var details = el("details", { className: "cns-assistant-sources" });
      details.appendChild(el("summary", null, "From the guides (" + data.sources.length + ")"));
      var list = el("ul");
      data.sources.forEach(function (source) {
        var li = el("li");
        var title = (source.label ? source.label + ": " : "") + source.title;
        var href = safePath(source.href);
        li.appendChild(href ? el("a", { href: href }, title) : el("strong", null, title));
        if (source.excerpt) li.appendChild(el("q", null, source.excerpt));
        list.appendChild(li);
      });
      details.appendChild(list);
      box.appendChild(details);
    }

    if (data.next && data.next.length) {
      var next = el("div", { className: "cns-assistant-next", "aria-label": "Next steps" });
      data.next.forEach(function (step) {
        var href = safePath(step.href);
        if (href) {
          next.appendChild(el("a", { href: href, className: "cns-assistant-chip cns-assistant-chip-link" }, step.label));
        } else if (step.ask) {
          var chip = el("button", { type: "button", className: "cns-assistant-chip" }, step.label);
          chip.addEventListener("click", function () {
            self.ask(step.ask);
          });
          next.appendChild(chip);
        }
      });
      box.appendChild(next);
    }
    if (data.mode === "ai") {
      box.appendChild(el("p", { className: "cns-assistant-byline" }, "AI-assisted answer. Check it against the guides before acting on it."));
    }
    return box;
  };

  Assistant.prototype.push = function (entry) {
    this.history.push(entry);
    if (this.history.length > MAX_HISTORY) this.history = this.history.slice(-MAX_HISTORY);
    writeStore(STORE_KEY, this.history);
    this.syncStarters();
    if (this.history.length === 1) this.log.textContent = "";
    this.log.appendChild(this.renderEntry(entry));
    this.scrollToEnd();
  };

  Assistant.prototype.clear = function () {
    this.history = [];
    writeStore(STORE_KEY, []);
    this.renderHistory();
    this.status.textContent = "Conversation cleared.";
    this.input.focus();
  };

  Assistant.prototype.setBusy = function (busy) {
    this.busy = busy;
    this.send.disabled = busy;
    this.panel.setAttribute("aria-busy", busy ? "true" : "false");
    this.status.textContent = busy ? "Looking that up…" : "";
  };

  Assistant.prototype.ask = function (text) {
    var self = this;
    var question = String(text || "").replace(/\s+/g, " ").trim();
    if (!question || this.busy) return;
    this.input.value = "";
    this.push({ kind: "question", text: question });
    this.setBusy(true);
    request("POST", ASK, { question: question, context: pageContext() })
      .then(function (data) {
        self.setBusy(false);
        // A notice means AI mode is on but fell back for this answer.
        if (data) self.setMode(data.mode === "ai" || data.notice ? "ai" : "builtin");
        self.push({ kind: "answer", data: data || {} });
      })
      .catch(function (error) {
        self.setBusy(false);
        self.push({ kind: "error", text: error.message });
      })
      .then(function () {
        self.input.focus();
      });
  };

  // ------------------------------------------------------------------ start

  function start() {
    // Signed-out visitors get no assistant: every answer needs a session.
    if (!document.body || document.body.classList.contains("cns-guest")) return;
    if (document.getElementById("cns-assistant-panel")) return;
    if (!window.fetch || !window.JSON) return;
    window.Consilium = window.Consilium || {};
    window.Consilium.assistant = new Assistant();
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start);
  else start();
})();

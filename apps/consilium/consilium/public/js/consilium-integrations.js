/* ==========================================================================
   Consilium — external tool buttons (Doc AI, horizon scanning)
   --------------------------------------------------------------------------
   Every button is a plain link to a portal address (/doc-ai, /horizon-scanning)
   that checks permission, records the hand-off and forwards on the server.
   This script adds two things:

   1. When a tool is not connected yet, a click explains that instead of
      opening a page that would say the same thing. The explanation names
      where an administrator connects it, and links there for an administrator.
   2. Consilium.integrations.docAiLink(document, version) builds the same link
      for rows a page draws in script (the version table on /policy).

   The settings arrive in <script type="application/json" id="cns-external-tools">
   written by templates/includes/external_tools.html: labels and states only,
   never an address. Plain ES5, no build step, like the rest of the portal.
   ========================================================================== */
(function () {
  "use strict";

  var NS = (window.Consilium = window.Consilium || {});

  function readConfig() {
    var node = document.getElementById("cns-external-tools");
    if (!node) return null;
    try { return JSON.parse(node.textContent || "{}"); } catch (e) { return null; }
  }

  function esc(value) {
    return String(value === null || value === undefined ? "" : value)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
  }

  /* ------------------------------------------------------------- dialog */

  var dialog = null;

  function buildDialog() {
    var node = document.createElement("dialog");
    node.className = "cns-dialog";
    node.setAttribute("aria-labelledby", "cns-tool-dialog-title");
    node.setAttribute("aria-describedby", "cns-tool-dialog-body");
    node.innerHTML =
      '<form method="dialog" class="cns-dialog-inner">' +
      '<div class="cns-dialog-icon" aria-hidden="true"><i class="bi bi-plug"></i></div>' +
      '<h2 class="cns-dialog-title" id="cns-tool-dialog-title"></h2>' +
      '<p class="cns-dialog-body" id="cns-tool-dialog-body"></p>' +
      '<div class="cns-dialog-actions"></div>' +
      "</form>";
    node.addEventListener("click", function (event) {
      // A click on the backdrop (the dialog element itself, outside the form) closes it.
      if (event.target === node) node.close();
    });
    document.body.appendChild(node);
    return node;
  }

  function explain(toolName, isAdmin) {
    if (!dialog) dialog = buildDialog();
    dialog.querySelector(".cns-dialog-title").textContent = toolName + " isn’t connected yet";
    dialog.querySelector(".cns-dialog-body").textContent =
      toolName + " isn’t connected yet — an administrator sets its address in Admin → Integrations.";
    var actions = dialog.querySelector(".cns-dialog-actions");
    actions.innerHTML =
      (isAdmin
        ? '<a class="cns-btn cns-btn-primary" href="/integrations"><i class="bi bi-sliders" aria-hidden="true"></i> Open Integrations</a>'
        : "") +
      '<button type="submit" class="cns-btn ' + (isAdmin ? "cns-btn-secondary" : "cns-btn-primary") + '" value="close">Close</button>';
    if (typeof dialog.showModal === "function") {
      dialog.showModal();
      var focusable = actions.querySelector("a, button");
      if (focusable) focusable.focus();
    } else {
      // A browser without <dialog>: the portal address says the same thing.
      return false;
    }
    return true;
  }

  document.addEventListener("click", function (event) {
    var link = event.target && event.target.closest
      ? event.target.closest('[data-cns-tool-state="not_connected"]')
      : null;
    if (!link) return;
    if (event.metaKey || event.ctrlKey || event.shiftKey || event.button === 1) return;
    if (explain(link.getAttribute("data-cns-tool") || "This tool", link.getAttribute("data-cns-tool-admin") === "1")) {
      event.preventDefault();
    }
  });

  /* -------------------------------------------------------------- links */

  /**
   * The Doc AI link for one version of a document, as HTML, or "" when this
   * person does not see the button. `options.compact` draws the small ghost
   * button used inside tables.
   */
  function docAiLink(documentName, versionName, options) {
    var config = readConfig();
    var tool = config && config.doc_ai;
    if (!tool || !tool.shown || !documentName) return "";
    var opts = options || {};
    var href = "/doc-ai?name=" + encodeURIComponent(documentName) +
      (versionName ? "&version=" + encodeURIComponent(versionName) : "");
    var attrs = ' data-cns-tool="Doc AI" data-cns-tool-state="' + esc(tool.state) + '"' +
      (config.admin ? ' data-cns-tool-admin="1"' : "") +
      (tool.state === "connected" && tool.new_tab ? ' target="_blank" rel="noopener noreferrer"' : "");
    var label = opts.label || tool.label;
    return '<a class="cns-btn ' + (opts.compact ? "cns-btn-ghost cns-btn-sm" : "cns-btn-secondary") +
      '" href="' + esc(href) + '"' + attrs +
      (opts.compact ? ' title="' + esc(tool.label) + '"' : "") + ">" +
      '<i class="bi bi-pencil-square" aria-hidden="true"></i> ' + esc(label) + "</a>";
  }

  NS.integrations = {
    config: readConfig,
    docAiLink: docAiLink,
    explain: explain
  };
})();

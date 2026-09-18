/* ==========================================================================
   Header: menus, slide-out panel and global search
   --------------------------------------------------------------------------
   Plain script, no build step, no dependency beyond consilium.js (for the API
   client and escaping). Everything here enhances markup that already works
   without it: every menu item is an ordinary link, and without script the
   panels simply stay closed.

   Menus follow the disclosure-navigation pattern rather than ARIA's
   role="menu": the items are links to pages, and a screen reader should read
   them as links. Each top-level button carries aria-expanded and
   aria-controls. On top of the pattern the keyboard gets what people expect
   from a menu bar:

     Enter, Space, Down   open a menu and move to its first item
     Up                   open a menu and move to its last item
     Left, Right          move between the top-level menus (an open menu
                          follows the focus)
     Home, End            first or last item (or menu)
     Escape               close, and return to the menu's button
     Tab                  leaves the menu, which then closes

   Below 768px the same markup becomes a slide-out panel (the menu button in
   the header opens it) and each menu an expandable section. The panel keeps
   the focus inside it while open and gives it back to the menu button on
   close.

   Search is a combobox over consilium.consilium_core.search.global_search:
   results are grouped by record type, the arrow keys move through them
   (aria-activedescendant), Enter opens one, Escape closes, and "/" or
   Ctrl/Cmd+K focuses the box from anywhere on the page.
   ========================================================================== */

(function (window, document) {
  "use strict";

  var NS = window.Consilium || {};
  var header = document.querySelector("[data-cns-header]");
  if (!header) return;

  var DESKTOP = window.matchMedia ? window.matchMedia("(min-width: 768px)") : { matches: true };
  function isDesktop() { return DESKTOP.matches; }

  function escapeHtml(value) {
    if (NS.util && NS.util.escapeHtml) return NS.util.escapeHtml(value);
    return String(value == null ? "" : value).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  function visible(node) {
    return !!(node && (node.offsetWidth || node.offsetHeight || node.getClientRects().length));
  }

  /* ----------------------------------------------------------------------
     Menus
     ---------------------------------------------------------------------- */

  var nav = header.querySelector("[data-cns-nav]");
  var triggers = nav ? Array.prototype.slice.call(nav.querySelectorAll(".cns-menu-trigger")) : [];
  var buttons = triggers.filter(function (t) { return t.tagName === "BUTTON"; });

  function panelOf(button) {
    return document.getElementById(button.getAttribute("aria-controls"));
  }

  function itemsOf(button) {
    var panel = panelOf(button);
    return panel ? Array.prototype.slice.call(panel.querySelectorAll(".cns-menu-item")) : [];
  }

  function isOpen(button) { return button.getAttribute("aria-expanded") === "true"; }

  /* A panel near the right edge would run off the screen; it is moved left
     just enough to fit, with the page gutter kept. */
  function place(panel) {
    panel.style.left = "";
    panel.style.right = "";
    if (!isDesktop()) return;
    var rect = panel.getBoundingClientRect();
    // The right edge of the page's content column, or the screen's, whichever is nearer.
    var room = document.documentElement.clientWidth - 16;
    var inner = nav.querySelector(".cns-mainnav-inner");
    if (inner) {
      var box = inner.getBoundingClientRect();
      room = Math.min(room, box.right - (parseFloat(getComputedStyle(inner).paddingRight) || 0));
    }
    if (rect.right > room) {
      panel.style.left = Math.round(Math.min(0, room - rect.right) + (parseFloat(getComputedStyle(panel).left) || 0)) + "px";
    }
  }

  function open(button, focus) {
    if (isDesktop()) {
      buttons.forEach(function (other) { if (other !== button) close(other); });
    }
    var panel = panelOf(button);
    if (!panel) return;
    button.setAttribute("aria-expanded", "true");
    button.parentNode.classList.add("is-open");
    panel.hidden = false;
    place(panel);
    var items = itemsOf(button);
    if (focus === "first" && items.length) items[0].focus();
    if (focus === "last" && items.length) items[items.length - 1].focus();
  }

  function close(button, refocus) {
    var panel = panelOf(button);
    button.setAttribute("aria-expanded", "false");
    button.parentNode.classList.remove("is-open");
    if (panel) panel.hidden = true;
    if (refocus) button.focus();
  }

  function closeAll() {
    buttons.forEach(function (b) { if (isOpen(b)) close(b); });
  }

  function openButton() {
    for (var i = 0; i < buttons.length; i++) if (isOpen(buttons[i])) return buttons[i];
    return null;
  }

  function moveTrigger(from, step) {
    var index = triggers.indexOf(from);
    var next = triggers[(index + step + triggers.length) % triggers.length];
    var wasOpen = from.tagName === "BUTTON" && isOpen(from);
    if (wasOpen) close(from);
    next.focus();
    if (wasOpen && next.tagName === "BUTTON") open(next);
  }

  buttons.forEach(function (button) {
    button.addEventListener("click", function (event) {
      if (isOpen(button)) {
        close(button);
      } else {
        // A keyboard "click" (Enter or Space reach here with detail 0) moves
        // into the menu; a pointer click leaves the focus where it is.
        open(button, event.detail === 0 && isDesktop() ? "first" : null);
      }
    });

    /* Moving the pointer across the bar while a menu is open follows it, as a
       desktop menu bar does. Nothing opens on hover alone. */
    button.addEventListener("pointerenter", function (event) {
      if (event.pointerType !== "mouse" || !isDesktop()) return;
      var current = openButton();
      if (current && current !== button) open(button);
    });
  });

  triggers.forEach(function (trigger) {
    trigger.addEventListener("keydown", function (event) {
      var isButton = trigger.tagName === "BUTTON";
      switch (event.key) {
        case "ArrowDown":
          if (!isButton) return;
          event.preventDefault();
          if (isDesktop()) open(trigger, "first");
          else if (!isOpen(trigger)) open(trigger); else focusStep(trigger, 1);
          break;
        case "ArrowUp":
          if (!isButton) return;
          event.preventDefault();
          if (isDesktop()) open(trigger, "last"); else focusStep(trigger, -1);
          break;
        case "ArrowRight":
        case "ArrowLeft":
          if (!isDesktop()) return;
          event.preventDefault();
          moveTrigger(trigger, event.key === "ArrowRight" ? 1 : -1);
          break;
        case "Home":
        case "End":
          if (!isDesktop()) return;
          event.preventDefault();
          if (isButton && isOpen(trigger)) close(trigger);
          triggers[event.key === "Home" ? 0 : triggers.length - 1].focus();
          break;
        case "Escape":
          // On a phone Escape closes the whole panel (see below).
          if (isDesktop() && isButton && isOpen(trigger)) { event.preventDefault(); close(trigger); }
          break;
      }
    });
  });

  /* Inside a panel. */
  if (nav) {
    nav.addEventListener("keydown", function (event) {
      var item = event.target.closest && event.target.closest(".cns-menu-item");
      if (!item) return;
      var panel = item.closest("[data-cns-menu-panel]");
      var button = panel && document.querySelector('[aria-controls="' + panel.id + '"]');
      if (!button) return;
      var items = itemsOf(button);
      var index = items.indexOf(item);
      switch (event.key) {
        case "ArrowDown":
          event.preventDefault();
          if (isDesktop()) items[(index + 1) % items.length].focus(); else focusStep(item, 1);
          break;
        case "ArrowUp":
          event.preventDefault();
          if (isDesktop()) items[(index - 1 + items.length) % items.length].focus(); else focusStep(item, -1);
          break;
        case "Home":
          event.preventDefault();
          items[0].focus();
          break;
        case "End":
          event.preventDefault();
          items[items.length - 1].focus();
          break;
        case "ArrowRight":
        case "ArrowLeft":
          if (!isDesktop()) return;
          event.preventDefault();
          var step = event.key === "ArrowRight" ? 1 : -1;
          var at = triggers.indexOf(button);
          var next = triggers[(at + step + triggers.length) % triggers.length];
          close(button);
          if (next.tagName === "BUTTON") open(next, "first"); else next.focus();
          break;
        case "Escape":
          if (!isDesktop()) return;
          event.preventDefault();
          close(button, true);
          break;
      }
    });

    /* Tabbing out of an open menu closes it (desktop); the panel on a phone
       is a list of sections and stays as the person left it. */
    nav.addEventListener("focusout", function (event) {
      if (!isDesktop()) return;
      var menu = event.target.closest && event.target.closest(".cns-menu");
      if (!menu) return;
      var to = event.relatedTarget;
      if (to && menu.contains(to)) return;
      var button = menu.querySelector("button.cns-menu-trigger");
      if (button && isOpen(button) && to) close(button);
    });
  }

  document.addEventListener("click", function (event) {
    if (!isDesktop() || !nav) return;
    if (!nav.contains(event.target)) closeAll();
  });

  document.addEventListener("keydown", function (event) {
    if (event.key !== "Escape") return;
    if (drawerOpen()) { event.preventDefault(); closeDrawer(); return; }
    var current = openButton();
    if (current && isDesktop()) close(current, nav.contains(document.activeElement));
  });

  /* ----------------------------------------------------------------------
     Slide-out panel (phones)
     ---------------------------------------------------------------------- */

  var toggle = header.querySelector("[data-cns-nav-toggle]");
  var backdrop = header.querySelector("[data-cns-nav-backdrop]");
  var closer = nav ? nav.querySelector("[data-cns-nav-close]") : null;

  function drawerOpen() { return !!(nav && nav.classList.contains("is-open")); }

  function focusables() {
    return Array.prototype.slice.call(
      nav.querySelectorAll("button, a[href], [tabindex]:not([tabindex='-1'])")
    ).filter(function (n) { return !n.disabled && visible(n); });
  }

  /* Up and Down on a phone walk the visible sections and items in order. */
  function focusStep(from, step) {
    var all = focusables();
    var i = all.indexOf(from);
    if (i === -1) return;
    var next = all[i + step];
    if (next) next.focus();
  }

  function openDrawer() {
    if (!nav) return;
    nav.classList.add("is-open");
    document.documentElement.classList.add("cns-drawer-open");
    if (backdrop) backdrop.hidden = false;
    toggle.setAttribute("aria-expanded", "true");
    toggle.setAttribute("aria-label", "Close the menu");
    // The section the page belongs to starts expanded.
    buttons.forEach(function (b) {
      if (b.hasAttribute("data-active") && !isOpen(b)) open(b);
    });
    var first = nav.querySelector(".cns-menu-trigger");
    (first || closer).focus();
  }

  function closeDrawer() {
    if (!drawerOpen()) return;
    nav.classList.remove("is-open");
    document.documentElement.classList.remove("cns-drawer-open");
    if (backdrop) backdrop.hidden = true;
    toggle.setAttribute("aria-expanded", "false");
    toggle.setAttribute("aria-label", "Open the menu");
    toggle.focus();
  }

  if (toggle && nav) {
    toggle.addEventListener("click", function () {
      if (drawerOpen()) closeDrawer(); else openDrawer();
    });
    if (backdrop) backdrop.addEventListener("click", closeDrawer);
    if (closer) closer.addEventListener("click", closeDrawer);

    // Keep the focus inside the panel while it is open.
    nav.addEventListener("keydown", function (event) {
      if (event.key !== "Tab" || !drawerOpen()) return;
      var all = focusables();
      if (!all.length) return;
      var first = all[0];
      var last = all[all.length - 1];
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
    });

    var onChange = function () {
      // Crossing the breakpoint resets both layouts.
      if (isDesktop()) {
        if (drawerOpen()) {
          nav.classList.remove("is-open");
          document.documentElement.classList.remove("cns-drawer-open");
          if (backdrop) backdrop.hidden = true;
          toggle.setAttribute("aria-expanded", "false");
        }
      }
      closeAll();
    };
    if (DESKTOP.addEventListener) DESKTOP.addEventListener("change", onChange);
    else if (DESKTOP.addListener) DESKTOP.addListener(onChange);
  }

  /* ----------------------------------------------------------------------
     Global search
     ---------------------------------------------------------------------- */

  var METHOD = "consilium.consilium_core.search.global_search";
  var box = header.querySelector("[data-cns-search]");
  var opener = header.querySelector("[data-cns-search-open]");
  if (!box) return;

  var input = box.querySelector("input");
  var panel = box.querySelector(".cns-gsearch-panel");
  var status = box.querySelector("[data-cns-search-status]");
  var state = { query: "", seq: 0, active: -1, controller: null, timer: null };

  function options() {
    return Array.prototype.slice.call(panel.querySelectorAll("[role='option']"));
  }

  function setActive(index) {
    var all = options();
    all.forEach(function (o) { o.setAttribute("aria-selected", "false"); o.classList.remove("is-active"); });
    state.active = all.length ? (index + all.length) % all.length : -1;
    if (state.active === -1 || index === -1) {
      state.active = -1;
      input.removeAttribute("aria-activedescendant");
      return;
    }
    var option = all[state.active];
    option.setAttribute("aria-selected", "true");
    option.classList.add("is-active");
    input.setAttribute("aria-activedescendant", option.id);
    if (option.scrollIntoView) option.scrollIntoView({ block: "nearest" });
  }

  function showPanel(html) {
    panel.innerHTML = html;
    panel.hidden = false;
    input.setAttribute("aria-expanded", "true");
    state.active = -1;
    input.removeAttribute("aria-activedescendant");
  }

  function hidePanel() {
    panel.hidden = true;
    input.setAttribute("aria-expanded", "false");
    input.removeAttribute("aria-activedescendant");
    state.active = -1;
  }

  /* The words typed, marked where they occur in a title. Escaped first. */
  function highlight(text, query) {
    var safe = escapeHtml(text);
    var words = query.split(/\s+/).filter(function (w) { return w.length > 1; });
    if (!words.length) return safe;
    var pattern = words.map(function (w) {
      return escapeHtml(w).replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    }).join("|");
    try {
      return safe.replace(new RegExp("(" + pattern + ")", "gi"), "<mark>$1</mark>");
    } catch (e) {
      return safe;
    }
  }

  var HINT = '<div class="cns-gsearch-foot" aria-hidden="true"><span><kbd>&uarr;</kbd><kbd>&darr;</kbd> to move</span>' +
    "<span><kbd>Enter</kbd> to open</span><span><kbd>Esc</kbd> to close</span></div>";

  function render(data) {
    var query = data.query || state.query;
    var groups = data.groups || [];
    if (!groups.length) {
      showPanel('<div class="cns-gsearch-empty"><i class="bi bi-search" aria-hidden="true"></i>' +
        "<p><strong>No forum, policy or escalation matches “" + escapeHtml(query) + "”.</strong></p>" +
        "<p>Try a reference such as FRM-, GDOC- or ESC-, or fewer words. Only records you may read are searched.</p></div>");
      status.textContent = "No results.";
      return;
    }
    var n = 0;
    var total = 0;
    var html = groups.map(function (group, g) {
      var gid = "cns-gs-group-" + g;
      var rows = group.results.map(function (row) {
        total += 1;
        var id = "cns-gs-opt-" + n++;
        return '<a class="cns-gsearch-option" role="option" aria-selected="false" tabindex="-1" id="' + id +
          '" href="' + escapeHtml(row.url) + '">' +
          '<span class="cns-gsearch-option-icon" aria-hidden="true"><i class="bi ' + escapeHtml(group.icon) + '"></i></span>' +
          '<span class="cns-gsearch-option-text"><span class="cns-gsearch-option-title">' + highlight(row.title, query) +
          '</span><span class="cns-gsearch-option-detail">' + escapeHtml(row.detail) + "</span></span>" +
          (row.status ? '<span class="cns-pill cns-status-' + escapeHtml(row.tone) + '">' + escapeHtml(row.status) + "</span>" : "") +
          "</a>";
      }).join("");
      var all = group.see_all
        ? '<a class="cns-gsearch-option cns-gsearch-all" role="option" aria-selected="false" tabindex="-1" id="cns-gs-opt-' + n++ +
          '" href="' + escapeHtml(group.see_all) + '">See all ' + escapeHtml(group.label.toLowerCase()) +
          " matching “" + escapeHtml(query) + "”" + '<i class="bi bi-arrow-right" aria-hidden="true"></i></a>'
        : "";
      return '<div class="cns-gsearch-group" role="group" aria-labelledby="' + gid + '">' +
        '<div class="cns-gsearch-group-label" id="' + gid + '">' + escapeHtml(group.label) + "</div>" +
        rows + all + "</div>";
    }).join("");
    showPanel(html + HINT);
    status.textContent = total + (total === 1 ? " result" : " results") + " in " + groups.length +
      (groups.length === 1 ? " group" : " groups") + ". Use the arrow keys to move through them.";
  }

  function run(query) {
    state.query = query;
    var seq = ++state.seq;
    if (state.controller) { try { state.controller.abort(); } catch (e) { /* already done */ } }
    state.controller = window.AbortController ? new window.AbortController() : null;
    if (!panel.querySelector(".cns-gsearch-option")) {
      showPanel('<div class="cns-gsearch-loading"><span class="cns-spinner" aria-hidden="true"></span> Searching&hellip;</div>');
    }
    box.setAttribute("aria-busy", "true");
    NS.api.call(METHOD, { q: query }, { trackLoading: false, signal: state.controller && state.controller.signal })
      .then(function (data) {
        if (seq !== state.seq) return;
        box.removeAttribute("aria-busy");
        render(data || {});
      })
      .catch(function (error) {
        if (seq !== state.seq || (error && error.name === "AbortError")) return;
        box.removeAttribute("aria-busy");
        showPanel('<div class="cns-gsearch-empty cns-gsearch-error"><i class="bi bi-exclamation-triangle" aria-hidden="true"></i>' +
          "<p><strong>The search could not be run.</strong></p><p>" +
          escapeHtml((error && error.message) || "The server did not answer.") + "</p></div>");
        status.textContent = "The search could not be run.";
      });
  }

  function schedule() {
    var query = input.value.replace(/\s+/g, " ").trim();
    window.clearTimeout(state.timer);
    if (query.length < 2) {
      state.seq++;
      state.query = query;
      if (query.length === 1) {
        showPanel('<div class="cns-gsearch-empty"><p>Keep typing &mdash; two characters or more.</p></div>');
      } else {
        hidePanel();
      }
      return;
    }
    state.timer = window.setTimeout(function () { run(query); }, 180);
  }

  input.addEventListener("input", schedule);
  input.addEventListener("focus", function () {
    if (input.value.trim().length >= 2 && panel.innerHTML && panel.hidden) {
      panel.hidden = false;
      input.setAttribute("aria-expanded", "true");
    }
  });

  input.addEventListener("keydown", function (event) {
    var all = options();
    switch (event.key) {
      case "ArrowDown":
        event.preventDefault();
        if (panel.hidden && input.value.trim().length >= 2) { panel.hidden = false; input.setAttribute("aria-expanded", "true"); return; }
        if (all.length) setActive(state.active + 1);
        break;
      case "ArrowUp":
        event.preventDefault();
        if (all.length) setActive(state.active <= 0 ? all.length - 1 : state.active - 1);
        break;
      case "Enter":
        event.preventDefault();
        event.stopPropagation();
        var target = all[state.active] || all[0];
        if (target) {
          window.location.href = target.getAttribute("href");
        } else if (input.value.trim().length >= 2) {
          window.clearTimeout(state.timer);
          run(input.value.trim());
        }
        break;
      case "Escape":
        event.preventDefault();
        event.stopPropagation();
        if (!panel.hidden) hidePanel();
        else if (input.value) { input.value = ""; }
        else closeMobileSearch(true);
        break;
      case "Tab":
        hidePanel();
        break;
    }
  });

  // Choosing a result with the pointer must not blur the box first.
  panel.addEventListener("mousedown", function (event) { event.preventDefault(); });
  panel.addEventListener("mousemove", function (event) {
    var option = event.target.closest && event.target.closest("[role='option']");
    if (!option) return;
    var index = options().indexOf(option);
    if (index !== state.active) setActive(index);
  });

  box.addEventListener("focusout", function (event) {
    if (event.relatedTarget && box.contains(event.relatedTarget)) return;
    hidePanel();
  });

  document.addEventListener("click", function (event) {
    if (!box.contains(event.target) && !(opener && opener.contains(event.target))) hidePanel();
  });

  /* Phones: the box opens as a row under the bar from its button. */
  function openMobileSearch() {
    header.classList.add("is-searching");
    if (opener) opener.setAttribute("aria-expanded", "true");
    input.focus();
  }

  function closeMobileSearch(refocus) {
    if (!header.classList.contains("is-searching")) return;
    header.classList.remove("is-searching");
    hidePanel();
    if (opener) {
      opener.setAttribute("aria-expanded", "false");
      if (refocus) opener.focus();
    }
  }

  if (opener) {
    opener.addEventListener("click", function () {
      if (header.classList.contains("is-searching")) closeMobileSearch(false);
      else openMobileSearch();
    });
  }

  /* "/" (or Ctrl/Cmd+K) focuses the search from anywhere, except while typing. */
  document.addEventListener("keydown", function (event) {
    var t = event.target;
    var typing = t && (t.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName));
    var slash = event.key === "/" && !event.ctrlKey && !event.metaKey && !event.altKey && !typing;
    var commandK = (event.key === "k" || event.key === "K") && (event.ctrlKey || event.metaKey) && !event.altKey;
    if (!slash && !commandK) return;
    event.preventDefault();
    if (drawerOpen()) closeDrawer();
    if (!visible(input)) openMobileSearch();
    input.focus();
    input.select();
  });
})(window, document);

/* ==========================================================================
   Reference labels
   --------------------------------------------------------------------------
   Reference data is keyed by a code — FRM types, risk categories,
   organisational units and the rest. A code is the right thing to store and
   the wrong thing to show: nobody in a governance meeting says "EXEC_CTTE".

   This reads the label field for a list once, through the same API client as
   everything else, and hands back a lookup a formatter can call synchronously.

     Consilium.reference.load(["Governance Forum Type", "Risk Category"])
       .then(function () {
         Consilium.reference.label("Risk Category", "CYBER");  // "Cyber Risk"
       });

   An unknown code comes back unchanged, so a value the viewer cannot read, or
   a list that failed to load, still shows something truthful.
   ========================================================================== */

(function (window) {
  "use strict";

  var NS = (window.Consilium = window.Consilium || {});

  /* The field that holds the readable name, per reference list. */
  var LABEL_FIELDS = {
    "Governance Forum Type": "forum_type_name",
    "Governance Forum Role": "governance_forum_role_name",
    "Governance Responsibility": "governance_responsibility_name",
    "Risk Category": "risk_category_name",
    "Risk Type": "risk_type_name",
    "Organization Unit": "org_unit_name",
    "Organizational Level": "organizational_level_name",
    "Legal Entity": "legal_entity_name",
    "Jurisdiction": "jurisdiction_name",
    "Regulatory Requirement": "regulatory_requirement_name",
    "Governing Document Type": "document_type_name",
    "Retention Class": "title",
    "Escalation Type": "escalation_type_name",
    "Governance Forum": "forum_name"
  };

  var cache = {};
  var inFlight = {};

  function loadOne(doctype) {
    if (cache[doctype]) return Promise.resolve(cache[doctype]);
    if (inFlight[doctype]) return inFlight[doctype];

    // People are not a list most users may read, so their names come from a
    // narrow endpoint that returns display names only.
    if (doctype === "User") {
      inFlight[doctype] = NS.api
        .call("consilium.consilium_core.branding.people", {}, { method: "GET", trackLoading: false })
        .then(function (map) {
          cache[doctype] = map || {};
          delete inFlight[doctype];
          return cache[doctype];
        })
        .catch(function () {
          cache[doctype] = {};
          delete inFlight[doctype];
          return cache[doctype];
        });
      return inFlight[doctype];
    }

    var labelField = LABEL_FIELDS[doctype];
    if (!labelField) {
      cache[doctype] = {};
      return Promise.resolve(cache[doctype]);
    }

    inFlight[doctype] = NS.api
      .list(doctype, {
        fields: ["name", labelField],
        order_by: labelField + " asc",
        limit_page_length: 500,
        trackLoading: false
      })
      .then(function (rows) {
        var map = {};
        rows.forEach(function (row) {
          if (row[labelField]) map[row.name] = row[labelField];
        });
        cache[doctype] = map;
        delete inFlight[doctype];
        return map;
      })
      .catch(function () {
        /* No access, or the list could not be read. Codes still display. */
        cache[doctype] = {};
        delete inFlight[doctype];
        return cache[doctype];
      });

    return inFlight[doctype];
  }

  NS.reference = {
    labelFields: LABEL_FIELDS,

    /** Warm the cache for one or more lists. */
    load: function (doctypes) {
      var list = Array.isArray(doctypes) ? doctypes : [doctypes];
      return Promise.all(list.map(loadOne));
    },

    /** The readable name for a code, or the code itself. */
    label: function (doctype, code) {
      if (!code) return "";
      var map = cache[doctype];
      return (map && map[code]) || code;
    },

    /** True once this list has been read (or has failed and given up). */
    ready: function (doctype) {
      return !!cache[doctype];
    }
  };

  /* People. Records hold account IDs; readers want names. A person is written
     as a tagged element carrying the ID, and the names are filled in when they
     arrive — so a page does not have to load them before it renders, and rows
     a table adds later (the next page, a new sort) are named as well. */
  NS.person = function (id) {
    if (!id) return "";
    var escape = NS.util.escapeHtml;
    var known = cache.User && cache.User[id];
    return '<span data-cns-person="' + escape(id) + '" title="' + escape(id) + '">' +
      escape(known || id) + "</span>";
  };

  function namePeople(root) {
    var map = cache.User;
    if (!map) return;
    (root || document).querySelectorAll("[data-cns-person]").forEach(function (node) {
      var name = map[node.getAttribute("data-cns-person")];
      if (name && node.textContent !== name) node.textContent = name;
    });
  }

  /* The inbox tab carries a count of what waits on the viewer, overdue first.
     Read once per page; the inbox itself is the source of truth. */
  var badge = document.querySelector("[data-cns-inbox-badge]");
  if (badge && !document.body.classList.contains("cns-guest")) {
    NS.api.call("consilium.consilium_core.inbox.my_task_count", {}, { trackLoading: false })
      .then(function (r) {
        if (!r || !r.count) return;
        badge.textContent = r.count > 99 ? "99+" : String(r.count);
        if (r.overdue) {
          badge.setAttribute("data-overdue", "");
          badge.title = r.overdue + " overdue";
        }
        badge.setAttribute("aria-label", r.count + " waiting" + (r.overdue ? ", " + r.overdue + " overdue" : ""));
        badge.hidden = false;
      })
      .catch(function () { /* the tab still works without its count */ });
  }

  if (document.querySelector('meta[name="cns-time-zone"]') && !document.body.classList.contains("cns-guest")) {
    loadOne("User").then(function () {
      namePeople();
      if (window.MutationObserver) {
        new MutationObserver(function (changes) {
          changes.forEach(function (change) {
            change.addedNodes.forEach(function (node) {
              if (node.nodeType === 1) namePeople(node.parentNode || node);
            });
          });
        }).observe(document.body, { childList: true, subtree: true });
      }
    });
  }
})(window);

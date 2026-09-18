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
})(window);

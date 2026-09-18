/*
 * Consilium — governance analysis helpers (O-6, O-7).
 *
 * Shared by /governance-gaps, /emerging-risks, /regulatory-updates and the
 * Impact panel on /policy. Nothing here decides anything: the server works out
 * every result and every permission; this only draws it.
 *
 * The one rule this file exists to keep: machine-generated text is always
 * drawn inside a box that says so, with whether AI was used, why not when it
 * was not, and the reference of the audit record of what was sent. Text from
 * the model is rendered from the server's blocks, escaped, and a link survives
 * only if it is a same-site path.
 */
(function () {
  "use strict";

  var NS = (window.Consilium = window.Consilium || {});
  var util = NS.util || {};
  var esc = util.escapeHtml || function (v) {
    return String(v == null ? "" : v).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  };

  function safeHref(href) {
    if (typeof href !== "string") return null;
    if (href.charAt(0) === "#") return href;
    if (href.charAt(0) === "/" && href.charAt(1) !== "/") return href;
    return null;
  }

  function renderParts(parts) {
    return (parts || []).map(function (part) {
      var href = safeHref(part.href);
      if (href) return '<a href="' + esc(href) + '">' + esc(part.text) + "</a>";
      return esc(part.text);
    }).join("");
  }

  function renderBlocks(blocks) {
    return (blocks || []).map(function (block) {
      if (block.type === "ul" || block.type === "ol") {
        return "<" + block.type + ">" + (block.items || []).map(function (item) {
          return "<li>" + renderParts(item) + "</li>";
        }).join("") + "</" + block.type + ">";
      }
      return "<p>" + renderParts(block.parts) + "</p>";
    }).join("");
  }

  var SEVERITY_CLASS = {
    Critical: "cns-status-danger", High: "cns-status-danger", Medium: "cns-status-warning",
    Low: "cns-status-neutral"
  };

  function severity(value) {
    return '<span class="cns-pill ' + (SEVERITY_CLASS[value] || "cns-status-neutral") + '">' + esc(value || "—") + "</span>";
  }

  /* The state of the AI layer before anyone has asked: available, or why not. */
  function availabilityText(ai) {
    if (!ai) return "";
    if (ai.available) {
      return "AI commentary is available. Asking sends the facts listed on this page to the configured AI service " +
        (ai.mode === "Include visible record summary"
          ? "(record titles and short summaries you may read are included)."
          : "(counts, taxonomy and opaque record references only — no titles or record text).");
    }
    return (ai.reason || "AI is not available.") + " The rule-based result above is complete without it.";
  }

  /*
   * The machine-generated box.
   *   container: element to fill
   *   ai: {available, reason, mode}      availability, from the rule-based call
   *   result: {used, status, notice, service_request, blocks, withheld} | null
   *   opts: {button: label, onAsk: fn}   when AI is available, a button to ask
   *         {foot: text, meta: text}      replace the availability line and state when nothing is shown
   */
  function renderAIBox(container, ai, result, opts) {
    if (!container) return;
    opts = opts || {};
    var html = '<div class="cns-ai-box" role="region" aria-label="Machine-generated commentary">';
    html += '<div class="cns-ai-box-head"><span class="cns-pill cns-status-info cns-ai-label">' +
      '<i class="bi bi-robot" aria-hidden="true"></i> Machine-generated</span>';
    if (result && result.used) {
      html += '<span class="cns-ai-meta">AI was used · not reviewed by a person · audit ' + esc(result.service_request || "") + "</span>";
    } else if (result) {
      html += '<span class="cns-ai-meta">AI was not used</span>';
    } else {
      html += '<span class="cns-ai-meta">' + esc(opts.meta || (ai && ai.available ? "Not yet asked" : "AI off")) + "</span>";
    }
    html += "</div>";

    if (result && result.used && result.blocks) {
      html += '<div class="cns-ai-text cns-prose">' + renderBlocks(result.blocks) + "</div>";
      html += '<p class="cns-ai-foot">Written by an AI service from the facts on this page. It may be wrong: check it against the rule-based result, which is authoritative.';
      if (result.withheld) html += " " + esc(result.withheld) + " record(s) were withheld from the AI service by the data-sharing rules.";
      html += "</p>";
    } else if (result) {
      html += '<p class="cns-ai-foot">' + esc(result.notice || "No AI answer.") + "</p>";
    } else {
      html += '<p class="cns-ai-foot">' + esc(opts.foot || availabilityText(ai)) + "</p>";
    }
    if (ai && ai.available && opts.onAsk) {
      html += '<button type="button" class="cns-btn cns-btn-secondary cns-btn-sm cns-ai-ask">' +
        '<i class="bi bi-stars" aria-hidden="true"></i> ' + esc(opts.button || "Ask the AI service") + "</button>";
    }
    html += "</div>";
    container.innerHTML = html;
    var button = container.querySelector(".cns-ai-ask");
    if (button) {
      button.addEventListener("click", function () {
        button.disabled = true;
        button.innerHTML = '<span class="cns-spinner" aria-hidden="true"></span> Asking&hellip;';
        opts.onAsk(button);
      });
    }
  }

  /* A monthly series as a small inline chart. Numbers stay in the table. */
  function sparkline(counts, rising) {
    var n = (counts || []).length;
    if (!n) return "";
    var max = Math.max.apply(null, counts.concat([1]));
    var w = 96, h = 24, step = n > 1 ? w / (n - 1) : w;
    var pts = counts.map(function (v, i) {
      return (i * step).toFixed(1) + "," + (h - 2 - (v / max) * (h - 4)).toFixed(1);
    }).join(" ");
    return '<svg class="cns-spark' + (rising ? " cns-spark--rising" : "") + '" viewBox="0 0 ' + w + " " + h +
      '" width="' + w + '" height="' + h + '" role="img" aria-label="Monthly counts: ' + esc(counts.join(", ")) + '">' +
      '<polyline fill="none" stroke-width="2" points="' + pts + '"/></svg>';
  }

  function errorState(container, error) {
    if (!container) return;
    container.innerHTML = '<div class="cns-alert cns-status-danger" role="alert"><i class="bi bi-exclamation-triangle" aria-hidden="true"></i><div>' +
      esc((error && error.message) || "Something went wrong.") + "</div></div>";
  }

  NS.ai = {
    esc: esc,
    safeHref: safeHref,
    renderBlocks: renderBlocks,
    renderAIBox: renderAIBox,
    availabilityText: availabilityText,
    severity: severity,
    sparkline: sparkline,
    errorState: errorState
  };
})();

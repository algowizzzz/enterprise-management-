/* ==========================================================================
   The workspace (desk) forms, for business users
   --------------------------------------------------------------------------
   Every record that moves through states carries a set of check boxes the
   platform keeps in step with its status — "Is Open", "Is Editable",
   "Is Committable" and the rest (consilium_core/state_flags.py). They are
   read-only, set automatically, and exist so that rules never depend on the
   wording of a status. To a business user opening a meeting or a matter they
   are noise that reads like a fault ("Is Editable" unticked on a record they
   are editing), so they are hidden from everyone but administrators, who
   configure what each status sets and need to see the result.

   Display only: nothing here changes what anyone may read or write, and the
   fields stay on the record, in reports and in the change log.
   ========================================================================== */
(function () {
  "use strict";

  var FLAGS = ["is_open", "is_editable", "is_active", "is_committable", "requires_review",
               "requires_statement", "is_affirmative"];
  var MODULES = ["Consilium Core", "Governance", "Policy", "Escalation"];
  var ADMIN_ROLES = ["System Manager", "Consilium Administrator"];

  function isAdministrator() {
    var roles = (window.frappe && frappe.user_roles) || [];
    return ADMIN_ROLES.some(function (role) { return roles.indexOf(role) !== -1; });
  }

  $(document).on("form-refresh", function (event, frm) {
    if (!frm || !frm.meta || MODULES.indexOf(frm.meta.module) === -1 || isAdministrator()) return;
    FLAGS.forEach(function (fieldname) {
      var df = frappe.meta.get_docfield(frm.doctype, fieldname, frm.docname);
      /* Only the automatic ones: an editable "Is Active" on a reference list is
         a choice a person makes, and stays. */
      if (df && df.fieldtype === "Check" && df.read_only) frm.toggle_display(fieldname, false);
    });
  });
})();

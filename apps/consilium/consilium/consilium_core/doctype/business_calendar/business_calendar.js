// Business Calendar — the zone its hours are in, said on the form.
//
// A calendar's working day ("08:30 to 17:30") has no zone of its own: the
// service-level clocks that use it count those hours in the site's time zone
// (consilium_core/sla.py works in the server's wall clock). The form showed
// the times bare, beside dates that were in the reader's zone, so the same
// deadline read differently on two screens. It now says which zone it means.
frappe.ui.form.on("Business Calendar", {
	refresh(frm) {
		const zone = (frappe.boot.time_zone && frappe.boot.time_zone.system) || frappe.boot.sysdefaults.time_zone || "UTC";
		const message = __("Working hours and holidays are in the site's time zone: {0}.", [zone]);
		frm.set_intro(message, "blue");
		["day_start", "day_end"].forEach((fieldname) => {
			frm.set_df_property(fieldname, "description", __("In {0}", [zone]));
		});
	},
});

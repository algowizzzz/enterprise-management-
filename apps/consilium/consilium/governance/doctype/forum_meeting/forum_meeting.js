// Forum Meeting — workspace form.
//
// Minutes are versioned, so they are recorded through a server action rather
// than typed into a field: each save appends a version and nothing is lost.

frappe.ui.form.on("Forum Meeting", {
	refresh(frm) {
		if (frm.is_new() || !frm.perm[0] || !frm.perm[0].write) return;
		const label = frm.doc.minutes_version ? __("Correct minutes") : __("Record minutes");
		frm.add_custom_button(label, () => {
			const dialog = new frappe.ui.Dialog({
				title: label,
				fields: [
					{
						fieldname: "minutes",
						fieldtype: "Text Editor",
						label: __("Minutes"),
						description: __("What was discussed and decided. Motions and votes are recorded separately."),
					},
					{
						fieldname: "body_file",
						fieldtype: "Attach",
						label: __("Or attach the minutes as a file"),
					},
					{
						fieldname: "change_summary",
						fieldtype: "Data",
						label: __("What changed"),
						depends_on: `eval:${frm.doc.minutes_version ? 1 : 0}`,
						description: __("For a correction: what was wrong, and why it changed."),
					},
				],
				primary_action_label: __("Save minutes"),
				primary_action(values) {
					frappe
						.call({
							method: "consilium.governance.meetings.record_meeting_minutes",
							args: { meeting: frm.doc.name, ...values },
							freeze: true,
						})
						.then((r) => {
							dialog.hide();
							frappe.show_alert({
								message: __("Minutes saved as version {0}", [r.message.version_number]),
								indicator: "green",
							});
							frm.reload_doc();
						});
				},
			});
			dialog.show();
		});
	},
});

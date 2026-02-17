$(document).on('app_ready', function () {
	const _registered = {};
	const OrigShowActions = frappe.ui.form.States.prototype.show_actions;

	frappe.ui.form.States.prototype.show_actions = function () {
		const frm = this.frm;
		if (frm && !_registered[frm.doctype]) {
			_registered[frm.doctype] = true;
			frappe.workflow.setup(frm.doctype);
			const wf = frappe.workflow.workflows[frm.doctype];

			if (wf && wf.custom_enable_confirmation) {
				frappe.ui.form.on(frm.doctype, 'before_workflow_action', function (frm) {
					let action = frm.selected_workflow_action;
					let from_state = frm.doc.workflow_state || '';

					// Find the to_state from workflow transitions
					let to_state = '';
					if (wf.transitions) {
						for (let t of wf.transitions) {
							if (t.state === from_state && t.action === action) {
								to_state = t.next_state;
								break;
							}
						}
					}

					// Unfreeze first so the dialog is clickable
					frappe.dom.unfreeze();

					return new Promise((resolve, reject) => {
						let d = new frappe.ui.Dialog({
							title: __('Confirm Workflow Action'),
							size: 'small',
							fields: [
								{
									fieldtype: 'HTML',
									options: `
										<div style="text-align:center; padding: 8px 5px;">
											<p style="font-size: 14px; margin-bottom: 4px;">
												${__('Are you sure you want to')}
												<b style="color: #171717;">${action}</b>
												${__('this')} <b>${__(frm.doctype)}</b>?
											</p>
											<p style="font-size: 12px; color: #6b7280; margin: 2px 0;">
												<b>${frm.doc.name}</b>
												&mdash; ${from_state} &rarr; <b>${to_state}</b>
											</p>
										</div>
									`
								},
								{
									fieldname: 'remarks',
									fieldtype: 'Small Text',
									label: __('Remarks (optional)')
								}
							],
							primary_action_label: __('Yes, {0}', [action]),
							primary_action: function () {
								let remarks = d.get_value('remarks') || '';
								d.hide();

								// Log the workflow action
								frappe.call({
									method: 'avientek.avientek.doctype.workflow_action_log.workflow_action_log.log_workflow_action',
									args: {
										reference_doctype: frm.doctype,
										reference_name: frm.doc.name,
										action: action,
										from_state: from_state,
										to_state: to_state,
										remarks: remarks
									},
									async: false
								});

								resolve();
							},
							secondary_action_label: __('No, Cancel'),
							secondary_action: function () {
								d.hide();
								reject();
							},
							onhide: function () {
								// If closed via X button, also reject
								frappe.dom.unfreeze();
							}
						});

						d.show();
						d.$wrapper.find('.modal-dialog').css('max-width', '480px');
						d.$wrapper.find('[data-fieldname="remarks"] textarea').css('height', '60px');

						// Apply gradient styling to buttons
						setTimeout(function () {
							let $primary = d.$wrapper.find('.btn-primary-dark, .btn-primary');
							let $secondary = d.$wrapper.find('.btn-secondary, .btn-default').not('.btn-primary-dark').not('.btn-primary');

							$primary.css({
								'background': 'linear-gradient(135deg, #10b981, #059669)',
								'border': 'none',
								'color': '#fff',
								'font-weight': '600',
								'padding': '8px 24px',
								'border-radius': '8px',
								'box-shadow': '0 2px 8px rgba(16, 185, 129, 0.3)'
							});

							$secondary.css({
								'background': 'linear-gradient(135deg, #ef4444, #dc2626)',
								'border': 'none',
								'color': '#fff',
								'font-weight': '600',
								'padding': '8px 24px',
								'border-radius': '8px',
								'box-shadow': '0 2px 8px rgba(239, 68, 68, 0.3)'
							});
						}, 100);
					});
				});
			}
		}
		return OrigShowActions.call(this);
	};
});

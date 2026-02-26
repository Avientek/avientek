import frappe
from frappe.model.document import Document


class WorkflowActionLog(Document):
	pass


@frappe.whitelist()
def log_workflow_action(reference_doctype, reference_name, action, from_state, to_state, remarks=None):
	log = frappe.new_doc("Workflow Action Log")
	log.reference_doctype = reference_doctype
	log.reference_name = reference_name
	log.action = action
	log.from_state = from_state
	log.to_state = to_state
	log.user = frappe.session.user
	log.full_name = frappe.utils.get_fullname(frappe.session.user)
	log.timestamp = frappe.utils.now_datetime()
	log.ip_address = frappe.local.request_ip if hasattr(frappe.local, "request_ip") else ""
	log.remarks = remarks
	log.insert(ignore_permissions=True)

	# Post as comment on the document
	comment_text = f"<b>{action}</b>: {from_state} → {to_state}"
	if remarks:
		comment_text += f"<br><i>{remarks}</i>"
	frappe.get_doc(reference_doctype, reference_name).add_comment("Comment", comment_text)

	frappe.db.commit()
	return log.name

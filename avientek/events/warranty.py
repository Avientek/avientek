import frappe
from frappe import _
from frappe.utils import add_months, getdate, today


def on_delivery_note_submit(doc, method=None):
	"""Auto-create Warranty List entries for delivered items
	that have custom_default_warranty_months set on the Item."""
	created = []

	for item in doc.items:
		warranty_months = frappe.get_cached_value(
			"Item", item.item_code, "custom_default_warranty_months"
		)
		if not warranty_months:
			continue

		start_date = getdate(doc.posting_date)
		end_date = add_months(start_date, warranty_months)

		wty = frappe.new_doc("Warranty List")
		wty.company = doc.company
		wty.delivery_note = doc.name
		wty.delivery_date = doc.posting_date
		wty.customer = doc.customer
		wty.item_code = item.item_code
		wty.item_name = item.item_name
		wty.qty = item.qty
		serial_no = item.serial_no or ""
		batch_no = item.batch_no or ""

		# ERPNext v15: fetch from Serial and Batch Bundle if direct fields are empty
		if not (serial_no or batch_no) and item.serial_and_batch_bundle:
			bundle_entries = frappe.get_all(
				"Serial and Batch Entry",
				filters={"parent": item.serial_and_batch_bundle},
				fields=["batch_no", "serial_no"],
			)
			if bundle_entries:
				batch_nos = {e.batch_no for e in bundle_entries if e.batch_no}
				serial_nos = [e.serial_no for e in bundle_entries if e.serial_no]
				batch_no = ", ".join(sorted(batch_nos)) if batch_nos else ""
				serial_no = "\n".join(serial_nos) if serial_nos else ""

		wty.serial_no = serial_no
		wty.batch_no = batch_no
		wty.warranty_months = warranty_months
		wty.warranty_start_date = start_date
		wty.warranty_end_date = end_date
		wty.status = "Under Warranty"
		wty.insert(ignore_permissions=True)
		created.append(wty.name)

	if created:
		frappe.msgprint(
			_("{0} warranty record(s) created: {1}").format(
				len(created),
				", ".join(
					f'<a href="/app/warranty-list/{w}">{w}</a>' for w in created
				),
			),
			title=_("Warranty Created"),
			indicator="green",
		)


def on_delivery_note_cancel(doc, method=None):
	"""Cancel or delete Warranty List entries linked to the cancelled Delivery Note."""
	# Cancel submitted warranties
	submitted = frappe.get_all(
		"Warranty List",
		filters={"delivery_note": doc.name, "docstatus": 1},
		pluck="name",
	)
	for wty_name in submitted:
		wty = frappe.get_doc("Warranty List", wty_name)
		wty.cancel()

	# Delete draft warranties
	drafts = frappe.get_all(
		"Warranty List",
		filters={"delivery_note": doc.name, "docstatus": 0},
		pluck="name",
	)
	for wty_name in drafts:
		frappe.delete_doc("Warranty List", wty_name, ignore_permissions=True)

	total = len(submitted) + len(drafts)
	if total:
		frappe.msgprint(
			_("{0} warranty record(s) cancelled/deleted.").format(total),
			title=_("Warranties Cancelled"),
			indicator="orange",
		)


def expire_warranties():
	"""Daily scheduler: mark Active warranties as Expired if warranty_end_date has passed."""
	expired = frappe.get_all(
		"Warranty List",
		filters={
			"docstatus": 1,
			"status": "Under Warranty",
			"warranty_end_date": ["<", today()],
		},
		pluck="name",
	)

	for wty_name in expired:
		frappe.db.set_value("Warranty List", wty_name, "status", "Expired")

	if expired:
		frappe.db.commit()

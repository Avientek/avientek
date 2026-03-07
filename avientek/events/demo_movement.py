import frappe
from frappe import _
from frappe.utils import today, add_days, date_diff, getdate


def on_submit(doc, method=None):
	"""Update Asset custom DAM status when a Demo Movement is submitted."""
	if doc.movement_type == "Move Out":
		_set_asset_status(doc.asset, "On Demo", doc.customer)
	elif doc.movement_type == "Return":
		_record_return(doc)
	elif doc.movement_type == "Internal Transfer":
		_set_asset_status(doc.asset, "Free", "")


def on_cancel(doc, method=None):
	"""Revert Asset custom DAM status when a Demo Movement is cancelled."""
	if doc.movement_type == "Move Out":
		_set_asset_status(doc.asset, "Free", "")
	elif doc.movement_type == "Return":
		_set_asset_status(doc.asset, "On Demo", doc.customer or "")
		_reopen_previous_movement(doc)


def _set_asset_status(asset, status, customer):
	frappe.db.set_value("Asset", asset, {
		"custom_dam_status": status,
		"custom_dam_customer": customer,
	})


def _record_return(doc):
	_set_asset_status(doc.asset, "Free", "")

	# Close the matching open Move Out movement
	open_move = frappe.db.get_value("Demo Movement", {
		"asset": doc.asset,
		"movement_type": "Move Out",
		"status": ["in", ["Open", "Overdue"]],
		"docstatus": 1,
		"name": ["!=", doc.name],
	}, "name")

	if open_move:
		frappe.db.set_value("Demo Movement", open_move, {
			"status": "Returned",
			"actual_return_date": today(),
		})


def _reopen_previous_movement(doc):
	prev = frappe.db.get_value("Demo Movement", {
		"asset": doc.asset,
		"movement_type": "Move Out",
		"status": "Returned",
		"docstatus": 1,
	}, ["name", "expected_return_date"], as_dict=True)

	if prev:
		is_overdue = prev.expected_return_date and getdate(prev.expected_return_date) < getdate(today())
		frappe.db.set_value("Demo Movement", prev.name, {
			"status": "Overdue" if is_overdue else "Open",
			"actual_return_date": None,
		})


def send_return_reminders():
	"""
	Daily scheduled job — send email reminders for upcoming and overdue returns.
	  - 3 days before expected return → reminder to salesperson + technical team
	  - On expected return date (if not returned) → reminder
	  - 7+ days overdue → escalation to management
	"""
	_today = getdate(today())
	remind_at = str(add_days(_today, 3))   # 3 days ahead
	escalate_at = str(add_days(_today, -7)) # 7 days past due

	open_movements = frappe.db.sql("""
		SELECT
			dm.name, dm.asset, dm.customer, dm.expected_return_date,
			dm.requested_salesperson, dm.movement_date,
			a.asset_name,
			DATEDIFF(%(today)s, dm.expected_return_date) AS days_overdue
		FROM `tabDemo Movement` dm
		JOIN `tabAsset` a ON a.name = dm.asset
		WHERE dm.movement_type = 'Move Out'
		  AND dm.status IN ('Open', 'Overdue')
		  AND dm.docstatus = 1
		  AND dm.expected_return_date IS NOT NULL
	""", {"today": str(_today)}, as_dict=True)

	for mv in open_movements:
		exp = getdate(mv.expected_return_date)
		days_overdue = date_diff(_today, exp)

		subject = None
		message = None

		if days_overdue >= 7:
			subject = _("ESCALATION: Demo Unit Overdue — {0}").format(mv.asset_name)
			message = _(
				"Demo unit <b>{asset_name}</b> at <b>{customer}</b> "
				"is <b>{days} days overdue</b> for return.<br>"
				"Movement: {name} | Expected Return: {exp}"
			).format(
				asset_name=mv.asset_name,
				customer=mv.customer, days=days_overdue,
				name=mv.name, exp=mv.expected_return_date,
			)
			_send_reminder(mv, subject, message, escalate=True)

		elif days_overdue == 0:
			subject = _("Demo Unit Return Due Today — {0}").format(mv.asset_name)
			message = _(
				"Demo unit <b>{asset_name}</b> at <b>{customer}</b> "
				"is due for return <b>today</b>.<br>Movement: {name}"
			).format(
				asset_name=mv.asset_name,
				customer=mv.customer, name=mv.name,
			)
			_send_reminder(mv, subject, message)

		elif mv.expected_return_date == remind_at:
			subject = _("Demo Unit Return Due in 3 Days — {0}").format(mv.asset_name)
			message = _(
				"Demo unit <b>{asset_name}</b> at <b>{customer}</b> "
				"is due for return in <b>3 days</b> ({exp}).<br>Movement: {name}"
			).format(
				asset_name=mv.asset_name,
				customer=mv.customer, exp=mv.expected_return_date, name=mv.name,
			)
			_send_reminder(mv, subject, message)

		# Update status to Overdue if past due
		if days_overdue > 0 and mv.get("status") != "Overdue":
			frappe.db.set_value("Demo Movement", mv.name, "status", "Overdue")

	frappe.db.commit()


def _send_reminder(mv, subject, message, escalate=False):
	recipients = []

	# Salesperson's email
	if mv.requested_salesperson:
		sp_user = frappe.db.get_value("Sales Person", mv.requested_salesperson, "custom_user")
		if sp_user:
			recipients.append(sp_user)

	if escalate:
		# Add Sales Managers and DAM Managers for escalation
		managers = frappe.db.sql("""
			SELECT u.email FROM `tabUser` u
			JOIN `tabHas Role` hr ON hr.parent = u.name
			WHERE hr.role IN ('DAM Manager', 'Sales Manager')
			  AND u.enabled = 1
		""", as_dict=True)
		recipients += [m.email for m in managers if m.email]

	if not recipients:
		return

	frappe.sendmail(
		recipients=list(set(recipients)),
		subject=subject,
		message=message,
		delayed=False,
	)

from . import __version__ as app_version

app_name = "avientek"
app_title = "Avientek"
app_publisher = "Craft"
app_description = "Avientek customizations"
app_email = "info@craftinteractive.ae"
app_license = "MIT"

# Includes in <head>
# ------------------

fixtures = [{'dt':'Custom Field',
				'filters': [
					['name', 'in', (
						'Purchase Order Item-avientek_eta', 'Sales Order Item-avientek_eta',
						'Sales Order Item-eta_history', 'Purchase Order Item-eta_history',
						'Purchase Order Item-eta_history_text', 'Purchase Order Item-eta_history_text',
						'Purchase Order Item-swap_so', 'Purchase Order Item-set_so_eta')]
                ]
			}]
# include js, css files in header of desk.html
# app_include_css = "/assets/avientek/css/avientek.css"
# app_include_js = "/assets/avientek/js/avientek.js"

# include js, css files in header of web template
# web_include_css = "/assets/avientek/css/avientek.css"
# web_include_js = "/assets/avientek/js/avientek.js"

# include custom scss in every website theme (without file extension ".scss")
# website_theme_scss = "avientek/public/scss/website"

# include js, css files in header of web form
# webform_include_js = {"doctype": "public/js/doctype.js"}
# webform_include_css = {"doctype": "public/css/doctype.css"}

# include js in page
# page_js = {"page" : "public/js/file.js"}

# include js in doctype views
doctype_js = {
	"Quotation" : "public/js/quotation.js",
	"Purchase Order" : "public/js/purchase_order.js"
}
# doctype_list_js = {"doctype" : "public/js/doctype_list.js"}
# doctype_tree_js = {"doctype" : "public/js/doctype_tree.js"}
# doctype_calendar_js = {"doctype" : "public/js/doctype_calendar.js"}

# Home Pages
# ----------

# application home page (will override Website Settings)
# home_page = "login"

# website user home page (by Role)
# role_home_page = {
#	"Role": "home_page"
# }

# Generators
# ----------

# automatically create page for each record of this doctype
# website_generators = ["Web Page"]

# Jinja
# ----------

# add methods and filters to jinja environment
# jinja = {
#	"methods": "avientek.utils.jinja_methods",
#	"filters": "avientek.utils.jinja_filters"
# }

# Installation
# ------------

# before_install = "avientek.install.before_install"
# after_install = "avientek.install.after_install"

# Uninstallation
# ------------

# before_uninstall = "avientek.uninstall.before_uninstall"
# after_uninstall = "avientek.uninstall.after_uninstall"

# Desk Notifications
# ------------------
# See frappe.core.notifications.get_notification_config

# notification_config = "avientek.notifications.get_notification_config"

# Permissions
# -----------
# Permissions evaluated in scripted ways

# permission_query_conditions = {
#	"Event": "frappe.desk.doctype.event.event.get_permission_query_conditions",
# }
#
# has_permission = {
#	"Event": "frappe.desk.doctype.event.event.has_permission",
# }

# DocType Class
# ---------------
# Override standard doctype classes

# override_doctype_class = {
# 	"Purchase Order": "avientek.events.purchase_order.CustomPurchaseOrder"
# }

# Document Events
# ---------------
# Hook on document methods and events

doc_events = {
	"Purchase Order": {
		"before_update_after_submit": "avientek.events.purchase_order.po_validate"
	}
}

# Scheduled Tasks
# ---------------

# scheduler_events = {
#	"all": [
#		"avientek.tasks.all"
#	],
#	"daily": [
#		"avientek.tasks.daily"
#	],
#	"hourly": [
#		"avientek.tasks.hourly"
#	],
#	"weekly": [
#		"avientek.tasks.weekly"
#	],
#	"monthly": [
#		"avientek.tasks.monthly"
#	],
# }

# Testing
# -------

# before_tests = "avientek.install.before_tests"

# Overriding Methods
# ------------------------------
#
# override_whitelisted_methods = {
#	"frappe.desk.doctype.event.event.get_events": "avientek.event.get_events"
# }
#
# each overriding function accepts a `data` argument;
# generated from the base implementation of the doctype dashboard,
# along with any modifications made in other Frappe apps
# override_doctype_dashboards = {
#	"Task": "avientek.task.get_dashboard_data"
# }

# exempt linked doctypes from being automatically cancelled
#
# auto_cancel_exempted_doctypes = ["Auto Repeat"]


# User Data Protection
# --------------------

# user_data_fields = [
#	{
#		"doctype": "{doctype_1}",
#		"filter_by": "{filter_by}",
#		"redact_fields": ["{field_1}", "{field_2}"],
#		"partial": 1,
#	},
#	{
#		"doctype": "{doctype_2}",
#		"filter_by": "{filter_by}",
#		"partial": 1,
#	},
#	{
#		"doctype": "{doctype_3}",
#		"strict": False,
#	},
#	{
#		"doctype": "{doctype_4}"
#	}
# ]

# Authentication and authorization
# --------------------------------

# auth_hooks = [
#	"avientek.auth.validate"
# ]
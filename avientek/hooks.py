app_name = "avientek"
app_title = "Avientek"
app_publisher = "Avientek"
app_description = "Avientek customizations"
app_email = "accounts@avientek.com"
app_license = "mit"

# Apps
# ------------------

# required_apps = []

# Each item in the list will be shown as an app in the apps page
# add_to_apps_screen = [
# 	{
# 		"name": "avientek",
# 		"logo": "/assets/avientek/logo.png",
# 		"title": "Avientek",
# 		"route": "/avientek",
# 		"has_permission": "avientek.api.permission.has_app_permission"
# 	}
# ]

# Includes in <head>
# ------------------

fixtures = [
	{
		"dt": "Custom Field",
		"filters": [
			[
				"name",
				"in",
				(
					"Purchase Order Item-avientek_eta",
					"Sales Order Item-avientek_eta",
					"Sales Order Item-eta_history",
					"Sales Order Item-eta",
					"Sales Order-avientek_display_currency",
					"Sales Order-avientek_exchange_rate",
					"Sales Order-avientek_total",
					"Sales Order-avientek_grand_total",
					"Sales Order-avientek_rounding_adjustment",
					"Sales Order-avientek_rounded_total",
					"Sales Order Item-avientek_rate",
					"Sales Order Item-avientek_amount",
					"Sales Order Item-avientek_exchange_rate",
					"Purchase Order Item-eta_history",
					"Purchase Order Item-eta_history_text",
					"Sales Order Item-eta_history_text",
					"Purchase Order Item-swap_so",
					"Purchase Order Item-set_so_eta",
					"Purchase Order-avientek_eta",
					"Purchase Order-avientek_display_currency",
					"Purchase Order-avientek_total",
					"Purchase Order-avientek_grand_total",
					"Purchase Order-avientek_rounding_adjustment",
					"Purchase Order-avientek_rounded_total",
					"Purchase Order Item-avientek_rate",
					"Purchase Order Item-avientek_amount",
					"Purchase Order-avientek_exchange_rate",
					"Purchase Order Item-avientek_exchange_rate",
					"Supplier-avientek_display_currency",
					"Customer-avientek_display_currency",
					"Quotation Item-custom_finance_",
					"Quotation Item-custom_transport_",
					"Quotation Item-custom_incentive_",
					"Quotation Item-custom_customs_",
					"Quotation Item-custom_markup_",
					"Quotation Item-custom_finance_value",
					"Quotation Item-custom_incentive_value",
					"Quotation Item-custom_customs_value",
					"Quotation Item-custom_markup_value",
					"Quotation Item-custom_transport_value",
					"Quotation Item-custom_total_",
					"Quotation Item-custom_cogs",
					"Quotation Item-custom_selling_price",
					"Brand-custom_finance_",
					"Brand-custom_transport",
					"Quotation-custom_section_break_pdpgu",
					"Quotation-custom_brand_summary",
					"Quotation Item-custom_section_break_dkbzh",
					"Quotation Item-custom_standard_price_",
					"Quotation Item-custom_special_price",
					"Quotation Item-custom_margin_",
					"Quotation Item-custom_margin_value",
					"Quotation-probability",
					"Quotation-custom_company_currency",
					"Quotation Item-custom_special_rate",
					"Quotation Item-custom_final_valuation_rate",
					"Quotation Item-custom_view_price_history",
					"Quotation-custom_section_break_m2mfs",
					"Quotation-custom_service_items",
     				"Quotation-custom_section_break_iz6bt",
					"Quotation-custom_total_qty","Quotation-custom_column_break_fkkaf",
					"Quotation-custom_total_company_currency","Quotation-custom_column_break_d6xvc",
					"Quotation-custom_total","Journal Entry-custom_sales_invoice",
					"Sales Order Item-custom_incentive_value","Sales Invoice Item-custom_incentive_value",
					"Quotation-custom_next_state","Quotation-custom_quote_type",
					"Sales Order-custom_quote_type","Sales Invoice-custom_quote_type",
					"Delivery Note-custom_customers_purchase_order",
					"Terms and Conditions-custom_column_break_amx2o","Terms and Conditions-custom_company",
					"Selling Settings-custom_applicable_date","Department-custom_payment_approver",
					"Journal Entry-custom_payment_request_form",
     				"Quotation-custom_section_break_d9xy0","Quotation-custom_total_shipping_value",
					"Quotation-custom_total_finance_value","Quotation-custom_total_transport_value",
					"Quotation-custom_total_reward_value","Quotation-custom_total_incentive_value",
					"Quotation-custom_column_break_tjozq","Quotation-custom_total_margin_value","Quotation-custom_total_customs_value",
         			"Quotation-custom_total_cost","Quotation-custom_total_selling",
					"Quotation-custom_auto_approve_ok","Quotation-custom_gm_approve_ok",
					"Quotation-custom_quote_project"
     ),
			]
		],
	},
	{
		"dt": "Property Setter",
		"filters": [
			[
				"name",
				"in",
				[
					"Item-main-search_fields",
					"Sales Order-delivery_date-no_copy",
					"Sales Order-transaction_date-no_copy",
					"Sales Order-other_charges_calculation-no_copy",
					"Sales Order-per_delivered-no_copy",
					"Sales Order-per_billed-no_copy",
					"Purchase Invoice-represents_company-ignore_user_permissions",
					"Purchase Order Item-sales_order-read_only",
					"Purchase Invoice-represents_company-ignore_user_permissions",
				],
			]
		],
	},
]

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
	"Quotation": "public/js/quotation.js",
	"Purchase Order": "public/js/purchase_order.js",
	"Sales Order" : "public/js/sales_order.js",
	"Company": "public/js/send_email.js",
	# "Journal Entry": "public/js/journal_entry.js",
	# "Purchase Invoice": "public/js/purchase_invoice.js"
	# "Purchase Receipt" : "public/js/purchase_receipt.js",
}
doctype_list_js = {"Sales Order" : "public/js/sales_order_list.js",
	"Quotation": "public/js/quotation_list.js"
}
# doctype_tree_js = {"doctype" : "public/js/doctype_tree.js"}
# doctype_calendar_js = {"doctype" : "public/js/doctype_calendar.js"}

# Svg Icons
# ------------------
# include app icons in desk
# app_include_icons = "avientek/public/icons.svg"


# Home Pages
# ----------

# application home page (will override Website Settings)
# home_page = "login"

# website user home page (by Role)
# role_home_page = {
# "Role": "home_page"
# }

# Generators
# ----------

# automatically create page for each record of this doctype
# website_generators = ["Web Page"]

# Jinja
# ----------

# add methods and filters to jinja environment
# jinja = {
# "methods": "avientek.utils.jinja_methods",
# "filters": "avientek.utils.jinja_filters"
# }

# Installation
# ------------

# before_install = "avientek.install.before_install"
# after_install = "avientek.install.after_install"

# Uninstallation
# ------------

# before_uninstall = "avientek.uninstall.before_uninstall"
# after_uninstall = "avientek.uninstall.after_uninstall"

# Integration Setup
# ------------------
# To set up dependencies/integrations with other apps
# Name of the app being installed is passed as an argument

# before_app_install = "avientek.utils.before_app_install"
# after_app_install = "avientek.utils.after_app_install"

# Integration Cleanup
# -------------------
# To clean up dependencies/integrations with other apps
# Name of the app being uninstalled is passed as an argument

# before_app_uninstall = "avientek.utils.before_app_uninstall"
# after_app_uninstall = "avientek.utils.after_app_uninstall"

# Desk Notifications
# ------------------
# See frappe.core.notifications.get_notification_config

# notification_config = "avientek.notifications.get_notification_config"

# Permissions
# -----------
# Permissions evaluated in scripted ways

# permission_query_conditions = {
# "Event": "frappe.desk.doctype.event.event.get_permission_query_conditions",
# }
# hooks.py

# permission_query_conditions = {
#     "Payment Request Form": "avientek.avientek.doctype.payment_request_form.payment_request_form.get_permission_query_conditions"
# }

#
# has_permission = {
# "Event": "frappe.desk.doctype.event.event.has_permission",
# }
permission_query_conditions = {
    "Project Quotation": "avientek.events.sales_person_permission.project_quotation_pqc",
    "Quotation": "avientek.events.sales_person_permission.quotation_pqc",
}

has_permission = {
    "Project Quotation": "avientek.events.sales_person_permission.project_quotation_has_perm",
    "Quotation": "avientek.events.sales_person_permission.quotation_has_perm",
}
# DocType Class
# ---------------
# Override standard doctype classes

# override_doctype_class = {
# 	"Purchase Order": "avientek.events.purchase_order.CustomPurchaseOrder"
# }

after_migrate = "avientek.migrate.after_migrate"

# Document Events
# ---------------
# Hook on document methods and events

doc_events = {
    "Purchase Order": {
        "before_update_after_submit": "avientek.events.purchase_order.po_validate",
        "validate": "avientek.events.purchase_order.check_exchange_rate",
    },
    "Item":        {"validate": "avientek.events.item.validate_brand_pn"},
    "Sales Order": {"before_update_after_submit": "avientek.events.sales_order.update_eta_in_po"},
    "Quotation": {
        "validate": "avientek.events.quotation.set_margin_flags"
    },
    "Sales Invoice": {"on_submit": "avientek.events.sales_invoice.create_incentive_journal_entry"},
}


# Scheduled Tasks
# ---------------

# scheduler_events = {
# "all": [
# "avientek.tasks.all"
# ],
# "daily": [
# "avientek.tasks.daily"
# ],
# "hourly": [
# "avientek.tasks.hourly"
# ],
# "weekly": [
# "avientek.tasks.weekly"
# ],
# "monthly": [
# "avientek.tasks.monthly"
# ],
# }

# Testing
# -------

# before_tests = "avientek.install.before_tests"

# Overriding Methods
# ------------------------------
override_whitelisted_methods = {
	"erpnext.buying.doctype.purchase_order.purchase_order.make_inter_company_sales_order": "avientek.events.purchase_order.make_inter_company_sales_order",
	"erpnext.selling.doctype.sales_order.sales_order.make_inter_company_purchase_order": "avientek.events.purchase_order.make_inter_company_purchase_order",
}
# override_whitelisted_methods = {
# 	# "frappe.desk.doctype.event.event.get_events": "avientek.event.get_events"
# 	"erpnext.buying.doctype.purchase_order.purchase_order.make_inter_company_sales_order":"avientek.events.utils.make_inter_company_sales_order"

# }
#
# each overriding function accepts a `data` argument;
# generated from the base implementation of the doctype dashboard,
# along with any modifications made in other Frappe apps
# override_doctype_dashboards = {
# "Task": "avientek.task.get_dashboard_data"
# }

# exempt linked doctypes from being automatically cancelled
#
# auto_cancel_exempted_doctypes = ["Auto Repeat"]

# Ignore links to specified DocTypes when deleting documents
# -----------------------------------------------------------

# ignore_links_on_delete = ["Communication", "ToDo"]

# Request Events
# ----------------
# before_request = ["avientek.utils.before_request"]
# after_request = ["avientek.utils.after_request"]

# Job Events
# ----------
# before_job = ["avientek.utils.before_job"]
# after_job = ["avientek.utils.after_job"]

# User Data Protection
# --------------------

# user_data_fields = [
# {
# "doctype": "{doctype_1}",
# "filter_by": "{filter_by}",
# "redact_fields": ["{field_1}", "{field_2}"],
# "partial": 1,
# },
# {
# "doctype": "{doctype_2}",
# "filter_by": "{filter_by}",
# "partial": 1,
# },
# {
# "doctype": "{doctype_3}",
# "strict": False,
# },
# {
# "doctype": "{doctype_4}"
# }
# ]

# Authentication and authorization
# --------------------------------

# auth_hooks = [
# "avientek.auth.validate"
# ]

# Automatically update python controller files with type annotations for this app.
# export_python_type_annotations = True

# default_log_clearing_doctypes = {
# 	"Logging DocType Name": 30  # days to retain logs
# }

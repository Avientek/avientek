from frappe import _


def get_data():
	return {
		"fieldname": "name",
		"non_standard_fieldnames": {},
		"transactions": [
			{"label": _("Movements"), "items": ["Demo Movement"]},
		],
		"internal_and_external_links": {
			"Demo Movement": ["assets", "demo_movement"],
		},
	}

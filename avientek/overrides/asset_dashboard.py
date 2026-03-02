def get_data(data):
	"""Add Demo Movement to the Asset form connections panel."""
	data.setdefault("non_standard_fieldnames", {})
	data["non_standard_fieldnames"]["Demo Movement"] = "asset"
	data["non_standard_fieldnames"]["RMA Case"] = "demo_asset"

	data.setdefault("transactions", [])
	data["transactions"].append({
		"label": "Demo Asset Management",
		"items": ["Demo Movement", "RMA Case"],
	})

	return data

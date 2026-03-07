def get_data(data):
	"""Add Demo Movement and Asset Capitalization to the Asset form connections panel."""
	data.setdefault("non_standard_fieldnames", {})
	data["non_standard_fieldnames"]["Demo Movement"] = "asset"
	data["non_standard_fieldnames"]["RMA Case"] = "demo_asset"
	data["non_standard_fieldnames"]["Asset Decapitalization"] = "asset"

	data.setdefault("transactions", [])
	data["transactions"].append({
		"label": "Demo Asset Management",
		"items": ["Demo Movement", "RMA Case", "Asset Decapitalization"],
	})

	return data

# Copyright (c) 2026, Avientek and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class SalesPersonTargetDetail(Document):
    """Child rows of Sales Person Target — one row per
    (month, item_group, brand, territory, country) cell of the target
    matrix. Empty item_group / brand / territory / country act as
    wildcards in the actual-vs-target report."""

    pass

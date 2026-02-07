import frappe

def execute():
    fields_to_delete = [
        # Quotation fields
        ('Quotation', 'base_total_shipping'),
        ('Quotation', 'base_total_processing_charges'),
        ('Quotation', 'base_total_reward'),
        ('Quotation', 'base_total_levee'),
        ('Quotation', 'base_total_std_margin'),
        ('Quotation', 'total_shipping'),
        ('Quotation', 'total_processing_charges'),
        ('Quotation', 'total_reward'),
        ('Quotation', 'total_levee'),
        ('Quotation', 'total_std_margin'),
        ('Quotation', 'total_shipping_per'),
        ('Quotation', 'total_processing_charges_per'),
        ('Quotation', 'total_reward_per'),
        ('Quotation', 'total_levee_per'),
        ('Quotation', 'total_std_margin_per'),
        # Quotation Item fields
        ('Quotation Item', 'total_shipping'),
        ('Quotation Item', 'total_reward'),
        ('Quotation Item', 'total_levee'),
        ('Quotation Item', 'total_std_margin'),
        ('Quotation Item', 'base_total_shipping'),
        ('Quotation Item', 'base_total_reward'),
        ('Quotation Item', 'base_total_levee'),
        ('Quotation Item', 'base_total_std_margin'),
    ]

    deleted = 0
    for dt, fn in fields_to_delete:
        name = f'{dt}-{fn}'
        if frappe.db.exists('Custom Field', name):
            frappe.delete_doc('Custom Field', name, force=True)
            print(f'Deleted: {name}')
            deleted += 1

    frappe.db.commit()
    print(f'Total deleted: {deleted}')

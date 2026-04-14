import frappe

def execute():
    company = "AVIENTEK TRADING LLC"

    pe = frappe.db.sql("SELECT name FROM `tabPayment Entry` WHERE company=%s AND docstatus=1 LIMIT 1", company, pluck="name")
    if pe:
        try:
            doc = frappe.get_doc("Payment Entry", pe[0])
            doc.make_gl_entries(gl_entries=None, from_repost=True)
            frappe.db.commit()
            print(f"PE {pe[0]}: SUCCESS")
        except Exception as e:
            print(f"PE {pe[0]}: ERROR - {str(e)[:300]}")

    je = frappe.db.sql("SELECT name FROM `tabJournal Entry` WHERE company=%s AND docstatus=1 LIMIT 1", company, pluck="name")
    if je:
        try:
            doc = frappe.get_doc("Journal Entry", je[0])
            doc.make_gl_entries(gl_entries=None, from_repost=True)
            frappe.db.commit()
            print(f"JE {je[0]}: SUCCESS")
        except Exception as e:
            print(f"JE {je[0]}: ERROR - {str(e)[:300]}")

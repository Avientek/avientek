# Payment Request Form — where your attachments show up

This guide explains where each file you attach to a Payment Request Form (PRF) actually appears — in the print preview on screen, and in the combined PDF you download. Use it as a quick answer to *"I attached a file but I don't see it on the print."*

## Quick answer — the five places you can attach a file

There are five different places to attach a file on a PRF. Each one shows up in a slightly different way:

| Where you attach the file | What it's typically used for | Shows up on print preview? | Shows up in Combined PDF? |
|---|---|---|---|
| **Costing Sheet** column (inside the payment row) | Cost breakdown for a specific invoice / PO line | Yes — right under that row | Yes — bundled with that row |
| **Bank Letter** field (in Party Bank Details) | Supplier's bank verification letter | Yes — right after bank details | Yes — as a separate page |
| **Additional Documents** table (description + file) | Proforma invoice, cost sheet, anything supporting the payment | Yes — right after the voucher table | Yes — as separate pages |
| **Attachments** widget (drag-drop area on the left sidebar of the form) | Any other related document | Yes — at the end of the print | Yes — as separate pages |
| Auto-generated Combined PDF (`...combined.pdf` file) | Created automatically when you click *Download Combined PDF* | No (skipped on purpose) | No (skipped on purpose) |

If you upload the same file in more than one place, it only shows up once — the system removes duplicates automatically.

## How each one works in plain terms

### Costing Sheet (per row)
This is the small attach icon inside each payment line in the "Payment References" table. Use it when the file relates ONLY to that specific invoice or purchase order — like a cost breakdown for that one item. On both the print and the combined PDF, it appears nestled with the row it belongs to.

### Bank Letter
This is the dedicated *Bank Letter* attach field. Use it for the supplier's official bank letter showing their account number / IBAN / SWIFT. On print, it appears immediately after the "BANK DETAILS" section so the approver can see the document right next to the numbers it confirms. In the combined PDF, it sits as its own page after the supporting invoices.

### Additional Documents (the description + file table)
The table with a *Description* column and an *Attachment* column near the bottom of the form. Use it when you want to attach a few related documents and label each one — for example *"Proforma invoice for PO 533"* + the PDF. Each row shows up as its own section in both the print and the combined PDF, with your description as the title and the file content underneath.

> **What changed on 17-May-2026:** Additional Documents already worked in the downloaded Combined PDF, but they were missing from the on-screen print preview. After today's update, they appear in both places.

### Sidebar Attachments (the drag-drop widget on the left of the form)
The general "Attachments" widget on the form's left sidebar. Use it for anything else — anything that doesn't fit the more specific slots above. These appear at the end of the print and the combined PDF, each labeled with the original file name.

### Auto-generated Combined PDF
When you click *Download Combined PDF*, the system saves the result as a file attached to the same PRF (so you can re-download later). To avoid the bundle including a copy of yesterday's bundle, the system intentionally skips any file whose name starts with `<PRF name>_combined`. This is invisible to you — it just means the combined PDF doesn't contain a copy of an older combined PDF inside it.

## "I attached a file but I can't see it on the print"

Quick checklist:

1. **Was the update done on production?**
   Run *Update* from the Frappe Cloud dashboard. Today's print improvements only apply after this step. If you're seeing a screen from before the update, your browser may also be holding an old cached copy — press *Ctrl-Shift-R* (Windows) or *Cmd-Shift-R* (Mac) on the print page.

2. **Is the right format selected?**
   On the print page, the print format selector should say *Payment Voucher Fast*. If it shows *Standard* or anything else, switch to *Payment Voucher Fast* — that's the only one designed to show your attachments.

3. **Did you fill the *Description* on the Additional Documents row?**
   The description is optional but it makes the section title meaningful. If left blank, the section uses the file name instead.

4. **What file type did you upload?**
   PDFs and standard image formats (JPG, PNG, GIF, WEBP) display correctly. Excel sheets, Word documents and other office files are NOT displayed inline — they only appear as attachments in the file sidebar of the form, not in the print. Convert them to PDF first if they need to appear on the print.

5. **Did you upload it to the right slot?**
   If you uploaded a bank letter into the Additional Documents table instead of the dedicated *Bank Letter* field, it will still show — just under "Additional Document" header instead of after the bank details. Both are fine.

## "I see the bank letter twice in the combined PDF"

This happens if the same file was uploaded both via the *Bank Letter* field AND via the sidebar attachments. The system de-duplicates by file location, so if the SAME file is in both places, it only shows once. But if you uploaded two SEPARATE copies (e.g. once when creating the PRF, then again after adjusting it), they're two different files and both will appear. Remove the duplicate from the sidebar.

## "An old combined PDF is showing inside my new combined PDF"

This was a real bug reported on 15-May-2026 — fixed in the same-day update. The bundle used to (incorrectly) include any older combined PDFs it found in the attachments. After the fix, all auto-generated combined PDFs are skipped, regardless of any random suffix the system added to keep filenames unique.

## "Print preview is blank — just the letterhead, no voucher content"

This means the print format selector is on *Standard* (which just shows bare field labels) instead of *Payment Voucher Fast* (which has the full voucher layout). The default was changed on 15-May-2026 to use *Payment Voucher Fast* automatically. If you still see *Standard* selected, log out and log back in — your saved session may be holding the old preference.

# PRF Attachment Flow — where each upload renders

This document explains every place a file can be uploaded on a Payment Request Form (PRF), and exactly where that file shows up in the on-screen Print view and the Combined PDF download. Use this when answering "why isn't my attachment showing in the print?".

## TL;DR — five attachment slots, two render targets

| Upload slot on PRF | On-screen Print preview (`/app/print/...`) | Downloaded Combined PDF |
|---|---|---|
| **1. Costing Sheet** on a Payment References row (`payment_references[].costing_sheet_attachment`) | ✓ embedded as images per row | ✓ embedded as full pages |
| **2. Bank Letter** field (`doc.bank_letter`) | ✓ embedded as images | ✓ appended as full PDF page(s) |
| **3. Additional Documents** child table (`additional_documents[].attachment`) | ✓ embedded as images **(fixed 2026-05-17)** | ✓ appended as full PDF page(s) |
| **4. Sidebar Attachments** (drag-drop into the Attachments widget) | ✓ embedded as images | ✓ appended as full PDF page(s) |
| **5. Auto-generated Combined PDF** (`<docname>_combined*.pdf`) | — excluded (would recurse) | — excluded (would recurse) |

Both render targets dedupe — a single file uploaded to multiple slots only shows once.

## Detailed flow per slot

### 1. Costing Sheet — per Payment References row

**Where it lives:** `payment_references[*].costing_sheet_attachment` (Attach field on the child table).

**On-screen print:** Rendered in the per-row attachments block via `ctx.row_attachments[*].costing_images`. The print template iterates each payment reference and embeds its costing images right under the row.

**Combined PDF:** The PDF builder fetches `ctx.row_attachments` and merges those PDFs as part of the per-reference step. They appear interleaved between the voucher and the linked PI/PO/Quotation pages.

**Source code:**
- Builder: `get_payment_voucher_context()` → `row_attachments` block
- Template: `payment_voucher_fast.json` → `{% for att in ctx.row_attachments %}`

### 2. Bank Letter — `doc.bank_letter`

**Where it lives:** Single `Attach` field on the parent PRF. Typically a PDF of the supplier's bank letter showing IBAN / SWIFT / Account No.

**On-screen print:** Auto-fetched as part of `ctx.row_attachments` (Bank Letter is bundled with the first row's images so the bank verification appears immediately after the bank-details table).

**Combined PDF:** Step 3 of `_build_combined_pdf_bytes` — appended as a full PDF page after all the per-reference attachments. Dedupes against any sidebar pass that might also pick up the same file.

**Source code:**
- Builder: `get_payment_voucher_context()` → `row_attachments[0].bank_images`
- Combined: `_build_combined_pdf_bytes()` → `# 3. Bank letter`

### 3. Additional Documents — `additional_documents[*]`

**Where it lives:** Child table with two columns: *Description* (free text) and *Attachment* (Attach). Used for proforma invoices, cost sheets attached to the payment request that don't belong on a specific Payment References row.

**On-screen print:** Rendered as its own section between the voucher table and the sidebar attachments via `ctx.additional_documents_print`. Each row shows `Additional Document: <description>` as the header, followed by the rasterized pages of the attachment.

**Combined PDF:** Step 4 of `_build_combined_pdf_bytes` — each Additional Document's attachment is appended as a full PDF page (or images for non-PDF).

**Source code:**
- Builder: `get_payment_voucher_context()` → `additional_documents_print` block (added 2026-05-17)
- Template: `payment_voucher_fast.json` → `{% for att in ctx.additional_documents_print %}`
- Combined: `_build_combined_pdf_bytes()` → `# 4. Additional documents`

> **Pre-2026-05-17 gap:** the context builder ALREADY excluded Additional Documents from `prf_attachments` (to prevent duplication between sidebar pass and the Additional Documents merge step in Combined PDF) but the print template had no separate section for them. Net effect: Additional Documents appeared in the Combined PDF only, never in the on-screen print preview. **Fixed in commit on 2026-05-17.**

### 4. Sidebar Attachments — drag-drop into the Attachments widget

**Where it lives:** File records attached to the PRF doctype (created by drag-dropping into the sidebar widget on the form). These are NOT linked to any specific child row — they're loose attachments at the parent level.

**On-screen print:** Rendered via `ctx.prf_attachments`. Each shows `PRF Attachment: <file_name>` as the header followed by the rasterized pages.

**Combined PDF:** Step 5 of `_build_combined_pdf_bytes` — each sidebar PDF is appended as a full PDF page.

**Dedup:** The context builder explicitly excludes files matching `doc.bank_letter` OR any `additional_documents[*].attachment` URL — those flow through their own dedicated paths above. It also excludes any file whose name starts with `<docname>_combined` (the auto-generated combined PDF itself; see slot 5).

**Source code:**
- Builder: `get_payment_voucher_context()` → `prf_attachments` block
- Combined: `_build_combined_pdf_bytes()` → `# 5. PRF sidebar attachments`

### 5. Auto-generated Combined PDF — `<docname>_combined*.pdf`

**Where it lives:** Auto-created File record attached to the PRF when the user clicks Download Combined PDF. Frappe may auto-rename duplicates with a random suffix (e.g. `AVFZC-02148_combined9de9f8.pdf`).

**On-screen print + Combined PDF:** **Excluded from both.** Including the auto-generated bundle as a sidebar attachment would recurse it back into the next bundle (the "header repeated" symptom Jithin reported on 2026-05-15). The filter matches `<docname>_combined*.pdf` case-insensitive prefix + `.pdf` suffix to catch all auto-renamed variants.

## Troubleshooting

### "My Additional Document doesn't show in the print"
- Confirm prod has been updated since 2026-05-17 (the fix that added the print render section).
- Open the PRF print preview and check the format selector is set to **Payment Voucher Fast** (default — see [docs/daily_update_2026_05_17.md](daily_update_2026_05_17.md)).
- Check the attachment field is populated on the Additional Document row.
- Check the file is PDF/JPG/PNG/GIF/WEBP — other types are skipped (Excel, Word, etc.).

### "My bank letter shows twice in the Combined PDF"
- A user uploaded the same file via both the `bank_letter` field AND the sidebar Attachments widget.
- The builder dedupes by file_url, so a single file uploaded twice creates two File records with different URLs that both get included.
- Workaround: remove the duplicate File row from the sidebar.

### "An old combined PDF is showing up inside the new combined PDF"
- This was the 2026-05-15 bug — filter was too narrow (`<docname>_combined.pdf` exact match), letting random-suffix variants through.
- Fixed 2026-05-15 (commit `acf7070`). Pattern now matches any `<docname>_combined*.pdf`.

### "Print preview is empty / shows only letterhead"
- Confirm default print format is "Payment Voucher Fast" on prod. See `Property Setter` named `Payment Request Form-main-default_print_format`.
- The 2026-05-15 fix added a Property Setter that pins this default; also persisted via `after_migrate` so it survives DB restores.

## Source-file index

| Concern | File |
|---|---|
| Context builder (assembles `ctx` for print template) | `avientek/avientek/doctype/payment_request_form/payment_request_form.py` → `get_payment_voucher_context()` |
| Combined PDF builder | same file → `_build_combined_pdf_bytes()` |
| Print template (Fast — default) | `avientek/avientek/print_format/payment_voucher_fast/payment_voucher_fast.json` |
| Print template (Professional) | `avientek/avientek/print_format/payment_voucher_professional/payment_voucher_professional.json` |
| Default-print-format Property Setter | `avientek/migrate.py::after_migrate` |
| Print format auto-sync to DB | `avientek/migrate.py::_sync_payment_voucher_formats` |

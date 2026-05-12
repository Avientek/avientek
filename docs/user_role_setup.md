# Avientek ERPNext — User & Role Setup Guide

**Audience**: Admin / HR / IT users responsible for onboarding new team members on `avientekv21.frappe.cloud`.

**Last updated**: 2026-05-14 — Sammish (added Avientek Settings approver pool config + Impersonate testing flow + User Permission gotcha).

---

## TL;DR

1. **Create user** at `/app/user/new` — email, first name, last name. Welcome email sets the password.
2. **Assign roles** by opening the user → Roles table → Add Row → pick role → Save.
3. **Configure approver pools** at `/app/avientek-settings` → Quotation High-Probability Workflow section if the roles need to participate in workflow approvals.
4. **Test** using Impersonate (top-right account menu) — never share passwords just to verify access.
5. **Watch out for User Permissions** restricting a user to their own salespeople — approvers need broader visibility to see other people's work.

---

## A) Create a new user

**Path**: `/app/user/new` (or click **Add User** on the User list).

| Field | What to enter | Required? |
|---|---|---|
| Email Address | Their work email (`firstname.lastname@avientek.com`) | ✅ |
| First Name | First name | ✅ |
| Last Name | Last name | ✅ |
| User Type | `System User` for ERP access. `Website User` is portal-only — used for external customers / suppliers via the customer portal. | ✅ |
| Enabled | Tick to allow login | ✅ |
| Send Welcome Email | Tick = Frappe emails the user a password-set link. Untick = manual credentials. | optional |
| Roles Profile | Pre-applies a saved bundle of roles (e.g. "Sales Person Profile"). Faster than picking roles one by one. | optional |
| Module Profile | Restricts which modules the user can see in the desk sidebar. | optional |

**Steps**:

1. Open `/app/user/new`
2. Fill the required fields
3. Click **Save** (Ctrl+S)
4. If "Send Welcome Email" was ticked, the user gets an email with a "Set Password" link. They click it, choose a password, and land on the desk.

---

## B) Assign roles to an existing user

1. Open `/app/user/<email>` (e.g. `/app/user/jane@avientek.com`)
2. Scroll down to the **Roles** section
3. Click **Add Row**
4. In the **Role** dropdown, type the role name (e.g. `GM-CS`) and pick it from the autocomplete
5. Repeat for each role
6. **Save**

The user must **log out and log back in** for new roles to take effect on their session.

### Remove a role

1. Open the user
2. In the Roles table, click the small **X** on the row you want to remove
3. Save
4. User must re-login.

---

## C) Avientek role catalog — who does what

### Sales workflow roles (Quotation V3)

| Role | What this role can do | Used in Avientek Settings as |
|---|---|---|
| `Sales User` | Create / edit Quotations, Sales Orders. Standard sales access. | — |
| `Sales Support L2` | Same as Sales User + can request updates / cancellations on high-prob (≥75%) quotes by ticking the Document Approval section checkboxes. | **Team Roles** |
| `GM-CS` | **Level 1 approver** for high-prob quote revisions / cancellations. Clicks `Approve Level 1` or `Approve Cancellation Level 1`. | **Level 1 Approval Roles** |
| `General Manager` | **Level 2 approver** — final sign-off after L1. Clicks `Approve Level 2` or `Approve Cancellation Level 2`. | **Level 2 Approval Roles** |
| `Director` | Alternative L2 approver candidate. Can be added to Level 2 Approval Roles for redundancy. | optional addition |

### PRF (Payment Request Form) workflow roles

| Role | Stage |
|---|---|
| `Sales User` / `Purchase User` / `Stock User` | Create PRF in Draft |
| `Accounts User` / `Accounts Manager` / `Dept Head` | **Authorise** (Stage 1 — draft → Authorised) |
| `Finance Manager` | **Approve Level 1** (Authorised → Approved Level 1). Can also Reject. |
| `General Manager` / `Director` | **Approve Level 2** (Approved Level 1 → Approved Level 2). |
| `Finance Controller` | **Release Payment** (Approved L2 → Released). Can also edit `issued_bank` + `payment_mode` on Approved L1/L2. Can Cancel from any submitted state. |

### Admin / utility roles

| Role | Purpose |
|---|---|
| `System Manager` | Admin — bypasses most restrictions. Use sparingly; only for IT / Sammish / Support. |
| `Procurement L2` | Restricted role — sees only Approved + probability=100 quotes (RBAC). Set on Avientek Settings → Restricted Roles. |

---

## D) Configure Avientek Settings approver pools

After creating users and assigning the right roles, tell the system **which roles are L1 / L2 / Team** by configuring tables on Avientek Settings.

**Path**: `/app/avientek-settings` → scroll to **Quotation High-Probability Workflow** section.

| Table | What goes here | Effect |
|---|---|---|
| **Level 1 Approval Roles** | Add one row per role that can approve at L1 | These roles get the `Approve Level 1` / `Approve Cancellation Level 1` buttons on quotes routed for approval |
| **Level 2 Approval Roles** | Add one row per role that can approve at L2 | Get the `Approve Level 2` / `Approve Cancellation Level 2` buttons |
| **Team Roles** | Add one row per role that creates quotes / can request updates / cancellations | Multi-role OR logic — any of these roles can tick the Document Approval checkboxes |
| **Restricted Roles** | Add one row per role that should ONLY see Approved+100 quotes (Dispatch / Procurement / Logistics / Supply Chain) | RBAC visibility filter |

After saving Avientek Settings, the V3 Quotation workflow is automatically re-seeded — the new role pool propagates to every workflow transition.

**Current config (as of 2026-05-14)**:
- Level 1 Approval Roles: `GM-CS`
- Level 2 Approval Roles: `General Manager`
- Team Roles: `Sales Support L2`
- Restricted Roles: (empty)

---

## E) Common gotcha — User Permissions blocking approver visibility

**Problem**: A user has the right role (e.g. `GM-CS`) but when they open the Quotation list, they only see their own quotes — not the ones routed to them for approval.

**Cause**: Frappe `User Permission` records restrict which records a user can access. If a user has a row like:

```
Allow: Sales Person
For Value: DEVEN
Apply to All Doctypes: ✓
```

Then they only see Quotations / Sales Orders / Sales Invoices / etc. where `sales_person = DEVEN`. As an approver, they need to see OTHER people's quotes.

### Check User Permissions for a user

`/app/user-permission?user=<email>`

If you see a `Sales Person` row with `Apply to All Doctypes: ✓` on someone who's supposed to be an approver, you need to widen their visibility.

### Fix — Option 1: Narrow the User Permission scope (recommended)

1. Open the User Permission row
2. Untick **Apply to All Doctypes**
3. Set **Applicable For = Sales Person**
4. Save

This makes the permission restrict only the Sales Person doctype itself (so they see only their own Sales Person record), not every doctype that has a `sales_person` link field.

### Fix — Option 2: Delete the User Permission entirely

If the user no longer needs any salesperson restriction (e.g. they're now a manager / approver):

1. Open the User Permission row
2. Menu → Delete

Saves on the User Permission list page also works.

### Known impact (today's prod state)

| Approver | Current User Permission | Issue |
|---|---|---|
| Rahul (orders.mea) | none | ✓ can see all quotes |
| Jithin (accounts) | none | ✓ can see all quotes |
| Deven (dr) | restricted to `DEVEN` (apply_to_all) | ✗ can only L1-approve his own quotes |
| Febin (fi) | restricted to 3 salespeople | ✗ same |
| Rihan (ra) | restricted to 2 salespeople | ✗ same |
| Shijin (st) | restricted to 4 salespeople | ✗ same |

So today, **only Rahul** can effectively L1-approve any quote. Same shape at L2 (Rahul + Jithin). Single point of failure.

To make the other 4 GM-CS holders functional approvers, widen their User Permissions per the steps above.

---

## F) Testing a new user (without sharing passwords)

Frappe has an **Impersonate** feature that lets an admin see the system as a target user — no password sharing needed.

### Steps

1. Login as Administrator or any user with `System Manager` role
2. Top-right → click your avatar → **Impersonate User**
3. Enter the email of the user you want to test as
4. The page reloads. You'll see a red banner: `Impersonating <email>`. Everything you see / click is as that user.
5. To stop, click **Stop Impersonating** on the banner.

### Use cases
- Verify a new user's role assignments work
- Reproduce a bug another user is reporting without asking for their password
- Quick check whether an approver can see the doc they're meant to approve

We used Impersonate today to diagnose:
- `ng@avientek.com` (Nagma) — confirm she can see the Document Approval section on a 100% quote
- `dr@avientek.com` (Deven) — discover the User Permission gap that blocks him from approving Nagma's quote

---

## G) Disable a user (don't delete)

**Never delete** a user record — they're referenced in audit trails on every document they touched. Instead, deactivate:

1. Open `/app/user/<email>`
2. **Untick** the **Enabled** checkbox (top-right of the form)
3. Save

The user can no longer log in. Past documents still show their name in the activity log. To re-enable later, re-tick Enabled and Save.

---

## H) End-to-end onboarding checklist

For each new team member:

- [ ] Create User record at `/app/user/new` (email, first name, last name, User Type=System User, Send Welcome Email ON)
- [ ] Open the user, add the right roles in the Roles table, Save
- [ ] If they're a salesperson: create a corresponding **Sales Person** record (`/app/sales-person/new`) and link `user_id` to their email
- [ ] If they're a salesperson with a restricted territory / customer set: optionally add User Permissions
- [ ] If they're an approver (`GM-CS` / `General Manager` / etc.): make sure they have NO restrictive `Sales Person` User Permission with `Apply to All Doctypes: ✓` — see section E
- [ ] If they're meant to participate in the Quotation V3 workflow as an approver: confirm the role is listed on Avientek Settings → Level 1 / Level 2 / Team Roles tables
- [ ] Welcome email arrives in their inbox; they click the link and set a password
- [ ] Test by Impersonating them (section F) and verifying they see what you expect
- [ ] Hand off — share the URL `https://avientekv21.frappe.cloud` and brief them on the workflow they'll be using

---

## I) Quick troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| User can't log in | Welcome email expired / spam / Enabled unchecked | Resend invite (User form → Menu → Email Invitation), or temporarily set a password via System Manager |
| User can see quotes but can't click Approve button | Role missing from Avientek Settings approval table, OR they're the creator (self-approval is blocked) | Add their role to L1 / L2 table, OR have a different user approve |
| User can't see the quote routed to them | User Permission restricting them to their own salespeople | Section E — narrow or delete the User Permission |
| Document Approval section not visible on quote | Quote is not yet submitted (docstatus=0), OR probability < 75% (it's only for high-prob) | Verify docstatus=1 and probabilities is ≥75% |
| Document Approval checkboxes are greyed out | Custom Field `allow_on_submit=0` | Was fixed 2026-05-14 (commit `bf0c4e1`) — hard-refresh browser if you still see it |
| User sees "Not Saved" badge but didn't change anything | Auto-refresh helpers were dirtying the form on async fetch | Fixed 2026-05-14 (commit `130abba`) — hard-refresh browser |

---

## Reference

- **System Manager admin user**: `orders.mea@avientek.com` (Rahul) — can do all of the above. Plus `support@quarkcs.com` (QCS support).
- **Source of truth for approver pools**: `/app/avientek-settings`. Changes here propagate to workflow on save.
- **Workflow seeder** (auto-runs on every `bench migrate`): `avientek/patches/seed_quotation_approval_v3_workflow.py`. Rebuilds the V3 workflow using Avientek Settings as input.
- **PRF workflow seeder**: `avientek/patches/create_payment_request_workflow.py`.

For any setup question not covered here, contact Sammish (support@quarkcs.com).

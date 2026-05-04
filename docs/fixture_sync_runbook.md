# Fixture Sync Runbook

## Why this exists

`bench migrate` (Frappe Cloud → Update + Migrate) does two things that wipe
client UI changes:

1. **Re-imports `avientek/fixtures/*.json`** — every Custom Field, Property
   Setter, Custom DocPerm, Print Format, and Workflow listed in
   `hooks.py::fixtures` is overwritten with the version shipped in the repo.
2. **Re-asserts role permissions** via `migrate.py::after_migrate` — used
   to be hardcoded; now reads `avientek/data/role_perm_baseline.json`.

If the client opens the UI and edits any of those records, the next deploy
silently reverts them. To prevent that, **pull live state into the repo
before each deploy** so client edits become the new committed baseline.

## One-time setup

Create an API key for the production site:

1. `/app/user/<your-user>` → API Access → Generate Keys
2. Save in `~/.avientek/credentials` (TOML):
   ```toml
   [avientekv21.frappe.cloud]
   api_key = "..."
   api_secret = "..."
   ```

Or pass via `--api-key`/`--api-secret` flags or
`AVIENTEK_API_KEY`/`AVIENTEK_API_SECRET` env vars.

## Standard pre-deploy workflow

```bash
# 1. Make sure repo is clean
cd ~/frappe-bench-qcs/apps/avientek
git status

# 2. See what client has changed since last sync (no writes)
python tools/sync_fixtures.py --dry-run

# 3. Pull live state into the repo
python tools/sync_fixtures.py

# 4. Review every diff carefully
git diff avientek/fixtures/ avientek/data/role_perm_baseline.json

# 5. Decide per-diff:
#    - LEGITIMATE client edit → keep
#    - ACCIDENTAL / TO BE REVERTED → git checkout that hunk
#    - YOUR LATEST CHANGE that hasn't deployed yet → keep your version
#       (the pull may have overwritten it; restore it manually)

# 6. Commit
git add avientek/fixtures/ avientek/data/role_perm_baseline.json
git commit -m "sync: pull live fixtures pre-deploy ($(date +%Y-%m-%d))"
git push upstream master

# 7. Frappe Cloud → Update + Migrate
#    The migrate now respects client edits because they are the baseline.
```

## What the script pulls

* All DocTypes listed in `avientek/hooks.py::fixtures` — Custom Field,
  Property Setter, Custom DocPerm, Print Format, Workflow (whatever is
  declared there).
* `Custom DocPerm` rows for the 3 enforced roles into
  `data/role_perm_baseline.json`:
  * `Sales Invoice / Sales Invoice- Custom / permlevel=0`
  * `Sales Invoice / Accounts Manager / permlevel=0` (export flag only)
  * `Sales Invoice / Accounts User / permlevel=0` (export flag only)

## What the script does NOT pull

* Print format HTML for `custom_format=1` rows — those have their own
  on-disk source and the `after_migrate` hook
  `_sync_payment_voucher_formats()` already auto-syncs them.
* Real data records (Customer, Supplier, Item) — fixtures are for schema
  customisations only.
* User permission rules from the Avientek `User Permission Manager`
  doctype — that's a separate runtime feature, not migrate-managed.

## Filtering a single fixture type

```bash
python tools/sync_fixtures.py --only "Property Setter"
python tools/sync_fixtures.py --only "Custom Field"
```

## What if the puller fails on one DocType?

The script reports the error and continues with the next DocType. The
files for healthy DocTypes are still updated. Rerun for a clean pull,
or skip the role baseline with `--skip-role-baseline` if it's the
problem.

## Adding a new role to the enforced baseline

Edit `avientek/data/role_perm_baseline.json` directly:

```json
{
  "parent": "Quotation",
  "role": "Sales Manager",
  "permlevel": 0,
  "perms": {"export": 1, "report": 1},
  "create_if_missing": false
}
```

Then add a matching tuple to `tools/sync_fixtures.py::ROLE_BASELINE_TARGETS`
so the next pull keeps that row in the JSON.

## Removing the migrate-time enforcement entirely

If a role/perm becomes fully client-managed (no enforcement needed):

1. Remove its row from `avientek/data/role_perm_baseline.json`
2. Remove its entry from `ROLE_BASELINE_TARGETS` in
   `tools/sync_fixtures.py`

Migrate will then leave that DocPerm alone forever.

## Recovery if a deploy reverted client work

```bash
# Pull live state into a scratch branch (do NOT push to master yet)
git checkout -b restore/fixtures-$(date +%Y%m%d)
python tools/sync_fixtures.py
git add -A && git commit -m "snapshot: live fixtures pre-restore"

# Compare against last good repo commit
git diff master -- avientek/fixtures/ avientek/data/

# Cherry-pick / merge the legitimate restored values back into master
```

## Why we don't run this as a migrate hook

We considered making `after_migrate` itself pull live state — but that
creates a loop (migrate writes fixtures → migrate pulls them back) and
removes the human review step. The pre-deploy pull stays manual on
purpose so a person eyeballs every diff before re-asserting.

#!/usr/bin/env python3
"""Pull live fixtures from a Frappe Cloud Avientek site into the repo.

Why this exists
---------------
Frappe re-imports `avientek/fixtures/*.json` on every `bench migrate`, which
silently overwrites whatever the client edited in the UI for those records.
The same applies to the role baseline that `migrate.py::after_migrate`
re-asserts. To preserve client edits, the deploy workflow must be:

    1. Pull live state from production into the repo (this script)
    2. Review `git diff fixtures/ avientek/data/role_perm_baseline.json`
    3. Commit the legitimate client edits as the new baseline
    4. Deploy (Frappe Cloud → Update + Migrate) — now safe to re-apply

Usage
-----
    # Default site: avientekv21.frappe.cloud
    python tools/sync_fixtures.py

    # Specify site
    python tools/sync_fixtures.py --site mysite.frappe.cloud

    # Dry-run: show what would change, write nothing
    python tools/sync_fixtures.py --dry-run

    # Filter to one fixture type
    python tools/sync_fixtures.py --only "Property Setter"

Auth (any of these works, in order of precedence):
    1. --api-key + --api-secret CLI flags
    2. AVIENTEK_API_KEY + AVIENTEK_API_SECRET env vars
    3. ~/.avientek/credentials TOML file:
         [<site>]
         api_key = "..."
         api_secret = "..."

Get an API key from /app/user/<user> → API Access → Generate Keys.

Limitations
-----------
* Skips audit fields (creation, modified, modified_by, owner) so noisy
  whitespace diffs don't fill PRs.
* Only the DocTypes/filters declared in `hooks.py::fixtures` are pulled.
  Adjust hooks.py first if a new fixture is needed.
* Does NOT touch `print_format.json` HTML for custom_format=1 rows on its
  own — the dedicated patches in `avientek/patches/sync_payment_voucher_*`
  handle those because the after_migrate hook syncs them every migrate
  anyway. (Other print formats here are pulled normally.)
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
APP_ROOT = REPO_ROOT / "avientek"
HOOKS_PATH = APP_ROOT / "hooks.py"
FIXTURES_DIR = APP_ROOT / "fixtures"
ROLE_BASELINE_PATH = APP_ROOT / "data" / "role_perm_baseline.json"

DEFAULT_SITE = "avientekv21.frappe.cloud"

# Audit fields stripped from every record so pulled JSON stays diffable.
NOISY_FIELDS = {
    "creation", "modified", "modified_by", "owner",
    "_user_tags", "_comments", "_assign", "_liked_by",
}


# ────────────────────────────── credential resolution ────────────────────


def resolve_credentials(args) -> tuple[str, str]:
    """Return (api_key, api_secret) from flags / env / TOML file."""
    if args.api_key and args.api_secret:
        return args.api_key, args.api_secret
    env_key = os.environ.get("AVIENTEK_API_KEY")
    env_secret = os.environ.get("AVIENTEK_API_SECRET")
    if env_key and env_secret:
        return env_key, env_secret
    creds_file = Path.home() / ".avientek" / "credentials"
    if creds_file.is_file():
        try:
            try:
                import tomllib  # py 3.11+
                data = tomllib.loads(creds_file.read_text())
            except Exception:
                # Fallback for older Python — naive INI-ish parser
                data = _parse_simple_toml(creds_file.read_text())
            site_block = data.get(args.site) or {}
            k, s = site_block.get("api_key"), site_block.get("api_secret")
            if k and s:
                return k, s
        except Exception as exc:
            print(f"⚠ couldn't parse {creds_file}: {exc}", file=sys.stderr)
    sys.exit(
        "ERROR: no API credentials. Provide via --api-key/--api-secret, "
        "AVIENTEK_API_KEY/AVIENTEK_API_SECRET env vars, or "
        f"{creds_file} (TOML with [{args.site}] block)."
    )


def _parse_simple_toml(text: str) -> dict[str, dict[str, str]]:
    """Tiny TOML parser — sections + key="value". No arrays/nested tables."""
    out: dict[str, dict[str, str]] = {}
    section = None
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        m_sec = re.match(r"^\[([^\]]+)\]$", line)
        if m_sec:
            section = m_sec.group(1).strip()
            out.setdefault(section, {})
            continue
        m_kv = re.match(r'^([\w.\-]+)\s*=\s*"(.*)"\s*$', line)
        if m_kv and section is not None:
            out[section][m_kv.group(1)] = m_kv.group(2)
    return out


# ────────────────────────────── hooks.py parsing ─────────────────────────


def load_hook_fixtures() -> list[dict[str, Any]]:
    """Read the `fixtures` list from hooks.py without importing the app
    (the puller is a standalone CLI; no bench needed). Uses ast to grab
    the literal value of the `fixtures` assignment."""
    import ast
    src = HOOKS_PATH.read_text()
    tree = ast.parse(src)
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for tgt in node.targets:
                if isinstance(tgt, ast.Name) and tgt.id == "fixtures":
                    return ast.literal_eval(node.value)
    raise RuntimeError("`fixtures = [...]` not found in hooks.py")


# ────────────────────────────── REST API client ──────────────────────────


def fc_get(site: str, path: str, params: dict, key: str, secret: str) -> Any:
    url = f"https://{site}{path}"
    if params:
        url += "?" + urllib.parse.urlencode(params, doseq=True)
    req = urllib.request.Request(
        url, headers={
            "Authorization": f"token {key}:{secret}",
            "Accept": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode("utf-8"))


def fetch_records(site: str, doctype: str, names: list[str],
                  key: str, secret: str) -> list[dict]:
    """Fetch full records for a list of names. Frappe REST returns at
    most ~20 fields by default — use `/api/method/frappe.client.get`
    per name to grab the full document with child tables."""
    out = []
    for name in names:
        resp = fc_get(
            site, "/api/method/frappe.client.get",
            {"doctype": doctype, "name": name}, key, secret,
        )
        msg = resp.get("message")
        if msg:
            out.append(msg)
    return out


def list_names(site: str, doctype: str, filters: list,
               key: str, secret: str) -> list[str]:
    """Expand the `filters` clause from hooks.py into a list of names."""
    params = {
        "doctype": doctype,
        "filters": json.dumps(filters or []),
        "fields": json.dumps(["name"]),
        "limit_page_length": 0,
    }
    resp = fc_get(site, "/api/method/frappe.client.get_list",
                  params, key, secret)
    return [row["name"] for row in (resp.get("message") or [])]


# ────────────────────────────── normalisation ────────────────────────────


def normalise(rec: dict) -> dict:
    """Strip audit fields + sort keys recursively for stable diffs."""
    if isinstance(rec, dict):
        clean = {k: normalise(v) for k, v in rec.items() if k not in NOISY_FIELDS}
        # Sort keys for stable diff
        return dict(sorted(clean.items()))
    if isinstance(rec, list):
        return [normalise(x) for x in rec]
    return rec


# ────────────────────────────── role baseline pull ───────────────────────

ROLE_BASELINE_TARGETS = [
    # (parent, role, permlevel, perm_keys_to_capture, create_if_missing)
    ("Sales Invoice", "Sales Invoice- Custom", 0, [
        "read", "write", "create", "delete", "submit", "cancel", "amend",
        "report", "export", "import", "share", "print", "email", "select",
        "if_owner",
    ], True),
    ("Sales Invoice", "Accounts Manager", 0, ["export"], False),
    ("Sales Invoice", "Accounts User", 0, ["export"], False),
]


def pull_role_baseline(site: str, key: str, secret: str) -> dict:
    """Build the role_perm_baseline.json content from live Custom DocPerm."""
    rows = []
    for parent, role, permlevel, perm_keys, create_if_missing in ROLE_BASELINE_TARGETS:
        names = list_names(
            site, "Custom DocPerm",
            [["parent", "=", parent], ["role", "=", role],
             ["permlevel", "=", permlevel]],
            key, secret,
        )
        if not names:
            # Keep the baseline entry even when missing on prod — so the
            # enforcement still has an authoritative spec to assert.
            print(f"   ⚠ Custom DocPerm not found on prod: "
                  f"{parent} / {role} / pl={permlevel}")
            rows.append({
                "parent": parent, "role": role, "permlevel": permlevel,
                "perms": {k: 0 for k in perm_keys},
                "create_if_missing": create_if_missing,
            })
            continue
        # Multiple rows shouldn't exist (migrate cleans dupes), but if so
        # keep the oldest by creation order — REST returns ordered list.
        live = fetch_records(site, "Custom DocPerm", [names[0]], key, secret)[0]
        rows.append({
            "parent": parent, "role": role, "permlevel": permlevel,
            "perms": {k: int(live.get(k) or 0) for k in perm_keys},
            "create_if_missing": create_if_missing,
        })
    from datetime import datetime, timezone
    return {
        "_comment": (
            "Baseline Custom DocPerm rows that after_migrate enforces every "
            "migrate. Edit this file (or regenerate it from production via "
            "tools/sync_fixtures.py) instead of editing hardcoded values in "
            "migrate.py."
        ),
        "_last_synced": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "_synced_from": site,
        "rows": rows,
    }


# ────────────────────────────── orchestration ────────────────────────────


def diff_summary(old: Any, new: Any) -> tuple[int, int, int]:
    """Crude (added, removed, changed) record-count diff for two lists."""
    if not isinstance(old, list) or not isinstance(new, list):
        return 0, 0, 0
    old_by_name = {r.get("name"): r for r in old if isinstance(r, dict)}
    new_by_name = {r.get("name"): r for r in new if isinstance(r, dict)}
    added = len(set(new_by_name) - set(old_by_name))
    removed = len(set(old_by_name) - set(new_by_name))
    changed = sum(
        1 for n in set(old_by_name) & set(new_by_name)
        if old_by_name[n] != new_by_name[n]
    )
    return added, removed, changed


def write_fixture(path: Path, payload: list, dry_run: bool) -> tuple[int, int, int]:
    if not path.exists():
        old = []
    else:
        try:
            old = json.loads(path.read_text()) or []
        except Exception:
            old = []
    a, r, c = diff_summary(old, payload)
    if dry_run:
        return a, r, c
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=1, ensure_ascii=False) + "\n")
    return a, r, c


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    ap.add_argument("--site", default=DEFAULT_SITE)
    ap.add_argument("--api-key")
    ap.add_argument("--api-secret")
    ap.add_argument("--only", help="Only pull this DocType (e.g. 'Property Setter')")
    ap.add_argument("--skip-role-baseline", action="store_true")
    ap.add_argument("--dry-run", action="store_true",
                    help="Show diff summary but don't write files")
    args = ap.parse_args()

    key, secret = resolve_credentials(args)
    print(f"Pulling fixtures from https://{args.site}/  "
          f"(dry_run={args.dry_run})\n")

    fixtures = load_hook_fixtures()
    if args.only:
        fixtures = [f for f in fixtures if f.get("dt") == args.only]
        if not fixtures:
            sys.exit(f"No fixture spec for DocType {args.only!r} in hooks.py")

    grand_total = {"added": 0, "removed": 0, "changed": 0}
    for spec in fixtures:
        dt = spec.get("dt")
        filters = spec.get("filters")
        if not dt:
            continue
        try:
            names = list_names(args.site, dt, filters, key, secret)
        except urllib.error.HTTPError as e:
            print(f"  ✗ {dt}: list HTTP {e.code} — {e.reason}")
            continue
        records = fetch_records(args.site, dt, names, key, secret)
        records = [normalise(r) for r in records]
        # File naming convention used by Frappe: snake_case of doctype.
        fname = re.sub(r"[^a-z0-9]+", "_", dt.lower()).strip("_") + ".json"
        path = FIXTURES_DIR / fname
        a, r, c = write_fixture(path, records, args.dry_run)
        grand_total["added"] += a
        grand_total["removed"] += r
        grand_total["changed"] += c
        print(f"  • {dt:18s} → {fname:32s}  "
              f"+{a} -{r} ~{c}  (live={len(records)})")

    if not args.skip_role_baseline:
        print("\nRole permission baseline:")
        baseline = pull_role_baseline(args.site, key, secret)
        if args.dry_run:
            existing = (json.loads(ROLE_BASELINE_PATH.read_text())
                        if ROLE_BASELINE_PATH.exists() else {})
            changed = (existing.get("rows") or []) != baseline["rows"]
            print(f"  • role_perm_baseline.json  "
                  f"changed_rows_block={'yes' if changed else 'no'}")
        else:
            ROLE_BASELINE_PATH.parent.mkdir(parents=True, exist_ok=True)
            ROLE_BASELINE_PATH.write_text(
                json.dumps(baseline, indent=2, ensure_ascii=False) + "\n"
            )
            print(f"  • wrote {ROLE_BASELINE_PATH}")

    print(
        f"\nDone. Totals: +{grand_total['added']} added "
        f"-{grand_total['removed']} removed ~{grand_total['changed']} changed."
    )
    if not args.dry_run:
        print("Next: review with `git diff` then commit.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

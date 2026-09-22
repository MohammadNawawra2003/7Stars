#!/usr/bin/env python3
"""Seven Stars — historical booking import, audit first.

    ⚠ AUDIT BEFORE YOU IMPORT. CON-01 will refuse historical overlaps, and that refusal is
    information, not an obstacle. Each clashing pair is either bad source data to correct or
    a genuine past event the client must confirm. Reaching for the bypass first throws that
    information away.

Run it through the Odoo shell, which gives the script a real `env`:

    odoo-bin shell -d <db> --addons-path=... --no-http \
        < tools/import_historical_bookings.py

configured by environment variables:

    SS_SOURCE=tools/sample_historical_bookings.csv   the export to read
    SS_CONFLICTS=conflicts.md                        where to write the conflict list
    SS_IMPORT=1                                      actually create records (default: audit only)
    SS_APPROVED=OLD-007,OLD-008                      refs the client has signed off as real
                                                     past overlaps, loaded under the
                                                     migration bypass

Step 1  audit          SS_SOURCE=... (no SS_IMPORT)      -> writes the conflict list
Step 2  take the list to the client; correct the data or get the overlaps approved
Step 3  import         SS_IMPORT=1 SS_APPROVED=...       -> creates the bookings

The bypass is scoped to this run and needs BOTH the context flag and a management user.
Nothing about it is stored, and CON-01 is refusing overlaps again the moment the run ends —
seven_stars_rental/tests/test_migration.py is what keeps that true.

⚠ sale.order.line.start_date and return_date are related, store=False fields and cannot be
imported. The booking period lives on the ORDER.
"""
import csv
import os
import sys
from collections import defaultdict

SOURCE = os.environ.get('SS_SOURCE', 'tools/sample_historical_bookings.csv')
CONFLICTS_PATH = os.environ.get('SS_CONFLICTS', 'conflicts.md')
DO_IMPORT = os.environ.get('SS_IMPORT') == '1'
APPROVED = {ref.strip() for ref in os.environ.get('SS_APPROVED', '').split(',') if ref.strip()}

MIGRATION_FLAG = 'ss_migration_import'


def read_source(path):
    """Columns: ref, customer, phone, hall_code, start, end, event_type, guests,
    required_deposit, collected. One row per booking."""
    with open(path, encoding='utf-8') as handle:
        return list(csv.DictReader(handle))


def audit(env, rows):
    halls = {
        product.default_code: product
        for product in env['product.template'].search([('default_code', 'like', 'SS-HALL-')])
    }
    missing = sorted({row['hall_code'] for row in rows} - set(halls))
    if missing:
        sys.stderr.write(f"! unknown hall codes in the source: {missing}\n")

    audit_rows = []
    for row in rows:
        hall = halls.get(row['hall_code'])
        audit_rows.append({
            'ref': row['ref'],
            'hall': row['hall_code'],
            'start': row['start'],
            'end': row['end'],
            'prep': hall.prep_time if hall else 4.0,
            'cleanup': hall.cleanup_time if hall else 5.0,
        })
    return env['sale.order'].ss_find_import_conflicts(audit_rows)


def write_conflict_list(path, rows, conflicts):
    by_ref = {row['ref']: row for row in rows}
    lines = [
        "# Seven Stars — historical import conflict list",
        "",
        f"Source: `{SOURCE}` — {len(rows)} bookings read.",
        f"**{len(conflicts)} pair(s) would be refused by CON-01.**",
        "",
        "Each pair is either bad source data to correct, or a genuine past event the client",
        "must confirm. Nothing below is imported until it has been cleaned or approved.",
        "",
    ]
    if not conflicts:
        lines.append("No conflicts. The source data can be imported as it stands.")
    else:
        lines += ["| # | Hall | Booking A | Booking B | A window | B window | Why |",
                  "|---|---|---|---|---|---|---|"]
        for index, conflict in enumerate(conflicts, start=1):
            left, right = conflict['refs']
            (a_start, a_end), (b_start, b_end) = conflict['windows']
            overlap_of_event = a_start < b_end and b_start < a_end
            why = ("the events themselves overlap" if overlap_of_event
                   else "inside the preparation/cleanup window")
            lines.append(
                f"| {index} | {conflict['hall']} | {left} — {by_ref[left]['customer']} "
                f"| {right} — {by_ref[right]['customer']} "
                f"| {a_start} → {a_end} | {b_start} → {b_end} | {why} |")
        lines += ["", "## To proceed", "",
                  "1. Correct the source file where a row is simply wrong, then re-run the audit.",
                  "2. For any pair the client confirms really happened, pass the LATER ref in",
                  "   `SS_APPROVED` so it loads under the migration bypass.",
                  "3. Re-run with `SS_IMPORT=1`."]
    with open(path, 'w', encoding='utf-8') as handle:
        handle.write("\n".join(lines) + "\n")
    return path


def import_rows(env, rows, conflicts):
    conflicting_refs = {ref for conflict in conflicts for ref in conflict['refs']}
    blocked = conflicting_refs - APPROVED
    halls = {
        product.default_code: product.product_variant_id
        for product in env['product.template'].search([('default_code', 'like', 'SS-HALL-')])
    }
    partners = {}
    created, skipped = [], []

    for row in rows:
        if row['ref'] in blocked and row['ref'] not in APPROVED:
            # only skip the SECOND half of an unapproved pair; the first still loads
            if any(row['ref'] == sorted(conflict['refs'])[1]
                   for conflict in conflicts
                   if not APPROVED & set(conflict['refs'])):
                skipped.append(row['ref'])
                continue

        partner = partners.get(row['customer'])
        if not partner:
            partner = env['res.partner'].search([('name', '=', row['customer'])], limit=1)
            if not partner:
                partner = env['res.partner'].create({
                    'name': row['customer'], 'phone': row.get('phone') or False})
            partners[row['customer']] = partner

        model = env['sale.order']
        if row['ref'] in APPROVED:
            model = model.with_context(**{MIGRATION_FLAG: True})

        order = model.create({
            'partner_id': partner.id,
            'is_rental_order': True,
            'rental_start_date': row['start'],
            'rental_return_date': row['end'],
            'event_type': row.get('event_type') or False,
            'guest_count': int(row['guests']) if row.get('guests') else 0,
            'required_deposit_amount': float(row.get('required_deposit') or 0.0),
            'booking_state': 'completed',
            'client_order_ref': row['ref'],
            'order_line': [(0, 0, {'product_id': halls[row['hall_code']].id,
                                   'product_uom_qty': 1, 'is_rental': True})],
        })
        if float(row.get('collected') or 0.0):
            env['seven.stars.payment'].create({
                'order_id': order.id,
                'amount': float(row['collected']),
                'method': 'cash',
                'reference': f"HISTORICAL-{row['ref']}",
            })
        created.append((row['ref'], order.name))
    return created, skipped


def main(env):
    rows = read_source(SOURCE)
    conflicts = audit(env, rows)
    path = write_conflict_list(CONFLICTS_PATH, rows, conflicts)
    print(f"read {len(rows)} bookings from {SOURCE}")
    print(f"{len(conflicts)} conflict pair(s) -> {path}")

    if not DO_IMPORT:
        print("audit only. Review the conflict list with the client, then re-run with "
              "SS_IMPORT=1.")
        return

    unapproved = [conflict for conflict in conflicts if not APPROVED & set(conflict['refs'])]
    if unapproved:
        print(f"⚠ {len(unapproved)} conflict pair(s) are neither corrected nor approved; "
              "the later booking of each pair will be SKIPPED.")

    created, skipped = import_rows(env, rows, conflicts)
    env.cr.commit()
    print(f"imported {len(created)} bookings")
    for ref, name in created:
        print(f"  {ref} -> {name}")
    if skipped:
        print(f"skipped {len(skipped)}: {skipped}")


main(env)      # noqa: F821 — `env` is provided by `odoo-bin shell`

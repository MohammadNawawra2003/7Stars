"""Retire seven.stars.payment before the new data files load.

Money became a posted account.payment on 2026-09-23 (Jamal round 1) and the custom ledger
was deleted. On a database that still holds the old records this breaks the upgrade twice
over, and both failures were reported from Odoo.sh staging:

  ParseError: For external id seven_stars_rental_demo.payment_001_1 when trying to
  create/update a record of model account.payment found record of different model
  seven.stars.payment (53735)

    The starter dataset reuses those external ids for the account.payment records, and Odoo
    refuses to repoint an external id at a different model. The stale ir.model.data rows have
    to be gone before the data files are read — which is what a PRE-migration is for.

  OwlError: Unknown field order_id

    The old search view survives in ir_ui_view and still refers to seven.stars.payment.order_id.

Every local test missed this because they all ran against databases created FROM the new code.
A database created from the old code is the only place it shows.
"""
import logging

_logger = logging.getLogger(__name__)

OBSOLETE_MODEL = 'seven.stars.payment'
OBSOLETE_TABLE = 'seven_stars_payment'


def migrate(cr, version):
    if not version:
        return

    cr.execute("SELECT COUNT(*) FROM ir_model_data WHERE model = %s", (OBSOLETE_MODEL,))
    stale = cr.fetchone()[0]
    _logger.info("Seven Stars: retiring %s (%s external ids)", OBSOLETE_MODEL, stale)

    # Views first: they carry the xmlids too, and a leftover search view on a model that no
    # longer exists makes the Payments menu raise "Unknown field order_id".
    cr.execute("DELETE FROM ir_ui_view WHERE model = %s", (OBSOLETE_MODEL,))
    cr.execute("DELETE FROM ir_act_window WHERE res_model = %s", (OBSOLETE_MODEL,))
    cr.execute("DELETE FROM ir_model_data WHERE model = %s", (OBSOLETE_MODEL,))
    cr.execute(
        "DELETE FROM ir_model_data "
        " WHERE module IN ('seven_stars_rental', 'seven_stars_rental_demo') "
        "   AND name LIKE 'view_seven_stars_payment%%'")
    cr.execute("DELETE FROM ir_model_fields WHERE model = %s", (OBSOLETE_MODEL,))
    cr.execute("DELETE FROM ir_model WHERE model = %s", (OBSOLETE_MODEL,))

    # The starter bookings are declared <odoo noupdate="1">, so an existing database keeps
    # them exactly as first created — while demo_payments IS updatable and its records are
    # recreated here at the NEW amounts, which now include the operational-appendix services.
    # Leaving the pair as it is would show every completed demo booking as overpaid. Letting
    # the bookings re-apply once puts the service lines on them and the two match again.
    # Only the starter dataset's own records are touched; anything Seven Stars created has no
    # external id and is never re-applied.
    cr.execute(
        "UPDATE ir_model_data SET noupdate = false "
        " WHERE module = 'seven_stars_rental_demo' AND model = 'sale.order'")
    _logger.info("Seven Stars: starter bookings unfrozen for one upgrade (%s rows)", cr.rowcount)
    # The rows themselves are history the client may still want; the table is dropped because
    # the model is gone and nothing can read it any more.
    cr.execute(f"DROP TABLE IF EXISTS {OBSOLETE_TABLE} CASCADE")

"""CON-01 — a hall cannot be double-booked (spec §12).

Odoo 19 Rental blocks nothing: sale_renting has no action_confirm, no _action_confirm and no
write override, and its only date constraint is a single-row SQL CHECK that cannot compare
two rows (spec §3.1). Everything asserted here is ours.

The fixtures are built in setUp rather than taken from seven_stars_rental_demo, so these
tests state their own preconditions and cannot be broken by editing demo data.
"""
from datetime import datetime

from odoo import Command
from odoo.exceptions import ValidationError
from odoo.tests import TransactionCase, tagged

from odoo.addons.seven_stars_rental.models.res_config_settings import (
    GUEST_TOLERANCE_KEY, SAME_DAY_GAP_KEY, get_optional_float,
)


@tagged('post_install', '-at_install')
class TestHallAvailability(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.customer = cls.env['res.partner'].create({'name': "عميل اختبار التوفر"})

        def hall(name, capacity):
            return cls.env['product.template'].create({
                'name': name, 'type': 'service', 'rent_ok': True, 'sale_ok': True,
                'list_price': 1000.0, 'hall_capacity': capacity,
                'prep_time': 4.0, 'cleanup_time': 5.0,
                'taxes_id': [Command.clear()],
            }).product_variant_id

        cls.hall_a = hall("TEST Hall A", 600)
        cls.hall_b = hall("TEST Hall B", 550)

    def _booking(self, halls, start, end, **values):
        vals = {
            'partner_id': self.customer.id,
            'is_rental_order': True,
            'rental_start_date': start,
            'rental_return_date': end,
            'order_line': [
                Command.create({'product_id': h.id, 'product_uom_qty': 1, 'is_rental': True})
                for h in halls
            ],
        }
        vals.update(values)
        return self.env['sale.order'].create(vals)

    # ------------------------------------------------------- the core guarantee
    def test_overlapping_booking_on_the_same_hall_is_refused(self):
        self._booking([self.hall_a], datetime(2030, 10, 15, 18, 0), datetime(2030, 10, 15, 22, 0))
        with self.assertRaises(ValidationError):
            self._booking([self.hall_a],
                          datetime(2030, 10, 15, 20, 0), datetime(2030, 10, 15, 23, 0))

    def test_the_message_names_the_hall_and_the_clashing_booking(self):
        first = self._booking([self.hall_a],
                              datetime(2030, 10, 15, 18, 0), datetime(2030, 10, 15, 22, 0))
        with self.assertRaises(ValidationError) as caught:
            self._booking([self.hall_a],
                          datetime(2030, 10, 15, 20, 0), datetime(2030, 10, 15, 23, 0))
        message = str(caught.exception)
        self.assertIn(self.hall_a.display_name, message)
        self.assertIn(first.display_name, message,
                      "the clerk has to be told WHICH booking is in the way")

    def test_the_same_time_in_a_different_hall_is_allowed(self):
        self._booking([self.hall_a], datetime(2030, 10, 15, 18, 0), datetime(2030, 10, 15, 22, 0))
        other = self._booking([self.hall_b],
                              datetime(2030, 10, 15, 18, 0), datetime(2030, 10, 15, 22, 0))
        self.assertTrue(other.id, "two different halls at the same hour must both be bookable")

    # ------------------------------------------------------------------ buffers
    def test_the_cleanup_buffer_blocks_a_later_booking(self):
        """Event ends 22:00, cleanup runs to 03:00. A 02:00 start is inside it."""
        self._booking([self.hall_a], datetime(2030, 10, 15, 18, 0), datetime(2030, 10, 15, 22, 0))
        with self.assertRaises(ValidationError):
            self._booking([self.hall_a],
                          datetime(2030, 10, 16, 2, 0), datetime(2030, 10, 16, 5, 0))

    def test_the_preparation_buffer_blocks_an_earlier_booking(self):
        """Event starts 18:00, preparation starts 14:00. Something ending 15:00 collides."""
        self._booking([self.hall_a], datetime(2030, 11, 20, 18, 0), datetime(2030, 11, 20, 22, 0))
        with self.assertRaises(ValidationError):
            self._booking([self.hall_a],
                          datetime(2030, 11, 20, 11, 0), datetime(2030, 11, 20, 15, 0))

    def test_a_booking_clear_of_both_buffers_is_allowed(self):
        """22:00 + 5h cleanup = 03:00; the next event's 4h preparation starts at 03:00.
        The interval is half-open, so touching envelopes do not collide."""
        self._booking([self.hall_a], datetime(2030, 10, 15, 18, 0), datetime(2030, 10, 15, 22, 0))
        later = self._booking([self.hall_a],
                              datetime(2030, 10, 16, 7, 0), datetime(2030, 10, 16, 11, 0))
        self.assertTrue(later.id)

    # ------------------------------------------------------------ which bookings hold a hall
    def test_a_draft_booking_still_blocks_the_hall(self):
        """A tentative hold on an already-held hall must fail. Proven and intended (spec §12)."""
        self._booking([self.hall_a], datetime(2030, 12, 4, 18, 0), datetime(2030, 12, 4, 22, 0),
                      booking_state='draft')
        with self.assertRaises(ValidationError):
            self._booking([self.hall_a],
                          datetime(2030, 12, 4, 19, 0), datetime(2030, 12, 4, 23, 0),
                          booking_state='tentative')

    def test_a_cancelled_booking_releases_the_hall(self):
        self._booking([self.hall_a], datetime(2030, 12, 11, 18, 0), datetime(2030, 12, 11, 22, 0),
                      booking_state='cancelled')
        replacement = self._booking([self.hall_a],
                                    datetime(2030, 12, 11, 18, 0), datetime(2030, 12, 11, 22, 0))
        self.assertTrue(replacement.id)

    def test_moving_a_booking_onto_an_occupied_slot_is_refused(self):
        self._booking([self.hall_a], datetime(2031, 1, 8, 18, 0), datetime(2031, 1, 8, 22, 0))
        movable = self._booking([self.hall_a],
                                datetime(2031, 3, 8, 18, 0), datetime(2031, 3, 8, 22, 0))
        with self.assertRaises(ValidationError):
            movable.write({
                'rental_start_date': datetime(2031, 1, 8, 19, 0),
                'rental_return_date': datetime(2031, 1, 8, 23, 0),
            })


@tagged('post_install', '-at_install')
class TestDeferredRules(TransactionCase):
    """PRD §22 items 6 and 11 ship UNSET. An absent parameter is not a zero (spec §8)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.customer = cls.env['res.partner'].create({'name': "عميل اختبار الإعدادات"})
        cls.hall = cls.env['product.template'].create({
            'name': "TEST Hall Gap", 'type': 'service', 'rent_ok': True, 'sale_ok': True,
            'list_price': 1000.0, 'hall_capacity': 400,
            'prep_time': 4.0, 'cleanup_time': 5.0,
            'taxes_id': [Command.clear()],
        }).product_variant_id

    def _booking(self, start, end):
        return self.env['sale.order'].create({
            'partner_id': self.customer.id, 'is_rental_order': True,
            'rental_start_date': start, 'rental_return_date': end,
            'order_line': [Command.create(
                {'product_id': self.hall.id, 'product_uom_qty': 1, 'is_rental': True})],
        })

    def _set_gap(self, hours):
        settings = self.env['res.config.settings'].create({
            'same_day_gap_mode': 'configured' if hours is not None else 'pending',
            'same_day_gap_hours': hours or 0.0,
        })
        settings.execute()

    def test_unset_reads_as_none_and_a_stored_zero_reads_as_zero(self):
        """The tri-state itself. get_param returns a string or None, so absent and '0' are
        genuinely different values (runtime T18)."""
        self.env['ir.config_parameter'].sudo().set_param(SAME_DAY_GAP_KEY, False)
        self.assertIsNone(get_optional_float(self.env, SAME_DAY_GAP_KEY))

        self.env['ir.config_parameter'].sudo().set_param(SAME_DAY_GAP_KEY, '0')
        self.assertEqual(get_optional_float(self.env, SAME_DAY_GAP_KEY), 0.0,
                         "a deliberate zero must survive as a zero, not collapse to unset")

        self.env['ir.config_parameter'].sudo().set_param(SAME_DAY_GAP_KEY, False)
        self.assertIsNone(get_optional_float(self.env, GUEST_TOLERANCE_KEY))

    def test_choosing_pending_deletes_the_parameter(self):
        self._set_gap(6.0)
        self.assertEqual(get_optional_float(self.env, SAME_DAY_GAP_KEY), 6.0)
        self._set_gap(None)
        self.assertIsNone(get_optional_float(self.env, SAME_DAY_GAP_KEY),
                          "Pending must remove the key, not store a zero")

    def test_while_the_gap_is_unset_no_extra_separation_is_invented(self):
        self._set_gap(None)
        self._booking(datetime(2031, 5, 6, 8, 0), datetime(2031, 5, 6, 11, 0))
        # 11:00 + 5h cleanup = 16:00; the evening's 4h preparation begins at 16:00. Touching,
        # not overlapping — allowed while no further gap has been agreed.
        evening = self._booking(datetime(2031, 5, 6, 20, 0), datetime(2031, 5, 6, 23, 0))
        self.assertTrue(evening.id)

    def test_once_configured_the_gap_blocks_the_same_pair(self):
        self._set_gap(6.0)
        self._booking(datetime(2031, 5, 7, 8, 0), datetime(2031, 5, 7, 11, 0))
        with self.assertRaises(ValidationError):
            self._booking(datetime(2031, 5, 7, 20, 0), datetime(2031, 5, 7, 23, 0))
        self._set_gap(None)

    def test_the_guest_count_is_recorded_and_blocks_nothing_while_unset(self):
        self.env['ir.config_parameter'].sudo().set_param(GUEST_TOLERANCE_KEY, False)
        booking = self._booking(datetime(2031, 6, 10, 18, 0), datetime(2031, 6, 10, 22, 0))
        booking.guest_count = 900          # hall capacity is 400
        self.assertEqual(booking.guest_count, 900,
                         "the number is always recorded; enforcement is a separate decision")

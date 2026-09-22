"""The eight-state lifecycle and the seven buttons (spec §9.1).

The cancellation and postponement NOTICE rules are Phase 4; the transitions themselves are
here.
"""
from odoo.exceptions import ValidationError
from odoo.tests import tagged

from .common import SevenStarsCommon


@tagged('post_install', '-at_install')
class TestBookingLifecycle(SevenStarsCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.hall = cls._hall("LIFE Hall", 600, 14000.0).product_variant_id
        cls.clerk = cls._user('test_life_clerk', 'group_ss_clerk')
        cls.booking_manager = cls._user('test_life_bm', 'group_ss_booking_manager')

    def _paid_booking(self, day, amount=14000.0, deposit=3000.0):
        order = self._booking([self.hall], *self.evening(2033, 1, day),
                              required_deposit_amount=deposit)
        self.env['seven.stars.payment'].create({'order_id': order.id, 'amount': amount})
        return order

    def test_the_full_eight_state_walk(self):
        order = self._paid_booking(8)
        self.assertEqual(order.booking_state, 'draft')

        order.action_hold_tentative()
        self.assertEqual(order.booking_state, 'tentative')

        order.action_await_deposit()
        self.assertEqual(order.booking_state, 'awaiting')

        order.action_confirm_booking()
        self.assertEqual(order.booking_state, 'confirmed')
        self.assertEqual(order.state, 'sale',
                         "confirming the booking confirms the standard order too")

        order.appendix_event_date = order.rental_start_date.date()
        order.action_mark_ready()
        self.assertEqual(order.booking_state, 'ready')

        order.action_close_booking()
        self.assertEqual(order.booking_state, 'completed')

    def test_the_two_state_fields_are_independent(self):
        """Standard `state` has four values and keeps its own meaning; booking_state carries
        the eight the PRD asks for. Verified coexisting at runtime (T4)."""
        order = self._paid_booking(15)
        self.assertEqual(order.state, 'draft')
        order.action_hold_tentative()
        self.assertEqual(order.booking_state, 'tentative')
        self.assertEqual(order.state, 'draft', "a tentative hold is not a confirmed sale")

    def test_postponing_a_confirmed_booking(self):
        order = self._paid_booking(22)
        order.action_confirm_booking()
        order.action_postpone()
        self.assertEqual(order.booking_state, 'postponed')

    def test_closing_settles_the_rental_quantities_and_clears_the_late_flag(self):
        """"Late Pickup" is permanent while qty_delivered is below the ordered quantity
        (spec §3.2, runtime T5), so a closed booking must settle its quantities or it reads
        as late for ever."""
        order = self._paid_booking(29)
        order.action_confirm_booking()
        order.appendix_event_date = order.rental_start_date.date()
        order.action_mark_ready()
        order.action_close_booking()

        for line in order.order_line.filtered('is_rental'):
            self.assertEqual(line.qty_delivered, line.product_uom_qty)
            self.assertEqual(line.qty_returned, line.product_uom_qty)
        self.assertEqual(order.rental_status, 'returned')
        self.assertFalse(order.is_late)

    def test_marking_ready_is_refused_until_the_appendix_is_started(self):
        """BTN-04's guard (spec §9.1). Only the appendix's anchor field is enforced: the
        client never said which of the fifteen items make it "complete", and guessing would
        block real work."""
        order = self._paid_booking(30)
        order.action_confirm_booking()
        self.assertFalse(order.appendix_event_date)
        with self.assertRaises(ValidationError):
            order.action_mark_ready()
        self.assertEqual(order.booking_state, 'confirmed')

        order.appendix_event_date = order.rental_start_date.date()
        order.action_mark_ready()
        self.assertEqual(order.booking_state, 'ready')

    # --------------------------------------------------------------- cancellation
    def test_a_booking_manager_may_cancel(self):
        order = self._booking([self.hall], *self.evening(2033, 2, 5))
        order.with_user(self.booking_manager).action_cancel_booking()
        self.assertEqual(order.booking_state, 'cancelled')
        self.assertEqual(order.state, 'cancel')

    def test_a_clerk_may_not_cancel(self):
        """The view's groups= attribute only hides the button; the method is reachable over
        RPC, so the right is checked server-side as well."""
        order = self._booking([self.hall], *self.evening(2033, 2, 12), user=self.clerk)
        with self.assertRaises(ValidationError):
            order.with_user(self.clerk).action_cancel_booking()
        self.assertNotEqual(order.booking_state, 'cancelled')

    def test_a_cancelled_booking_frees_the_hall_for_the_same_slot(self):
        window = self.evening(2033, 2, 19)
        first = self._booking([self.hall], *window)
        first.with_user(self.booking_manager).action_cancel_booking()
        replacement = self._booking([self.hall], *window)
        self.assertTrue(replacement.id)

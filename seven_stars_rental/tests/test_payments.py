"""Money (spec §6, §6.1) — CON-03 and CON-04.

seven.stars.payment rows are the only record of money actually received. Everything on the
booking that looks like received money is a stored compute over them.
"""
from odoo import Command
from odoo.exceptions import ValidationError
from odoo.tests import tagged

from .common import SevenStarsCommon


@tagged('post_install', '-at_install')
class TestPayments(SevenStarsCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.hall = cls._hall("PAY Hall", 600, 14000.0).product_variant_id
        cls.clerk = cls._user('test_pay_clerk', 'group_ss_clerk')
        cls.manager = cls._user('test_pay_manager', 'group_ss_manager')

    def _pay(self, order, amount, method='cash', reference=False):
        return self.env['seven.stars.payment'].create({
            'order_id': order.id, 'amount': amount,
            'method': method, 'reference': reference,
        })

    # ------------------------------------------------------------- the computes
    def test_collected_and_outstanding_follow_the_payment_rows(self):
        order = self._booking([self.hall], *self.evening(2032, 3, 5))
        self.assertEqual(order.amount_total, 14000.0)
        self.assertEqual(order.collected_amount, 0.0)
        self.assertEqual(order.outstanding_amount, 14000.0)

        self._pay(order, 3000.0)
        self.assertEqual(order.collected_amount, 3000.0)
        self.assertEqual(order.outstanding_amount, 11000.0)

        self._pay(order, 5000.0, method='transfer', reference='TRF-1')
        self.assertEqual(order.collected_amount, 8000.0)
        self.assertEqual(order.outstanding_amount, 6000.0)

        self._pay(order, 6000.0)
        self.assertEqual(order.collected_amount, 14000.0)
        self.assertEqual(order.outstanding_amount, 0.0,
                         "the balance has to reach exactly zero, not almost zero")

    def test_removing_a_payment_row_moves_the_balance_back(self):
        """Proves the direction of truth: the rows drive the totals, never the reverse."""
        order = self._booking([self.hall], *self.evening(2032, 3, 12))
        first = self._pay(order, 3000.0)
        self._pay(order, 2000.0)
        self.assertEqual(order.collected_amount, 5000.0)

        first.unlink()
        self.assertEqual(order.collected_amount, 2000.0)
        self.assertEqual(order.outstanding_amount, 12000.0)

    def test_no_received_money_is_stored_outside_seven_stars_payment(self):
        """required_deposit_amount is a TERM. Setting it must move nothing (spec §6.1)."""
        order = self._booking([self.hall], *self.evening(2032, 3, 19))
        order.required_deposit_amount = 3000.0
        self.assertEqual(order.collected_amount, 0.0,
                         "agreeing a deposit is not the same as receiving one")
        self.assertEqual(order.outstanding_amount, order.amount_total)

    # -------------------------------------------------------------------- CON-03
    def test_confirmation_is_refused_until_the_deposit_has_arrived(self):
        order = self._booking([self.hall], *self.evening(2032, 4, 2), user=self.clerk,
                              required_deposit_amount=3000.0, booking_state='awaiting')
        with self.assertRaises(ValidationError):
            order.with_user(self.clerk).action_confirm_booking()
        self.assertEqual(order.booking_state, 'awaiting')

    def test_confirmation_succeeds_once_the_deposit_has_arrived(self):
        order = self._booking([self.hall], *self.evening(2032, 4, 9), user=self.clerk,
                              required_deposit_amount=3000.0, booking_state='awaiting')
        self._pay(order, 3000.0)
        order.with_user(self.clerk).action_confirm_booking()
        self.assertEqual(order.booking_state, 'confirmed')

    def test_a_partial_deposit_is_still_refused(self):
        order = self._booking([self.hall], *self.evening(2032, 4, 16), user=self.clerk,
                              required_deposit_amount=3000.0, booking_state='awaiting')
        self._pay(order, 2999.0)
        with self.assertRaises(ValidationError):
            order.with_user(self.clerk).action_confirm_booking()

    def test_management_may_confirm_without_the_deposit(self):
        """The authorised exception of spec §23.3 G3, and the waiver is written down."""
        order = self._booking([self.hall], *self.evening(2032, 4, 23), user=self.clerk,
                              required_deposit_amount=3000.0, booking_state='awaiting')
        order.with_user(self.manager).action_confirm_booking()

        self.assertEqual(order.booking_state, 'confirmed')
        self.assertEqual(order.collected_amount, 0.0, "no money was invented by the waiver")
        bodies = order.message_ids.mapped('body')
        self.assertTrue(any('استثناء إداري' in body for body in bodies),
                        "the waiver must be visible in the chatter")

    # -------------------------------------------------------------------- CON-04
    def test_closing_is_refused_while_money_is_owed(self):
        order = self._booking([self.hall], *self.evening(2032, 5, 7),
                              required_deposit_amount=3000.0)
        self._pay(order, 3000.0)
        order.action_confirm_booking()
        order.appendix_event_date = order.rental_start_date.date()
        order.action_mark_ready()
        with self.assertRaises(ValidationError):
            order.action_close_booking()
        self.assertEqual(order.booking_state, 'ready')

    def test_closing_succeeds_once_the_balance_is_zero(self):
        order = self._booking([self.hall], *self.evening(2032, 5, 14),
                              required_deposit_amount=3000.0)
        self._pay(order, 3000.0)
        order.action_confirm_booking()
        order.appendix_event_date = order.rental_start_date.date()
        order.action_mark_ready()
        self._pay(order, 11000.0)
        self.assertEqual(order.outstanding_amount, 0.0)

        order.action_close_booking()
        self.assertEqual(order.booking_state, 'completed')

    # ------------------------------------------------------------ no accounting
    def test_a_whole_booking_creates_no_accounting_document(self):
        """The workflow implements no accounting (spec §1.2). The modules exist only because
        sale_renting -> sale -> account_payment -> account requires them."""
        moves_before = self.env['account.move'].search_count([])
        payments_before = self.env['account.payment'].search_count([])

        order = self._booking([self.hall], *self.evening(2032, 6, 4),
                              required_deposit_amount=3000.0)
        self._pay(order, 3000.0)
        order.action_confirm_booking()
        order.appendix_event_date = order.rental_start_date.date()
        order.action_mark_ready()
        self._pay(order, 11000.0)
        order.action_close_booking()

        self.assertEqual(self.env['account.move'].search_count([]), moves_before)
        self.assertEqual(self.env['account.payment'].search_count([]), payments_before)
        self.assertFalse(order.invoice_ids)

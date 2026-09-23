"""Money (spec §6, §6.1) — CON-03 and CON-04.

Posted account.payment records are the only record of money actually received. Everything on
the booking that looks like received money is a stored compute over them.

Since 2026-09-23 the money is real accounting: confirming a booking posts the contract's
invoice and settles the payments already taken against it (Jamal's round-1 feedback).
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

    # ------------------------------------------------------------- the computes
    def test_collected_and_outstanding_follow_the_payment_rows(self):
        order = self._booking([self.hall], *self.evening(2032, 3, 5))
        self.assertEqual(order.amount_total, 14000.0)
        self.assertEqual(order.collected_amount, 0.0)
        self.assertEqual(order.outstanding_amount, 14000.0)

        self._pay(order, 3000.0)
        self.assertEqual(order.collected_amount, 3000.0)
        self.assertEqual(order.outstanding_amount, 11000.0)

        self._pay(order, 5000.0, transfer=True, memo='TRF-1')
        self.assertEqual(order.collected_amount, 8000.0)
        self.assertEqual(order.outstanding_amount, 6000.0)

        self._pay(order, 6000.0)
        self.assertEqual(order.collected_amount, 14000.0)
        self.assertEqual(order.outstanding_amount, 0.0,
                         "the balance has to reach exactly zero, not almost zero")

    def test_cancelling_a_payment_moves_the_balance_back(self):
        """Proves the direction of truth: the payments drive the totals, never the reverse.

        A posted payment is cancelled rather than deleted — it is an accounting document now.
        """
        order = self._booking([self.hall], *self.evening(2032, 3, 12))
        self._pay(order, 3000.0)
        self._pay(order, 2000.0)
        self.assertEqual(order.collected_amount, 5000.0)

        order.payment_ids.sorted('id')[0].sudo().action_cancel()
        self.assertEqual(order.collected_amount, 2000.0)
        self.assertEqual(order.outstanding_amount, 12000.0)

    def test_no_received_money_is_stored_outside_the_payments(self):
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

    # -------------------------------------------------------------- the accounting
    # «بعد تغيير الحالة الى مؤكد — فوترة اوتوماتيكية على المحاسبة، والدفعات التي تم انشاؤها
    #  يتم تسويتها من الفاتورة المصدرة على العقد»  — Jamal, 2026-09-23.
    def test_a_payment_is_a_posted_accounting_document(self):
        order = self._booking([self.hall], *self.evening(2032, 6, 4))
        self._pay(order, 3000.0)

        payment = order.payment_ids
        self.assertEqual(len(payment), 1)
        self.assertIn(payment.state, ('in_process', 'paid'))
        self.assertTrue(payment.move_id, "a payment must reach the general ledger")
        self.assertEqual(payment.move_id.state, 'posted')

    def test_a_payment_is_in_the_bookings_currency(self):
        """A hall is paid in shekels. A payment takes the COMPANY's currency unless it is
        told otherwise, which once put «$ 5,000.00» on a ₪ 15,000.00 booking."""
        order = self._booking([self.hall], *self.evening(2032, 8, 6))
        self._pay(order, 1000.0)

        self.assertEqual(order.payment_ids.currency_id, order.currency_id)

    def test_confirming_a_booking_invoices_it_automatically(self):
        order = self._booking([self.hall], *self.evening(2032, 6, 11),
                              required_deposit_amount=3000.0, booking_state='awaiting')
        self._pay(order, 3000.0)
        self.assertFalse(order.invoice_ids, "nothing is invoiced before «مؤكد»")

        order.action_confirm_booking()

        invoice = order.invoice_ids
        self.assertEqual(len(invoice), 1, "one invoice for the contract")
        self.assertEqual(invoice.state, 'posted')
        self.assertEqual(invoice.amount_total, order.amount_total,
                         "the WHOLE contract is invoiced, not just the deposit")

    def test_the_deposit_is_settled_from_the_contract_invoice(self):
        """The deposit arrives before the invoice exists, so it waits as an outstanding
        credit on the customer and is reconciled the moment the invoice is posted."""
        order = self._booking([self.hall], *self.evening(2032, 6, 18),
                              required_deposit_amount=3000.0, booking_state='awaiting')
        self._pay(order, 3000.0)
        order.action_confirm_booking()

        invoice = order.invoice_ids
        self.assertEqual(invoice.amount_residual, 11000.0,
                         "14,000 invoiced less the 3,000 deposit already taken")
        self.assertTrue(order.payment_ids.move_id.line_ids.filtered('reconciled'))

    def test_the_balance_reaches_the_customer_receivable(self):
        """«وعلى الرصيد الذمة» — what the customer owes is visible on their account."""
        order = self._booking([self.hall], *self.evening(2032, 6, 25),
                              required_deposit_amount=3000.0, booking_state='awaiting')
        self._pay(order, 3000.0)
        order.action_confirm_booking()

        receivable = self.env['account.move.line'].search([
            ('partner_id', '=', order.partner_id.id),
            ('account_id.account_type', '=', 'asset_receivable'),
            ('parent_state', '=', 'posted'),
        ])
        self.assertEqual(sum(receivable.mapped('amount_residual')), 11000.0)

    def test_paying_the_rest_clears_the_invoice(self):
        order = self._booking([self.hall], *self.evening(2032, 7, 2),
                              required_deposit_amount=3000.0, booking_state='awaiting')
        self._pay(order, 3000.0)
        order.action_confirm_booking()
        self._pay(order, 11000.0)

        self.assertEqual(order.outstanding_amount, 0.0)
        self.assertEqual(order.invoice_ids.amount_residual, 0.0)
        self.assertEqual(order.invoice_ids.payment_state, 'paid')

    def test_confirming_twice_raises_only_one_invoice(self):
        order = self._booking([self.hall], *self.evening(2032, 7, 9),
                              required_deposit_amount=3000.0, booking_state='awaiting')
        self._pay(order, 3000.0)
        order.action_confirm_booking()
        order._ss_invoice_booking()

        self.assertEqual(len(order.invoice_ids), 1)

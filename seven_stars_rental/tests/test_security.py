"""PRD §17 — the permission matrix, verified from a real session per role (spec §11).

⚠ Never assert a permission as admin. uid 1 bypasses every ACL (odoo/orm/models.py:3377),
so a check that passes as admin has verified nothing. Every test here goes through
with_user() on a user created for the purpose.

⚠ And env.su is not a way to recognise an administrator: Odoo 19 runs @api.constrains with
su=True whatever the real uid, which is why every guard in this addon asks env.user.

The matrix, from Appendix A item 30: «منع موظف الحجوزات ومدير الحجوزات من تغيير السعر ومنح
الخصم وإلغاء حجز مؤكد واسترجاع الأموال والتعديل بعد التوقيع والموافقة على التمديد».
"""
from odoo import Command
from odoo.exceptions import AccessError, ValidationError
from odoo.tests import tagged

from .common import SevenStarsCommon


@tagged('post_install', '-at_install')
class TestPermissionMatrix(SevenStarsCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.hall = cls._hall("SEC Hall", 600, 14000.0).product_variant_id
        cls.other_hall = cls._hall("SEC Hall Two", 400, 2500.0).product_variant_id

        cls.clerk = cls._user('test_sec_clerk', 'group_ss_clerk')
        cls.other_clerk = cls._user('test_sec_clerk2', 'group_ss_clerk')
        cls.accountant = cls._user('test_sec_accountant', 'group_ss_accountant')
        cls.booking_manager = cls._user('test_sec_bm', 'group_ss_booking_manager')
        cls.manager = cls._user('test_sec_manager', 'group_ss_manager')

    def _confirmed(self, day, user=None):
        order = self._booking([self.hall], *self.evening(2038, 1, day),
                              user=user or self.clerk)
        # deliberately NOT sudo(): sudo keeps the original uid, so it grants no group
        # membership and the §17 guards refuse it — which is the point. Every set-up step
        # here goes through the role that is actually entitled to it.
        order.with_user(self.manager).write({'required_deposit_amount': 5000.0})
        self._pay(order, 5000.0)
        order.with_user(self.manager).action_confirm_booking()
        return order

    # ------------------------------------------------- the record layer, free
    def test_a_clerk_cannot_see_another_clerks_booking(self):
        """Half the matrix comes free: sale.sale_order_personal_rule confines a salesman
        without "all leads" to their own documents (spec §3.4). No custom rule needed."""
        theirs = self._booking([self.hall], *self.evening(2038, 2, 5), user=self.other_clerk)
        with self.assertRaises(AccessError):
            theirs.with_user(self.clerk).read(['name'])

    def test_a_bookings_manager_sees_every_booking(self):
        theirs = self._booking([self.hall], *self.evening(2038, 2, 12), user=self.other_clerk)
        self.assertTrue(theirs.with_user(self.booking_manager).read(['name']))

    def test_the_accountant_sees_every_booking_but_cannot_edit_it(self):
        theirs = self._booking([self.hall], *self.evening(2038, 2, 19), user=self.other_clerk)
        self.assertTrue(theirs.with_user(self.accountant).read(['name', 'outstanding_amount']))
        with self.assertRaises(AccessError):
            theirs.with_user(self.accountant).write({'guest_count': 500})

    # --------------------------------------------------------- «تغيير السعر»
    def test_neither_clerk_nor_bookings_manager_may_change_a_price(self):
        order = self._booking([self.hall], *self.evening(2038, 3, 5), user=self.clerk)
        for user in (self.clerk, self.booking_manager):
            with self.subTest(role=user.login), self.assertRaises(ValidationError):
                order.with_user(user).order_line.write({'price_unit': 1.0})
        order.with_user(self.manager).order_line.write({'price_unit': 13000.0})
        self.assertEqual(order.order_line.price_unit, 13000.0)

    # ---------------------------------------------------------- «منح الخصم»
    def test_neither_clerk_nor_bookings_manager_may_discount(self):
        order = self._booking([self.hall], *self.evening(2038, 3, 12), user=self.clerk)
        for user in (self.clerk, self.booking_manager):
            with self.subTest(role=user.login), self.assertRaises(ValidationError):
                order.with_user(user).order_line.write({'discount': 2.0})

    # ------------------------------------------------------- «اعتماد السعر»
    def test_price_approved_is_absent_from_a_clerks_form(self):
        """The clerk must not see the approval control. This is asserted against the
        RENDERED form, which is what she actually looks at — not against fields_get().

        ⚠ price_approved deliberately carries no Python groups=. A field-level ACL on
        sale.order reaches every order in the database, and adding one here broke NINE
        standard `sale` tests with AccessError. The view hides it; the write guard below is
        what enforces it."""
        order = self._booking([self.hall], *self.evening(2038, 3, 19), user=self.clerk)
        clerk_form = order.with_user(self.clerk).get_view(
            self.env.ref('sale.view_order_form').id, 'form')['arch']
        self.assertNotIn('price_approved', clerk_form)

        manager_form = order.with_user(self.manager).get_view(
            self.env.ref('sale.view_order_form').id, 'form')['arch']
        self.assertIn('price_approved', manager_form)

    def test_a_clerk_cannot_write_price_approved(self):
        order = self._booking([self.hall], *self.evening(2038, 3, 19), user=self.clerk)
        with self.assertRaises(ValidationError):
            order.with_user(self.clerk).write({'price_approved': True})
        self.assertFalse(order.price_approved)

    def test_an_ordinary_sale_order_is_untouched_by_the_field(self):
        """The regression that forced this design: reading every field of a plain quotation
        as a salesman must keep working."""
        product = self._service("SEC Service", 1000.0)
        quotation = self.env['sale.order'].with_user(self.clerk).create({
            'partner_id': self.customer.id,
            'order_line': [Command.create({
                'product_id': product.product_variant_id.id, 'product_uom_qty': 1})],
        })
        self.assertTrue(quotation.read())      # all fields, as a non-manager

    def test_a_clerk_can_still_open_a_booking_form(self):
        """Restricting a field must not break the screen for the people who use it most."""
        order = self._booking([self.hall], *self.evening(2038, 3, 26), user=self.clerk)
        view = order.with_user(self.clerk).get_view(
            self.env.ref('sale.view_order_form').id, 'form')
        self.assertIn('arch', view)
        self.assertTrue(order.with_user(self.clerk).read(
            ['booking_state', 'collected_amount', 'outstanding_amount']))

    # ------------------------------------------------- «العربون» is a term
    def test_only_management_sets_the_agreed_deposit(self):
        order = self._booking([self.hall], *self.evening(2038, 4, 2), user=self.clerk)
        with self.assertRaises(ValidationError):
            order.with_user(self.clerk).write({'required_deposit_amount': 1.0})
        order.with_user(self.manager).write({'required_deposit_amount': 5000.0})
        self.assertEqual(order.required_deposit_amount, 5000.0)

    # --------------------------------------------------- «إلغاء حجز مؤكد»
    def test_a_bookings_manager_may_cancel_an_enquiry_but_not_a_confirmed_booking(self):
        enquiry = self._booking([self.hall], *self.evening(2038, 5, 7), user=self.clerk)
        enquiry.with_user(self.booking_manager).action_cancel_booking()
        self.assertEqual(enquiry.booking_state, 'cancelled')

        confirmed = self._confirmed(14)
        with self.assertRaises(ValidationError):
            confirmed.with_user(self.booking_manager).action_cancel_booking()
        self.assertEqual(confirmed.booking_state, 'confirmed')

        confirmed.with_user(self.manager).action_cancel_booking()
        self.assertEqual(confirmed.booking_state, 'cancelled')

    def test_a_clerk_may_not_cancel_anything(self):
        enquiry = self._booking([self.hall], *self.evening(2038, 5, 21), user=self.clerk)
        with self.assertRaises(ValidationError):
            enquiry.with_user(self.clerk).action_cancel_booking()

    # ------------------------------------------------- «التعديل بعد التوقيع»
    def test_a_signed_booking_may_not_be_edited_by_a_clerk(self):
        confirmed = self._confirmed(28)
        for vals in (
            {'rental_return_date': self.evening(2038, 1, 28)[1].replace(hour=23, minute=59)},
            {'event_type': 'henna'},
            {'partner_id': self.env['res.partner'].create({'name': "SEC other"}).id},
        ):
            with self.subTest(vals=list(vals)), self.assertRaises(ValidationError):
                confirmed.with_user(self.clerk).write(vals)

    def test_an_unsigned_booking_may_still_be_edited_by_its_clerk(self):
        enquiry = self._booking([self.hall], *self.evening(2038, 6, 4), user=self.clerk)
        enquiry.with_user(self.clerk).write({'event_type': 'henna', 'guest_count': 300})
        self.assertEqual(enquiry.event_type, 'henna')

    # ------------------------------------------- «الموافقة على التمديد»
    def test_extending_a_confirmed_booking_is_management_only(self):
        """Extending is moving rental_return_date on a signed booking, which the same rule
        already covers — no separate mechanism was invented for it."""
        confirmed = self._confirmed(11 + 20)
        later = confirmed.rental_return_date.replace(hour=23, minute=59)
        with self.assertRaises(ValidationError):
            confirmed.with_user(self.booking_manager).write({'rental_return_date': later})
        confirmed.with_user(self.manager).write({'rental_return_date': later})
        self.assertEqual(confirmed.rental_return_date, later)

    # ------------------------------------------------- «استرجاع الأموال»
    def test_a_refund_is_management_only(self):
        order = self._booking([self.hall], *self.evening(2038, 7, 2), user=self.clerk)
        self._pay(order, 3000.0, user=self.clerk)

        with self.assertRaises(ValidationError):
            self._pay(order, 1000.0, user=self.clerk, refund=True)

        self._pay(order, 1000.0, user=self.manager, refund=True, memo='REFUND-1')
        self.assertEqual(order.collected_amount, 2000.0,
                         "a refund is an outbound payment, so one ledger stays the truth")

    # ----------------------------------------------------- payments and closing
    def test_a_clerk_and_an_accountant_may_both_record_a_payment(self):
        order = self._booking([self.hall], *self.evening(2038, 8, 6), user=self.clerk)
        for user in (self.clerk, self.accountant):
            with self.subTest(role=user.login):
                self._pay(order, 1000.0, user=user)
        self.assertEqual(order.collected_amount, 2000.0)

    def test_a_payment_is_not_the_staff_to_erase_or_edit(self):
        """It is a posted accounting document now — correcting it is an accounting act, and
        neither the clerk nor the Seven Stars accountant holds accounting rights."""
        order = self._booking([self.hall], *self.evening(2038, 8, 13), user=self.clerk)
        self._pay(order, 1000.0, user=self.clerk)
        payment = order.payment_ids

        for user in (self.clerk, self.accountant):
            with self.subTest(role=user.login):
                with self.assertRaises(AccessError):
                    payment.with_user(user).unlink()
                with self.assertRaises(AccessError):
                    payment.with_user(user).write({'amount': 5.0})

    def test_closing_a_booking_is_management_only(self):
        order = self._confirmed(8)
        order.with_user(self.manager).write({'appendix_event_date': '2038-01-08'})
        order.with_user(self.manager).action_mark_ready()
        self._pay(order, order.outstanding_amount)

        for user in (self.clerk, self.booking_manager):
            with self.subTest(role=user.login), self.assertRaises(ValidationError):
                order.with_user(user).action_close_booking()

        order.with_user(self.manager).action_close_booking()
        self.assertEqual(order.booking_state, 'completed')

    def test_management_may_confirm_without_the_deposit_but_a_clerk_may_not(self):
        """CON-03's two branches, each from a real session (spec §6.1, §23.3 G3)."""
        clerk_order = self._booking([self.hall], *self.evening(2038, 9, 3), user=self.clerk)
        clerk_order.with_user(self.manager).write({'required_deposit_amount': 5000.0})
        clerk_order.with_user(self.clerk).action_hold_tentative()
        clerk_order.with_user(self.clerk).action_await_deposit()
        with self.assertRaises(ValidationError):
            clerk_order.with_user(self.clerk).action_confirm_booking()

        manager_order = self._booking([self.hall], *self.evening(2038, 9, 10), user=self.clerk)
        manager_order.with_user(self.manager).write({'required_deposit_amount': 5000.0})
        manager_order.with_user(self.clerk).action_hold_tentative()
        manager_order.with_user(self.clerk).action_await_deposit()
        manager_order.with_user(self.manager).action_confirm_booking()
        self.assertEqual(manager_order.booking_state, 'confirmed')


@tagged('post_install', '-at_install')
class TestNoCollateralDamage(SevenStarsCommon):
    """This addon adds fields and a model to sale.order, which EVERY Odoo user touches.
    Both regressions below were found by running the standard `sale` and `sale_renting`
    suites with this addon installed — our own tests could not have caught them, because
    they are about records that are not ours.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.plain_user = cls.env['res.users'].create({
            'name': "Plain salesperson", 'login': 'test_plain_salesperson',
            'group_ids': [Command.set([
                cls.env.ref('base.group_user').id,
                cls.env.ref('sales_team.group_sale_salesman').id,
            ])],
        })
        cls.product = cls._service("PLAIN Service", 1000.0)

    def test_a_plain_salesperson_can_read_a_whole_quotation(self):
        """`payment_ids` points at account.payment, and it sits on EVERY sale.order.
        Without a read ACL for internal users, reading all fields of any quotation raised
        AccessError and broke four standard `sale` tests."""
        quotation = self.env['sale.order'].with_user(self.plain_user).create({
            'partner_id': self.customer.id,
            'order_line': [Command.create({
                'product_id': self.product.product_variant_id.id, 'product_uom_qty': 1})],
        })
        self.assertTrue(quotation.read(), "a plain salesperson must be able to read an order")

    def test_a_plain_salesperson_cannot_record_a_payment(self):
        """Read access is not write access."""
        booking = self._booking(
            [self._hall("PLAIN Hall", 400, 2500.0).product_variant_id],
            *self.evening(2039, 5, 6))
        with self.assertRaises(AccessError):
            self.env['ss.payment.register'].with_user(self.plain_user).create({
                'order_id': booking.id, 'amount': 100.0})

    def test_an_ordinary_rental_product_is_not_treated_as_a_hall(self):
        """A hall is a rental product WITH A CAPACITY. Ordinary rental products are not
        exclusive — Odoo Rental will rent two of the same projector at once — and keying the
        availability rule on "is a rental line" refused a standard sale_renting booking for a
        Projector and broke two upstream tests."""
        projector = self.env['product.template'].create({
            'name': "PLAIN Projector", 'type': 'service', 'rent_ok': True, 'sale_ok': True,
            'list_price': 50.0, 'taxes_id': [Command.clear()]})
        self.assertEqual(projector.hall_capacity, 0)

        first = self._booking([projector.product_variant_id], *self.evening(2039, 6, 3))
        second = self._booking([projector.product_variant_id], *self.evening(2039, 6, 3))
        self.assertTrue(second.id, "two projectors may be rented at the same time")
        self.assertFalse(first._ss_is_hall_booking())

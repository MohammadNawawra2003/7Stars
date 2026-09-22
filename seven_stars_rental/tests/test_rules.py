"""Phase 4 — the business rules bite (spec §12, §13).

Seasonal and midweek pricing, the 5% discount ceiling, the summed-capacity guest check,
the hall lock, and the two reminders.
"""
from datetime import datetime

from odoo import Command
from odoo.exceptions import ValidationError
from odoo.tests import Form, tagged

from .common import SevenStarsCommon
from odoo.addons.seven_stars_rental.models.res_config_settings import GUEST_TOLERANCE_KEY
from odoo.addons.seven_stars_rental.models.sale_order import MIDWEEK_WEEKDAYS_KEY


@tagged('post_install', '-at_install')
class TestSeasonalPricing(SevenStarsCommon):
    """The prices themselves are ordinary product.pricing master data. What is custom is
    only CHOOSING the pricelist from the event date, which the client asked for by name."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.hall_men = cls._hall("RULE Hall Men", 600, 14000.0)
        cls.hall_women = cls._hall("RULE Hall Women", 550, 14000.0)
        cls.v_men = cls.hall_men.product_variant_id
        cls.v_women = cls.hall_women.product_variant_id

        def price(pricelist_xmlid, men, women):
            pricelist = cls.env.ref(f'seven_stars_rental.{pricelist_xmlid}')
            cls.env['product.pricing'].create([
                {'product_template_id': cls.hall_men.id, 'pricelist_id': pricelist.id,
                 'recurrence_id': cls.recurrence.id, 'price': men},
                {'product_template_id': cls.hall_women.id, 'pricelist_id': pricelist.id,
                 'recurrence_id': cls.recurrence.id, 'price': women},
            ])
            return pricelist

        cls.pl_pair = price('pricelist_wedding_pair', 14000.0, 0.0)
        cls.pl_pair_reduced = price('pricelist_wedding_pair_reduced', 12000.0, 0.0)
        cls.pl_winter = price('pricelist_winter', 12000.0, 12000.0)
        cls.pl_midweek = price('pricelist_midweek', 12000.0, 12000.0)
        cls.pl_standard = cls.env.ref('seven_stars_rental.pricelist_standard')

    def _form_booking(self, halls, start, end):
        """Through a real Form, so the onchange fires exactly as it does for a clerk."""
        form = Form(self.env['sale.order'].with_context(in_rental_app=True))
        form.partner_id = self.customer
        form.rental_start_date = start
        form.rental_return_date = end
        for hall in halls:
            with form.order_line.new() as line:
                line.product_id = hall
        return form

    def test_a_december_wedding_on_both_halls_is_exactly_12000(self):
        """The Phase 4 acceptance case. 12000, never 24000 and never 28000."""
        form = self._form_booking([self.v_men, self.v_women],
                                  datetime(2036, 12, 17, 18, 0), datetime(2036, 12, 17, 23, 0))
        self.assertEqual(form.pricelist_id, self.pl_pair_reduced,
                         "a December pair must land on the reduced wedding pricelist")
        order = form.save()
        self.assertEqual(order.amount_total, 12000.0)

        order.action_update_prices()
        self.assertEqual(order.amount_total, 12000.0,
                         "the seasonal pair price must survive a forced recomputation")

    def test_a_summer_wedding_on_both_halls_is_exactly_14000(self):
        form = self._form_booking([self.v_men, self.v_women],
                                  datetime(2036, 7, 16, 18, 0), datetime(2036, 7, 16, 23, 0))
        self.assertEqual(form.pricelist_id, self.pl_pair)
        self.assertEqual(form.save().amount_total, 14000.0)

    def test_a_single_hall_in_winter_takes_the_winter_pricelist(self):
        form = self._form_booking([self.v_men],
                                  datetime(2036, 1, 15, 18, 0), datetime(2036, 1, 15, 23, 0))
        self.assertEqual(form.pricelist_id, self.pl_winter)
        self.assertEqual(form.save().amount_total, 12000.0)

    def test_winter_is_december_to_march(self):
        """«خصم الشتاء (12 حتى 3)» — the client's own words."""
        order = self.env['sale.order'].new({'is_rental_order': True})
        for month, winter in ((12, True), (1, True), (2, True), (3, True),
                              (4, False), (7, False), (11, False)):
            order.rental_start_date = datetime(2036, month, 10, 18, 0)
            self.assertEqual(order._ss_is_winter(), winter, f"month {month}")

    def test_midweek_enforces_nothing_until_the_days_are_configured(self):
        """The midweek discount exists, but WHICH days was never stated — so it ships UNSET,
        exactly like the two deferred rules. Nothing is invented in the meantime."""
        params = self.env['ir.config_parameter'].sudo()
        params.set_param(MIDWEEK_WEEKDAYS_KEY, False)

        tuesday = (datetime(2036, 7, 15, 18, 0), datetime(2036, 7, 15, 23, 0))
        form = self._form_booking([self.v_men], *tuesday)
        self.assertEqual(form.pricelist_id, self.pl_standard,
                         "with the day range unset, no booking may be treated as midweek")

        params.set_param(MIDWEEK_WEEKDAYS_KEY, '0,1,2,3')      # Monday..Thursday
        form = self._form_booking([self.v_men], *tuesday)
        self.assertEqual(form.pricelist_id, self.pl_midweek)
        self.assertEqual(form.save().amount_total, 12000.0)
        params.set_param(MIDWEEK_WEEKDAYS_KEY, False)

    def test_choosing_a_segment_pricelist_by_hand_applies_its_price(self):
        """Segments are never auto-selected: who counts as أهل البلد is a human judgement."""
        locals_pricelist = self.env.ref('seven_stars_rental.pricelist_segment_locals')
        self.env['product.pricing'].create({
            'product_template_id': self.hall_men.id, 'pricelist_id': locals_pricelist.id,
            'recurrence_id': self.recurrence.id, 'price': 13000.0})
        order = self._booking([self.v_men], datetime(2036, 8, 6, 18, 0),
                              datetime(2036, 8, 6, 23, 0), pricelist=locals_pricelist)
        self.assertEqual(order.amount_total, 13000.0)


@tagged('post_install', '-at_install')
class TestDiscountCeiling(SevenStarsCommon):
    """CON-02. Odoo has no maximum-discount field anywhere — T11 wrote 10% and nothing
    objected.

    Refined in Phase 5 by the PRD §17 matrix, which is stricter than the 5% ceiling alone:
    «منع موظف الحجوزات ومدير الحجوزات من ... منح الخصم» bars the clerk AND the bookings
    manager from discounting at all. The 5% is therefore the ceiling on MANAGEMENT's own
    manual discount, and going above it needs a formally approved price.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.hall = cls._hall("CEIL Hall", 600, 14000.0).product_variant_id
        cls.clerk = cls._user('test_rule_clerk', 'group_ss_clerk')
        cls.manager = cls._user('test_rule_manager', 'group_ss_manager')

    def test_a_clerk_may_not_discount_at_all(self):
        order = self._booking([self.hall], *self.evening(2036, 9, 3), user=self.clerk)
        with self.assertRaises(ValidationError):
            order.with_user(self.clerk).order_line.write({'discount': 1.0})
        self.assertEqual(order.amount_total, 14000.0)

    def test_a_bookings_manager_may_not_discount_either(self):
        """The matrix names the bookings manager alongside the clerk."""
        booking_manager = self._user('test_rule_bm', 'group_ss_booking_manager')
        order = self._booking([self.hall], *self.evening(2036, 10, 1), user=self.clerk)
        with self.assertRaises(ValidationError):
            order.with_user(booking_manager).order_line.write({'discount': 3.0})

    def test_management_may_discount_up_to_five_percent(self):
        order = self._booking([self.hall], *self.evening(2036, 9, 3), user=self.clerk)
        order.with_user(self.manager).order_line.write({'discount': 5.0})
        self.assertEqual(order.amount_total, 13300.0)

    def test_a_clerk_may_not_change_the_price_either(self):
        """«تغيير السعر» — the other half of the same matrix row."""
        order = self._booking([self.hall], *self.evening(2036, 10, 8), user=self.clerk)
        with self.assertRaises(ValidationError):
            order.with_user(self.clerk).order_line.write({'price_unit': 9000.0})
        self.assertEqual(order.order_line.price_unit, 14000.0)

    def test_management_may_not_exceed_the_ceiling_unapproved(self):
        order = self._booking([self.hall], *self.evening(2036, 9, 10), user=self.clerk)
        lines = order.with_user(self.manager).order_line
        with self.assertRaises(ValidationError):
            lines.write({'discount': 10.0})
            lines.flush_recordset()          # @api.constrains fires at flush, not on assignment

    def test_an_approved_price_releases_the_ceiling(self):
        order = self._booking([self.hall], *self.evening(2036, 9, 24), user=self.clerk)
        order.with_user(self.manager).price_approved = True
        order.with_user(self.manager).order_line.write({'discount': 12.0})
        order.order_line.flush_recordset()
        self.assertEqual(order.order_line.discount, 12.0)

    def test_the_ceiling_leaves_ordinary_sales_alone(self):
        """This is a hall-booking rule. A normal quotation is none of its business."""
        product = self._service("CEIL Service", 1000.0)
        # created BY the clerk: sale.sale_order_personal_rule limits a salesman to their own
        # documents, which is half of the PRD §17 matrix for free (spec §11).
        quotation = self.env['sale.order'].with_user(self.clerk).create({
            'partner_id': self.customer.id,
            'order_line': [Command.create({
                'product_id': product.product_variant_id.id, 'product_uom_qty': 1})],
        })
        quotation.order_line.write({'discount': 40.0})
        quotation.order_line.flush_recordset()
        self.assertEqual(quotation.order_line.discount, 40.0)


@tagged('post_install', '-at_install')
class TestCapacityAndHallLock(SevenStarsCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.hall_men = cls._hall("CAP Hall Men", 600, 14000.0)
        cls.hall_women = cls._hall("CAP Hall Women", 550, 14000.0)
        cls.hall_other = cls._hall("CAP Hall Other", 400, 2500.0)
        cls.v_men = cls.hall_men.product_variant_id
        cls.v_women = cls.hall_women.product_variant_id
        cls.v_other = cls.hall_other.product_variant_id

    def _set_tolerance(self, percent):
        self.env['ir.config_parameter'].sudo().set_param(
            GUEST_TOLERANCE_KEY, str(percent) if percent is not None else False)

    # ------------------------------------------------------------------ CON-05
    def test_while_the_tolerance_is_unset_an_over_capacity_booking_is_recorded(self):
        self._set_tolerance(None)
        order = self._booking([self.v_other], *self.evening(2037, 1, 8))
        order.guest_count = 900                      # capacity is 400
        self.assertEqual(order.guest_count, 900,
                         "recorded and visible; the rule is still pending, so nothing blocks")

    def test_once_configured_the_tolerance_blocks_a_genuine_overrun(self):
        self._set_tolerance(10.0)
        try:
            order = self._booking([self.v_other], *self.evening(2037, 1, 15))
            with self.assertRaises(ValidationError):
                order.guest_count = 900
        finally:
            self._set_tolerance(None)

    def test_eight_hundred_guests_fit_the_pair_because_capacities_are_summed(self):
        """600 + 550 = 1150. This is what dissolved PRD §22 item 11 (spec §3.5, T28)."""
        self._set_tolerance(0.0)
        try:
            pair = self._booking([self.v_men, self.v_women], *self.evening(2037, 2, 5))
            pair.guest_count = 800
            self.assertEqual(pair.guest_count, 800)

            single = self._booking([self.v_men], *self.evening(2037, 2, 12))
            with self.assertRaises(ValidationError):
                single.guest_count = 800     # 800 > 600, the men's hall alone
        finally:
            self._set_tolerance(None)

    # ------------------------------------------------------------------ CON-06
    def test_the_hall_cannot_change_after_confirmation(self):
        """«هل يمكن تغيير القاعة بعد التأكيد؟ لا» (spec §23.1)."""
        order = self._booking([self.v_men], *self.evening(2037, 3, 5),
                              required_deposit_amount=3000.0)
        self.env['seven.stars.payment'].create({'order_id': order.id, 'amount': 3000.0})
        order.action_confirm_booking()

        with self.assertRaises(ValidationError):
            order.write({'order_line': [Command.create({
                'product_id': self.v_other.id, 'product_uom_qty': 1, 'is_rental': True})]})

    def test_the_dates_may_still_move_after_confirmation(self):
        """Postponement is exactly that, and CON-01 re-checks the new dates."""
        order = self._booking([self.v_men], *self.evening(2037, 4, 2),
                              required_deposit_amount=3000.0)
        self.env['seven.stars.payment'].create({'order_id': order.id, 'amount': 3000.0})
        order.action_confirm_booking()

        order.write({
            'rental_start_date': datetime(2037, 6, 4, 18, 0),
            'rental_return_date': datetime(2037, 6, 4, 23, 0),
        })
        self.assertEqual(order.rental_start_date, datetime(2037, 6, 4, 18, 0))

    def test_an_unconfirmed_booking_may_still_change_hall(self):
        order = self._booking([self.v_men], *self.evening(2037, 5, 7))
        order.write({'order_line': [Command.create({
            'product_id': self.v_other.id, 'product_uom_qty': 1, 'is_rental': True})]})
        self.assertEqual(len(order.order_line), 2)


@tagged('post_install', '-at_install')
class TestReminders(SevenStarsCommon):
    """Spec §13 — two standard activities. No cron, no automated action, no server action."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.hall = cls._hall("ACT Hall", 600, 14000.0).product_variant_id

    def test_confirming_schedules_the_appendix_and_inspection_reminders(self):
        order = self._booking([self.hall], *self.evening(2037, 7, 9),
                              required_deposit_amount=3000.0)
        self.env['seven.stars.payment'].create({'order_id': order.id, 'amount': 3000.0})
        self.assertFalse(order.activity_ids)

        order.action_confirm_booking()

        summaries = order.activity_ids.mapped('summary')
        self.assertIn("تعبئة الملحق التشغيلي", summaries)
        self.assertIn("جولة المندوب قبل المناسبة", summaries)

        appendix = order.activity_ids.filtered(
            lambda a: a.summary == "تعبئة الملحق التشغيلي")
        self.assertEqual(appendix.date_deadline.isoformat(), '2037-06-25',
                         "two weeks before the event")

    def test_confirming_twice_does_not_duplicate_the_reminders(self):
        order = self._booking([self.hall], *self.evening(2037, 8, 6),
                              required_deposit_amount=3000.0)
        self.env['seven.stars.payment'].create({'order_id': order.id, 'amount': 3000.0})
        order.action_confirm_booking()
        order.action_confirm_booking()
        self.assertEqual(len(order.activity_ids), 2)

    def test_no_cron_or_automated_action_ships_with_this_addon(self):
        module_data = self.env['ir.model.data'].search([
            ('module', '=', 'seven_stars_rental'),
            ('model', 'in', ('ir.cron', 'base.automation', 'ir.actions.server')),
        ])
        self.assertFalse(module_data, f"unexpected automation: {module_data.mapped('name')}")

"""Demo-data integrity (spec §19).

These tests read seven_stars_rental_demo. Install BOTH addons, or every assertion here
runs against an empty database:

    odoo-bin -d ss_test -i seven_stars_rental,seven_stars_rental_demo --test-enable \
        --test-tags /seven_stars_rental
"""
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestDemoData(TransactionCase):

    def _ref(self, xmlid):
        return self.env.ref(f'seven_stars_rental_demo.{xmlid}', raise_if_not_found=False)

    def setUp(self):
        super().setUp()
        # Deliberately a FAILURE, not a skip: a skip would quietly report green on a
        # database where the demo addon never loaded.
        self.assertTrue(
            self._ref('hall_3'),
            "seven_stars_rental_demo loaded no data — install BOTH addons: "
            "-i seven_stars_rental,seven_stars_rental_demo")

    # ------------------------------------------------------------------ halls
    def test_four_halls_exist_as_rental_products(self):
        for n in (1, 2, 3, 4):
            hall = self._ref(f'hall_{n}')
            self.assertTrue(hall, f"hall_{n} missing from demo data")
            self.assertEqual(hall.type, 'service')
            self.assertTrue(hall.rent_ok, f"{hall.name} is not rentable")

    def test_halls_and_services_carry_no_tax(self):
        """A default sales tax would make amount_total disagree with the agreed price, and
        the balance, the receipts and the contracts all derive from it (spec §3.6, T32)."""
        products = self.env['product.template'].search(
            [('default_code', 'like', 'SS-')])
        self.assertTrue(products, "no Seven Stars products found")
        taxed = products.filtered('taxes_id')
        self.assertFalse(
            taxed, f"these ship with a tax and must not: {taxed.mapped('name')}")

    # ------------------------------------------------------------- pricelists
    def test_standalone_hall_prices(self):
        expected = {'hall_1': 2500.0, 'hall_2': 2500.0, 'hall_3': 14000.0, 'hall_4': 14000.0}
        for xmlid, price in expected.items():
            row = self._ref(f'pricing_{xmlid}_standalone')
            self.assertTrue(row, f"standalone pricing row for {xmlid} missing")
            self.assertEqual(row.price, price)
            self.assertFalse(row.pricelist_id, "the standalone row carries no pricelist")

    def test_wedding_pair_pricelist_carries_the_combined_price(self):
        """Halls 3+4 = 14,000 TOTAL. Full price on hall 3, 0.00 on hall 4 (spec §3.5)."""
        self.assertEqual(self._ref('pricing_wedding_pair_hall_3').price, 14000.0)
        self.assertEqual(self._ref('pricing_wedding_pair_hall_4').price, 0.0)
        self.assertEqual(self._ref('pricing_wedding_pair_reduced_hall_3').price, 12000.0)
        self.assertEqual(self._ref('pricing_wedding_pair_reduced_hall_4').price, 0.0)

    def test_zero_price_row_exists_only_on_the_wedding_pair_pricelists(self):
        """T31 guard. On any other pricelist a 0.00 row would make the women's hall free
        whenever it is rented alone."""
        pair_lists = (self.env.ref('seven_stars_rental.pricelist_wedding_pair')
                      | self.env.ref('seven_stars_rental.pricelist_wedding_pair_reduced'))
        halls = self.env['product.template'].search([('default_code', 'like', 'SS-HALL-')])
        zero_rows = self.env['product.pricing'].search([
            ('product_template_id', 'in', halls.ids), ('price', '=', 0.0)])
        stray = zero_rows.filtered(lambda r: r.pricelist_id not in pair_lists)
        self.assertFalse(stray, (
            "a 0.00 hall price outside the wedding-pair pricelists: "
            f"{[(r.pricelist_id.name, r.product_template_id.name) for r in stray]}"))

    def test_every_seasonal_and_segment_pricelist_prices_hall_4(self):
        hall_4 = self._ref('hall_4')
        for xmlid in ('pricelist_winter', 'pricelist_midweek',
                      'pricelist_segment_locals', 'pricelist_segment_family'):
            row = self.env['product.pricing'].search([
                ('pricelist_id', '=', self.env.ref(f'seven_stars_rental.{xmlid}').id),
                ('product_template_id', '=', hall_4.id)], limit=1)
            self.assertTrue(row, f"{xmlid} has no price for hall 4")
            self.assertGreater(row.price, 0.0, f"{xmlid} prices hall 4 at zero")

    def test_pricelists_are_in_shekels(self):
        """The pricelist records belong to the business addon, because the auto-selection
        code references them by XML ID; only the amounts are demo data."""
        ils = self.env.ref('base.ILS')
        self.assertTrue(ils.active, "base.ILS ships inactive and must be activated")
        for xmlid in ('pricelist_standard', 'pricelist_winter', 'pricelist_midweek',
                      'pricelist_wedding_pair', 'pricelist_wedding_pair_reduced',
                      'pricelist_segment_locals', 'pricelist_segment_family'):
            pricelist = self.env.ref(f'seven_stars_rental.{xmlid}')
            self.assertEqual(pricelist.currency_id, ils, xmlid)

    # ------------------------------------------------------- people and roles
    def test_twenty_demo_customers_are_tagged(self):
        tag = self._ref('partner_tag_demo')
        customers = self.env['res.partner'].search([('category_id', '=', tag.id)])
        self.assertEqual(len(customers), 20)

    def test_one_demo_user_per_role(self):
        for xmlid, group in (
            ('user_clerk', 'group_ss_clerk'),
            ('user_accountant', 'group_ss_accountant'),
            ('user_booking_manager', 'group_ss_booking_manager'),
            ('user_manager', 'group_ss_manager'),
        ):
            user = self._ref(xmlid)
            self.assertTrue(user, f"{xmlid} missing")
            self.assertTrue(
                user.has_group(f'seven_stars_rental.{group}'),
                f"{xmlid} is not in {group}")

    def test_no_demo_booking_has_a_duplicated_hall_line(self):
        """Regression guard. These files are not noupdate, so -u re-applies them, and a
        (0, 0, {...}) command CREATES a line every time it runs: one upgrade silently took
        the demo from 220 order lines to 264. Every order_line list now starts with
        (5, 0, 0), and this test is what notices if one ever stops doing so."""
        bookings = self.env['sale.order'].search([('is_rental_order', '=', True)])
        self.assertTrue(bookings, "no demo bookings found")
        for booking in bookings:
            halls = booking.order_line.filtered('is_rental').product_id
            hall_lines = booking.order_line.filtered('is_rental')
            self.assertEqual(
                len(hall_lines), len(halls),
                f"{booking.name} holds the same hall twice: "
                f"{hall_lines.mapped('product_id.name')}")

    def test_the_demo_covers_every_booking_state(self):
        bookings = self.env['sale.order'].search([('is_rental_order', '=', True)])
        states = set(bookings.mapped('booking_state'))
        self.assertEqual(
            states,
            {'draft', 'tentative', 'awaiting', 'confirmed', 'ready', 'postponed',
             'completed', 'cancelled'},
            "the demo is meant to show all eight states on day one")

    def test_a_completed_demo_booking_has_a_zero_balance(self):
        completed = self.env['sale.order'].search([
            ('is_rental_order', '=', True), ('booking_state', '=', 'completed')])
        self.assertTrue(completed)
        for booking in completed:
            self.assertEqual(booking.outstanding_amount, 0.0,
                             f"{booking.name} is completed but still owes money")

    def test_awaiting_demo_bookings_have_no_payments(self):
        """That is precisely what «انتظار العربون» means."""
        awaiting = self.env['sale.order'].search([
            ('is_rental_order', '=', True), ('booking_state', '=', 'awaiting')])
        self.assertTrue(awaiting)
        for booking in awaiting:
            self.assertFalse(booking.payment_ids, f"{booking.name} already has money")
            self.assertGreater(booking.required_deposit_amount, 0.0,
                               f"{booking.name} has no agreed deposit to wait for")

    def test_the_demo_wedding_pair_totals_fourteen_thousand(self):
        """The headline business rule, asserted against the shipped data rather than a
        fixture: halls 3 and 4 on one booking, 14,000 total, never 28,000."""
        hall_3 = self._ref('hall_3_product')
        hall_4 = self._ref('hall_4_product')
        pair = self.env['sale.order'].search([
            ('is_rental_order', '=', True),
            ('pricelist_id', '=', self.env.ref(
                'seven_stars_rental.pricelist_wedding_pair').id)], limit=1)
        self.assertTrue(pair, "no demo booking uses the wedding-pair pricelist")
        self.assertEqual(pair.order_line.filtered('is_rental').product_id, hall_3 | hall_4)
        self.assertEqual(pair.amount_total, 14000.0)
        self.assertEqual(pair.amount_total, pair.amount_untaxed)

    def test_services_and_packages_exist(self):
        services = self.env['product.template'].search([('default_code', 'like', 'SS-SRV-')])
        packages = self.env['product.template'].search([('default_code', 'like', 'SS-PKG-')])
        self.assertEqual(len(services), 11)
        self.assertEqual(len(packages), 3)


@tagged('post_install', '-at_install')
class TestSecurityGroups(TransactionCase):
    """The four groups ship in Phase 0 because Phase 2's CON-03 branches on
    group_ss_manager (spec §11)."""

    def test_the_four_groups_exist_under_one_privilege(self):
        privilege = self.env.ref('seven_stars_rental.res_groups_privilege_seven_stars')
        groups = [self.env.ref(f'seven_stars_rental.{g}') for g in (
            'group_ss_clerk', 'group_ss_accountant',
            'group_ss_booking_manager', 'group_ss_manager')]
        for group in groups:
            self.assertEqual(group.privilege_id, privilege, group.name)

    def test_management_is_above_booking_manager(self):
        """BTN-07 is 'booking manager or above', so the implication has to be real."""
        manager = self.env.ref('seven_stars_rental.group_ss_manager')
        booking_manager = self.env.ref('seven_stars_rental.group_ss_booking_manager')
        clerk = self.env.ref('seven_stars_rental.group_ss_clerk')
        self.assertIn(booking_manager, manager.implied_ids)
        self.assertIn(clerk, booking_manager.implied_ids)

    def test_arabic_is_active_and_right_to_left(self):
        """Reports take their direction from res.lang.direction, not from rtlcss
        (spec §10, T13)."""
        lang = self.env['res.lang'].with_context(active_test=False).search(
            [('code', '=', 'ar_001')], limit=1)
        self.assertTrue(lang.active, "Arabic was not activated by ss_base_data.xml")
        self.assertEqual(lang.direction, 'rtl')

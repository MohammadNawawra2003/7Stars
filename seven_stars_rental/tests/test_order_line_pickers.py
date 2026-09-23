"""Jamal feedback round 1 — everything that has to reach بنود الطلب.

Two of his notes are the same requirement seen twice:

    «عند اضافة فرقة الزفة او اي بند تشغيلي تحت الملحق التشغيلي يجب اضافتها على بند الطلب»
    «اختيار القاعة: عند الاختيار اضافتها على بند الطلب حسب القاعة السعر»

Both are solved the same way — the order line is the single truth and the widget is computed
from it — so both are tested here. The test that matters most is
test_the_hall_picker_prices_the_pair_through_the_pricelist: a picker that seeded price_unit
from product.list_price would bill a wedding 28,000 instead of 14,000.
"""
from datetime import datetime

from odoo import Command
from odoo.exceptions import UserError, ValidationError
from odoo.tests import TransactionCase, tagged

EVENING = (datetime(2032, 6, 10, 18, 0), datetime(2032, 6, 10, 23, 0))


@tagged('post_install', '-at_install')
class TestOrderLinePickers(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.customer = cls.env['res.partner'].create({'name': "عائلة اختبار البنود"})
        cls.recurrence = cls.env.ref('sale_renting.recurrence_daily')

        def hall(name, capacity, price):
            template = cls.env['product.template'].create({
                'name': name, 'type': 'service', 'rent_ok': True, 'sale_ok': True,
                'list_price': price, 'hall_capacity': capacity,
                'prep_time': 4.0, 'cleanup_time': 5.0,
                'taxes_id': [Command.clear()],
            })
            cls.env['product.pricing'].create({
                'product_template_id': template.id,
                'recurrence_id': cls.recurrence.id, 'price': price,
            })
            return template

        cls.hall_3 = hall("PICK Hall 3 Men", 600, 14000.0)
        cls.hall_4 = hall("PICK Hall 4 Women", 550, 14000.0)
        cls.v3 = cls.hall_3.product_variant_id
        cls.v4 = cls.hall_4.product_variant_id

        # The wedding pair: full price on hall 3, 0.00 on hall 4, so the PAIR is 14,000.
        cls.pair_pricelist = cls.env['product.pricelist'].create({
            'name': "PICK wedding pair", 'currency_id': cls.env.ref('base.ILS').id})
        cls.env['product.pricing'].create([
            {'product_template_id': cls.hall_3.id, 'recurrence_id': cls.recurrence.id,
             'price': 14000.0, 'pricelist_id': cls.pair_pricelist.id},
            {'product_template_id': cls.hall_4.id, 'recurrence_id': cls.recurrence.id,
             'price': 0.0, 'pricelist_id': cls.pair_pricelist.id},
        ])

        # Exactly one product may carry an appendix item, and the starter dataset tags its
        # own services. Clear those first so this suite states its own preconditions.
        cls.env['product.template'].search(
            [('ss_appendix_item', '!=', False)]).ss_appendix_item = False
        cls.zaffa = cls.env['product.template'].create({
            'name': "PICK فرقة زفة للعريس", 'type': 'service', 'sale_ok': True,
            'list_price': 1000.0, 'ss_appendix_item': 'zaffa_groom',
            'taxes_id': [Command.clear()],
        })

    def _booking(self, **values):
        vals = {
            'partner_id': self.customer.id,
            'is_rental_order': True,
            'pricelist_id': self.pair_pricelist.id,
            'rental_start_date': EVENING[0],
            'rental_return_date': EVENING[1],
        }
        vals.update(values)
        return self.env['sale.order'].create(vals)

    # ------------------------------------------------------------------ the hall picker
    def test_picking_a_hall_writes_its_rental_line(self):
        booking = self._booking()
        booking.hall_ids = self.v3

        lines = booking.order_line.filtered('is_rental')
        self.assertEqual(lines.product_id, self.v3)
        self.assertTrue(lines.is_rental, "a hall must be booked as a RENTAL line")

    def test_the_hall_picker_prices_the_pair_through_the_pricelist(self):
        """⚠⚠⚠ The 14,000 rule, reached through the picker rather than through raw lines.

        The pair price lives ONLY as a 0.00 product.pricing row on hall 4 in this pricelist.
        A picker that copied product.list_price onto the line would produce 28,000 here and
        would have overcharged every wedding.
        """
        booking = self._booking()
        booking.hall_ids = self.v3 | self.v4

        self.assertEqual(booking.amount_total, 14000.0)
        self.assertEqual(len(booking.order_line.filtered('is_rental')), 2,
                         "both halls stay real lines — conflicts and capacity depend on it")

    def test_unpicking_a_hall_removes_its_line(self):
        booking = self._booking()
        booking.hall_ids = self.v3 | self.v4
        booking.hall_ids = self.v3

        self.assertEqual(booking.order_line.filtered('is_rental').product_id, self.v3)

    def test_the_picker_reads_back_halls_added_as_plain_lines(self):
        """The line is the truth, so a hall added the old way still shows in the picker."""
        booking = self._booking(order_line=[
            Command.create({'product_id': self.v3.id, 'product_uom_qty': 1,
                            'is_rental': True})])

        self.assertEqual(booking.hall_ids, self.v3)

    # ------------------------------------------------------- the operational appendix items
    def test_ticking_an_appendix_item_adds_its_service_line(self):
        booking = self._booking()
        booking.hall_ids = self.v3
        booking.appendix_zaffa_groom = True

        line = booking.order_line.filtered(
            lambda sol: sol.product_id.product_tmpl_id == self.zaffa)
        self.assertTrue(line, "فرقة الزفة must reach بنود الطلب")
        self.assertEqual(booking.amount_total, 15000.0, "14,000 hall + 1,000 زفة")

    def test_unticking_an_appendix_item_removes_its_service_line(self):
        booking = self._booking()
        booking.appendix_zaffa_groom = True
        booking.appendix_zaffa_groom = False

        self.assertFalse(booking.order_line.filtered(
            lambda sol: sol.product_id.product_tmpl_id == self.zaffa))

    def test_an_appendix_item_is_computed_from_the_order_line(self):
        """Ticked because the service is sold, not because a flag was stored separately."""
        booking = self._booking(order_line=[
            Command.create({'product_id': self.zaffa.product_variant_id.id,
                            'product_uom_qty': 1})])

        self.assertTrue(booking.appendix_zaffa_groom)

    def test_an_appendix_item_with_no_service_product_refuses(self):
        """Silently ignoring it would be worse: the box is computed, so it would appear to
        tick and then read back unticked."""
        booking = self._booking()
        self.assertFalse(self.env['product.template'].search(
            [('ss_appendix_item', '=', 'promo_show')]), "precondition: nothing sells it")
        with self.assertRaises(UserError):
            booking.appendix_promo_show = True

    def test_one_appendix_item_cannot_be_sold_by_two_services(self):
        with self.assertRaises(ValidationError):
            self.env['product.template'].create({
                'name': "PICK زفة ثانية", 'type': 'service', 'sale_ok': True,
                'list_price': 900.0, 'ss_appendix_item': 'zaffa_groom',
            })

    # ------------------------------------------------------------------ the rest of round 1
    def test_the_customer_details_the_contract_prints_are_editable_on_the_booking(self):
        booking = self._booking()
        booking.partner_id_number = '412345678'
        booking.partner_whatsapp = '+970 598 111 222'
        booking.partner_responsible_person = "أبو الاختبار"
        booking.partner_street = "الولجة"

        self.assertEqual(self.customer.id_number, '412345678')
        self.assertEqual(self.customer.whatsapp, '+970 598 111 222')
        self.assertEqual(self.customer.responsible_person, "أبو الاختبار")
        self.assertEqual(self.customer.street, "الولجة")

    def test_the_three_contracts_are_offered_as_contract_types(self):
        contracts = self.env['ir.actions.report'].search([('ss_is_contract', '=', True)])

        self.assertEqual(len(contracts), 3)
        for xmlid in ('action_report_hall_contract', 'action_report_henna_contract',
                      'action_report_lunch_contract'):
            self.assertIn(self.env.ref(f'seven_stars_rental.{xmlid}'), contracts)

    def test_the_documents_carry_the_arabic_report_font(self):
        """«تغيير نوع الخط» — the class the Tajawal rule is scoped to must reach the page."""
        report = self.env.ref('seven_stars_rental.action_report_hall_contract')
        booking = self._booking()
        booking.hall_ids = self.v3
        html, _type = report._render_qweb_html(report.report_name, booking.ids)

        self.assertIn('o_ss_report', html.decode() if isinstance(html, bytes) else html)

    def test_more_than_one_contract_type_can_be_selected(self):
        booking = self._booking()
        booking.contract_report_ids = (
            self.env.ref('seven_stars_rental.action_report_hall_contract')
            | self.env.ref('seven_stars_rental.action_report_henna_contract'))

        self.assertEqual(len(booking.contract_report_ids), 2)

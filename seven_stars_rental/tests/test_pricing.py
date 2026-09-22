"""Hall pricing, packages and services (spec §3.3).

Rental lines bypass pricelist ITEMS entirely (product_pricelist.py:76,
sale_order_line.py:107-114), so every hall rate is a product.pricing row keyed on
pricelist_id + product_template_id + recurrence_id. There is no custom pricing engine.

Seasonal, midweek and the discount ceiling are Phase 4.
"""
from odoo import Command
from odoo.tests import tagged

from .common import SevenStarsCommon


@tagged('post_install', '-at_install')
class TestHallPricing(SevenStarsCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.hall_lunch = cls._hall("PRICE Hall Lunch", 400, 2500.0)
        cls.hall_men = cls._hall("PRICE Hall Men", 600, 14000.0)
        cls.photography = cls._service("PRICE Photography", 1500.0)
        cls.flowers = cls._service("PRICE Flowers", 500.0)

    def test_a_hall_prices_from_its_product_pricing_row(self):
        order = self._booking([self.hall_lunch.product_variant_id], *self.evening(2034, 1, 7))
        self.assertEqual(order.order_line.price_unit, 2500.0)
        self.assertEqual(order.amount_total, 2500.0)

    def test_the_booking_total_carries_no_tax(self):
        """outstanding_amount derives from amount_total, and every printed document quotes
        it — a default tax would silently make the balance disagree with the agreed price
        (spec §3.6, runtime T32)."""
        order = self._booking([self.hall_men.product_variant_id], *self.evening(2034, 1, 14))
        self.assertEqual(order.amount_total, order.amount_untaxed)
        self.assertFalse(order.order_line.tax_ids)

    def test_services_add_to_the_hall_and_are_never_multiplied_by_it(self):
        order = self._booking([self.hall_men.product_variant_id], *self.evening(2034, 1, 21))
        self.env['sale.order.line'].create({
            'order_id': order.id,
            'product_id': self.photography.product_variant_id.id,
            'product_uom_qty': 1,
        })
        order.invalidate_recordset()
        self.assertEqual(order.amount_total, 15500.0)

        self.env['sale.order.line'].create({
            'order_id': order.id,
            'product_id': self.flowers.product_variant_id.id,
            'product_uom_qty': 1,
        })
        order.invalidate_recordset()
        self.assertEqual(order.amount_total, 16000.0)

    def test_a_package_keeps_one_agreed_total_and_still_lists_its_components(self):
        """Odoo 19's Combo type is deliberately not used: its semantics are "pick one per
        group", so a nine-service fixed package would need nine groups with split prices that
        mean nothing on a contract — and a rental product cannot be a combo at all. The
        package is one priced line plus note lines, which keeps the total exact."""
        package = self._service("PRICE Wedding Package", 14000.0)
        order = self._booking([], *self.evening(2034, 2, 4))
        self.env['sale.order.line'].create({
            'order_id': order.id,
            'product_id': package.product_variant_id.id,
            'product_uom_qty': 1,
        })
        components = ["تصوير", "إنارة", "ضيافة", "توزيعات", "زفة",
                      "دبكة", "أمن", "تنسيق", "شاشات"]
        for sequence, component in enumerate(components, start=1):
            self.env['sale.order.line'].create({
                'order_id': order.id,
                'display_type': 'line_note',
                'name': f"— {component}",
                'sequence': 100 + sequence,
            })
        order.invalidate_recordset()

        self.assertEqual(order.amount_total, 14000.0,
                         "note lines must not move the total")
        notes = order.order_line.filtered(lambda line: line.display_type == 'line_note')
        self.assertEqual(len(notes), 9, "all nine components are printed on the contract")

    def test_a_whole_period_is_billed_even_when_the_event_is_shorter(self):
        """math.ceil in product_pricing._compute_price (product_pricing.py:101-114): a
        five-hour evening on a daily rule bills a full day. Not a bug — state it (spec C5)."""
        order = self._booking([self.hall_men.product_variant_id], *self.evening(2034, 2, 11))
        self.assertEqual(order.amount_total, 14000.0)


@tagged('post_install', '-at_install')
class TestDiscountField(SevenStarsCommon):
    """The discount ceiling itself is CON-02, Phase 4. What Phase 2 fixes is that the manual
    price guard cannot be relied on: action_update_prices recomputes with
    force_price_recomputation=True (sale_order.py:1375), which ignores technical_price_unit
    and overwrites anything typed by hand (runtime T25)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.hall = cls._hall("DISC Hall", 600, 14000.0).product_variant_id

    def test_a_hand_typed_price_does_not_survive_update_prices(self):
        order = self._booking([self.hall], *self.evening(2034, 3, 4))
        order.order_line.price_unit = 0.0
        self.assertEqual(order.amount_total, 0.0)

        order.action_update_prices()
        self.assertEqual(order.amount_total, 14000.0,
                         "this is why the wedding pair price lives in master data, "
                         "never as a zero typed onto the line")

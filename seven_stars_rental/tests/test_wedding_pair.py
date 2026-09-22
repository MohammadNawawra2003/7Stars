"""The multi-hall wedding — acceptance suite (spec §19.1).

A wedding books hall 3 AND hall 4 for 14,000 TOTAL, never 28,000. The booking carries one
rental line per hall so both halls are real for conflict checking, for the schedule and for
the capacity sum; the single combined price is carried by product.pricing on a wedding
pricelist — full price on hall 3, 0.00 on hall 4.

Each method re-asserts in CI what runtime battery D proved at design time (T24–T33).

Methods 1–3 (occupancy, conflicts, capacity) belong to Phase 1.
Methods 4–8 (pricing, services, double-charging, tax) arrive with Phase 2.
"""
from datetime import datetime

from odoo import Command
from odoo.exceptions import ValidationError
from odoo.tests import TransactionCase, tagged

EVENING = (datetime(2031, 2, 10, 18, 0), datetime(2031, 2, 10, 23, 0))


@tagged('post_install', '-at_install')
class TestWeddingPair(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.customer = cls.env['res.partner'].create({'name': "عائلة اختبار الزفاف"})

        def hall(name, capacity, price):
            return cls.env['product.template'].create({
                'name': name, 'type': 'service', 'rent_ok': True, 'sale_ok': True,
                'list_price': price, 'hall_capacity': capacity,
                'prep_time': 4.0, 'cleanup_time': 5.0,
                'taxes_id': [Command.clear()],
            })

        cls.hall_3 = hall("PAIR Hall 3 Men", 600, 14000.0)
        cls.hall_4 = hall("PAIR Hall 4 Women", 550, 14000.0)
        cls.hall_1 = hall("PAIR Hall 1 Lunch", 400, 2500.0)
        cls.recurrence = cls.env.ref('sale_renting.recurrence_daily')

        # Standalone rates: rented alone, each hall costs its own price.
        for template in (cls.hall_3, cls.hall_4, cls.hall_1):
            cls.env['product.pricing'].create({
                'product_template_id': template.id,
                'recurrence_id': cls.recurrence.id,
                'price': template.list_price,
            })

        cls.pair_pricelist = cls._pair_pricelist("PAIR wedding", 14000.0)
        cls.winter_pair_pricelist = cls._pair_pricelist("PAIR wedding winter", 12000.0)

        cls.v3 = cls.hall_3.product_variant_id
        cls.v4 = cls.hall_4.product_variant_id
        cls.v1 = cls.hall_1.product_variant_id

    @classmethod
    def _pair_pricelist(cls, name, price):
        pricelist = cls.env['product.pricelist'].create({
            'name': name, 'currency_id': cls.env.ref('base.ILS').id})
        cls.env['product.pricing'].create([
            {'product_template_id': cls.hall_3.id, 'recurrence_id': cls.recurrence.id,
             'price': price, 'pricelist_id': pricelist.id},
            {'product_template_id': cls.hall_4.id, 'recurrence_id': cls.recurrence.id,
             'price': 0.0, 'pricelist_id': pricelist.id},
        ])
        return pricelist

    def _booking(self, halls, window=EVENING, pricelist=None, **values):
        vals = {
            'partner_id': self.customer.id,
            'is_rental_order': True,
            'pricelist_id': (pricelist or self.pair_pricelist).id,
            'rental_start_date': window[0],
            'rental_return_date': window[1],
            'order_line': [
                Command.create({'product_id': h.id, 'product_uom_qty': 1, 'is_rental': True})
                for h in halls
            ],
        }
        vals.update(values)
        return self.env['sale.order'].create(vals)

    # ------------------------------------------------------------------- 1 (T33)
    def test_pair_occupies_both_physical_halls(self):
        pair = self._booking([self.v3, self.v4])
        rental_lines = pair.order_line.filtered('is_rental')

        self.assertEqual(len(rental_lines), 2, "one rental line per physical hall")
        self.assertEqual(rental_lines.product_id, self.v3 | self.v4)

        # The schedule gantt reads start_date / return_date on sale.order.line — related,
        # store=False fields, exactly the shape that silently renders an empty row.
        for line in rental_lines:
            self.assertEqual(line.start_date, EVENING[0])
            self.assertEqual(line.return_date, EVENING[1])

        gantt_domain = [('is_rental', '=', True), ('order_id', '=', pair.id)]
        on_gantt = self.env['sale.order.line'].search(gantt_domain)
        self.assertEqual(len(on_gantt), 2)

        grouped = self.env['sale.order.line']._read_group(
            gantt_domain, groupby=['product_id'], aggregates=['__count'])
        self.assertEqual(len(grouped), 2, "the schedule must show two rows, one per hall")

        zero_priced = rental_lines.filtered(lambda line: line.price_unit == 0.0)
        self.assertEqual(len(zero_priced), 1)
        self.assertIn(zero_priced, on_gantt,
                      "pricing the women's hall at zero must not hide it from staff")

    # ------------------------------------------------------------------- 2 (T27)
    def test_conflict_against_either_hall_is_refused(self):
        pair = self._booking([self.v3, self.v4])
        clash = (datetime(2031, 2, 10, 20, 0), datetime(2031, 2, 10, 23, 30))

        for hall in (self.v3, self.v4):
            with self.assertRaises(ValidationError, msg=f"{hall.display_name} was left unprotected") as caught:
                self._booking([hall], window=clash)
            self.assertIn(pair.display_name, str(caught.exception))

        # A hall that is not part of the wedding stays free.
        lunch_hall_booking = self._booking([self.v1], window=clash)
        self.assertTrue(lunch_hall_booking.id)

    # ------------------------------------------------------------------- 3 (T28)
    def test_combined_capacity_is_1150(self):
        pair = self._booking([self.v3, self.v4])
        combined = sum(
            line.product_id.product_tmpl_id.hall_capacity
            for line in pair.order_line.filtered('is_rental'))

        self.assertEqual(combined, 1150, "600 + 550 — the sum is what dissolves PRD §22 item 11")

        guests = 800
        self.assertLessEqual(guests, combined, "800 guests fit the pair")
        self.assertGreater(guests, self.hall_3.hall_capacity,
                           "and would NOT fit the men's hall alone — so summing is the point")

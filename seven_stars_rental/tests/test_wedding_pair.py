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

    # ------------------------------------------------------------- 4 (T26, T32)
    def test_base_pair_total_is_exactly_14000(self):
        pair = self._booking([self.v3, self.v4])
        prices = {line.product_id: line.price_unit for line in pair.order_line}

        self.assertEqual(prices[self.v3], 14000.0, "the men's hall carries the pair price")
        self.assertEqual(prices[self.v4], 0.0, "the women's hall is priced 0.00 by the pricelist")
        self.assertEqual(pair.amount_untaxed, 14000.0)
        self.assertEqual(pair.amount_total, 14000.0)

    # ------------------------------------------------------------------- 5 (T30)
    def test_winter_pair_total_is_exactly_12000(self):
        pair = self._booking([self.v3, self.v4], pricelist=self.winter_pair_pricelist)
        self.assertEqual(pair.amount_total, 12000.0,
                         "a seasonal pair price is a TOTAL, never doubled to 24000")

    # ------------------------------------------------------------------- 6 (T29)
    def test_optional_services_add_on_top(self):
        pair = self._booking([self.v3, self.v4])
        photography = self.env['product.template'].create({
            'name': "PAIR Photography", 'type': 'service', 'sale_ok': True,
            'list_price': 1500.0, 'taxes_id': [Command.clear()]})
        flowers = self.env['product.template'].create({
            'name': "PAIR Flowers", 'type': 'service', 'sale_ok': True,
            'list_price': 500.0, 'taxes_id': [Command.clear()]})

        self.env['sale.order.line'].create({
            'order_id': pair.id, 'product_id': photography.product_variant_id.id,
            'product_uom_qty': 1})
        pair.invalidate_recordset()
        self.assertEqual(pair.amount_total, 15500.0)

        self.env['sale.order.line'].create({
            'order_id': pair.id, 'product_id': flowers.product_variant_id.id,
            'product_uom_qty': 1})
        pair.invalidate_recordset()
        self.assertEqual(pair.amount_total, 16000.0,
                         "services add; they are never multiplied by the hall price")

    # --------------------------------------------------------- 7 (T24, T25, T26)
    def test_no_double_charging(self):
        """THIS METHOD MUST NEVER BE DELETED (spec §19.1).

        It is the only automated guard against the specific regression that brings 28,000
        back: someone "simplifying" the pair pricelist away and zeroing the hall 4 line by
        hand instead. A hand-typed zero does not survive Update Prices, because
        _recompute_prices runs with force_price_recomputation=True (sale_order.py:1375),
        which ignores the technical_price_unit manual-price guard.
        """
        pair = self._booking([self.v3, self.v4])

        # (a) the pair is 14000, not 28000
        self.assertEqual(pair.amount_total, 14000.0)
        self.assertNotEqual(pair.amount_total, 28000.0)

        # (b) it survives a forced recomputation
        pair.action_update_prices()
        self.assertEqual(pair.amount_total, 14000.0,
                         "Update Prices must reproduce the pair price, not double it")

        # (c) and it survives the dates moving
        pair.write({
            'rental_start_date': datetime(2031, 2, 17, 18, 0),
            'rental_return_date': datetime(2031, 2, 17, 23, 0),
        })
        pair.invalidate_recordset()
        self.assertEqual(pair.amount_total, 14000.0)

    # ------------------------------------------------------------------- 8 (T32)
    def test_booking_total_carries_no_tax(self):
        """Guard. A default sales tax silently breaks methods 4-6 and every printed total,
        because outstanding_amount and all eight documents derive from amount_total."""
        pair = self._booking([self.v3, self.v4])
        self.assertEqual(pair.amount_total, pair.amount_untaxed)
        self.assertFalse(pair.order_line.tax_ids)

        service = self.env['product.template'].create({
            'name': "PAIR Taxfree Service", 'type': 'service', 'sale_ok': True,
            'list_price': 1000.0, 'taxes_id': [Command.clear()]})
        self.env['sale.order.line'].create({
            'order_id': pair.id, 'product_id': service.product_variant_id.id,
            'product_uom_qty': 1})
        pair.invalidate_recordset()
        self.assertEqual(pair.amount_total, pair.amount_untaxed)
        self.assertEqual(pair.amount_total, 15000.0)

    # ------------------------------------------------------- the caveat, recorded
    def test_hall_4_alone_prices_itself_on_the_standard_pricelist(self):
        """T31. The 0.00 row belongs to the wedding-pair pricelists ONLY. Booking the
        women's hall on its own uses an ordinary pricelist, where it costs its own price.
        Open client question: is hall 4 ever rented alone, and at what price (spec §3.5)."""
        standard = self.env['product.pricelist'].create({
            'name': "PAIR standard", 'currency_id': self.env.ref('base.ILS').id})
        alone = self._booking([self.v4], window=(datetime(2031, 6, 18, 18, 0),
                                                 datetime(2031, 6, 18, 23, 0)),
                              pricelist=standard)
        self.assertEqual(alone.amount_total, 14000.0)

        on_pair_pricelist = self._booking([self.v4], window=(datetime(2031, 7, 16, 18, 0),
                                                             datetime(2031, 7, 16, 23, 0)))
        self.assertEqual(on_pair_pricelist.amount_total, 0.0,
                         "known and bounded: the wedding pricelist is for the PAIR")

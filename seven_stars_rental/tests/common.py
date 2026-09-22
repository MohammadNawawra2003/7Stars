"""Shared fixtures. Built here rather than taken from seven_stars_rental_demo so the tests
state their own preconditions and cannot be broken by editing demo data.
"""
from datetime import datetime

from odoo import Command
from odoo.tests import TransactionCase


class SevenStarsCommon(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.ils = cls.env.ref('base.ILS')
        cls.ils.active = True
        cls.recurrence = cls.env.ref('sale_renting.recurrence_daily')
        cls.customer = cls.env['res.partner'].create({
            'name': "عائلة اختبار", 'id_number': '900000000',
            'whatsapp': '+970 599 000 000', 'responsible_person': "أبو اختبار",
        })

    @classmethod
    def _hall(cls, name, capacity, price):
        template = cls.env['product.template'].create({
            'name': name, 'type': 'service', 'rent_ok': True, 'sale_ok': True,
            'list_price': price, 'hall_capacity': capacity,
            'prep_time': 4.0, 'cleanup_time': 5.0,
            'taxes_id': [Command.clear()],
        })
        cls.env['product.pricing'].create({
            'product_template_id': template.id,
            'recurrence_id': cls.recurrence.id,
            'price': price,
        })
        return template

    @classmethod
    def _service(cls, name, price):
        return cls.env['product.template'].create({
            'name': name, 'type': 'service', 'sale_ok': True, 'list_price': price,
            'taxes_id': [Command.clear()],
        })

    @classmethod
    def _user(cls, login, *groups):
        """A real, non-superuser session. uid 1 bypasses every ACL (models.py:3377), so a
        permission verified as admin is not verified at all."""
        return cls.env['res.users'].create({
            'name': login, 'login': login,
            'group_ids': [Command.set([
                cls.env.ref('base.group_user').id,
                *(cls.env.ref(f'seven_stars_rental.{g}').id for g in groups),
            ])],
        })

    def _booking(self, halls, start, end, user=None, pricelist=None, **values):
        vals = {
            'partner_id': self.customer.id,
            'is_rental_order': True,
            'rental_start_date': start,
            'rental_return_date': end,
            'order_line': [
                Command.create({'product_id': h.id, 'product_uom_qty': 1, 'is_rental': True})
                for h in halls
            ],
        }
        if pricelist:
            vals['pricelist_id'] = pricelist.id
        vals.update(values)
        model = self.env['sale.order']
        if user:
            model = model.with_user(user)
        return model.create(vals)

    @staticmethod
    def evening(year, month, day):
        return (datetime(year, month, day, 18, 0), datetime(year, month, day, 23, 0))

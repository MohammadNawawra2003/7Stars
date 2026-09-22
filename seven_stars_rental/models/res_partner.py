from odoo import fields, models


class ResPartner(models.Model):
    """The three customer details the contracts need and the standard contact does not carry.

    `id_number` is deliberately not `vat`, which is the tax identification number.
    `whatsapp` is a field of its own because res.partner.mobile does not exist in Odoo 19 —
    verified absent from base/models/res_partner.py, where only `phone` survives (spec §7).
    """
    _inherit = 'res.partner'

    id_number = fields.Char(string="رقم الهوية")
    whatsapp = fields.Char(string="رقم واتساب")
    responsible_person = fields.Char(string="الشخص المسؤول عن المناسبة")

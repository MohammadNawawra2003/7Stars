from odoo import fields, models


class ProductTemplate(models.Model):
    """Halls are rental service products, one product per PHYSICAL hall (spec §1.4).

    Nothing standard covers these three. `preparation_time` is defined in
    sale_stock_renting/models/product_template.py:12, a module that auto-installs only with
    sale_stock; skipping Inventory means no preparation field exists at all, and Odoo has no
    cleanup/after-event equivalent anywhere. So both buffers are written here (spec C3).
    """
    _inherit = 'product.template'

    hall_capacity = fields.Integer(
        string="سعة القاعة (عدد المعازيم)",
        help="Maximum guests. A booking that holds several halls is checked against the SUM "
             "of their capacities — halls 3+4 together seat 1150 (spec §3.5, runtime T28).")
    prep_time = fields.Float(
        string="وقت التجهيز قبل المناسبة (ساعات)", default=4.0,
        help="Hours reserved before the event. Part of the availability envelope, so another "
             "booking cannot start inside it.")
    cleanup_time = fields.Float(
        string="وقت التنظيف بعد المناسبة (ساعات)", default=5.0,
        help="Hours reserved after the event. Part of the availability envelope.")

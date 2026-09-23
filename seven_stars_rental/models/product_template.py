from odoo import api, fields, models
from odoo.exceptions import ValidationError

# The four chargeable items of the operational appendix (§10). Ticking one on a booking must
# put its service on the order lines, so each needs to know which product it sells — and the
# services live in the demo/starter dataset, not in this addon, so the link cannot be an xml
# ref. It is data on the product instead, which also lets Seven Stars repoint an appendix item
# at a different service without a code change.
APPENDIX_ITEMS = [
    ('promo_show', "عرض برومو"),
    ('dabke_women', "فرقة دبكة (النساء)"),
    ('zaffa_groom', "فرقة زفة للعريس"),
    ('zaffa_on_screens', "عرض الزفة على الشاشات"),
]


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
    ss_appendix_item = fields.Selection(
        APPENDIX_ITEMS, string="بند الملحق التشغيلي",
        help="Ticking this item on a booking's operational appendix adds THIS service to the "
             "order lines, priced by the booking's pricelist. Leave empty for a service that "
             "is not one of the appendix items. At most one product per item.")

    @api.constrains('ss_appendix_item')
    def _check_ss_appendix_item_is_unique(self):
        """One appendix item sells one service, or the booking would pick arbitrarily.

        ⚠ env.su is True inside every @api.constrains in Odoo 19, so nothing here may depend
        on it. Nothing does — this is a plain uniqueness rule that binds everyone.
        """
        for template in self.filtered('ss_appendix_item'):
            clash = self.search([
                ('ss_appendix_item', '=', template.ss_appendix_item),
                ('id', '!=', template.id),
            ], limit=1)
            if clash:
                raise ValidationError(template.env._(
                    "البند «%(item)s» مرتبط بالخدمة «%(other)s» بالفعل.\n"
                    "كل بند من الملحق التشغيلي يُباع بخدمة واحدة فقط.\n\n"
                    "Appendix item already sold by another service; exactly one product may "
                    "carry each item.",
                    item=dict(APPENDIX_ITEMS)[template.ss_appendix_item], other=clash.name))

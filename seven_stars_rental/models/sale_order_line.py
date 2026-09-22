"""CON-02 — the manual discount ceiling (spec §12).

Odoo has no maximum-discount field anywhere: runtime T11 wrote discount = 10.0 on a line and
nothing objected. The ceiling is therefore entirely ours.
"""
from odoo import api, models
from odoo.exceptions import ValidationError

# «سقف خصم يدوي لا يتجاوز 5%» — PRD §8, restated in the requirements form (spec Appendix A
# item 14). Whether the 5% is binding is PRD §22 item 8, still open; management can already
# exceed it, so answering that question changes a number here and nothing else.
MAX_DISCOUNT_PERCENT = 5.0


class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'

    @api.constrains('discount')
    def _check_ss_discount_ceiling(self):
        # ⚠ Odoo 19 runs @api.constrains with su=True and the REAL uid preserved (measured:
        # uid 5 su True for a clerk). env.su is therefore useless here as an "is this an
        # administrator?" test — checking it would silently disable this rule for everybody.
        # env.user is the honest question, and reading a groups= field is safe because the
        # constraint already runs elevated.
        for line in self:
            if not line.order_id.is_rental_order or line.discount <= MAX_DISCOUNT_PERCENT:
                continue
            # Working assumption for PRD §22 item 7: management only. The form's own
            # permissions section and PRD §17 agree against the form's discount section
            # (spec §23.2 X3). Final sign-off is still pending the client.
            if line.env.user.has_group('seven_stars_rental.group_ss_manager'):
                continue
            if line.order_id.price_approved:
                continue
            raise ValidationError(line.env._(
                "الخصم %(discount).2f%% يتجاوز السقف المسموح (%(ceiling).2f%%).\n"
                "يلزم اعتماد الإدارة للسعر قبل تجاوز السقف.\n\n"
                "A %(discount).2f%% discount exceeds the %(ceiling).2f%% ceiling. Management "
                "must approve the price before a larger discount can be given (PRD §8/§17).",
                discount=line.discount, ceiling=MAX_DISCOUNT_PERCENT))

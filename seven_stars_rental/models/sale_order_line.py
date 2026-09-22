"""CON-02 — the manual discount ceiling (spec §12).

Odoo has no maximum-discount field anywhere: runtime T11 wrote discount = 10.0 on a line and
nothing objected. The ceiling is therefore entirely ours.
"""
from odoo import api, fields, models
from odoo.exceptions import ValidationError

# «سقف خصم يدوي لا يتجاوز 5%» — PRD §8, restated in the requirements form (spec Appendix A
# item 14). Whether the 5% is binding is PRD §22 item 8, still open; management can already
# exceed it, so answering that question changes a number here and nothing else.
MAX_DISCOUNT_PERCENT = 5.0


class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'

    def _ss_is_management(self):
        return self.env.user.has_group('seven_stars_rental.group_ss_manager')

    def write(self, vals):
        """PRD §17 — «منع موظف الحجوزات ومدير الحجوزات من تغيير السعر ومنح الخصم».

        Both the booking clerk AND the bookings manager are barred from changing a price or
        granting a discount; only management may. A Python groups= cannot express this,
        because it is read-and-write in one: a clerk who could not READ price_unit could not
        quote a hall at all. So the restriction is on the WRITE, and the view merely makes it
        visible by showing the fields readonly.

        This guards the model, not the screen. The view's readonly attribute is a courtesy;
        this method is what actually holds when the field is written over RPC.
        """
        guarded = {'price_unit', 'discount'} & set(vals)
        if guarded and not self._ss_is_management():
            # hall bookings only: this is a Seven Stars rule, not a rule about
            # every rental order that might ever exist in the database.
            rental_lines = self.filtered(lambda line: line.order_id._ss_is_hall_booking())
            if rental_lines:
                raise ValidationError(self.env._(
                    "تغيير السعر أو منح الخصم من صلاحية الإدارة فقط (القسم 17).\n"
                    "الحقول المحمية: %(fields)s\n\n"
                    "Changing a price or granting a discount is reserved to management "
                    "(PRD §17). Protected fields: %(fields)s",
                    fields=", ".join(sorted(guarded))))
        return super().write(vals)

    @api.constrains('discount')
    def _check_ss_discount_ceiling(self):
        # ⚠ Odoo 19 runs @api.constrains with su=True and the REAL uid preserved (measured:
        # uid 5 su True for a clerk). env.su is therefore useless here as an "is this an
        # administrator?" test — checking it would silently disable this rule for everybody.
        # env.user is the honest question, and reading a groups= field is safe because the
        # constraint already runs elevated.
        for line in self:
            if not line.order_id._ss_is_hall_booking() or line.discount <= MAX_DISCOUNT_PERCENT:
                continue
            # Only management can reach a non-zero discount at all (see write() above), so
            # this ceiling is the limit on MANAGEMENT's own manual discount: 5% freely, more
            # only once the price has been formally approved.
            if line.order_id.price_approved:
                continue
            raise ValidationError(line.env._(
                "الخصم %(discount).2f%% يتجاوز السقف المسموح (%(ceiling).2f%%).\n"
                "يلزم اعتماد الإدارة للسعر قبل تجاوز السقف.\n\n"
                "A %(discount).2f%% discount exceeds the %(ceiling).2f%% ceiling. Management "
                "must approve the price before a larger discount can be given (PRD §8/§17).",
                discount=line.discount, ceiling=MAX_DISCOUNT_PERCENT))

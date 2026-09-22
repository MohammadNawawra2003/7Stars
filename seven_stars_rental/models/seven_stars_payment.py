"""The one custom model in this project (spec §6).

PRD §13 requires a payment statement (RPT-06) and a per-payment receipt (RPT-07). Both need
one row per payment carrying date, amount, method and reference — a genuine one-to-many
history, which is the single case where a related model is the right answer.

Rejected on evidence, not preference: account.payment (excluded by the accounting decision,
spec §1.2), chatter messages (cannot be summed, filtered or printed per payment), order
lines with negative amounts (corrupt amount_total and every standard total), fixed
payment_1_* fields (cap the number of payments and cannot be queried). No standard
non-accounting ledger model exists outside `account`.

This model is the ONLY source of truth for money actually received (spec §6.1). Nothing on
sale.order stores received money independently, so the two can never drift apart.
"""
from odoo import api, fields, models
from odoo.exceptions import ValidationError


class SevenStarsPayment(models.Model):
    _name = 'seven.stars.payment'
    _description = "Booking Payment"
    _order = 'date desc, id desc'

    order_id = fields.Many2one(
        'sale.order', string="الحجز", required=True, ondelete='cascade', index=True)
    date = fields.Date(string="تاريخ الدفعة", required=True, default=fields.Date.context_today)
    amount = fields.Monetary(string="المبلغ", required=True)
    currency_id = fields.Many2one(related='order_id.currency_id', depends=['order_id'])
    method = fields.Selection(
        [('cash', "نقداً"), ('transfer', "حوالة بنكية")],
        string="طريقة الدفع", required=True, default='cash')
    reference = fields.Char(string="المرجع / رقم الإيصال")

    @api.constrains('amount')
    def _check_ss_refund_is_management_only(self):
        """PRD §17 — «استرجاع الأموال» is management's.

        A refund is an ordinary payment row with a negative amount, which keeps one ledger
        instead of two. ⚠ env.su is True inside every @api.constrains in Odoo 19 and cannot
        be used to spot an administrator; env.user is the real caller.
        """
        for payment in self:
            if payment.amount >= 0:
                continue
            if payment.env.user.has_group('seven_stars_rental.group_ss_manager'):
                continue
            raise ValidationError(payment.env._(
                "استرجاع الأموال من صلاحية الإدارة فقط (القسم 17).\n\n"
                "Recording a refund (a negative payment) is reserved to management "
                "(PRD §17)."))

    def _compute_display_name(self):
        for payment in self:
            payment.display_name = f"{payment.order_id.name or ''} — {payment.amount:,.2f}"

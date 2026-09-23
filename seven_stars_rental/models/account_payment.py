"""Money received, as real accounting.

Jamal, 2026-09-23: «بعد تغيير الحالة الى مؤكد — فوترة اوتوماتيكية على المحاسبة، والدفعات التي
تم انشاؤها يتم تسويتها من الفاتورة المصدرة على العقد». This replaces the project's original
no-accounting position (PRD §21), and with it the custom seven.stars.payment ledger — two
records of the same money would inevitably drift, so there is exactly one and it is Odoo's.

Odoo links a payment to an INVOICE, and a booking takes its deposit long before it is
invoiced, so the payment needs to know its booking on its own. That is the only field here.
"""
from odoo import api, fields, models
from odoo.exceptions import ValidationError

# What a booking shows about its money, recomputed whenever a payment changes.
SS_ORDER_MONEY_FIELDS = ['payment_ids', 'collected_amount', 'outstanding_amount']


class AccountPayment(models.Model):
    _inherit = 'account.payment'

    ss_order_id = fields.Many2one(
        'sale.order', string="الحجز", index=True, copy=False,
        # NOT cascade: deleting a booking must never delete a posted accounting document.
        ondelete='set null',
        help="The booking this payment was received for. Set from the moment the deposit is "
             "taken, which is before any invoice exists.")

    # sale.order.payment_ids cannot be a relation — it sits on every order in the database
    # and reading it as a salesperson would demand accounting rights. So it is computed, and
    # nothing invalidates it automatically. These three overrides are that invalidation.
    @api.model_create_multi
    def create(self, vals_list):
        payments = super().create(vals_list)
        payments.ss_order_id.invalidate_recordset(SS_ORDER_MONEY_FIELDS)
        return payments

    def write(self, vals):
        orders = self.ss_order_id
        result = super().write(vals)
        (orders | self.ss_order_id).invalidate_recordset(SS_ORDER_MONEY_FIELDS)
        return result

    def unlink(self):
        orders = self.ss_order_id
        result = super().unlink()
        orders.invalidate_recordset(SS_ORDER_MONEY_FIELDS)
        return result

    def _ss_check_refund_is_management_only(self, user):
        """PRD §17 — «استرجاع الأموال» is management's.

        A refund is an outbound customer payment. The acting user is passed in rather than
        read off the environment: this runs on a sudo record (the clerk has no accounting
        access), and both env.su and an @api.constrains would report the superuser here —
        the trap that once silently disabled the discount ceiling for everyone.
        """
        for payment in self:
            if payment.payment_type != 'outbound' or not payment.ss_order_id:
                continue
            if user.has_group('seven_stars_rental.group_ss_manager'):
                continue
            raise ValidationError(payment.env._(
                "استرجاع الأموال من صلاحية الإدارة فقط (القسم 17).\n\n"
                "Recording a refund is reserved to management (PRD §17)."))

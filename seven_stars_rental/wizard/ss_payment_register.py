"""Taking money on a booking, without handing the clerk the accounting app.

Odoo's own account.payment.register starts from an invoice, and a hall booking takes its
deposit long before it is invoiced — so that wizard cannot serve the deposit, which is the
single most common payment Seven Stars records.

The clerk needs no accounting group: this wizard checks the Seven Stars permission itself and
then writes the payment sudo. Granting group_ss_clerk direct access to account.payment would
have meant account.move and account.move.line too, which is the accounting app in all but
name.
"""
from odoo import api, fields, models
from odoo.exceptions import UserError


class SsPaymentRegister(models.TransientModel):
    _name = 'ss.payment.register'
    _description = "تسجيل دفعة على الحجز"

    order_id = fields.Many2one('sale.order', string="الحجز", required=True, readonly=True)
    currency_id = fields.Many2one(related='order_id.currency_id')
    outstanding_amount = fields.Monetary(
        related='order_id.outstanding_amount', string="المبلغ المتبقي")
    date = fields.Date(
        string="تاريخ الدفعة", required=True, default=fields.Date.context_today)
    amount = fields.Monetary(string="المبلغ", required=True)
    journal_id = fields.Many2one(
        'account.journal', string="طريقة الدفع", required=True,
        domain="[('type', 'in', ('cash', 'bank'))]")
    memo = fields.Char(string="المرجع / رقم الإيصال")
    is_refund = fields.Boolean(
        string="استرجاع أموال",
        help="استرجاع مبلغ للعميل بدلاً من قبضه. من صلاحية الإدارة فقط (القسم 17).")

    @api.model
    def default_get(self, fields_list):
        values = super().default_get(fields_list)
        order = self.env['sale.order'].browse(self.env.context.get('active_id'))
        if order.exists():
            values.setdefault('order_id', order.id)
            if 'amount' in fields_list:
                values.setdefault('amount', max(order.outstanding_amount, 0.0))
            if 'journal_id' in fields_list:
                journal = self.env['account.journal'].search([
                    ('type', 'in', ('cash', 'bank')),
                    ('company_id', '=', order.company_id.id),
                ], limit=1, order='type desc, sequence')
                if journal:
                    values.setdefault('journal_id', journal.id)
        return values

    def action_register(self):
        self.ensure_one()
        if self.amount <= 0:
            raise UserError(self.env._("المبلغ يجب أن يكون أكبر من صفر."))
        # Who may record a payment at all is settled by ir.model.access on this wizard —
        # clerk, accountant and management have it and nobody else does. Repeating it here
        # as a has_group check would only add a second place to keep in step.
        payment = self.env['account.payment'].sudo().create({
            'ss_order_id': self.order_id.id,
            'partner_id': self.order_id.partner_id.id,
            'partner_type': 'customer',
            'payment_type': 'outbound' if self.is_refund else 'inbound',
            'amount': self.amount,
            # The booking's currency, never the company default: a hall is paid in shekels
            # and a payment left on a USD company reads as «$ 5,000.00» on the booking.
            'currency_id': self.order_id.currency_id.id,
            'date': self.date,
            'journal_id': self.journal_id.id,
            'memo': self.memo,
        })
        # Checked against the REAL user, never the sudo env, which would wave a refund through.
        payment._ss_check_refund_is_management_only(self.env.user)
        payment.action_post()
        # Settles it against the contract's invoice when one already exists; a deposit taken
        # before confirmation simply waits there and is settled by _ss_invoice_booking.
        self.order_id._ss_reconcile_payments()
        return {'type': 'ir.actions.act_window_close'}

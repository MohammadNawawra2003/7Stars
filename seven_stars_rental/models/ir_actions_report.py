from odoo import fields, models


class IrActionsReport(models.Model):
    """Marks a report as one of the bookable contract types (PRD §10).

    A booking can need more than one — a wedding with a henna night and a lunch — so the
    contract type is a Many2many on sale.order rather than a second selection beside
    event_type. The flag lives on the report so that adding a fourth contract is a new report
    record and nothing else; no list of names to keep in step.
    """
    _inherit = 'ir.actions.report'

    ss_is_contract = fields.Boolean(
        string="عقد من عقود سفن ستارز",
        help="Offered in «نوع العقد» on a booking, and printed by «طباعة العقود».")

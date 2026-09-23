"""The contract types, and the wording Seven Stars approves for each.

⚠⚠⚠ WHY THIS IS A MODEL AND NOT TWO FIELDS ON ir.actions.report.

The first version of Jamal's feedback #6 put `ss_is_contract` and `ss_contract_body` straight
onto `ir.actions.report`. It worked locally and it broke Odoo.sh staging the moment anyone
opened Apps or pressed Upgrade:

    psycopg2.errors.UndefinedColumn: column ir_act_report_xml.ss_is_contract does not exist
      … ir_module.py:637  self.env.cr.commit()
      … ir_module.py:246  module.reports_by_module = … browse('ir.actions.report')

`ir.module.module._get_views` computes `reports_by_module` by reading `ir.actions.report`, and
the ORM fetches every stored column of that model in one query. Between "new code loaded" and
"module actually upgraded" the registry knows the field but the column does not exist yet —
and `_button_immediate_function` commits, and therefore flushes, BEFORE running the upgrade.
So a new stored field on `ir.actions.report` makes upgrading from the web UI impossible, which
is the one route the client has.

Keeping the wording on its own model avoids that class of failure entirely, and gives Seven
Stars a plain menu to edit their contracts instead of Settings ▸ Technical ▸ Reports.
"""
from odoo import api, fields, models


class SevenStarsContractType(models.Model):
    _name = 'seven.stars.contract.type'
    _description = "نوع العقد"
    _order = 'sequence, id'

    name = fields.Char(string="نوع العقد", required=True, translate=False)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    report_id = fields.Many2one(
        'ir.actions.report', string="المستند", required=True, ondelete='cascade',
        domain=[('model', '=', 'sale.order')],
        help="The printed document this contract type produces.")
    body = fields.Html(
        string="نص العقد", sanitize=False, translate=False,
        help="نص الاتفاقية كما تعتمده إدارة قاعات سفن ستارز: التمهيد والبنود المرقّمة. "
             "يُطبع بين «أولاً: مقدمة الاتفاقية» و«رابعاً: التوقيعات».\n\n"
             "The agreement's own wording, per contract type — which is what makes the three "
             "contracts genuinely different documents rather than one template with a "
             "different heading. EDITABLE DATA on purpose: legal text must never need a code "
             "change, and none of it may be drafted by us.")

    @api.model
    def _ss_for_report(self, report_xmlid):
        """The contract type a template is printing, or an empty recordset."""
        report = self.env.ref(report_xmlid, raise_if_not_found=False)
        if not report:
            return self.browse()
        return self.search([('report_id', '=', report.id)], limit=1)

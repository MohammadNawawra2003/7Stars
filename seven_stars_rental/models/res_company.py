"""Making sure the company can actually do accounting.

Since 2026-09-23 a booking posts an invoice and its payments, so the company needs a chart
of accounts. On an existing database — every Odoo.sh build of this project — there already
is one and nothing here runs.

A BRAND NEW database is the awkward case. Odoo applies the chart template from
`ir.module.module._register_hook` (account/models/ir_module.py:102), which runs after every
module's data has loaded, so during a single-pass `-i` install there is no chart, no journal
and no receivable account yet. Measured on a clean database: zero journals at the moment the
starter dataset loads.

This is therefore NEVER automatic. It is called explicitly by the starter dataset, which is
the one thing that needs a working company the moment it is installed.
"""
import logging

from odoo import api, models

_logger = logging.getLogger(__name__)


class ResCompany(models.Model):
    _inherit = 'res.company'

    @api.model
    def _ss_ensure_accounting(self):
        """Load a chart of accounts for the current company if it has none.

        Deliberately a no-op when a chart already exists: re-running a chart template over a
        live company's accounts is not something a dataset may ever do.
        """
        company = self.env.company
        if company.chart_template:
            return
        chart_template = self.env['account.chart.template']
        code = chart_template._guess_chart_template(company.country_id)
        _logger.info("Seven Stars: no chart of accounts on %s, loading %s", company.name, code)
        chart_template.try_loading(code, company, install_demo=False)

"""The two rules the client has not decided yet (spec §8).

UNSET is not zero. `ir.config_parameter.get_param(key, default=None)` returns a string or
None (base/models/ir_config_parameter.py:60-67), so an absent key is genuinely
distinguishable from a deliberate '0'. While a rule is unset it enforces nothing and
invents nothing; once configured, the same code path reads a value. Runtime T17/T18/T19/T20.
"""
from odoo import api, fields, models

SAME_DAY_GAP_KEY = 'seven_stars_rental.same_day_gap_hours'
GUEST_TOLERANCE_KEY = 'seven_stars_rental.guest_tolerance_percent'

MODE_SELECTION = [
    ('pending', "بانتظار قرار العميل — Pending client decision"),
    ('configured', "مُفعّل — Configured"),
]


def get_optional_float(env, key):
    """The configured value, or None when the rule has never been decided.

    Never returns 0.0 for an absent key — a phantom zero would silently turn
    "not decided" into "decided to be zero", which is a different business rule.
    """
    raw = env['ir.config_parameter'].sudo().get_param(key, default=None)
    if raw is None or raw is False or raw == '':
        return None
    return float(raw)


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    same_day_gap_mode = fields.Selection(
        MODE_SELECTION, string="الفاصل بين حجزين في اليوم نفسه", default='pending',
        help="PRD §22 item 6. While pending, true overlaps are still blocked but no extra "
             "separation is invented between two bookings that do not overlap.")
    same_day_gap_hours = fields.Float(string="عدد ساعات الفاصل")
    guest_tolerance_mode = fields.Selection(
        MODE_SELECTION, string="نسبة التجاوز المسموحة لعدد المعازيم", default='pending',
        help="PRD §22 item 11. While pending the guest count is recorded and shown, and no "
             "booking is blocked or warned about.")
    guest_tolerance_percent = fields.Float(string="نسبة التجاوز %")

    @api.model
    def get_values(self):
        res = super().get_values()
        gap = get_optional_float(self.env, SAME_DAY_GAP_KEY)
        tolerance = get_optional_float(self.env, GUEST_TOLERANCE_KEY)
        res.update(
            same_day_gap_mode='configured' if gap is not None else 'pending',
            same_day_gap_hours=gap or 0.0,
            guest_tolerance_mode='configured' if tolerance is not None else 'pending',
            guest_tolerance_percent=tolerance or 0.0,
        )
        return res

    def set_values(self):
        super().set_values()
        params = self.env['ir.config_parameter'].sudo()
        for mode, value, key in (
            (self.same_day_gap_mode, self.same_day_gap_hours, SAME_DAY_GAP_KEY),
            (self.guest_tolerance_mode, self.guest_tolerance_percent, GUEST_TOLERANCE_KEY),
        ):
            # set_param(key, False) deletes the row (ir_config_parameter.py:set_param), which
            # is what returns the rule to UNSET rather than storing a zero.
            params.set_param(key, str(value) if mode == 'configured' else False)

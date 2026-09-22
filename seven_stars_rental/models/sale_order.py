"""The booking. A standard sale.order in rental mode — no new central model (spec §1.3).

CON-01 lives here. Odoo 19 Rental never blocks or warns on an overlapping booking: there is
no action_confirm, no _action_confirm and no write override in sale_renting, and its only
date constraint is a single-row SQL CHECK (sale_renting/models/sale_order.py:24) that is
structurally unable to compare two rows. The gantt's consolidation_max is 1e9. Availability
is therefore entirely ours (spec §3.1).
"""
from datetime import timedelta

from odoo import api, fields, models
from odoo.exceptions import ValidationError

from .res_config_settings import SAME_DAY_GAP_KEY, get_optional_float

EVENT_TYPES = [
    ('wedding', "زفاف"),
    ('lunch', "غداء"),
    ('henna', "حنة"),
    ('engagement', "خطوبة"),
    ('tawjihi', "حفل توجيهي"),
    ('aqiqa', "عقيقة"),
    ('students', "حفل طلبة"),
]

# The eight PRD states. Independent of the standard `state` field, which has four values and
# keeps its own meaning; the two were verified coexisting at runtime (T4).
BOOKING_STATES = [
    ('draft', "مسودة"),
    ('tentative', "حجز مبدئي غير ثابت"),
    ('awaiting', "انتظار العربون وتوقيع العقد"),
    ('confirmed', "مؤكد"),
    ('ready', "جاهز للمناسبة"),
    ('postponed', "مؤجل"),
    ('completed', "مكتمل"),
    ('cancelled', "ملغي"),
]


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    event_type = fields.Selection(
        EVENT_TYPES, string="نوع المناسبة", tracking=True,
        help="Decides which contract is printed (spec §10).")
    guest_count = fields.Integer(
        string="عدد المعازيم", tracking=True,
        help="Always recorded. It is only checked against hall capacity once the overrun "
             "tolerance has been configured (spec §8) — while that rule is pending, "
             "recording a large number blocks nothing.")
    booking_state = fields.Selection(
        BOOKING_STATES, string="حالة الحجز", default='draft', copy=False,
        tracking=True, index=True, required=True)
    internal_note_men = fields.Text(string="ملاحظات داخلية — قاعة الرجال")
    internal_note_women = fields.Text(string="ملاحظات داخلية — قاعة النساء")

    # ------------------------------------------------------------------ helpers
    def _ss_hall_products(self):
        """The physical halls this booking occupies.

        A wedding holds TWO of them — hall 3 and hall 4 — on one order, which is what lets
        every hall be protected, scheduled and counted separately (spec §3.5).
        """
        self.ensure_one()
        return self.order_line.filtered(lambda line: line.is_rental and line.product_id).product_id

    def _ss_envelope(self, hall, extra=timedelta()):
        """The window this booking really occupies the hall for: the event plus the hall's
        own preparation and cleanup time, plus any configured same-day gap.

        Nothing here is invented — prep_time and cleanup_time are the PRD's 4 and 5 hours,
        and `extra` is zero until the client decides PRD §22 item 6 (spec §8).
        """
        self.ensure_one()
        template = hall.product_tmpl_id
        return (
            self.rental_start_date - timedelta(hours=template.prep_time) - extra,
            self.rental_return_date + timedelta(hours=template.cleanup_time) + extra,
        )

    def _ss_is_live_booking(self):
        """A booking that still holds its halls.

        CON-01 blocks against ALL non-cancelled bookings, drafts included: a tentative hold
        on an already-held hall must fail. Proven and intended (spec §12).
        """
        self.ensure_one()
        return (
            self.is_rental_order
            and self.state != 'cancel'
            and self.booking_state != 'cancelled'
            and self.rental_start_date
            and self.rental_return_date
        )

    # ------------------------------------------------------------------- CON-01
    @api.constrains('rental_start_date', 'rental_return_date', 'order_line',
                    'state', 'booking_state')
    def _check_hall_availability(self):
        gap = get_optional_float(self.env, SAME_DAY_GAP_KEY)
        # The gap widens the envelope of the booking being checked, once — not both sides,
        # which would silently require twice the separation the client asked for.
        extra = timedelta(hours=gap) if gap is not None else timedelta()

        for order in self:
            if not order._ss_is_live_booking():
                continue
            for hall in order._ss_hall_products():
                mine_start, mine_end = order._ss_envelope(hall, extra)
                template = hall.product_tmpl_id
                # Coarse pre-filter. The other booking's envelope is widened by the SAME
                # hall's buffers, so this pad can never exclude a real clash.
                pad = timedelta(hours=template.prep_time + template.cleanup_time) + extra
                candidates = self.search([
                    ('id', '!=', order.id or 0),
                    ('is_rental_order', '=', True),
                    ('state', '!=', 'cancel'),
                    ('booking_state', '!=', 'cancelled'),
                    ('order_line.product_id', '=', hall.id),
                    ('rental_start_date', '<', mine_end + pad),
                    ('rental_return_date', '>', mine_start - pad),
                ])
                for other in candidates:
                    if hall not in other._ss_hall_products():
                        continue
                    other_start, other_end = other._ss_envelope(hall)
                    # Half-open interval: one booking may end exactly where the next begins.
                    if mine_start < other_end and other_start < mine_end:
                        raise ValidationError(self.env._(
                            "القاعة «%(hall)s» غير متاحة في هذا الوقت.\n"
                            "يوجد حجز آخر: %(other)s — %(customer)s\n"
                            "من %(other_start)s إلى %(other_end)s "
                            "(شاملاً وقت التجهيز والتنظيف).\n\n"
                            "Hall '%(hall)s' is not available then. It is held by booking "
                            "%(other)s for %(customer)s, whose occupied window including "
                            "preparation and cleanup runs %(other_start)s to %(other_end)s.",
                            hall=hall.display_name,
                            other=other.display_name,
                            customer=other.partner_id.display_name,
                            other_start=fields.Datetime.to_string(other_start),
                            other_end=fields.Datetime.to_string(other_end),
                        ))

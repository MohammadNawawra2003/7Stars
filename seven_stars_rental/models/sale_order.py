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

    # --------------------------------------------------------------- money (§6.1)
    # required_deposit_amount is a TERM. It is the deposit agreed for this booking, and
    # nothing has been received because it has a value. Money received exists only as
    # seven.stars.payment rows; everything below that looks like received money is a stored
    # compute over those rows, so the two can never drift apart.
    required_deposit_amount = fields.Monetary(
        string="العربون المطلوب", tracking=True,
        help="The deposit agreed with the customer — a condition of the booking, not a "
             "payment. Money actually received is recorded in the Payments tab.")
    payment_ids = fields.One2many('seven.stars.payment', 'order_id', string="الدفعات")
    collected_amount = fields.Monetary(
        string="المبلغ المدفوع", compute='_compute_ss_amounts', store=True,
        help="The sum of every payment row. Named collected_amount because sale.order."
             "amount_paid already exists and counts online payment transactions only.")
    outstanding_amount = fields.Monetary(
        string="المبلغ المتبقي", compute='_compute_ss_amounts', store=True)
    price_approved = fields.Boolean(
        string="اعتماد السعر", tracking=True,
        groups='seven_stars_rental.group_ss_manager',
        help="PRD §8/§17. A Python groups= is the only field-level restriction Odoo honours "
             "(spec §3.4) — ir.model.fields.groups is dead.")

    @api.depends('payment_ids.amount', 'amount_total')
    def _compute_ss_amounts(self):
        for order in self:
            collected = sum(order.payment_ids.mapped('amount'))
            order.collected_amount = collected
            order.outstanding_amount = order.amount_total - collected

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

    # ------------------------------------------------------------ CON-03, CON-04
    def _ss_check_deposit_before_confirm(self):
        """CON-03 — a booking is confirmed once enough money has actually arrived.

        The gate asks whether `collected_amount` has reached the agreed deposit. There is no
        "is this row the deposit?" flag and none is needed: a deposit is an ordinary payment
        row, and the question is only ever how much has been received (spec §6.1).

        The authorised management exception is a branch INSIDE the rule, not a later patch.
        The client confirms bookings she takes herself before any money arrives
        («فقط في حالات حجز من طرف سيدة الإدارة فقط», spec §23.3 G3). The waiver is written to
        the chatter, which already records who confirmed and when — no extra field.
        """
        self.ensure_one()
        if self.currency_id.compare_amounts(
                self.collected_amount, self.required_deposit_amount) >= 0:
            return
        if self.env.user.has_group('seven_stars_rental.group_ss_manager'):
            self.message_post(body=self.env._(
                "تم تأكيد الحجز دون استلام العربون المطلوب (%(required)s) — استثناء إداري. "
                "المبلغ المستلم حتى الآن: %(collected)s."
                "<br/>Confirmed without the required deposit under the management exception.",
                required=self.required_deposit_amount,
                collected=self.collected_amount,
            ))
            return
        raise ValidationError(self.env._(
            "لا يمكن تأكيد الحجز قبل استلام العربون المطلوب.\n"
            "العربون المطلوب: %(required)s\nالمبلغ المستلم: %(collected)s\n"
            "سجّل الدفعة في تبويب «الدفعات» ثم أكّد الحجز.\n\n"
            "This booking cannot be confirmed before the agreed deposit has been received "
            "(required %(required)s, received %(collected)s). Record the payment in the "
            "Payments tab first. Management may confirm without it.",
            required=self.required_deposit_amount,
            collected=self.collected_amount,
        ))

    def _ss_check_balance_before_close(self):
        """CON-04 — a booking is not closed while money is still owed."""
        self.ensure_one()
        if not self.currency_id.is_zero(self.outstanding_amount):
            raise ValidationError(self.env._(
                "لا يمكن إغلاق الحجز والحساب غير مصفّر.\n"
                "الإجمالي: %(total)s\nالمدفوع: %(collected)s\nالمتبقي: %(outstanding)s\n\n"
                "This booking still has an outstanding balance of %(outstanding)s and "
                "cannot be closed.",
                total=self.amount_total,
                collected=self.collected_amount,
                outstanding=self.outstanding_amount,
            ))

    # ------------------------------------------------------- the 7 custom buttons
    # Eight states minus `draft`, which is where a booking is created, leaves exactly seven
    # transitions (spec §9.1). Nothing else here is custom: Print, the standard confirm and
    # the chatter are all reused as they are.
    def action_hold_tentative(self):
        """BTN-01 — حجز مبدئي. CON-01 has already refused the hall if it was taken."""
        self.booking_state = 'tentative'
        return True

    def action_await_deposit(self):
        """BTN-02 — انتظار العربون وتوقيع العقد."""
        self.booking_state = 'awaiting'
        return True

    def action_confirm_booking(self):
        """BTN-03 — تأكيد الحجز, guarded by CON-03."""
        for order in self:
            order._ss_check_deposit_before_confirm()
            order.booking_state = 'confirmed'
            if order.state in ('draft', 'sent'):
                order.action_confirm()
        return True

    def action_mark_ready(self):
        """BTN-04 — جاهز للمناسبة. Phase 3 adds the operational-appendix guard."""
        self.booking_state = 'ready'
        return True

    def action_postpone(self):
        """BTN-05 — تأجيل. The notice period is a Phase 4 rule; moving the dates re-runs
        CON-01 by itself, because the constraint watches them."""
        self.booking_state = 'postponed'
        return True

    def action_close_booking(self):
        """BTN-06 — إغلاق الحجز, guarded by CON-04.

        Closing also settles the rental quantities. Rental never leaves `pickup` unless
        quantities move, and "Late Pickup" is permanent while qty_delivered is below the
        ordered quantity (spec §3.2, runtime T5) — so a closed booking that never had its
        quantities set would read as late for ever.
        """
        for order in self:
            order._ss_check_balance_before_close()
            for line in order.order_line.filtered('is_rental'):
                line.qty_delivered = line.product_uom_qty
                line.qty_returned = line.product_uom_qty
            order.booking_state = 'completed'
        return True

    def action_cancel_booking(self):
        """BTN-07 — إلغاء. Booking managers and above (spec §11); the cancellation notice
        rules are Phase 4.

        The view's groups= attribute only hides the button. A method is callable over RPC by
        anyone who can reach the record, so the right to cancel is checked here too.
        """
        if not self.env.su and not self.env.user.has_group(
                'seven_stars_rental.group_ss_booking_manager'):
            raise ValidationError(self.env._(
                "إلغاء الحجز من صلاحية مسؤول الحجوزات أو الإدارة فقط.\n\n"
                "Cancelling a booking is reserved to booking managers and management "
                "(PRD §17)."))
        for order in self:
            order.booking_state = 'cancelled'
            if order.state != 'cancel':
                order.action_cancel()
        return True
